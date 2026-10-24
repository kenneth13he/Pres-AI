"""Conservative request reservations against the existing shared Boson spending guard.

Reported token usage is recorded separately. The reservation is deliberately not refunded:
disconnections can hide final usage. It is a planning estimate, not a billing statement.
"""
from __future__ import annotations

import os
from typing import Any

from .voice_higgs import SpendCounter

REQUESTS = 0
UNKNOWN_USAGE = 0
INPUT_TOKENS = 0
OUTPUT_TOKENS = 0
CACHED_TOKENS = 0


def reserve_request(input_bytes: int, max_output_tokens: int) -> bool:
    global REQUESTS
    # UTF-8 bytes plus a generous system/context allowance bound a short text request.
    reserve = ((max(0, input_bytes) + 4096) * 0.75 + max(0, max_output_tokens) * 4.50) / 1e6
    cap = float(os.environ.get("SPEND_SOFT_CAP_USD", "60"))
    if (REQUESTS >= int(os.environ.get("BOSON_REASONING_MAX_REQUESTS", "200"))
            or SpendCounter.estimate_usd() + reserve > cap):
        return False
    REQUESTS += 1
    SpendCounter.reasoning_estimate_usd += reserve
    return True


def record_usage(usage: dict[str, Any] | None) -> None:
    global UNKNOWN_USAGE, INPUT_TOKENS, OUTPUT_TOKENS, CACHED_TOKENS
    if not isinstance(usage, dict):
        UNKNOWN_USAGE += 1
        return
    input_count, output_count = usage.get("input_tokens"), usage.get("output_tokens")
    if (not isinstance(input_count, int) or not isinstance(output_count, int)
            or input_count < 0 or output_count < 0):
        UNKNOWN_USAGE += 1
        return
    INPUT_TOKENS += input_count
    OUTPUT_TOKENS += output_count
    details = usage.get("input_token_details") or {}
    cached = details.get("cached_tokens") if isinstance(details, dict) else None
    if isinstance(cached, int) and 0 <= cached <= input_count:
        CACHED_TOKENS += cached


def diagnostics() -> dict[str, Any]:
    return {"requests_reserved": REQUESTS, "unknown_usage_requests": UNKNOWN_USAGE,
            "input_tokens": INPUT_TOKENS, "output_tokens": OUTPUT_TOKENS,
            "cached_input_tokens": CACHED_TOKENS,
            "reserved_estimate_usd": round(SpendCounter.reasoning_estimate_usd, 6),
            "reported_token_cost_usd": round(
                ((INPUT_TOKENS - CACHED_TOKENS) * .75 + CACHED_TOKENS * .25
                 + OUTPUT_TOKENS * 4.50) / 1e6, 6)}
