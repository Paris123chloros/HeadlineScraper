"""Official Alkamel semicolon CSV: overall positions, explicit class, full crew."""

import csv
import io
import re
from urllib.parse import unquote

from motorsport_research.championships.common import (
    EvidenceText,
    OfficialDataError,
    ParsedOfficial,
    check_scope,
    integer,
    position,
    result_status,
    source_state,
)
from motorsport_research.championships.models import Classification, PublishedResult, RaceContext

BRANDS = (
    "Aston Martin",
    "Mercedes-AMG",
    "Toyota",
    "Porsche",
    "Ferrari",
    "BMW",
    "Cadillac",
    "Peugeot",
    "Alpine",
    "Genesis",
    "Lexus",
    "Corvette",
    "Ford",
    "McLaren",
)


def parse_classification(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    year = re.search(r"/\d+_(\d{4})/", unquote(url))
    if year and int(year.group(1)) != context.season:
        raise OfficialDataError("WEC archive year differs from reviewed season")
    decoded = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(decoded), delimiter=";")
    required = {
        "POSITION",
        "NUMBER",
        "TEAM",
        "DRIVER_1",
        "DRIVER_2",
        "DRIVER_3",
        "VEHICLE",
        "CLASS",
        "STATUS",
        "LAPS",
        "TOTAL_TIME",
        "GAP_FIRST",
    }
    if (
        not reader.fieldnames
        or not required.issubset(reader.fieldnames)
        or len(reader.fieldnames) != len(set(reader.fieldnames))
    ):
        raise OfficialDataError("Unrecognized or ambiguous Alkamel CSV headers")
    heading = ";".join(reader.fieldnames)
    check_scope(context, heading, url)
    text = EvidenceText(heading)
    rows = []
    for fields in reader:
        if None in fields or any(value is None for value in fields.values()):
            raise OfficialDataError("Alkamel CSV contains a truncated or oversized row")
        fields = {key: value for key, value in fields.items() if key}
        if len(rows) >= 500:
            raise OfficialDataError("Alkamel CSV exceeds 500 entries")
        if context.category_scope and fields["CLASS"] != context.category_scope:
            continue
        drivers = [
            fields[key]
            for key in ("DRIVER_1", "DRIVER_2", "DRIVER_3", "DRIVER_4", "DRIVER_5")
            if fields.get(key)
        ]
        quote = " | ".join(f"{key}: {value}" for key, value in fields.items())
        brand = next((name for name in BRANDS if fields["VEHICLE"].startswith(name + " ")), None)
        rows.append(
            PublishedResult(
                entry_number=fields["NUMBER"],
                position_raw=fields["POSITION"],
                overall_position=position(fields["POSITION"]),
                class_position=integer(fields.get("CLASS_POSITION"), field="class position"),
                category=fields["CLASS"],
                drivers=drivers,
                team=fields["TEAM"],
                manufacturer=brand,
                manufacturer_basis="vehicle_prefix" if brand else "unknown",
                vehicle=fields["VEHICLE"],
                laps=integer(fields["LAPS"], field="laps"),
                time_raw=fields["TOTAL_TIME"] or None,
                gap_raw=fields["GAP_FIRST"] or None,
                status_raw=fields["STATUS"] or None,
                status=result_status(fields["STATUS"]),
                points_raw=fields.get("POINTS") or None,
                timing={
                    key: fields.get(key) or None for key in ("FL_TIME", "FL_LAPNUM", "GAP_PREVIOUS")
                },
                published_fields=fields,
                quote=quote,
                start_offset=text.append(quote),
            )
        )
    state = source_state("", url)
    return ParsedOfficial(
        "Official WEC classification",
        text.text,
        Classification(context=context, rows=rows, **state),
    )


def parse_class_bundle(content: bytes, url: str, context: RaceContext) -> ParsedOfficial:
    """Add published class ranks by matching a class table to the exact timing CSV."""
    import hashlib
    from urllib.parse import urlsplit

    from motorsport_research.championships.html_tables import read_tables
    from motorsport_research.championships.json_data import decode

    bundle = decode(content)
    if bundle.get("format") != "wec-class-bundle:1" or not context.category_scope:
        raise OfficialDataError("WEC class bundle requires an explicit class scope")
    components = bundle["components"]
    if set(components) != {"csv", "classification"}:
        raise OfficialDataError("WEC class bundle requires CSV and class classification components")
    raw = {}
    for role, component in components.items():
        raw[role] = component["content"].encode()
        if hashlib.sha256(raw[role]).hexdigest() != component["sha256"]:
            raise OfficialDataError("WEC class component checksum mismatch")
    for component in components.values():
        parts = urlsplit(component["url"])
        if parts.scheme != "https" or parts.username or parts.password:
            raise OfficialDataError("WEC component URLs require credential-free HTTPS")
    csv_url = components["csv"]["url"]
    html_url = components["classification"]["url"]
    if (
        url != csv_url
        or urlsplit(csv_url).hostname != "fiawec.alkamelsystems.com"
        or urlsplit(html_url).hostname != "www.fiawec.com"
    ):
        raise OfficialDataError("Unrecognized WEC class component publishers")
    base_context = RaceContext.model_validate(context.model_dump() | {"adapter": "wec-csv"})
    base = parse_classification(raw["csv"], csv_url, base_context)
    html = read_tables(raw["classification"])
    headers = [
        "Pos.",
        "Competitors",
        "N°",
        "Team",
        "Laps",
        "Total time",
        "Gap",
        "Interval",
        "Avg. (km/h)",
        "Best lap",
        "On",
    ]
    tables = [
        table for table in html.tables if table and [cell["text"] for cell in table[0]] == headers
    ]
    if len(tables) != 1 or len(tables[0]) - 1 != context.expected_entries:
        raise OfficialDataError("WEC class table is absent, ambiguous or incomplete")
    from motorsport_research.championships.notices import extract_text

    visible = extract_text(raw["classification"], "text/html")
    if context.category_scope.casefold() not in visible.casefold():
        raise OfficialDataError("WEC class is absent from the class table document")
    class_rows = {}
    for cells in tables[0][1:]:
        if len(cells) != len(headers):
            raise OfficialDataError("WEC class table contains a truncated row")
        fields = {key: cell["text"] for key, cell in zip(headers, cells, strict=True)}
        number = fields["N°"].removeprefix("#")
        if number in class_rows:
            raise OfficialDataError("Duplicate WEC class car number")
        class_rows[number] = fields
    text = EvidenceText("WEC class archive\n" + components["csv"]["url"] + "\n" + html_url)
    rows = []
    for row in base.classification.rows:
        fields = class_rows.get(row.entry_number)
        if (
            fields is None
            or row.time_raw is None
            or str(row.laps) != fields["Laps"]
            or row.time_raw.replace("'", ":") != fields["Total time"]
        ):
            raise OfficialDataError("WEC class table and CSV disagree on car, laps or time")
        passage = (
            row.quote
            + "\nClass table: "
            + " | ".join(f"{key}: {value}" for key, value in fields.items())
        )
        values = row.model_dump() | {
            "class_position": position(fields["Pos."]),
            "quote": passage,
            "start_offset": text.append(passage),
            "published_fields": row.published_fields | {"class_position": fields["Pos."]},
        }
        rows.append(PublishedResult.model_validate(values))
    return ParsedOfficial(
        "Official WEC class classification",
        text.text,
        Classification(
            context=context,
            rows=rows,
            state=base.classification.state,
            state_basis=base.classification.state_basis,
            state_quote=base.classification.state_quote,
        ),
    )
