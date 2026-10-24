"""The report is evidence or null — never a made-up number (CLAUDE.md §10)."""

from backend.tests.conftest import make_session, s, seg


async def test_empty_session_reports_nulls_with_caveats():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.control("end", s(10))
    r = session.report
    assert r is not None
    assert r.metrics["filler_words"] is None and r.metrics["words_per_minute"] is None
    assert r.dimensions["recovery"] is None and r.overall_score is None
    assert any("no curveball" in c.lower() for c in r.metric_caveats)
    assert any("No presenter transcript" in c for c in r.metric_caveats)
    assert r.curveballs == [] and r.improvements == []
    assert all(f.comment.startswith("Listened") for f in r.persona_feedback)


async def test_fillers_and_wpm_from_timestamped_transcript():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.presenter_transcript(s(5), seg(2, "um so basically we, like, ship weekly", 3))
    await session.presenter_transcript(s(10), seg(7, "and that is the whole plan", 3))
    await session.control("end", s(12))
    r = session.report
    assert r is not None
    assert r.metrics["filler_words"] == 3
    assert r.metrics["words_per_minute"] == 130  # 13 words over 6 s
    assert any("recognition accuracy" in c for c in r.metric_caveats)


async def test_wpm_is_null_without_end_times():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.presenter_transcript(
        s(5), seg(2, "no end time here").model_copy(update={"end_ms": None}))
    await session.control("end", s(12))
    r = session.report
    assert r is not None
    assert r.metrics["words_per_minute"] is None
    assert any("lack end times" in c for c in r.metric_caveats)


async def test_unanswered_question_is_counted_and_named():
    session = make_session(qna_questions=0)
    await session.start(0)
    await session.slide_changed(s(1), 2)
    await session.presenter_transcript(s(33), seg(33, "Everyone wants this product."))
    await session.tick(s(36))
    assert session.phase == "answering"
    await session.control("end", s(40))  # ended mid-answer
    r = session.report
    assert r is not None
    assert r.metrics["unanswered_questions"] == 1
    assert r.improvements[0].evidence == "Everyone wants this product."
    vc = next(f for f in r.persona_feedback if f.persona_id == "vc")
    assert vc.comment.startswith("Never got an answer")
