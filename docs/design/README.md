# Handoff: PresAI frontend redesign (homepage + setup wizard + live room + report)

Target repo: `kenneth13he/Pres-AI`, branch `main`, folder `frontend/`.

## Overview
A full visual and flow redesign of the PresAI frontend:
- **Homepage** (`frontend/index.html`): premium dark landing page with a self-playing demo room, interactive setup cards, how-it-works, rooms, curveballs, report preview, FAQ and CTA.
- **App** (`frontend/setup.html` → `room.html` → `report.html`): a 5-step setup wizard (Profile → Slides → Room → Audience → Curveballs & pacing) with a live preview, then the live room and the report card.
- **New in this round: custom guests.** Users can add their own audience member with a photo (Boson **Higgs Avatar**) and a voice (Boson **Higgs TTS 3**).

## About the design files
The `.dc.html` files in this folder are **design references built in HTML**, not production code. Open them in a browser (keep `support.js` next to them) to see the intended look and behaviour. Recreate them in the repo's existing stack: framework-free static HTML + ES modules + Tailwind CDN, served by FastAPI (see DECISIONS.md "Stack"). Don't ship the `.dc.html` files or `support.js`.

Wire everything through the existing seams: `frontend/js/api.js` (`getPresets`, `uploadSlides`, `createSession`), `spec/contracts.schema.json` (`SessionConfig`, `Persona`) and the WebSocket event stream used by `room.js`.

## Fidelity
**High fidelity.** Colours, type, spacing, radii and copy are final. Match them exactly, using Tailwind arbitrary values or `app.css`.

## Design tokens
Fonts (Google Fonts): **Urbanist** 400/500/600/700/800 for UI text. **JetBrains Mono** 400/500 for labels, counters, timers and IDs.

Colours:
| Token | Value | Use |
|---|---|---|
| bg (app) | `#0c0d0f` | App page background; inputs |
| bg (home) | `#0a0b0d` | Homepage background |
| surface | `#131517` | Cards, panels |
| surface-2 | `#0f1113` | Homepage cards |
| raised | `#1a1d20` / `#1c1f22` / `#262a2e` | Icon wells, hover, selected segment |
| border | `#23272a` | Card borders |
| border-input | `#2a2f32` | Inputs, secondary buttons |
| border-dashed | `#2f3538` | Dashed drop zones / add tiles |
| text | `#eceeed` | Primary text |
| muted | `#9aa1a0` (home: `#a3aaa8`) | Secondary text |
| faint | `#6c7372` | Hints, tertiary |
| mint (accent) | `oklch(0.82 0.15 150)` | Primary CTA, selection, speaking ring. Text on mint: `#07120b` |
| mint tint | `oklch(0.82 0.15 150 / .07)` bg, `/ .7` border | Selected cards |
| coral (alert) | `oklch(0.78 0.17 22)` | Curveballs, Moderator, errors, timer crunch |
| coral tint | `oklch(0.78 0.17 22 / .08)` bg, `/ .7` border | Selected curveball cards |

Radii: 999px (pills), 18px (drop zones, big cards), 16px (panels), 14px, 12px (roster tiles, segmented controls), 10px (inputs, buttons), 9px/7px (small buttons).
Spacing: 4/6/8/10/12/14/18/22/24/28/40px. Page padding 28px, max width 1240px (app) / 1200px (home).
Type scale (app): H1 34/800/-0.03em; panel title 16–18/700–800; body 15–16; hint 12–13; mono label 11/500/+0.06em uppercase.
Type scale (home): H1 `clamp(48px,7.4vw,96px)`/800/-0.045em/lh .98; H2 `clamp(34px,4.4vw,56px)`/800/-0.035em; section kicker 13px mono +0.08em in mint or coral.

## Screens

