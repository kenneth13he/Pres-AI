# Voice and audience setup

Run these commands from your cloned repository's root. The macOS launchers require
Python 3.12 (or `uv`) and Node.js with the `--test-timeout` option. Setup prefers Node
already on your PATH; a Codex-bundled runtime is an optional fallback, not a requirement.
Other platforms can use the commands in [README.md](../README.md).

```sh
./setup_local.command
```

Setup creates `.venv`, installs the pinned dependencies, creates `.env` only if missing,
and runs the offline Python and frontend checks. It preserves an existing `.env`.
The template defaults to mock adapters, so installing dependencies does not call a vendor.

For real speech and audience reasoning, privately put your Boson key in `.env` and select:

```dotenv
BOSON_API_KEY=your_private_key_here
VOICE_ADAPTER=higgs
ORCHESTRATOR=boson
BOSON_REASONING_MODEL=higgs-realtime
BOSON_AVATAR_ENABLED=false
DEBUG_CURVEBALL_ENDPOINT=false
```

The Boson audience and voice share that account's balance; usage is billable. An Anthropic
key is unnecessary for `ORCHESTRATOR=boson`. The separate Claude adapter remains optional.
Never commit `.env` or paste its values into shared instructions. Safe reasoning counters
appear in session snapshots. Raw microphone audio is not saved; completed transcripts and
reports are saved privately under ignored `data/sessions/`. Speech and reasoning context
are sent to Boson. No camera or talking-head videos are used.

