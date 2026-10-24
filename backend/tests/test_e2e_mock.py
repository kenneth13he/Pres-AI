"""The three canonical flows from CLAUDE.md §12, silent and deterministic."""

from backend.services.voice_mock import MockVoice
from backend.tests.conftest import make_session, s, seg


def types(session, since=0):
    return [e.type for e in session.events[since:]]


async def test_claim_question_answer_follow_up():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(
        s(33), seg(33, "We can get 100,000 customers in six months."))
    await session.tick(s(36))  # at a pause, past 30 s → the scheduler lets the VC in

    q = next(e for e in session.events if e.type == "question_queued")
    assert q.payload["persona_id"] == "vc"
    assert "100,000 customers" in q.payload["cited_excerpt"]
    assert session.phase == "answering"

    await session.presenter_transcript(s(45), seg(45, "We plan to grow through universities."))
    follow = [e for e in session.events if e.type == "question_queued"]
    assert len(follow) == 2 and follow[1].payload["follow_up_of"] == q.payload["question_id"]
    assert session.phase == "answering"

    await session.presenter_transcript(
        s(55), seg(55, "Two campus pilots so far, three hundred weekly actives and growing."))
    assert session.phase == "presenting"
    assert len([e for e in session.events if e.type == "question_queued"]) == 2  # max 1 follow-up
    assert session.last_event_end_ms == s(55)


async def test_slides_down_then_resume_records_recovery():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.presenter_transcript(s(100), seg(100, "and that is the architecture."))
    await session.force_curveball("slides_down", s(125))

    trig = next(e for e in session.events if e.type == "curveball_triggered")
    assert trig.payload["kind"] == "slides_down" and trig.payload["ui_effect"] == "slides_black"
    assert session.phase == "recovering"

    await session.presenter_transcript(s(128.4), seg(128.4, "So, the problem again is onboarding."))
    await session.tick(s(140))  # not yet auto-resolved
    assert session.curveballs.active is not None
    await session.tick(s(155))  # 30 s after trigger → auto restore

    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "auto_restored"
    assert res.payload["recovery"]["resume_after_ms"] == 3_400
    assert res.payload["recovery"]["score"] is not None
    assert session.phase == "presenting"

    await session.control("end", s(170))
    await session.tick(s(171))  # qna: mock asks nothing it can ground → finishes
    await session.control("end", s(172))
    assert session.report is not None
    recovery = session.report.curveballs[0].recovery
    assert recovery is not None and recovery.resume_after_ms == 3_400
    assert session.report.dimensions["recovery"] is not None
    assert any(m.type == "curveball" for m in session.report.key_moments)


async def test_time_crunch_countdown_moves_to_qna():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("time_crunch", s(100))
    timer = next(e for e in session.events if e.type == "timer_override")
    assert timer.payload["remaining_ms"] == 60_000
    assert session.phase == "presenting"  # keep going; the clock is the pressure
    await session.tick(s(150))
    assert session.phase == "presenting"
    await session.tick(s(160))
    assert session.phase == "qna"


async def test_pause_and_skip_are_never_penalised():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    assert session.phase == "answering"
    await session.control("pause", s(71))
    assert session.phase == "paused"
    await session.tick(s(72))  # nothing fires while paused
    await session.control("resume", s(73))
    await session.control("skip", s(74))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "skipped" and res.payload["recovery"] is None
    assert session.phase == "presenting"


async def test_failed_question_never_breaks_the_session():
    session = make_session(difficulty="friendly")  # no curveballs
    await session.start(0)
    await session.presenter_transcript(s(33), seg(33, "um so yeah this is the thing"))
    await session.tick(s(36))  # no claim to ground a question in → "none"
    assert session.phase == "presenting"
    assert "question_queued" not in types(session)


async def test_heckler_is_answered_then_resolved_as_answered():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    assert session.phase == "answering" and session.pending_question is not None
    assert session.pending_question["curveball_id"] == "cb-1"
    await session.presenter_transcript(
        s(80), seg(80, "No — the wrapper is ten percent of it; the data pipeline is the moat."))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "answered"
    assert res.payload["recovery"]["score"] is not None
    assert session.phase == "presenting"


