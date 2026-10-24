# Voice-room handoff — 24 October 2026

This is the verified voice-room integration for **`yang`**. Start here before
continuing A/B/C work. Read `CLAUDE.md` for the team rules and the latest
`DECISIONS.md` entries for the user-approved local choices.

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
| Offline backend gate | 281 tests; Ruff, Pyright, generated schema and mock fixtures passed, including setup, grading, terminal clock, preparing responses and final-only persistence. Re-run commands below on your checkout. |
| Offline frontend/audio gate | 151 tests passed, including PTT, cancellation, setup, portraits, terminal guards, safe API errors and bounded report-preparation polling. |
| Voice hardware | User confirmed microphone transcription, distinct clear voices, complete PTT turns through pauses, and automatic closing/report handoff. Earlier voice-lab latency sign-off is not a full-room acoustic latency guarantee. |
| Two real-audience human flows | Natural blackout and natural countdown → Q&A runs both reached reports automatically with clear audio. Together: 12 real Boson reasoning successes; zero recorded model failures/fallbacks/rejections, room errors, skips or unanswered questions. |
| Boson structured-output preflight | Decisions, follow-ups, recovery grading and custom-persona expansion all passed a bounded live check. Responses use grounding/validation and explicit diagnostics. |
| Delayed-closing fix | Exact-timing regression tests and a separate real Boson grading replay passed. The replay used saved text with synthetic delivery/clock and mock audio; it is not a new human presentation. |
| New content-coaching pass | One live Boson report call passed using fictional text, injected Q&A and silent mock audio. An initial formatting failure was fixed and retained in private diagnostic evidence; this is not a new human run. |

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

Original reports were preserved. Subsequent fixes and replay tests do not retroactively
make the original runs clean final-build demonstrations.

### Still open

- **P0-13 is not signed off:** two consecutive unaided, recorded runs of the final build
  still need acceptance. The blackout run had no presenter speech before automatic
  restoration, so its recovery gap/evidence/score correctly stayed unassessed.
- **P0-14 is not done:** no backup screen recording has been shared.
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
3. **All:** freeze the build, do two consecutive complete unaided recorded presentations
   without debug controls, then save the backup recording. Update P0-13/P0-14 only when
   the evidence meets their criteria.
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
