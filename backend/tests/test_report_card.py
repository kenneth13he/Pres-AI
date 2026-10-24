"""The report card's coaching pass: scores only with citations to what was actually said."""

from backend.services.audience import MockOrchestrator
from backend.tests.conftest import make_session, s, seg
from spec.contracts import (
    ReportAssessment,
    ReportAssessmentContext,
    ReportDimensionAssessment,
    ReportImprovementAssessment,
    ReportRubricEvidence,
)


class Grader(MockOrchestrator):
    """Plays the call like the mock, then grades it with whatever `make` returns."""

    def __init__(self, make):
        super().__init__()
        self.make = make
        self.seen: ReportAssessmentContext | None = None

    async def assess_report(self, context_json):
        self.seen = ReportAssessmentContext.model_validate_json(context_json)
        return self.make(self.seen)


def graded(ctx: ReportAssessmentContext, cite: str | None = None) -> ReportAssessment:
    first = cite or next(iter(ctx.evidence))
    dims = {k: ReportDimensionAssessment(score=None, observation="Not enough to judge.",
                                         evidence_ids=[])
            for k in ("clarity", "evidence", "structure", "question_handling")}
    dims["clarity"] = ReportDimensionAssessment(score=80, observation="Plain and direct.",
                                                evidence_ids=[first])
    return ReportAssessment(
        dimensions=dims,  # type: ignore[arg-type]
        strengths=[ReportRubricEvidence(observation="Clear opening.", evidence_ids=[first])],
        improvements=[ReportImprovementAssessment(
            observation="Claim had no source.", evidence_ids=[first],
            suggestion="Name where the number comes from.")])


def with_grader(grader):
    session = make_session()
    session.orchestrator = grader
    return session


async def present(session):
    await session.start(0)
    await session.presenter_transcript(s(33), seg(
        33, "We can get 100,000 customers in six months through our campus program."))
    await session.presenter_transcript(s(40), seg(
        40, "We plan to grow through universities, starting with two pilots this term."))
    await session.presenter_transcript(s(50), seg(
        50, "Two campus pilots so far, three hundred weekly actives and growing."))
    await session.finish(s(60))
    assert session.report is not None
    return session.report


async def test_scores_and_quotes_come_from_the_presenters_own_words():
    grader = Grader(graded)
    report_session = with_grader(grader)
    report = await present(report_session)
    assert grader.seen is not None
    said = [x.text for x in report_session.transcript if x.speaker == "presenter"]
    assert set(grader.seen.evidence.values()) <= set(said)
    assert report.dimensions["clarity"] == 80 and report.overall_score == 80
    assert "100,000 customers" in report.strengths[0]
    assert report.improvements[0].evidence.startswith("We can get 100,000")
    assert report.dimensions["structure"] is None  # unassessed is never zero


async def test_an_invented_citation_keeps_the_measured_report():
    report = await present(with_grader(Grader(lambda c: graded(c, "t99"))))
    assert report.overall_score is None and report.dimensions["clarity"] is None
    assert any("rejected" in c for c in report.metric_caveats)


async def test_a_failed_grader_still_ends_the_call_with_a_report():
    report = await present(with_grader(Grader(lambda c: None)))
    assert report.overall_score is None
    assert any("unavailable" in c for c in report.metric_caveats)
