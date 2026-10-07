"""Formula 1's published result and standings tables."""

import re

from motorsport_research.championships.common import (
    EvidenceText,
    OfficialDataError,
    ParsedOfficial,
    check_scope,
    integer,
    position,
    result_status,
)
from motorsport_research.championships.html_tables import read_tables
from motorsport_research.championships.models import (
    Classification,
    PublishedResult,
    RaceContext,
    StandingsContext,
)


def _driver(value: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"(.+) ([A-Z]{3})", value)
    return (match.group(1), match.group(2)) if match else (value, None)


def _table(content: bytes, expected_headers: list[str]):
    parser = read_tables(content)
    candidates = [
        table
        for table in parser.tables
        if table and [cell["text"] for cell in table[0]] == expected_headers
    ]
    if len(candidates) != 1:
        raise OfficialDataError("Expected exactly one recognized official F1 table")
    table = candidates[0]
    if not all(len(row) == len(expected_headers) for row in table[1:]):
        raise OfficialDataError("F1 table contains an incomplete row")
    return parser.headings, [
        {header: cell["text"] for header, cell in zip(expected_headers, row, strict=True)}
        for row in table[1:]
    ]


def parse_classification(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    if context.session in {"race", "sprint"}:
        headers = ["Pos.", "No.", "Driver", "Team", "Laps", "Time / Retired", "Pts."]
    elif context.session == "qualifying":
        headers = ["Pos.", "No.", "Driver", "Team", "Q1", "Q2", "Q3", "Laps"]
    else:
        headers = ["Pos.", "No.", "Driver", "Team", "Time / Gap", "Laps"]
    headings, values = _table(content, headers)
    text = EvidenceText("\n".join(headings))
    check_scope(context, text.text, url)
    rows = []
    for fields in values:
        name, code = _driver(fields["Driver"])
        if not name or not fields["No."] or not fields["Team"]:
            raise OfficialDataError("F1 row is missing driver, number or team")
        quote = " | ".join(f"{key}: {value}" for key, value in fields.items())
        start = text.append(quote)
        published_time = (
            fields.get("Time / Retired") or fields.get("Time") or fields.get("Time / Gap") or None
        )
        gap = fields.get("Gap") or None
        if published_time and published_time.startswith("+"):
            gap, published_time = published_time, None
        status_raw = fields["Pos."] if not fields["Pos."].isdigit() else None
        if published_time and result_status(published_time) != "unknown":
            status_raw, published_time = published_time, None
        rows.append(
            PublishedResult(
                entry_number=fields["No."],
                position_raw=fields["Pos."],
                overall_position=position(fields["Pos."]),
                drivers=[name],
                driver_code=code,
                team=fields["Team"],
                laps=integer(fields["Laps"], field="laps"),
                time_raw=published_time,
                gap_raw=gap,
                status_raw=status_raw,
                status=result_status(status_raw),
                points_raw=fields.get("Pts.") or None,
                timing={key: fields[key] or None for key in ("Q1", "Q2", "Q3") if key in fields},
                published_fields=fields,
                quote=quote,
                start_offset=start,
            )
        )
    return ParsedOfficial(headings[0], text.text, Classification(context=context, rows=rows))


def parse_standings(content: bytes, url: str, context: StandingsContext) -> ParsedOfficial:
    expected = (
        ["Pos.", "Driver", "Nationality", "Team", "Pts."]
        if context.category == "drivers"
        else ["Pos.", "Team", "Pts."]
    )
    headings, values = _table(content, expected)
    from urllib.parse import urlsplit

    category_path = "team" if context.category == "teams" else "drivers"
    if not urlsplit(url).path.rstrip("/").endswith(
        f"/results/{context.season}/{category_path}"
    ) or context.context_quote not in "\n".join(headings):
        raise OfficialDataError("Standings season/category does not match its source")
    if len(values) != context.expected_entries:
        raise OfficialDataError("Standings entry count differs from the reviewed context")
    text = EvidenceText("\n".join(headings))
    rows = []
    subjects = set()
    for fields in values:
        quote = " | ".join(f"{key}: {value}" for key, value in fields.items())
        subject = _driver(fields["Driver"])[0] if context.category == "drivers" else fields["Team"]
        from decimal import Decimal, InvalidOperation

        if not subject or subject in subjects:
            raise OfficialDataError("Standings subject is empty or duplicated")
        subjects.add(subject)
        try:
            points = Decimal(fields["Pts."])
        except InvalidOperation as error:
            raise OfficialDataError("Standings points are invalid") from error
        if not points.is_finite():
            raise OfficialDataError("Standings points are invalid")
        rows.append(
            {
                "position_raw": fields["Pos."],
                "position": position(fields["Pos."]),
                "subject": subject,
                "points_raw": fields["Pts."],
                "published_fields": fields,
                "quote": quote,
                "start_offset": text.append(quote),
            }
        )
    return ParsedOfficial(
        headings[0],
        text.text,
        payload={
            "record_type": "standings",
            "context": context.model_dump(mode="json"),
            "rows": rows,
            "scoring": "published_only",
        },
    )


def parse_fia_classification(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    """Pinned FIA race PDF layout: preserve full race time and published lap deficits."""
    from motorsport_research.championships.common import source_state
    from motorsport_research.championships.notices import extract_text

    if context.session != "race":
        raise OfficialDataError("FIA PDF adapter currently supports race classifications only")
    text = extract_text(content, "application/pdf")
    check_scope(context, text, url)
    heading = re.search(r"(?:Final|Provisional|Amended)\s+Race\s+Classification", text, re.I)
    if heading is None:
        raise OfficialDataError("FIA PDF has no recognized classification heading")
    state = source_state(heading.group(), "")
    rows = []
    for match in re.finditer(r"(?m)^(\d{1,2}) (\d{1,3}) ([^\n]+)\n ([^\n]+)$", text):
        rank, number, driver, timing_line = match.groups()
        timing = re.fullmatch(r"(.+?) (\d+) (\d+:\d+:\d+\.\d+) (.+)", timing_line)
        if timing is None:
            raise OfficialDataError("Unrecognized FIA entrant/timing row")
        team, laps, race_time, tail = timing.groups()
        end = re.fullmatch(
            r"(?:(.*?) )?(\d+\.\d{3}) (\d+:\d+\.\d+) (\d+)(?: (\d+(?:\.\d+)?))?", tail
        )
        if end is None:
            raise OfficialDataError("Unrecognized FIA fastest-lap/points columns")
        gaps, speed, fastest, on, points = end.groups()
        gap = None
        interval = None
        if gaps:
            gap_match = re.fullmatch(r"(\d+ LAPS?|\d+(?:\.\d+)?) (\d+ LAPS?|\d+(?:\.\d+)?)", gaps)
            if gap_match is None:
                raise OfficialDataError("Unrecognized FIA gap/interval columns")
            gap, interval = gap_match.groups()
        fields = {
            "position": rank,
            "number": number,
            "driver": driver,
            "entrant": team,
            "laps": laps,
            "time": race_time,
            "gap": gap,
            "interval": interval,
            "average_kph": speed,
            "fastest_lap": fastest,
            "fastest_on": on,
            "points": points,
        }
        rows.append(
            PublishedResult(
                entry_number=number,
                position_raw=rank,
                overall_position=int(rank),
                drivers=[driver],
                team=team,
                laps=int(laps),
                time_raw=race_time,
                gap_raw=gap,
                points_raw=points,
                timing={"fastest_lap": fastest, "interval": interval},
                published_fields=fields,
                quote=match.group(),
                start_offset=match.start(),
            )
        )
    return ParsedOfficial(
        heading.group(), text, Classification(context=context, rows=rows, **state)
    )
