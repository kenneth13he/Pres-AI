# demo/faces — portraits for the talking heads

Fictional, AI-generated faces (source: `demo/faces_source/grid.png`, supplied by the team).
Never put a real person's photo here without their written consent (CLAUDE.md §13 Fairness).

- `<persona_id>.jpg` pins a face to a roster persona. Every roster persona has one, and its
  gender matches the persona's preset voice (`ROSTER_VOICES` in `voice_higgs.py`).
- `pool_<n>_<name>.<f|m>.jpg` are handed to custom personas in order; the `f`/`m` tag picks a
  matching voice. Faces pinned to other roster personas are never handed out.
- Files starting with `_` are test faces, used only when nothing else is here.
- Square photos give 640×640 talking heads; 3:4 photos give 480×640.

Talking heads need `BOSON_AVATAR_ENABLED=true` in `.env`. A clip renders in ~5–8 s; past the
`BOSON_AVATAR_BUDGET_S` budget (9 s) the voice plays over the still portrait instead.
