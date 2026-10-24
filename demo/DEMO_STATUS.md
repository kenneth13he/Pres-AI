# Demo status

Current local mode uses **live Boson/Higgs speech and audience reasoning** with the existing
Boson key and balance. Hold-to-talk is the default; static portraits are used and avatar
video is off. The Claude adapter remains available but was not used for these local runs.

Last updated: 2026-10-24. Prepared checkpoint gate: **281 backend + 151 frontend/audio tests**,
plus lint, type, schema and mock checks. Two full human flows completed with clear audio
and automatic Q&A/report finish: 12 real reasoning successes, zero recorded errors or
fallbacks. **Formal two-clean-demo acceptance (P0-13) and backup recording (P0-14) remain open.**

The table distinguishes live local behavior from remaining demo evidence. Historical
checkpoints below retain the provider and test state that applied at the time.

Content coaching now uses a bounded real-model pass with verified source references;
unsupported dimensions remain unassessed. Audio stops before feedback preparation, and
the report automatically waits for the result. Its live synthetic preflight passed;
new microphone acceptance is deferred at the user's request. GitHub publication remains
blocked on write authentication; the full source and collaborator handoff are saved locally.

| # | Demo step (CLAUDE.md §13 script) | State | Notes |
|---|---|---|---|
| 1 | Pick preset / build audience on `/setup` | implementation and API checks passed | Roster, skepticism, custom third seat and curveball choices work; complete human setup walkthrough remains unsigned |
| 2 | Upload PDF, slides render in room | live locally; human room visuals confirmed | PDF/PNG upload probe passed; user confirmed visible slides and portraits in the guided room test |
| 3 | Presenter speaks, transcript appears | live locally; human hold-to-talk verified | Button/Space holds preserve deliberate pauses until release; microphone transcript and room controls passed human checks. Hands-free is optional and has separate reliability limits |
| 4 | Persona asks a grounded question in its own voice | live Boson; human flow confirmed | Real Higgs reasoning and speech used microphone transcript evidence; moderator and persona voices passed earlier human listening |
| 5 | Presenter answers, persona follows up once | live Boson; human flow confirmed | Spoken answers, one follow-up per question and acknowledgement/hand-back completed in both full flows |
| 6 | `slides_down` fires, viewer goes black | live locally; natural trigger and auto-restore verified | Natural blackout and countdown each fired once in the human runs. Guided tests separately covered blackout/Restore, heckler/Skip and frozen Pause timer |
| 7 | Presenter resumes; recovery seconds measured | partial demo coverage | Earlier guided mock-audience test measured 5.331 s. Natural blackout run had no speech during the effect, so timing/evidence/score correctly remain null. Measured natural blackout recovery is still undemonstrated |
| 8 | Q&A, then report with evidence quotes | human automatic finish confirmed; new coaching pass awaits microphone retest | Original flows had zero skips/unanswered questions. Countdown fixes passed tests/replay. New source-ID coaching, preparing/retry handling and final-only persistence passed offline checks plus a separate live Boson preflight; final-build human acceptance remains open |
| — | Two clean final-build demos | open | Two human flows completed, but missing recovery coverage and findings fixed afterward prevent P0-13 sign-off. Supplemental replay is separate from human demo evidence |
| — | Backup recording exists in `demo/` | no | P0-14 remains open |

## Hour gates

| Hour | Gate | Outcome |
|---|---|---|
| 1 | Contracts merged; all three run `make check` | scaffold: yes |
| 3–4 | Voice round trip | B local acceptance: native push-to-talk, user-confirmed audible ~2 s; first received audio 1663 ms |
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

## B local voice verification — 23 October 2026

Voice code is ready for hardware validation at `/voice-check.html`; it is not marked stage-live.
94 backend tests and 16 audio tests pass. Live synthetic/manual STT, Realtime script/voice
update, temporary auth, and three streamed TTS presets pass. API timing is not human audible
latency. See `docs/VOICE_SETUP.md` for measurements and remaining checks. The local browser
preview was declined; microphone permissions, listening quality and two clean stage runs
remain unverified. This Mac has Boson configured and the audience brain on mocks.

## B human native conversation — 2026-10-24 00:29 EDT

User confirmed microphone transcript quality, context-dependent native spoken answers
(twelve, then fifteen), one reply per turn, and reported 1394 ms to first received audio.
User also confirmed clear/distinct moderator, VC and student voices (P0-11 complete).
The live audible ~2 s target awaits final human confirmation; the displayed number is not
an acoustic measurement. Full presentation-room acceptance, two clean demos and recording
remain separate P0-13/P0-14 work. Current automated gate: 94 backend + 23 audio tests pass.

## P0-2 boundary regression — 2026-10-24 00:38 EDT

Across five or six human questions most replies were timely/right, but one started before
the presenter finished and was unrelated. P0-2 is not signed off. The local test now
defaults to explicit hold/release; hands-free silence is 1.1 s, and recording limits
discard rather than submit. 94 backend and 40 audio tests pass; human retest pending.

## B local voice acceptance — 2026-10-24 00:44 EDT

P0-2 accepted using the plan’s push-to-talk fallback: user confirmed waiting until
release despite a deliberate pause, one correct reply, and audible onset within roughly
two seconds. Displayed first-received-audio latency was 1663 ms, excluding device output
delay. P0-11 clear/distinct moderator, VC and student voices also passed human listening.

