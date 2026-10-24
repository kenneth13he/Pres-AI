"""One guest can complete practice; disagreements still require a panel."""

import httpx
import pytest

from backend import main, presets
from backend.engine import Session
from backend.services.audience import MockOrchestrator
from backend.services.scheduler import SchedulerSnapshot
from backend.services.voice_mock import MockVoice
from backend.session_records import SessionRecords
from backend.tests.conftest import make_config, s, seg


@pytest.mark.parametrize("count", [0, 4])
async def test_session_api_rejects_audience_outside_one_to_three(monkeypatch, count):
    monkeypatch.setattr(main, "ROOMS", {})
    config = make_config().model_dump()
    config["personas"] = [p.model_dump() for p in list(presets.personas().values())[:count]]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="http://testserver") as client:
        response = await client.post("/api/sessions", json={"config": config})
    assert response.status_code == 422
    assert main.ROOMS == {}


async def test_solo_api_session_questions_qna_report_and_persistence(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "ROOMS", {})
    monkeypatch.setattr(main, "SESSION_RECORDS", SessionRecords(tmp_path))
    clock = {"ms": 0}
    monkeypatch.setattr(main, "wall_ms", lambda: clock["ms"])
    persona = make_config().personas[0]
    config = make_config(personas=[persona.model_dump()], curveballs={"mode": "off"})

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                                 base_url="http://testserver") as client:
        created = await client.post("/api/sessions", json={"config": config.model_dump()})
        assert created.status_code == 200
        assert created.json()["config"]["personas"] == [persona.model_dump()]
        assert created.json()["config"]["input_mode"] == "push_to_talk"
        session_id = created.json()["session_id"]
        room = main.ROOMS[session_id]
        session = room.session
        room.t0 = 0
        assert isinstance(session.orchestrator, MockOrchestrator)
        assert isinstance(session.voice, MockVoice)

        await room.run(session.start(0))
        await room.run(session.presenter_transcript(
            s(33), seg(33, "We have 2,000 paying customers across three campus pilots.")))
        await room.run(session.tick(s(36)))
        assert session.phase == "answering"
        first = session.pending_question
        assert first is not None and first["persona_id"] == persona.id
        await room.run(session.presenter_transcript(s(45), seg(45, "Three campus pilots.")))
        follow_up = session.pending_question
        assert follow_up is not None and follow_up["follow_up_of"] == first["question_id"]
        await room.run(session.presenter_transcript(
            s(55), seg(55, "Our billing records show two thousand paying users across all "
                           "three campus pilots over the last six months.")))
        assert session.phase == "presenting"

        clock["ms"] = s(100)
        ended = await client.post(f"/api/sessions/{session_id}/control", json={"action": "end"})
        assert ended.json()["phase"] == "qna"
        await room.run(session.presenter_transcript(
            s(101), seg(101, "Our retention is 40 percent after six months.")))
        await room.run(session.tick(s(104)))
        assert session.phase == "answering" and session.pending_question is not None
        assert session.pending_question["persona_id"] == persona.id
        await room.run(session.presenter_transcript(
            s(115), seg(115, "We count paid accounts that remain active after six months "
                             "using every cohort in our billing records.")))
        assert session.phase == "qna" and session.qna_asked == 1
        clock["ms"] = s(116)
        await room.run(session.tick(s(116)))
        assert session.phase == "report" and session.report is not None
        assert {q["persona_id"] for q in session.questions} == {persona.id}
        assert {e.payload["speaker"] for e in session.events
                if e.type == "ai_speech_started" and e.payload["speaker"] != "moderator"} == {
                    persona.id}
        report_response = await client.get(f"/api/sessions/{session_id}/report")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["metrics"]["unanswered_questions"] == 0
        assert [p["persona_id"] for p in report["persona_feedback"]] == [persona.id]
        saved = main.SESSION_RECORDS.load(session_id)
        assert saved is not None and saved["report"] == report
        assert len(saved["snapshot"]["config"]["personas"]) == 1

        main.ROOMS.clear()
        assert (await client.get(f"/api/sessions/{session_id}/report")).json() == report
        assert (await client.get(f"/api/sessions/{session_id}")).json()["phase"] == "report"


@pytest.mark.parametrize("count", [1, 2, 3])
@pytest.mark.parametrize("mode", ["surprise", "choose"])
def test_crosstalk_eligibility_requires_multiple_guests(count, mode):
    personas = make_config().personas[:count]
    config = make_config(personas=personas, curveballs={"mode": mode, "kinds": ["crosstalk"]})
    preset = presets.presets()[config.preset_id].model_copy(
        update={"curveballs_allowed": ["crosstalk"]})
    session = Session("panel-size", config, preset, MockOrchestrator(), MockVoice())
    snapshot = SchedulerSnapshot(
        phase="presenting", elapsed_ms=s(100), questions_asked=0, curveballs_fired=0,
        fired_kinds=[], last_event_end_ms=None, last_presenter_speech_ms=s(97),
        slide_number=2, slide_changed_at_ms=None, duration_target_s=180, now_ms=s(100),
    )
    expected = ["crosstalk"] if count > 1 else []
    assert session.scheduler.allowed_kinds == expected
    assert session.scheduler.eligible(snapshot).curveball_kinds == expected


async def test_debug_crosstalk_is_ignored_with_one_guest():
    config = make_config(personas=make_config().personas[:1])
    session = Session("solo-debug", config, presets.presets()[config.preset_id],
                      MockOrchestrator(), MockVoice())
    await session.start(0)
    await session.force_curveball("crosstalk", s(100))
    assert session.phase == "presenting"
    assert session.curveballs.records == [] and session.pending_question is None
    await session.force_curveball("heckler", s(101))
    assert session.phase == "answering"
    assert session.pending_question is not None
    assert session.pending_question["persona_id"] == config.personas[0].id
