# PitchPanel — AI Presentation Audience with Live Curveballs

> **Boson AI Hackathon | 3 developers | 24-hour prototype | Claude Code build specification**
>
> **Purpose:** Paste this document into Claude Code as the shared source of truth. Build an AI audience that listens to a live presentation, interrupts with grounded questions, throws realistic curveballs (time cuts, dead slides, hecklers), speaks in distinct voices, optionally animates one talking-head avatar, and ends with an evidence-based report card.

## 1. Product in one paragraph

**PitchPanel** is an interactive rehearsal room for students, founders, and professionals. The presenter selects a scenario (Startup Pitch, Class Presentation, Research Defense), uploads PDF slides, and presents through their microphone. Two or three AI audience members with distinct goals and personalities listen, interrupt with grounded questions, accept spoken answers, and follow up. On top of questions, the room throws **curveballs** — the unexpected events that actually rattle presenters: "you have 60 seconds left," the projector dying, a hostile heckler, a latecomer asking for a recap, a question outside your expertise. The session ends with a Q&A round and a report card that scores content, question handling, and **recovery under pressure**, all grounded in captured evidence. The signature demo: a skeptical VC asks for evidence behind a growth claim, pushes back once, then the slides go black mid-pitch and the presenter has to keep going.

**Why this is different:** Yoodli, Orai, and PowerPoint Speaker Coach give feedback after you finish, to an empty room. PitchPanel simulates the audience *and* the chaos, so the first time you face a tough question or a dead projector isn't when it matters.

## 2. Non-negotiable MVP

1. Select one of three scenarios; load 2–3 audience personas and that scenario's curveball pack.
2. Upload a PDF deck; extract text and track the active slide.
3. Start a live microphone session; show a transcript or captions where available.
4. Receive a **spoken, context-relevant interruption** from one persona; only one AI speaks at a time.
5. Let the presenter respond by voice and receive a meaningful follow-up.
6. Trigger **at least one curveball** (MVP set: `time_crunch`, `slides_down`, `heckler`) and track how the presenter recovers.
7. End with a Q&A round and a report card grounded in captured evidence, including a Recovery section.
8. Show persona cards and active-speaker states; upgrade the active speaker to a Boson avatar only if API access and latency permit.

**Demo acceptance test:** Presenter says "We can get 100,000 customers in six months." The VC asks for evidence; presenter answers; VC follows up about acquisition cost or distribution. Shortly after, the slide viewer goes black with "Projector's down — keep going." Presenter continues without slides. Session ends; the report references the actual VC exchange and how long the presenter took to resume after the slides died.

## 3. Scope and reality checks

- Do **not** build multiple simultaneous talking avatars. Keep 2–3 personas, one active speaker.
- Do **not** claim a text transcript measures intonation, vocal confidence, or monotone delivery. That requires audio understanding or measured acoustic features.
- Filler words and speaking pace can be computed from a timestamped transcript, with caveats about recognition accuracy.
- Higgs Avatar access may be limited; confirm with Boson staff. If unavailable, use static portraits and a speaking indicator.
- Do not assume all Boson APIs chain together directly. Verify actual endpoints, SDKs, auth, event schemas, and quotas from event documentation.
- Do not assume TTS supports inline sound effects or emotion tags until tested. Curveball audio (phone ring, door slam) can always fall back to local audio files.
- Do not impersonate a real person or clone a real person's voice without permission. Personas are fictional; label them as such.
- Curveballs must be **realistic and fair** — no insults, no personal attacks. The heckler challenges the idea, never the presenter as a person.
- Keep API secrets server-side.

## 4. Team division — exactly three owners

### Person A — Frontend and demo UX
**Owns:** `frontend/`

