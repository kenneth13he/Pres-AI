"""PDF ingest: text per slide, PNG per slide, honest errors."""

import pymupdf
import pytest

from backend.services import slides
from backend.services.slides import DeckError, ingest_pdf, slide_text


def make_pdf(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page(width=960, height=540)  # 16:9
        page.insert_text((72, 100), text, fontsize=24)
    data = doc.tobytes()
    doc.close()
    return data


def test_ingest_extracts_text_and_renders_png(tmp_path):
    pdf = make_pdf(["Problem: onboarding takes two weeks", "Solution: one day", "Ask: a pilot"])
    deck = ingest_pdf(pdf, "pitch.pdf", data_dir=tmp_path)
    assert deck.page_count == 3 and deck.filename == "pitch.pdf"
    assert [s.number for s in deck.slides] == [1, 2, 3]
    assert "onboarding takes two weeks" in deck.slides[0].text
    assert deck.slides[2].image_url == f"/decks/{deck.deck_id}/3.png"
    for n in (1, 2, 3):
        png = tmp_path / deck.deck_id / f"{n}.png"
        assert png.exists() and png.stat().st_size > 1000
    assert slides.get_deck(deck.deck_id) is deck


def test_slide_text_is_one_based_and_safe():
    deck = ingest_pdf(make_pdf(["one", "two"]), "d.pdf", render_png=False)
    assert deck.slides[0].image_url is None
    assert slide_text(deck, 1) == "one" and slide_text(deck, 2) == "two"
    assert slide_text(deck, 0) == "" and slide_text(deck, 3) == "" and slide_text(None, 1) == ""


def test_text_is_cleaned_for_the_prompt():
    deck = ingest_pdf(make_pdf(["  spaced   out  \n\n\nlines "]), "d.pdf", render_png=False)
    assert deck.slides[0].text == "spaced out\nlines"


def test_bad_inputs_raise_presenter_safe_errors():
    with pytest.raises(DeckError, match="not a readable PDF"):
        ingest_pdf(b"this is not a pdf", "x.pdf", render_png=False)
    with pytest.raises(DeckError, match="limit is"):
        ingest_pdf(make_pdf(["p"] * (slides.MAX_PAGES + 1)), "long.pdf", render_png=False)
    doc = pymupdf.open()
    doc.new_page()
    aes256 = pymupdf.PDF_ENCRYPT_AES_256  # type: ignore[attr-defined]  # exists at runtime (=5)
    locked = doc.tobytes(encryption=aes256, user_pw="pw", owner_pw="pw")
    doc.close()
    with pytest.raises(DeckError, match="password"):
        ingest_pdf(locked, "locked.pdf", render_png=False)


def test_ligatures_are_expanded():
    deck = ingest_pdf(make_pdf(["office network effects, fifty"]), "d.pdf", render_png=False)
    assert deck.slides[0].text == "office network effects, fifty"
    assert all(ord(ch) < 0xFB00 for ch in deck.slides[0].text)


def test_upload_route_returns_deck_and_serves_png():
    import shutil

    from fastapi.testclient import TestClient

    from backend.main import app

    made: list[str] = []
    try:
        with TestClient(app) as client:
            r = client.post("/api/slides", files={"file": ("pitch.pdf", make_pdf(["Hello"]),
                                                           "application/pdf")})
            assert r.status_code == 200, r.text
            deck = r.json()
            made.append(deck["deck_id"])
            assert deck["page_count"] == 1 and "Hello" in deck["slides"][0]["text"]
            png = client.get(deck["slides"][0]["image_url"])
            assert png.status_code == 200 and png.headers["content-type"] == "image/png"
            bad = client.post("/api/slides", files={"file": ("x.pdf", b"nope", "application/pdf")})
            assert bad.status_code == 400 and "readable PDF" in bad.json()["detail"]
            not_pdf = client.post("/api/slides", files={"file": ("x.txt", b"hi", "text/plain")})
            assert not_pdf.status_code == 400
    finally:  # the /decks mount is fixed at import time, so clean up the real folder
        for deck_id in made:
            shutil.rmtree(slides.DATA_DIR / deck_id, ignore_errors=True)
            slides._DECKS.pop(deck_id, None)
