# PROGRESS.md

One checkpoint report per Claude Code session, appended, never edited. Template: CLAUDE.md §14.

## SESSION-0 · 2026-10-23 · scaffold · session 0
Built: repository skeleton — CLAUDE.md, PRIORITIES.md, DECISIONS.md, contracts + generated schema, FastAPI wiring with REST/WS routes and static mounts, engine/scheduler/curveballs/audience/report/slides as signed skeletons with `TODO(owner)` bodies, voice seam (protocol, mock, Higgs skeleton), persona roster + four presets, frontend pages with wired controls and mock replay, three mock fixtures, tests as the acceptance spec.
Tests: test_contracts.py (green), test_scheduler.py, test_curveballs.py, test_e2e_mock.py (red by design — the spec for P0-5/6/8/9/12)
Gate: lint, type, schema, mocks green; pytest red by design at this commit (see DECISIONS "Gate")
Demo path: all steps "mock" (demo/DEMO_STATUS.md)
Files outside my paths: n/a (scaffold)
Proposed decision changes (not implemented): none
Next: P0-2 (B), P0-3 + P0-7 on mocks (A), P0-8 then P0-5 (C) — all unblocked
Open question for the team: whose Anthropic key, and its monthly cap (CLAUDE.md §15 Q6)

## P0-8 · 2026-10-23 · C · session 1
Built: the scheduler — eligibility as a pure function of a snapshot (phase, slide transition, cooldown scaled by interruption frequency, question/curveball budgets per difficulty, curveball mode off/choose/surprise) plus the curveball trigger rules in `curveballs.eligible_kinds` (min elapsed, ≥50 % of target for time_crunch, never slide 1, pause vs mid-speech, no repeats).
Tests: test_scheduler.py 10/10 green; test_curveballs.py eligible-kinds tests green (the 4 trigger/resolve tests stay red for P0-9)
Gate: lint, type, schema, mocks green; pytest 17 passed / 9 failed (remaining red = P0-5/6/9/12 spec)
Demo path: unchanged
Files outside my paths: none
Proposed decision changes (not implemented): none
Next: P0-9 (curveball engine trigger/resolve/measure_recovery), because P0-8 now passes; then P0-5 via engine.tick/_maybe_interrupt
Open question for the team: none

## P0-8 · 2026-10-23 · fix 1
Fixed: cooldown values moved inside the 30–45 s band the rules state (rare 45 s, normal 40 s, often 30 s); choose-mode kinds deduplicated. Review notes carried to P0-9/P0-5: slides_down should also be able to fire on a slide change (needs_pause blocks it today); heckler's "value proposition detected" trigger belongs to the orchestrator; at_pause needs a speech_started/stopped signal once Higgs is wired (final-only transcripts).
Evidence: test_scheduler.py 10/10, ruff, pyright
Gate: green at the fix commit (pytest 17/9 as before)