Build Next.js + TypeScript + Tailwind UI:
- `/` landing + scenario selection
- `/setup` persona cards, difficulty (Friendly / Normal / Brutal), interruption frequency, curveball toggles, PDF upload
- `/room` slide viewer, mic permissions, optional camera preview, 2–3 persona tiles, speaking indicator, live question captions, session timer, start/end controls
- **Curveball UI effects:**
  - `slides_down`: slide viewer fades to black with a "Projector disconnected" overlay; slide controls disabled until `curveball_resolved`
  - `time_crunch`: timer switches to a red 60-second countdown
  - `heckler` / `latecomer` / `bait`: persona tile flashes, caption tagged with curveball label
  - `distraction`: play the provided sound clip; brief visual cue (phone icon, door icon)
- `/report` scorecards, key moments timeline (questions + curveballs), Recovery section, unanswered questions, suggested improvements
- Client connection to backend WebSocket and REST endpoints
- Fallback UI for missing avatar/video or network issues

**Interface contract:** Receive typed `SessionEvent` messages and render state. Send `slide_changed`, `presentation_started`, `presentation_ended`, and optional `request_question` / `request_curveball` (debug only) events. Mic audio integration follows the agreed voice bridge rather than creating a second competing connection.

**Definition of done:** All pages navigable with mocked events (including every MVP curveball) by hour 5; real session connected by hour 10.

### Person B — Boson speech, audio understanding, avatar
**Owns:** `backend/services/boson_*`, voice bridge, `demo/sfx/`

- Confirm event-specific access to Higgs Realtime, audio understanding, TTS, and Higgs Avatar.
- Build the lowest-latency **microphone → Boson → spoken response** proof of concept first.
- Support speaker-turn handling, interrupt/cancel behavior, and audio playback.
- Persona-to-voice mapping if supported; otherwise a single voice with visibly distinct persona labels.
- **Curveball voice delivery:**
  - Heckler line with an annoyed/impatient style if emotion or style control is supported; otherwise neutral voice with on-screen tag.
  - Moderator voice for `time_crunch` and `slides_down` announcements (a neutral "event host" voice separate from personas).
  - Test whether TTS supports inline sound effects; if not, supply short royalty-free local clips in `demo/sfx/` (phone ring, door, cough).
- Emit transcript/timing events if supported; otherwise coordinate a separate transcription service with Person C.
- If audio-understanding features are available, produce grounded delivery observations (hesitation, emphasis, pacing) — especially right after curveballs — without inventing scores.
- Try **one** talking-head avatar using a consenting or synthetic portrait. If unavailable, emit `avatar_status: unavailable` and do not block the demo.

**Interface contract:** `start_voice_session(config)`, `send_context(context)`, `request_persona_turn(persona_id, text, style?)`, `play_moderator_line(text)`, `cancel_speech()`, `stop_voice_session()`. Expose `audio_status`, `transcript_segment`, `ai_speech_started`, `ai_speech_ended`, and `avatar_status` events.

**Definition of done:** End-to-end voice round trip by hour 3–4; persona voices + moderator voice (or fallback) by hour 8.

### Person C — Backend, audience brain, curveballs, slides, feedback
**Owns:** `backend/main.py`, `models.py`, `services/audience.py`, `scheduler.py`, `curveballs.py`, `slides.py`, `report.py`

- FastAPI server and WebSocket event bus.
- PDF upload and slide text extraction (PyMuPDF).
- Session state machine and in-memory/JSON persistence for MVP.
- LLM-powered orchestrator: persona choice, grounded questions, follow-up logic.
- **Scheduler** that decides between nothing, a persona question, or a curveball, enforcing one active speaker, cooldowns, caps, and no repeats.
- **Curveball engine** (`curveballs.py`): scenario packs, difficulty budgets, trigger conditions, generated lines, and recovery tracking.
- Final Q&A phase and report using transcript, timestamps, slides, question log, and curveball log.
- Score clarity, evidence, answer completeness, question handling, and recovery with explicit rubrics; report filler count and WPM only if data supports them.

**Interface contract:** REST and WebSocket schemas below. Mock Person B's voice module so logic is testable without audio.

**Definition of done:** Mock presentation produces a grounded question, one curveball with recovery metrics, and a report by hour 6; real integration by hour 10.

