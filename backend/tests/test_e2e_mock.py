"""The call, end to end, silent and deterministic (mock brain, mock voice, fake clock)."""

import asyncio

from backend.services.audience import MockOrchestrator
from backend.services.voice_mock import MockVoice
from backend.tests.conftest import make_session, s, seg
from spec.contracts import Deck, PanelTurn, Slide

FULL_ANSWER = "Weekly retention: forty percent of our pilot users still come back every week."


def spoken(session, since=0):
    return [(e.payload["speaker"], e.payload["line"]) for e in session.events[since:]
            if e.type == "ai_speech_started"]


def with_deck(**overrides):
    overrides.setdefault("curveballs", {"mode": "off"})  # only the forced one fires
    session = make_session(**overrides)
    deck = Deck(deck_id="d", filename="d.pdf", page_count=5,
                slides=[Slide(number=i, text=f"slide {i}") for i in range(1, 6)])
    from backend.engine import Session
    return Session(session.session_id, session.config, session.preset, MockOrchestrator(),
                   MockVoice(), deck=deck)


async def test_someone_greets_you_when_the_call_starts():
    session = make_session()
    await session.start(0)
    assert session.phase == "presenting"
    assert len(spoken(session)) == 1


async def test_claim_question_answer_follow_up_then_the_thread_closes():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(
        s(33), seg(33, "We can get 100,000 customers in six months."))
    q = next(e for e in session.events if e.type == "question_queued")
    assert q.payload["persona_id"] == "vc"
    assert "100,000 customers" in q.payload["cited_excerpt"]

    await session.presenter_transcript(s(40), seg(40, "We plan to grow through universities."))
    asked = [e for e in session.events if e.type == "question_queued"]
    assert len(asked) == 2 and asked[1].payload["follow_up_of"] == q.payload["question_id"]

    n = len(session.events)
    await session.presenter_transcript(
        s(50), seg(50, "Two campus pilots so far, three hundred weekly actives and growing."))
    assert spoken(session, n) == []  # a full answer: they let you carry on
    assert session.open_question is None
    assert session.questions[0]["answer"] == "We plan to grow through universities."


async def test_mid_flow_the_panel_just_listens():
    session = make_session()
    await session.start(0)
    n = len(session.events)
    await session.presenter_transcript(s(5), seg(5, "So today I'll walk you through our idea."))
    await session.presenter_transcript(s(9), seg(9, "It starts with a problem we all have."))
    assert spoken(session, n) == []


async def test_talking_to_the_panel_gets_a_reply():
    session = make_session()
    await session.start(0)
    n = len(session.events)
    await session.presenter_transcript(s(3), seg(3, "Can you all hear me okay?"))
    assert len(spoken(session, n)) == 1


async def test_the_panel_never_hears_its_own_voice():
    class Talky(MockVoice):
        async def request_persona_turn(self, persona_id, text, style=None):
            await super().request_persona_turn(persona_id, text, style)
            return 4.0  # a four-second line

    session = make_session()
    session.voice = Talky()
    await session.start(0)  # "Hi, we can see and hear you. Whenever you're ready." 0 → 4.5 s
    await session.presenter_transcript(s(2), seg(2, "we can see and hear you"))
    assert session.transcript == []  # that was the panel coming back through the mic
    await session.presenter_transcript(s(3), seg(3, "Sorry, one sec, my slides froze."))
    await session.presenter_transcript(s(5), seg(5, "we can see and hear you"))
    assert [t.text for t in session.transcript] == [  # talking over them is still heard
        "Sorry, one sec, my slides froze.", "we can see and hear you"]


async def test_silence_gives_the_panel_one_chance_to_speak():
    calls: list[str] = []

    class Counting(MockOrchestrator):
        async def turn(self, ctx):
            calls.append(ctx.trigger)
            return await super().turn(ctx)

    session = make_session()
    session.orchestrator = Counting()
    await session.start(0)
    await session.presenter_transcript(s(10), seg(10, "So that's the first part."))
    for t in range(14, 30):
        await session.tick(s(t))
    assert calls == ["joined", "spoke", "silence"]


async def test_slides_down_then_resume_records_recovery():
    session = with_deck()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.presenter_transcript(s(100), seg(100, "and that is the architecture."))
    await session.force_curveball("slides_down", s(125))
    trig = next(e for e in session.events if e.type == "curveball_triggered")
    assert trig.payload["kind"] == "slides_down" and trig.payload["ui_effect"] == "slides_black"

    await session.presenter_transcript(s(128.4), seg(128.4, "So, the problem again is onboarding."))
    await session.tick(s(140))
    assert session.curveballs.active is not None
    await session.tick(s(155))  # 30 s after the trigger → auto restore
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "auto_restored"
    assert res.payload["recovery"]["resume_after_ms"] == 3_400

    await session.control("end", s(170))  # → Q&A: the mock asks one closing question
    await session.presenter_transcript(s(175), seg(175, FULL_ANSWER))
    assert session.report is not None
    recovery = session.report.curveballs[0].recovery
    assert recovery is not None and recovery.resume_after_ms == 3_400
    assert recovery.score is not None  # scored at the end, never during the call
    assert session.report.dimensions["recovery"] is not None


