# PresAI · CLAUDE.md

Read once per session. This file is the house rules and the shared source of truth for a three-person, 24-hour hackathon build. It is context, not enforcement: the team enforces at merge time with `make check` and the hour gates in §4. Nothing you can learn from the tree is repeated here once the tree exists; until then, this file carries the spec.

**Product in one line.** **PresAI** is an AI audience that listens to a live presentation, interrupts with grounded questions, throws realistic curveballs, speaks in distinct voices, and ends with an evidence-based report card. Voice, speech recognition and avatar come from the Higgs API (Boson AI) on one key with **$100 of credit** (§13, "Money"); the audience's brain is Claude on an Anthropic key (§9). The stack is **all Python**: FastAPI serves both the API and a framework-free browser frontend (§4).

---

## 1. Where truth lives

- `CLAUDE.md` — this file. House rules, scope, priorities, contracts. Changed only by agreement of all three owners, in its own commit titled `rules: <what>`.
- `DECISIONS.md` — settled. Dated entries, newest wins. Do not re-decide. A decision that looks wrong goes on your checkpoint report's `Proposed decision changes` line, unimplemented.
- `PRIORITIES.md` — the ordered build list (§3 is its first edition). Each line: `P0|P1|P2 · <id> · <owner> · <done? yes/no> · <blocked by>`. You change `done` and `blocked by` and nothing else.
- `spec/contracts.py` — the only source of event, persona, config and report types (pydantic). Person C owns it. `make schema` writes `spec/contracts.schema.json` from it; the frontend's mock fixtures are validated against that schema in `make check`. Nobody redefines a type locally, in Python or in JavaScript.
- `spec/curveballs.md` — the curveball catalog (§6 is its first edition): kind, trigger rule, UI effect, speaker, recovery metric, priority.
- `backend/scenarios/*.yaml` — scenario presets and persona roster. Content, not code: anyone may add a persona or preset; the schema is in `contracts.py`.
- `PROGRESS.md` — one checkpoint report per Claude Code session, appended, never edited (template in §14).
- `demo/DEMO_STATUS.md` — the demo path's current state: which steps are live, which are mocked, which are fallback. Updated at every hour gate. The judges' demo runs only what this file marks live.
- `.env.example` — every variable the system reads, with an empty value. `.env` is never committed.

## 2. What we are building, and why it is different

Rehearsal tools (speaker coaches, filler-word counters) give feedback after you finish, to an empty room. **PresAI simulates the audience and the chaos.** The presenter chooses who is in the room and how hard they push, uploads slides, and presents through the microphone. Two or three AI audience members with distinct goals listen, interrupt with questions that quote what the presenter actually said, accept spoken answers, and follow up. On top of questions the room throws **curveballs**: "you have 60 seconds," the projector dying, a heckler, the CEO walking in late and wanting the one-liner. The session ends with Q&A and a report card that scores content, question handling and **recovery under pressure**, every line grounded in a transcript quote or a measured timestamp.

**The thesis is proven at the demo if** a presenter makes a claim, a persona challenges it in its own voice, the presenter answers, the persona follows up once, a curveball lands, the presenter recovers, and the report quotes that exact exchange and states the recovery time in seconds. Everything in §3 exists to make that sentence true. Anything that doesn't is P2 or cut.

**Two product rules that are not negotiable.**
- **Friendly by default, flexible on demand.** A first-time user reaches a live room in three clicks (pick a preset, drop a PDF, press Start). Every knob in §5 lives behind an "Advanced" disclosure with a sensible default. Never ship a setup screen that needs reading.
- **Fair, never cruel.** Curveballs and hecklers challenge the idea, the evidence or the delivery, never the person. No insults, no appearance, no identity. Personas are fictional and labelled as such. A presenter can hit **Pause** or **Skip** at any time and nothing is scored against them for it.

## 3. Priority list (first edition of `PRIORITIES.md`)

**P0 — the demo does not exist without it.** All P0 lands before any P1 starts, per owner.

| # | What | Owner | Done when |
|---|---|---|---|
| P0-1 | Shared `contracts.py` + generated schema, scenario YAML schema, `.env.example`, `Makefile`, repo scaffold | C | Both other owners import from it and the mock event stream runs |
| P0-2 | Mic → model → spoken reply round trip, lowest latency path available | B | A spoken sentence gets a spoken answer in under ~2 s on the demo laptop |
| P0-3 | Setup flow: preset picker, PDF drop, Start (three clicks) | A | Reaches `/room` with a session created from mocked backend |
| P0-3b | **Audience builder**: pick 2–3 personas from the roster, free-text custom persona, skepticism slider, curveball picker (Off / Surprise me / Choose) — behind one "Customise" button, presets still work untouched | A (+ C for the custom-persona expansion in the orchestrator) | A custom persona typed on `/setup` appears as a tile in `/room` and asks a question in character (mocked until hour 10) |
| P0-4 | PDF upload, slide text extraction, active-slide tracking | C | `/api/slides` returns per-slide text for the sample deck |
| P0-5 | Orchestrator: one grounded persona question that quotes the transcript | C | Deterministic test: claim → question with `citedExcerpt` |
| P0-6 | Answer → follow-up (max 1) → hand back | C | Deterministic test passes; voice path mocked |
| P0-7 | Room UI: slide viewer, persona tiles, active-speaker state, captions, timer, Pause/Skip/End | A | All states render from mocked events |
| P0-8 | Scheduler: one speaker at a time, cooldowns, caps, no repeats | C | `test_scheduler.py` green |
| P0-9 | Curveball engine with the three MVP kinds (`slides_down`, `time_crunch`, `heckler`) and recovery tracking | C | `test_curveballs.py` green; `slides_down` → resume gap measured |
| P0-10 | Curveball UI effects for the three MVP kinds | A | Blackout overlay, red countdown, heckler tag all render from mocked events |
| P0-11 | Persona voices (or one voice + visible labels) and a neutral moderator voice | B | Two distinguishable voices, or the fallback documented in `DEMO_STATUS.md` |
| P0-12 | Report page: dimensions, Recovery card, key moments, evidence quotes | A + C | Report renders from a real session's JSON |
| P0-13 | End-to-end live run, twice in a row, no developer touching it | all | Recorded; `DEMO_STATUS.md` says "live" for every demo step |
| P0-14 | Backup screen recording of a real run | all | File exists in `demo/` |

