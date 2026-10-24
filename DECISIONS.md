# DECISIONS.md

Settled. Dated entries, newest first. Do not re-decide; a decision that looks wrong goes on your checkpoint report's `Proposed decision changes` line.

## 23 October 2026 — kickoff

- **Name:** PresAI (repo `kenneth13he/Pres-AI`). "PitchPanel" in the archived plan is history.
- **Vendor:** Higgs API (Boson AI), one key, **$100 of credit**. Realtime (`higgs-realtime`), TTS 3 (`higgs-tts-3`), STT (`higgs-stt-3.1`), Avatar. No LLM endpoint. Facts and the five hour-1 tests: CLAUDE.md §13.
- **Brain:** Claude `claude-opus-5-5` on an Anthropic key, official `anthropic` SDK, structured outputs, adaptive thinking, effort low (live) / high (report). **Live-checked 23 Oct 22:50** (`scripts/try_orchestrator.py`): all four prompts return valid structured output; latency decide 2.2–2.6 s, follow_up 2.1 s, assess_recovery 6.4 s; the VC question quoted the transcript verbatim and contrasted it with the slide. Key is in `.env` on the C laptop; `ORCHESTRATOR=claude` there. Monthly cap: still to confirm (§15 Q6).
- **Stack:** all Python. FastAPI serves the API and a framework-free static frontend (HTML/CSS/ES modules, Tailwind CDN, no bundler). Browser mic/audio code is JS by necessity, kept small. Pinned versions in `requirements.txt` (resolved today); Python 3.12.
- **Audience builder is P0** (P0-3b). It is the headline: "choose who is in the room".
- **Judging weights product, UX and demo quality.** Avatar stays P2 (needs every P1 done and >$40 credit left). Demo-path polish is the first P1.
- **Money rules:** $30 reserved from hour 18; soft cap $60 before hour 15; every vendor session has a hard timeout and closes in a `finally`; own spend counter on `/health`.
- **Gate:** `make check` must be green to merge to `main`, with one scaffold-time exception recorded in `PROGRESS.md` SESSION-0: tests are the spec and are red until their priority lands.
- **Scaffold scope:** skeletons only — contracts, wiring, interfaces, tests, docs. Bodies marked `TODO(A|B|C)` are the team's work (the first draft had full implementations; they were removed on purpose so the split in CLAUDE.md §11 holds).

## Vendor (Person B fills in from the hour-1 tests)

- Test 1 — round-trip latency: accepted locally on 24 Oct using the plan’s push-to-talk fallback. User confirmed the native mic → generated speech path waits through pauses until release, answers correctly once, and begins audibly within roughly two seconds. Displayed speech-end → first received audio: 1663 ms (not instrumented acoustic latency). Earlier hands-free run had one premature reply; automatic end-of-turn detection is not signed off as equally reliable.
- Test 2 — scripted line on demand / per-turn voice: live Realtime checks passed caption word matching for two turns and accepted session voice update default → eleanor. Audible voice difference unverified.
- Test 3 — STT timestamps: final-only transcripts have no speech timestamps. Use browser PCM capture boundaries on the session clock; never transcript-arrival time. Synthetic manual commit transcribed without an autonomous reply (1.5 s observation).
- Test 4 — TTS tags + two distinct preset voices: local binary transport live-checked with eleanor (moderator), marcus (VC, impatient tags), chloe (student, confused tags). On 24 Oct the user confirmed moderator, Dana and Sam are all clear and distinct; P0-11 accepted.
- Test 5 — ephemeral client secret in the browser: mint endpoint and browser-style WebSocket subprotocol passed through Python; on 24 Oct the user successfully used the actual browser microphone and confirmed a good transcript. Agent browser control remains denied; hardware evidence comes from user feedback.
- **Voice architecture (B, 23 Oct local): Shape 2.** Direct browser Realtime manual-commit STT with temporary credentials, backend TTS on a separate binary socket, and browser playback acknowledgement. Boson ignores `create_response:false` under vendor VAD, so browser utterance detection or PTT is required to preserve the single-orchestrator rule. Shape 1 scripted speech also passed the limited live test, but the split path keeps deterministic text/voice/style rendering separate from listening. Sources and local validation limits: `docs/VOICE_PROTOCOL.md`, `docs/VOICE_SETUP.md`.

## 24 October 2026 — local voice acceptance (B)