async def test_restore_slides_resolves_early():
    session = with_deck()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(90))
    await session.control("restore_slides", s(95))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "presenter_restored"


async def test_no_deck_means_no_slide_curveballs():
    session = make_session(curveballs={"mode": "choose", "kinds": ["slides_down", "heckler"]})
    assert "slides_down" not in session.scheduler.allowed_kinds
    assert "heckler" in session.scheduler.allowed_kinds


async def test_time_crunch_countdown_moves_to_qna_then_report():
    session = make_session()
    await session.start(0)
    await session.force_curveball("time_crunch", s(100))
    assert any(e.type == "timer_override" and e.payload["remaining_ms"] == 60_000
               for e in session.events)
    await session.tick(s(161))
    assert session.phase == "qna"
    assert session.open_question is not None  # the closing question
    await session.presenter_transcript(s(165), seg(165, FULL_ANSWER))
    assert session.phase == "report" and session.report is not None
    assert session.report.curveballs[0].resolution == "timed_out"


async def test_heckler_is_answered_by_your_next_words():
    session = make_session()
    await session.start(0)
    await session.force_curveball("heckler", s(70))
    assert session.open_question is not None
    await session.presenter_transcript(
        s(75), seg(75, "Fair challenge: the model is the easy part, the data is ours."))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "answered"


async def test_pause_and_skip_are_never_penalised():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.presenter_transcript(
        s(33), seg(33, "We can get 100,000 customers in six months."))
    await session.control("skip", s(35))
    assert session.questions[0]["skipped"] and session.open_question is None
    await session.control("pause", s(40))
    await session.presenter_transcript(s(45), seg(45, "this is ignored while paused"))
    await session.control("resume", s(100))
    assert session.phase == "presenting" and session.start_ms == s(60)
    assert all(t.text != "this is ignored while paused" for t in session.transcript)
    await session.control("end", s(110))
    assert session.report is not None
    assert session.report.metrics["unanswered_questions"] == 0
    assert session.report.metrics["skipped"] == 1


async def test_pause_time_never_counts_against_recovery():
    session = with_deck()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.control("pause", s(101))
    await session.control("resume", s(161))
    await session.presenter_transcript(s(163), seg(163, "Okay, where was I."))
    await session.control("restore_slides", s(170))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["recovery"]["resume_after_ms"] == 3_000


async def test_a_failed_brain_never_breaks_the_session():
    class Broken(MockOrchestrator):
        async def turn(self, ctx):
            raise RuntimeError("brain down")

    session = make_session()
    session.orchestrator = Broken()
    await session.start(0)
    await session.presenter_transcript(s(5), seg(5, "Can you hear me?"))
    assert any(e.type == "error" for e in session.events)
    assert session.phase == "presenting"
    assert [t.text for t in session.transcript] == ["Can you hear me?"]


async def test_a_failed_voice_still_closes_the_speech_events():
    class Mute(MockVoice):
        async def request_persona_turn(self, persona_id, text, style=None):
            raise RuntimeError("tts down")

    session = make_session()
    session.voice = Mute()
    await session.start(0)
    kinds = [e.type for e in session.events]
    assert "error" in kinds and kinds.index("ai_speech_started") < kinds.index("ai_speech_ended")


async def test_an_off_roster_speaker_or_ineligible_curveball_is_ignored():
    class Wrong(MockOrchestrator):
        async def turn(self, ctx):
            if ctx.trigger == "joined":
                return PanelTurn(action="speak", persona_id="nobody", line="hi", reason="x")
            return PanelTurn(action="curveball", curveball_kind="slides_down", line="x",
                             reason="x")

    session = make_session()
    session.orchestrator = Wrong()
    await session.start(0)
    await session.presenter_transcript(s(5), seg(5, "Hello."))
    assert spoken(session) == []


async def test_qna_with_no_questions_goes_straight_to_the_report():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.control("end", s(30))
    assert session.phase == "report" and session.report is not None


async def test_end_during_qna_finishes():
    session = make_session(qna_questions=2)
    await session.start(0)
    await session.control("end", s(30))
    assert session.phase == "qna"
    await session.control("end", s(31))
    assert session.phase == "report"
    assert session.questions[-1].get("cut_off") == "session ended"


async def test_in_the_server_the_brain_thinks_beside_the_room():
    """A slow brain never blocks the mic, and sentences that land while it thinks are folded
    into the next call rather than queued one by one."""
    gate = asyncio.Event()
    seen: list[int] = []

    class Slow(MockOrchestrator):
        async def turn(self, ctx):
            seen.append(len([ln for ln in ctx.conversation if ln.speaker == "presenter"]))
            await gate.wait()
            return await super().turn(ctx)

    session = make_session()
    session.background = True
    session.orchestrator = Slow()
    await session.start(0)  # returns at once: the greeting is still being thought about
    await asyncio.sleep(0)  # ...and the brain has started on it
    for i, text in enumerate(["One.", "Two.", "Three."]):
        await session.presenter_transcript(s(10 + i), seg(10 + i, text))
    assert len(session.transcript) == 3  # all heard while the brain was busy
    gate.set()
    while session._thinking and not session._thinking.done():
        await asyncio.sleep(0)
    assert seen == [0, 3]  # the greeting, then one call that saw all three sentences
