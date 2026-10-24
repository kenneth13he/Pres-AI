"""Assess saved clean-run evidence; never contact or change a running room.

CLI: --run SNAPSHOT.json REPORT.json MANIFEST.json (repeat for the two runs).
The manifest attests to observations an API cannot prove: human microphone input,
audible browser playback, waiting for automatic finish, avatars off, and no developer
controls. A skipped exercise is incomplete coverage, never a presenter performance grade.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, TypeGuard

COUNTS = ("attempts", "successes", "failures", "fallbacks", "rejections", "skipped")
OPERATIONS = ("decide", "follow_up", "assess_recovery", "expand_persona")
OPTIONAL_OPERATIONS = ("assess_report",)
KINDS = {"slides_down", "time_crunch"}


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _integer(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _normal(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[\"'\u2018\u2019\u201c\u201d\u2026]", " ", text).split())


def _verbatim(quote: Any, segments: list[dict[str, Any]]) -> bool:
    if not isinstance(quote, str) or len(_normal(quote).split()) < 3:
        return False
    return _normal(quote) in _normal(" ".join(str(row.get("text", "")) for row in segments))


def _closing_ack_completed(events: list[dict[str, Any]],
                           closing_questions: list[dict[str, Any]]) -> bool:
    """Pair the terminal acknowledgement after the last closing answer, in event order.

    Question speech is excluded: a follow-up queued after an answer is still a question,
    even when its speech_ended marker exists. These markers prove the room completed its
    speech operation; actual audible playback remains an operator attestation.
    """
    speakers = {_mapping(event.get("payload")).get("question_id"):
                _mapping(event.get("payload")).get("persona_id") for event in closing_questions}
    answers = [(index, event) for index, event in enumerate(events)
               if event.get("type") == "answer_received"
               and _mapping(event.get("payload")).get("question_id") in speakers
               and isinstance(_mapping(event.get("payload")).get("answer"), str)
               and _mapping(event.get("payload"))["answer"].strip()]
    if not answers:
        return False
    index, answer = answers[-1]
    speaker = speakers[_mapping(answer.get("payload")).get("question_id")]
    if not isinstance(speaker, str) or not speaker:
        return False
    started = ended = False
    for event in events[index + 1:]:
        kind, data = event.get("type"), _mapping(event.get("payload"))
        if kind == "session_ended":
            return ended
        if kind == "question_queued":
            return False
        if kind == "ai_speech_started":
            started = (data.get("speaker") == speaker and isinstance(data.get("line"), str)
                       and bool(data["line"].strip()))
            ended = False
        elif kind == "ai_speech_ended" and started and data.get("speaker") == speaker:
            started, ended = False, True
    return False


def assess_run(snapshot: Any, report: Any, manifest: Any) -> dict[str, Any]:
    """Return safe technical and exercise coverage, never transcript or vendor bodies.

    Missing proof is incomplete (pending while a run is open); contradictory evidence,
    a recorded session error, or a fallback is failed. Scores are never acceptance gates.
    A verified silent blackout can be technically clean without demonstrating recovery.
    """
    snapshot, report, manifest = map(_mapping, (snapshot, report, manifest))
    finalized = snapshot.get("phase") == "report" and bool(report)
    failures: set[str] = set()
    missing: set[str] = set()
    coverage: dict[str, bool] = {}
    coverage_notes: list[str] = []
    recovery_demonstration = "unverified"

    def equal(obj: dict[str, Any], key: str, expected: Any, label: str) -> None:
        if key not in obj:
            missing.add(label + ":missing")
        elif obj[key] != expected or type(obj[key]) is not type(expected):
            failures.add(label + ":mismatch")

    def covered(key: str, condition: bool) -> None:
        coverage[key] = condition
        if not condition:
            missing.add(key)

    session_id = snapshot.get("session_id")
    safe_id = (session_id if isinstance(session_id, str)
               and re.fullmatch(r"[\w-]{1,80}", session_id) else None)
    if not safe_id:
        missing.add("session_id")
    for obj, name in ((report, "report"), (manifest, "manifest")):
        if not obj or "session_id" not in obj:
            missing.add(name + ":session_id")
        elif obj["session_id"] != session_id:
            failures.add(name + ":session_id_mismatch")

    config = _mapping(snapshot.get("config"))
    equal(config, "input_mode", "push_to_talk", "input_mode")
    settings = _mapping(snapshot.get("run_settings"))
    for key, expected in (("voice_adapter", "higgs"), ("orchestrator", "boson"),
                          ("model", "higgs-realtime"), ("avatar_enabled", False),
                          ("debug_curveball_endpoint", False)):
        equal(settings, key, expected, "run_settings:" + key)
    for key, expected in (("input_source", "human_microphone"),
                          ("browser_audio_confirmed", True), ("avatar_enabled", False),
                          ("developer_controls_used", False), ("automatic_finish_confirmed", True)):
        covered("operator_attestation:" + key, key in manifest and manifest[key] == expected
                and type(manifest[key]) is type(expected))

    brain = _mapping(snapshot.get("reasoning"))
    equal(brain, "adapter", "boson", "reasoning:adapter")
    equal(brain, "model", "higgs-realtime", "reasoning:model")
    if brain.get("last_response_model") not in (None, "higgs-realtime"):
        failures.add("reasoning:response_model_mismatch")
    if brain.get("last_error") is not None:
        failures.add("reasoning:recorded_error")
    totals, operations = _mapping(brain.get("totals")), _mapping(brain.get("operations"))
    operation_names = OPERATIONS + tuple(op for op in OPTIONAL_OPERATIONS if op in operations)
    if set(operations) - set(OPERATIONS + OPTIONAL_OPERATIONS):
        failures.add("reasoning:unknown_operation")
    for name in COUNTS:
        value = totals.get(name)
        if not _integer(value):
            missing.add("reasoning:totals:" + name)
        elif name in ("failures", "fallbacks", "rejections") and value != 0:
            failures.add("reasoning:nonzero_" + name)
    covered("live_reasoning_attempt", _integer(totals.get("attempts"))
            and totals["attempts"] > 0)
    covered("live_reasoning_success", _integer(totals.get("successes"))
            and totals["successes"] > 0)
    for name in COUNTS:
        values = [_mapping(operations.get(op)).get(name) for op in operation_names]
        if not all(_integer(value) for value in values):
            missing.add("reasoning:operations:" + name)
        elif (_integer(totals.get(name))
              and sum(value for value in values if _integer(value)) != totals[name]):
            failures.add("reasoning:inconsistent_" + name)

    events = _rows(snapshot.get("events"))
    covered("event_log", bool(events))
    for event in events:
        if event.get("session_id", session_id) != session_id:
            failures.add("events:session_id_mismatch")
        if not _integer(event.get("timestamp_ms")):
            missing.add("events:timestamps")
    if any(event.get("type") == "error" for event in events):
        failures.add("session:error_event")
    by_type: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        by_type.setdefault(str(event.get("type")), []).append(event)
    def payload(event: dict[str, Any]) -> dict[str, Any]:
        return _mapping(event.get("payload"))

    def at(event: dict[str, Any]) -> int:
        value = event.get("timestamp_ms")
        return value if _integer(value) else 0

    phases = by_type.get("phase_changed", [])
    qna_events = [event for event in phases if payload(event).get("to") == "qna"]
    covered("started", bool(by_type.get("session_started")))
    covered("qna_entered", bool(qna_events))
    covered("report_created", snapshot.get("phase") == "report" and bool(report)
            and bool(by_type.get("session_ended")))
    transcripts = [payload(event) for event in by_type.get("transcript_segment", [])
                   if payload(event).get("speaker", "presenter") == "presenter"]
    covered("presenter_transcript", bool(transcripts))
    if any(not _integer(row.get("start_ms")) for row in transcripts):
        missing.add("transcript:timestamps")
    questions = by_type.get("question_queued", [])
    roots = [event for event in questions if not payload(event).get("follow_up_of")
             and not payload(event).get("curveball_id")]
    answer_ids = {payload(event).get("question_id")
                  for event in by_type.get("answer_received", [])
                  if isinstance(payload(event).get("answer"), str)
                  and payload(event)["answer"].strip()}
    answered_roots = [event for event in roots if payload(event).get("question_id") in answer_ids]
    qna_at = min((at(event) for event in qna_events), default=None)
    normal = [event for event in roots if qna_at is None or at(event) < qna_at]
    closing = [event for event in roots if qna_at is not None
               and at(event) >= qna_at]
    covered("grounded_question_answered", any(payload(event).get("question_id") in answer_ids
                                             for event in normal))
    covered("closing_question_answered", any(payload(event).get("question_id") in answer_ids
                                            for event in closing))
    closing_questions = [event for event in questions if qna_at is not None
                         and at(event) >= qna_at and not payload(event).get("curveball_id")]
    closing_ids = {payload(event).get("question_id") for event in closing_questions}
    skipped_ids = {payload(event).get("question_id") for event in by_type.get("skipped", [])}
    closing_complete = (bool(closing) and len(closing_ids) == len(closing_questions)
                        and all(isinstance(key, str) and key in answer_ids
                                and key not in skipped_ids for key in closing_ids))
    covered("closing_exchange_completed", closing_complete)
    covered("closing_terminal_acknowledged", closing_complete
            and _closing_ack_completed(events, closing_questions))
    for event in questions:
        quote = payload(event).get("cited_excerpt")
        if quote:
            before = [row for row in transcripts if _integer(row.get("start_ms"))
                      and row["start_ms"] <= at(event)]
            if not _verbatim(quote, before):
                failures.add("question:nonverbatim_evidence")
        elif event in normal:
            missing.add("question:grounded_excerpt")
    followups = Counter(payload(event).get("follow_up_of") for event in questions
                        if payload(event).get("follow_up_of"))
    if any(value > 1 for value in followups.values()):
        failures.add("question:repeated_followup")
    for op, minimum in (("decide", len(roots) + len(by_type.get("curveball_triggered", []))),
                        ("follow_up", len(answered_roots))):
        successes = _mapping(operations.get(op)).get("successes")
        covered("live_" + op, _integer(successes) and successes >= max(1, minimum))

    metrics = _mapping(report.get("metrics"))
    if not _integer(metrics.get("unanswered_questions")):
        missing.add("report:unanswered_questions")
    elif metrics["unanswered_questions"] != 0:
        failures.add("report:unanswered_questions")
    if finalized and any(payload(event).get("question_id") not in answer_ids | skipped_ids
                         for event in questions if not payload(event).get("curveball_id")):
        failures.add("events:unanswered_question")
    for improvement in _rows(report.get("improvements")):
        if not _verbatim(improvement.get("evidence"), transcripts):
            failures.add("report:nonverbatim_evidence")

    kind = manifest.get("required_curveball")
    if kind not in KINDS:
        missing.add("manifest:required_curveball")
    choice = _mapping(config.get("curveballs"))
    if kind in KINDS:
        equal(choice, "mode", "choose", "curveball:selection_mode")
        equal(choice, "kinds", [kind], "curveball:selected_kind")
    triggered = by_type.get("curveball_triggered", [])
    resolved = by_type.get("curveball_resolved", [])
    report_curves = _rows(report.get("curveballs"))
    covered("one_selected_curveball", len(triggered) == 1
            and payload(triggered[0]).get("kind") == kind)
    if len(triggered) > 1 or any(payload(event).get("kind") != kind for event in triggered):
        failures.add("curveball:unexpected_or_repeated")
    for event in triggered:
        source = payload(event).get("trigger_source")
        if source is None:
            missing.add("curveball:trigger_source")
        elif source != "scheduler":
            failures.add("curveball:not_natural")
    covered("curveball_reported", len(report_curves) == 1 and report_curves[0].get("kind") == kind)
    if len(report_curves) > 1:
        failures.add("report:unexpected_curveballs")
    if triggered:
        trigger = triggered[0]
        match = [event for event in resolved if payload(event).get("curveball_id")
                 == payload(trigger).get("curveball_id")]
        resolution = payload(match[0]) if len(match) == 1 else {}
        report_curve = report_curves[0] if len(report_curves) == 1 else {}
        covered("curveball_completed", bool(resolution)
                and resolution.get("resolution") != "skipped")
        answered_before = {payload(event).get("question_id")
                           for event in by_type.get("answer_received", [])
                           if at(event) < at(trigger)}
        covered("grounded_exchange_before_curveball", any(
            payload(event).get("question_id") in answered_before and at(event) < at(trigger)
            for event in normal))
        if resolution.get("resolution") == "skipped":
            missing.add("curveball:skipped_exercise")
        if resolution and report_curve and any(resolution.get(key) != report_curve.get(key)
                                               for key in ("kind", "resolution", "recovery")):
            failures.add("curveball:report_disagrees_with_events")
        if report_curve:
            if not _integer(report_curve.get("at_ms")):
                missing.add("report:curveball_timestamp")
            elif report_curve["at_ms"] != at(trigger):
                failures.add("curveball:report_timestamp_mismatch")
        recovery = _mapping(resolution.get("recovery"))
        resolved_at = at(match[0]) if len(match) == 1 else None
        after = [row for row in transcripts if _integer(row.get("start_ms"))
                 and row["start_ms"] > at(trigger) and resolved_at is not None
                 and row["start_ms"] <= resolved_at]
        recovery_counts = _mapping(operations.get("assess_recovery"))
        successes = recovery_counts.get("successes")
        live_recovery = _integer(successes) and successes > 0
        truthful_silence = False
        if kind == "slides_down":
            gap = recovery.get("resume_after_ms")
            measured = _integer(gap) and bool(after)
            quoted = _verbatim(recovery.get("evidence"), after)
            # Late speech cannot backfill a recovery that was unobserved at restoration.
            overlap = any(_integer(row.get("start_ms")) and _integer(row.get("end_ms"))
                          and row["start_ms"] <= at(trigger) < row["end_ms"]
                          for row in transcripts)
            if not after and not overlap and resolution.get("resolution") != "skipped":
                nulls = all(key in recovery and recovery[key] is None
                            for key in ("resume_after_ms", "score", "evidence"))
                if any(recovery.get(key) is not None
                       for key in ("resume_after_ms", "score", "evidence")):
                    failures.add("recovery:values_without_observed_speech")
                notes = recovery.get("notes")
                explained = (isinstance(notes, str)
                             and bool(re.search(r"\bno(?: presenter)? speech\b", _normal(notes))))
                skipped = recovery_counts.get("skipped")
                skipped_assessment = (_integer(skipped) and skipped > 0
                                      and all(_integer(recovery_counts.get(key))
                                              and recovery_counts[key] == 0
                                              for key in COUNTS if key != "skipped"))
                paused = sum(max(0, min(end, resolved_at or 0) - max(start, at(trigger)))
                             for start, end in _pause_intervals(events))
                automatic = (resolution.get("resolution") == "auto_restored"
                             and resolved_at is not None
                             and resolved_at - at(trigger) - paused >= 30_000)
                covered("silent_blackout_truthful_nulls", nulls)
                covered("silent_blackout_explained", explained)
                covered("silent_blackout_assessment_skipped", skipped_assessment)
                covered("silent_blackout_auto_restored", automatic)
                truthful_silence = (nulls and explained and skipped_assessment and automatic
                                    and bool(report_curve)
                                    and report_curve.get("recovery") == resolution.get("recovery"))
            if truthful_silence:
                coverage.update(slides_recovery_measured=False, slides_recovery_quote=False,
                                live_recovery_assessment=False)
                recovery_demonstration = "not_observed"
                coverage_notes.extend(("slides_down:spoken_recovery_not_observed",
                                       "p0_13:measured_blackout_recovery_not_demonstrated"))
            else:
                covered("slides_recovery_measured", measured)
                covered("slides_recovery_quote", quoted)
                if measured and quoted and live_recovery:
                    recovery_demonstration = "observed"
            if recovery.get("evidence") and not _verbatim(recovery["evidence"], after):
                failures.add("recovery:nonverbatim_evidence")
            if _integer(gap) and after:
                first = min(row["start_ms"] for row in after)
                pauses = _pause_intervals(events)
                paused = sum(max(0, min(end, first) - max(start, at(trigger)))
                             for start, end in pauses)
                if gap != max(0, first - at(trigger) - paused):
                    failures.add("recovery:timing_disagrees_with_transcript")
        elif kind == "time_crunch":
            timers = by_type.get("timer_override", [])
            expiry = [event for event in timers if payload(event).get("remaining_ms") == 0
                      and payload(event).get("style") == "expired"]
            covered("crunch_countdown", any(payload(event).get("remaining_ms") == 60_000
                                            for event in timers))
            covered("timer_expiry_to_qna", bool(expiry) and qna_at is not None
                    and at(expiry[0]) <= qna_at
                    and resolution.get("resolution") == "timed_out")
            if expiry:
                paused = sum(max(0, min(end, at(expiry[0])) - max(start, at(trigger)))
                             for start, end in _pause_intervals(events))
                if at(expiry[0]) - at(trigger) - paused < 60_000:
                    failures.add("crunch:premature_timer_expiry")
            if recovery.get("resume_after_ms") is not None:
                failures.add("crunch:invented_resume_gap")
            if recovery.get("evidence") and not _verbatim(recovery["evidence"], after):
                failures.add("recovery:nonverbatim_evidence")
            if after and live_recovery and _verbatim(recovery.get("evidence"), after):
                recovery_demonstration = "observed"
        if not truthful_silence:
            covered("live_recovery_assessment", live_recovery)
    if failures:
        status = "failed"
    elif not finalized:
        status = "pending"
    else:
        status = "incomplete" if missing else "complete"
    return {
        "status": status, "session_id": safe_id,
        "technical_clean": status == "complete", "recovery_demonstration": recovery_demonstration,
        "demo_coverage_complete": status == "complete" and recovery_demonstration == "observed",
        "coverage_notes": coverage_notes,
        "required_curveball": kind if kind in KINDS else None,
        "failures": sorted(failures), "incomplete_reasons": sorted(missing), "coverage": coverage,
        "counts": {"root_questions": len(roots), "answered_roots": len(answered_roots),
                   "followups": sum(followups.values()), "curveballs": len(triggered),
                   "pauses": len(by_type.get("paused", [])),
                   "skips": len(by_type.get("skipped", []))},
        "performance_scores_evaluated": False,
    }


def _pause_intervals(events: list[dict[str, Any]]) -> list[tuple[int, int]]:
    intervals: list[tuple[int, int]] = []
    start = None
    for event in events:
        at = event.get("timestamp_ms")
        if not _integer(at):
            continue
        if event.get("type") == "paused":
            start = at
        elif event.get("type") == "resumed" and start is not None:
            intervals.append((start, at))
            start = None
    return intervals


def assess_presentations(runs: list[dict[str, Any]], required_runs: int = 2) -> dict[str, Any]:
    ids = [run.get("session_id") for run in runs if run.get("session_id")]
    duplicate = len(ids) != len(set(ids))
    statuses = [run.get("status") for run in runs]
    kinds = {run.get("required_curveball") for run in runs if run.get("status") == "complete"}
    if duplicate or "failed" in statuses:
        status = "failed"
    elif len(runs) < required_runs or "pending" in statuses:
        status = "pending"
    elif any(value != "complete" for value in statuses) or (required_runs >= 2 and kinds != KINDS):
        status = "incomplete"
    else:
        status = "complete"
    return {"status": status, "required_runs": required_runs, "duplicate_session": duplicate,
            "technical_clean": status == "complete",
            "demo_coverage_complete": status == "complete"
            and all(run.get("demo_coverage_complete") is True for run in runs),
            "coverage_notes": sorted({note for run in runs
                                      for note in run.get("coverage_notes", [])}),
            "both_exercises_covered": kinds == KINDS, "runs": runs,
            "performance_scores_evaluated": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", nargs=3, action="append", required=True,
                        metavar=("SNAPSHOT", "REPORT", "MANIFEST"))
    parser.add_argument("--required-runs", type=int, default=2)
    args = parser.parse_args()
    if args.required_runs < 1:
        parser.error("--required-runs must be positive")
    runs = []
    for files in args.run:
        try:
            values = [json.loads(Path(path).read_text()) if Path(path).exists() else None
                      for path in files]
            runs.append(assess_run(*values))
        except (OSError, ValueError, TypeError):
            runs.append({"status": "failed", "failures": ["input:unreadable_or_invalid_json"]})
    result = assess_presentations(runs, args.required_runs)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "complete" else 1 if result["status"] == "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
