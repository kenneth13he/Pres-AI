"""A silent voice adapter: records every call and reports speech as instantly finished.

Why: the deterministic tests and all offline frontend work run on this.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec.contracts import SessionConfig, SessionEvent

from .voice_base import OnEvent, OnTranscript


@dataclass
class MockVoice:
    calls: list[tuple[str, dict]] = field(default_factory=list)
    _session_id: str = ""
    _on_event: OnEvent | None = None
    _on_transcript: OnTranscript | None = None

    def on_event(self, callback: OnEvent) -> None:
        self._on_event = callback

    def on_transcript(self, callback: OnTranscript) -> None:
        self._on_transcript = callback

    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None:
        self._session_id = session_id
        self.calls.append(("start", {"session_id": session_id}))

    async def send_context(self, text: str) -> None:
        self.calls.append(("context", {"text": text}))

    async def request_persona_turn(
        self, persona_id: str, text: str, style: str | None = None
    ) -> None:
        self.calls.append(("persona", {"persona_id": persona_id, "text": text, "style": style}))
        await self._emit_audio_status(f"spoke:{persona_id}")

    async def play_moderator_line(self, text: str) -> None:
        self.calls.append(("moderator", {"text": text}))
        await self._emit_audio_status("spoke:moderator")

    async def play_sfx(self, sfx_id: str) -> None:
        self.calls.append(("sfx", {"sfx_id": sfx_id}))

    async def cancel_speech(self) -> None:
        self.calls.append(("cancel", {}))

    async def stop_voice_session(self) -> None:
        self.calls.append(("stop", {}))

    async def _emit_audio_status(self, status: str) -> None:
        if self._on_event:
            await self._on_event(
                SessionEvent(
                    type="audio_status",
                    session_id=self._session_id,
                    timestamp_ms=0,
                    payload={"status": status, "adapter": "mock"},
                )
            )