- **P0-2 complete locally with push-to-talk fallback.** Human retest held through a two-second mid-question pause and a longer natural question: no reply before release, one relevant answer, and audible onset within roughly two seconds. User reported 1663 ms to first received audio; device output delay is not measured by that display.
- **P0-11 complete locally.** User confirmed moderator, VC and student clear and distinguishable.
- **Turn control:** the voice-check defaults to explicit hold/release. Hands-free remains optional with a 1.1 s endpoint and quiet-tail tolerance; recording limits discard instead of auto-submitting. The earlier hands-free premature-turn failure remains documented.
- **Scope:** native speech-to-speech is the P0-2 validation path. The presentation room retains the split transcription/orchestrator/TTS design; full room integration, two clean live demos and backup recording are still P0-13/P0-14 work. No local Anthropic key is configured.
- Changes remain local, uncommitted and unpushed; no merge or collaborator message was performed.

## 24 October 2026 — presentation-room voice integration (local, user requested)

- **Hold-to-talk is the default for new sessions.** The user explicitly requested it for
  the actual room. SessionConfig, generated schema and setup selection now agree; an
  explicit hands-free choice is preserved. This supersedes the original default-live rule.
- **One audience brain remains in control.** The room uses split Higgs transcription +
  backend orchestrator + streamed Higgs TTS; native voice-check conversation remains separate.
- **Presenter floor:** capture/release/discard/final carry one turn_id. Held speech and
  pending STT suppress audience decisions; slow model calls recheck before speaking. The
  event reader processes floor updates while ordered workers handle slow session actions.
- **Controls:** Pause/Skip/End cancel capture/playback locally, then use REST so controls
  can invalidate slow calls without waiting behind a transcript on the event connection.
- **Verification:** 109 backend tests + 77 audio/controller tests, lint/type/schema/mocks pass.
  Actual local-server test with live Higgs TTS passed the 30 s scheduler boundary, held and
  pending-final floor, quoted question→answer→follow-up→ack, frozen pause and evidence report;
  zero room error events. Transcripts and playback ACKs were simulated, not hardware/browser.
- **Remaining:** this Mac has no Anthropic key, so the room visibly uses audience test mode.
  Full human room acceptance, two stage-style live runs and backup recording remain pending.
  No push, merge, PR or collaborator message was performed.

## 24 October 2026 — requested local UI integration

- Adapt the `feat/voice-room` UI, same-room JPEG portraits, audience builder and report
  from commit `4b508eecf37915417cafe504ee95bd2e6335ab67`; keep the existing local voice
  implementation and its hold-to-talk default. This is a selective integration, not a merge.
- Keep the voices already accepted by the user. Static portrait selection uses the new
  cast while preserving the local voice mapping, rather than reassigning voices by the
  upstream portrait filename's role prefix.
- Talking-head videos stay off as explicitly requested. No upstream avatar pipeline,
  asynchronous clip queue or video dependencies are imported.
- The user authorized the frontend work across owner boundaries for this local task.
  No collaborator messaging, push or merge is authorized or performed.

## 24 October 2026 — whole-room keyboard test safeguards

- Space belongs to hold-to-talk while its microphone session exists, including temporary
  playback/Pause blocks. Enter or clicking activates other buttons; editable fields keep
  normal Space input. A denied hold requires a fresh release/press before it can capture.
- Keyboard ownership ends when its turn is cancelled, disabled or directly released.
  A later keyup cannot submit a new pointer hold. Nine deterministic regressions cover
  delayed repeat, focused controls, blur and mixed-input ownership; frontend/audio suite
  is 113 passing. Backend transport, voices and turn-floor protocol are unchanged.

## 24 October 2026 — guided room acceptance fixes

- Skip keeps transcript history and now visibly confirms dismissal/no penalty. A prominent
  room-state message explains whose turn it is and whether the timer is paused.
- Resume after an idle audio closure must reconnect speech/microphone before unpausing.
  Failure leaves it paused. Repeated requests coalesce; End remains usable during connection;
  terminal report/stop events prevent delayed responses reopening the room. Paused Q&A
  reloads retain their closing-round context. Idle/hard limits are preserved.
- Guided human checks and a separate automatic closing run passed. Keep initial failed
  attempts in the acceptance record; do not call the main guided run error-free or an unaided
  demo. Voices remain live, audience reasoning remains mock, and videos remain off.
- Final local checks: 109 backend + 131 frontend/audio tests pass. Nothing committed/pushed.

## 24 October 2026 — existing Boson key for the local audience

