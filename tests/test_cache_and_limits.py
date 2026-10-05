from rag_service.cache import InMemoryCache, RedisCache, cache_key, cache_namespace
from rag_service.pricing import cost_usd
from rag_service.rate_limit import RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_key_normalizes_whitespace_case_and_punctuation():
    assert cache_key("Can I deploy on Friday?", "ns") == cache_key(
        "  can i   deploy on friday ", "ns"
    )
    assert cache_key("q", "ns1") != cache_key("q", "ns2")


def test_cache_namespace_changes_with_any_part():
    base = cache_namespace("corpus-v1", "anthropic|claude-opus-5-5|effort=medium", "top_k=4")
    assert base == cache_namespace(
        "corpus-v1", "anthropic|claude-opus-5-5|effort=medium", "top_k=4"
    )
    assert base != cache_namespace(
        "corpus-v2", "anthropic|claude-opus-5-5|effort=medium", "top_k=4"
    )
    assert base != cache_namespace("corpus-v1", "anthropic|claude-opus-5-5|effort=low", "top_k=4")
    assert base != cache_namespace(
        "corpus-v1", "anthropic|claude-opus-5-5|effort=medium", "top_k=6"
    )


def test_in_memory_cache_expires_entries():
    clock = FakeClock()
    cache = InMemoryCache(ttl_seconds=10, clock=clock)
    cache.set("k", {"a": 1})
    assert cache.get("k") == {"a": 1}
    clock.now = 10
    assert cache.get("k") is None


def test_in_memory_cache_evicts_least_recently_used():
    cache = InMemoryCache(max_entries=2)
    cache.set("a", {})
    cache.set("b", {})
    cache.get("a")
    cache.set("c", {})
    assert cache.get("b") is None
    assert cache.get("a") == {}


def test_redis_cache_round_trip():
    class FakeRedis:
        def __init__(self) -> None:
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value.encode()

    cache = RedisCache(FakeRedis(), ttl_seconds=60)
    cache.set("k", {"answer": "yes"})
    assert cache.get("k") == {"answer": "yes"}
    assert cache.get("missing") is None


def test_rate_limiter_blocks_then_refills():
    clock = FakeClock()
    limiter = RateLimiter(per_minute=2, clock=clock)
    assert limiter.check("a") == (True, 0.0)
    assert limiter.check("a") == (True, 0.0)
    allowed, retry_after = limiter.check("a")
    assert not allowed
    assert retry_after == 30.0
    assert limiter.check("b")[0], "limits are per client"
    clock.now = 30
    assert limiter.check("a")[0]


def test_cost_calculation():
    # 2,000 input tokens at $4/MTok + 300 output tokens at $20/MTok
    assert cost_usd("claude-opus-5-5", 2000, 300) == 0.014
    assert cost_usd("claude-opus-5-5", 0, 0, cache_read_tokens=1_000_000) == 0.2
    assert cost_usd("unknown-model", 100, 100) is None
