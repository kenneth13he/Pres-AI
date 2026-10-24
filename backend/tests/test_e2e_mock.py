"""The three canonical flows from CLAUDE.md §12, silent and deterministic."""

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
