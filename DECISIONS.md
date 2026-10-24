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

- Test 1 — round-trip latency: _pending_
- Test 2 — scripted line on demand / per-turn voice: _pending_
- Test 3 — STT timestamps: _pending_
- Test 4 — TTS tags + two distinct preset voices: _pending_
- Test 5 — ephemeral client secret in the browser: _pending_
- **Voice architecture:** Shape 1 or Shape 2 — _decide by hour 2_

## 2026-10-24 · Lean call: one brain call, still Higgs faces, mic always on
- The panel's behaviour is one Claude call per presenter sentence (or 5 s of silence):
  `Orchestrator.turn` → `PanelTurn` (wait / speak / curveball). Replaces decide + follow_up +
  reply + the regex social layer. Brain calls run beside the room, never blocking the mic.
- Faces are stills of Higgs's built-in avatars (Claire, James, Emma) in `demo/faces/higgs/`;
  the speaking tile glows. Video clips, rest loops and live avatars (LiveKit) are removed:
  too slow and fragile for the demo. Return trigger: Boson enables 3 concurrent live avatars.
- The mic is always on. The server drops only echo (a line that is mostly the panelist's own
  words while they are talking), so a presenter talking over the panel is still heard.
- Voices: Higgs TTS 3 raw PCM in each character's cloned voice → WAV clip; its exact length
  tells the engine how long the panel is talking.

## 2026-10-24 · Three live faces on one key
- Measured: Higgs runs three realtime avatars at once on our key, but only one per LiveKit
  room, and starting them back to back is rate-limited (429). One room per panelist, started
  15 s apart → all three live. Higgs's realtime slots are shared platform-wide: "every
  realtime avatar slot is in use" happens; a refused seat retries every 20 s (5 tries) and
  keeps its still face and voice meanwhile.
- Live faces are released when the call ends, on server shutdown, or 60 s after the last
  browser tab leaves; each also has a 15-min hard cap.
- Echo: a line that mostly repeats the panel's words is dropped while they talk and for 4 s
  after (speech recognition is late). Headphones avoid it entirely.
