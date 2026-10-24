"""PDF → per-slide text and PNG.

Owner: Person C (P0-4). Test: backend/tests/test_slides.py.

Why: the orchestrator grounds questions in slide text; the room shows the PNGs so the
frontend never parses a PDF. Decks live under data/decks/<deck_id>/ (git-ignored) and are
served at /decks/<deck_id>/<n>.png by main.py. Slides are 1-based.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pymupdf

from spec.contracts import Deck, Slide

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "decks"
RENDER_DPI = 96  # ~1024 px wide for a 16:9 slide: sharp enough for the room, small enough to serve
MAX_PAGES = 60  # a 24-hour hackathon deck; anything longer is a mistake, not a use case
_DECKS: dict[str, Deck] = {}


class DeckError(ValueError):
    """The upload is not a PDF we can use; the message is safe to show the presenter."""


def ingest_pdf(pdf_bytes: bytes, filename: str, render_png: bool = True,
               data_dir: Path | None = None) -> Deck:
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # pymupdf raises several types for a bad file
        raise DeckError("That file is not a readable PDF.") from exc
    with doc:
        if doc.is_encrypted:
            raise DeckError("That PDF is password-protected; export an unprotected copy.")
        if doc.page_count == 0:
            raise DeckError("That PDF has no pages.")
        if doc.page_count > MAX_PAGES:
            raise DeckError(f"That PDF has {doc.page_count} pages; the limit is {MAX_PAGES}.")
        deck_id = uuid.uuid4().hex[:10]
        out_dir = (data_dir or DATA_DIR) / deck_id
        if render_png:
            out_dir.mkdir(parents=True, exist_ok=True)
        slides: list[Slide] = []
        for index in range(1, doc.page_count + 1):
            page = doc[index - 1]
            image_url = None
            if render_png:
                page.get_pixmap(dpi=RENDER_DPI).save(out_dir / f"{index}.png")
                image_url = f"/decks/{deck_id}/{index}.png"
            slides.append(Slide(number=index, text=_clean(page.get_text()), image_url=image_url))
    deck = Deck(deck_id=deck_id, filename=filename, page_count=len(slides), slides=slides)
    _DECKS[deck_id] = deck
    return deck


def _clean(text: str) -> str:
    """Collapse PyMuPDF's one-span-per-line output into readable lines for the prompt."""
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def get_deck(deck_id: str | None) -> Deck | None:
    return _DECKS.get(deck_id) if deck_id else None


def slide_text(deck: Deck | None, number: int) -> str:
    if deck is None or number < 1 or number > len(deck.slides):
        return ""
    return deck.slides[number - 1].text
