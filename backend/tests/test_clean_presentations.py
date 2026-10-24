"""Acceptance is proof of exercised behavior, not a grade for the presenter."""

from __future__ import annotations

from copy import deepcopy

import pytest

from backend.services.audience import MockOrchestrator
from backend.tests.conftest import make_session, s, seg
from scripts.assess_clean_presentations import (
    COUNTS,
    OPERATIONS,
    assess_presentations,
    assess_run,
)
from spec.contracts import OrchestratorDecision


def evidence(kind="slides_down", session_id="clean-1"):
    events = []

    def emit(type_, at, **payload):
        events.append({"type": type_, "timestamp_ms": at, "session_id": session_id,
                       "payload": payload})

    claim = "We have 2,000 paying customers across three school pilots."
    recovery_quote = "The core idea is that every student receives useful feedback."
    emit("session_started", 0)
    emit("transcript_segment", 25_000, start_ms=20_000, end_ms=25_000,
         speaker="presenter", text=claim)
    emit("question_queued", 32_000, question_id="q1", question="How was that measured?",
         persona_id="vc", cited_excerpt=claim, follow_up_of=None, curveball_id=None)
    emit("answer_received", 45_000, question_id="q1", answer="Our billing records cover it.")
    emit("curveball_triggered", 125_000, kind=kind, curveball_id="cb1",
         trigger_source="scheduler")
    emit("transcript_segment", 136_000, start_ms=130_000, end_ms=136_000,
         speaker="presenter", text=recovery_quote)
    recovery = {"resume_after_ms": 5_000 if kind == "slides_down" else None,
                "evidence": recovery_quote, "score": None, "notes": "measured",
                "suggestion": None}
    resolve_at = 155_000 if kind == "slides_down" else 185_000
    resolution = "auto_restored" if kind == "slides_down" else "timed_out"
    if kind == "time_crunch":
        emit("timer_override", 125_000, remaining_ms=60_000, style="urgent")
        emit("timer_override", 185_000, remaining_ms=0, style="expired")
    emit("curveball_resolved", resolve_at, kind=kind, curveball_id="cb1",
         resolution=resolution, recovery=recovery)
    emit("phase_changed", 190_000, **{"from": "presenting", "to": "qna"})
    emit("question_queued", 195_000, question_id="q2", question="What is your next step?",
         persona_id="student", cited_excerpt=None, follow_up_of=None, curveball_id=None)
    emit("answer_received", 205_000, question_id="q2", answer="We will expand the pilot.")
    emit("ai_speech_started", 205_000, speaker="student", line="Thanks, that answers it.")
    emit("ai_speech_ended", 209_000, speaker="student")
    emit("phase_changed", 210_000, **{"from": "qna", "to": "report"})
    emit("session_ended", 210_000, report_url=f"/api/sessions/{session_id}/report")
    operations: dict[str, dict[str, int]] = {op: dict.fromkeys(COUNTS, 0) for op in OPERATIONS}
    for op, count in (("decide", 3), ("follow_up", 2), ("assess_recovery", 1)):
        operations[op].update(attempts=count, successes=count)
    snapshot = {
        "session_id": session_id, "phase": "report", "events": events,
        "config": {"input_mode": "push_to_talk", "duration_target_s": 240,
                   "curveballs": {"mode": "choose", "kinds": [kind]}},
        "run_settings": {"voice_adapter": "higgs", "orchestrator": "boson",
                         "model": "higgs-realtime", "avatar_enabled": False,
                         "debug_curveball_endpoint": False},
        "reasoning": {"adapter": "boson", "model": "higgs-realtime",
                      "last_response_model": None, "last_error": None,
                      "operations": operations,
                      "totals": {key: sum(row[key] for row in operations.values())
                                 for key in COUNTS}},
    }
    report = {"session_id": session_id, "overall_score": None,
              "dimensions": {"clarity": None, "recovery": None},
              "metrics": {"unanswered_questions": 0},
              "improvements": [{"evidence": claim}],
              "curveballs": [{"kind": kind, "at_ms": 125_000, "resolution": resolution,
                              "recovery": deepcopy(recovery)}]}
    manifest = {"session_id": session_id, "required_curveball": kind,
                "input_source": "human_microphone", "browser_audio_confirmed": True,
                "avatar_enabled": False, "developer_controls_used": False,
                "automatic_finish_confirmed": True}
    return snapshot, report, manifest


