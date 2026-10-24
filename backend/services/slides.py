"""PDF → per-slide text and PNG.

Owner: Person C (P0-4).

Why: the orchestrator grounds questions in slide text; the room shows the PNGs so the
frontend never parses a PDF. Decks live under data/decks/<deck_id>/ (git-ignored) and are
served at /decks/<deck_id>/<n>.png by main.py.
"""

from __future__ import annotations

from pathlib import Path

from spec.contracts import Deck

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "decks"
_DECKS: dict[str, Deck] = {}


def ingest_pdf(pdf_bytes: bytes, filename: str, render_png: bool = True) -> Deck:
    """PyMuPDF (`import pymupdf`; `fitz` is the deprecated alias): open from bytes, per page → Slide(number, text=page.get_text(),
    image_url="/decks/<id>/<n>.png" after page.get_pixmap(dpi=96).save(...)). Store in _DECKS."""
    # TODO(C)
    raise NotImplementedError


def get_deck(deck_id: str | None) -> Deck | None:
    return _DECKS.get(deck_id) if deck_id else None


def slide_text(deck: Deck | None, number: int) -> str:
    if deck is None or number < 1 or number > len(deck.slides):
        return ""
    return deck.slides[number - 1].text
