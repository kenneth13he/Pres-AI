"""Grounded report coaching, bounded sources, failure safety, and both real transport seams."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from backend.services import report_assessment as service
from backend.services.audience import REPORT_PROMPT, ClaudeOrchestrator, StructuredOrchestrator
from backend.services.audience_boson import prompt_schema, report_shape_prompt
from backend.services.report import build_report
from backend.tests.conftest import make_session, seg
from backend.tests.test_boson_orchestrator import Harness, completed
from backend.tests.test_claude_orchestrator import FakeClient
from spec.contracts import OrchestratorDecision, Report, ReportAssessment, ReportAssessmentContext


def prepared():
    session = make_session()
    session.transcript = [
        seg(1, "Our tutoring product helps students review difficult lessons. We begin with the "
            "problem, explain our approach, and finish with the next step for the school pilot."),
        seg(20, "The pilot includes two hundred students. We compare weekly practice completion "
            "against their first week, using school records rather than assuming improved grades."),
        seg(40, "The school coordinator will run the next pilot and collect feedback every Friday. "
            "Our next step is to agree on the schedule before expanding the program."),
    ]
    session.questions = [
        {"question_id": "q1", "persona_id": "vc", "question": "How do you measure the pilot?",
         "answer": session.transcript[1].text, "answer_after_ms": 15_000, "skipped": False,
         "follow_up_of": None, "curveball_id": None, "cited_excerpt": session.transcript[0].text,
         "slide_number": 1},
        {"question_id": "q2", "persona_id": "student", "question": "Who runs the next pilot?",
         "answer": session.transcript[2].text, "answer_after_ms": 35_000, "skipped": False,
         "follow_up_of": None, "curveball_id": None, "cited_excerpt": None, "slide_number": 1},
    ]
    return session


def rubric() -> ReportAssessment:
    return ReportAssessment.model_validate({
        "dimensions": {
            "clarity": {"score": 80, "evidence_ids": ["t0"], "observation": "Explains the aim."},
            "evidence": {"score": 60, "evidence_ids": ["t1"], "observation": "Names a baseline."},
            "structure": {"score": 70, "evidence_ids": ["t0", "t2"],
                          "observation": "Opening leads to a next step."},
            "question_handling": {"score": 90, "evidence_ids": ["t1"],
                                  "observation": "Directly explains the measurement."}},
        "strengths": [{"evidence_ids": ["t0"], "observation": "The purpose is explicit."}],
        "improvements": [{"evidence_ids": ["t1"], "observation": "Outcome evidence is limited.",
                          "suggestion": "Add an observed result with its source."}],
        "persona_feedback": [{"persona_id": "vc", "score": 75, "evidence_ids": ["t1"],
                              "observation": "The measurement question received a direct answer."}],
    })


class Grader(StructuredOrchestrator):
    def __init__(self, output: ReportAssessment | None):
        super().__init__("higgs-realtime", "boson")
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def _parse(self, system, user, schema, effort, max_tokens=2048, timeout_s=None):
        self.calls.append({"system": system, "context": user, "schema": schema,
                           "effort": effort, "max_tokens": max_tokens, "timeout_s": timeout_s})
        self._reasoning_counts["assess_report"]["attempts"] += 1
        if self.output is None:
            self._reasoning_error("assess_report", "timeout", "TimeoutError")
        else:
            self._reasoning_counts["assess_report"]["successes"] += 1
        return self.output


async def test_one_grounded_pass_enriches_content_and_preserves_deterministic_facts():
    session = prepared()
    session.orchestrator = grader = Grader(rubric())
    baseline = build_report(session)
    result = await service.assess_report(session, baseline)
    assert result.overall_score == 75
    assert result.dimensions["recovery"] == baseline.dimensions["recovery"]
    assert result.metrics == baseline.metrics and result.key_moments == baseline.key_moments
    assert result.curveballs == baseline.curveballs
    assert result.improvements[0].evidence == session.transcript[1].text
    assert session.transcript[0].text in result.strengths[0]
    assert result.persona_feedback[0].score == 75
    assert baseline.overall_score is None and baseline.strengths == []
    assert Report.model_validate(result.model_dump()) == result
    assert len(grader.calls) == 1
    call = grader.calls[0]
    assert call["schema"] is ReportAssessment and call["system"] == REPORT_PROMPT
    assert call["max_tokens"] == 768 and call["effort"] == "high"
    context = ReportAssessmentContext.model_validate_json(call["context"])
    assert context.evidence["t1"] == session.transcript[1].text
    assert any("subjective text-based" in note for note in result.metric_caveats)


@pytest.mark.parametrize("bad_reference", ["dimension", "finding", "cross_persona", "skipped"])
async def test_invalid_or_wrong_owner_evidence_rejects_without_replacement_quotes(bad_reference):
    session, assessment = prepared(), rubric()
    if bad_reference == "dimension":
        assessment.dimensions["clarity"].evidence_ids = ["invented"]
    elif bad_reference == "finding":
        assessment.improvements[0].evidence_ids = []
    elif bad_reference == "cross_persona":
        assessment.persona_feedback[0].evidence_ids = ["t2"]
    else:
        session.questions[0]["skipped"] = True
    session.orchestrator = grader = Grader(assessment)
    baseline = build_report(session)
    result = await service.assess_report(session, baseline)
    assert result.overall_score is None and result.dimensions == baseline.dimensions
    assert result.improvements == baseline.improvements
    assert any("assessment rejected" in note for note in result.metric_caveats)
    counts = grader.diagnostics()["operations"]["assess_report"]
    assert counts["rejections"] == counts["fallbacks"] == 1


def test_context_bounds_exact_sources_and_disables_structure_for_partial_coverage():
    session = prepared()
    long = "private source " * 1000
    session.transcript.append(seg(60, long))
    context = service.build_context(session)
    assert context.partial and "structure" not in context.permitted_dimensions
    assert "t3" not in context.evidence
    assert context.evidence == {f"t{i}": row.text for i, row in enumerate(session.transcript[:3])}
    assert sum(len(text) for text in context.evidence.values()) <= service.MAX_SOURCE_CHARS
    output = rubric()
    output.dimensions["structure"].score = None
    output.dimensions["structure"].evidence_ids = []
    result = service.apply_assessment(build_report(session), output, context)
    assert result.overall_score == round((80 + 60 + 90) / 3)
    assert service.PARTIAL_CAVEAT in result.metric_caveats
    assert any("3 of 4" in note for note in result.metric_caveats)


async def test_insufficient_text_and_mock_mode_do_not_make_paid_calls():
    session = prepared()
    baseline = build_report(session)
    assert await service.assess_report(session, baseline) is baseline
    session.orchestrator = grader = Grader(rubric())
    session.transcript = [seg(1, "A very short thought.")]
    result = await service.assess_report(session, build_report(session))
    assert result.overall_score is None and grader.calls == []
    assert grader.diagnostics()["operations"]["assess_report"]["skipped"] == 1
    assert any("insufficient" in note for note in result.metric_caveats)


async def test_no_answered_questions_cannot_receive_question_or_persona_scores():
    session, output = prepared(), rubric()
    session.questions = []
    context = service.build_context(session)
    assert "question_handling" not in context.permitted_dimensions
    output.dimensions["question_handling"].score = None
    output.dimensions["question_handling"].evidence_ids = []
    output.persona_feedback = []
    session.orchestrator = Grader(output)
    result = await service.assess_report(session, build_report(session))
    assert result.dimensions["question_handling"] is None
    assert all(item.score is None for item in result.persona_feedback)
    assert result.overall_score == 70


async def test_provider_failure_preserves_honest_baseline_with_a_safe_caveat():
    session = prepared()
    session.orchestrator = Grader(None)
    baseline = build_report(session)
    result = await service.assess_report(session, baseline)
    assert result.overall_score is None and result.metrics == baseline.metrics
    assert any("unavailable" in note for note in result.metric_caveats)
    assert session.orchestrator.diagnostics()["totals"]["failures"] == 1


async def test_outer_timeout_bounds_an_unresponsive_provider(monkeypatch):
    class Waiting(Grader):
        async def assess_report(self, context_json):
            await asyncio.Future()

    session = prepared()
    session.orchestrator = Waiting(None)
    monkeypatch.setattr(service, "REPORT_TIMEOUT_S", 0.01)
    result = await asyncio.wait_for(service.assess_report(session, build_report(session)), 0.2)
    assert result.overall_score is None
    assert any("unavailable" in note for note in result.metric_caveats)


async def test_boson_report_keeps_text_transport_token_cap_budget_and_accounting(monkeypatch):
    monkeypatch.setenv("BOSON_API_KEY", "fake-offline-key")
    h = Harness(completed(rubric().model_dump()))
    result = await h.orch.assess_report(service.build_context(prepared()).model_dump_json())
    assert result == rubric() and h.socket.closed
    counts = h.orch.diagnostics()["operations"]["assess_report"]
    assert counts["attempts"] == counts["successes"] == 1
    assert counts["failures"] == counts["rejections"] == counts["fallbacks"] == 0
    assert h.reservations[0][1] == 768
    assert h.socket.sent[1]["response"]["max_output_tokens"] == 768
    instructions = h.socket.sent[1]["response"]["instructions"]
    assert "EXACT REPORT SHAPE" in instructions and "Use [] for empty arrays" in instructions


def test_report_prompt_expands_four_required_dimension_properties_without_mutating_models():
    original = ReportAssessment.model_json_schema()
    shaped = prompt_schema(ReportAssessment)
    dimensions = shaped["properties"]["dimensions"]
    keys = {"clarity", "evidence", "structure", "question_handling"}
    assert set(dimensions["properties"]) == set(dimensions["required"]) == keys
    assert dimensions["additionalProperties"] is False
    assert "propertyNames" not in dimensions and "maxProperties" not in dimensions
    assert all(value == {"$ref": "#/$defs/ReportDimensionAssessment"}
               for value in dimensions["properties"].values())
    assert ReportAssessment.model_json_schema() == original
    assert ReportAssessment.model_validate_json(report_shape_prompt().splitlines()[-1])
    for definition in shaped["$defs"].values():
        if "evidence_ids" in definition.get("properties", {}):
            assert definition["properties"]["evidence_ids"]["maxItems"] == 1
    assert original["$defs"]["ReportDimensionAssessment"]["properties"]["evidence_ids"][
        "maxItems"] == 2  # Strict admission cap is preserved; no trimming or permissive repair.
    assert shaped["properties"]["strengths"]["maxItems"] == 1
    assert shaped["properties"]["improvements"]["maxItems"] == 1


async def test_three_answer_report_failure_preserves_strict_caps_and_safe_paths(monkeypatch):
    monkeypatch.setenv("BOSON_API_KEY", "fake-offline-key")
    session = prepared()
    session.transcript.append(seg(60, "We will compare the pilot findings before expanding."))
    session.questions[1]["persona_id"] = "vc"
    session.questions.append({
        "question_id": "q3", "persona_id": "vc", "question": "What happens before expansion?",
        "answer": session.transcript[3].text, "answer_after_ms": 55_000, "skipped": False,
        "follow_up_of": None, "curveball_id": None, "cited_excerpt": None, "slide_number": 1})
    context = service.build_context(session)
    assert len(context.questions) == 3
    assert {question.persona_id for question in context.questions} == {"vc"}
    assert [question.answer_evidence_ids for question in context.questions] == [
        ["t1"], ["t2"], ["t3"]]
    output = rubric().model_dump()
    for item in (output["dimensions"]["question_handling"], output["improvements"][0],
                 output["persona_feedback"][0]):
        item["evidence_ids"] = ["t1", "t2", "t3"]
    h = Harness(completed(output))
    assert await h.orch.assess_report(context.model_dump_json()) is None
    diagnostic = h.orch.diagnostics()
    assert diagnostic["operations"]["assess_report"]["failures"] == 1
    assert diagnostic["operations"]["assess_report"]["fallbacks"] == 1
    assert diagnostic["operations"]["assess_report"]["successes"] == 0
    assert diagnostic["last_response_validation"] == {
        "operation": "assess_report", "error_count": 3, "errors": [
            {"loc": ["dimensions", "question_handling", "evidence_ids"], "type": "too_long"},
            {"loc": ["improvements", 0, "evidence_ids"], "type": "too_long"},
            {"loc": ["persona_feedback", 0, "evidence_ids"], "type": "too_long"},
        ]}
    assert len(h.connections) == len(h.reservations) == 1  # No automatic retry hides the failure.
    instructions = h.socket.sent[1]["response"]["instructions"]
    assert "EXACTLY ONE representative evidence ID" in instructions
    assert "Never list every answered turn" in instructions


async def test_report_validation_metadata_hides_unknown_fields_and_response_text(monkeypatch):
    monkeypatch.setenv("BOSON_API_KEY", "fake-offline-key")
    output = rubric().model_dump()
    output["private response field"] = "private response content"
    h = Harness(completed(output))
    assert await h.orch.assess_report("{}") is None
    metadata = h.orch.diagnostics()["last_response_validation"]
    assert metadata["errors"] == [{"loc": ["[field]"], "type": "extra_forbidden"}]
    assert "private response" not in str(metadata)


def test_non_report_prompt_shapes_keep_the_original_nullable_required_transformation():
    original = OrchestratorDecision.model_json_schema()
    expected = json.loads(json.dumps(original))
    expected["required"] = list(expected["properties"])
    assert prompt_schema(OrchestratorDecision) == expected
    assert OrchestratorDecision.model_json_schema() == original


async def test_optional_claude_keeps_official_structured_parser_for_the_new_rubric():
    client = FakeClient(rubric())
    orchestrator = ClaudeOrchestrator(client=client)
    result = await orchestrator.assess_report(service.build_context(prepared()).model_dump_json())
    assert result == rubric() and len(client.messages.calls) == 1
    call = client.messages.calls[0]
    assert call["output_format"] is ReportAssessment and call["max_tokens"] == 768
    assert orchestrator.diagnostics()["operations"]["assess_report"]["successes"] == 1