## 5. Suggested repository structure

```text
pitchpanel/
├── README.md
├── .env.example
├── DEMO_STATUS.md
├── frontend/
│   ├── app/{page.tsx,setup/page.tsx,room/page.tsx,report/page.tsx}
│   ├── components/
│   │   ├── AudienceCard.tsx
│   │   ├── SlideViewer.tsx
│   │   ├── MicControl.tsx
│   │   ├── QuestionOverlay.tsx
│   │   ├── CurveballOverlay.tsx
│   │   ├── SessionTimer.tsx
│   │   └── ReportCard.tsx
│   └── lib/{api,types,ws}.ts
├── backend/
│   ├── main.py
│   ├── models.py
│   ├── scenarios/
│   │   ├── startup_pitch.yaml
│   │   ├── class_presentation.yaml
│   │   └── research_defense.yaml
│   ├── services/
│   │   ├── slides.py
│   │   ├── audience.py
│   │   ├── scheduler.py
│   │   ├── curveballs.py
│   │   ├── report.py
│   │   ├── boson_realtime.py
│   │   ├── boson_audio_understanding.py
│   │   └── boson_avatar.py
│   └── tests/
│       ├── test_scheduler.py
│       ├── test_curveballs.py
│       └── test_e2e_mock.py
└── demo/
    ├── sample_pitch.pdf
    ├── sfx/{phone_ring.mp3,door.mp3,cough.mp3}
    └── demo_script.md
```

Use `main` as the integration branch with `feat/frontend`, `feat/boson`, `feat/backend` branches. Agree on event contracts before coding.

## 6. Curveball system

Curveballs are scripted *types* of unexpected events whose *content* is generated live from the presentation, so they feel real rather than canned.

### 6.1 Curveball catalog

| Kind | What happens | What it tests | Delivered by | Priority |
|---|---|---|---|---|
| `time_crunch` | Moderator: "Sorry, we're running behind — you've got 60 seconds." Timer turns red. | Condensing, prioritizing the key message | Moderator voice + UI timer | **P0** |
| `slides_down` | Slide viewer goes black: "Projector's disconnected — keep going." Restores after ~30 s or on presenter request. | Presenting without visual crutch | UI only (+ optional moderator line) | **P0** |
| `heckler` | A persona challenges the core idea bluntly: "Isn't this just a ChatGPT wrapper?" | Composure, reframing, staying on message | Persona voice with impatient style | **P0** |
| `latecomer` | "Sorry, I just walked in — can you give me the 20-second version?" | On-the-spot summarizing | Persona voice | P1 |
| `bait` | A plausible question deliberately outside the presenter's scope. | Admitting uncertainty vs. bluffing | Persona voice | P1 |
| `distraction` | Phone ring / door slam / cough mid-sentence. | Recovering train of thought | SFX clip (or TTS sound effect if supported) | P1 |
| `crosstalk` | Two personas start disagreeing with each other. | Taking back control of the room | Two persona turns, sequential | P2 |

### 6.2 Scenario packs (`backend/scenarios/*.yaml`)

```yaml
id: startup_pitch
name: Startup Pitch
personas: [vc, student, professor]
curveballs_allowed: [time_crunch, slides_down, heckler, latecomer, distraction]
default_difficulty: normal
duration_target_s: 180
```

| Scenario | Allowed curveballs |
|---|---|
| Startup Pitch | time_crunch, slides_down, heckler, latecomer, distraction |
| Class Presentation | time_crunch, slides_down, latecomer, distraction |
| Research Defense | time_crunch, slides_down, bait, heckler (methodology-focused) |

### 6.3 Difficulty budgets

| Difficulty | Persona questions | Curveballs | Heckler tone |
|---|---|---|---|
| Friendly | 1–2 | 0 | — |
| Normal | 2 | 1 | Firm but polite |
| Brutal | 2–3 | 2 | Blunt, still never personal |

The demo runs on **Normal**: 2 questions, 1 curveball.

### 6.4 Trigger rules

