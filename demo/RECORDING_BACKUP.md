# Local presentation backup

The demo laptop has a complete real-run backup at
`demo/backup-presentation-60d6e482.webm` (about 6 minutes 16 seconds, 41,294,172 bytes).
The media is private and excluded from Git; cloning this repository does not download it.
The original downloaded recording and the earlier candidate copy remain preserved.

Open the WebM in the separate Google Chrome app (Command-O, then select the file).
The user reviewed the full clip there and confirmed readable picture and both presenter
and audience voices. The embedded Codex preview displayed black despite valid captured
frames; Chrome playback was confirmed.

## What the backup shows

- Human microphone input with live Boson/Higgs audience speech and reasoning.
- Grounded audience questions, one follow-up per exchange, static fictional portraits.
- Naturally scheduled blackout and captured recovery measured at 7.140 seconds.
- Automatic Q&A completion, microphone/audio shutdown and the actual session report.

This was recorded from build `2bde30b`, before the subsequent report-citation and queued-clock
fixes. Its report coaching visibly used a safe fallback, and its recorded completion clock
had the documented backdating issue. It is a usable record of a real presentation, not a
claim of two clean presentations on the latest build. P0-13 remains unsigned.

SHA-256: `26c5b33d9ef306460ed1eec33cc5a70b1b92f3e252da3fde7bb71e3de85dee0c`

The local backup-file requirement of P0-14 is met. For a final-build stage demonstration,
replace this fallback with a reviewed recording from the remaining clean-run acceptance.
Do not publish the recorded voice or raw session evidence with source-code updates.
