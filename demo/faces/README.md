# Static fictional audience portraits

Imported unchanged from `kenneth13he/Pres-AI`, branch `feat/voice-room`, commit
`4b508eecf37915417cafe504ee95bd2e6335ab67` (24 October 2026).
The upstream cast is AI-generated and photographed in the same fictional meeting room.
No real-person photo or voice clone is used.

This local integration uses JPEG portraits only. It does **not** need avatar access,
`BOSON_AVATAR_ENABLED=true`, video generation or idle loops. Talking-head videos stay off.

`frontend/js/portraits.js` selects distinct pictures for the moderator and each audience
seat while retaining our accepted voice assignments: eleanor for the moderator,
marcus for Dana, chloe for Sam and oliver for the professor. It prefers the upstream
cast's matching base voice where available. Nora has no named member in this cast;
its picture uses the static pool. Remaining seats use a deterministic unused picture.
The role/name shown beside a portrait comes from the session, including custom personas.

Upstream role prefixes on filenames are provenance, not a local voice reassignment.
The source files are kept under their upstream names so future asset updates can be compared.
