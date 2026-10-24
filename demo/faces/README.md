# demo/faces — portraits for the talking heads

The cast: ten fictional, AI-generated people photographed in **one** meeting room (same
whiteboard, lights and table), so they join into one continuous room on screen. Source:
`demo/faces_source/grid_room.png` (crops in `crops/`). Never put a real person's photo here
without their written consent (CLAUDE.md §13 Fairness).

| persona (roster) | character | voice |
|---|---|---|
| vc · Dana | layla | eleanor |
| student · Sam | ken | jake |
| professor · Prof. Okafor | mr_tan | marcus, slower |
| methods · Dr. Lind | dev | marcus, faster |
| mentor · Alex, journalist · Morgan | hannah | chloe |
| classmate · Jordan | leo | jake, lower |
| hiring_manager · Priya | mei | eleanor, higher |
| senior_eng · Marcus | finn | oliver |
| recruiter · Casey | ava | chloe, higher |
| customer · Riley | ray | oliver, higher |
| exec · The Sponsor | mr_tan | marcus, slower |

- `<persona_id>--<character>.jpg` pins a face; the character fixes the voice
  (`CHARACTER_VOICES` in `backend/services/voice_higgs.py`) in every preset.
- `pool_<n>--<character>.jpg` go to custom personas in order, never repeating a character
  already at the table.
- Crop to 3:4 (talking heads render at 480×640, so the face doesn't jump).
- The photo sets the resting expression. For a tougher room, generate the faces neutral:
  "attentive, mouth closed, not smiling, slightly skeptical, listening to a pitch".

Needs `BOSON_AVATAR_ENABLED=true`. Idle loops render once per face file and are cached.