async def test_one_event_at_a_time_and_cooldown_between_them():
    session = make_session(difficulty="brutal")
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(33), seg(33, "We have 2,000 users already."))
    await session.tick(s(36))
    assert session.phase == "answering"
    await session.force_curveball("slides_down", s(37))  # refused: a question is pending
    assert session.curveballs.active is None
    await session.presenter_transcript(
        s(45), seg(45, "Yes, two thousand paying users from the three pilot schools we signed."))
    assert session.phase == "presenting"
    await session.presenter_transcript(s(50), seg(50, "And revenue is 40% up month on month."))
    await session.tick(s(53))  # inside the 40 s cooldown → nothing
    assert len([e for e in session.events if e.type == "question_queued"]) == 1


async def test_restore_slides_resolves_early_and_qna_asks_then_finishes():
    session = make_session(qna_questions=1)
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.presenter_transcript(s(102), seg(102, "Fine, from memory then."))
    await session.control("restore_slides", s(110))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "presenter_restored"
    assert res.payload["recovery"]["resume_after_ms"] == 2_000
    await session.control("end", s(150))
    assert session.phase == "qna"
    await session.presenter_transcript(s(151), seg(151, "Our churn is only 2 percent."))
    await session.tick(s(152))  # Q&A question grounded in that claim
    assert session.phase == "answering"
    await session.presenter_transcript(
        s(160), seg(160, "Measured over six months across every cohort we have onboarded so far."))
    assert session.phase == "qna"
    await session.tick(s(161))  # 1 of 1 asked → finish
    assert session.ended and session.report is not None
    assert session.report.metrics["unanswered_questions"] == 0


# ---- fixes from the pre-merge review: pause/skip never penalised, nothing gets stuck ----


async def test_pause_time_never_counts_against_recovery_or_the_crunch():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.control("pause", s(101))
    await session.presenter_transcript(s(105), seg(105, "ignored while paused"))
    assert session.transcript == []
    await session.control("resume", s(121))  # 20 s paused
    await session.tick(s(125))  # 30 s auto-resolve must not have fired: only 5 s of play
    assert session.curveballs.active is not None
    await session.presenter_transcript(s(123.4), seg(123.4, "So, the problem again is onboarding."))
    await session.tick(s(151))  # trigger shifted to 120 → due at 150
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["recovery"]["resume_after_ms"] == 3_400
    assert session.elapsed_ms(s(151)) == s(131)

    await session.force_curveball("time_crunch", s(160))
    await session.control("pause", s(170))
    await session.control("resume", s(240))  # 70 s paused; only 10 s of the crunch used
    await session.tick(s(241))
    assert session.phase == "presenting"
    await session.tick(s(291))
    assert session.phase == "qna"


async def test_vip_arrives_is_answerable_and_does_not_get_stuck():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("vip_arrives", s(100))
    assert session.phase == "answering" and session.pending_question is not None
    await session.presenter_transcript(
        s(110), seg(110, "We cut onboarding from two weeks to one day; we need a pilot by March."))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["resolution"] == "answered" and session.phase == "presenting"


async def test_skip_during_time_crunch_skips_the_question_not_the_crunch():
    session = make_session(difficulty="brutal")
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("time_crunch", s(100))
    await session.presenter_transcript(s(141), seg(141, "We have 2,000 users already."))
    await session.tick(s(144))  # cooldown (40 s) over → question
    assert session.phase == "answering"
    await session.control("skip", s(145))
    assert session.phase == "presenting" and session.pending_question is None
    crunch = session.curveballs.records[0]
    assert crunch.resolution is None and session.time_crunch_deadline_ms == s(160)
    assert session.questions[-1]["skipped"] is True
    await session.tick(s(160))
    assert session.phase == "qna"
    assert crunch.resolution == "timed_out" and crunch.recovery is not None
    assert crunch.recovery.resume_after_ms is None  # judged on the close, not a resume gap
    r = session.report
    assert r is None
    await session.control("end", s(161))
    r = session.report
    assert r is not None
    assert r.metrics["unanswered_questions"] == 0 and r.metrics["skipped"] == 1


async def test_restore_slides_while_paused_is_ignored_and_resume_is_clean():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.control("pause", s(101))
    await session.control("restore_slides", s(102))
    assert session.curveballs.active is not None
    await session.control("resume", s(103))
    assert session.phase == "recovering"
    await session.control("restore_slides", s(104))
    assert session.phase == "presenting" and session.curveballs.active is None


