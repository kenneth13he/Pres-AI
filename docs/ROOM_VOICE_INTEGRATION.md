# Presentation-room voice integration

Integration prepared for `yang`, 24 October 2026 (America/Toronto). See
[`COLLABORATOR_HANDOFF.md`](../COLLABORATOR_HANDOFF.md) for the current verified state,
publication scope and remaining checks.

## What is integrated

- New sessions default to `push_to_talk` in the backend contract, generated schema and
  setup selector. An explicit hands-free selection is still supported.
- `/room.html?session=...` uses backend-controlled Higgs speech and Higgs transcription.
  The native conversation voice-check remains a separate diagnostic; it does not replace
  the presentation audience orchestrator.
- The room has a visible **Hold to talk** button and keyboard Space support. Hold through
  thinking pauses and release only when the complete point or answer is finished.
- Microphone authorization and both audio connections must succeed before the first
  `presentation_started` message. A failed microphone attempt does not start the timer.
- Turn IDs connect capture start, release/discard and the final transcript. The backend
  keeps the presenter floor while held and while that final transcript is pending.
  Slow audience calls recheck the floor before producing any question or follow-up.
- Floor messages remain responsive while the event connection processes a model call.
  Pause, Skip and End use REST and cancel capture/audio before waiting on session work.
  Cancelled transcript results cannot become later answers.
- A binary audio connection carries speech outside the JSON event bus. Playback must
  acknowledge completion before the backend gives the floor back. **Stop reply** cancels
  spoken audio; **Skip** dismisses the current question/curveball without a scoring penalty.
- The room displays real deck PNGs, captions, persona and moderator speaking states,
  elapsed/countdown timers, and the existing MVP curveball effects. Reconnecting audio
  retains the session clock. Pause freezes the timer, including paused reconnect snapshots.
- End enters the backend Q&A phase and keeps the microphone available. The report phase
  stops the microphone/audio and exposes a report link. Page exit closes both transports.
- Completion is announced before report grading. While feedback is being prepared,
  the report endpoint returns HTTP 409 with code `report_preparing`; the report page
  retries that state automatically for up to 45 seconds. A finished report is saved once.
- Content coaching resolves source IDs to exact captured text. Unsupported dimensions
  remain unassessed; metrics, recovery and history are not rewritten by the model.
- Finished elapsed time is frozen. Late events, capture results and slide controls do
  not reopen or mutate the finished room.
- Recovery transcript start times use detected speech onset rather than the time the
  hold button was pressed. Silent holds are discarded rather than generating a reply.

## Run locally