This supersedes the prior P0-2 pending entries; automatic hands-free turn detection remains
a separate reliability limitation. Full Claude audience-room integration, two stage-style
runs and backup recording are still pending. No claim is made that all demo rows are live.

## Local room integration — 2026-10-24 01:11 EDT

Hold-to-talk now defaults in setup and SessionConfig. Actual room controls and voice bridge
are connected, microphone readiness precedes Start, and floor IDs protect speech plus
pending final transcription. Pause/Skip/End remain responsive through model/voice work.
109 backend and 77 audio/controller tests pass. A 36.73 s local-server probe with live
Boson TTS passed quoted-question/follow-up/ack, held-floor protection, frozen pause and
report evidence with zero errors; its presenter transcript and playback ACKs were simulated.
No actual browser walkthrough or two human demos are claimed. The room shows audience test
mode because this Mac still lacks an Anthropic key. Nothing was pushed or merged.

## Local UI integration — 2026-10-24 01:36 EDT

Adapted feat/voice-room `4b508ee` locally: same-room static portraits, compact shared table,
speaker bubbles, full audience builder, and full report rendering with evidence and caveats.
Hold-to-talk remains the default; the accepted voice transport, floor, cancellation and
playback safeguards are unchanged. Videos stay off; no avatar pipeline was imported.
109 backend + 104 frontend/audio tests pass. Local API checks created preset/custom rooms
with correct options and rendered a six-page PDF. A saved real report validates against the
new renderer; mock reports are visibly illustrative. Served assets/imports and credential
checks pass. No new browser/hardware walkthrough or two human runs are claimed.
Prepared room: /room.html?session=82b73366. Everything remains local and unpushed.

## Guided room test in progress — 24 October 2026

Fresh human test session `1e7452ac`: user confirmed the complete hold-button sentence once,
two-second mid-sentence pause without an early audience reply, visible slides and three
portraits, reacting mic meter and frozen Pause timer. Audience/follow-up, Space, curveballs
and final report are not yet accepted. Three curveballs will be manually injected for
this guided diagnostic; it is not an unattended scheduler demo.

Code review reproduced and fixed nine Space ownership regressions, including a denied
hold starting from key repeat and an old key release ending a newer pointer hold.
113 frontend/audio tests pass. Space remains reserved for PTT; Enter or clicking activates
other buttons. The existing backend/floor/voice path is unchanged.

A separate isolated API smoke passed six live Higgs TTS turns, all three forced curveballs,
measured synthetic recovery, skipped heckler with null recovery, frozen countdown, Q&A
with one follow-up, and report generation with zero room errors. Presenter input and audio
ACKs were simulated; its speech-rate metric is not a human measurement. No human speech,
browser playback or natural trigger acceptance is inferred from that result.

## Guided room test completed after fixes — 24 October 2026, 02:43 EDT

User confirmed button and focused Space holds through two-second pauses, one complete
transcript, quoted spoken question → one follow-up → acknowledgement, slides/portraits/meter,
blackout/recovery/Restore, audible heckler, visible Skip/no-penalty confirmation, frozen
Pause timer/red countdown, automatic Q&A with matching portrait, automatic audio reconnect
on Resume, and the actual report's quotes/5.3 s recovery/skips/timeline.

Fixed three findings locally: keyboard ownership, weak Skip/current-state feedback, and
Resume restarting a paused room after idle without first reconnecting audio. Q&A reload
context, concurrent clicks, End during connection and late terminal responses are covered.
131 frontend/audio + 109 backend tests pass; independent controller/view review passed45.
Idle/hard limits and talking-head videos-off preference remain intact.

The first room `1e7452ac` retains its one historical audio-reconnect error and all replay
attempts. The final follow-up was manually ended, counted as skipped with no penalty.
A fresh short room `de47e83d` then passed spoken closing question→answer→ack→automatic
report with microphone/audio stopped, zero errors, zero skips and zero unanswered questions.
This is guided testing with live Higgs speech and mock audience reasoning. It is not two
clean unaided demos; P0-13/P0-14 and real Claude reasoning remain pending. No push or commit.

## Existing Boson key and two real-audience human runs —24 October2026

Local mode is now real Boson/Higgs audience reasoning with the existing key/balance, not Claude; the user declined separate Claude API billing. Hold-to-talk remains default, tested voices/controls retained, videos off, no push.

User confirmed bb1e3b93 (natural blackout) and ff575163 (natural countdown→Q&A) completed with clear audio and automatic report finish. Together:12 real reasoning successes; zero failures/fallbacks/rejections, room errors, skips or unanswered questions. Reports remain available after restart.

Strict clean-demo coverage remains open. Run1 correctly has no measured blackout recovery because speech began after restoration. Run2 revealed an ungraded closing turn submitted after zero and an AI warning saying five minutes while the timer allowed60s. Both code issues are fixed locally: canonical60s speech and bounded once-only delayed-final assessment with explicit overrun/word-timing caveat.240 backend/133 frontend tests and a separate real Boson timing replay pass; the replay is synthetic delivery/clock, not a new human run. Original reports remain unchanged. P0-13/P0-14 are not closed.
