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

## P0-9 · 2026-10-23 · C · session 2
Built: the curveball engine — `trigger` (record + `curveball_triggered` payload per §7, persona kept only for persona speakers, default line when none generated, sfx_url for clips), `active`, `due_for_auto_resolve`, `resolve` (`skipped` → recovery None), and `measure_recovery` (resume_after_ms from the earliest presenter segment after the event; None with a note when there is none — never 0). Closed the review note: a slide change now counts as a pause for 1.5–6 s after it, so `slides_down` can fire "on a slide change" (§6.2).
Tests: test_curveballs.py 10/10 (3 new: speaker/persona rule, generated line + sfx, out-of-order/AI segments); test_scheduler.py 13/13 (3 new: slide-change pause window, curveballs_enabled=False, budget exhaustion)
Gate: ruff, pyright, schema, mocks green; pytest 27 passed / 5 failed (remaining red = the e2e spec for P0-5/6/12)
Demo path: unchanged (engine wiring is P0-5/6)
Files outside my paths: none
Proposed decision changes (not implemented): none
Next: P0-5 + P0-6 — engine.py start/slide_changed/presenter_transcript/tick/_maybe_interrupt/_ask/_handle_answer/_speak/_fire_curveball/_resolve and MockOrchestrator.decide/follow_up/assess_recovery, because P0-8 and P0-9 now pass
Open question for the team: none

## P0-5 + P0-6 (+ P0-12 C half) · 2026-10-23 · C · session 3
Built: the engine (`backend/engine.py`) — start, slide_changed, presenter_transcript, tick (time_crunch deadline → Q&A, auto-resolve, scheduler → orchestrator → ask/fire), questions with one follow-up max, _speak via the voice seam, curveball firing (answerable kinds become a pending question; time_crunch keeps presenting; others recover), _resolve with the orchestrator's recovery assessment merged into the event, pause/resume/skip/restore_slides/end, Q&A step, finish → report. `MockOrchestrator` bodies: claim detection → grounded question from the most skeptical persona, thin-answer follow-up, timing-based recovery score, custom-persona expansion. `build_report`: fillers/WPM only from timestamped transcript with caveats, recovery dimension from scored curveballs, improvements with evidence quotes, key moments, persona feedback, unanswered count.
Tests: test_e2e_mock.py 8/8 (5 spec + heckler answered→resolved, one-event-at-a-time + cooldown, restore_slides + Q&A flow); test_report.py 4/4 (nulls with caveats, fillers+WPM, WPM null without end times, unanswered named); suite 39/39
Gate: ruff, pyright, schema, mocks, pytest all green — first fully green gate
Demo path: steps 4–8 now run on the mock orchestrator end to end (DEMO_STATUS.md to be flipped after review)
Files outside my paths: none
Proposed decision changes (not implemented): none
Next: P0-4 (slides.ingest_pdf) and the C half of P0-3b (ClaudeOrchestrator bodies incl. expand_persona), because the engine now runs
Open question for the team: none

## P0-5 + P0-6 · 2026-10-23 · fix 1
Fixed (per pre-merge review): pause is frozen — every stored timestamp shifts by the paused duration on resume, so the resume gap, the 60 s crunch, auto-resolve and cooldowns never count paused time, and transcript during pause is ignored; `vip_arrives` (and any answerable kind with a moderator voice) now assigns an answering persona instead of sticking in `recovering`; Skip targets the pending question (marked `skipped`, never "unanswered") or a non-time_crunch curveball, never the crunch itself; `time_crunch` resolves at the deadline on its own metric (no resume gap, no invented score) and starts the cooldown when it fires; `restore_slides` ignored while paused; explicit `in_qna` flag, End during a Q&A answer finishes; AI segments are never answers; every voice/LLM call is wrapped so a failure is an `error` event and the phase still moves; `RecoveryAssessment.score/evidence` nullable so "no speech after the event" is null not 0; mock claim regex no longer fires on greetings/ordinals, dedupes on the cited sentence, rotates personas; report counts skipped questions as skipped, not unanswered. Timebase pinned: all timestamps are ms since Start (session clock); main.py converts.
Evidence: 9 new regression tests in test_e2e_mock.py; suite 48/48; live WebSocket smoke run (pause/resume/end, session-relative timestamps)
Gate: green at the fix commit
Notes for A: an answerable curveball emits both `curveball_triggered` and `question_queued` (same line, `curveball_id` set) — caption only one. Notes for B: the engine emits its own `ai_speech_ended` floor; a live adapter's own end event should replace it, not duplicate it.

