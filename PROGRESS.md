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

## P0-2 + voice integration · 2026-10-23 · B · local session 1
Built: isolated Python 3.12.14 checkout on feat/voice from 302c44b; private ignored Boson config; manual-commit browser Higgs STT with live VAD/PTT and capture timestamps; streamed backend TTS with persona presets/styles on a separate binary socket, playback ACK, cancellation, timeouts, cleanup and safe errors; room microphone bridge and standalone voice-check page; Mac setup/start launchers and local validation guide. Shape 2 chosen; no autonomous vendor audience responses.
Tests: 72-test baseline; final gate 94 backend tests plus 16 deterministic audio/bridge tests; live TTS/STT/Realtime script+voice update/ephemeral auth and local binary transport; synthetic transcript through the real engine + live Boson TTS produced two speech turns and a report with zero error events. No human mic/listening/browser runtime verification (preview access declined).
Gate: lint, type, schema, mocks, pytest and audio tests green locally; changes uncommitted and unpushed
Demo path: voice implementation local; actual mic/audible latency and persona-distinction checks pending, no new stage-live claim. No Anthropic key on this Mac; audience brain runs on mock.
Files outside my paths: backend/main.py + new backend/voice_routes.py (voice socket/auth/callback wiring), backend/engine.py (playback-based timestamps and stale-answer guard), frontend/js/room.js (voice bridge/control lifecycle), backend/tests/test_voice_* (offline regressions), pyproject.toml (explicit Python 3.12 for this Mac's type checker), .gitignore (synthetic diagnostic outputs), setup/start scripts and docs/status files (local setup and evidence). Owner notification deferred because no collaborator messaging was authorized; review these integration seams before merging.
Proposed decision changes (not implemented): none
Next: P0-2 hardware check at /voice-check.html, then P0-11 listening distinction, then coordinate P0-13 with A/C
Open question for the team: real mic-to-audible latency under ~2 s and voice distinction on the demo laptop; Anthropic key/quota remains with C

## P0-11 human validation · 2026-10-24 00:18 EDT · B
Built: no new code; guided the user through the local browser voice check.
Tests: user confirmed moderator playback clear/complete and moderator, Dana and Sam clear/distinct.
Gate: P0-11 listening accepted; P0-2 microphone/latency check ongoing
Demo path: local persona voice playback human-verified; full presentation demo not yet signed off
Files outside my paths: PRIORITIES.md and docs/VOICE_SETUP.md (human acceptance evidence)
Proposed decision changes (not implemented): none
Next: P0-2 microphone round trip and latency check
Open question for the team: none

## P0-2 native conversational test mode · 2026-10-24 00:25 EDT · B
Built: voice-check defaults to live native Higgs speech-to-speech; manual commit correlates the created user item before requesting a generated response, carries conversational context, streams captions/audio, waits for playback, and tracks audio connection usage. Fixed reply remains a separately labelled diagnostic; production room split architecture unchanged.
Tests: 94 backend tests + 23 deterministic audio/conversation tests green; synthetic native two-turn check answered seven+five=12 then +three=15, first received audio after paced input end 468/655 ms. User confirmed earlier microphone transcript good and fixed diagnostic 1691 ms; that figure is not native-response or acoustic latency.
Gate: green locally; all changes uncommitted and unpushed
Demo path: native browser conversation awaiting user hardware retest; P0-11 human listening already passed
Files outside my paths: frontend/voice-check.html and frontend/js/voice_check.js (explicit live vs diagnostic modes), docs/status (evidence and limits)
Proposed decision changes (not implemented): none
Next: user speaks two context-dependent turns in Live AI conversation mode and reports audible delay
Open question for the team: P0-2 live audible round-trip timing

## P0-2 premature-turn fix · 2026-10-24 00:38 EDT · B
Built: hold-to-talk is the voice-check default with visible hold/release control and Stop reply; mic/worklet epoch markers prevent stale cancelled audio; blur/pointer cancellation discards rather than submits; hands-free endpoint 1100 ms with quiet-tail tolerance; 60 s input cap discards and latches instead of force-submitting. Room speech activity respects the presenter's held PTT floor.
Tests: user reported five or six turns mostly timely/right but one premature/unrelated reply; added pause, long-hold, overlength, flush, cancellation, stale-event and wrapper tests — 40 audio tests and 94 backend tests green
Gate: P0-11 remains accepted; P0-2 requires hold-to-talk human retest before completion
Demo path: preserve push-to-talk fallback; full room/demo integration remains separate
Files outside my paths: frontend/voice-check.html + frontend/js/voice_check.js (turn control), docs/status (regression evidence)
Proposed decision changes (not implemented): none
Next: user retests deliberate mid-question pauses while holding, then relevant replies and audible latency after release
Open question for the team: none

## P0-2 + P0-11 local human acceptance · 2026-10-24 00:44 EDT · B
Built: no new code; recorded the focused hold-to-talk regression retest and local sign-off
Tests: user confirmed waiting until release through a deliberate mid-question pause and a longer natural question, one correct reply, and audible onset within roughly two seconds; displayed first received audio 1663 ms. Prior moderator/VC/student listening passed; gate remains 94 backend + 40 audio/control tests green.
Gate: P0-2 complete locally via explicit push-to-talk fallback; P0-11 complete locally
Demo path: native voice lab accepted; full presentation room, two clean demos and backup recording remain P0-13/P0-14
Files outside my paths: PRIORITIES.md, DECISIONS.md, demo/DEMO_STATUS.md, docs/VOICE_SETUP.md (human acceptance evidence)
Proposed decision changes (not implemented): none
Next: integration review with A/C for the split presentation-room voice path; no collaborator messaging authorized or performed
Open question for the team: Anthropic key/quota and full room integration; hands-free boundary tuning remains optional

## Presentation-room voice integration · 2026-10-24 01:11 EDT · B (user requested)
Built: actual room uses validated hold button/Space with PTT default in setup+schema; waits for microphone before starting clock, stable turn IDs and capture-floor protection through final STT, responsive reader/ordered model workers, REST Pause/Skip/End, reconnect clock, real deck PNGs, persona/moderator speaking indicators, deduplicated captions, curveball effects, frozen timers, Q&A microphone lifetime and report link. Silent holds discarded; recovery starts at detected speech onset.
Tests: 109 backend + 62 audio/controller tests pass; lint/type/schema/mocks green. Local live-Higgs-TTS check passed in 36.73 s: actual30s gate, held and pending-STT floor, quoted question→answer→follow-up→ack, frozen Pause/Resume, report with real injected quote, zero errors. Synthetic input and playback ACKs; hardware/browser not claimed. Initial smoke harness waited for an answering→answering phase event that is correctly absent; corrected to wait for ai_speech_ended, then the real test passed.
Gate: green locally; changes remain uncommitted/unpushed
Demo path: voice now integrated into room locally; P0-13 two human runs and P0-14 recording remain open; audience reasoning mock on this Mac without Anthropic key
Files outside my paths: spec/contracts.py+generated schema (user-requested default), backend/main.py/engine.py/tests (floor/control/worker lifecycle), frontend room/setup/styles/controller/view (required local room integration), docs/status and setup/start launchers (review and use)
Proposed decision changes (not implemented): none; default change explicitly requested by user and recorded in DECISIONS
Next: manual room walkthrough and real audience reasoning when private Anthropic key is configured
Open question for the team: Anthropic key/quota, full presentation room acceptance and stage recording

## Presentation-room final verification · 2026-10-24 01:15 EDT · B
Built: final input-recovery hardening — button resets on blur, empty STT re-enables hold controls, Space and pointer share room input-admission rules, stale connections close before requesting a microphone. Normal audience speech is preserved by input-only gating rather than pausing audio.
Tests: final gate 109 backend + 77 audio/controller/view tests green; five actual view unit regressions and input/state lifecycle regressions added. Previous real local-server live-TTS integration passed with zero errors. Credential scan clean; syntax and diff whitespace checks pass.
Gate: green locally; no commit, push or merge
Demo path: prepared sample-deck room is unstarted at /room.html?session=638d0236; whole-room human microphone/browser acceptance remains separate
Files outside my paths: same integration scope already recorded
Proposed decision changes (not implemented): none
Next: user opens the prepared room; configure private Anthropic key for live audience reasoning when available
Open question for the team: P0-13/P0-14 human demos and backup recording

## Local voice-room UI integration · 2026-10-24 01:36 EDT · B (user requested)
Built: selectively adapted feat/voice-room commit 4b508eecf37915417cafe504ee95bd2e6335ab67: shared meeting-table layout, 16 unchanged same-room JPEG assets, deterministic portraits preserving accepted voices, separate moderator host, safe active-speaker bubbles/nameplates/fallbacks, full audience builder and report page. Custom third seats never silently drop a roster person; stale/failed uploads cannot restore an old deck. Reports render every schema section, literal evidence, null/zero distinction, skipped no-penalty state, named audience feedback and illustrative mock labels. Historical captions cannot look like current speech.
Tests: 109 backend + 104 frontend/audio tests pass; lint/type/schema/mocks, JavaScript syntax and whitespace checks pass. Actual localhost API checks created preset/custom rooms with faithful PTT/skepticism/curveball settings and uploaded a six-page PDF with valid PNG. All 22 HTML/CSS/module URLs and 16 portraits served; finished probe report validated. Fourteen protected backend/voice/controller files match pre-UI source hashes. Credential scan clean; .env remains mode600; health confirms avatars off. Browser/microphone walkthrough not performed because saved browser access is denied; no workaround used.
Gate: green locally; no commit, merge, push, PR or collaborator message
Demo path: prepared sample room /room.html?session=82b73366 is unstarted; setup and report preview now complete. Live Higgs voices remain; audience reasoning remains mock without a local Anthropic key. P0-13/P0-14 human demonstrations and recording remain open.
Files outside my paths: frontend room/setup/report/styles/modules/tests, demo/faces, documentation/status (explicitly authorized local integration). Pre-integration source+patch backup in sibling backups/before_voice_room_ui_20261024_012216; credentials excluded.
Proposed decision changes (not implemented): none; requested local selection and videos-off scope recorded in DECISIONS
Next: human room walkthrough using Hold to talk, then live audience reasoning when its private key is configured
Open question for the team: human demo acceptance and backup recording

## Guided whole-room test started · 2026-10-24 · B (user requested)
Built: fresh sample-deck human room 1e7452ac, PTT/Normal/rare/one closing Q&A, automatic curveballs Off so debug injections can test each kind predictably. Reproduced and fixed nine keyboard ownership regressions in mic.js: denied repeats cannot late-start, noneditable Space cannot activate another control, blur/stop clean up ownership, and old keyup cannot end a newer pointer turn after disable/cancel/release. Enter/click retain control activation.
Tests: 113 frontend/audio tests pass. Separate isolated actual-server test 8ad4ed98 passed six Higgs audio turns, slides blackout/restore with synthetic measured recovery, heckler Skip/null recovery, time-crunch Pause with frozen countdown, End→Q&A→one follow-up→answer→report; zero room errors. All API-test presenter input/playback ACKs were synthetic; its WPM is not a human measurement. User accepted hold-button sentence once through two-second pause with no early reply, room visuals/meter and paused timer. Remaining human checks are still pending; one later input reached server only as the first half of the requested claim, so guided retry is underway.
Gate: local source remains uncommitted/unpushed; previous 109 backend checks remain green; no backend implementation changed in this test
Demo path: first whole-room human input/visual/Pause checks passed; Space, audience/follow-up, curveballs and human final report still in progress. P0-13/P0-14 remain open.
Files outside my paths: frontend/room.html (clear Space/Enter guidance), documentation/status (test evidence); no collaborator message, merge or push
Proposed decision changes (not implemented): none
Next: continue guided human test and record each observed result in ignored data/voice_checks/full_room_acceptance.json
Open question for the team: whole-room human acceptance remains in progress

## Guided whole-room acceptance completed after fixes · 2026-10-24 02:43 EDT · B
Built: explicit Skip/no-penalty notice and prominent room state; reconnect-before-Resume with coalescing/frozen clock/retry; paused-Q&A context restore; usable End during reconnect and stale-response/report/stop fences. Keyboard ownership safeguards retain prior hardening. No backend restart; human session was preserved.
Tests: user passed button/Space holds through two-second pauses, one complete transcript, quoted audience question→one follow-up→ack, slides/portraits/meter, blackout/recovery/Restore, audible warning replay, heckler/visible Skip, frozen countdown, automatic Q&A and matching speaker, one-click Resume reconnect, and the real report's quotes/5.3 s recovery/skips/timeline. 109 backend + 131 frontend/audio tests pass; independent controller/view review45 pass. Fresh short session de47e83d passed closing question→complete answer→spoken acknowledgement→automatic report/audio stop with zero errors, zero skips and zero unanswered questions.
Gate: green locally; no commit, push, merge, PR or collaborator message
Demo path: guided hardware acceptance after fixes, with live Higgs speech and mock audience reasoning. Main session1e7452ac retains one historical audio-disconnected error, an initially partial Space attempt, initially unheard blackout warning/replay, and manually ended final follow-up. Do not call it a clean unattended demo. Curveballs were debug-forced; initial full report has five curveballs including replays and three skipped questions without penalty. Two unaided real-reasoning demos and backup recording remain P0-13/P0-14.
Files outside my paths: room controller/view/HTML and frontend regression tests (necessary behavior and feedback fixes found in requested test), documentation/status (acceptance record)
Proposed decision changes (not implemented): none
Next: configure real audience reasoning privately when ready, then two clean unaided demo runs and backup recording; everything stays local until explicitly authorized otherwise
Open question for the team: real Claude key/quota and stage demonstration/recording

## Real Boson audience setup and safer Q&A controls · 2026-10-24 · B (user requested)
Built: existing Boson key now powers text-only real audience decisions/follow-ups/recovery/persona expansion, through shared grounding/validation and bounded requests/spend. Added safe per-session provenance/counters, decision backoff and privately persisted finished reports. No Anthropic account/key/calls or new billing account. Main End→Q&A now disables during Q&A; separate Finish session early prevents the repeated accidental cutoff.
Tests: final live four-operation preflight passed with no failures/fallbacks/rejections; isolated synthetic room passed real Boson reasoning and Higgs audio, not a human clean run. 199 backend + 133 frontend/audio tests, lint/type/schema/mocks pass. Warmup32d5c923 had four real model successes and zero reasoning errors/fallbacks/rejections but ended before blackout and manually cut off a closing follow-up; not counted clean.
Gate: local only; no commit, push, merge, PR or collaborator message
Demo path: two fresh clean human runs with naturally scheduled blackout and time crunch still pending; P0-13/P0-14 remain open. Hold-to-talk and static portraits/videos off retained.
Files outside my paths: shared audience/main/engine/persistence/budget and tests, frontend room controls/provider label and tests, documentation (necessary real-reasoning setup and test safeguards authorized by user)
Proposed decision changes (not implemented): none; user explicitly selected existing Boson credentials after declining Claude API charges
Next: run full presentations with human input/audio attestation and passive read-only observation, no developer forcing during runs
Open question for the team: stage recording and two clean full human presentations

## Clean-run evidence and offline gate isolation · 2026-10-24 · B
Built: offline acceptance now requires the complete closing exchange, final spoken acknowledgement, and human confirmation of automatic finish. Missing/skipped coverage remains incomplete, never a presenter penalty. Fixed a test fixture that inherited the deliberately disabled live debug endpoint; bounded failure detection now reports HTTP errors before waiting for audio. No serving code or live configuration changed during the human retry.
Tests: 207 backend + 133 frontend/audio tests pass; lint/type/schema/mocks green. An earlier gate rerun was interrupted after151 passing tests because the test-only debug request returned403 and the test waited for impossible audio; fixture isolation fixes the cause. Serving build remained unchanged throughout.
Gate: local only, no commit/push; two human clean runs still in progress
Next: complete naturally scheduled blackout and time-crunch presentations and record actual audio/automatic-finish confirmation

## Two live Boson presentation flows and timing fixes · 2026-10-24 · B
Built: existing Boson credentials power real audience reasoning locally. Safer Q&A controls prevent repeat main-button Finish. Natural blackout and natural sixty-second countdown presentations both completed with human-confirmed clear audio and automatic Q&A/report. Fixed two findings afterward: generated warning now matches the60s timer; a held closing turn submitted after expiry is assessed once with its actual overrun caveat, preserving deadline/phase and control safeguards.
Tests:240 backend +133 frontend/audio tests, lint/type/schema/mocks pass. Separate exact-timing real Boson grader replay passed; one response, no failure/fallback/rejection, original resolution unchanged. Both original human runs together had12 real reasoning successes, zero failures/fallbacks/rejections/errors/skips/unanswered; original reports preserved. Local server restarted successfully; new and previous saved reports all return200. Credentials scan clean; env ignored/mode600; carryover estimate preserved.
Gate: local only; HEAD302c44b unchanged; no commit, push, merge, PR or collaborator message
Demo path: two human flows completed, not two fully clean final-build certifications. Run1 blackout recovery speech not observed; Run2 original report missed delayed closing grade and warning said five minutes. Fixes have offline/live-model supplemental proof; formal measured-recovery/two-clean-demo/recording sign-off remains open.
Files outside my paths: backend engine/tests (bugs exposed by requested human test), offline acceptance tooling and documentation/status; all within authorized local integration/testing scope
Proposed decision changes (not implemented): none
Next: focused human validation of final timing behavior and speaking-during-blackout practice before formal demo/recording sign-off; preserve hold-to-talk and videos off

## Verified voice integration prepared for yang · 2026-10-24 · B (user requested publication)
Built: prepared the tested room/voice/Boson source, static portraits and regression suite for the user-requested yang update. COLLABORATOR_HANDOFF.md explains implementation, aggregate verification, current provider/configuration, ownership boundaries and ordered next steps. README and current setup/demo guidance point to it. Fixed fresh uv-venv setup to use uv pip, checked Node prerequisites, and isolated socket-test report persistence from private runtime data. Private environment variants are ignored; example defaults keep debug forcing off.
Tests: final publication candidate passes246 backend and133 frontend/audio tests; Ruff, Pyright, schema, mock fixtures, shell syntax and whitespace checks pass. Six setup regressions use offline fake tools; no new vendor calls or server changes during publication preparation.
Gate: user now explicitly authorizes committing and pushing to origin/yang, superseding prior local-only constraint. Fetched yang is an ancestor of the tested302c44b base, so publication preserves its history without force. CLAUDE.md house rules remain unchanged.
Demo path: two human flows completed,12 reasoning successes and zero recorded errors/fallbacks; formal P0-13/P0-14 remain open for the documented recovery/final-build/recording checks.
Files outside my paths: shared backend/contracts and setup/room/report UI already covered by the authorized integration; README, current setup/status docs and new collaborator handoff added for this publication request
Proposed decision changes (not implemented): none
Next: collaborators start with COLLABORATOR_HANDOFF.md, run offline gates, configure their own private credentials, then complete focused hardware retests and recorded final-build demos
Open question for the team: final human recovery/timing acceptance and backup recording

## Complete remaining P0 report and lifecycle code; human checks deferred · 2026-10-24 · B (user requested continued autonomous work)
Built: content rubric now evaluates clarity/evidence/structure/question handling using bounded exact source IDs and strict ownership checks; model cannot create evidence text or change measured recovery/metrics/skips. Overall averages supported content dimensions with explicit subjective/coverage caveats. Finish stops voice/capture and freezes time before grading, notifies the room immediately, exposes preparing409, then persists only the final report. Bounded timeout/cancellation preserves measured fallback. Report loader polls preparing only, has45s timeout/Retry/pagehide cleanup, and optional metadata never blocks valid content. Terminal/disposed room events and slide controls are fenced; archived reports do not open a live room socket.
Tests:281 backend +151 frontend/audio tests pass; Ruff/Pyright/schema/mocks and whitespace checks pass. One live fictional-text report probe initially failed strict response validation; explicit nested prompt schema/template fixed it and the bounded retry passed with one actual report success and zero failures/fallbacks/rejections. Initial diagnostic preserved privately; synthetic delivery/mock audio is not another human presentation. Existing human reports were not changed.
Gate: implementation is ready for later human testing as requested; hold-to-talk/default voices retained, videos off. GitHub push remains externally blocked by absent local GitHub credentials and the connected app HTTP403. No account permissions changed, no credentials disclosed, no unverified remote update claimed.
Demo path: reports now include real source-grounded content coaching; formal P0-13/P0-14 still require final-build microphone/recovery acceptance and two recorded unaided runs. Tests and preflights do not substitute for those human checks.
Files outside my paths: spec internal rubric models/schema, backend report/audience/engine/main and regressions, frontend API/room/report lifecycle and tests; necessary completion of the user-authorized integrated presentation room
Proposed decision changes (not implemented): none; evidence/coaching formulas and provider choices documented in DECISIONS.md
Next: refresh local server and source checkpoint; when user returns, test the complete final build and restore GitHub write authentication for publishing yang

## Authenticated yang publication checkpoint · 2026-10-24 · B (user requested)
Built: latest verified implementation is committed in1cde6c7 and8e03068. Updated COLLABORATOR_HANDOFF.md to direct collaborators to the current code, reproducible checks, private credential setup and remaining acceptance work.
Tests: the implementation retains281 passing backend tests and151 passing frontend/audio tests, with Ruff/Pyright/schema/mocks passing. This final update changes documentation only; whitespace checks pass. Independent source/docs/privacy audit found no publication blocker and no private runtime files included.
Gate: user explicitly requested publication to yang and completed GitHub CLI sign-in after the connected app still refused writes. Refetched origin/yang and confirmed it is an ancestor of the verified checkpoint; publication uses a normal fast-forward push without force.
Demo path: hold-to-talk, accepted voices and videos-off remain. Final-build human microphone/recovery validation, two recorded unaided demonstrations and backup recording remain P0-13/P0-14; prior guided runs and automated/model checks do not replace them.
Files outside my paths: collaborator handoff and this append-only progress record, both requested for collaborator continuity
Proposed decision changes (not implemented): none
Next: collaborators pull yang and start with COLLABORATOR_HANDOFF.md; continue the documented final-build acceptance and recording work when the user returns.

## Recorded final-build attempt and acceptance fixes · 2026-10-24 · B
Built: user completed recorded session60d6e482 with clear hold-to-talk/audio, natural blackout recovery, two grounded answered questions and two follow-ups, automatic Q&A/report and stopped microphone. Recovery measured7.140s. The full6:16 recording was saved, reviewed by the user in Chrome, copied into demo/ as an ignored candidate and hash-verified; original preserved. Its final coaching response failed strict citation-count validation, so the run is not clean. Corrected report-only generation to request one representative citation/finding, with strict admission, ownership and visible fallback unchanged. Added safe bounded validation diagnostics. Fixed queued ticks sampling time before the room lock, which had backdated completion by1.988s.
Tests:285 backend +151 frontend/audio tests pass, plus Ruff/Pyright/schema/mocks and whitespace checks. Exact queued-clock regression failed before the fix and passes afterward; cancellation stays safe. One bounded live saved-context call reproduced the citation overflow; two independent fixed text-only checks passed structure/grounding, including the full report service with metrics/recovery unchanged. Historical artifacts were not regenerated. These are supplemental checks, not replacement human demos.
Gate: corrected build ready to freeze for fresh human acceptance; P0-13/P0-14 stay open. No clean-run attestation was invented and no failed counter was hidden. App/recorder run in a visible Terminal window for stable local testing; Chrome tab sharing/microphone permission and a running recorder are confirmed before starting a take. Source remains hold-to-talk with static portraits/videos off.
Files outside my paths: backend/main.py ticker lifecycle and focused clock tests; backend Boson report prompt/diagnostics and report regression tests; aggregate handoff/status/decisions. Necessary fixes found by the user-requested final acceptance.
Proposed decision changes (not implemented): none
Next: restart the local app with the frozen fixes, prepare two fresh sessions, record natural blackout and countdown presentations without developer controls, validate reports/counters and save a clean backup. Recordings and raw evidence stay private.

## Deadline handoff and immediate yang publication · 2026-10-24 · B (user requested)
Built: corrected code is committed in2a9b85e. User now explicitly prioritizes immediate GitHub publication and a handoff with final tests left open. No further presentation requirements are imposed for publication. Preserved the earlier complete recording candidate and original reports; keys, raw evidence and media remain excluded from Git.
Tests:285 backend +151 frontend/audio tests, Ruff/Pyright/schema/mocks pass at the code checkpoint. Two independent live saved-context report checks passed strict structure/grounding with metrics/recovery unchanged. Final diff/privacy/history checks and authenticated fast-forward push are the release gates; automated proof does not certify human microphone/playback.
Gate: P0-13/P0-14 remain open. Corrected-build attempt e0f2de65 had two audio disconnection errors, only two captured presenter segments, no measured recovery and correctly skipped coaching. Run2 remained unstarted. The behavior is consistent with existing60s idle closure, but the exact client-local reason was not saved; the handoff documents manual reconnect/paused Resume before continuing after idle. No speculative transport change was made under the deadline.
Files outside my paths: aggregate collaborator handoff, demo status and priority completion fields, requested for accurate collaborator continuity
Proposed decision changes (not implemented): none
Next: collaborators start with COLLABORATOR_HANDOFF.md; complete idle/reconnect acceptance and two recorded clean presentations of the corrected build, then choose the final backup. Earlier failed/partial evidence is retained, never relabelled clean.
