import pytest

from backend.services import reasoning_budget as budget
from backend.services.voice_higgs import SpendCounter


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    for name in ("REQUESTS", "UNKNOWN_USAGE", "INPUT_TOKENS", "OUTPUT_TOKENS", "CACHED_TOKENS"):
        monkeypatch.setattr(budget, name, 0)
    for name in ("tts_chars", "realtime_ms", "reasoning_estimate_usd"):
        monkeypatch.setattr(SpendCounter, name, 0)
    monkeypatch.setenv("BOSON_SPEND_CARRYOVER_USD", "0")
    monkeypatch.setenv("SPEND_SOFT_CAP_USD", "60")
    monkeypatch.setenv("BOSON_REASONING_MAX_REQUESTS", "2")


def test_reservations_share_the_voice_spend_limit_and_request_cap(monkeypatch):
    assert budget.reserve_request(2000, 768)
    assert budget.reserve_request(2000, 768)
    before = SpendCounter.estimate_usd()
    assert not budget.reserve_request(2000, 768)
    assert SpendCounter.estimate_usd() == before
    monkeypatch.setenv("BOSON_REASONING_MAX_REQUESTS", "10")
    monkeypatch.setenv("SPEND_SOFT_CAP_USD", str(before + .00001))
    assert not budget.reserve_request(2000, 768)


def test_unknown_usage_is_not_zero_and_reservation_survives(monkeypatch):
    assert budget.reserve_request(2000, 768)
    before = SpendCounter.estimate_usd()
    budget.record_usage(None)
    budget.record_usage({"input_tokens": -1, "output_tokens": 0})
    assert budget.diagnostics()["unknown_usage_requests"] == 2
    assert SpendCounter.estimate_usd() == before
    monkeypatch.setenv("BOSON_SPEND_CARRYOVER_USD", "1.25")
    assert SpendCounter.estimate_usd() == before + 1.25


def test_reported_tokens_and_cache_discount_are_kept_separate_from_reservations():
    budget.record_usage({"input_tokens": 1000, "output_tokens": 200,
                         "input_token_details": {"cached_tokens": 400}})
    got = budget.diagnostics()
    assert got["input_tokens"] == 1000 and got["output_tokens"] == 200
    assert got["cached_input_tokens"] == 400
    assert got["reported_token_cost_usd"] == .00145
    assert got["reserved_estimate_usd"] == 0