## P0-5 + P0-6 · 2026-10-23 · fix 2
Fixed (per second review): curveball `at_ms` is no longer shifted on resume — recovery timing subtracts the recorded pause intervals instead, so a pause after an early resume cannot inflate a measured gap and the report's times agree with the event log; a question the room cuts off (End, crunch expiry) is `skipped` with a reason and a `skipped` event, never "unanswered"; curveball pseudo-questions are excluded from the unanswered count; `enter_qna` disarms the crunch deadline and resolves an open crunch as `answered` when the presenter closes early (`timed_out` only at the deadline); `in_qna` is set before resolving so there is no detour through presenting; `_resolve` on an already-resolved record still restores the phase; REST `elapsed_ms` fixed (`start_ms is not None`); mock follow-up wording varies by persona and question; persona feedback quotes root questions, not follow-ups.
Evidence: 4 new regression tests; suite 52/52; gate green
Gate: green at the fix commit

## P0-4 · 2026-10-23 · C · session 4
Built: `slides.ingest_pdf` — PyMuPDF opens the upload from bytes, per page extracts cleaned text and renders a 96-dpi PNG under `data/decks/<id>/<n>.png` (served at `/decks/...`); presenter-safe `DeckError`s for not-a-PDF, encrypted, empty and >60 pages, mapped to HTTP 400 in `/api/slides`.
Tests: test_slides.py 5/5 (text + PNG, 1-based `slide_text`, text cleaning, bad inputs, the HTTP route end to end incl. PNG serving); suite 57/57
Gate: ruff, pyright, schema, mocks, pytest green
Demo path: step 2 (upload PDF, slides render) now backend-live; needs A's `renderSlide` to show on screen
Files outside my paths: pyproject.toml (pytest filterwarnings for the pymupdf/swig DeprecationWarning on 3.12)
Proposed decision changes (not implemented): none
Next: C half of P0-3b — `ClaudeOrchestrator` bodies (decide / follow_up / assess_recovery / expand_persona) behind the mock-tested seam, because the engine and slides now run
Open question for the team: none

## P0-4 · 2026-10-23 · fix 1
Fixed (per review): `demo/sample_pitch.pdf` added (6-slide fictional Startup Pitch deck, generated with PyMuPDF — the §13 stage-recovery deck); ligatures expanded in extracted text so slide lines match the transcript; ingest runs in a threadpool so a big deck never stalls the rooms; 50 MB upload cap with a presenter-safe 400; route test cleans up the deck folder and the in-memory entry it creates; wrong AES fallback dropped.
Evidence: test_slides.py 6/6 (ligature case added); suite 58/58; `data/decks` count unchanged across a test run
Gate: green at the fix commit

## P0-3b (C half) · 2026-10-23 · C · session 5
Built: the real `ClaudeOrchestrator` — official `anthropic` SDK, `messages.parse` with structured outputs on `claude-opus-5-5`, adaptive thinking with effort low (decide / follow-up) and high (recovery); byte-stable system prompts with everything variable in the user turn; an 8 s timeout (`ORCHESTRATOR_TIMEOUT_S`); refusals and disallowed answers fall back to "none" / satisfied / null, never an exception that the engine can't absorb; evidence must be a verbatim transcript quote or it is replaced; `expand_persona` turns free text into a labelled custom `Persona`. Client is injectable, so all of it is tested offline. `scripts/try_orchestrator.py` makes one live call per prompt once a key is in `.env`.
Tests: test_claude_orchestrator.py 7/7 (context formatting, call shape, guards, refusal, one-follow-up rule, null recovery, verbatim evidence, persona expansion + fallback, timeout); suite 65/65
Gate: green at the commit
Demo path: the brain can go live with `ORCHESTRATOR=claude` + `ANTHROPIC_API_KEY` — not yet exercised against the live API (needs the key: §15 Q6)
Files outside my paths: .env.example (ORCHESTRATOR_TIMEOUT_S)
Proposed decision changes (not implemented): none
Next: all C-owned P0 lines are done; remaining C work is integration (P0-13) once A's room and B's voice land, then P1-2 curveballs and P1-4 fillers/WPM polish
Open question for the team: whose Anthropic key, and its monthly cap — run `scripts/try_orchestrator.py` once it is in `.env`