- The user declined separate Claude API charges and requested reuse of their existing Boson key. Local `ORCHESTRATOR=boson` uses bounded text-only Higgs requests and shared structured audience validation; it is explicitly labelled live Boson audience. Claude remains selectable but is neither configured nor called. Existing Boson credit usage continues.
- Track real per-operation success, failure, fallback, rejection and token usage. A provider label alone is not clean-run evidence. Missing real-mode credentials fail visibly rather than silently selecting mock. Respect shared spending/request limits and retain conservative spend carryover across this restart.
- Persist finished local reports privately so a server restart does not lose acceptance evidence. No raw microphone audio is recorded.
- Repeated accidental Finish Q&A clicks led to separate controls: the main End button starts Q&A once, then disables; deliberate early finish sits in the side panel. Automatic completion exposes the report link. Hold-to-talk, accepted voices, playback acknowledgements, videos off and local-only work remain.
- Preflight and synthetic room checks passed; warmup 32d5c923 ended before the automatic blackout and cut off a closing follow-up. It does not count toward the two clean human presentations.

## 24 October 2026 — findings from two real Boson presentations

- Human sessions bb1e3b93 (natural blackout) and ff575163 (natural time crunch) both reached reports automatically with confirmed clear audio, no skips/unanswered questions and12 successful real Boson calls; zero reasoning failure/fallback/rejection or room-error events. Original evidence remains private under data/voice_checks/clean_presentations and saved reports survive restart.
- Do not certify both original runs as fully clean: blackout speech was not observed before restoration; the crunch closing turn was captured215438–266194ms but arrived269397ms, after the265358ms expiry, so its original report missed assessment. Its generated warning also incorrectly said five minutes against the fixed60s timer.
- Time-crunch speech now always uses the canonical sixty-second warning. A turn already held/pending at resolution can contribute its matching late final once, within existing hold/transcription limits. Resolution/deadline/Q&A timing remains unchanged; pause/cancel/skip/end/new-turn/terminal guards invalidate it. The report records a1.3s overrun and unavailable individual-word timing rather than assuming all words were before zero.
- Separate exact-timing replay with the saved closing text, synthetic input delivery/clock, MockVoice and a real Boson grader passed. This is supplemental verification, not another human presentation or retrospective repair of the original report. Formal P0-13/P0-14 sign-off remains open.

## 24 October 2026 — publish the verified checkpoint to yang

The user explicitly requested updating their GitHub yang branch with verified work and a collaborator progress/next-steps file. This supersedes the earlier no-push instruction for this checkpoint. Publish source, tests, static fictional portraits and aggregate handoff evidence; keep keys, private runtime reports/transcripts/decks, diagnostic artifacts and recordings out. Preserve yang history and do not merge main or the later unverified voice-room/avatar experiments. Final publication checks are246 backend +133 frontend/audio tests plus lint/type/schema/mocks. Formal two-clean-demo/recording status remains open; publishing the code does not close those acceptance items.

## 24 October 2026 — finish report code before further human tests

The user requested continuous implementation work and deferred testing until later. Complete the remaining P0 report pass locally without claiming new human acceptance. One bounded provider-neutral rubric references exact captured source IDs; server-side ownership/eligibility validation resolves quotes. Unknown/unsupported references reject the assessment rather than substituting evidence. Skip/cut-off questions are excluded. Content scores are subjective text coaching, not external fact verification or acoustic/psychological measurements. Overall is the equal-weight mean of supported content dimensions, with coverage stated; recovery and metrics remain deterministic and separate.

Finish stops microphone/audio and freezes session duration before optional grading. The room sees terminal events immediately; report GET distinguishes preparing409 from unfinished409. A bounded25s final-preparation budget and safe fallback retain usable measured reports; frontend preparing polling is bounded45s and cancels on retry/page exit. Only final reports persist, and historical reports remain unchanged. The explicit JSON prompt shape fixed an initial live report-format rejection; a separate one-call fictional-text preflight passed afterward. These changes are code/model verification, not two clean human demos. GitHub yang publication still requires valid write authentication.

## 24 October 2026 — final acceptance findings: report citations and queued clock

Recorded human attempt60d6e482 completed natural blackout recovery, two grounded question exchanges and automatic report handoff. Its coaching response exceeded the internal two-reference limit, so it correctly retained a measured fallback and is not a clean demo. One bounded saved-context call reproduced the malformed arrays. Report-only Boson generation now requests one representative source per item and at most one strength/improvement; the admission model still permits two references and validates exact source IDs and answer/persona ownership. Invalid responses are neither trimmed nor silently retried. Diagnostics expose only bounded schema-known field paths and fixed error types, never generated content. Two independent fixed text calls passed, one through the report service with deterministic metrics/recovery unchanged; they are not new human presentations.

