"""Playback completion, rather than generation start, controls live turn timing."""

from backend.services.voice_mock import MockVoice
from backend.tests.conftest import make_session, s, seg


class DelayedVoice(MockVoice):
    def __init__(self, completions: list[int]) -> None:
        super().__init__()
        self.completions = completions
        self.speech_ended_at_ms = 0

    async def request_persona_turn(self, persona_id: str, text: str,
                                   style: str | None = None) -> None:
        await super().request_persona_turn(persona_id, text, style)
        self.speech_ended_at_ms = self.completions.pop(0)

    async def play_moderator_line(self, text: str) -> None:
        await self.request_persona_turn("moderator", text, "neutral")


async def test_question_waits_until_actual_playback_end_to_accept_an_answer():
    session = make_session(difficulty="friendly")
    session.voice = DelayedVoice([s(43), s(49)])
    await session.start(0)
    await session.presenter_transcript(s(33), seg(33, "We have 2,000 paying users."))
    await session.tick(s(36))

    question = session.pending_question
    assert question is not None
    assert question["asked_at_ms"] == s(36)
    assert question["answer_after_ms"] == s(43)
    speech_events = [e for e in session.events if e.type.startswith("ai_speech_")]
    assert [e.timestamp_ms for e in speech_events] == [s(36), s(43)]
    assert session.events[-1].timestamp_ms == s(43)

    # A transcript from before the audible question can arrive late from STT. Keep it
    # in the presentation history, but do not mistake it for an answer to that question.
    late_segment = seg(35, "Our next point is that revenue is growing every single month.")
    await session.presenter_transcript(s(44), late_segment)
    assert question["answer"] is None
    assert session.pending_question is question
    assert late_segment in session.transcript

    answer = "We count every active paying account across three pilot schools each month."
    await session.presenter_transcript(s(45), seg(44, answer))
    assert question["answer"] == answer
    assert session.phase == "presenting"
    assert session.last_event_end_ms == s(49)
    assert session.events[-1].timestamp_ms == s(49)


async def test_follow_up_uses_its_own_playback_boundary():
    session = make_session(difficulty="friendly")
    session.voice = DelayedVoice([s(43), s(50), s(57)])
    await session.start(0)
    await session.presenter_transcript(s(33), seg(33, "We have 2,000 paying users."))
    await session.tick(s(36))
    await session.presenter_transcript(s(44), seg(44, "Through schools."))

    follow_up = session.pending_question
    assert follow_up is not None and follow_up["follow_up_of"] is not None
    assert follow_up["answer_after_ms"] == s(50)
    await session.presenter_transcript(s(51), seg(46, "A late fragment from the first answer."))
    assert follow_up["answer"] is None
    await session.presenter_transcript(
        s(54), seg(52, "We signed three school pilots with two thousand paid weekly users "
                  "in total."))
    assert session.phase == "presenting"
    assert session.last_event_end_ms == s(57)


async def test_answerable_curveball_waits_until_playback_has_finished():
    session = make_session()
    session.voice = DelayedVoice([s(105), s(114)])
    await session.start(0)
    await session.force_curveball("heckler", s(100))
    pending = session.pending_question
    assert pending is not None and pending["answer_after_ms"] == s(105)

    await session.presenter_transcript(s(106), seg(101, "Earlier presentation material."))
    assert pending["answer"] is None
    await session.presenter_transcript(
        s(110), seg(107, "We own the complete data pipeline and deliver results beyond "
                   "a simple API wrapper."))
    assert session.phase == "presenting"
    assert session.last_event_end_ms == s(114)


async def test_time_crunch_cooldown_begins_after_its_spoken_announcement():
    session = make_session()
    session.voice = DelayedVoice([s(107)])
    await session.start(0)
    await session.force_curveball("time_crunch", s(100))
    assert session.last_event_end_ms == s(107)
    assert session.time_crunch_deadline_ms == s(160)
    assert session.events[-1].timestamp_ms == s(107)
