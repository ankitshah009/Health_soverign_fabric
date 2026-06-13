"""Unit tests for the shared HTTP client and LRU cache in grok_service.

Targets:
    - init_grok_client / close_grok_client / get_client lifecycle
    - _content_hash (SHA-256 determinism)
    - _cache_get / _cache_put (miss, hit, eviction at _CACHE_MAX_SIZE)

No real HTTP calls are made; httpx.AsyncClient is mocked throughout.
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Module-level import (after conftest patches DATABASE_PATH)
# ---------------------------------------------------------------------------
import app.services.grok_service as grok_mod
from app.services.grok_service import (
    _CACHE_MAX_SIZE,
    _cache_get,
    _cache_put,
    _content_hash,
    close_grok_client,
    get_client,
    init_grok_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_module_state() -> None:
    """Return the module globals to a clean state between tests."""
    grok_mod._client = None
    grok_mod._response_cache.clear()


# ---------------------------------------------------------------------------
# get_client() — raises before init
# ---------------------------------------------------------------------------


class TestGetClientBeforeInit:
    def setup_method(self) -> None:
        _reset_module_state()

    def test_get_client_raises_runtime_error_when_not_initialized(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_client()

    def test_get_client_error_message_mentions_init_function(self):
        with pytest.raises(RuntimeError, match="init_grok_client"):
            get_client()


# ---------------------------------------------------------------------------
# init_grok_client() — creates client
# ---------------------------------------------------------------------------


class TestInitGrokClient:
    def setup_method(self) -> None:
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_init_grok_client_sets_module_client(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()
        assert grok_mod._client is mock_client

    @pytest.mark.asyncio
    async def test_get_client_returns_client_after_init(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()
        assert get_client() is mock_client

    @pytest.mark.asyncio
    async def test_init_still_succeeds_when_warmup_request_fails(self):
        """A failing warm-up GET must not prevent the client from being created."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network down"))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()  # must not raise
        assert grok_mod._client is mock_client

    @pytest.mark.asyncio
    async def test_init_creates_async_client_with_correct_settings(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client) as mock_cls:
            await init_grok_client()
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args.kwargs
        assert "timeout" in call_kwargs
        assert "limits" in call_kwargs


# ---------------------------------------------------------------------------
# close_grok_client() — closes and nullifies
# ---------------------------------------------------------------------------