- No curveball in the first 45 seconds or during an AI turn, a presenter answer, or a slide transition.
- At least 30 seconds between any two audience events (question or curveball).
- `time_crunch`: fires once, after ≥ 50% of `duration_target_s` has elapsed.
- `slides_down`: fires on a slide change or natural pause after ≥ 60 s; never on slide 1.
- `heckler`: fires after the presenter states the core value proposition (orchestrator detects it) or at a pause after ≥ 60 s.
- `latecomer`: fires after ≥ 90 s so there is something to recap.
- `bait`: generated from slide/transcript topics but targeted just past what was covered.
- `distraction`: fires mid-speech (not at a pause), at most once.
- A curveball never repeats within a session.

### 6.5 Recovery tracking

Each curveball records evidence used by the report:

| Kind | Measured | How |
|---|---|---|
| `time_crunch` | Finished within 60 s? Words after cut; did the close include the key ask/conclusion? | Transcript timestamps + LLM rubric |
| `slides_down` | Seconds until presenter resumed speaking; did they keep structure? | Silence gap from timestamps + LLM rubric |
| `heckler` | Did the answer address the challenge directly, stay calm in wording, and return to the talk? | LLM rubric on answer transcript |
| `latecomer` | Recap length (target ≤ 30 s) and whether it covered problem/solution/ask | Timestamps + LLM rubric |
| `bait` | Admitted uncertainty vs. asserted unsupported specifics | LLM rubric |
| `distraction` | Pause length after the sound, filler burst after resuming | Timestamps + filler count window |

If timing data is missing, set the metric to `null` and say so in the report. Never fabricate recovery numbers.

## 7. Shared data contracts

```ts
type Persona = {
  id: string;            // "vc" | "student" | "professor"
  name: string;
  role: string;          // "Skeptical VC", "Confused Student", "Picky Professor"
  focus: string[];
  skepticism: number;    // 0..1
  voiceId?: string;
  avatarUrl?: string;
};

type Difficulty = "friendly" | "normal" | "brutal";

type CurveballKind =
  | "time_crunch" | "slides_down" | "heckler"
  | "latecomer" | "bait" | "distraction" | "crosstalk";

type SessionPhase =
  | "setup" | "presenting" | "interruption" | "answering"
  | "curveball" | "recovering" | "qna" | "report";

type SessionEvent = {
  type:
    | "session_started" | "slide_changed" | "transcript_segment"
    | "question_queued" | "ai_speech_started" | "ai_speech_ended"
    | "answer_received" | "curveball_triggered" | "curveball_resolved"
    | "timer_override" | "avatar_status" | "phase_changed"
    | "session_ended" | "error";
  sessionId: string;
  timestampMs: number;
  payload: Record<string, unknown>;
};
```

Example interruption event:

```json
{
  "type": "question_queued",
  "sessionId": "demo-001",
  "timestampMs": 90000,
  "payload": {
    "personaId": "vc",
    "questionId": "q-12",
    "question": "What evidence supports reaching 100,000 users?",
    "reason": "unsupported growth projection",
    "citedExcerpt": "We can get 100,000 customers in six months",
    "slideNumber": 3
  }
}
```

Example curveball events:

```json
{
  "type": "curveball_triggered",
  "sessionId": "demo-001",
  "timestampMs": 125000,
  "payload": {
    "curveballId": "cb-2",
    "kind": "slides_down",
    "speaker": "moderator",
    "line": "Sorry — the projector just disconnected. Can you keep going?",
    "uiEffect": "slides_black",
    "autoResolveAfterMs": 30000,
    "sfxUrl": null
  }
}
```

```json
{
  "type": "curveball_resolved",
  "sessionId": "demo-001",
  "timestampMs": 155000,
  "payload": {
    "curveballId": "cb-2",
    "kind": "slides_down",
    "resolution": "auto_restored",
    "recovery": { "resumeAfterMs": 3400, "notes": "Resumed by restating the problem" }
  }
}
```

