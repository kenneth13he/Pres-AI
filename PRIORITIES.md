# PRIORITIES.md

The ordered build list (CLAUDE.md §3). You change `done` and `blocked by` and nothing else; a new line or a reorder is a team decision recorded in `DECISIONS.md`. Take the first undone line with your name that is not blocked.

Format: `priority · id · owner · done · blocked by · what`

## P0 — the demo does not exist without it

| P | id | owner | done | blocked by | what |
|---|---|---|---|---|---|
| P0 | P0-1 | C | yes (scaffold) | — | `spec/contracts.py` + schema, scenario YAML, `.env.example`, `Makefile`, repo scaffold |
| P0 | P0-2 | B | no | — | Mic → model → spoken reply round trip (hour-1 tests 1–5 in CLAUDE.md §13) |
| P0 | P0-3 | A | yes | — | Setup flow: preset picker, PDF drop, Start — three clicks to `/room` |
| P0 | P0-3b | A (+C) | C done; A builder done (custom guests with photo + voice are sent as full `Persona`s and seated); a custom guest asking live is not yet run | — | Audience builder: roster picker, custom persona text, skepticism, curveball picker |
| P0 | P0-4 | C | yes | — | PDF upload → per-slide text + PNG (`services/slides.py`) |
| P0 | P0-5 | C | yes (mock orchestrator + engine; Claude bodies land with P0-3b) | — | Orchestrator: one grounded question quoting the transcript (`test_e2e_mock::test_claim_question_answer_follow_up`) |
| P0 | P0-6 | C | yes | — | Answer → follow-up (max 1) → hand back |
| P0 | P0-7 | A | yes | — | Room UI on mocks: slide viewer, tiles, speaking state, captions, timer, Pause/Skip/End |
| P0 | P0-8 | C | yes | — | Scheduler: one speaker, cooldowns, caps, no repeats (`test_scheduler.py`) |
| P0 | P0-9 | C | yes (engine; e2e wiring lands with P0-5/6) | — | Curveball engine: slides_down / time_crunch / heckler + recovery tracking (`test_curveballs.py`, e2e) |
| P0 | P0-10 | A | yes | — | Curveball UI effects for the three MVP kinds, from mocks |
| P0 | P0-11 | B | no | P0-2 | Persona voices (or one voice + labels) and a neutral moderator voice |
| P0 | P0-12 | A + C | yes (page renders a real session's report, run 24 Oct) | — | Report page: dimensions, Recovery card, key moments, evidence quotes |
| P0 | P0-13 | all | no | all P0 | End-to-end live run, twice in a row, nobody touching it |
| P0 | P0-14 | all | no | P0-13 | Backup screen recording in `demo/` |

## P1 — only after your P0 is green

| P | id | owner | done | blocked by | what |
|---|---|---|---|---|---|
| P1 | P1-1 | A | no | P0-7 | Demo-path polish: transitions, tile animations, empty/loading/error states, reconnect, shortcuts |
| P1 | P1-2 | C (+B) | no | P0-9 | Curveballs latecomer, bait, distraction, vip_arrives |
| P1 | P1-3 | B | no | P0-11 | Heckler voice with `<\|emotion:anger\|>`; distinct moderator preset voice |
| P1 | P1-4 | C | no | P0-12 | Filler words and WPM with the accuracy caveat shown |
| P1 | P1-5 | A + B | no | P0-12 | Report polish: persona feedback spoken in their voices; share-as-image |
| P1 | P1-6 | C + A | no | P0-12 | Session history (local JSON) |

## P2 — stretch; never blocks anything

| P | id | owner | done | blocked by | what |
|---|---|---|---|---|---|
| P2 | P2-1 | B | no | all P1, >$40 credit left | One talking-head avatar (synthetic portrait) |
| P2 | P2-2 | C | no | P1-2 | Curveballs crosstalk, fact_check, elevator, plain_language, dead_room |
| P2 | P2-3 | B | no | P0-2 | Audio-understanding delivery observations, only if grounded |
| P2 | P2-4 | B + C | no | — | Multi-language presenting |
| P2 | P2-5 | A + C | no | P0-12 | Shareable report link |
