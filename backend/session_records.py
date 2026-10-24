"""Private, read-only snapshots keep finished reports available across a local restart."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spec.contracts import Report


class SessionRecords:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session_id):
            raise ValueError("Invalid session identifier")
        return self.root / f"{session_id}.json"

    def save(self, snapshot: dict[str, Any], report: dict[str, Any]) -> None:
        session_id = snapshot["session_id"]
        if snapshot.get("phase") != "report" or report.get("session_id") != session_id:
            raise ValueError("Only finished sessions may be saved")
        Report.model_validate(report)
        path = self._path(session_id)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = {"snapshot": snapshot, "report": report,
                "saved_at_utc": datetime.now(UTC).isoformat()}
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root,
                                             prefix=".session-", delete=False) as stream:
                temporary = Path(stream.name)
                os.fchmod(stream.fileno(), 0o600)
                json.dump(data, stream, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(self, session_id: str) -> dict[str, Any] | None:
        try:
            path = self._path(session_id)
            if path.stat().st_size > 4 * 1024 * 1024:
                return None
            data = json.loads(path.read_text())
            report = Report.model_validate(data["report"])
            snapshot = data["snapshot"]
            if (snapshot.get("phase") != "report" or snapshot.get("session_id") != session_id
                    or report.session_id != session_id):
                return None
            return data
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