### 1. Homepage (`index.html`)
Reference: `Home A - Premium Dark.dc.html`.
- **Nav:** fixed, max 1200px. Transparent at top. Past 24px of scroll it gets `rgba(10,11,13,.78)` + 14px blur + a `#1c2022` bottom border, and padding shrinks 22px → 14px. It **hides on scroll down** (past 140px, deltas over 6px) and shows again on scroll up. Use a rAF-throttled, passive scroll listener.
- **Hero:** coral-dot pill "LIVE AI AUDIENCE · UP TO 10 GUESTS", centred H1, subcopy, two CTAs (mint pill → app).
- **Self-playing demo room:** a scripted beat timeline (presenting → interruption → curveball → recovering → Q&A) with captions, a speaking ring on the active tile, and a crunch timer. It has **Pause/Play** and **Sound on/off** controls; sound is off by default. Audio currently uses browser `speechSynthesis` as a stand-in for Higgs voices; swap it for Higgs TTS 3 when available.
- **Three interactive setup cards** ("Three clicks to a live room"): profile, deck, guest count.
- **Rooms** (5 settings), **Curveballs** grid, **Report card** preview, **FAQ**, and a final **CTA** ("Your room is ready.").
- Sections fade in with an IntersectionObserver on `[data-reveal]`.

### 2. App shell (`setup.html`)
Reference: `Pres AI App.dc.html` (use the `startStep` prop / Tweaks to jump between steps).
- Sticky header with logo, a **step pill nav** (numbered dot → ✓ when done; current step `#1c1f22` bg), and an Exit link.
- Two-column grid (`repeat(auto-fit,minmax(min(100%,440px),1fr))`, gap 40px). The left column holds the step content (max 640px). The right column holds the **live room preview**: a 16:9 stage showing seat layout per room type, coloured seats, slide position, and a session summary.

#### Step 1 · Profile
Saved profiles appear as cards (initial, swatch, meta "role · room · N guests"), plus "New profile" and **"Use default profile"** (skips straight to Slides). A profile stores `pname, role, goal, level, tone, setting, chosen, skep, input, customs`. It's persisted in `localStorage` (`presai.profiles`, `presai.activeProfile`) and auto-saves on change.

#### Step 2 · Slides
Drop zone accepts **PDF, PowerPoint (.ppt/.pptx/.pps/.ppsx/.pot/.potx), Keynote (.key), OpenDocument (.odp/.otp)**. Other extensions show a coral error. There's also a link field for Google Slides / Canva / OneDrive. Below that is the **Presentation context** box: notes textarea plus attachable files (.txt/.md/.pdf/.doc/.docx).
> Backend today only ingests PDF (`slides.ingest_pdf`). Either convert other formats server-side or limit the accept list to PDF until that lands.

#### Step 3 · Room
Five room types: video call, classroom, boardroom, lecture hall, interview panel. Each has its own seat layout (see `layout()` in the reference JS), a guest count stepper + slider (1–10), and an input-mode segment (Live mic / Push to talk).
> `setup.js` currently caps the roster at 2–3 personas. The design allows 1–10; confirm with the team (DECISIONS.md) before raising it.

#### Step 4 · Audience
- Preset pills (Startup Pitch, etc.), then the **Roster** grid (`repeat(auto-fill,minmax(190px,1fr))`, gap 8px) built from `personas.yaml`. Tiles have a checkbox, name and role, max 10 selected and at least 1.
- **Custom guest tiles** (new) come after the presets: checkbox, 32px round photo, name, role, mono voice label (`voice · marcus`), and a row of **Edit / Remove** text buttons underneath.
- **"+ Custom guest" tile:** dashed `#2f3538` border, mint "+" chip, subtitle "Your own photo and voice". Clicking it opens the panel below.
- **Custom guest panel:** border `oklch(0.82 0.15 150 / .45)`, radius 16, padding 22. It contains:
  - **Portrait · Higgs Avatar:** 168×168 click/drop zone, PNG/JPEG/WebP only. Crop to a centred square, downscale to 320px, store as a JPEG data URL (quality 0.85). Shows a "Replace" chip once set.
  - **Name** (required), **Role** (optional, defaults to "Custom guest"), **What they push on** (optional free text, used as the persona focus).
  - **Voice · Higgs TTS 3**, a 3-way segment:
    - *Preset voice:* `chloe, eleanor, jake, marcus, nora, oliver` → `voice`
    - *Voice ID:* free text such as `voice_abc123…` → `voice`
    - *Clone from clip:* audio upload (wav/mp3/opus/pcm/flac, 5–30 s of clean speech), a transcript textarea (→ `ref_text`, recommended), and a **required** consent checkbox ("I own the right to use this voice.")
  - Footer: a "Still needs …" hint, Cancel, and **Add to roster / Save changes**. Disabled (`#262a2e` bg, `#6c7372` text, not-allowed cursor) until name + photo + a valid voice are set.
  - Saving adds the guest and auto-selects it if under 10. Removing a guest also drops it from `chosen` and `skep`; if nothing is left selected, it falls back to `vc`.