```json
{
  "type": "timer_override",
  "sessionId": "demo-001",
  "timestampMs": 140000,
  "payload": { "curveballId": "cb-3", "remainingMs": 60000, "style": "urgent" }
}
```

### REST and WebSocket routes

| Route | Method | Purpose |
|---|---|---|
| `/api/scenarios` | GET | List scenarios, personas, allowed curveballs |
| `/api/slides` | POST | Upload PDF, return slide text and metadata |
| `/api/sessions` | POST | Create session (scenario, personas, difficulty, curveball toggles, deck) |
| `/api/sessions/{id}` | GET | Session state |
| `/api/sessions/{id}/curveball` | POST | **Debug/demo only:** force a curveball kind |
| `/api/sessions/{id}/finish` | POST | Finish and compute report |
| `/api/sessions/{id}/report` | GET | Report JSON |
| `/ws/sessions/{id}` | WS | UI event stream and state changes |
| `/health` | GET | Health and configured adapters |

Actual audio transport is decided by Person B after testing Boson's supported connection method. Don't route raw PCM through arbitrary JSON messages.

## 8. Session state machine

```text
SETUP
  ↓ start
PRESENTING ── claim / pause / time trigger ──→ INTERRUPTION ── AI finishes ──→ ANSWERING
   ↑   │                                                                        │
   │   │                                         follow-up (max 1) or resume ───┘
   │   └── curveball trigger ──→ CURVEBALL ── line delivered / effect applied ──→ RECOVERING
   │                                                                               │
   └────────────── presenter resumes / effect resolves ────────────────────────────┘
  ↓ user ends presentation (or time_crunch countdown hits 0)
QNA → REPORT
```

**Scheduler rules (questions + curveballs combined):**
- Exactly one audience event at a time; only one AI voice ever speaks.
- First audience event after at least 30 seconds of content (curveballs: 45 s).
- Cooldown ~30–45 seconds after any completed audience event.
- Normal-difficulty demo cap: 2 persona questions + 1 curveball in ~3 minutes.
- Max 1 follow-up per question.
- Questions take priority when a strong unsupported claim is detected; otherwise a due curveball may fire at the next eligible moment.
- No events during an AI turn, a presenter answer, or a slide transition (except `distraction`, which deliberately fires mid-speech).
- If live turn detection cannot support reliable mid-speech barge-in, fire at the next pause and call it an interruption of the presentation rather than overlapping speech.
- `time_crunch` reaching 0 moves the session to QNA automatically.

## 9. Audience reasoning and prompts

Use one **orchestrator** to decide what happens. Do not run independent audio agents that race to speak.

**Personas:**
1. **Skeptical VC:** market size, traction, acquisition cost, competition, moat. Also plays `heckler` in Startup Pitch.
2. **Confused Student:** plain-language definitions, examples, missing explanation. Also plays `latecomer`.
3. **Picky Professor:** assumptions, methodology, evidence, logical consistency. Also plays `bait` and methodology `heckler` in Research Defense.
4. **Moderator (non-persona voice):** delivers `time_crunch` and `slides_down` announcements. Neutral, brief.

**Orchestrator prompt:**

```text
You are the moderator of a simulated presentation audience.
Inputs: scenario, difficulty, active slide text, recent presenter transcript
(last ~30 s with timestamps), prior Q&A, curveball budget remaining,
eligible curveball kinds right now, seconds since last audience event.

Decide ONE action:
  - "none"
  - "question": choose the most relevant persona, write one short,
    specific, natural question (max ~20 words) that quotes or paraphrases
    something the presenter actually said.
  - "curveball": only from the eligible kinds provided; write the line
    for the assigned speaker, grounded in the current talk.

Rules:
- Prefer unsupported claims, confusing terms, and missing evidence for questions.
- Never invent facts about the presenter's slides or company.
- Avoid duplicates and excessive interruptions.
- Heckler lines challenge the idea, never the person; no insults.
- Bait questions must be plausible and adjacent to the topic, but beyond
  what the slides or transcript cover.

Return JSON:
{ "action": "none"|"question"|"curveball",
  "persona_id": string|null, "curveball_kind": string|null,
  "line": string|null, "reason": string,
  "cited_transcript_excerpt": string|null, "slide_number": number|null }
```

