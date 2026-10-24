"""Opt-in finish/report preflight: fictional text, silent audio, one real Boson rubric call."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend import presets  # noqa: E402
from backend.engine import Session  # noqa: E402
from backend.services.audience_boson import BosonOrchestrator  # noqa: E402
from backend.services.voice_mock import MockVoice  # noqa: E402
from spec.contracts import CurveballMode, SessionConfig, TranscriptSegment  # noqa: E402


async def main() -> int:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("BOSON_API_KEY"):
        print("The local Boson key is missing. No request was sent.")
        return 2
    roster = presets.personas()
    config = SessionConfig(preset_id="startup_pitch", personas=[roster["vc"], roster["student"]],
                           curveballs=CurveballMode(mode="off"), qna_questions=0)
    brain = BosonOrchestrator(max_output_tokens=768)
    voice = MockVoice()
    session = Session("report-preflight", config, presets.presets()["startup_pitch"],
                      brain, voice)
    lines = [
        "The problem is that students practise presentations in empty rooms. They receive "
        "feedback after speaking, but rarely practise answering an unexpected audience question.",
        "Our product lets a presenter choose a fictional audience and rehearse with their slides. "
        "Each audience member asks about claims in the actual presentation "
        "and listens to an answer.",
        "Our next step is a six-week pilot with three schools. We will compare weekly active "
        "usage and retention before expanding, rather than assuming the pilots establish demand.",
        "We will measure weekly active usage from the pilot logs and retention across all six "
        "weeks. Three signed pilot agreements let us collect that evidence before broader rollout.",
    ]
    result: dict[str, Any] = {
        "status": "fail", "synthetic_input": True, "human_acceptance": False,
        "audio_adapter": "mock", "anthropic_called": False, "original_reports_modified": False,
    }
    notifications = []

    async def pending() -> None:
        notifications.append({"phase": session.phase, "report_pending": session.report is None,
                              "voice_stopped": voice.calls[-1][0] == "stop"})

    session.on_report_pending = pending
    try:
        async with asyncio.timeout(32):
            await session.start(0)
            for index, text in enumerate(lines):
                start = (index * 10 + 1) * 1000
                await session.presenter_transcript(start + 7000, TranscriptSegment(
                    start_ms=start, end_ms=start + 6000, text=text))
            # The Q&A record is deliberately injected; only report grading contacts Boson.
            question = session._new_question(
                "vc", "How will you validate retention before expanding?", 30_000,
                "synthetic report preflight", lines[2], 1, None, None)
            question["answer"] = lines[3]
            await session.finish(45_000)
        report = session.report
        diagnostic = brain.diagnostics()
        result.update(reasoning=diagnostic, notifications=notifications,
                      report=report.model_dump() if report else None)
        counts = diagnostic["operations"]["assess_report"]
        if (report is None or report.overall_score is None
                or report.dimensions["question_handling"] is None
                or counts["attempts"] != 1 or counts["successes"] != 1
                or any(diagnostic["totals"][key] for key in ("failures", "fallbacks", "rejections"))
                or notifications != [{"phase": "report", "report_pending": True,
                                      "voice_stopped": True}]):
            raise ValueError("Report preflight did not pass")
        assert session.elapsed_ms(90_000) == 45_000
        result["status"] = "pass"
    except Exception as exc:
        result["error_class"] = type(exc).__name__
        result.setdefault("reasoning", brain.diagnostics())
    result["checked_at_utc"] = datetime.now(UTC).isoformat()
    out = ROOT / "data/voice_checks/boson_report_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    out.chmod(0o600)
    print(json.dumps({"status": result["status"], "human_acceptance": False,
                      "reasoning": result["reasoning"]["totals"]}))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use existing Boson API credits")
    if not parser.parse_args().live:
        parser.error("Pass --live to allow one bounded text reasoning request.")
    raise SystemExit(asyncio.run(main()))
