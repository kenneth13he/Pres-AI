"""One bounded text-coaching pass over frozen sources; deterministic report facts stay intact."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from spec.contracts import (
    Improvement,
    PersonaFeedback,
    Report,
    ReportAssessment,
    ReportAssessmentContext,
    ReportAssessmentQuestion,
    ReportDimension,
)

from .audience import MockOrchestrator

if TYPE_CHECKING:
    from ..engine import Session

MAX_SOURCE_CHARS = 16_000
MAX_SEGMENT_CHARS = 4_000
MAX_SEGMENTS = 48
MAX_QUESTIONS = 8
MIN_REPORT_WORDS = 20
REPORT_TIMEOUT_S = 30
DIMENSIONS: tuple[ReportDimension, ...] = (
    "clarity", "evidence", "structure", "question_handling")
PARTIAL_CAVEAT = (
    "Content coaching used a bounded excerpt of the captured transcript; coverage is partial.")
COACHING_CAVEAT = (
    "Content scores are subjective text-based coaching estimates, not measured abilities. "
    "They do not verify external facts, vocal confidence, intonation or psychological traits.")


def build_context(session: Session) -> ReportAssessmentContext:
    """Keep exact full segments with stable source IDs, prioritising actual answered turns."""
    presenter = [(index, segment) for index, segment in enumerate(session.transcript)
                 if segment.speaker == "presenter" and segment.text.strip()]
    personas = {person.id: person.role[:160] for person in session.config.personas}
    answered = [question for question in session.questions if question.get("answer")
                and not question.get("skipped") and not question.get("cut_off")
                and question.get("persona_id") in personas]
    owners: dict[str, int] = {}
    used: set[int] = set()
    for question in answered:
        for index, segment in presenter:
            # an answer is the presenter's sentences after the question, joined
            if (index not in used and segment.start_ms >= question.get("asked_at_ms", 0)
                    and segment.text.strip() in question["answer"]):
                owners[question["question_id"]] = index
                used.add(index)
                break
    indices = [index for index, _ in presenter]
    priority = list(owners.values()) + indices[:2] + indices[-2:] + indices
    sources = dict(presenter)
    selected: set[int] = set()
    chars = 0
    for index in priority:
        text = sources[index].text
        if (index in selected or len(selected) >= MAX_SEGMENTS or len(text.split()) < 3
                or len(text) > MAX_SEGMENT_CHARS or chars + len(text) > MAX_SOURCE_CHARS):
            continue
        selected.add(index)
        chars += len(text)
    evidence = {f"t{index}": sources[index].text for index in sorted(selected)}
    questions = [ReportAssessmentQuestion(
        question_id=question["question_id"], persona_id=question["persona_id"],
        question=question["question"], answer_evidence_ids=[f"t{owners[question['question_id']]}"])
        for question in answered if question["question_id"] in owners
        and owners[question["question_id"]] in selected and len(question["question"]) <= 500]
    partial = len(selected) != len(presenter) or len(questions) < len(answered)
    if len(questions) > MAX_QUESTIONS:
        questions = questions[:MAX_QUESTIONS]
        partial = True
    words = sum(len(text.split()) for text in evidence.values())
    permitted: list[ReportDimension] = ["clarity", "evidence"] if words >= MIN_REPORT_WORDS else []
    if not partial and len(evidence) >= 3 and words >= 50:
        permitted.append("structure")
    if questions:
        permitted.append("question_handling")
    return ReportAssessmentContext(
        evidence=evidence, questions=questions, personas=personas, partial=partial,
        presenter_words=words, permitted_dimensions=permitted)


def _validate(assessment: ReportAssessment, context: ReportAssessmentContext) -> None:
    """Reject unsupported scores or references rather than substituting fabricated evidence."""
    if set(assessment.dimensions) != set(DIMENSIONS):
        raise ValueError("invalid_dimensions")
    allowed = set(context.evidence)
    answer_ids = {source for question in context.questions
                  for source in question.answer_evidence_ids}
    owners: dict[str, set[str]] = {}
    for question in context.questions:
        owners.setdefault(question.persona_id, set()).update(question.answer_evidence_ids)

    def references(ids: list[str], *, required: bool, permitted: set[str] = allowed) -> None:
        if ((required and not ids) or len(ids) != len(set(ids))
                or any(source not in permitted for source in ids)):
            raise ValueError("invalid_evidence_reference")

    for key, dimension in assessment.dimensions.items():
        if not dimension.observation.strip():
            raise ValueError("empty_observation")
        if dimension.score is not None and key not in context.permitted_dimensions:
            raise ValueError("unsupported_dimension")
        references(dimension.evidence_ids, required=dimension.score is not None,
                   permitted=answer_ids if key == "question_handling" else allowed)
    for finding in [*assessment.strengths, *assessment.improvements]:
        if not finding.observation.strip():
            raise ValueError("empty_observation")
        references(finding.evidence_ids, required=True)
    if any(not item.suggestion.strip() for item in assessment.improvements):
        raise ValueError("empty_suggestion")
    feedback_ids = [item.persona_id for item in assessment.persona_feedback]
    if len(feedback_ids) != len(set(feedback_ids)):
        raise ValueError("duplicate_persona")
    for feedback in assessment.persona_feedback:
        if not feedback.observation.strip():
            raise ValueError("empty_observation")
        if feedback.persona_id not in owners:
            raise ValueError("unanswered_persona")
        references(feedback.evidence_ids, required=True, permitted=owners[feedback.persona_id])


def apply_assessment(baseline: Report, assessment: ReportAssessment,
                     context: ReportAssessmentContext) -> Report:
    """Resolve quoted text on the server and preserve measured recovery, metrics and timeline."""
    _validate(assessment, context)
    report = baseline.model_copy(deep=True)
    report.metric_caveats = [note for note in report.metric_caveats
                             if not note.startswith("Content dimensions are scored")]
    if context.partial:
        report.metric_caveats.append(PARTIAL_CAVEAT)
    report.metric_caveats.append(COACHING_CAVEAT)
    accepted = []
    for key, dimension in assessment.dimensions.items():
        report.dimensions[key] = dimension.score
        if dimension.score is not None:
            accepted.append(dimension.score)
            quotes = " / ".join(f"“{context.evidence[source]}”"
                                for source in dimension.evidence_ids)
            report.metric_caveats.append(
                f"{key.replace('_', ' ').capitalize()} estimate: {dimension.observation} "
                f"Evidence: {quotes}")
        else:
            report.metric_caveats.append(
                f"{key.replace('_', ' ').capitalize()} not assessed: {dimension.observation}")
    report.overall_score = round(sum(accepted) / len(accepted)) if accepted else None
    report.metric_caveats.append(
        f"Overall is the equal-weight mean of {len(accepted)} of 4 assessed content dimensions; "
        "recovery remains separate. Unassessed dimensions are excluded, never treated as zero.")
    report.strengths = [f"{item.observation} Evidence: “{context.evidence[item.evidence_ids[0]]}”"
                        for item in assessment.strengths]
    report.improvements = [Improvement(observation=item.observation,
                                      evidence=context.evidence[item.evidence_ids[0]],
                                      suggestion=item.suggestion)
                           for item in assessment.improvements]
    feedback = {item.persona_id: PersonaFeedback(
        persona_id=item.persona_id, score=item.score,
        comment=f"{item.observation} Evidence: “{context.evidence[item.evidence_ids[0]]}”")
        for item in assessment.persona_feedback}
    report.persona_feedback = [feedback.get(item.persona_id, item)
                               for item in report.persona_feedback]
    return report


async def assess_report(session: Session, baseline: Report) -> Report:
    """Finish-time only; a bounded failure always leaves an honest available baseline report."""
    if type(session.orchestrator) is MockOrchestrator:
        return baseline
    context = build_context(session)
    if context.presenter_words < MIN_REPORT_WORDS:
        skip = getattr(session.orchestrator, "skip_report_assessment", None)
        if callable(skip):
            skip()
        report = baseline.model_copy(deep=True)
        report.metric_caveats.append("Content not assessed: insufficient captured presenter text.")
        return report
    try:
        async with asyncio.timeout(REPORT_TIMEOUT_S):
            assessment = await session.orchestrator.assess_report(context.model_dump_json())
        if assessment is not None:
            return apply_assessment(baseline, assessment, context)
        reason = "Content assessment unavailable; content scores remain not assessed."
    except (ValueError, TypeError, KeyError):
        reject = getattr(session.orchestrator, "reject_report_assessment", None)
        if callable(reject):
            reject()
        reason = "Content assessment rejected: its evidence or rubric was unsupported."
    except Exception:
        reason = "Content assessment unavailable; content scores remain not assessed."
    report = baseline.model_copy(deep=True)
    if context.partial:
        report.metric_caveats.append(PARTIAL_CAVEAT)
    report.metric_caveats.append(reason)
    return report