@pytest.mark.parametrize("kind", ["slides_down", "time_crunch"])
def test_complete_evidence_does_not_require_invented_performance_scores(kind):
    result = assess_run(*evidence(kind))
    assert result["status"] == "complete", result
    assert result["technical_clean"] and result["demo_coverage_complete"]
    assert result["recovery_demonstration"] == "observed"
    assert not result["performance_scores_evaluated"]


def silent_blackout_evidence():
    snapshot, report, manifest = evidence()
    # This speech starts after restoration; it cannot establish recovery during the blackout.
    transcript = next(event for event in snapshot["events"]
                      if event["type"] == "transcript_segment" and event["timestamp_ms"] == 136_000)
    snapshot["events"].remove(transcript)
    transcript["timestamp_ms"] = 166_000
    transcript["payload"].update(start_ms=160_000, end_ms=166_000)
    qna_index = next(i for i, event in enumerate(snapshot["events"])
                     if event["type"] == "phase_changed")
    snapshot["events"].insert(qna_index, transcript)
    recovery = {"resume_after_ms": None, "score": None, "evidence": None,
                "notes": "no presenter speech recorded after the event; timing not measured",
                "suggestion": "Continue from your outline."}
    resolved = next(event for event in snapshot["events"] if event["type"] == "curveball_resolved")
    resolved["payload"]["recovery"] = deepcopy(recovery)
    report["curveballs"][0]["recovery"] = deepcopy(recovery)
    counts = snapshot["reasoning"]["operations"]["assess_recovery"]
    counts.update(attempts=0, successes=0, skipped=1)
    snapshot["reasoning"]["totals"] = {
        key: sum(row[key] for row in snapshot["reasoning"]["operations"].values())
        for key in COUNTS}
    return snapshot, report, manifest


def test_truthful_silent_blackout_is_technically_clean_without_claiming_a_recovery_demonstration():
    result = assess_run(*silent_blackout_evidence())
    assert result["status"] == "complete", result
    assert result["technical_clean"] and not result["demo_coverage_complete"]
    assert result["recovery_demonstration"] == "not_observed"
    assert not result["coverage"]["slides_recovery_measured"]
    assert not result["coverage"]["slides_recovery_quote"]
    assert not result["coverage"]["live_recovery_assessment"]
    assert not result["incomplete_reasons"]
    assert "p0_13:measured_blackout_recovery_not_demonstrated" in result["coverage_notes"]
    pair = assess_presentations([result, assess_run(*evidence("time_crunch", "other"))])
    assert pair["status"] == "complete" and pair["technical_clean"]
    assert not pair["demo_coverage_complete"]
    assert set(pair["coverage_notes"]) == set(result["coverage_notes"])


@pytest.mark.parametrize("side", ["event", "report"])
def test_silent_recovery_event_and_report_must_agree_exactly(side):
    snapshot, report, manifest = silent_blackout_evidence()
    recovery = (next(event for event in snapshot["events"]
                     if event["type"] == "curveball_resolved")["payload"]["recovery"]
                if side == "event" else report["curveballs"][0]["recovery"])
    recovery["score"] = 0
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "curveball:report_disagrees_with_events" in result["failures"]


@pytest.mark.parametrize("field", ["resume_after_ms", "score", "evidence", "notes"])
def test_silent_recovery_requires_explicit_null_fields_and_an_explanation(field):
    snapshot, report, manifest = silent_blackout_evidence()
    event_recovery = next(event for event in snapshot["events"]
                          if event["type"] == "curveball_resolved")["payload"]["recovery"]
    del event_recovery[field]
    del report["curveballs"][0]["recovery"][field]
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert not result["technical_clean"]


@pytest.mark.parametrize("skipped", [None, 0])
def test_silent_recovery_needs_a_recorded_deliberate_no_call(skipped):
    snapshot, report, manifest = silent_blackout_evidence()
    counts = snapshot["reasoning"]["operations"]["assess_recovery"]
    counts["skipped"] = skipped
    snapshot["reasoning"]["totals"]["skipped"] = skipped
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert not result["coverage"]["silent_blackout_assessment_skipped"]