Start the server with `./start_local.command`, then open
[setup](http://127.0.0.1:8000/setup.html). The server binds only to the local machine.

1. Keep the default preset and hold-to-talk input. Optionally upload `demo/sample_pitch.pdf`.
2. Create the room and press **Start presenting**. Allow microphone access.
3. Present a claim while holding the button or Space. Release between complete points.
   The scheduler first permits audience questions after about 30 seconds of content.
4. When an audience member finishes speaking, hold to give a complete answer. A thin answer
   can receive one follow-up. The captions show the exchange and speaker highlighting
   follows the actual playback lifecycle.
5. Try Pause/Resume, Skip and End → Q&A. The main End button then disables; answer
   until the report link appears. The separate Finish session early button is an
   intentional exit from Q&A.

Microphone speech goes to Boson for transcription. Raw microphone audio is not saved.
Transcripts stay in the local session. No camera is used.

## Local UI integration from feat/voice-room

The room design, same-room fictional portraits, audience builder and report page were
adapted from upstream commit `4b508eecf37915417cafe504ee95bd2e6335ab67` on 24 October.
This is a selective local integration, not a branch merge. The pre-integration source
and patch are backed up in the sibling `backups/before_voice_room_ui_20261024_012216/`
folder; the backup excludes credentials and ignored runtime data.

- The shared-table room shows a static portrait, name, role and speaking state for each
  audience member, plus a moderator seat. Captions and speech bubbles use plain text.
- Setup supports two or three roster members, skepticism sliders, a custom third member,
  and Off / Surprise me / Choose curveballs. The visible audience must match the submitted
  seats; adding a custom member never silently removes a selected person.
- The report renders dimensions, caveats, metrics, strengths, recovery evidence, key
  moments, improvements and persona feedback. Unmeasured values remain unmeasured;
  skipping is never presented as a penalty. Mock reports are labelled illustrative.
- Portrait selection preserves the accepted local voice assignments. Upstream filenames
  retain their original role prefixes, but the local helper chooses pictures to fit the
  existing voices where possible. The static cast has no Nora-specific character.
- Talking-head videos remain off. No upstream MP3/MP4 clip queue, avatar client, video
  generation, idle rendering or new video dependencies were imported. The tested manual
  STT, binary PCM transport, playback acknowledgements and input safeguards remain in use.

Open [setup](http://127.0.0.1:8000/setup.html) to create a new audience, or reload an
unstarted room to see the new layout. For a report-only preview, use the explicitly
illustrative [mock report](http://127.0.0.1:8000/report.html?mock=1).

## Reasoning configuration and acceptance limits

For offline work, keep `VOICE_ADAPTER=mock` and `ORCHESTRATOR=mock`; the audience is labelled
**audience test mode**. For real speech and audience reasoning, privately configure a Boson
key, `VOICE_ADAPTER=higgs`, `ORCHESTRATOR=boson`, and `BOSON_REASONING_MODEL=higgs-realtime`,
then restart the local server. Both adapters use the Boson account's balance. No Anthropic
key is needed for that configuration; the separate `claude` adapter remains optional.
Keep `BOSON_AVATAR_ENABLED=false` and `DEBUG_CURVEBALL_ENDPOINT=false` for normal runs.
No key is included in this guide. See [VOICE_SETUP.md](VOICE_SETUP.md) for setup steps.

P0-2 and P0-11 retain their earlier human acceptance in the voice lab. Two human room flows
also completed with real Boson reasoning, clear audio and automatic Q&A/report. Their original
reports remain historical evidence; subsequent countdown fixes were checked with a separately
labelled synthetic timing replay. A later recorded natural blackout measured 7.140-second
recovery, and the reviewed older-build backup now exists locally (see
[RECORDING_BACKUP.md](../demo/RECORDING_BACKUP.md)). P0-13's two clean final-build runs remain
open. Automated checks emulate browser APIs and do not replace human hardware testing.

## Automated verification

```sh
make check
node --test --test-timeout=5000 scripts/test_*.mjs
```

Use Node from your normal PATH for the browser checks. The macOS setup launcher can
also use an existing bundled runtime on Codex installations. No Node runtime is
required by the running app.

Current checks: **296 backend tests and 166 frontend/audio tests pass**, plus lint, types,
schema consistency and mock fixtures. Coverage includes real ASGI event/binary socket flows
with simulated vendor HTTP, standalone deterministic frontend controllers, audience
configuration/upload races, report rendering and portrait/speaker lifecycle. These are
not substitutes for human microphone/browser acceptance. Two human flows completed;
the handoff records their limits and the focused checks still required after fixes.

The UI integration also passed an actual local API check: a six-page sample PDF produced
a valid PNG; preset and custom rooms retained the selected roster, skepticism, curveball
choices and PTT default. All 22 required HTML/CSS/module URLs and 16 portraits are served.
At UI integration completion, fourteen protected voice/backend/controller files matched
the pre-UI backup byte for byte. The subsequent guided room test hardened keyboard
ownership in `mic.js`, with nine additional regressions. A later presentation-only
controller changes add visible Skip confirmation and reconnect-before-Resume; backend and
audio transports are unchanged.
`/health` confirms avatars off. The prepared, unstarted sample room is recorded in ignored
`data/voice_checks/prepared_room.json`; safe API results are in `ui_integration.json`.

During hold-to-talk, Space is reserved for speaking even while capture is temporarily
blocked by playback or Pause. Use Enter or click to activate other buttons. A Space press
that was denied cannot start later through key repeat; release and press again. Releasing
an old keyboard hold cannot submit a newer mouse-held turn. Editable fields keep normal
Space input.

The room now has a prominent current-state message and a separate confirmation when Skip
succeeds. Transcript history intentionally retains the old question; skipping dismisses
the active demand without erasing the record. The paused state explicitly says the timer
is frozen. Past skips do not show a fresh success banner on reload.

Unexpected audio loss now pauses the room automatically and freezes both timers. Held or
pending final input is discarded, playback canceled, and stale cleanup cannot affect a
replacement audio bridge. **Resume reconnects speech and microphone before unfreezing the
session**. A failed connection leaves the room paused with a retry message. If network loss
prevents confirming Pause, the page labels its freeze as local-only and repairs Pause on Resume.
Repeated clicks share one connection; End remains available during connection work, and
late responses cannot reopen a finished room. Reloading paused Q&A preserves Finish Q&A.
The one-minute idle and ten-minute hard limits remain intact.

The guided whole-room test is recorded separately in ignored
`data/voice_checks/full_room_acceptance.json`. The user has confirmed complete button and
Space holds through a two-second thinking pause, visible slides and three portraits, a
responding mic meter, frozen Pause timer, spoken quoted question → one follow-up →
acknowledgement, blackout/recovery/Restore, audible heckler and clear Skip confirmation,
and an audible sixty-second warning with a red countdown that freezes on Pause. Automatic
Q&A, the matching speaker portrait, one-click Resume reconnection and the real report page
also passed. The main session was manually finished before the final answer, so a separate
short room verified spoken closing question → complete answer → acknowledgement → automatic
report, with microphone/audio stopped. That closing check had zero errors and zero skips.

The first Space attempt reached the server only as a partial phrase; the focused retest
captured the full closing line once. The first blackout warning was not heard during a
test that automatically paused after the backend's end event. A foreground replay without
that automatic pause was heard completely; the original cause is unproven. Neither initial
failure is erased from the acceptance log. The test also found weak visible Skip feedback;
the new confirmation/current-state messages passed the user's retest.

The main guided session (`1e7452ac`) contains one historical audio-disconnected error at
the first Q&A question, which exposed the Resume bug and remains in the record. Its report
correctly has five manually injected curveballs (including replays), three skipped questions
including the manually ended final follow-up, and zero unanswered-question penalties.
The separate closing check (`de47e83d`) completed automatically with no errors/skips. This
is guided acceptance after fixes, not two clean unaided demos or a live Claude quality test.
P0-13's two unaided runs and P0-14's backup recording remain open.

An isolated actual-server smoke also passed all three manually forced MVP curveballs,
measured slides recovery, a skipped heckler without a recovery score, frozen countdown,
End → Q&A → one follow-up → report, six generated Higgs audio turns and zero room errors.
Its presenter transcripts and playback ACKs were synthetic. Its report's speech rate is
an artifact of injected timestamps, not a human measurement. Results are in ignored
`data/voice_checks/full_room_api_smoke.json`. Manual debug triggers bypass scheduler
budgets; this is not an unattended natural demo or a hardware/browser acceptance result.

For an opt-in local-server check that makes short billable Boson TTS calls:

```sh
.venv/bin/python scripts/try_room_voice.py --live --deck demo/sample_pitch.pdf
```

That check uses synthetic presenter transcripts and simulated playback acknowledgements,
waits across the actual 30-second scheduling threshold, and verifies held-floor protection,
grounded question/follow-up/ack audio, pause/resume and report evidence. Its safe report is
saved in ignored `data/voice_checks/room_integration.json`. It does not test a physical
microphone or audible device output.

Live local-server verification on 24 October passed in 36.73 s with three real Boson
TTS turns and zero room errors. Its results include the grounded claim quote, linked
follow-up, valid PNG, frozen pause clock and evidence report. Playback acknowledgements
and input transcript were simulated; this does not replace the full human room walkthrough.

## Client coordination details

The event connection accepts `presenter_turn_started`, `presenter_turn_ended` and
`presenter_turn_cancelled` with a `turn_id`. Final `transcript_segment` input carries that
same outer `turn_id` plus the unchanged `segment` contract. Capture IDs never travel inside
raw PCM. Session snapshots include the full `session_clock_ms`, pause-adjusted `elapsed_ms`
and nullable `timer_remaining_ms` so reconnecting controls retain their clocks. Server
SessionEvent types remain unchanged; the generated schema changes only the input-mode default.
