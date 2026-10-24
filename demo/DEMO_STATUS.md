# DEMO_STATUS.md

The demo path's current state. Updated at every hour gate (CLAUDE.md §4). The judges' demo runs only what is marked **live**. Values: `mock` · `fallback` (what the fallback is) · `live`.

Last updated: 2026-10-23 22:55 (C: backend P0 complete, brain live-checked)

| # | Demo step (CLAUDE.md §13 script) | State | Notes |
|---|---|---|---|
| 1 | Pick preset / build audience on `/setup` | mock | pages exist, builder is TODO(A) |
| 2 | Upload PDF, slides render in room | backend live | `/api/slides` + PNGs served; room `renderSlide` TODO(A) |
| 3 | Presenter speaks, transcript appears | mock | Shape undecided; browser-STT fallback planned in `mic.js` |
| 4 | VC asks a grounded question in its own voice | brain live, voice mock | Claude `decide` 2.2–2.6 s live-checked; voice TODO(B) |
| 5 | Presenter answers, VC follows up once | brain live, STT mock | `follow_up` 2.1 s live-checked; transcript source TODO(B) |
| 6 | `slides_down` fires, viewer goes black | backend live | engine fires + resolves; overlay TODO(A) |
| 7 | Presenter resumes; recovery seconds measured | backend live | measured gap + Claude rubric score (6.4 s) |
| 8 | Q&A, then report with evidence quotes | backend live | `build_report`; report page TODO(A) |
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
| 22:55 | 0 | 0 | 0.00 (Higgs untouched; ~$0.10 Anthropic on 8 live calls) |
