"""The voice seam between the audience brain and whatever makes sound.

Why: Person C's engine must be testable silent, and Person B must be free to pick
Shape 1 or Shape 2 (CLAUDE.md §13) without touching the engine. The engine calls
only these methods; the adapter reports back through `VoiceEvents`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from spec.contracts import SessionConfig, SessionEvent, TranscriptSegment

OnEvent = Callable[[SessionEvent], Awaitable[None]]
OnTranscript = Callable[[TranscriptSegment], Awaitable[None]]


class VoiceAdapter(Protocol):
    async def start_voice_session(self, session_id: str, config: SessionConfig) -> None: ...
    async def send_context(self, text: str) -> None: ...
    async def request_persona_turn(
        self, persona_id: str, text: str, style: str | None = None
    ) -> None: ...
    async def play_moderator_line(self, text: str) -> None: ...
    async def play_sfx(self, sfx_id: str) -> None: ...
    async def cancel_speech(self) -> None: ...
    async def stop_voice_session(self) -> None: ...
    def on_event(self, callback: OnEvent) -> None: ...
    def on_transcript(self, callback: OnTranscript) -> None: ...