async def test_end_during_a_qna_answer_finishes():
    session = make_session(qna_questions=2)
    await session.start(0)
    await session.control("end", s(100))
    await session.presenter_transcript(s(101), seg(101, "Our churn is only 2 percent."))
    await session.tick(s(102))
    assert session.phase == "answering"
    await session.control("end", s(103))
    assert session.ended


async def test_ai_segments_are_never_an_answer():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    await session.presenter_transcript(
        s(71), seg(71, "echo of the heckler line").model_copy(update={"speaker": "ai"}))
    assert session.phase == "answering" and session.transcript == []


async def test_mock_does_not_reask_a_claim_or_question_greetings():
    session = make_session(difficulty="brutal", interruption_frequency="often")
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(33), seg(33, "Hi everyone, thanks for having me today."))
    await session.tick(s(36))
    assert session.phase == "presenting"  # a greeting is not a claim
    await session.presenter_transcript(s(40), seg(40, "First, the market: revenue grew 40%."))
    await session.tick(s(43))
    assert session.phase == "answering"
    await session.presenter_transcript(
        s(50), seg(50, "From our audited numbers across both regions over the last two quarters."))
    await session.presenter_transcript(s(85), seg(85, "Again: revenue grew 40% last year."))
    await session.presenter_transcript(s(86), seg(86, "First, the market: revenue grew 40%."))
    await session.tick(s(90))  # the repeated sentence is skipped; the new one is asked
    asked = [e.payload["cited_excerpt"] for e in session.events
             if e.type == "question_queued" and e.payload.get("cited_excerpt")]
    assert asked == ["First, the market: revenue grew 40%.", "Again: revenue grew 40% last year."]
    personas = [e.payload["persona_id"] for e in session.events
                if e.type == "question_queued" and e.payload.get("cited_excerpt")]
    assert personas[0] != personas[1]  # the room shares the questions


async def test_voice_failure_never_strands_the_phase():
    session = make_session()

    class BrokenVoice(MockVoice):
        async def request_persona_turn(self, persona_id: str, text: str,
                                       style: str | None = None) -> None:
            raise RuntimeError("TTS down")

    session.voice = BrokenVoice()
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("heckler", s(70))
    assert session.phase == "answering"
    assert any(e.type == "error" and e.payload["where"] == "voice.speak" for e in session.events)
    starts = [e for e in session.events if e.type == "ai_speech_started"]
    ends = [e for e in session.events if e.type == "ai_speech_ended"]
    assert len(starts) == len(ends) == 2  # the host's welcome, then the heckle


async def test_unmeasured_recovery_is_null_not_zero():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.control("end", s(101))
    r = session.report
    assert r is not None
    rec = r.curveballs[0].recovery
    assert rec is not None and rec.resume_after_ms is None and rec.score is None
    assert r.dimensions["recovery"] is None


# ---- second review round ----------------------------------------------------------------


async def test_pause_after_an_early_resume_does_not_inflate_the_gap():
    session = make_session()
    await session.start(0)
    await session.slide_changed(s(1), 3)
    await session.force_curveball("slides_down", s(100))
    await session.presenter_transcript(s(100.5), seg(100.5, "Right — no slides, fine."))
    await session.control("pause", s(102))
    await session.control("resume", s(132))
    await session.presenter_transcript(s(137), seg(137, "So the problem is onboarding."))
    await session.control("restore_slides", s(140))
    res = next(e for e in session.events if e.type == "curveball_resolved")
    assert res.payload["recovery"]["resume_after_ms"] == 500  # measured, not 7000
    trig = next(e for e in session.events if e.type == "curveball_triggered")
    await session.control("end", s(150))
    await session.control("end", s(151))
    assert session.report is not None
    assert session.report.curveballs[0].at_ms == trig.timestamp_ms  # report agrees with events


async def test_crunch_expiry_cuts_off_a_pending_question_without_penalty():
    session = make_session(difficulty="brutal", qna_questions=0)
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("time_crunch", s(100))
    await session.presenter_transcript(s(141), seg(141, "We have 12,000 users already."))
    await session.tick(s(144))
    assert session.phase == "answering"
    await session.tick(s(160))  # deadline while the question is pending
    assert session.ended
    phases = [e.payload["to"] for e in session.events if e.type == "phase_changed"]
    assert phases[-2:] == ["qna", "report"]  # no detour through presenting
    cut = [e for e in session.events if e.type == "skipped"]
    assert cut and cut[0].payload["reason"] == "presentation ended"
    r = session.report
    assert r is not None
    assert r.metrics["unanswered_questions"] == 0
    vc = next(f for f in r.persona_feedback if f.persona_id == "vc")
    assert vc.comment.startswith("We ran out of time")


