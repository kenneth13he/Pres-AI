# Voice protocol and local checks

Official Boson documentation reviewed 23 October 2026. Documented capabilities still need
live checks on the demo computer; synthetic audio checks do not establish microphone or
speaker quality, browser permission behavior, or human speech-to-audible-response latency.

## Architecture

PresAI must control when a persona speaks and the exact text it speaks. The reliable shape
is a silent Realtime transcription connection plus backend TTS for each persona turn.
The browser sends microphone audio directly to Boson using a temporary credential; persona
speech is carried on a separate binary audio transport, outside the session JSON event bus.

**Do not use `create_response: false` to silence Realtime VAD.** Boson accepts this field
but ignores it. Its server/semantic VAD always creates a response at the end of a turn.
`session.type: transcription` is unsupported. Silent listening therefore uses
`audio.input.turn_detection: null`, browser-side utterance boundaries (or push-to-talk),
`input_audio_buffer.append`, and `input_audio_buffer.commit`. Committing a manual turn
transcribes it but does not generate an assistant response. Do not send `response.create`
unless a response is actually wanted.

Sources: [migration differences](https://docs.boson.ai/models/higgs-realtime/migrate-an-existing-integration),
[client events](https://docs.boson.ai/api-reference/realtime/client-events).

## Authentication and configuration

The server mints a credential via `POST /v1/realtime/client_secrets` with its private Bearer
key and `{"expires_after":{"seconds":300}}`. Only `value` and its expiry go to the browser.
The browser opens `wss://api.boson.ai/v1/realtime` with WebSocket subprotocols `realtime` and
`bai-client-secret.<value>`. Temporary keys expire; mint a fresh key per connection.
Credentials and the full subprotocol list must never be logged.

Send `session.update` immediately after opening. The first acknowledgement is
`session.created`; later updates return `session.updated`. Waiting for `session.created`
before configuring would deadlock. Set `session.model: higgs-realtime`, exactly one
`output_modalities` value (`["audio"]` or `["text"]`), and nested `audio.input/output`
configuration. Enable `audio.input.transcription.model: higgs-stt-3.1`.

Source: [connections and sessions](https://docs.boson.ai/models/higgs-realtime/guides/connections-and-sessions).

## Audio, transcripts, timing, and cancellation

PCM is signed 16-bit, little-endian, mono, normally 24 kHz. Keep microphone chunks small.
HTTP stream chunk boundaries need not align to samples, so keep a trailing byte for the
next chunk. Browser playback needs its own completion signal; `response.done` only says
generation has ended, not that the queued audio has finished playing.

User transcripts arrive only as `conversation.item.input_audio_transcription.completed`
with `item_id` and `transcript`; the final event does not carry word timestamps. With
vendor VAD, `speech_started.audio_start_ms` and `speech_stopped.audio_end_ms` refer to the
input-audio clock. With manual turns, preserve the browser's captured speech start/end
times and identify that timing source. Transcript arrival time is not speech-resumption
time. Stop queued playback on a barge-in or cancel, and avoid overlapping persona turns.

Sources: [audio format](https://docs.boson.ai/models/higgs-realtime/guides/audio-and-voices),
[server events](https://docs.boson.ai/api-reference/realtime/server-events),
[interruptions](https://docs.boson.ai/models/higgs-realtime/guides/turn-detection-and-interruptions).

## TTS and voices

`POST /v1/audio/speech` accepts `model: higgs-tts-3`, `input`, and `voice`. Streaming requires
`stream: true, response_format: pcm`; it returns raw 24 kHz PCM. A non-streaming `wav`
response is easiest to inspect manually. Word timestamps require non-streaming output and
change the response into a JSON envelope with base64 audio.

Documented preset voices include `eleanor`, `jake`, `oliver`, `chloe`, `marcus`, and `nora`.
`GET /v1/audio/voices` describes registered reference voices and returns `data` items with
`voice`, `description`, and `created_at`; do not assume it enumerates every built-in preset.
Use delivery tags such as `<|emotion:anger|><|prosody:speed_fast|>` before the speech text.
Use fictional personas and preset voices. Realtime prompted script fidelity and changing
voices after an audio response must be measured rather than assumed.

Sources: [speech API](https://docs.boson.ai/api-reference/audio/create-a-speech),
[preset voices](https://docs.boson.ai/models/higgs-tts/voices),
[list voices](https://docs.boson.ai/api-reference/audio/list-voices),
[delivery tags](https://docs.boson.ai/models/higgs-tts/tags).

## Opt-in validation

Run from the repository root, with the existing secret in the ignored `.env`:

```sh
.venv/bin/python scripts/try_voice.py --live --check output
.venv/bin/python scripts/try_voice.py --live --check realtime
.venv/bin/python scripts/try_voice.py --live --check transcription
.venv/bin/python scripts/try_voice.py --live --check browser-auth
```

`--check all` runs each check. Every check has a 60-second hard timeout and closes sockets
on exit. Requests never run at import, and `--live` is required. Results and synthetic WAVs
are stored in ignored `data/voice_checks/`. Only safe summaries are printed; credentials
and raw error bodies are suppressed.

The transcription test reuses `first_speech.wav` if present, otherwise `output.wav`; it
creates a short TTS fixture only if neither exists. It verifies that manual commit emits a
final transcript and observes another 1.5 seconds for unwanted autonomous responses.
`browser-auth` validates the browser-style WebSocket subprotocol using a Python client;
the actual browser/runtime remains a separate test. The Realtime test saves two synthetic
spoken turns, compares caption words to the requested line, and tries a voice update.
It cannot establish perceptual voice differences or audible quality without listening.

## Native speech-to-speech validation (voice-check lab only)

The voice-check page also offers **Live AI conversation · Higgs**. This uses direct native
audio input and generated audio output, manually requesting one response after a committed
utterance. It carries the conversation history, so follow-up questions can refer to earlier
answers. The production presentation room keeps the split STT/orchestrator/TTS architecture;
this lab mode does not replace its audience orchestrator or claim to validate Claude latency.
The fixed diagnostic is a separate mode and is not evidence of conversational generation.

The opt-in synthetic check is:

```sh
.venv/bin/python scripts/try_voice_conversation.py --live --fixture data/voice_checks/question_one.wav data/voice_checks/question_two.wav
```

On 24 October 2026 it answered “What is seven plus five?” with “Seven plus five equals
twelve,” then answered “What if I add three to that result?” with “That would make the
total 15.” No scripted answer or input override was supplied. First received audio was
468 / 655 ms after the paced synthetic input ended. These figures exclude live utterance
detection, browser playback and device output delay. User validation of this new browser
conversation mode remains required.
