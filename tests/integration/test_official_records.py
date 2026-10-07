"""Official captured records, and explicitly synthetic amendment/procedure cases."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from motorsport_research.championships.common import OfficialDataError
from motorsport_research.championships.service import (
    CONTEXT,
    OfficialService,
    parse,
    read_manifest,
)
from motorsport_research.cli import main
from motorsport_research.storage.database import connect, initialize, migrations
from motorsport_research.storage.models import DocumentInput, SourceInput
from motorsport_research.storage.repository import Repository, open_repository

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/official"
MANIFESTS = sorted(FIXTURES.glob("*.manifest.json"))


@pytest.fixture
def data(tmp_path):
    initialize(tmp_path)
    return tmp_path


def load(name):
    return read_manifest(FIXTURES / (name + ".manifest.json"))


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: path.stem)
def test_reviewed_archives_replay_and_every_row_has_verified_evidence(data, manifest_path):
    manifest, raw = read_manifest(manifest_path)
    service = OfficialService(data)
    first = service.import_manifest(manifest_path)
    second = service.import_manifest(manifest_path)
    assert first["record"]["version_id"] == second["record"]["version_id"]
    assert first["claim_ids"] == second["claim_ids"]
    assert not second["record"]["created"]
    with open_repository(data, read_only=True) as repo:
        history = repo.record_history(first["record"]["record_id"])
        assert len(history) == 1
        version = history[0]
        assert version["payload"]["provenance"]["kind"] == manifest.provenance
        doc = repo._require("document_versions", version["document_version_id"])
        assert repo.blobs.read(doc["content_hash"]) == raw
        for row in version["payload"]["rows"]:
            claim = repo.trace_claim(row["claim_id"])
            evidence = claim["evidence"][0]
            assert evidence["source_kind"] == manifest.source.kind
            assert evidence["canonical_url"] == str(manifest.url)
            assert (
                doc["extracted_text"][row["start_offset"] : row["start_offset"] + len(row["quote"])]
                == row["quote"]
            )
            assert claim["assessment"]["label"] == "unassessed"
            assert claim["extraction_runs"][0]["model_tag"] is None
        assert repo.stats()["counts"]["official_ingestions"] == 2


def parsed(name, **changes):
    manifest, raw = load(name)
    context = CONTEXT.validate_python(manifest.context.model_dump(mode="json") | changes)
    return parse(
        raw,
        str(manifest.url),
        manifest.media_type,
        context,
        manifest.source.kind,
        manifest.provenance,
    )


def test_complete_f1_weekend_and_independent_signed_classification():
    expected = {
        "f1-practice1": ("3", "Daniel Ricciardo", "1:32.869"),
        "f1-practice2": ("44", "Lewis Hamilton", "1:30.374"),
        "f1-practice3": ("55", "Carlos Sainz", "1:30.824"),
        "f1-qualifying": ("1", "Max Verstappen", None),
        "f1-race": ("1", "Max Verstappen", "1:31:44.742"),
    }
    for name, (number, driver, time) in expected.items():
        rows = parsed(name).classification.rows
        assert len(rows) == 20
        assert (rows[0].entry_number, rows[0].drivers[0], rows[0].time_raw) == (
            number,
            driver,
            time,
        )
    html = parsed("f1-race").classification
    pdf = parsed("fia-f1-final").classification
    assert pdf.state == "final" and html.state == "published"
    assert [(row.entry_number, row.overall_position, row.laps) for row in pdf.rows] == [
        (row.entry_number, row.overall_position, row.laps) for row in html.rows
    ]
    assert [row.points_raw for row in pdf.rows[:10]] == [
        "26",
        "18",
        "15",
        "12",
        "10",
        "8",
        "6",
        "4",
        "2",
        "1",
    ]
    assert all(row.points_raw is None for row in pdf.rows[10:])
    assert pdf.rows[10].gap_raw == "1 LAP"
    assert html.rows[19].gap_raw == "+2 laps"
    assert parsed("f1-qualifying").classification.rows[0].timing == {
        "Q1": "1:30.031",
        "Q2": "1:29.374",
        "Q3": "1:29.179",
    }


def test_wec_full_crew_class_scopes_and_published_values():
    overall = parsed("wec-overall").classification
    hypercar = parsed("wec-hypercar").classification
    gt3 = parsed("wec-lmgt3").classification
    assert overall.state == "final" and overall.state_basis == "document_url"
    assert len(overall.rows) == 35 and len(hypercar.rows) == 17 and len(gt3.rows) == 18
    assert {row.entry_number for row in hypercar.rows}.isdisjoint(
        row.entry_number for row in gt3.rows
    )
    assert hypercar.context.record_key != gt3.context.record_key
    first = overall.rows[0]
    assert first.entry_number == "8" and first.team == "Toyota Racing"
    assert first.drivers == ["Sébastien BUEMI", "Brendon HARTLEY", "Ryo HIRAKAWA"]
    assert first.time_raw == "6:01'01.299" and first.laps == 203
    assert first.manufacturer == "Toyota" and first.manufacturer_basis == "vehicle_prefix"
    # This CSV supplies overall positions, not class ranks. Never manufacture a rank.
    assert all(row.class_position is None for row in overall.rows)
    assert {row.category for row in overall.rows} == {"HYPERCAR", "LMGT3"}
    assert any(row.gap_raw and "Lap" in row.gap_raw for row in overall.rows)
    assert all(row.points_raw is None for row in overall.rows)


def test_wrc_rally_stage_crew_and_restarts_are_distinct():
    rally = parsed("wrc-rally").classification
    stage = parsed("wrc-stage17").classification
    assert len(rally.rows) == 48 and len(stage.rows) == 56
    assert rally.context.record_key != stage.context.record_key
    assert rally.rows[0].drivers == ["Oliver SOLBERG"]
    assert rally.rows[0].co_driver == "Elliott EDMONDSON"
    assert rally.rows[0].time_raw == "PT4H24M59S"
    assert stage.rows[0].drivers == ["Elfyn EVANS"]
    assert stage.rows[0].time_raw == "00:20:06.7490000"
    assert any(row.restart_status == "restarted" for row in rally.rows)
    assert all(row.restart_status == "unknown" for row in stage.rows)
    assert all(row.co_driver and row.category for row in rally.rows + stage.rows)
    assert all(row.points_raw is None for row in rally.rows)


def test_dtm_complete_weekend_published_points_and_disqualification():
    race1, race2 = parsed("dtm-race1").classification, parsed("dtm-race2").classification
    assert race1.context.record_key != race2.context.record_key
    assert race1.state == race2.state == "provisional"
    assert race1.rows[0].drivers == ["PREINING Thomas"] and race1.rows[0].points_raw == "25"
    assert race1.rows[0].timing["totalpoints"] == "26"
    assert race2.rows[0].drivers == ["ENGEL Maro"] and race2.rows[0].points_raw == "25"
    assert race1.rows[-1].status == "disqualified" and race1.rows[-1].overall_position is None
    assert race1.rows[-1].laps is None
    assert race2.rows[-1].status == "retired" and race2.rows[-1].gap_raw == "6L"
    for name in (
        "dtm-practice1",
        "dtm-practice2",
        "dtm-practice3",
        "dtm-qualifying1",
        "dtm-qualifying2",
    ):
        assert len(parsed(name).classification.rows) == 21


def test_official_standings_have_no_recomputed_scores():
    payload = parsed("f1-standings").payload
    assert payload["scoring"] == "published_only"
    assert len(payload["rows"]) == 24
    assert payload["rows"][0]["subject"] == "Max Verstappen"
    assert payload["rows"][0]["points_raw"] == "437"


@pytest.mark.parametrize(
    "name,changes",
    [
        ("f1-race", {"season": 2025}),
        ("f1-practice1", {"session_number": 2}),
        ("wec-overall", {"season": 2025}),
        ("wrc-rally", {"season": 2025}),
        ("dtm-race1", {"season": 2025}),
        ("wec-overall", {"expected_entries": 34}),
    ],
)
def test_wrong_scope_or_entry_count_is_rejected(name, changes):
    with pytest.raises((OfficialDataError, ValidationError)):
        parsed(name, **changes)


def test_failure_audit_is_atomic_and_official_trust_is_not_inherited(data, tmp_path):
    manifest, raw = load("f1-race")
    path = tmp_path / "bad.manifest.json"
    (tmp_path / "bad.html").write_bytes(raw.replace(b"<table", b"<badtable"))
    invalid = manifest.model_dump(mode="json") | {
        "file": "bad.html",
        "sha256": hashlib.sha256((tmp_path / "bad.html").read_bytes()).hexdigest(),
    }
    path.write_text(json.dumps(invalid))
    with pytest.raises(OfficialDataError, match="failed ingestion"):
        OfficialService(data).import_manifest(path)
    with open_repository(data, read_only=True) as repo:
        assert repo.stats()["counts"]["documents"] == repo.stats()["counts"]["records"] == 0
    assert OfficialService(data).status()[0]["outcome"] == "failed"
    with pytest.raises(OfficialDataError, match="official HTTPS publisher"):
        parse(
            raw, str(manifest.url), manifest.media_type, manifest.context, "independent", "captured"
        )


def synthetic_classification(tmp_path, filename, time):
    raw = (
        "POSITION;NUMBER;TEAM;DRIVER_1;DRIVER_2;DRIVER_3;VEHICLE;CLASS;STATUS;LAPS;TOTAL_TIME;GAP_FIRST;CLASS_POSITION\n"
        "1;8;Fictional Team;Fictional Driver One;Fictional Driver Two;"
        f";Unknown Car;HYPERCAR;Classified;10;{time};;1\n"
    ).encode()
    (tmp_path / filename).write_bytes(raw)
    m, _ = load("wec-overall")
    manifest = m.model_dump(mode="json") | {
        "provenance": "synthetic",
        "source": {
            "key": "synthetic-classification",
            "name": "Synthetic classification",
            "url": "https://example.invalid/",
            "kind": "unknown",
        },
        "file": filename,
        "url": "https://example.invalid/" + filename,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    manifest["context"].update(
        season=2026,
        meeting_key="fictional",
        meeting_name="Fictional meeting",
        expected_entries=1,
        context_quote="POSITION;NUMBER",
    )
    path = tmp_path / (filename + ".manifest.json")
    path.write_text(json.dumps(manifest))
    return path


def test_amendments_reversions_and_penalty_revision_do_not_rewrite_results(data, tmp_path):
    service = OfficialService(data)
    final = synthetic_classification(tmp_path, "Race_Final.csv", "1:00:00.000")
    amended = synthetic_classification(tmp_path, "Race_Amended.csv", "1:00:05.000")
    a = service.import_manifest(final)
    b = service.import_manifest(amended)
    c = service.import_manifest(final)
    assert [item["record"]["revision"] for item in (a, b, c)] == [1, 2, 3]
    penalty = service.import_manifest(FIXTURES / "fia-penalty-synthetic.manifest.json")
    overturned = service.import_manifest(FIXTURES / "fia-overturned-synthetic.manifest.json")
    assert penalty["record"]["record_id"] == overturned["record"]["record_id"]
    with open_repository(data, read_only=True) as repo:
        history = repo.record_history(a["record"]["record_id"])
        assert [v["payload"]["state"] for v in history] == ["final", "amended", "final"]
        assert [v["payload"]["rows"][0]["time_raw"] for v in history] == [
            "1:00:00.000",
            "1:00:05.000",
            "1:00:00.000",
        ]
        assert history[0]["payload"]["rows"][0]["class_position"] == 1
        assert history[0]["payload"]["rows"][0]["manufacturer"] is None
        decisions = repo.record_history(penalty["record"]["record_id"])
        assert [v["payload"]["context"]["procedural_status"] for v in decisions] == [
            "imposed",
            "overturned",
        ]
        assert all(v["payload"]["classification_effect"] == "not_applied" for v in decisions)
        repo.trace_claim(history[0]["claim_ids"][0])


def test_rule_dates_and_investigation_are_evidence_bound(data):
    service = OfficialService(data)
    rule = service.import_manifest(FIXTURES / "fia-rule-synthetic.manifest.json")
    investigation = service.import_manifest(FIXTURES / "fia-investigation-synthetic.manifest.json")
    with open_repository(data, read_only=True) as repo:
        record = repo.record_history(rule["record"]["record_id"])[0]
        assert record["payload"]["context"]["effective_date"] == "2027-01-01"
        assert record["effective_at"] is None  # Day precision does not invent a UTC timestamp.
        assert all(
            repo.trace_claim(claim)["assertion_type"] == "investigation"
            for claim in investigation["claim_ids"]
        )
    manifest, raw = load("fia-rule-synthetic")
    context = CONTEXT.validate_python(
        manifest.context.model_dump(mode="json") | {"effective_date": "2026-01-01"}
    )
    with pytest.raises(OfficialDataError, match="not explicitly published"):
        parse(raw, str(manifest.url), manifest.media_type, context, "unknown", "synthetic")
    manifest, raw = load("fia-investigation-synthetic")
    with pytest.raises(ValidationError, match="cannot assert a finding"):
        CONTEXT.validate_python(
            manifest.context.model_dump(mode="json") | {"procedural_status": "imposed"}
        )
    with pytest.raises(ValidationError, match="cannot impose a sanction"):
        CONTEXT.validate_python(
            manifest.context.model_dump(mode="json") | {"sanction": {"quote": "Allegation"}}
        )


def test_wrc_bundle_checksums_joins_and_stage_semantics():
    m, raw = load("wrc-stage17")
    bundle = json.loads(raw)
    bundle["components"]["results"]["url"] = bundle["components"]["results"]["url"].replace(
        "stagetimes", "results"
    )
    with pytest.raises(OfficialDataError, match="not cumulative"):
        parse(
            json.dumps(bundle).encode(), str(m.url), m.media_type, m.context, "official", "captured"
        )
    bundle["components"]["entries"]["content"] = "[]"
    with pytest.raises(OfficialDataError, match="checksum mismatch"):
        parse(
            json.dumps(bundle).encode(), str(m.url), m.media_type, m.context, "official", "captured"
        )


def test_collected_wrc_components_and_single_document_normalization(data, monkeypatch, capsys):
    m, raw = load("wrc-rally")
    components = json.loads(raw)["components"]
    ids = {}
    with open_repository(data) as repo:
        source = repo.register_source(m.source)
        for role, component in components.items():
            receipt = repo.import_document(
                source,
                DocumentInput(
                    url=component["url"],
                    content=component["content"].encode(),
                    extracted_text=component["content"],
                    title=role,
                    parser_version="collection:2",
                    media_type="application/json",
                ),
            )
            ids[role] = receipt["version_id"]
    receipt = OfficialService(data).bundle_wrc(ids, m.context)
    assert len(receipt["claim_ids"]) == 48
    monkeypatch.setenv("DATA_DIR", str(data))
    context_path, components_path = data / "context.json", data / "components.json"
    context_path.write_text(m.context.model_dump_json())
    components_path.write_text(json.dumps(ids))
    assert (
        main(["bundle-wrc", "--context", str(context_path), "--components", str(components_path)])
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["record"]["created"]
    assert not OfficialService(data).bundle_wrc(ids, m.context)["record"]["created"]
    m, raw = load("f1-race")
    with open_repository(data) as repo:
        source = repo.register_source(m.source)
        origin = repo.import_document(
            source,
            DocumentInput(
                url=m.url,
                content=raw,
                extracted_text="Collected page",
                title="Results",
                parser_version="collection:2",
                media_type="text/html",
            ),
        )
    normalized = OfficialService(data).normalize(origin["version_id"], m.context)
    assert normalized["document"]["version_id"] != origin["version_id"]
    context_path.write_text(m.context.model_dump_json(), encoding="utf-8-sig")
    assert main(["normalize-official", origin["version_id"], "--context", str(context_path)]) == 0
    assert not json.loads(capsys.readouterr().out)["record"]["created"]
    assert not OfficialService(data).normalize(origin["version_id"], m.context)["record"]["created"]
    assert OfficialService(data).status()[0]["origin_document_version_id"] == origin["version_id"]


def test_upgrade_preserves_previous_storage_and_cli_imports(tmp_path, monkeypatch, capsys):
    initialize(tmp_path, steps=migrations()[:-1])
    connection = connect(tmp_path)
    try:
        repo = Repository(connection, tmp_path)
        source_id = repo.register_source(
            SourceInput(
                key="before-upgrade", name="Previous evidence", url="https://example.invalid/"
            )
        )
        old = repo.import_document(
            source_id,
            DocumentInput(
                url="https://example.invalid/old",
                content=b"Preserved evidence",
                extracted_text="Preserved evidence",
                title="Existing evidence",
                parser_version="fixture:1",
            ),
        )
    finally:
        connection.close()
    # This is the complete previous schema; the additive migration creates the audit only.
    assert initialize(tmp_path) == len(migrations())
    with open_repository(tmp_path, read_only=True) as repo:
        saved = repo._require("document_versions", old["version_id"])
        assert repo.blobs.read(saved["content_hash"]) == b"Preserved evidence"
        assert saved["extracted_text"] == "Preserved evidence"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["import-official", str(FIXTURES / "dtm-race1.manifest.json")]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert main(["record-history", receipt["record"]["record_id"]]) == 0
    assert len(json.loads(capsys.readouterr().out)[0]["payload"]["rows"]) == 21
    assert main(["official-status"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["outcome"] == "success"


def test_bad_pdf_fails_in_bounded_worker():
    from motorsport_research.championships.notices import extract_text

    with pytest.raises(OfficialDataError, match="PDF extraction failed"):
        extract_text(b"%PDF-1.7\nnot a document", "application/pdf")


def test_wec_class_table_adds_published_ranks_and_refuses_a_different_race(
    data, monkeypatch, capsys
):
    result = parsed("wec-class-hypercar").classification
    assert len(result.rows) == 17
    assert [row.class_position for row in result.rows] == list(range(1, 18))
    # Publisher table ranks include non-classified/retired rows; retain their CSV statuses too.
    assert result.rows[15].status == "not_classified"
    assert result.rows[16].status == "retired"
    manifest, raw = load("wec-class-hypercar")
    bundle = json.loads(raw)
    component = bundle["components"]["classification"]
    component["content"] = component["content"].replace("6:01:01.299", "6:01:02.299")
    component["sha256"] = hashlib.sha256(component["content"].encode()).hexdigest()
    with pytest.raises(OfficialDataError, match="disagree"):
        parse(
            json.dumps(bundle).encode(),
            str(manifest.url),
            manifest.media_type,
            manifest.context,
            "official",
            "captured",
        )
    ids = {}
    with open_repository(data) as repo:
        for role, component in json.loads(raw)["components"].items():
            source = repo.register_source(
                SourceInput(key=role, name=role, url=component["url"], kind="official")
            )
            doc = repo.import_document(
                source,
                DocumentInput(
                    url=component["url"],
                    content=component["content"].encode(),
                    extracted_text="Collected component",
                    title=role,
                    parser_version="collection:2",
                    media_type="text/html" if role == "classification" else "text/csv",
                ),
            )
            ids[role] = doc["version_id"]
    receipt = OfficialService(data).bundle_wec(ids, manifest.context)
    assert len(receipt["claim_ids"]) == 17
    monkeypatch.setenv("DATA_DIR", str(data))
    context_path, components_path = data / "context.json", data / "components.json"
    context_path.write_text(manifest.context.model_dump_json())
    components_path.write_text(json.dumps(ids))
    assert (
        main(["bundle-wec", "--context", str(context_path), "--components", str(components_path)])
        == 0
    )
    assert not json.loads(capsys.readouterr().out)["record"]["created"]
    assert not OfficialService(data).bundle_wec(ids, manifest.context)["record"]["created"]


@pytest.mark.parametrize(
    "media,content,expected",
    [
        ("application/json", b'{"results":[]}', "success"),
        ("text/csv", b"position;number\n1;8\n", "success"),
        ("application/json", b'{"results":1,"results":2}', "parser_failure"),
        ("application/json", b'{"points":NaN}', "parser_failure"),
    ],
)
def test_collection_archives_structured_data_without_asserting_race_facts(media, content, expected):
    from motorsport_research.sources.parsers import CollectionError, parse_document

    if expected == "success":
        result = parse_document(content, media, "utf-8", "http", "https://example.invalid/results")
        assert result.text == content.decode()
        assert "normalize" in result.warnings[0]
    else:
        with pytest.raises(CollectionError) as error:
            parse_document(content, media, "utf-8", "http", "https://example.invalid/results")
        assert error.value.outcome == expected


def test_every_published_reference_field_for_all_championships():
    references = json.loads((FIXTURES / "reference-results.json").read_text(encoding="utf-8"))
    assert set(references) == {
        "f1-race",
        "f1-qualifying",
        "f1-practice1",
        "f1-practice2",
        "f1-practice3",
        "wec-overall",
        "wec-hypercar",
        "wec-lmgt3",
        "wrc-rally",
        "wrc-stage17",
        "dtm-race1",
        "dtm-race2",
        "dtm-qualifying1",
        "dtm-qualifying2",
        "dtm-practice1",
        "dtm-practice2",
        "dtm-practice3",
    }
    for name, expected in references.items():
        actual = [row.model_dump() for row in parsed(name).classification.rows]
        assert [{key: row[key] for key in expected[0]} for row in actual] == expected, name


def test_sprint_points_and_constructor_standings_preserve_published_scoring():
    sprint = parsed("f1-sprint").classification
    assert sprint.context.session == "sprint"
    assert sprint.rows[0].time_raw == "31:31.383"
    assert sprint.rows[0].laps == 19 and sprint.rows[0].points_raw == "8"
    assert [row.points_raw for row in sprint.rows[:8]] == ["8", "7", "6", "5", "4", "3", "2", "1"]
    teams = parsed("f1-teams").payload
    assert len(teams["rows"]) == 10
    assert teams["rows"][0]["subject"] == "McLaren Mercedes"
    assert teams["rows"][0]["points_raw"] == "666"


@pytest.mark.parametrize(
    "command,context_name", [("bundle-wrc", "wrc-rally"), ("bundle-wec", "wec-class-hypercar")]
)
def test_cli_refuses_malformed_component_maps(data, monkeypatch, capsys, command, context_name):
    monkeypatch.setenv("DATA_DIR", str(data))
    context, _ = load(context_name)
    (data / "context.json").write_text(context.context.model_dump_json())
    (data / "components.json").write_text('["event","entries","results"]')
    assert (
        main(
            [
                command,
                "--context",
                str(data / "context.json"),
                "--components",
                str(data / "components.json"),
            ]
        )
        == 2
    )
    assert "Invalid official" in capsys.readouterr().err
    assert OfficialService(data).status() == []


def test_driver_case_variants_across_two_official_publishers_share_meeting_identity(data):
    service = OfficialService(data)
    website = service.import_manifest(FIXTURES / "f1-race.manifest.json")
    federation = service.import_manifest(FIXTURES / "fia-f1-final.manifest.json")
    assert website["record"]["record_id"] == federation["record"]["record_id"]
    with open_repository(data, read_only=True) as repo:
        variants = repo.resolve_alias("Max Verstappen", "F1")
        assert variants["status"] == "unique"
        assert (
            repo.resolve_alias("Max VERSTAPPEN", "F1")["candidates"][0]["id"]
            == variants["candidates"][0]["id"]
        )
        assert (
            repo.connection.execute(
                "SELECT count(*) FROM entities WHERE kind = 'driver'"
            ).fetchone()[0]
            == 20
        )
        history = repo.record_history(website["record"]["record_id"])
        assert len(history) == 2
        assert history[0]["payload"]["state"] == "published"
        assert history[1]["payload"]["state"] == "final"
