# PresAI

An AI audience that listens to your presentation, interrupts with grounded questions, throws realistic curveballs (projector dies, "you've got 60 seconds", a heckler), speaks in distinct voices, and ends with a report card that quotes what you actually said.

**Read `CLAUDE.md` first.** It is the house rules and the shared source of truth: scope, priorities, contracts, team split, hour gates, vendor facts, money rules. Then `PRIORITIES.md` for what to build next, `DECISIONS.md` for what is settled, `demo/DEMO_STATUS.md` for what is live.

## Try the live call (branch `feat/voice-room`)

You present to three AI panelists on a video call. They have live, lip-synced Higgs faces,
interrupt, follow up and throw curveballs, and the call ends with a report card that quotes
what you said.

1. `make setup`, then fill in `.env`: `BOSON_API_KEY`, `ANTHROPIC_API_KEY`, the three
   `LIVEKIT_*` values (a LiveKit Cloud project), and set `VOICE_ADAPTER=higgs`,
   `ORCHESTRATOR=claude`, `BOSON_AVATAR_ENABLED=true`.
2. `make dev`, then wait until http://localhost:8000/health shows all three `faces` as
   `live`. Higgs is slow and flaky to start avatars; it can take a few minutes after boot.
   The faces then stay up across calls (about $12/h for three while the server runs).
3. Open http://localhost:8000, pick a preset, Join, and talk. **Use headphones.** Your mic
   is always on, and Higgs STT does the speech-to-text on the server (Chrome's own
   recognizer was unreliable). End → Finish shows the report card after about 10 s.

## Run it

```bash
make setup        # .venv, pinned deps, .env from .env.example, schema
make dev          # http://localhost:8000  (API + frontend, one process)
make check        # the gate: ruff + pyright + schema + mock fixtures + pytest
```

Without keys everything runs on mocks: `VOICE_ADAPTER=mock`, `ORCHESTRATOR=mock`. The room can be built and demoed with no backend at all at `/room.html?mock=1` (replays `frontend/mocks/demo_session.json`) and `/report.html?mock=1`.

## Layout

```
CLAUDE.md               house rules + spec        PRIORITIES.md   ordered build list
DECISIONS.md            settled, dated            PROGRESS.md     one checkpoint per session
spec/contracts.py       THE types (pydantic)      spec/contracts.schema.json  generated (make schema)
spec/curveballs.md      curveball catalog
backend/main.py         FastAPI: REST + WS + static frontend
backend/engine.py       session state machine (C)
backend/services/       scheduler · curveballs · audience (Claude) · report · slides (C)
                        voice_base · voice_mock · voice_higgs (B)
backend/scenarios/      personas.yaml + presets (content, anyone)
backend/tests/          the spec as tests; red until the owning priority lands
frontend/               static HTML/CSS/ES-module JS, Tailwind CDN, no build (A)
frontend/mocks/         fixtures the frontend is built against; validated by make mocks
demo/                   DEMO_STATUS.md, demo_script.md, sfx/, sample deck
docs/archive/           the original plan this grew from
```

## State of the scaffold

This is a **skeleton**: contracts, wiring, interfaces, tests and docs are real; the bodies marked `TODO(A|B|C)` are yours. `make check` is green on lint/type/schema/mocks and **red on tests by design** — each test file is the acceptance spec for a `PRIORITIES.md` line and goes green when that line lands (CLAUDE.md §12, step 3).

Owners: **A** frontend/demo UX · **B** voice (Higgs) · **C** backend/brain/curveballs/report.
