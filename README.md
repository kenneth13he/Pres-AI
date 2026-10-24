# PresAI

An AI audience that listens to your presentation, interrupts with grounded questions, throws realistic curveballs (projector dies, "you've got 60 seconds", a heckler), speaks in distinct voices, and ends with a report card that quotes what you actually said.

**Read `CLAUDE.md` first.** It is the house rules and the shared source of truth: scope, priorities, contracts, team split, hour gates, vendor facts, money rules. Then `PRIORITIES.md` for what to build next, `DECISIONS.md` for what is settled, `demo/DEMO_STATUS.md` for what is live.

**Using the optimized `feat/optimized-presentation-room` branch? Read [COLLABORATOR_HANDOFF.md](COLLABORATOR_HANDOFF.md).** It covers the current build, setup, test evidence, remaining checks, and the next work for each owner.

## Run it

```bash
make setup        # .venv, pinned deps, .env from .env.example, schema
make dev          # http://localhost:8000  (API + frontend, one process)
make check        # the gate: ruff + pyright + schema + mock fixtures + pytest
node --test --test-timeout=5000 scripts/test_*.mjs  # browser/audio checks; Node required
```

Without keys everything runs on mocks: `VOICE_ADAPTER=mock`, `ORCHESTRATOR=mock`. The room can be built and demoed with no backend at all at `/room.html?mock=1` (replays `frontend/mocks/demo_session.json`) and `/report.html?mock=1`.

Setup needs Python 3.12 or newer (or `uv`) and Node with `--test-timeout` support.
Offline checks and mock mode make no vendor calls. The page styling still loads Tailwind
from a CDN, so normal styling requires internet access or an already cached CDN asset.

For live Boson voice and audience reasoning, privately set `BOSON_API_KEY`,
`VOICE_ADAPTER=higgs`, and `ORCHESTRATOR=boson` in `.env`. Keep
`BOSON_AVATAR_ENABLED=false` and `DEBUG_CURVEBALL_ENDPOINT=false` for presentation
checks. This uses Boson API credits. An Anthropic key is needed only if the team
chooses `ORCHESTRATOR=claude`. Hold-to-talk is the room default.

## Layout

```
CLAUDE.md               house rules + spec        PRIORITIES.md   ordered build list
DECISIONS.md            settled, dated            PROGRESS.md     one checkpoint per session
spec/contracts.py       THE types (pydantic)      spec/contracts.schema.json  generated (make schema)
spec/curveballs.md      curveball catalog
backend/main.py         FastAPI: REST + WS + static frontend
backend/engine.py       session state machine (C)
backend/services/       scheduler · curveballs · audience (Boson/Claude/mock) · report · slides (C)
                        voice_base · voice_mock · voice_higgs (B)
backend/scenarios/      personas.yaml + presets (content, anyone)
backend/tests/          the spec as tests; red until the owning priority lands
frontend/               static HTML/CSS/ES-module JS, Tailwind CDN, no build (A)
frontend/mocks/         fixtures the frontend is built against; validated by make mocks
demo/                   DEMO_STATUS.md, demo_script.md, sfx/, sample deck
docs/archive/           the original plan this grew from
```

## Current state

The optimized branch combines the premium dark redesign, five-step setup and reusable local
profiles, persistent Continue actions, adaptive layouts for 1–3 guests, and whole static portraits with
blurred backdrops. Without slides, the audience fills the stage. It retains the verified voice/backend lifecycle; camera and avatar
videos remain off. The UI is selectively adapted from `9df73d3`, `5274a12` and `b783dce`.

The presentation room includes live Boson transcription, streamed persona speech,
hold-to-talk controls, real audience reasoning, static portraits, an audience builder,
curveballs, Q&A, and reports from actual session events. Offline backend and browser
checks pass. Two human presentation flows completed; final clean-demo and recording
sign-off remain open. The handoff separates original test evidence from subsequent
fixes and the focused checks still needed.

Reports now include a bounded text-coaching pass with evidence resolved from captured
source IDs. Unsupported dimensions remain unassessed; recovery timing and event metrics
stay deterministic. Audio stops before grading, and the report page automatically waits
for feedback. Current checks: **309 backend + 188 frontend tests**. Unexpected audio loss
automatically pauses the room; Resume reconnects before either timer continues. The additional opt-in
`scripts/try_report_assessment.py --live` probe uses fictional text and one real Boson
grading call; it is separate from human presentation acceptance.

Owners: **A** frontend/demo UX · **B** voice (Higgs) · **C** backend/brain/curveballs/report.
