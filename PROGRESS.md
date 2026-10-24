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