@pytest.mark.parametrize("counter", ["failures", "fallbacks", "rejections"])
def test_silence_never_excuses_a_recorded_recovery_failure_or_fallback(counter):
    snapshot, report, manifest = silent_blackout_evidence()
    snapshot["reasoning"]["operations"]["assess_recovery"][counter] = 1
    snapshot["reasoning"]["totals"][counter] = 1
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "reasoning:nonzero_" + counter in result["failures"]


def test_late_transcription_of_actual_blackout_speech_cannot_use_the_silence_exception():
    snapshot, report, manifest = silent_blackout_evidence()
    transcript = next(event for event in snapshot["events"]
                      if event["type"] == "transcript_segment" and event["timestamp_ms"] == 166_000)
    transcript["payload"].update(start_ms=140_000, end_ms=150_000)
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete", result
    assert result["recovery_demonstration"] == "unverified"
    assert "slides_recovery_measured" in result["incomplete_reasons"]


def test_no_speech_requires_normal_auto_restoration_not_an_early_manual_restore():
    snapshot, report, manifest = silent_blackout_evidence()
    resolved = next(event for event in snapshot["events"] if event["type"] == "curveball_resolved")
    resolved["payload"]["resolution"] = "presenter_restored"
    report["curveballs"][0]["resolution"] = "presenter_restored"
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert not result["coverage"]["silent_blackout_auto_restored"]


def test_two_distinct_completed_exercises_and_no_duplicate_session():
    runs = [assess_run(*evidence("slides_down", "a")),
            assess_run(*evidence("time_crunch", "b"))]
    assert assess_presentations(runs)["status"] == "complete"
    assert assess_presentations([runs[0], runs[0]])["status"] == "failed"
    assert assess_presentations(runs[:1])["status"] == "pending"
    assert assess_presentations([runs[0], assess_run(*evidence("slides_down", "c"))])[
        "status"] == "incomplete"


@pytest.mark.parametrize("key", ["failures", "fallbacks", "rejections"])
def test_missing_counter_is_incomplete_and_positive_counter_is_failure(key):
    snapshot, report, manifest = evidence()
    del snapshot["reasoning"]["totals"][key]
    assert assess_run(snapshot, report, manifest)["status"] == "incomplete"
    snapshot["reasoning"]["totals"][key] = 1
    snapshot["reasoning"]["operations"]["decide"][key] = 1
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "reasoning:nonzero_" + key in result["failures"]


@pytest.mark.parametrize("operation", ["decide", "follow_up", "assess_recovery"])
def test_successful_real_operations_are_required_not_just_a_provider_label(operation):
    snapshot, report, manifest = evidence()
    count = snapshot["reasoning"]["operations"][operation]["successes"]
    snapshot["reasoning"]["operations"][operation]["successes"] = 0
    snapshot["reasoning"]["totals"]["successes"] -= count
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete"
    assert not result["failures"]


def test_wrong_runtime_model_or_mock_adapter_fails_even_if_manifest_claims_live():
    snapshot, report, manifest = evidence()
    snapshot["run_settings"]["orchestrator"] = "mock"
    snapshot["reasoning"]["model"] = "a-different-model"
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "run_settings:orchestrator:mismatch" in result["failures"]


def test_report_assessment_counters_are_counted_without_invalidating_historical_runs():
    historical = evidence()
    assert assess_run(*historical)["status"] == "complete"
    snapshot, report, manifest = deepcopy(historical)
    counts: dict[str, int] = dict.fromkeys(COUNTS, 0)
    counts.update(attempts=1, successes=1)
    snapshot["reasoning"]["operations"]["assess_report"] = counts
    for key, value in counts.items():
        snapshot["reasoning"]["totals"][key] += value
    assert assess_run(snapshot, report, manifest)["status"] == "complete"
    del counts["successes"]
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete"
    assert "reasoning:operations:successes" in result["incomplete_reasons"]


def test_failed_report_assessment_cannot_hide_behind_successful_audience_calls():
    snapshot, report, manifest = evidence()
    counts: dict[str, int] = dict.fromkeys(COUNTS, 0)
    counts.update(attempts=1, failures=1, fallbacks=1)
    snapshot["reasoning"]["operations"]["assess_report"] = counts
    for key, value in counts.items():
        snapshot["reasoning"]["totals"][key] += value
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "reasoning:nonzero_failures" in result["failures"]
    assert "reasoning:nonzero_fallbacks" in result["failures"]


