"""Live check of the panel brain on realistic moments of a call. Costs a few cents.

Usage (needs ANTHROPIC_API_KEY in .env):
    .venv/bin/python scripts/try_orchestrator.py

Why: the offline tests prove formatting and fallbacks; this shows whether the panel actually
behaves like people (and how fast) against the live API.
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
from backend.services.audience import ClaudeOrchestrator, Line, OrchestratorContext  # noqa: E402
from spec.contracts import TranscriptSegment  # noqa: E402


async def main() -> int:
    import os
    import time

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is empty in .env — nothing to try.", file=sys.stderr)
        return 2
    orch = ClaudeOrchestrator()
    roster = presets.personas()
    panel = [roster["vc"], roster["student"], roster["professor"]]

    def ctx(lines: list[tuple[str, str]], **kw: object) -> OrchestratorContext:
        convo = [Line(who, text, i * 4000) for i, (who, text) in enumerate(lines)]
        base: dict = dict(preset_id="startup_pitch", difficulty="normal", personas=panel,
                          slide_number=1, slide_text="", conversation=convo, elapsed_s=60,
                          seconds_since_panel_spoke=40)
        base.update(kw)
        return OrchestratorContext(**base)

    moments = {
        "joined": ctx([], trigger="joined", seconds_since_panel_spoke=None, elapsed_s=0),
        "hearing check": ctx([("presenter", "Hi everyone, can you hear me okay?")]),
        "mid-flow": ctx([("presenter", "So today I'm going to walk you through PresAI."),
                         ("presenter", "It's a rehearsal tool for presentations.")]),
        "big claim": ctx([("presenter", "PresAI is a rehearsal tool."),
                          ("presenter", "We can get 100,000 customers in six months.")]),
        "answer": ctx([("presenter", "We can get 100,000 customers in six months."),
                       ("vc", "Where does 100,000 come from?"),
                       ("presenter", "We'll grow through universities.")],
                      open_question=Line("vc", "Where does 100,000 come from?", 4000)),
        "invites questions": ctx([("presenter", "That's the pitch. Any questions?")]),
    }
    for name, c in moments.items():
        t0 = time.perf_counter()
        turn = await orch.turn(c)
        took = time.perf_counter() - t0
        who = turn.persona_id or ''
        print(f"{name:18} {took:4.1f}s  {turn.action:9} {who:10} {turn.line or ''}")
    print("assess_recovery →", (await orch.assess_recovery(
        "slides_down", "Sorry — the projector just disconnected. Can you keep going?",
        [TranscriptSegment(start_ms=128_400, end_ms=131_000,
                           text="So, the problem again is onboarding.")],
        3_400)).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