A ticker queued behind the closing acknowledgment evaluated time before acquiring the room lock, backdating the terminal event and frozen duration by1.988s. Its clock is now sampled in the coroutine body after lock acquisition. The exact regression and blocked-tick cancellation test pass. Original snapshots, reports and the six-minute recording candidate stay unchanged.285 backend and151 frontend/audio tests plus lint/type/schema/mocks pass. Freeze this corrected build before two fresh recorded human runs; P0-13/P0-14 remain open. Hold-to-talk, one-speaker guards, videos-off and private credentials/recordings are retained.

## 24 October 2026 — finish audio safety automatically; retain the reviewed backup

The user deferred optional custom voices/avatars and requested the remaining important work. Unexpected audio or room connection loss now freezes local clocks, discards held/pending input, closes the old bridge and coalesces a backend Pause. Backend loss receipt invalidates delayed audience actions immediately, holds authoritative timer values while bounded work unwinds, and applies Pause at the receipt time. Attachment/control ownership prevents old cleanup from pausing a replacement or clearing a newer intent. Explicit Resume reconnects before timers run; failed Pause confirmation stays visibly local-only until repaired. Intentional End/report/dispose stay fenced; early Finish remains available. Idle60s/hard600s guards are retained, with no automatic paid reconnect loop.

The local-file criterion for P0-14 is fulfilled by preserving the user-reviewed real-run recording as demo/backup-presentation-60d6e482.webm, verifying its hash and documenting its older-build/report-fallback limitations in demo/RECORDING_BACKUP.md. This is artifact completion, not retrospective clean-demo certification. P0-13's two human final-build runs remain open; automatic simulations do not certify microphones or audible playback. WebM recordings join existing MP4/MOV ignores so private media is not pushed.296 backend and166 frontend/audio tests pass, including the actual transcription idle callback and real ASGI socket handling with simulated vendor responses.

## 24 October 2026 — final deadline release verification

The user requested a complete push/readiness check within20 minutes. The release is based on main302c44b. Reviewed latest alternative voice-room f958d7c: shared public contracts match and its report features are already covered here, while its panel/free-chat protocol differs. A merge dry-run confirms conflicts, so no wholesale late merge is made over tested PTT/audio lifecycle protections.

A fresh GitHub yang clone installed pinned dependencies in a new Python3.12 environment and passed its full gate. Tightened Make setup to validate Python>=3.12 before fallback creation and chmod600 new/existing .env without replacing content. Three separate Make regressions retain all six launcher regressions. Actual make setup,299 backend tests,166 frontend/audio tests, lint/type/schema/mocks and credential/asset checks pass. A separate mock server passed PDF upload/PNG/session/held input/Pause/Resume/report with no provider key or calls. CDN styling still requires internet or cache, explicitly documented. P0-13 human evidence remains deferred; automatic proof is not two human presentations.


## 24 October 2026 — optimized release branch requested by user

Create `feat/optimized-presentation-room` from verified `yang` checkpoint1392f74 and publish the optimized work there, preserving existing branches. Adopt main9df73d3 design and the static whole-face framing from most-recent-update5274a12 while retaining the tested modular backend/audio lifecycle, Boson voice/reasoning, default hold-to-talk and videos-off. Keep the prominent Continue bar, safe profiles, PDF upload/Start guards, authoritative report loading, audio-loss Pause and report persistence. Do not merge the alternative native-panel backend, webcam or live-avatar pool. A bounded fictional-input live provider check complements offline gates; it does not certify two human presentations or a new recording.


## 24 October 2026 — use collaborator adaptive layout with guarded voice lifecycle

The user requested the collaborator's latest design. Adapt b783dce's adaptive guest-region geometry, full gallery without a deck, bounded labels and viewport stage to the existing optimized branch. Allow1–3 roster guests consistently in contract/schema/API/setup; exclude crosstalk for solo audiences. Generated free-text guests retain server expansion and require1–2 roster guests. Preserve selected people when totals need correction. Keep static portraits/moderator, prominent Continue actions, Boson reasoning/voice, hold-to-talk default/floor and videos-off. No native-panel backend, webcam or LiveKit pool is imported. A backend restart is required for the new one-guest contract; preserve the prior paused test snapshot privately and create fresh manual rooms.
