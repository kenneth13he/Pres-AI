# Voice-room handoff — 24 October 2026

This is the verified voice-room integration for **`yang`**. Start here before
continuing A/B/C work. Read `CLAUDE.md` for the team rules and the latest
`DECISIONS.md` entries for the user-approved local choices.

## Deadline handoff

The user requested publication with final human tests left open, then asked to finish the
remaining important work automatically. The current gate is 299 backend and 166 frontend/audio
tests plus lint/type/schema/mocks. Report/clock fixes and two bounded live report replays
were already verified. Hold-to-talk stays default; talking-head videos stay off.
P0-13 remains unsigned. P0-14's local backup-file requirement is met: see
[`demo/RECORDING_BACKUP.md`](demo/RECORDING_BACKUP.md) for the reviewed six-minute real-run
backup, hash and older-build limitations. The private video itself is excluded from Git.

The subsequent corrected-build attempt recorded two voice disconnections and insufficient
presentation text; report coaching correctly skipped. The countdown room was not started.
Disconnections were consistent with the existing 60-second idle shutdown; the exact
browser-local cause was not retained. The resulting continuation-without-audio gap is now
fixed: unexpected loss pauses the room, freezes elapsed/countdown, discards pending input
and cancels playback. Resume reconnects before continuing. Network failure shows an explicit
local-only freeze until backend Pause is confirmed. No automatic paid reconnect loop was added;
idle/hard limits remain. Actual idle-callback and real ASGI socket simulations pass, but a
fresh human pair of this final build is still unverified.

## Final release and compatibility check

- A fresh clone of the published `yang` checkpoint was installed into a new Python 3.12
  environment from the pinned requirements. Its full backend/frontend gate passed.
- The final setup recipe was then exercised in that clean environment: Python fallback,
  dependency installation, schema generation and private `.env` permissions all passed.
  Three additional Make setup regressions preserve the six existing launcher regressions.
- A separate mock/mock HTTP/WebSocket server served 42 checked pages/modules/portraits,
  ingested the six-slide sample PDF, returned a valid slide PNG, captured one synthetic
  held turn, froze Pause time, resumed and produced a valid report with zero error events.
  This used no provider credentials and is automatic proof, not human microphone acceptance.
- `origin/main` (`302c44b`) is an ancestor of the release. The alternate
  `feat/voice-room` report snapshot (`f958d7c`) has identical shared public
  report/persona/event contracts; its report additions are already covered here.
  Its subsequent update through `3bc3b8c` was also reviewed: shared contracts are
  unchanged; it adds a live-face warm pool and a WAV-upload Higgs STT path for its
  own room. Yang already uses Higgs STT with explicit hold-to-talk and socket ownership.
  The warm pool is outside the requested videos-off release. Its native panel/free-chat
  engine uses a different protocol. A merge dry-run reports conflicts: do not wholesale
  merge it over the tested single-orchestrator, hold-to-talk lifecycle. An intentional
  future migration needs integration work; no unsafe late merge was performed.
- Mock/offline checks require no vendor key, but normal page styling still uses the
  Tailwind CDN and therefore needs internet or a cached copy. Live Boson use needs internet.

## What is ready

- The actual setup → room → Q&A → report flow is integrated. PDF slides, the audience
  builder, static portraits, active-speaker feedback, captions, Pause/Skip and report
  rendering work with session events.
- **Hold-to-talk is the default:** hold the button or Space through thinking pauses;
  release after finishing. Enter/click activates other controls. Hands-free is optional.
- The room uses Higgs transcription, one backend audience orchestrator, and streamed
  Higgs PCM speech with playback acknowledgements. Native voice-lab conversation is
  a separate diagnostic at `/voice-check.html`.
- **Real Boson/Higgs audience reasoning is available on the existing Boson key.**
  The user declined a separate Claude API bill and selected this route. Claude and
  mock adapters remain available; the recorded local validation made no Anthropic calls.
- The accepted voice mapping is retained: moderator Eleanor, Dana/VC Marcus,
  Sam/student Chloe, professor Oliver, mentor Nora. Portraits are fictional and static.
  **Talking-head videos stay off.**
- Presenter holds and pending final transcripts protect the floor. Pause/Skip/End
  cancel capture/playback, old decisions are discarded, and Resume reconnects audio
  before restarting the clock. Idle/hard limits remain.
- `End → Q&A` starts the closing round once, then disables as `Q&A in progress`.
  Answer the audience and wait for the report link. A separate `Finish session early`
  button is an intentional exit; Skip is explicitly no-penalty.
- Finished reports persist locally in private, ignored `data/sessions/`, and survive
  a server restart. No raw microphone audio is recorded by the room.
- Reports include bounded, evidence-grounded content coaching for clarity, evidence,
  structure and question handling. Source IDs resolve to exact stored text on the server.
  Unsupported judgments remain unassessed. Recovery, metrics, event history and skips
  retain their deterministic values.
