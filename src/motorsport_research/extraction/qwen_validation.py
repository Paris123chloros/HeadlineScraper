"""Literal grounding and conservative label checks; semantic truth requires review."""

import json
import re

from motorsport_research.extraction.articles import date_metadata
from motorsport_research.extraction.qwen_client import InferenceError
from motorsport_research.extraction.relevance import CHAMPIONSHIPS, CUES, TOPICS

NUMBER = r"(?<!\w)[+-]?\d+(?:[.,:/]\d+)*(?:%|\b)"


def passages(article):
    result = []
    for block in article["blocks"]:
        text = block["text"]
        boundaries = (
            [0] + [m.end() for m in re.finditer(r'[.!?][”"\']?\s+(?=[A-Z“"])', text)] + [len(text)]
        )
        for begin, end in zip(boundaries, boundaries[1:], strict=False):
            sentence_begin = begin
            while begin < end:
                part_end = end
                # Bound individual passages by UTF-8 bytes, preserving every character.
                while len(text[begin:part_end].encode()) > 1000:
                    part_end = begin + max(1, (part_end - begin) // 2)
                if part_end < end:
                    space = text.rfind(" ", begin, part_end)
                    if space > begin:
                        part_end = space + 1
                raw = text[begin:part_end]
                value = raw.strip()
                if value:
                    start = block["body_start"] + begin + len(raw) - len(raw.lstrip())
                    result.append(
                        {
                            "id": f"p{len(result):05d}",
                            "text": value,
                            "body_start": start,
                            "body_end": start + len(value),
                            "partial": part_end != end or begin != sentence_begin,
                        }
                    )
                begin = part_end
    return result


def chunks(article, settings):
    parts = passages(article)
    groups = []
    current = []

    def payload(group):
        return json.dumps(
            {"source_passages": [{"passage_id": p["id"], "text": p["text"]} for p in group]},
            ensure_ascii=False,
        )

    for passage in parts:
        if len(payload(current + [passage]).encode()) > settings.qwen_max_input_bytes:
            if not current:
                raise ValueError("Passage exceeds model input budget")
            groups.append({"passages": current, "payload": payload(current)})
            current = []
        current.append(passage)
    if current:
        groups.append({"passages": current, "payload": payload(current)})
    if not groups or len(groups) > settings.qwen_max_chunks:
        raise ValueError("Article exceeds configured chunk budget; nothing was truncated")
    return groups


def source_spans(article, passage):
    spans = []
    for block in article["blocks"]:
        for fragment in block["spans"]:
            start = max(passage["body_start"], fragment["body_start"])
            end = min(passage["body_end"], fragment["body_end"])
            if start >= end:
                continue
            # Map normalized whitespace back to the exact original Unicode positions.
            positions = []
            for match in re.finditer(r"\S+", fragment["quote"]):
                if positions:
                    positions.append(match.start() - 1)
                positions.extend(range(match.start(), match.end()))
            first = positions[start - fragment["body_start"]]
            last = positions[end - fragment["body_start"] - 1] + 1
            quote = fragment["quote"][first:last]
            spans.append({"quote": quote, "start_offset": fragment["start_offset"] + first})
    if not spans:
        raise ValueError("Selected passage has no archived evidence")
    return spans


def validate_output(output, group, article, repo):
    allowed = {p["id"]: p for p in group["passages"]}
    seen = set()
    validated = []
    for claim in output.claims:
        passage = allowed.get(claim.passage_id)
        if passage is None or claim.quote != passage["text"] or claim.passage_id in seen:
            raise InferenceError(
                "invalid_evidence", "Unknown/duplicate passage or fabricated quotation"
            )
        seen.add(claim.passage_id)
        quote = claim.quote
        for name in [*claim.entities, *([claim.asserted_by] if claim.asserted_by else [])]:
            if name not in quote:
                raise InferenceError(
                    "invalid_evidence", "Entity/attribution absent from the quotation"
                )
        for championship in claim.championships:
            if not re.search(CHAMPIONSHIPS[championship], quote, re.I):
                raise InferenceError("invalid_evidence", "Championship absent from quotation")
        if claim.topic == "fia-announcements":
            source = repo._require("sources", article["origin"]["source_id"])
            if source["kind"] != "official" or source["url"].split("/")[2] != "www.fia.com":
                raise InferenceError(
                    "invalid_evidence", "FIA announcement lacks reviewed publisher"
                )
        elif not (
            re.search(TOPICS[claim.topic], quote, re.I)
            or (
                claim.topic == "sport-news"
                and any(re.search(pattern, quote, re.I) for pattern in CHAMPIONSHIPS.values())
            )
        ):
            raise InferenceError("invalid_evidence", "Topic has no literal cue in quotation")
        if claim.assertion_type != "reported":
            if not re.search(CUES[claim.assertion_type], quote, re.I):
                raise InferenceError("invalid_evidence", "Procedural label lacks a published cue")
            if claim.assertion_type in {"finding", "decision"} and re.search(
                r"\b(?:no|not|without|yet|pending)\b", quote, re.I
            ):
                raise InferenceError("invalid_evidence", "Negated/unresolved finding or decision")
            if claim.assertion_type == "investigation" and re.search(
                r"\bno\s+investigation", quote, re.I
            ):
                raise InferenceError("invalid_evidence", "Negated investigation")
        if (
            claim.assertion_type in {"reported", "allegation"}
            and re.search(
                r"\b(?:alleg\w*|rumou?r\w*|unconfirmed|reportedly|could|may)\b", quote, re.I
            )
            and claim.uncertainty != "uncertain"
        ):
            raise InferenceError("invalid_evidence", "Uncertain wording was upgraded to certainty")
        printed_numbers = set(re.findall(NUMBER, quote))
        if any(number not in printed_numbers for number in claim.numbers):
            raise InferenceError(
                "invalid_evidence", "Numeric value is not a complete printed token"
            )
        dates = []
        for date in claim.dates:
            if date.value_raw not in quote:
                raise InferenceError("invalid_evidence", "Date was inferred rather than quoted")
            dates.append(
                {
                    "role": date.role,
                    "value_raw": date.value_raw,
                    "parsed": date_metadata(
                        [{"source": "quoted_passage", "value": date.value_raw}]
                    ),
                }
            )
        entities = [{"mention": name, **repo.resolve_alias(name)} for name in claim.entities]
        attribution = (
            repo.resolve_alias(claim.asserted_by)
            if claim.asserted_by
            else {"status": "unspecified", "candidates": []}
        )
        validated.append(
            {
                **claim.model_dump(mode="json"),
                "evidence": source_spans(article, passage),
                "date_mentions": dates,
                "entity_candidates": entities,
                "attribution_candidates": attribution,
                "partial_passage": passage["partial"],
                "review_required": True,
                "evidence_label": "unassessed",
            }
        )
    return validated
