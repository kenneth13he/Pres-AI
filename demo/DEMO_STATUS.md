# DEMO_STATUS.md

The demo path's current state. Updated at every hour gate (CLAUDE.md §4). The judges' demo runs only what is marked **live**. Values: `mock` · `fallback` (what the fallback is) · `live`.

Last updated: 2026-10-23 scaffold (hour 0)

| # | Demo step (CLAUDE.md §13 script) | State | Notes |
|---|---|---|---|
| 1 | Pick preset / build audience on `/setup` | mock | pages exist, builder is TODO(A) |
| 2 | Upload PDF, slides render in room | mock | `services/slides.py` TODO(C) |
| 3 | Presenter speaks, transcript appears | mock | Shape undecided; browser-STT fallback planned in `mic.js` |
| 4 | VC asks a grounded question in its own voice | mock | orchestrator + voice TODO |
| 5 | Presenter answers, VC follows up once | mock | |
| 6 | `slides_down` fires, viewer goes black | mock | fixture `demo_session.json` plays it |
| 7 | Presenter resumes; recovery seconds measured | mock | |
| 8 | Q&A, then report with evidence quotes | mock | `report.json` fixture |
| — | Backup recording exists in `demo/` | no | P0-14 |

## Hour gates

| Hour | Gate | Outcome |
|---|---|---|
| 1 | Contracts merged; all three run `make check` | scaffold: yes |
| 3–4 | Voice round trip | — |
| 5 | Live audio + one spoken question | — |
| 8 | Avatar decision | — |
| 10 | One curveball end-to-end with a recovery metric | — |
| 15 | P1 freeze | — |
| 18 | UI/audio/integration freeze | — |
| 21 | Two clean runs recorded; backup video | — |

## Spend (from `/health`)

| When | TTS chars | Realtime min | Estimate USD |
|---|---|---|---|
| hour 0 | 0 | 0 | 0.00 |