**Follow-up prompt:**

```text
Assess whether the presenter's answer addresses the actual question.
If it does, acknowledge briefly ("Fair enough, go on.") and return to the presentation.
If it does not, ask one concise follow-up targeting the missing detail.
Do not be rude or repeat the exact same wording.
Return JSON: { "verdict": "satisfied"|"follow_up", "line": string,
  "missing_detail": string|null }
```

**Recovery assessment prompt (runs after each curveball resolves):**

```text
Given the curveball kind, its line, the presenter's transcript for the
next 60 seconds with timestamps, and measured timing values:
Evaluate recovery using this rubric for the kind:
- time_crunch: delivered core message + clear close within the limit?
- slides_down: kept structure and resumed promptly without slides?
- heckler: addressed the challenge directly, stayed composed in wording,
  returned to the talk?
- latecomer: recap ≤ 30 s covering problem, solution, ask?
- bait: admitted uncertainty or scoped the answer, rather than inventing specifics?
- distraction: resumed the thought without restarting from scratch?
Quote the transcript as evidence. If timing data is missing, say so.
Return JSON: { "score": 0-100, "evidence": string, "observation": string,
  "suggestion": string }
```

## 10. Report card

```json
{
  "overallScore": 78,
  "dimensions": {
    "clarity": 82,
    "evidence": 69,
    "questionHandling": 74,
    "structure": 85,
    "recovery": 71
  },
  "metrics": {
    "fillerWords": 12,
    "wordsPerMinute": 143,
    "unansweredQuestions": 1,
    "curveballsFaced": 1
  },
  "strengths": ["Clearly explained the problem"],
  "improvements": [
    {
      "observation": "Growth claim lacked supporting evidence",
      "evidence": "We can get 100,000 customers in six months",
      "suggestion": "Add acquisition assumptions and early traction"
    }
  ],
  "curveballs": [
    {
      "kind": "slides_down",
      "atMs": 125000,
      "resumeAfterMs": 3400,
      "score": 71,
      "evidence": "Resumed with 'So, the problem again is...'",
      "suggestion": "Memorize a 3-point outline so you can present without slides"
    }
  ],
  "keyMoments": [
    { "atMs": 90000, "type": "question", "personaId": "vc", "summary": "Asked for evidence on growth claim" },
    { "atMs": 125000, "type": "curveball", "kind": "slides_down", "summary": "Projector died; resumed in 3.4 s" }
  ],
  "personaFeedback": [
    { "personaId": "vc", "score": 72, "comment": "Market argument needs proof" }
  ]
}
```

**These are illustrative values only.** Never hardcode demo scores as if measured. If timestamps or audio signals are missing, set affected metrics to `null` and explain the missing measurement. Scores are subjective coaching estimates from explicit rubrics, not objective psychological measurements. `recovery` is `null` if no curveballs occurred.

## 11. 24-hour plan (3 developers in parallel)

| Time | Person A — Frontend | Person B — Boson | Person C — Backend |
|---|---|---|---|
| 0–1h | Scaffold Next.js and mock room | Verify API credentials, minimal voice sample | Schemas, FastAPI, repo contracts, scenario YAMLs |
| 1–3h | Scenario picker, setup page, persona cards | Mic → model → speaker round trip | PDF parsing, session state machine |
| 3–5h | Room, slide viewer, question overlay, timer | Voice turn + cancellation handling | Orchestrator and first grounded question |
| 5–8h | Curveball overlays (slides_down, time_crunch, heckler tag) | Persona voices, moderator voice, SFX/style test | Scheduler with cooldowns, curveball engine (MVP 3 kinds), follow-ups |
| 8–11h | Integrate live events | Connect voice to backend events | Connect slides, question log, curveball log, voice |
| 11–15h | Report page with Recovery + key moments | One avatar attempt, fallback ready | Recovery assessment, evidence-based report |
| 15–18h | Error states, responsiveness | Latency/turn-taking fixes; P1 curveball audio | P1 curveballs (latecomer, bait, distraction); e2e tests |
| 18–21h | Demo UI freeze | Audio/visual freeze | Integration freeze, backup mode |
| 21–24h | Rehearse and present | Rehearse and present | Record fallback demo, submit |