- **Skepticism** panel: one 0–100 slider per selected guest (custom default 50).

**Backend integration for custom guests:**
- Photo → Higgs Avatar `ref_image` (`POST /v1/videos` or `/v1/videos/stream`, model `higgs-avatar`).
- Voice → Higgs TTS 3 `POST /v1/audio/speech` with `voice`. For cloned clips, call `POST /v1/audio/voices` once with `ref_audio` + `ref_text` and store the returned `voice_id`. Never send the clip on every turn.
- `Persona` in `spec/contracts.py` needs optional `avatar_url` / `voice_id` (and a `custom: true` label). Note that `ClaudeOrchestrator.expand_persona` currently **scrubs** `voice_id`/`avatar_url`, so user-supplied values must be merged back after expansion.
- Keep the "fictional / Custom" labelling rule from CLAUDE.md for generated personas. User-supplied photos need consent wording; reuse the voice consent pattern.

#### Step 5 · Curveballs & pacing
Difficulty segment (Friendly 0 / Normal 1 / Brutal 2 curveballs), a curveball count stepper (0–5), Surprise me / Let me choose, and a grid of 13 kinds (coral selection). Then interruption frequency (Rare/Normal/Often), length in minutes (1–20), and Q&A questions (0–3). Map these to `SessionConfig` (`difficulty`, `interruption_frequency`, `curveballs.mode/kinds`, `duration_target_s`, `qna_questions`).

### 3. Live room (`room.html`)
Header shows the room name, guest count and phase pill (coral for curveball/recovering, mint otherwise). The stage reuses the room layout with the slide viewer and guest tiles:
- Speaking ring: `0 0 0 2px mint, 0 0 28px oklch(0.82 0.15 150 / .35)`.
- Flash: coral ring.
- Blank / dead room: opacity .35 + grayscale.
- Custom guests show their photo as the tile background (later, the Higgs Avatar video).

Overlays: "Projector disconnected / Keep going." with a Restore button (slides_down), dim for elevator, and a coral crunch timer. Controls: Pause/Resume (P), Skip (S), ←/→ slides, End → Q&A → View report. Captions scroll with speaker colours (You `#eceeed`, Moderator coral, guests mint). Drive all of this from the engine's WebSocket events rather than the scripted beats in the reference.

### 4. Report (`report.html`)
Meta line (ROOM · N GUESTS · time), five dimensions (null shows "—" in `#4a5052`), metrics row, a curveball recovery list with resume time, evidence quote and suggestion, a key-moments timeline, and "From the audience" feedback cards. Bind to `mocks/report.json` / the report contract; show nulls with their caveats.

## State (app)
`step, profiles, profileId, pname/role/goal/level/tone, deck, link, ctx, ctxFiles, setting, input, chosen[], skep{}, preset, customs[], cg (open custom-guest draft | null), difficulty, cbCount, cbMode, kinds[], freq, length, qna`, plus live-room state (`beat/phase, log, t, crunch, paused, restored, slide`).
Custom guest record: `{ id, name, role, focus, img (data URL), vmode: 'preset'|'id'|'clone', preset, voiceId, clipName, refText, consent }`.

## Files in this bundle
- `Home A - Premium Dark.dc.html`: homepage reference
- `Pres AI App.dc.html`: wizard, live room and report reference (logic class at the bottom of the file has all layouts, copy and state rules)
- `support.js`: runtime needed only to open the references locally

## Suggested repo mapping
| Repo file | Built from |
|---|---|
| `frontend/index.html` | Home A |
| `frontend/setup.html`, `js/setup.js` | App steps 1–5 + preview |
| `frontend/room.html`, `js/room.js` | App live room |
| `frontend/report.html`, `js/report.js` | App report |
| `frontend/css/app.css` | Tokens above (replace cyan `#22d3ee` with mint, amber flash with coral) |
| `spec/contracts.py` / `backend/scenarios/personas.yaml` | Custom guest fields (`avatar_url`, `voice_id`) |
