"""One live call per prompt against the real Claude orchestrator. Costs a few cents.

Usage (needs ANTHROPIC_API_KEY in .env):
    .venv/bin/python scripts/try_orchestrator.py

Why: the offline tests prove formatting and fallbacks; this proves the key, the model id and
the structured-output shapes against the live API before hour 10 (CLAUDE.md §4).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from backend import presets  # noqa: E402
from backend.services.audience import ClaudeOrchestrator, OrchestratorContext  # noqa: E402
from spec.contracts import TranscriptSegment  # noqa: E402


async def main() -> int:
    orch = ClaudeOrchestrator()
    roster = presets.personas()
    ctx = OrchestratorContext(
        preset_id="startup_pitch", difficulty="normal",
        personas=[roster["vc"], roster["student"], roster["professor"]],
        slide_number=3, slide_text="Traction\n• Two campus pilots\n• 300 weekly actives",
        recent_transcript=[TranscriptSegment(
            start_ms=33_000, end_ms=36_000,
            text="We can get 100,000 customers in six months.")],
        question_allowed=True, eligible_kinds=["slides_down"], curveball_budget_remaining=1,
        seconds_since_last_event=None,
    )
    print("decide →", (await orch.decide(ctx)).model_dump_json(indent=2))
    print("follow_up →", (await orch.follow_up(
        "What evidence supports 100,000 customers?", "We plan to grow through universities.",
        roster["vc"], used=0)).model_dump_json(indent=2))
    print("assess_recovery →", (await orch.assess_recovery(
        "slides_down", "Sorry — the projector just disconnected. Can you keep going?",
        [TranscriptSegment(start_ms=128_400, end_ms=131_000,
                           text="So, the problem again is onboarding.")],
        3_400)).model_dump_json(indent=2))
    print("expand_persona →", (await orch.expand_persona(
        "my thesis committee chair who hates jargon", 1)).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