def test_unknown_reasoning_operation_needs_review_instead_of_silently_disappearing():
    snapshot, report, manifest = evidence()
    snapshot["reasoning"]["operations"]["unrecognized"] = dict.fromkeys(COUNTS, 0)
    assert "reasoning:unknown_operation" in assess_run(snapshot, report, manifest)["failures"]


def test_error_event_fails_and_output_never_leaks_vendor_error_or_transcript():
    snapshot, report, manifest = evidence()
    snapshot["events"].append({"type": "error", "payload": {"message": "SECRET vendor body"}})
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "failed"
    assert "SECRET" not in str(result) and "paying customers" not in str(result)


def test_pending_question_is_pending_not_a_failed_presentation():
    snapshot, _, manifest = evidence()
    snapshot["phase"] = "answering"
    snapshot["events"] = snapshot["events"][:3]
    result = assess_run(snapshot, None, manifest)
    assert result["status"] == "pending", result


def test_missing_hardware_attestation_cannot_be_inferred_from_transcripts():
    snapshot, report, manifest = evidence()
    del manifest["browser_audio_confirmed"]
    manifest["input_source"] = "synthetic_transcript"
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]


@pytest.mark.parametrize("confirmation", [None, False])
def test_automatic_finish_requires_confirmation_even_when_no_question_was_cut_off(confirmation):
    snapshot, report, manifest = evidence()
    manifest["automatic_finish_confirmed"] = confirmation
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert result["coverage"]["closing_exchange_completed"]
    assert result["coverage"]["closing_terminal_acknowledged"]
    assert "operator_attestation:automatic_finish_confirmed" in result["incomplete_reasons"]


def closing_followup(snapshot, *, answered):
    events = snapshot["events"]
    index = next(i for i, event in enumerate(events) if event["type"] == "answer_received"
                 and event["payload"]["question_id"] == "q2")

    def event(type_, at, **payload):
        return {"type": type_, "timestamp_ms": at, "session_id": snapshot["session_id"],
                "payload": payload}

    replacement = [
        event("question_queued", 205_000, question_id="q3", persona_id="student",
              question="Who will run the next pilot?", follow_up_of="q2", curveball_id=None),
        event("ai_speech_started", 205_000, speaker="student", line="Who will run the next pilot?"),
        event("ai_speech_ended", 206_000, speaker="student"),
    ]
    if answered:
        replacement += [
            event("answer_received", 207_000, question_id="q3", answer="The school will run it."),
            event("ai_speech_started", 207_000, speaker="student", line="Thanks, that answers it."),
            event("ai_speech_ended", 209_000, speaker="student"),
        ]
    else:
        replacement.append(event("skipped", 209_000, question_id="q3", reason="session ended"))
    events[index + 1:-2] = replacement


def test_answered_closing_root_with_cut_off_followup_is_incomplete_not_a_performance_failure():
    snapshot, report, manifest = evidence()
    closing_followup(snapshot, answered=False)
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert result["coverage"]["closing_question_answered"]  # compatibility: the root was answered
    assert not result["coverage"]["closing_exchange_completed"]
    assert not result["coverage"]["closing_terminal_acknowledged"]


def test_complete_closing_followup_then_terminal_acknowledgement_covers_the_exchange():
    snapshot, report, manifest = evidence()
    closing_followup(snapshot, answered=True)
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "complete", result
    assert result["coverage"]["closing_exchange_completed"]
    assert result["coverage"]["closing_terminal_acknowledged"]


@pytest.mark.parametrize("broken_marker", ["missing_start", "missing_end", "wrong_speaker"])
def test_missing_or_unmatched_terminal_acknowledgement_is_incomplete(broken_marker):
    snapshot, report, manifest = evidence()
    if broken_marker == "wrong_speaker":
        next(event for event in snapshot["events"] if event["type"] == "ai_speech_ended")[
            "payload"]["speaker"] = "vc"
    else:
        remove = "ai_speech_started" if broken_marker == "missing_start" else "ai_speech_ended"
        snapshot["events"] = [event for event in snapshot["events"] if event["type"] != remove]
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert result["coverage"]["closing_exchange_completed"]
    assert not result["coverage"]["closing_terminal_acknowledged"]