**P1 — makes the demo noticeably better; only after your P0 is green.**

| # | What | Owner |
|---|---|---|
| P1-1 | Polish of the demo path: transitions, persona tile animations, empty/loading/error states, reconnect, keyboard shortcuts (Space = push-to-talk, P = pause). **Judging weights product and UX, so this is the first P1.** | A |
| P1-2 | Curveballs `latecomer`, `bait`, `distraction`, `vip_arrives` | C (+ B for SFX/voice) |
| P1-3 | Heckler voice with `<\|emotion:anger\|>` / impatient prosody; distinct moderator preset voice | B |
| P1-4 | Filler words and WPM from timestamped transcript, with the accuracy caveat shown | C |
| P1-5 | Report polish: persona feedback in each persona's voice (TTS playback on the report page), share-as-image | A + B |
| P1-6 | Session history: list past reports locally (JSON files) | C + A |

**P2 — stretch; never blocks anything.**

| # | What | Owner |
|---|---|---|
| P2-1 | One talking-head avatar for the active speaker (synthetic portrait). Judging is on product and demo quality, not API coverage, so this stays P2: only if every P1 above is done and more than $40 of credit remains. | B |
| P2-2 | Curveballs `crosstalk`, `fact_check`, `elevator`, `plain_language`, `dead_room` | C |
| P2-3 | Audio-understanding delivery observations (hesitation, emphasis) if the API exists and is grounded | B |
| P2-4 | Multi-language presenting | B + C |
| P2-5 | Shareable report link | A + C |

**Cut for the hackathon (return trigger in brackets).** Multiple simultaneous avatars [never]. Camera-based body-language scoring [needs a measured model; not a transcript]. Accounts and cloud persistence [after the hackathon]. Real-person voice cloning [never without written consent]. Mobile layout [after the demo].

## 4. The gate, and the hour gates

**Stack (settled).** All Python, one process: FastAPI serves the REST and WebSocket API *and* the frontend as static files from `frontend/` (plain HTML, CSS and ES-module JavaScript, Tailwind from the CDN, no bundler, no Node toolchain). The browser parts that cannot be Python — microphone capture, WebSocket audio playback, overlays — are small, dependency-free JS modules; keep them under ~200 lines each. PyMuPDF for slides, `anthropic` SDK for the brain, `websockets`/`httpx` for Higgs. Python 3.12, `uv` or `pip` with pinned `requirements.txt`.

**`make check`** = `ruff check` + `pyright` (or `mypy`) on `backend/` + `pytest backend/tests` + mock fixtures under `frontend/mocks/` validated against `spec/contracts.schema.json` + mocked end-to-end (`test_e2e_mock.py`). Exit 0 or 1. Green at the commit you merge to `main`, or it does not merge. Branches: `main` is integration; `feat/frontend`, `feat/voice`, `feat/backend` per owner; short-lived, merged at least every three hours.

**Hour gates** (clock starts at kickoff; write the outcome in `DEMO_STATUS.md`):

| Hour | Gate | If missed |
|---|---|---|
| 1 | Contracts merged; all three can run `make check` | Nobody writes feature code until it is |
| 3–4 | Voice round trip works (P0-2) | Switch to push-to-talk + separate STT; keep going |
| 5 | Live audio + one relevant spoken question | Push-to-talk and pause-based questions; the question/answer loop is the product, not the audio transport |
| 8 | Avatar access confirmed or not | Static persona cards with speaking animation; avatar becomes P2 |
| 10 | One curveball end-to-end with a recovery metric (`slides_down` preferred) | Debug trigger instead of scheduler for the demo; disable auto-curveballs |
| 15 | P1 freeze: nothing new starts | Finish or revert; don't half-ship |
| 18 | UI, audio and integration freeze | Only fixes to the demo path |
| 21 | Two clean runs recorded; backup video exists | Demo from the backup video; say so honestly |

Curveballs never take priority over the hour-5 loop. Avatar never blocks anything.

## 5. Flexibility: audience, difficulty, curveballs

