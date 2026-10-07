"""DTM's public Wige API: select the published session, preserve opaque status codes."""

from datetime import date

from motorsport_research.championships.common import (
    EvidenceText,
    OfficialDataError,
    ParsedOfficial,
    integer,
    position,
    result_status,
    source_state,
)
from motorsport_research.championships.json_data import decode, fields, quote
from motorsport_research.championships.models import Classification, PublishedResult, RaceContext
from motorsport_research.championships.wec import BRANDS


def parse_classification(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    data = decode(content)
    if not isinstance(data, dict) or not isinstance(data.get("wigeResultses"), list):
        raise OfficialDataError("Unrecognized DTM API response")
    expected_name = {
        "race": "Race",
        "qualifying": "Qualifying",
        "practice": "Free Practice",
        "warmup": "Warm Up",
    }[context.session] + f" {context.session_number}"
    candidates = []
    for event in data["wigeResultses"]:
        if event["raceSeries"] != "DTM" or event["wigeName"] != context.context_quote:
            continue
        if date.fromisoformat(event["startDate"]).year != context.season:
            continue
        document = decode(event["jsonText"])
        sessions = [
            item
            for item in document["sessions"]
            if str(item["sessionid"]) == str(document["sessionid"])
        ]
        if len(sessions) != 1:
            raise OfficialDataError("Ambiguous DTM publisher session identity")
        if sessions[0]["name"] == expected_name:
            candidates.append((event, document, sessions[0]))
    if len(candidates) != 1:
        raise OfficialDataError("Expected exactly one DTM meeting/session result")
    event, document, session = candidates[0]
    header = {
        "meeting": event["wigeName"],
        "start_date": event["startDate"],
        "publisher_event_id": event["wigeEventId"],
        "session": session,
        "provision": document.get("provision"),
        "revisedmark": document.get("revisedmark"),
    }
    text = EvidenceText(quote(header))
    rows = []
    for row in document["result"]:
        values = fields(row)
        published_position = values.get("position") or values.get("status") or "-"
        brand = next(
            (
                brand
                for brand in BRANDS + ("Audi", "Lamborghini")
                if values["car"] == brand or values["car"].startswith(brand + " ")
            ),
            None,
        )
        passage = quote(row)
        rows.append(
            PublishedResult(
                entry_number=values["number"],
                position_raw=published_position,
                overall_position=position(published_position),
                drivers=[values["name"]],
                team=values["team"],
                manufacturer=brand,
                manufacturer_basis="vehicle_prefix" if brand else "unknown",
                vehicle=values["car"],
                laps=integer(values["laps"], field="laps"),
                time_raw=values["time"] or None,
                gap_raw=values["gap"] or None,
                status_raw=values["status"] or None,
                status=result_status(values["status"]),
                points_raw=values.get("racepoints") or values.get("sessionpoints") or None,
                timing={
                    key: values.get(key)
                    for key in (
                        "fastestlap",
                        "int",
                        "qualifyingpoints",
                        "totalpoints",
                        "fastestlappoints",
                    )
                },
                published_fields=values,
                quote=passage,
                start_offset=text.append(passage),
            )
        )
    # A revision marker alone does not tell us whether a result is final or amended.
    state = source_state(document.get("provision") or "", "")
    return ParsedOfficial(
        expected_name, text.text, Classification(context=context, rows=rows, **state)
    )
