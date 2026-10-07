"""Shared parsing safeguards and evidence text assembly."""

from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from motorsport_research.championships.models import Classification, RaceContext

PARSER_VERSION = "official-records:1"


class OfficialDataError(ValueError):
    pass


@dataclass
class ParsedOfficial:
    title: str
    text: str
    classification: Classification | None = None
    payload: dict | None = None


class EvidenceText:
    def __init__(self, heading: str):
        self.text = heading.strip()

    def append(self, quote: str) -> int:
        self.text += "\n"
        start = len(self.text)
        self.text += quote
        return start


def integer(value: str | None, *, field: str) -> int | None:
    if value is None or value.strip() in {"", "-"}:
        return None
    if not value.isdigit():
        raise OfficialDataError(f"Non-integer published {field}")
    return int(value)


def position(value: str) -> int | None:
    if value.isdigit() and int(value) > 0:
        return int(value)
    if value.upper() not in {"NC", "DQ", "DSQ", "DNS", "DNF", "RET", "EX", "-"}:
        raise OfficialDataError("Unrecognized published classification position")
    return None


def result_status(value: str | None) -> str:
    return {
        "classified": "classified",
        "nc": "not_classified",
        "not classified": "not_classified",
        "dnf": "retired",
        "retired": "retired",
        "ret": "retired",
        "dsq": "disqualified",
        "disqualified": "disqualified",
        "dq": "disqualified",
        "dns": "did_not_start",
        "did not start": "did_not_start",
    }.get((value or "").casefold(), "unknown")


def check_scope(context: RaceContext, text: str, url: str) -> None:
    if context.context_quote not in text and context.context_quote not in unquote(url):
        raise OfficialDataError("Reviewed context passage is absent from the document and URL")
    if context.championship == "F1":
        parts = urlsplit(url).path.split("/")
        if "results" in parts:
            index = parts.index("results")
            if int(parts[index + 1]) != context.season:
                raise OfficialDataError("F1 URL season differs from reviewed context")
            expected = {
                "race": "race-result",
                "sprint": "sprint-results",
                "qualifying": "qualifying",
                "practice": "practice",
            }[context.session]
            if expected not in parts:
                raise OfficialDataError("F1 URL session differs from reviewed context")
            if context.session == "practice" and int(parts[-1]) != context.session_number:
                raise OfficialDataError("F1 practice number differs from reviewed context")


def source_state(text: str, url: str) -> dict:
    import re

    for state, pattern in (
        ("amended", r"\bAMENDED\b"),
        ("provisional", r"\bPROVISIONAL\b"),
        ("final", r"\bFINAL\b"),
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return {"state": state, "state_basis": "document_text", "state_quote": match.group(0)}
    filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    for state in ("amended", "provisional", "final"):
        match = re.search(r"(?:^|[ _-])(" + state + r")(?:[._ -]|$)", filename, re.I)
        if match:
            return {"state": state, "state_basis": "document_url", "state_quote": match.group(1)}
    return {"state": "published", "state_basis": "unspecified", "state_quote": None}
