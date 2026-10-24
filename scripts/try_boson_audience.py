"""Opt-in bounded audience preflight using the existing Boson key; no microphone/audio."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from backend import presets  # noqa: E402
from backend.services.audience import OrchestratorContext  # noqa: E402
from backend.services.audience_boson import BosonOrchestrator  # noqa: E402
from backend.services.reasoning_budget import diagnostics as budget_status  # noqa: E402
from spec.contracts import TranscriptSegment  # noqa: E402


async def main() -> int:
    load_dotenv(ROOT / ".env")
    if not os.environ.get("BOSON_API_KEY"):
        print("The local Boson key is missing. No request was sent.")
        return 2
    brain = BosonOrchestrator(max_output_tokens=int(
        os.environ.get("BOSON_REASONING_MAX_OUTPUT_TOKENS", "768")))
    started = time.monotonic()
    result: dict[str, Any] = {"status": "fail", "adapter": "boson", "audio_sent": False,
                              "anthropic_called": False, "synthetic_input": True}
    try:
        roster = presets.personas()
        transcript = TranscriptSegment(start_ms=33000, end_ms=36000,
                                      text="We can get 100,000 customers in six months.")
        ctx = OrchestratorContext(
            preset_id="startup_pitch", difficulty="normal",
            personas=[roster["vc"], roster["student"], roster["professor"]],
            slide_number=3, slide_text="Traction: two campus pilots, 300 weekly active users.",
            recent_transcript=[transcript], question_allowed=True, eligible_kinds=[])
        async with asyncio.timeout(55):
            question = await brain.decide(ctx)
            result["question"] = question.model_dump()
            if question.action != "question" or not question.line or not question.persona_id:
                raise ValueError("No grounded question returned")
            follow = await brain.follow_up(question.line, "It is just our estimate.",
                                          roster[question.persona_id], used=0)
            result["follow_up"] = follow.model_dump()
            recovery = await brain.assess_recovery("slides_down", "The projector disconnected.",
                [TranscriptSegment(start_ms=128400, end_ms=131000,
                                   text=("The problem is slow onboarding. "
                                         "Our pilot measures retention."))],
                3400)
            result["recovery"] = recovery.model_dump()
            custom = await brain.expand_persona(
                "a fictional product operator who challenges customer retention evidence", 1)
            result["custom_persona"] = custom.model_dump()
        diagnostic = brain.diagnostics()
        totals = diagnostic["totals"]
        if (totals["attempts"] != 4 or totals["successes"] != 4
                or any(totals[k] for k in ("failures", "fallbacks", "rejections"))
                or diagnostic["last_response_model"] != brain.model):
            raise ValueError("Live reasoning preflight did not pass all four operations")
        result["status"] = "pass"
    except Exception as exc:
        result["error_class"] = type(exc).__name__
    result.update({"checked_at_utc": datetime.now(UTC).isoformat(),
                   "runtime_s": round(time.monotonic() - started, 3),
                   "reasoning": brain.diagnostics(), "budget": budget_status()})
    out = ROOT / "data" / "voice_checks" / "boson_audience_preflight.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Use existing Boson API credits")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to allow four bounded text reasoning requests.")
    raise SystemExit(asyncio.run(main()))