## P0-3b (C half) · 2026-10-23 · fix 1
Fixed (per review, verified against the installed SDK 2.3.0): the SDK validates the JSON before `stop_reason` is visible, so a refusal with text, a truncated reply or a constraint violation raised instead of falling back — `_parse` now catches `ValidationError` and `anthropic.APIError` and treats `refusal`/`max_tokens` as "no answer"; `expand_persona` never raises (session creation can't 500 on the brain) and scrubs `voice_id`/`avatar_url`; `decide` enforces grounding — a question needs a ≥3-word excerpt found verbatim (quotes/case/whitespace-insensitive, across segment boundaries) in the recent transcript, a roster `persona_id`, and the slide actually shown; the system prompt says so; recovery gets an 8192-token budget and the same verbatim rule; client built with `max_retries=1` so the 8 s window is real; `try_orchestrator.py` exits early without a key.
Evidence: 6 new tests, four of them through the real `anthropic` client over an `httpx2.MockTransport` (refusal text, truncation, 401, valid reply) — the path the fake client bypassed; suite 71/71
Gate: green at the fix commit

## P0-3b (C half) · 2026-10-23 · fix 2
Fixed: live check against the real API passed for all four prompts (results in DECISIONS "Brain", latencies in DEMO_STATUS); the high-effort recovery call gets its own 15 s budget (`ORCHESTRATOR_SLOW_TIMEOUT_S`) since it measured 6.4 s; custom-persona `plays` filtered to persona-voiced kinds (the live model also listed moderator kinds).
Evidence: `scripts/try_orchestrator.py` output 22:50; timing run decide 2.6/2.2 s, follow_up 2.1 s, recovery 6.4 s
Gate: green at the fix commit
Note for later (P1): `assess_recovery` runs inside the room lock, so the room holds ~6 s at the moment a curveball resolves. Acceptable for the demo (nothing else is due at that instant); making it a background task needs a new `recovery_assessed` event in the contract — A's call.

## Backend live run · 2026-10-23 · C · session 6
Built: nothing new — the whole backend exercised live over WebSocket with `ORCHESTRATOR=claude`: custom persona expanded in 3.5 s; grounded VC question at 30.0 s quoting the claim verbatim and contrasting it with the slide; one follow-up; pause/resume; `slides_down` forced, restored, resume gap measured (6.2 s) and scored 80 by the rubric; Q&A; report with the real quote. Zero `error` events. The run exposed one gap, fixed here: the closing Q&A demanded a verbatim transcript quote and ended instantly — Q&A now tells the model it is the closing round and accepts a question grounded in the slides alone.
Tests: +1 (Q&A grounding); suite 72/72
Gate: green at the commit
Demo path: backend side of steps 2–8 live (DEMO_STATUS.md); A's room and B's voice are the remaining mocks
Files outside my paths: none
Proposed decision changes (not implemented): none
Next: integration support for A/B; P1-2/P1-4 are already in place by construction and get flipped when A can show them
Open question for the team: Anthropic monthly cap (we have spent well under $1 so far)

## P0-3 + P0-3b (A) + P0-7 + P0-10 + P0-12 (A) · 2026-10-24 13:50 · A · session 1
Built: frontend redesign from the design handoff (docs/design/, references only, not served): premium-dark homepage with a self-playing demo room; 5-step setup wizard (profile → slides → room → audience with custom guests → curveballs) with a live room preview; event-driven live room (room layouts per setting, speaking ring, tile flash, blackout + Restore, dim, blank, VIP tile, crunch timer, captions, P/S/←/→); report card — all through the existing api.js / WebSocket seams.
Tests: no new Python tests; mock fixture gains a heckler curveball (`make mocks`). Verified by driving headless Chrome: mock replay incl. pause/restore; live run on the real engine (mock orchestrator/voice): sample deck upload → room with slide PNGs → grounded question quoting the claim → follow-up → `slides_down` blackout → Restore → "back on track after 2.6 s" → Q&A → report with the quote and score 85.
Gate: green (lint, pyright, schema, mocks, pytest 72/72) on the rebased branch
Demo path: steps 1, 2, 6, 8 → live (A side); steps 3–5 still wait on B's voice/STT
Files outside my paths: docs/design/ (handoff files); mic.js level meter (the TODO(A) half only)
Proposed decision changes (not implemented): the design allows 1–10 guests; SessionConfig caps personas at 2–3, so the UI caps at 3 (`MAX_GUESTS` in frontend/js/rooms.js). Profile (role/goal/level/tone), room setting and presentation context have no contract fields and stay in localStorage — C to decide whether the orchestrator should see them.
Next: P1-1 (demo-path polish)
Open question for the team: B — custom guests send `voice_id` (a preset name or a Boson voice id); cloned voices need a backend route that calls `POST /v1/audio/voices` once and stores the id; until then they use the default voice (said on screen).
