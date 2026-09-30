"""Per-request cost accounting.

Prices are USD per million tokens (Anthropic first-party API, September 2026).
Check https://www.anthropic.com/pricing before relying on them for budgeting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        # 5-minute cache writes are billed at 1.25x the input price.
        return self.input * 1.25


PRICES_PER_MTOK: dict[str, Price] = {
    "claude-opus-5-5": Price(input=4.00, output=20.00, cache_read=0.20),
    "claude-sonnet-5-5": Price(input=2.00, output=10.00, cache_read=0.20),
    "claude-haiku-4-5": Price(input=1.00, output=5.00, cache_read=0.10),
}


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Return the request cost in USD, or ``None`` if the model has no known price."""
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * price.cache_write
    )
    return round(total / 1_000_000, 6)
