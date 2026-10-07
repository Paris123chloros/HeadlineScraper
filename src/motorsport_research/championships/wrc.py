"""Join archived official public API components without dropping their original bytes."""

import hashlib
from datetime import date
from urllib.parse import parse_qs, urlsplit

from motorsport_research.championships.common import (
    EvidenceText,
    OfficialDataError,
    ParsedOfficial,
    position,
)
from motorsport_research.championships.json_data import decode, fields, quote
from motorsport_research.championships.models import Classification, PublishedResult, RaceContext

API = "https://p-p.redbull.com/rb-wrccom-lintegration-yv-prod/api/events/"


def parse_classification(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    bundle = decode(content)
    if bundle.get("format") != "wrc-public-api:1":
        raise OfficialDataError("WRC requires an archive of event, entries and results components")
    components = bundle["components"]
    values, urls = {}, {}
    for key, component in components.items():
        raw = component["content"].encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != component["sha256"]:
            raise OfficialDataError("WRC component checksum mismatch")
        if not component["url"].startswith(API):
            raise OfficialDataError("Unrecognized WRC component publisher")
        urls[key] = component["url"]
        values[key] = decode(raw)
    required = {"event", "entries", "results"} | (
        {"stages"} if context.session == "stage" else set()
    )
    if not required.issubset(values) or set(values) - required - {"retirements"}:
        raise OfficialDataError("Incomplete or unrecognized WRC component roles")
    event = values["event"]
    event_id = event["eventId"]
    base = API + str(event_id)
    if (
        url != base + ".json"
        or urls["event"] != base + ".json"
        or context.context_quote != event["name"]
    ):
        raise OfficialDataError("WRC event identity differs from reviewed context")
    if date.fromisoformat(event["startDate"]).year != context.season:
        raise OfficialDataError("WRC season differs from event date")
    rallies = [rally for rally in event["rallies"] if rally["isMain"]]
    if len(rallies) != 1:
        raise OfficialDataError("Ambiguous WRC main rally identity")
    rally_id = rallies[0]["rallyId"]
    if urls["entries"] != f"{base}/rallies/{rally_id}/entries.json":
        raise OfficialDataError("WRC entries refer to a different rally")
    heading = {"event": event, "component_urls": urls}
    if context.session == "stage":
        if urls["stages"] != base + "/stages.json":
            raise OfficialDataError("WRC stages refer to a different event")
        stages = [stage for stage in values["stages"] if stage["number"] == context.session_number]
        if len(stages) != 1 or stages[0]["status"] not in {"Completed", "Interrupted"}:
            raise OfficialDataError("Expected exactly one completed/interrupted WRC stage")
        stage = stages[0]
        path = f"{base}/stages/{stage['stageId']}/stagetimes.json"
        parts = urlsplit(urls["results"])
        if parts.scheme + "://" + parts.netloc + parts.path != path or parse_qs(parts.query) != {
            "rallyId": [str(rally_id)]
        }:
            raise OfficialDataError(
                "Stage results must be stage times, not cumulative rally results"
            )
        heading["stage"] = stage
        time_key = "elapsedDuration"
    else:
        if urls["results"] != f"{base}/rallies/{rally_id}/results.json":
            raise OfficialDataError("WRC classification refers to a different rally")
        time_key = "totalTime"
    if "retirements" in values and urls["retirements"] != base + "/retirements.json":
        raise OfficialDataError("WRC retirements refer to a different event")
    entries = {}
    for entry in values["entries"]:
        if entry["eventId"] != event_id or entry["entryId"] in entries:
            raise OfficialDataError("Duplicate or mismatched WRC entry identity")
        entries[entry["entryId"]] = entry
    text = EvidenceText(quote(heading))
    rows = []
    for result in values["results"]:
        entry = entries.get(result["entryId"])
        if entry is None:
            raise OfficialDataError("WRC result lacks a matching entry/crew")
        if context.category_scope and entry["group"]["name"] != context.category_scope:
            continue
        retirements = [
            retirement
            for retirement in values.get("retirements", [])
            if retirement["entryId"] == entry["entryId"]
        ]
        restart = (
            "restarted"
            if context.session == "rally"
            and any(item["status"] == "Rejoined" for item in retirements)
            else "unknown"
        )
        evidence = {"entry": entry, "result": result, "retirement_notices": retirements}
        passage = quote(evidence)
        raw = result.get("position")
        pos = str(raw) if raw is not None else "-"
        rows.append(
            PublishedResult(
                entry_number=entry["identifier"],
                position_raw=pos,
                overall_position=position(pos),
                category=entry["group"]["name"],
                drivers=[entry["driver"]["fullName"]],
                co_driver=entry["codriver"]["fullName"],
                driver_code=entry["driver"].get("code"),
                team=entry["entrant"]["name"] if entry.get("entrant") else None,
                manufacturer=entry["manufacturer"]["name"] if entry.get("manufacturer") else None,
                manufacturer_basis="publisher_field" if entry.get("manufacturer") else "unknown",
                vehicle=entry["vehicleModel"],
                time_raw=result.get(time_key),
                gap_raw=result.get("diffFirst"),
                status_raw=result.get("status"),
                restart_status=restart,
                timing={
                    key: str(result[key]) if result.get(key) is not None else None
                    for key in (
                        "penaltyTime",
                        "penaltyTimeMs",
                        "diffFirstMs",
                        "totalTimeMs",
                        "elapsedDurationMs",
                    )
                },
                published_fields={**fields(result), "entry_status": entry.get("status")},
                quote=passage,
                start_offset=text.append(passage),
            )
        )
    # API result position is not a signed FIA classification or a retirement finding.
    return ParsedOfficial(event["name"], text.text, Classification(context=context, rows=rows))
