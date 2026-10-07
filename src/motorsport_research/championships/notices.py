"""Review-led FIA notice extraction. Quotes establish assertions, never blanket truth."""

import re
import subprocess
import sys
from html.parser import HTMLParser

from motorsport_research.championships.common import OfficialDataError, ParsedOfficial
from motorsport_research.championships.models import NoticeContext


class TextReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "svg"}:
            self.ignored += 1
        if not self.ignored and tag in {"p", "div", "br", "h1", "h2", "li", "time"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "svg"} and self.ignored:
            self.ignored -= 1
        if not self.ignored and tag in {"p", "div", "h1", "h2", "li", "time"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)


def extract_text(content: bytes, media_type: str) -> str:
    if media_type == "application/pdf":
        try:
            result = subprocess.run(
                [sys.executable, "-m", "motorsport_research.championships.pdf_text"],
                input=content,
                capture_output=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise OfficialDataError("PDF extraction exceeded 15 seconds") from error
        if result.returncode:
            raise OfficialDataError("PDF extraction failed or exceeded its page/memory/text limits")
        return result.stdout.decode("utf-8")
    if media_type == "text/html":
        reader = TextReader()
        reader.feed(content.decode("utf-8-sig"))
        reader.close()
        return "\n".join(
            " ".join(line.split()) for line in "".join(reader.parts).splitlines() if line.strip()
        )
    if media_type == "text/plain":
        return content.decode("utf-8-sig")
    raise OfficialDataError("Unsupported FIA notice media type")


def selected(text: str, quote: str, start: int | None = None) -> int:
    if start is None:
        start = text.find(quote)
        if start >= 0 and text.find(quote, start + 1) >= 0:
            raise OfficialDataError("Notice quote is ambiguous; provide its start_offset")
    if start < 0 or text[start : start + len(quote)] != quote:
        raise OfficialDataError("Notice quote is absent from the archived document text")
    return start


def validate_date(value, passage: str):
    # Only explicit day/month/year dates are supported. A year alone is not January 1.
    forms = {
        value.isoformat(),
        value.strftime("%d.%m.%Y"),
        value.strftime("%d/%m/%Y"),
        f"{value.day} {value.strftime('%B')} {value.year}",
        value.strftime("%d %B %Y"),
    }
    if not any(
        re.search(r"(?<!\d)" + re.escape(form) + r"(?!\d)", passage, re.I) for form in forms
    ):
        raise OfficialDataError("Reviewed date is not explicitly published in its evidence passage")


def parse_notice(content: bytes, media_type: str, context: NoticeContext) -> ParsedOfficial:
    text = extract_text(content, media_type)
    selected(text, context.title_quote, context.title_start_offset)
    rows = []
    for role, selection in (
        ("statement", context.statement),
        ("sanction", context.sanction),
        ("procedural_status", context.procedural_status_evidence),
    ):
        if selection is not None:
            rows.append(
                {
                    "role": role,
                    "quote": selection.quote,
                    "start_offset": selected(text, selection.quote, selection.start_offset),
                }
            )
    for field in ("effective_date", "published_date"):
        value, passage = getattr(context, field), getattr(context, field + "_quote")
        if value is not None:
            start = selected(text, passage)
            validate_date(value, passage)
            rows.append({"role": field, "quote": passage, "start_offset": start})
    payload = {
        "record_type": context.kind,
        "context": context.model_dump(mode="json"),
        "rows": rows,
        "interpretation": "human_reviewed_context",
        "classification_effect": "not_applied",
    }
    return ParsedOfficial(context.title_quote, text, payload=payload)