- Microphone/audio stop immediately when the session ends. Feedback is prepared afterward;
  the report page waits automatically, with bounded retries and a visible Retry option.
  Finished timers stay frozen, and late events or slide clicks cannot reopen the room.

## What was actually verified

| Evidence | Result and limit |
| --- | --- |
| Offline backend gate | 299 tests; Ruff, Pyright, generated schema and mock fixtures passed, including Make/launcher setup, disconnect pause, ownership, teardown, clocks, report preparation and persistence. Re-run commands below on your checkout. |
| Offline frontend/audio gate | 166 tests passed, including actual STT idle → voice close → room pause, frozen timers, pending-input discard, reconnect-before-Resume and control races. No microphone or vendor calls are used by these tests. |
| Voice hardware | User confirmed microphone transcription, distinct clear voices, complete PTT turns through pauses, and automatic closing/report handoff. Earlier voice-lab latency sign-off is not a full-room acoustic latency guarantee. |
| Two real-audience human flows | Natural blackout and natural countdown → Q&A runs both reached reports automatically with clear audio. Together: 12 real Boson reasoning successes; zero recorded model failures/fallbacks/rejections, room errors, skips or unanswered questions. |
| Boson structured-output preflight | Decisions, follow-ups, recovery grading and custom-persona expansion all passed a bounded live check. Responses use grounding/validation and explicit diagnostics. |
| Delayed-closing fix | Exact-timing regression tests and a separate real Boson grading replay passed. The replay used saved text with synthetic delivery/clock and mock audio; it is not a new human presentation. |
| New content-coaching pass | One live Boson report call passed using fictional text, injected Q&A and silent mock audio. An initial formatting failure was fixed and retained in private diagnostic evidence; this is not a new human run. |
| Recorded final-build blackout attempt | Human confirmed complete clear audio, automatic finish and readable recording. Natural blackout recovery measured 7.140 seconds; two grounded questions and two follow-ups completed. Final content coaching failed validation, so the recording is a local candidate and the attempt is not clean. |
| Report-failure fix | One saved-context live call reproduced excess evidence references; two independent fixed calls passed schema and grounding, including the report service. Original report/metrics/recovery were preserved. These text replays do not replace fresh human runs. |

Private keys, transcripts, session reports, uploaded decks, diagnostic audio and raw
acceptance artifacts are **not included** in this branch. The table is an aggregate
record of local evidence; another machine cannot open those local session links.

### Findings fixed after the two human runs

1. A generated time-crunch warning said “five minutes” over a sixty-second timer.
   The room now always speaks the canonical **sixty-second** warning for that effect.
2. A PTT closing turn began during the countdown and was submitted just after zero.
   The original report missed its grading. A held/pending matching turn can now be
   assessed once after resolution, within the existing capture/transcription bounds.
   The original deadline and Q&A transition stay unchanged. Notes retain the measured
   overrun and unknown individual-word timing; no on-time close is invented.
3. Repeat clicks on the old End/Finish control could cut off Q&A accidentally. Starting
   Q&A and deliberately finishing early now have separate controls.
4. A recorded final-build attempt exposed a report response citing more than two sources
   per item. Boson generation now requests one representative reference and one strength
   and improvement. Admission limits, source ownership and quote validation remain strict;
   invalid responses are never trimmed or silently retried. Safe diagnostics expose only
   schema field paths and error types.
5. A timer tick queued behind closing audio sampled its clock too early, backdating the
   finish by about two seconds. Live ticks now sample time after acquiring the room lock;
   the regression verifies event order, frozen duration, persistence and cancellation.
6. Audio idle closure used to leave the presentation running without its speech bridge.
   Both controller and backend now pause safely. Attachment/control ownership protects a
   replacement connection from old cleanup; terminal shutdown stays idempotent. Pause
   intent uses the loss receipt time while bounded in-flight work unwinds. This timestamp
   can precede a later canceled-speech completion in append order; it is not a backdated finish.

Original reports were preserved. Subsequent fixes and replay tests do not retroactively
make the original runs clean final-build demonstrations.

### Still open

- **P0-13 is not signed off:** two consecutive unaided, recorded runs of the corrected
  frozen build still need acceptance. The recorded recovery demonstration had a report
  fallback; the subsequent attempt had voice disconnections. Historical attempts are retained.
- **Backup limitation:** P0-14's real-run file exists and was human-reviewed, but records
  an older build with the documented coaching fallback and clock issue. It does not certify
  P0-13. A same-build clean recording can replace it later; the original remains preserved.
- Content coaching is implemented, but scores can remain `null`/“Not assessed” when
  captured evidence is insufficient. Scores are subjective text estimates, not verified
  factual accuracy, acoustic measurements or psychological judgments. Overall averages
  assessed content dimensions only; the report explains its coverage and scores recovery
  separately. Original historical reports are not regenerated with new scores.
