"""Validate every frontend mock fixture against spec/contracts.py.

Why: the frontend is built on these fixtures until the backend is live; if a fixture drifts
from the contract, the hour-10 integration fails silently. A session fixture has `config`
and `events`; a report fixture has `dimensions`; anything else (presets) is skipped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic import ValidationError  # noqa: E402

from spec.contracts import Report, SessionConfig, SessionEvent  # noqa: E402

MOCKS = ROOT / "frontend" / "mocks"


def main() -> int:
    failures = 0
    for path in sorted(MOCKS.glob("*.json")):
        data = json.loads(path.read_text())
        try:
            if "events" in data:
                SessionConfig.model_validate(data["config"])
                for event in data["events"]:
                    SessionEvent.model_validate(event)
                print(f"{path.name}: {len(data['events'])} events ok")
            elif "dimensions" in data:
                Report.model_validate(data)
                print(f"{path.name}: report ok")
            else:
                print(f"{path.name}: skipped (not a session or report fixture)")
        except (ValidationError, KeyError) as exc:
            failures += 1
            print(f"{path.name}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
