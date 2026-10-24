from pathlib import Path

import pytest

from backend.session_records import SessionRecords


def report(session_id="finished"):
    return {"session_id": session_id, "dimensions": {}, "metrics": {}}


def test_finished_snapshot_and_report_survive_a_new_store_instance(tmp_path):
    store = SessionRecords(tmp_path)
    snapshot = {"session_id": "finished", "phase": "report", "reasoning": {
        "adapter": "boson", "model": "higgs-realtime", "totals": {"successes": 4}}}
    store.save(snapshot, report())
    saved = SessionRecords(tmp_path).load("finished")
    assert saved and saved["snapshot"] == snapshot
    assert saved["report"]["session_id"] == "finished"
    assert (tmp_path / "finished.json").stat().st_mode & 0o777 == 0o600


def test_unfinished_corrupt_mismatched_and_traversal_records_are_not_read(tmp_path):
    store = SessionRecords(tmp_path)
    with pytest.raises(ValueError):
        store.save({"session_id": "active", "phase": "paused"}, report("active"))
    assert store.load("../private") is None
    (tmp_path / "broken.json").write_text("not JSON")
    assert store.load("broken") is None
    store.save({"session_id": "finished", "phase": "report"}, report())
    contents = (tmp_path / "finished.json").read_text().replace('"report"', '"paused"', 1)
    (tmp_path / "finished.json").write_text(contents)
    assert store.load("finished") is None


def test_save_rejects_another_reports_identity(tmp_path: Path):
    with pytest.raises(ValueError):
        SessionRecords(tmp_path).save(
            {"session_id": "finished", "phase": "report"}, report("other"))