Start the app, then open [setup](http://127.0.0.1:8000/setup.html):

```sh
./start_local.command
```

The launcher binds only to `127.0.0.1:8000`. Press Control-C in its terminal to stop it.
Restart after changing adapter settings. For offline work, keep both adapters on `mock`
and use the explicitly labelled `/room.html?mock=1` and `/report.html?mock=1` previews.

## Current room controls

Create a session with the default **Hold to talk** input. Start waits for microphone
authorization and both audio connections before the presentation timer begins. Hold the
button or Space through each complete point and any thinking pause; release to submit it.
Hands-free remains optional and uses a 1.1-second pause detector. A turn longer than one
minute is discarded instead of submitting an unfinished point.

Persona speech mutes capture to avoid self-transcription. Pause, Skip and End cancel queued
speech. Playback completion acknowledgements control when the backend returns the floor;
delayed transcripts cannot answer questions they preceded. Resume reconnects audio before
unfreezing a paused timer if its idle connection has closed.

Click **End → Q&A** once to enter the closing round. The button becomes disabled
**Q&A in progress**. Answer with Hold to talk; the report link appears automatically after
the final answer and acknowledgement. **Finish session early** is a separate intentional
exit that skips an unfinished question without penalty. See
[ROOM_VOICE_INTEGRATION.md](ROOM_VOICE_INTEGRATION.md) for details and acceptance limits.

## Voice check and offline verification

For an isolated microphone test, open [voice check](http://127.0.0.1:8000/voice-check.html),
keep **Hold to talk** and **Live AI conversation · Higgs**, connect audio, then start the
microphone. Hold through a mid-question pause, finish, and release: expect one relevant
reply after release. Test Moderator, VC and Student separately for clear, distinct voices.
The displayed speech-end-to-first-received-audio time excludes device playback delay.
Human listening remains the hardware check. The separate fixed-reply diagnostic does not
test generated audience reasoning. Stop audio when finished; connections have a one-minute
idle limit and a ten-minute hard limit.

These checks do not contact a vendor:

```sh
make check
node --test --test-timeout=5000 scripts/test_*.mjs
```

Live validation commands in [VOICE_PROTOCOL.md](VOICE_PROTOCOL.md) require explicit
`--live` and consume Boson credits. Diagnostic output remains in ignored
`data/voice_checks/`. The dated entries below are historical checkpoints; the current
setup and controls above supersede their earlier instructions and configuration states.

## Verification on 23 October 2026, Toronto

- Baseline: 72 backend tests passed before voice changes.
- Final backend checks: lint, type, schema, mock fixtures and 94 tests passed.
- Browser audio code: 16 deterministic tests passed; these emulate audio APIs, not hardware.
- Live TTS: default speech first bytes in 262 ms in the initial direct API test.
- Live manual STT: a synthetic speech fixture transcribed 319 ms after commit; no autonomous
  response during the following 1.5 seconds. It misrecognized "PresAI" as "Precise", so
  recognition quality still needs checking against your presentation vocabulary.
- Realtime scripted speech: both turns' caption words matched the script; session voice
  update default → eleanor accepted; first audio 315 / 439 ms. Audible difference untested.
- Local binary TTS transport: Moderator / VC / Student accepted, including impatient and
  confused style tags; first binary audio 899 / 492 / 416 ms in this run. These are single
  samples, not latency guarantees. The backend waited for playback acknowledgement.
- Temporary credentials: local mint endpoint and actual Boson WebSocket subprotocol passed.
- Full room backend check: synthetic transcript + live Boson TTS, fixed mock audience,
  heckler/answer/acknowledgement/report flow exercised. Hardware remains unverified.

Live calls are short and billable. The balance has not been verified. `/health` estimates
this process's TTS/audio usage; it is not an account balance and excludes other devices,
standalone validation scripts, Realtime token charges and pricing changes. Restarting the
server resets that estimate. No raw microphone audio is stored. Opt-in diagnostic WAVs are
synthetic and saved only under ignored `data/voice_checks/`.

Re-run automated checks without contacting Boson:

```sh
make check
node --test scripts/test_browser_audio.mjs scripts/test_voice_bridge.mjs
```

If Node is not in your terminal PATH, use the bundled executable at
`~/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node` for the second command.

Opt-in live checks and protocol sources are in [VOICE_PROTOCOL.md](VOICE_PROTOCOL.md).
Safe local results are in `data/voice_checks/*.json`; generated samples are there too.

## Human listening check — 2026-10-24 00:18 EDT

The user played the moderator line and confirmed it was clear and complete, then played
Dana (VC) and Sam (Student) and confirmed all three voices were clear and distinct. This
completes P0-11 listening validation in the local browser. Microphone and round-trip timing
checks are ongoing. Feedback was supplied by the user; no automated browser observation
was performed because the saved browser access permission remains blocked.

## Human microphone diagnostic — 2026-10-24 00:21 EDT

The user confirmed the microphone transcript was good and reported 1691 ms on the fixed-reply
diagnostic. This measures captured speech end to first received reply audio, excluding
device output delay. The fixed line does not validate conversational generation. P0-2
remains pending an actual generated spoken response and audible delay confirmation.

## Actual conversational test (24 October update)

Reload the voice-check page and choose **Live AI conversation · Higgs** before connecting
(the default). Connect audio, start the microphone, ask “What is seven plus five?”, wait
for the complete answer, then ask “Now add three to that result.” Replies are generated
from the actual audio conversation. Correct results should be twelve, then fifteen.
Check that the transcript matches, one reply plays per turn, AI speech is not transcribed
as user speech, and you hear each reply begin within roughly two seconds. Record the new
displayed timing separately from the previous fixed diagnostic.

The displayed metric is now accurately labelled speech end to **first received audio**;
it excludes device output delay. Native speech-to-speech is a voice validation mode, not
the production Claude audience orchestrator. To repeat the earlier diagnostic, choose
**Fixed reply · audio diagnostic** before connecting.

After this update all 94 backend tests and 23 audio/conversation tests pass. No browser
control or indirect UI observation was used; human feedback remains the hardware evidence.

## Human native conversation result — 2026-10-24 00:29 EDT

The user confirmed the actual browser microphone produced context-dependent spoken answers
of twelve, then fifteen, with one reply per turn. They reported 1394 ms displayed latency
for the live test (one value was supplied, not separate measurements for both turns).
This is captured speech end to first received reply audio; device output delay is additional.
The earlier 1691 ms remains separate evidence for the fixed diagnostic. P0-11 is complete;
P0-2's functional native mic/model/spoken-reply path passed. A final human confirmation of
the roughly two-second audible target is pending; acoustic latency was not instrumented.

## Premature-response regression and fix — 2026-10-24 00:38 EDT

The user tried five or six questions: most replies were timely and correct, but once the AI
answered an unfinished question with an unrelated response. P0-2 remains pending this retest.
Inspection found a 650 ms low-volume/pause endpoint and a 20 s forced commit, either of which
could submit partial speech and mute the remaining question during reply generation.

The voice-check now defaults to **Hold to talk · recommended**. Hold its visible question
button (or Space) through the entire question and any thinking pauses; release only after
finishing. The AI receives a submitted turn only on release. Focus loss or pointer
cancellation discards unfinished input, and queued audio from cancelled turns is ignored.
**Stop reply** cancels a response without closing the microphone.

Hands-free remains optional and waits for 1.1 s of silence with a lower continuation
threshold for quiet words. It is still a pause detector, not proof of semantic completion.
After 60 s an overlong turn is discarded with an explanatory status; the limit never
forces a reply to a partial question. This preserves the plan's push-to-talk fallback.

Retest: reload, keep Hold to talk and Live AI conversation selected, connect and start the
microphone. Hold while saying “What is seven…”; pause for two seconds while still holding,
then finish “…plus five?” Release. There must be no answer during the pause and exactly
one relevant answer after release. Repeat with a longer natural question and a follow-up;
confirm timing still feels within roughly two seconds after finishing/releasing.

Current checks: 94 backend tests and 40 audio/turn-control tests pass. No new paid calls,
recordings, or automatic browser observations were required for this fix.

## Current acceptance — 2026-10-24 00:44 EDT

**P0-2 and P0-11 are complete locally.** P0-2 is accepted using the plan’s explicit
push-to-talk fallback, not a claim that automatic turn detection is universally reliable.

The user held through an intentional mid-question pause, finished the question, and released,
then repeated with a longer natural question. They confirmed the AI waited, answered
correctly once, and began audibly within roughly two seconds. Reported displayed latency:
**1663 ms**, captured speech end to first received reply audio. Audible timing is a human
approximation; acoustic onset was not instrumented. Moderator, VC and student clarity and
voice distinction were independently confirmed earlier.

This acceptance supersedes the earlier pending/retest entries, which remain as history.
The earlier 1691 ms fixed diagnostic and 1394 ms hands-free native result are separate
observations. One premature hands-free turn was reported; the hold/release regression
retest passed after the fix.

Current automated verification: **94 backend tests + 40 audio/control tests passed**.
No full presentation-room acceptance, two-run demo or backup recording is claimed; those
remain P0-13/P0-14. This Mac still uses a mock audience orchestrator without an Anthropic key.

## Presentation room is now wired — 2026-10-24 01:11 EDT

Use [setup](http://127.0.0.1:8000/setup.html) for the actual presentation room. Hold-to-talk
is the default in the form and backend. Start waits for a working microphone, then the
button/Space records complete presentation points and answers. Audience questions first
become eligible after 30 s; End enters Q&A and the report phase closes audio.

See [ROOM_VOICE_INTEGRATION.md](ROOM_VOICE_INTEGRATION.md) for the integration, usage and
remaining limits. Current checks: 109 backend + 77 audio/controller tests pass. Actual
local-server flow with live TTS passed; inputs and playback ACKs in that check were synthetic.
P0-13/P0-14 still need whole-room human demos and recording. The audience is visibly in test
mode on this Mac until a private Anthropic key is configured.

## Current real-audience room status —24 October2026

The existing Boson key now runs text reasoning and voice. No Anthropic key or calls are used. Two full human room flows completed with clear audio and automatic Q&A/report: [blackout](http://127.0.0.1:8000/report.html?session=bb1e3b93) and [countdown](http://127.0.0.1:8000/report.html?session=ff575163). The original reports are historical: blackout recovery was unobserved, and the countdown report missed a late-submitted closing turn.

The local app now includes the subsequent fixes: a canonical sixty-second warning, and once-only grading for an already-held turn submitted after countdown expiry. Report notes retain any measured overrun and unknown word-level timing.240 backend and133 frontend checks pass, plus a supplemental real Boson timing replay; that replay is not human demo evidence. Formal clean-demo/recovery/recording sign-off remains open. Everything is local and unpushed.
