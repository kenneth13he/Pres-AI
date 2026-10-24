from pathlib import Path

import pytest

from backend import main
from backend.services.audience import MockOrchestrator
from backend.session_records import SessionRecords
from backend.tests.conftest import make_session


def test_requested_real_audience_never_silently_becomes_mock(monkeypatch):
    monkeypatch.setenv("ORCHESTRATOR", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main.health()["adapters"]["orchestrator"] == "unavailable"
    with pytest.raises(main.HTTPException) as exc:
        main.make_orchestrator()
    assert exc.value.status_code == 503
    monkeypatch.setenv("ORCHESTRATOR", "boson")
    monkeypatch.delenv("BOSON_API_KEY", raising=False)
    with pytest.raises(main.HTTPException):
        main.make_orchestrator()
    monkeypatch.setenv("BOSON_API_KEY", "offline-key-not-sent")
    assert main.reasoning_status(main.make_orchestrator())["adapter"] == "boson"


async def test_finished_room_survives_memory_removal(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    session = make_session(qna_questions=0)
    room = main.Room(session)
    monkeypatch.setitem(main.ROOMS, session.session_id, room)
    await room.run(session.start(0))
    await room.run(session.control("end", 1000))
    snapshot = main.get_session(session.session_id)
    assert snapshot["reasoning"]["adapter"] == "mock"
    assert snapshot["run_settings"]["orchestrator"] == "mock"
    main.ROOMS.pop(session.session_id)
    assert main.get_session(session.session_id) == snapshot
    assert main.get_report(session.session_id)["session_id"] == session.session_id


async def test_safe_fallback_metadata_becomes_one_visible_room_error():
    class FailedBrain(MockOrchestrator):
        def diagnostics(self):
            result = super().diagnostics()
            result["totals"]["failures"] = 1
            result["totals"]["fallbacks"] = 1
            return result
    session = make_session()
    session.orchestrator = FailedBrain()
    room = main.Room(session)
    await room.run(session.start(0))
    await room.run(session.tick(1000))
    errors = [e for e in session.events if e.type == "error"]
    assert len(errors) == 1 and errors[0].payload["where"] == "orchestrator.fallback"
    assert "safe fallback" in errors[0].payload["message"]