Every option below has a default so that a preset alone produces a good session. Options live in `SessionConfig` (§7) and are set on `/setup`.

### 5.1 Presets (one click)

| Preset | Personas | Curveballs allowed | Target length |
|---|---|---|---|
| Startup Pitch | Skeptical VC, Confused Student, Picky Professor | time_crunch, slides_down, heckler, latecomer, distraction, vip_arrives | 3 min |
| Class Presentation | Picky Professor, Confused Student, Bored Classmate | time_crunch, slides_down, latecomer, distraction, plain_language | 5 min |
| Research Defense | Picky Professor, Methods Skeptic, Friendly Mentor | time_crunch, slides_down, bait, heckler (methodology), fact_check | 5 min |
| Job Interview Talk | Hiring Manager, Senior Engineer, Recruiter | time_crunch, bait, vip_arrives, elevator | 3 min |
| Custom | presenter picks 2–3 from the roster or types their own | presenter picks or "Surprise me" | presenter sets |

### 5.2 Persona roster (`backend/scenarios/personas.yaml`)

Each persona has `id`, `name`, `role`, `focus[]`, `skepticism` (0–1 default), `styleHint`, `voiceId?`, `plays[]` (which curveball kinds it may voice). Starter roster: Skeptical VC, Confused Student, Picky Professor, Methods Skeptic, Friendly Mentor, Bored Classmate, Hiring Manager, Senior Engineer, Recruiter, Potential Customer, Journalist, Executive Sponsor. A **custom persona** is a free-text description ("my thesis committee chair who hates jargon") that the orchestrator turns into the same fields at session start; it is labelled "Custom · fictional" in the UI.

### 5.3 Knobs (Advanced drawer, all with defaults)

