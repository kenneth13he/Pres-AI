# spec/curveballs.md — the curveball catalog

Edition 1 (23 Oct 2026) = CLAUDE.md §6, which is normative. The machine-readable form is `CATALOG` in `backend/services/curveballs.py`; a change here is a change there in the same commit.

| Kind | What happens | Tests | Delivered by | Recovery metric | Priority |
|---|---|---|---|---|---|
| `time_crunch` | "We're running behind — 60 seconds." Timer red; at 0 → Q&A. | Prioritising | Moderator + timer | Finished within 60 s? Close had the ask? | **P0** |
| `slides_down` | Viewer goes black; restores after ~30 s or on Restore. | Presenting without the crutch | UI (+ moderator line) | Seconds until speech resumed; kept structure? | **P0** |
| `heckler` | Persona challenges the core idea bluntly. | Composure, reframing | Persona, impatient style | Addressed directly, composed, returned to the talk? | **P0** |
| `latecomer` | "Give me the 20-second version?" | Summarising | Persona | Recap ≤ 30 s covering problem/solution/ask? | P1 |
| `bait` | Plausible question just outside what was covered. | Admitting uncertainty | Persona | Scoped/admitted vs invented? | P1 |
| `distraction` | Phone / door / cough mid-sentence. | Recovering the thread | Local clip; cough via TTS tag | Pause length; filler burst | P1 |
| `vip_arrives` | "The decision-maker just joined for two minutes." | Audience-shifting | Moderator + new tile | Ask + why-now in 30 s? | P1 |
| `crosstalk` | Two personas disagree (sequential turns). | Taking back the room | Two persona turns | Re-took control within 20 s? | P2 |
| `fact_check` | Persona cites a contradicting number. | Defending evidence | Persona | Source cited / uncertainty acknowledged? | P2 |
| `elevator` | "30 seconds, no slides." Slides dim. | Compression | Moderator + UI | Problem/solution/ask in 30 s? | P2 |
| `plain_language` | "Explain it to someone with no background." | Jargon control | Persona | Jargon count next 30 s vs before | P2 |
| `dead_room` | Tiles blank-faced for 45 s. | Confidence without feedback | UI | Pace and filler change | P2 |

Trigger rules, difficulty budgets, fairness: CLAUDE.md §6.2–6.3, §2, §13 "Fairness". A timing that cannot be measured is `null`, never 0.