class TestCloseGrokClient:
    def setup_method(self) -> None:
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_close_grok_client_calls_aclose(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()
        await close_grok_client()
        mock_client.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_grok_client_nullifies_module_client(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()
        await close_grok_client()
        assert grok_mod._client is None

    @pytest.mark.asyncio
    async def test_get_client_raises_after_close(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=MagicMock(status_code=200))
        with patch("app.services.grok_service.httpx.AsyncClient", return_value=mock_client):
            await init_grok_client()
        await close_grok_client()
        with pytest.raises(RuntimeError):
            get_client()

    @pytest.mark.asyncio
    async def test_close_when_already_none_does_not_raise(self):
        _reset_module_state()  # _client already None
        await close_grok_client()  # must be silent


# ---------------------------------------------------------------------------
# _content_hash() — SHA-256 determinism
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_returns_hex_string(self):
        result = _content_hash(b"hello")
        assert isinstance(result, str)
        assert all(c in "0123456789abcdef" for c in result)

    def test_correct_length_for_sha256(self):
        result = _content_hash(b"hello")
        assert len(result) == 64

    def test_same_bytes_produce_same_hash(self):
        data = b"insurance claim document bytes"
        assert _content_hash(data) == _content_hash(data)

    def test_different_bytes_produce_different_hashes(self):
        assert _content_hash(b"aaa") != _content_hash(b"bbb")

    def test_hash_matches_stdlib_sha256(self):
        data = b"test payload for hashing"
        expected = hashlib.sha256(data).hexdigest()
        assert _content_hash(data) == expected

    def test_empty_bytes_produce_valid_hash(self):
        result = _content_hash(b"")
        assert len(result) == 64

    def test_large_payload_produces_valid_hash(self):
        data = b"x" * 100_000
        result = _content_hash(data)
        assert len(result) == 64


# ---------------------------------------------------------------------------
# _cache_get() — miss returns None
# ---------------------------------------------------------------------------


class TestCacheGet:
    def setup_method(self) -> None:
        grok_mod._response_cache.clear()

    def test_cache_get_returns_none_for_unknown_key(self):
        assert _cache_get("nonexistent-key") is None

    def test_cache_get_returns_none_after_clear(self):
        grok_mod._response_cache["some-key"] = {"data": 1}
        grok_mod._response_cache.clear()
        assert _cache_get("some-key") is None


# ---------------------------------------------------------------------------
# _cache_put() — store and retrieve
# ---------------------------------------------------------------------------


class TestCachePut:
    def setup_method(self) -> None:
        grok_mod._response_cache.clear()

    def test_cache_put_stores_value(self):
        _cache_put("key-001", {"result": "ok"})
        assert grok_mod._response_cache["key-001"] == {"result": "ok"}

    def test_cache_get_returns_stored_value_after_put(self):
        payload = {"damage_type": "fire", "estimated_cost": 5000.0}
        _cache_put("key-002", payload)
        assert _cache_get("key-002") == payload

    def test_cache_put_overwrites_existing_key(self):
        _cache_put("key-003", {"v": 1})
        _cache_put("key-003", {"v": 2})
        assert _cache_get("key-003") == {"v": 2}

    def test_cache_stores_multiple_independent_keys(self):
        _cache_put("k1", {"a": 1})
        _cache_put("k2", {"b": 2})
        assert _cache_get("k1") == {"a": 1}
        assert _cache_get("k2") == {"b": 2}


# ---------------------------------------------------------------------------
# _cache_put() — LRU eviction at _CACHE_MAX_SIZE
# ---------------------------------------------------------------------------


class TestCacheEviction:
    def setup_method(self) -> None:
        grok_mod._response_cache.clear()

    def test_cache_size_does_not_exceed_max(self):
        for i in range(_CACHE_MAX_SIZE + 5):
            _cache_put(f"key-{i:04d}", {"index": i})
        assert len(grok_mod._response_cache) == _CACHE_MAX_SIZE

    def test_oldest_key_is_evicted_when_at_capacity(self):
        # Fill to capacity
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"key-{i:04d}", {"index": i})

        # The first key inserted should still be present
        assert _cache_get("key-0000") is not None

        # Insert one more — this must evict key-0000 (the oldest)
        _cache_put("key-new", {"index": _CACHE_MAX_SIZE})
        assert _cache_get("key-0000") is None

    def test_newest_key_survives_after_eviction(self):
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"key-{i:04d}", {"index": i})
        _cache_put("key-latest", {"index": 9999})
        assert _cache_get("key-latest") == {"index": 9999}

    def test_second_oldest_key_survives_single_eviction(self):
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"key-{i:04d}", {"index": i})
        # key-0001 is the second oldest — one eviction should leave it intact
        _cache_put("key-trigger", {"index": -1})
        assert _cache_get("key-0001") is not None

    def test_cache_max_size_constant_matches_actual_limit(self):
        assert _CACHE_MAX_SIZE == 100

    def test_sequential_evictions_drain_oldest_keys_first(self):
        for i in range(_CACHE_MAX_SIZE):
            _cache_put(f"base-{i:04d}", {"index": i})

        # Insert 10 more — the 10 oldest base-* keys should be evicted
        for i in range(10):
            _cache_put(f"extra-{i:04d}", {"extra": True})

        for i in range(10):
            assert _cache_get(f"base-{i:04d}") is None, f"base-{i:04d} should have been evicted"

        for i in range(10, _CACHE_MAX_SIZE):
            assert _cache_get(f"base-{i:04d}") is not None, f"base-{i:04d} should still be present"