- **Difficulty:** Friendly / Normal (default) / Brutal. Sets question and curveball budgets (§6.3).
- **Skepticism slider** per persona (overrides the roster default).
- **Interruption frequency:** Rare / Normal / Often. Scales the cooldown.
- **Curveballs:** Off / Surprise me (default; scheduler picks from the preset's allowed set) / Choose (checkboxes).
- **Session length target** (drives `time_crunch` timing).
- **Q&A round at the end:** on by default; length 1–3 questions.
- **Input mode:** Live mic (default) / Push-to-talk. Push-to-talk is always available as a fallback, never hidden.
- **Captions:** always on. Not a knob.

### 5.4 In-room controls (always visible)

Pause (freezes scheduler, timer and voice), Skip (dismisses the current question or curveball, logged as `skipped`, not penalised), Restore slides (resolves `slides_down` early, logged), End → Q&A, and a mic-level meter so the presenter knows they are being heard.

## 6. Curveball system (first edition of `spec/curveballs.md`)

Curveballs are scripted *kinds* whose *content* is generated live from the talk, so they feel real rather than canned. Each records evidence the report uses. If a timing value cannot be measured, it is `null` and the report says so. Never fabricate a recovery number.

### 6.1 Catalog

| Kind | What happens | Tests | Delivered by | Recovery metric | Priority |
|---|---|---|---|---|---|
| `time_crunch` | Moderator: "We're running behind — you've got 60 seconds." Timer turns red; at 0 → Q&A. | Prioritising the key message | Moderator voice + timer | Finished within 60 s? Close included the ask/conclusion? | **P0** |
| `slides_down` | Slide viewer goes black: "Projector's disconnected — keep going." Restores after ~30 s or on Restore. | Presenting without the crutch | UI (+ optional moderator line) | Seconds until speech resumed; kept structure? | **P0** |
| `heckler` | A persona challenges the core idea bluntly: "Isn't this just a wrapper around an existing API?" | Composure, reframing | Persona voice, impatient style if available | Addressed directly, stayed composed in wording, returned to the talk? | **P0** |
| `latecomer` | "Sorry, just walked in — give me the 20-second version?" | Summarising on the spot | Persona voice | Recap ≤ 30 s covering problem / solution / ask? | P1 |
| `bait` | Plausible question just outside what was covered. | Admitting uncertainty vs bluffing | Persona voice | Scoped or admitted vs invented specifics? | P1 |
| `distraction` | Phone ring / door / cough mid-sentence. | Recovering train of thought | Local clip for ring/door (`demo/sfx/`); cough via TTS `<\|sfx:cough\|>` in a persona voice | Pause length; filler burst after resuming | P1 |
| `vip_arrives` | Moderator: "The decision-maker just joined for two minutes. What do they need to hear?" | Audience-shifting, the one-liner | Moderator + new persona tile appears | Did the next 30 s state the ask and the why-now? | P1 |
| `crosstalk` | Two personas start disagreeing with each other. | Taking back the room | Two persona turns, sequential, never overlapping | Did the presenter re-take control within 20 s? | P2 |
| `fact_check` | A persona cites a number that contradicts the slide: "Your slide says 40%, I've seen 15%." | Defending evidence calmly | Persona voice | Cited a source or acknowledged uncertainty vs dismissed? | P2 |
| `elevator` | "Pretend we're in an elevator. Thirty seconds, no slides." Slides dim, 30 s timer. | Compression | Moderator + UI | Covered problem / solution / ask in 30 s? | P2 |
| `plain_language` | "Explain that to someone with no background." | Jargon control | Persona voice (Student / Customer) | Jargon count in the next 30 s vs before | P2 |
| `dead_room` | Persona tiles go blank-faced; no reactions for 45 s. | Confidence without feedback | UI only | Pace and filler change during the window | P2 |

### 6.2 Trigger rules

- No curveball in the first 45 s, during an AI turn, a presenter answer, or a slide transition. `distraction` is the one exception: it fires mid-speech by design.
- At least 30 s between any two audience events (question or curveball); `Interruption frequency` scales this.
- `time_crunch` fires once, after ≥ 50 % of the session length target. `slides_down` fires on a slide change or pause after ≥ 60 s, never on slide 1. `heckler` fires after the orchestrator detects the core value proposition, or at a pause after ≥ 60 s. `latecomer` and `vip_arrives` fire after ≥ 90 s so there is something to recap. `bait` and `fact_check` are generated from slide and transcript topics.
- A kind never repeats within a session. Questions take priority when a strong unsupported claim is detected; otherwise a due curveball fires at the next eligible moment.
- Pause freezes all triggers. Skip resolves the current event as `skipped` and starts the cooldown.

### 6.3 Difficulty budgets

| Difficulty | Persona questions | Curveballs | Heckler tone |
|---|---|---|---|
| Friendly | 1–2 | 0 | — |
| Normal | 2 | 1 | Firm but polite |
| Brutal | 2–3 | 2 | Blunt, still never personal |

The judges' demo runs on **Normal** with `slides_down`.

## 7. Shared contracts (first edition of `spec/contracts.py`)

```python
from typing import Literal
from pydantic import BaseModel, Field

CurveballKind = Literal[
    "time_crunch", "slides_down", "heckler",
    "latecomer", "bait", "distraction", "vip_arrives",
    "crosstalk", "fact_check", "elevator", "plain_language", "dead_room",
]
Difficulty = Literal["friendly", "normal", "brutal"]
InterruptionFrequency = Literal["rare", "normal", "often"]
InputMode = Literal["live", "push_to_talk"]
SessionPhase = Literal[
    "setup", "presenting", "interruption", "answering",
    "curveball", "recovering", "paused", "qna", "report",
]
EventType = Literal[
    "session_started", "slide_changed", "transcript_segment",
    "question_queued", "ai_speech_started", "ai_speech_ended",
    "answer_received", "curveball_triggered", "curveball_resolved",
    "timer_override", "paused", "resumed", "skipped",
    "avatar_status", "audio_status", "phase_changed",
    "session_ended", "error",
]

class Persona(BaseModel):
    id: str
    name: str
    role: str
    focus: list[str]
    skepticism: float = Field(ge=0, le=1)
    style_hint: str | None = None
    voice_id: str | None = None
    avatar_url: str | None = None
    plays: list[CurveballKind] = []
    custom: bool = False            # True → labelled "Custom · fictional" in the UI

class CurveballMode(BaseModel):
    mode: Literal["off", "surprise", "choose"] = "surprise"
    kinds: list[CurveballKind] = []  # used only when mode == "choose"

class SessionConfig(BaseModel):
    preset_id: str                   # "startup_pitch" | ... | "custom"
    personas: list[Persona] = Field(min_length=2, max_length=3)
    difficulty: Difficulty = "normal"
    interruption_frequency: InterruptionFrequency = "normal"
    curveballs: CurveballMode = CurveballMode()
    duration_target_s: int = 180
    qna_questions: int = Field(default=2, ge=0, le=3)
    input_mode: InputMode = "live"
    deck_id: str | None = None

class SessionEvent(BaseModel):
    type: EventType
    session_id: str
    timestamp_ms: int
    payload: dict
```

Wire format is JSON with these exact snake_case names; the JavaScript side uses them as-is (no camelCase translation layer). `make schema` regenerates `spec/contracts.schema.json`; a changed contract is one commit that touches `contracts.py`, the schema, and every mock fixture it breaks.

Canonical payloads (the frontend's mocks use exactly these shapes):

```json
{ "type": "question_queued", "sessionId": "demo-001", "timestampMs": 90000,
  "payload": { "personaId": "vc", "questionId": "q-12",
    "question": "What evidence supports reaching 100,000 users?",
    "reason": "unsupported growth projection",
    "citedExcerpt": "We can get 100,000 customers in six months", "slideNumber": 3 } }
```

```json
{ "type": "curveball_triggered", "sessionId": "demo-001", "timestampMs": 125000,
  "payload": { "curveballId": "cb-2", "kind": "slides_down", "speaker": "moderator",
    "line": "Sorry — the projector just disconnected. Can you keep going?",
    "uiEffect": "slides_black", "autoResolveAfterMs": 30000, "sfxUrl": null } }
```

```json
{ "type": "curveball_resolved", "sessionId": "demo-001", "timestampMs": 155000,
  "payload": { "curveballId": "cb-2", "kind": "slides_down",
    "resolution": "auto_restored" ,
    "recovery": { "resumeAfterMs": 3400, "notes": "Resumed by restating the problem" } } }
```

`resolution` is one of `auto_restored | presenter_restored | answered | skipped | timed_out`. A `skipped` resolution has `recovery: null`.

### REST and WebSocket routes

| Route | Method | Purpose |
|---|---|---|
| `/api/presets` | GET | Presets, persona roster, allowed curveballs per preset |
| `/api/slides` | POST | Upload PDF; returns `deckId`, per-slide text, page count |
| `/api/sessions` | POST | Create session from `SessionConfig` |
| `/api/sessions/{id}` | GET | Session state and config |
| `/api/sessions/{id}/control` | POST | `pause | resume | skip | restore_slides | end` |
| `/api/sessions/{id}/curveball` | POST | **Debug only** (`DEBUG_CURVEBALL_ENDPOINT=true`): force a kind |
| `/api/sessions/{id}/report` | GET | Report JSON |
| `/ws/sessions/{id}` | WS | `SessionEvent` stream; client sends `slide_changed`, `presentation_started`, `presentation_ended` |
| `/health` | GET | Health and which adapters are configured (`voice`, `stt`, `avatar`, `llm`) |

Audio transport is Person B's decision after testing the vendor's supported connection. Raw PCM never travels inside the JSON event stream.

## 8. Session state machine and scheduler

```text
SETUP ─start→ PRESENTING ─claim / pause / time→ INTERRUPTION ─AI done→ ANSWERING
   ↑              │                                                  │
   │              │                       follow-up (max 1) or resume ┘
   │              └─curveball trigger→ CURVEBALL ─delivered→ RECOVERING
   │                                                           │
   └──────────── presenter resumes / effect resolves ──────────┘
Any state ─Pause→ PAUSED ─Resume→ previous state
PRESENTING ─End, or time_crunch hits 0→ QNA → REPORT
```

**Scheduler rules.** Exactly one audience event at a time; only one AI voice ever speaks. First event after ≥ 30 s of content (curveballs ≥ 45 s). Cooldown 30–45 s after any completed event, scaled by interruption frequency. Max one follow-up per question. If live barge-in is unreliable, fire at the next pause and call it an interruption, not overlapping speech. A failed LLM call, TTS call or curveball is skipped and logged as `error`; the session never breaks.

## 9. Audience reasoning: one orchestrator, three prompts

One orchestrator decides what happens. Never run independent audio agents that race to speak.

**The brain is Claude**, through the official `anthropic` Python SDK (never raw HTTP, never an OpenAI-compatible shim). Model `claude-opus-5-5` for all three prompts. Thinking stays adaptive (it cannot be disabled on this model); latency is controlled with `output_config.effort`: `"low"` for the orchestrator and follow-up calls (they run inside a ~4 s window), `"high"` for the recovery assessment and the report (they run after the fact). Every prompt returns JSON through structured outputs (`output_config.format` with the pydantic schema from `contracts.py`, via `client.messages.parse`), not through "return JSON" instructions or prefill — prefill is rejected on this model. Pass `fallbacks: "default"` with the `server-side-fallback-2026-07-01` beta so a safety refusal is routed instead of crashing a live session; check `stop_reason` before reading content. The system prompt is byte-identical across calls so the prefix caches; everything that varies (transcript window, slide, budgets) goes in the user turn. The LLM key lives in `.env` as `ANTHROPIC_API_KEY`; the orchestrator's cost is a few cents per session and is not the budget to worry about — Higgs minutes are.

**Orchestrator prompt**

```text
You are the moderator of a simulated presentation audience.
Inputs: preset, difficulty, personas (with focus and skepticism), active slide text,
recent presenter transcript (last ~30 s with timestamps), prior Q&A, curveball
budget remaining, eligible curveball kinds right now, seconds since last event.

Decide ONE action:
  - "none"
  - "question": choose the most relevant persona; write one short, specific,
    natural question (≤ 20 words) that quotes or paraphrases something the
    presenter actually said.
  - "curveball": only from the eligible kinds; write the line for the assigned
    speaker, grounded in the current talk.

Rules: prefer unsupported claims, confusing terms and missing evidence. Never
invent facts about the slides or the presenter's company. No duplicates. Heckler
and fact_check lines challenge the idea, never the person. Bait is plausible,
adjacent, and beyond what was covered.

Return JSON: { "action", "persona_id", "curveball_kind", "line", "reason",
  "cited_transcript_excerpt", "slide_number" }
```

**Follow-up prompt**

```text
Does the presenter's answer address the actual question? If yes, acknowledge in
≤ 6 words ("Fair enough, go on.") and hand back. If no, ask one concise follow-up
targeting the missing detail. Never rude; never the same wording twice.
Return JSON: { "verdict": "satisfied"|"follow_up", "line", "missing_detail" }
```

**Recovery prompt** (after each curveball resolves; rubric per kind from §6.1)

```text
Given the curveball kind, its line, the presenter's next 60 s of transcript with
timestamps, and the measured timing values (or null): score recovery 0–100 on the
kind's rubric. Quote the transcript as evidence. If timing is null, say so.
Return JSON: { "score", "evidence", "observation", "suggestion" }
```

## 10. Report card

Dimensions `clarity`, `evidence`, `structure`, `questionHandling`, `recovery` (0–100; `recovery` is `null` if no curveball fired). Metrics `fillerWords`, `wordsPerMinute` (both `null` unless a timestamped transcript exists, with an accuracy caveat), `unansweredQuestions`, `curveballsFaced`, `skipped`. Then `strengths[]`, `improvements[]` (each with `observation`, `evidence` quote, `suggestion`), `curveballs[]` (kind, `atMs`, metric, score, evidence, suggestion), `keyMoments[]` (timeline of questions and curveballs), `personaFeedback[]` (one line per persona in its own voice).

Scores are coaching estimates from explicit rubrics, not measurements of the person. Never hardcode demo values as if measured. Every `evidence` field is a verbatim transcript quote or a measured number; if neither exists, the item is omitted.

## 11. Team division: exactly three owners

### Person A — Frontend and demo UX
**Owns:** `frontend/` (static HTML/CSS/ES-module JS served by FastAPI; Tailwind via CDN; no build step) and `frontend/mocks/`.
- `/` preset picker (three clicks to a room), `/setup` with the audience builder (P0-3b) and the Advanced drawer (§5.3), `/room` (§5.4 controls, slide viewer rendered from the backend's per-slide PNGs, 2–3 persona tiles, speaking indicator, captions, timer, mic meter), `/report`.
- Curveball effects: `slides_down` blackout overlay with controls disabled until resolved; `time_crunch` red countdown; `heckler`/`latecomer`/`bait`/`fact_check` tile flash + tagged caption; `distraction` SFX + icon; `vip_arrives` new tile slides in; `elevator` dimmed slides + 30 s ring; `dead_room` blank-faced tiles.
- One small WS/REST client module (`frontend/js/api.js`) using the snake_case names from `spec/contracts.schema.json`. A realistic mock event stream (`frontend/mocks/*.json`, replayed with timing) including every P0 curveball and a custom persona, until the backend is live.
- **Never** implements vendor audio calls or invents a backend shape. Mic capture follows Person B's bridge.
- **Done:** all pages navigable on mocks by hour 5; real session connected by hour 10.

### Person B — Voice, audio understanding, avatar
**Owns:** `backend/services/voice_*`, the mic↔model bridge, `demo/sfx/`.
- Hour 1: run the five Higgs tests in §13 "Vendor" and write the results in `DECISIONS.md` under "Vendor". The architecture (§13, "Voice architecture") is decided by those results, not by preference.
- Lowest-latency mic → model → spoken reply first (P0-2). Then turn handling, cancel/interrupt, playback.
- Persona-to-voice mapping if supported; else one voice with visibly distinct labels. A neutral moderator voice distinct from personas. Test style control (impatient heckler) and inline SFX; if absent, local clips.
- Transcript segments with timestamps if the vendor emits them; else coordinate a separate STT with Person C. Audio-understanding observations only if grounded in a real signal.
- One avatar attempt only after voice works; emits `avatar_status: unavailable` otherwise.
- **Interface:** `start_voice_session(config)`, `send_context(ctx)`, `request_persona_turn(persona_id, text, style?)`, `play_moderator_line(text)`, `play_sfx(id)`, `cancel_speech()`, `stop_voice_session()`. Emits `audio_status`, `transcript_segment`, `ai_speech_started`, `ai_speech_ended`, `avatar_status`.
- **Done:** round trip by hour 3–4; persona + moderator voices (or fallback) by hour 8.

### Person C — Backend, audience brain, curveballs, slides, report
**Owns:** `backend/main.py`, `spec/contracts.py`, `Makefile`, `backend/scenarios/`, `services/{slides,audience,scheduler,curveballs,report}.py`, `backend/tests/`.
- FastAPI, WebSocket event bus, static-file mount for `frontend/`, in-memory session state with JSON dump per session.
- PDF text extraction and per-slide PNG rendering (PyMuPDF). Preset and roster loading. Custom-persona expansion (free text → `Persona`, one Claude call at session start, P0-3b).
- Orchestrator, follow-up, recovery prompts (§9); scheduler (§8); curveball engine (§6) with budgets, triggers and recovery tracking; report (§10).
- Mocks Person B's voice module so everything is testable silent.
- **Done:** mock run yields a grounded question, one curveball with a recovery metric and a report by hour 6; real integration by hour 10.

**Who unblocks whom.** A is blocked by C for contracts (hour 1) and by B for mic capture (hour 4). C is blocked by B for real transcript timing (hour 8). B is blocked by nobody. When blocked, build against the mock and write the gap in `DEMO_STATUS.md`; never wait silently.

## 12. The session: seven steps for every Claude Code session

1. Read this file, `DECISIONS.md`, and your owner section. Read `PRIORITIES.md` and take the first undone line with your name that is not blocked. You do not pick a different, better or smaller line.
2. Branch from `main` if you are not already on your `feat/*` branch. Pull `main` first.
3. Tests first where a deterministic test is possible (everything Person C owns; frontend state reducers). The three canonical tests: `claim → question → answer → follow-up`; `slides_down → presenter resumes → recovery metric recorded`; `time_crunch → countdown → automatic Q&A`.
4. Implement inside your owned paths. A file outside them is a one-line note in your checkpoint report with the reason, and a message to its owner.
5. `make check` exit 0. For anything touching the demo path, run the mock end-to-end once and watch it.
6. Merge to `main` (fast-forward or squash; no long-lived divergence). Update `PRIORITIES.md` (`done`) and `DEMO_STATUS.md` if a demo step changed state.
7. Append the checkpoint report (§14) to `PROGRESS.md`. Stop. One priority line per session unless the line took under twenty minutes, then take the next.

## 13. Gotchas — none of these are derivable from the tree

**Vendor.** We have one Higgs API key (Boson AI). What the docs say, as of 23 October 2026 (verify anything you build on; dated findings go in `DECISIONS.md` under "Vendor"):
- **Higgs Realtime** — speech-to-speech over WebSocket `wss://api.boson.ai/v1/realtime`, model `higgs-realtime`, protocol compatible with the OpenAI Realtime API (the OpenAI SDK works with a Boson base URL). `turn_detection`: `server_vad` (threshold default 0.85, `silence_duration_ms` 500), `semantic_vad`, or `null` for manual `input_audio_buffer.commit`. Barge-in is built in: user speech cancels the in-flight response; `input_audio_buffer.speech_started` is the signal to stop local playback. User transcripts come only as a **final** event, `conversation.item.input_audio_transcription.completed`, and only when the transcription model `higgs-stt-3.1` is configured; there is no streaming user-transcript delta. Assistant captions stream via `response.output_audio_transcript.delta` (and `.length` for alignment). Text-only mode: `output_modalities: ["text"]`. Browser clients authenticate with ephemeral keys from `POST /v1/realtime/client_secrets`; the API key never ships to the browser. Sessions close on 5 min idle and on a max-duration cap. WebRTC is not available; WebSocket only. ~700 ms speech-in to speech-out claimed.
- **Higgs TTS 3** — `POST /v1/audio/speech`, model `higgs-tts-3`, voices `default`, `jake` and the preset list at `GET /v1/audio/voices`; cloning via `ref_audio` (never a real person without written consent). Streaming: `stream: true`, `response_format: "pcm"` (16-bit, 24 kHz, mono). Word timestamps only with `stream: false`. Inline tags: `<|emotion:anger|confusion|contemplation|surprise|enthusiasm|…|>`, `<|style:whispering|shouting|>`, `<|prosody:pause|long_pause|speed_fast|pitch_low|expressive_high|…|>`, `<|sfx:cough|sigh|laughter|sniff|…|>`, `<|reset|>`. Delivery tags go at the start of the text; sfx tags are vocalised in the speaker's voice, so a cough works, a phone ring or door slam does not — those stay local clips in `demo/sfx/`.
- **Higgs Avatar** — still image + audio or text → video; realtime sessions exist (`/v1/avatar-realtime`), $0.07/min. P2 only.
- **Not offered:** a chat-completions/LLM endpoint or a standalone audio-understanding endpoint. The orchestrator needs its own LLM (§15 Q1), or Realtime in text mode, which is untested.

**Voice architecture** (Person B decides by hour 2 from the hour-1 tests). Two viable shapes; the five tests pick one:
- **Shape 1, Realtime-centred:** browser holds the Realtime WebSocket with an ephemeral key; it forwards `input_audio_transcription.completed` and speech start/stop events to our backend over our own WS; the backend's orchestrator decides what to say and makes Realtime say it. Lowest latency; works only if test 2 passes.
- **Shape 2, split:** Realtime (or `higgs-stt-3.1` through it) is used only to listen and transcribe; every persona, heckler and moderator line is rendered by TTS 3 with the persona's voice and tags, streamed as PCM, and played by the browser. Deterministic, distinct voices and styles guaranteed; a little slower; the backend owns all audio decisions. **This is the default if test 2 fails.**
- Hour-1 tests, in order: (1) mic → Realtime → spoken reply round trip; measure latency. (2) Can Realtime be made to speak a specific scripted line on demand (`response.create` with instructions, or a `conversation.item.create` + `response.create`), and can one session switch voice per turn? (3) Does `higgs-stt-3.1` transcription arrive with usable timestamps for the resume-gap metric; if not, which timestamps do we take from our own clock on `speech_started`/`speech_stopped`? (4) TTS 3 streaming with `<|emotion:anger|>` for the heckler and a neutral moderator voice; list two or three preset voices that sound distinct. (5) Ephemeral client secret from our backend works in the browser.
- Whatever the shape: only our backend holds the API key; the browser gets ephemeral secrets; raw PCM never rides our JSON event bus.

**Money.** $100 of credit on one key, shared by three people and the stage demo. Prices: Realtime ≈ $0.016/min of audio in + out plus tokens ($0.75/M in, $4.50/M out), TTS $0.015 per 1K characters, STT $0.0025/min, Avatar $0.07/min. A three-minute session costs cents; an avatar session or a forgotten open WebSocket costs dollars. Rules: every Realtime or Avatar session is created with a hard client-side timeout and closed in a `finally`; no session is left open in a notebook or a tab; `/health` prints the spend counter we keep ourselves (characters and minutes sent) because the vendor's dashboard lags. **Reserve $30 for hour 18 onward.** If a mock will do, use the mock; the deterministic tests never call the vendor. If the counter passes $60 before hour 15, stop live testing and say so in `DEMO_STATUS.md`.

**One voice.** Only one AI voice ever speaks. `crosstalk` is two sequential turns, never two streams. A second `request_persona_turn` while one is playing cancels the first or queues; it never overlaps.

**Grounding.** A question without a `citedExcerpt` or `slideNumber` does not get asked. A report line without a verbatim quote or a measured number does not get written. Timing you did not measure is `null`, labelled as such in the UI. Filler and WPM carry the recognition-accuracy caveat on screen. A transcript measures words, not intonation, vocal confidence or monotone: never claim those from text.

**Fairness.** Heckler, fact_check and bait challenge the idea, the evidence or the delivery. No insults, no identity, no appearance, no mocking an accent. Personas are fictional and labelled. No cloning a real person's voice or face without written consent; the demo avatar is synthetic. Pause and Skip are never penalised in scoring.

**Demo honesty.** The debug curveball endpoint is for rehearsal and as a fallback if the scheduler's timing is off on stage; it is disabled unless `DEBUG_CURVEBALL_ENDPOINT=true`. Never present pre-scripted AI responses as live. If we demo from the backup recording, we say so.

**Privacy.** Ask for mic (and camera, if used) permission with a sentence that says what is recorded. Store no raw audio or video by default. If recording is on, the setup screen says so and the report page has Delete. Transcripts live in the local session JSON only.

**Latency budget.** Question generation runs during pauses and shows a "thinking" state on the persona tile; if it misses its window (~4 s), skip it, do not queue a stale question. Pre-generate the heckler line once the value proposition is detected.

**Environment.** `.env.example` carries `BOSON_API_KEY=`, `BOSON_REALTIME_MODEL=higgs-realtime`, `BOSON_TTS_MODEL=higgs-tts-3`, `BOSON_STT_MODEL=higgs-stt-3.1`, `BOSON_AVATAR_ENABLED=false`, `ANTHROPIC_API_KEY=`, `ORCHESTRATOR_MODEL=claude-opus-5-5`, `CURVEBALLS_ENABLED=true`, `DEBUG_CURVEBALL_ENDPOINT=true`, `SPEND_SOFT_CAP_USD=60`, `PORT=8000`. Two keys, never pasted into chat, a commit, or a screenshot.

**Hackathon tooling.** Pinned versions in `package.json` and `requirements.txt`; no `latest`. Never `npx -y`. One sample deck in `demo/sample_pitch.pdf` so PDF parsing failing on stage is recoverable with one click.

**Stuck.** If `make check` has not moved in about fifteen turns, stop, write the `Open question for the team` line, and ping the owner who can unblock you. Do not widen scope, add a dependency, or lower a threshold to get unstuck.

## 14. Checkpoint report (append to `PROGRESS.md`)

```
## <PRIORITY-ID> · <YYYY-MM-DD HH:MM> · <owner> · session <n>
Built: one sentence
Tests: <test names added or changed> | none
Gate: green at <sha> | red because <what>
Demo path: <which DEMO_STATUS.md steps changed state> | unchanged
Files outside my paths: none | <file>: <reason, owner told>
Proposed decision changes (not implemented): none | proposal
Next: <PRIORITY-ID>, because <blocker> now clears
Open question for the team: none | one line
```

## 15. Open questions for the team (answer in `DECISIONS.md`, then delete here)

Settled (23 October 2026, copy into `DECISIONS.md` as the first entry): the name is **PresAI**; voice/STT/avatar are the **Higgs API** on one key with **$100 of credit**; the orchestrator is **Claude (`claude-opus-5-5`) on an Anthropic key**; the **audience builder is P0** (P0-3b); the stack is **all Python** (FastAPI + static frontend); judging weights **product, UX and demo quality**, so Avatar stays P2 and polish is the first P1.

1. **Voice architecture.** Shape 1 or Shape 2 (§13) — Person B answers by hour 2 from the hour-1 tests. Everyone else builds against the mock until then.
2. **Demo content.** Which preset and deck do we demo? Default: Startup Pitch, Normal, VC + Student + one *custom* persona typed live on stage (shows off P0-3b), curveball `slides_down`. Who is the presenter on stage?
3. **Machines and network.** Who has a laptop that can run everything for the stage demo, and do we have wired network or a hotspot? The Realtime WebSocket needs a stable connection.
4. **Stage audio.** One mic and one speaker on stage: do we raise the VAD threshold, use a headset, or go push-to-talk for the live demo regardless of what works in a quiet room?
5. **Recording consent.** Do we store any audio at all during the hackathon? Default: no.
6. **Anthropic key quota.** Whose key, and is it a personal account with a low monthly cap? A session makes ~10–20 calls; a day of three people testing is a few hundred. Confirm the cap won't trip mid-demo.
7. **After the hackathon.** One-off, or accounts and persistence later? Decides whether session JSON gets a stable schema now.

## 16. Definition of hackathon success

The system accepts a deck, lets the presenter choose who is in the room, listens to a real presenter, asks a relevant question in a distinct voice, handles a response and follow-up, throws at least one realistic curveball, measures how the presenter recovered, and produces a report that quotes actual moments. Done twice in a row with nobody touching the keyboard. Avatars, extra curveballs and vocal analysis make it stronger; they are not prerequisites.
