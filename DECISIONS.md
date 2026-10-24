# DECISIONS.md

Settled. Dated entries, newest first. Do not re-decide; a decision that looks wrong goes on your checkpoint report's `Proposed decision changes` line.

## 23 October 2026 — kickoff

- **Name:** PresAI (repo `kenneth13he/Pres-AI`). "PitchPanel" in the archived plan is history.
- **Vendor:** Higgs API (Boson AI), one key, **$100 of credit**. Realtime (`higgs-realtime`), TTS 3 (`higgs-tts-3`), STT (`higgs-stt-3.1`), Avatar. No LLM endpoint. Facts and the five hour-1 tests: CLAUDE.md §13.
- **Brain:** Claude `claude-opus-5-5` on an Anthropic key, official `anthropic` SDK, structured outputs, adaptive thinking, effort low (live) / high (report). Whose key and its monthly cap: **open** (CLAUDE.md §15 Q6).
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