- The warning and delayed-closing fixes have automated/live-model proof, but need the
  focused human checks below on the final build.

## Run it on your machine

Use Python 3.12, the pinned `requirements.txt`, Make, and Node for the browser tests.
From a clean checkout of `yang`:

```sh
make setup
chmod 600 .env
make check
node --test --test-timeout=5000 scripts/test_*.mjs
make dev
```

The macOS `setup_local.command` and `start_local.command` launchers are also available.
Open `http://127.0.0.1:8000/setup.html`. A sample six-page PDF is in
`demo/sample_pitch.pdf`. Offline defaults are mock/mock and need no API key.

For a live room, put your key privately in `.env`; set these values there:

```dotenv
VOICE_ADAPTER=higgs
ORCHESTRATOR=boson
BOSON_REALTIME_MODEL=higgs-realtime
BOSON_REASONING_MODEL=higgs-realtime
BOSON_AVATAR_ENABLED=false
CURVEBALLS_ENABLED=true
DEBUG_CURVEBALL_ENDPOINT=false
```

Set `BOSON_API_KEY` privately as well. Do not put it in source, a handoff or chat.
Live checks consume your Boson credits. Only set `ANTHROPIC_API_KEY` and
`ORCHESTRATOR=claude` if the team explicitly chooses Claude. Restart after changing
provider settings. `/health` reports the actual adapter and safe budget counters;
session snapshots include per-operation successes/failures/fallbacks/rejections.

Optional paid reasoning preflight:

```sh
.venv/bin/python scripts/try_boson_audience.py --live
.venv/bin/python scripts/try_report_assessment.py --live
```

Keep debug curveball forcing disabled for acceptance runs. Separate diagnostic probes
may require it; those are not evidence of a naturally scheduled clean demo.

## Next work, in order

1. **B + presenter:** confirm the warning says sixty seconds. Hold a short closing turn
   through zero, release shortly afterward, then finish Q&A normally. Check the full
   transcript, once-only recovery assessment and overrun caveat, complete speech and
   automatic microphone/audio stop. Do not use Finish session early for this check.
2. **All:** practise a naturally scheduled blackout on Slide 2 or later. Speak and release
   a brief recovery point while the blackout is active, before its thirty-second restore.
   Verify a measured resume gap, exact evidence quote and matching report entry.
3. **All:** do two consecutive complete unaided recorded presentations without debug
   controls, including idle/reconnect behavior. Update P0-13 only when evidence passes.
   P0-14's older-build fallback file already exists; replace it with a clean final-build
   recording when available, preserving its documented limitations in the meantime.
4. **C + A:** verify the new report coaching in a real microphone session, including
   preparing → ready, evidence quotes, unsupported nulls and unchanged recovery/metrics.
   Use real session JSON, not the illustrative `?mock=1` report, for final acceptance.

## Integration map

- **B / voice:** `backend/services/voice_higgs.py`, `backend/voice_routes.py`, browser
  microphone/worklet/realtime/voice modules, voice-check page and voice probes.
- **C / reasoning and state:** `backend/services/audience.py` (shared validation plus
  Claude/mock), `audience_boson.py`, `reasoning_budget.py`, `backend/engine.py`,
  `backend/main.py`, `backend/session_records.py`, and their tests.
  `report_assessment.py` owns the bounded content rubric; finish announces the terminal
  state before grading and exposes `report_preparing` only while the result is pending.
- **A / UI:** setup model/controller/view, room controller/view, portraits and CSS,
  report controller/view and static JPEG assets.
- **Shared contract:** `input_mode` defaults to `push_to_talk` in both
  `spec/contracts.py` and the generated schema; explicit hands-free settings still work.
- **Evidence tools:** `scripts/assess_clean_presentations.py` distinguishes actual clean
  coverage from truthful unassessed recovery. API simulations/replays never count as
  human microphone/playback acceptance.

The tested backend base is `302c44b`. The room UI was selectively adapted from
`feat/voice-room` at `4b508ee`; this is not a merge of that branch's later avatar/call
experiments. When bringing in further UI changes, retain the tested PTT floor,
playback acknowledgements, cancellation/reconnect guards and videos-off setting.

## Checkpoint and branch history

The verified implementation is recorded in `1cde6c7` (room integration and handoff)
and `8e03068` (grounded report coaching and terminal lifecycle), followed by this
documentation update. Publication targets `yang` through authenticated local Git,
preserving the branch's existing history with a normal fast-forward update.
The earlier GitHub app write refusal is superseded by the user's completed local
GitHub sign-in. Collaborators should pull `yang`, run the offline checks above,
and configure their own private credentials before continuing the open acceptance work.