**Hard gates:**
- **Hour 5:** live audio + one relevant spoken question. If real-time speech isn't working, switch to push-to-talk and keep the question/answer loop.
- **Hour 8:** if avatar access isn't confirmed, switch to static persona cards.
- **Hour 10:** at least one curveball (`slides_down` preferred) working end-to-end with a recovery metric. Curveballs never take priority over the hour-5 loop.

## 12. Acceptance criteria

- [ ] Presenter can pick a scenario, difficulty, and personas, and upload a PDF.
- [ ] Slide text is extracted and the active slide is tracked.
- [ ] Presenter speech produces transcript segments with timestamps (or the gap is documented).
- [ ] A persona asks a spoken question that references something the presenter actually said.
- [ ] Presenter can answer by voice; persona follows up at most once, then hands back.
- [ ] Only one AI voice speaks at a time; cooldowns and caps are respected.
- [ ] `slides_down`, `time_crunch`, and `heckler` each work end-to-end with correct UI effects.
- [ ] Each curveball records recovery evidence, or `null` with an explanation.
- [ ] `time_crunch` countdown hitting zero moves the session to Q&A.
- [ ] Report includes dimensions, Recovery, key moments, and evidence quotes from the real session.
- [ ] A failed question, TTS call, or curveball is skipped without breaking the session.
- [ ] Demo runs twice in a row without developer intervention.

## 13. Demo script (2–3 minutes)

1. **Hook (15s):** "Practicing slides isn't the same as practicing your audience — or the things that go wrong."
2. **Setup (15s):** Select Startup Pitch, Normal difficulty, VC + Student + Professor; upload sample PDF.
3. **Live claim (20s):** "We can acquire 100,000 users in six months."
4. **VC interruption (20s):** "What evidence supports that projection?"
5. **Presenter response (15s):** "We plan to grow through university communities."
6. **VC follow-up (15s):** "What early data supports that channel?" Presenter answers briefly.
7. **Curveball (30s):** Slides go black — moderator: "Sorry, projector's down — can you keep going?" Presenter continues from memory. Slides restore.
8. **Finish/Q&A (15s):** Professor asks about one assumption.
9. **Report (25s):** Show the weak growth claim with evidence quote, the VC exchange, the Recovery card ("resumed in X s"), and pace/fillers if measured.
10. **Close (10s):** "The first time you face a tough question — or a dead projector — shouldn't be when it matters most."

Use the debug `/curveball` endpoint during rehearsal only. In the live demo, let the scheduler fire it; keep the debug trigger as a fallback if timing goes wrong. Prepare a **backup screen recording** of a real successful run. Never present pre-scripted AI responses as live.

## 14. Failure modes and fallbacks

| Problem | Fallback |
|---|---|
| Higgs Avatar unavailable | Static character cards with active-speaker animation |
| Multiple voices unavailable | One Boson voice; distinct persona identities in UI |
| Emotion/style control unavailable | Neutral heckler voice + "Heckler" tag on screen |
| TTS sound effects unavailable | Local SFX clips in `demo/sfx/` |
| Full-duplex audio unstable | Push-to-talk and pause-based questions/curveballs |
| Audio understanding unavailable | Transcript-based content + timing-based recovery only |
| Real-time transcript unavailable | Separate STT or recognized-turn text |
| Curveball fires at a bad moment in demo | Debug trigger at a planned moment; disable auto-curveballs |
| Recovery timing unreliable | Report rubric-based recovery only; set timing to `null` |
| PDF parsing fails | Preloaded sample deck |
| LLM response slow | Generate during pauses; show "thinking" state; skip if over budget |
| Internet unreliable | Pre-recorded demo video |