async def test_ending_early_during_a_crunch_closes_it_as_answered():
    session = make_session(qna_questions=1)
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.force_curveball("time_crunch", s(100))
    await session.presenter_transcript(s(105), seg(105, "So: the ask is a pilot. Thank you."))
    await session.control("end", s(110))
    assert session.phase == "qna" and session.time_crunch_deadline_ms is None
    crunch = session.curveballs.records[0]
    assert crunch.resolution == "answered"
    await session.presenter_transcript(s(150), seg(150, "Our churn is only 2 percent."))
    await session.tick(s(161))  # past the old deadline: nothing expires inside Q&A
    assert not any(e.type == "timer_override" and e.payload.get("style") == "expired"
                   for e in session.events)
    assert session.phase == "answering"


async def test_follow_up_wording_varies_between_questions():
    session = make_session(difficulty="brutal", interruption_frequency="often")
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(33), seg(33, "We have 2,000 users already."))
    await session.tick(s(36))
    await session.presenter_transcript(s(40), seg(40, "From pilots."))
    await session.presenter_transcript(s(45), seg(45, "Three schools, since January, all paying."))
    await session.presenter_transcript(s(80), seg(80, "Revenue is 40% up month on month."))
    await session.tick(s(83))
    await session.presenter_transcript(s(90), seg(90, "Because of pricing."))
    follow_ups = [e.payload["question"] for e in session.events
                  if e.type == "question_queued" and e.payload.get("follow_up_of")]
    assert len(follow_ups) == 2 and follow_ups[0] != follow_ups[1]


async def test_no_deck_means_no_slide_curveballs():
    session = make_session()  # conftest sessions have no deck
    assert "slides_down" not in session.scheduler.allowed_kinds
    allowed = session.scheduler.allowed_kinds
    assert "time_crunch" in allowed and "heckler" in allowed


# ---- a real audience: welcome, "can you hear me", hello back, taking questions -----------


def lines(session, speaker=None):
    return [e.payload["line"] for e in session.events if e.type == "ai_speech_started"
            and (speaker is None or e.payload["speaker"] == speaker)]


async def test_the_host_welcomes_you_when_the_call_starts():
    session = make_session()
    await session.start(0)
    assert lines(session, "moderator") == [
        "Hi, thanks for joining — we can see and hear you. Go ahead whenever you're ready."]


async def test_can_you_hear_me_gets_an_answer_but_not_every_time():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(20), seg(20, "hello can you guys hear me"))
    assert lines(session, "moderator")[-1] == "Yes, we can hear you clearly — go ahead."
    await session.presenter_transcript(s(25), seg(25, "can you hear me now"))  # within cooldown
    assert lines(session, "moderator").count("Yes, we can hear you clearly — go ahead.") == 1
    await session.presenter_transcript(s(45), seg(45, "am I on mute?"))
    assert lines(session, "moderator").count("Yes, we can hear you clearly — go ahead.") == 2
    assert session.phase == "presenting" and session.questions == []


async def test_a_hello_gets_one_hello_back_from_the_friendliest_panelist():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(17), seg(17, "Hi everyone"))
    await session.presenter_transcript(s(19), seg(19, "hello again"))
    # Sam has the lowest skepticism on the panel
    assert lines(session, "student") == ["Hi! Good to meet you — go ahead."]


async def test_inviting_questions_gets_one_right_away():
    session = make_session()
    await session.start(0)
    await session.presenter_transcript(s(10), seg(10, "We already have 2,000 paying users."))
    # before the usual 30 s wait
    await session.presenter_transcript(s(14), seg(14, "Any questions so far?"))
    assert session.phase == "answering" and len(session.questions) == 1


async def test_when_the_room_has_asked_enough_they_say_so():
    session = make_session(difficulty="friendly")
    await session.start(0)
    session.questions = [{"follow_up_of": None, "curveball_id": None}] * 2  # budget used
    await session.presenter_transcript(s(80), seg(80, "Does that make sense?"))
    assert lines(session)[-1] == "No more questions from me for now — carry on."
