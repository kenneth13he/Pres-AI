# demo/faces — portraits for the talking heads

Drop **fictional** portraits here (PNG, JPEG or WebP; one face, looking at the camera, head and
shoulders). Never a real person's photo without their written consent (CLAUDE.md §13 Fairness).

- `vc.jpg`, `student.png`, … pins a face to that persona id.
- Any other image is handed to the remaining seats in name order.
- Files starting with `_` are test faces, used only when nothing else is here
  (`_sample_boson.jpg` is Boson's own docs sample, used to prove the pipeline).
- Square photos give 640×640 talking heads; portrait 3:4 photos give 480×640.

Talking heads need `BOSON_AVATAR_ENABLED=true` in `.env`. A clip renders in ~5–8 s; past the
`BOSON_AVATAR_BUDGET_S` budget (9 s) the voice plays over the still portrait instead.