## 15. Environment and security

`.env.example`:

```bash
BOSON_API_KEY=
BOSON_REALTIME_MODEL=
BOSON_TTS_MODEL=
BOSON_AVATAR_ENABLED=false
LLM_API_KEY=
CURVEBALLS_ENABLED=true
DEBUG_CURVEBALL_ENDPOINT=true
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

Keep `.env` out of Git. Request microphone/camera permission clearly. Avoid storing raw audio/video by default; if recording is enabled, get informed consent and provide deletion controls. Disable the debug curveball endpoint outside local demos.

## 16. Claude Code instructions for each developer

### Prompt for Person A

```text
Read AI_PRESENTATION_PANEL_CLAUDE_PLAN.md in full. You own frontend/ only.
Build the Next.js/TypeScript/Tailwind UI for PitchPanel: scenario selection,
setup (personas, difficulty, curveball toggles, PDF upload), presentation room
(slide viewer, persona tiles, active speaker, question overlay, session timer),
curveball overlays (slides_down blackout, time_crunch red countdown, heckler/
latecomer/bait tags, distraction SFX), and the report page with Recovery and
key moments. Implement a typed event client following the shared contracts.
Use realistic mock events, including every MVP curveball, until the backend
is ready. Do not implement Boson API calls or invent backend contracts.
Prioritize the live demo path.
```

### Prompt for Person B

```text
Read AI_PRESENTATION_PANEL_CLAUDE_PLAN.md in full. You own the Boson voice
bridge and backend/services/boson_* modules plus demo/sfx/. First verify the
actual Boson Realtime/TTS/audio-understanding/avatar APIs using current
documentation and event resources. Implement microphone-to-spoken-response
and expose the agreed events. Add cancel/interrupt handling. Map personas to
distinct voices if supported, add a neutral moderator voice, and test whether
style/emotion control and inline sound effects work; otherwise use local SFX
clips. Attempt one avatar only after voice works. Never block the MVP on
avatar access. Document how to run a test.
```

### Prompt for Person C

```text
Read AI_PRESENTATION_PANEL_CLAUDE_PLAN.md in full. You own FastAPI, models,
slides, audience orchestrator, scheduler, curveball engine, and report.
Implement REST/WebSocket contracts and in-memory session state. Load scenario
YAMLs. Extract PDF slide text, generate grounded persona questions, manage
turn-taking, and implement curveballs (MVP: time_crunch, slides_down, heckler)
with trigger rules, difficulty budgets, cooldowns, and recovery tracking.
Generate evidence-based report cards including Recovery. Mock voice events
until Person B's integration is ready. Never let more than one audience voice
speak at once. Write deterministic tests for:
  claim → question → answer → follow-up
  slides_down → presenter resumes → recovery metric recorded
  time_crunch → countdown → automatic Q&A.
```

## 17. First 15-minute team sync

1. Choose repo and branches; Person C owns schemas and scenario YAMLs.
2. Decide the voice bridge (browser↔Boson via ephemeral auth, or browser↔backend↔Boson) only after verifying API requirements.
3. Agree on JSON event shapes, including `curveball_triggered`, `curveball_resolved`, and `timer_override`; agree who owns mic capture and playback.
4. Ask Boson staff about Higgs Avatar access, voice/style controls, sound effects, and audio-understanding APIs.
5. Fix the demo: Startup Pitch, Normal difficulty, VC + Student + Professor, curveball = `slides_down`.
6. Set checkpoints: hour 5 (live question loop), hour 8 (avatar decision), hour 10 (one curveball end-to-end).

## 18. Definition of hackathon success

The system accepts a deck, listens to a real presenter, asks a relevant question in a Boson voice, handles a response and follow-up, throws at least one realistic curveball, measures how the presenter recovered, and produces a report that references actual moments. Avatars, extra curveballs, and advanced vocal analysis make it stronger, but are **not** prerequisites for a complete demo.