def test_ordinary_question_skip_does_not_disqualify_a_completed_closing_exchange():
    snapshot, report, manifest = evidence()
    snapshot["events"][4:4] = [
        {"type": "question_queued", "timestamp_ms": 55_000, "payload": {
            "question_id": "optional", "persona_id": "vc", "curveball_id": None,
            "cited_excerpt": report["improvements"][0]["evidence"], "follow_up_of": None}},
        {"type": "skipped", "timestamp_ms": 60_000, "payload": {"question_id": "optional"}},
    ]
    for counter in ("attempts", "successes"):
        snapshot["reasoning"]["operations"]["decide"][counter] += 1
        snapshot["reasoning"]["totals"][counter] += 1
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "complete", result
    assert result["counts"]["skips"] == 1


def test_debug_trigger_and_repeat_are_failures_but_legacy_missing_source_is_incomplete():
    snapshot, report, manifest = evidence()
    trigger = next(event for event in snapshot["events"] if event["type"] == "curveball_triggered")
    del trigger["payload"]["trigger_source"]
    assert assess_run(snapshot, report, manifest)["status"] == "incomplete"
    trigger["payload"]["trigger_source"] = "debug"
    assert assess_run(snapshot, report, manifest)["status"] == "failed"
    trigger["payload"]["trigger_source"] = "scheduler"
    snapshot["events"].append(deepcopy(trigger))
    assert assess_run(snapshot, report, manifest)["status"] == "failed"


def test_skip_is_incomplete_exercise_coverage_and_pause_does_not_penalize_recovery():
    snapshot, report, manifest = evidence()
    trigger_index = next(i for i, event in enumerate(snapshot["events"])
                         if event["type"] == "curveball_triggered")
    snapshot["events"][trigger_index + 1:trigger_index + 1] = [
        {"type": "paused", "timestamp_ms": 126_000, "payload": {}},
        {"type": "resumed", "timestamp_ms": 128_000, "payload": {}},
    ]
    resolved = next(event for event in snapshot["events"] if event["type"] == "curveball_resolved")
    resolved["payload"]["recovery"]["resume_after_ms"] = 3_000
    report["curveballs"][0]["recovery"]["resume_after_ms"] = 3_000
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "complete", result
    assert result["counts"]["pauses"] == 1
    resolved["payload"].update(resolution="skipped", recovery=None)
    report["curveballs"][0].update(resolution="skipped", recovery=None)
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete" and not result["failures"]
    assert "curveball:skipped_exercise" in result["incomplete_reasons"]


@pytest.mark.parametrize("location", ["question", "report", "recovery"])
def test_evidence_must_be_a_real_presenter_quote(location):
    snapshot, report, manifest = evidence()
    fake = "We have ten million customers."
    if location == "question":
        snapshot["events"][2]["payload"]["cited_excerpt"] = fake
    elif location == "report":
        report["improvements"][0]["evidence"] = fake
    else:
        resolved = next(event for event in snapshot["events"]
                        if event["type"] == "curveball_resolved")
        resolved["payload"]["recovery"]["evidence"] = fake
        report["curveballs"][0]["recovery"]["evidence"] = fake
    assert assess_run(snapshot, report, manifest)["status"] == "failed"


def test_crunch_requires_real_expiry_not_an_early_end_into_qna():
    snapshot, report, manifest = evidence("time_crunch")
    snapshot["events"] = [event for event in snapshot["events"]
                          if not (event["type"] == "timer_override"
                                  and event["payload"].get("style") == "expired")]
    result = assess_run(snapshot, report, manifest)
    assert result["status"] == "incomplete"
    assert "timer_expiry_to_qna" in result["incomplete_reasons"]


async def test_engine_records_scheduler_and_debug_curveball_provenance():
    class ChooseSlides(MockOrchestrator):
        async def decide(self, ctx):
            return OrchestratorDecision(action="curveball", curveball_kind="slides_down",
                                        reason="eligible offline exercise")

    natural = make_session(curveballs={"mode": "choose", "kinds": ["slides_down"]})
    natural.orchestrator = ChooseSlides()
    await natural.start(0)
    await natural.slide_changed(s(1), 2)
    await natural.presenter_transcript(s(2), seg(2, "We have 2,000 paying customers."))
    await natural.tick(s(61))
    debug = make_session()
    await debug.start(0)
    await debug.force_curveball("slides_down", s(1))
    sources = [next(event.payload["trigger_source"] for event in session.events
                    if event.type == "curveball_triggered") for session in (natural, debug)]
    assert sources == ["scheduler", "debug"]
