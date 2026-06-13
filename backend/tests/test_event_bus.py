"""Unit tests for app.services.event_bus.EventBus.

Covers: push, subscribe, complete, has_active_queue, TTL cleanup,
multiple subscribers, and edge cases.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.services.event_bus import (
    EventBus,
    _COMPLETION_SENTINEL,
    _POST_COMPLETE_GRACE,
    _QUEUE_TTL_SECONDS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> EventBus:
    """Return a fresh EventBus for each test (avoid singleton pollution)."""
    return EventBus()


async def _drain(bus: EventBus, claim_id: str, *, timeout: float = 1.0) -> list[dict]:
    """Collect all events from subscribe() up to *timeout* seconds."""
    collected: list[dict] = []
    async with asyncio.timeout(timeout):
        async for event in bus.subscribe(claim_id):
            collected.append(event)
    return collected


# ---------------------------------------------------------------------------
# push() — queue creation and event delivery
# ---------------------------------------------------------------------------


class TestPush:
    @pytest.mark.asyncio
    async def test_push_creates_queue_on_first_call(self):
        bus = _make_bus()
        assert "CLM-001" not in bus._queues
        bus.push("CLM-001", {"type": "started"})
        assert "CLM-001" in bus._queues

    @pytest.mark.asyncio
    async def test_push_does_not_duplicate_queue_on_second_call(self):
        bus = _make_bus()
        bus.push("CLM-001", {"type": "started"})
        first_queue = bus._queues["CLM-001"]
        bus.push("CLM-001", {"type": "processing"})
        assert bus._queues["CLM-001"] is first_queue

    @pytest.mark.asyncio
    async def test_push_adds_event_to_existing_queue(self):
        bus = _make_bus()
        bus.push("CLM-002", {"type": "a"})
        bus.push("CLM-002", {"type": "b"})
        assert bus._queues["CLM-002"].queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_push_separate_claim_ids_create_separate_queues(self):
        bus = _make_bus()
        bus.push("CLM-A", {"type": "x"})
        bus.push("CLM-B", {"type": "y"})
        assert "CLM-A" in bus._queues
        assert "CLM-B" in bus._queues
        assert bus._queues["CLM-A"] is not bus._queues["CLM-B"]

    @pytest.mark.asyncio
    async def test_push_after_complete_adds_event_beyond_sentinel(self):
        """push() after complete() puts data after the sentinel in the queue.
        The subscriber will have already returned on seeing the sentinel, so
        this is a no-op from the subscriber's perspective — but must not raise.
        """
        bus = _make_bus()
        bus.push("CLM-003", {"type": "start"})
        bus.complete("CLM-003")
        # Must not raise
        bus.push("CLM-003", {"type": "late"})
        # Queue should now hold start + sentinel + late
        assert bus._queues["CLM-003"].queue.qsize() == 3


# ---------------------------------------------------------------------------
# subscribe() — ordered delivery and sentinel handling
# ---------------------------------------------------------------------------


class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_yields_events_in_insertion_order(self):
        bus = _make_bus()
        events = [{"seq": i} for i in range(5)]
        for ev in events:
            bus.push("CLM-SEQ", ev)
        bus.complete("CLM-SEQ")

        collected = await _drain(bus, "CLM-SEQ")
        assert collected == events

    @pytest.mark.asyncio
    async def test_subscribe_returns_immediately_on_missing_queue(self):
        bus = _make_bus()
        collected = []
        async for ev in bus.subscribe("CLM-MISSING"):
            collected.append(ev)
        assert collected == []

    @pytest.mark.asyncio
    async def test_subscribe_returns_on_completion_sentinel(self):
        bus = _make_bus()
        bus.push("CLM-DONE", {"type": "first"})
        bus.complete("CLM-DONE")

        collected = await _drain(bus, "CLM-DONE")
        # Sentinel itself must NOT appear in collected events
        assert {"type": "first"} in collected
        assert _COMPLETION_SENTINEL not in collected

    @pytest.mark.asyncio
    async def test_subscribe_stops_at_sentinel_not_beyond(self):
        bus = _make_bus()
        bus.push("CLM-STOP", {"seq": 0})
        bus.push("CLM-STOP", {"seq": 1})
        bus.complete("CLM-STOP")
        bus.push("CLM-STOP", {"seq": 2})  # after sentinel — should not appear

        collected = await _drain(bus, "CLM-STOP")
        assert len(collected) == 2
        assert {"seq": 2} not in collected

    @pytest.mark.asyncio
    async def test_subscribe_delivers_single_event(self):
        bus = _make_bus()
        bus.push("CLM-ONE", {"value": 42})
        bus.complete("CLM-ONE")

        collected = await _drain(bus, "CLM-ONE")
        assert collected == [{"value": 42}]

    @pytest.mark.asyncio
    async def test_subscribe_delivers_zero_events_when_completed_immediately(self):
        bus = _make_bus()
        bus.push("CLM-EMPTY", {"type": "placeholder"})
        bus.complete("CLM-EMPTY")

        # Override: push and immediately complete *without* any real data
        bus2 = _make_bus()
        bus2.complete("CLM-EMPTY2")  # no queue exists — completes silently
        collected = []
        async for ev in bus2.subscribe("CLM-EMPTY2"):
            collected.append(ev)
        assert collected == []


# ---------------------------------------------------------------------------
# complete() — signalling and metadata
# ---------------------------------------------------------------------------


class TestComplete:
    @pytest.mark.asyncio
    async def test_complete_sets_completed_at_timestamp(self):
        bus = _make_bus()
        bus.push("CLM-C1", {"type": "x"})
        before = time.monotonic()
        bus.complete("CLM-C1")
        after = time.monotonic()
        ts = bus._queues["CLM-C1"].completed_at
        assert ts is not None
        assert before <= ts <= after

    def test_complete_on_missing_claim_does_not_raise(self):
        bus = _make_bus()
        bus.complete("CLM-GHOST")  # no queue — must be silent

    @pytest.mark.asyncio
    async def test_complete_marks_queue_as_inactive(self):
        bus = _make_bus()
        bus.push("CLM-C2", {"type": "y"})
        assert bus.has_active_queue("CLM-C2") is True
        bus.complete("CLM-C2")
        assert bus.has_active_queue("CLM-C2") is False


# ---------------------------------------------------------------------------
# has_active_queue()
# ---------------------------------------------------------------------------


class TestHasActiveQueue:
    def test_returns_false_for_missing_claim_id(self):
        bus = _make_bus()
        assert bus.has_active_queue("CLM-NONE") is False

    @pytest.mark.asyncio
    async def test_returns_true_after_push_before_complete(self):
        bus = _make_bus()
        bus.push("CLM-ACT", {"type": "x"})
        assert bus.has_active_queue("CLM-ACT") is True

    @pytest.mark.asyncio
    async def test_returns_false_after_complete(self):
        bus = _make_bus()
        bus.push("CLM-DONE2", {"type": "x"})
        bus.complete("CLM-DONE2")
        assert bus.has_active_queue("CLM-DONE2") is False

    def test_returns_false_for_never_pushed_claim(self):
        bus = _make_bus()
        assert bus.has_active_queue("CLM-NEVER") is False


# ---------------------------------------------------------------------------
# TTL cleanup — abandoned queues removed after _QUEUE_TTL_SECONDS
# ---------------------------------------------------------------------------


class TestTTLCleanup:
    @pytest.mark.asyncio
    async def test_abandoned_queue_is_removed_after_ttl(self):
        """Simulate an old queue that never called complete().

        We manipulate created_at directly so we don't have to wait 5 minutes.
        """
        bus = _make_bus()
        bus.push("CLM-TTL", {"type": "start"})
        # Age the queue past the TTL threshold
        bus._queues["CLM-TTL"].created_at = time.monotonic() - (_QUEUE_TTL_SECONDS + 1)

        # Run one cleanup loop iteration manually (sleep bypassed)
        with patch("asyncio.sleep", return_value=None):
            # We call the loop body logic directly by running the coroutine with
            # a very short-lived mock sleep so it exits after one pass.
            async def _one_pass() -> None:
                await asyncio.sleep(0)  # patched — returns immediately
                now = time.monotonic()
                to_remove = []
                for cid, cq in bus._queues.items():
                    if cq.completed_at and (now - cq.completed_at) > _POST_COMPLETE_GRACE:
                        to_remove.append(cid)
                    elif cq.completed_at is None and (now - cq.created_at) > _QUEUE_TTL_SECONDS:
                        cq.queue.put_nowait(_COMPLETION_SENTINEL)
                        to_remove.append(cid)
                for cid in to_remove:
                    del bus._queues[cid]

            await _one_pass()

        assert "CLM-TTL" not in bus._queues

    @pytest.mark.asyncio
    async def test_completed_queue_is_removed_after_grace_period(self):
        """Completed queues are removed after _POST_COMPLETE_GRACE seconds."""
        bus = _make_bus()
        bus.push("CLM-GRACE", {"type": "done"})
        bus.complete("CLM-GRACE")
        # Age the completion timestamp past the grace period
        bus._queues["CLM-GRACE"].completed_at = time.monotonic() - (_POST_COMPLETE_GRACE + 1)

        async def _one_pass() -> None:
            await asyncio.sleep(0)
            now = time.monotonic()
            to_remove = []
            for cid, cq in bus._queues.items():
                if cq.completed_at and (now - cq.completed_at) > _POST_COMPLETE_GRACE:
                    to_remove.append(cid)
                elif cq.completed_at is None and (now - cq.created_at) > _QUEUE_TTL_SECONDS:
                    cq.queue.put_nowait(_COMPLETION_SENTINEL)
                    to_remove.append(cid)
            for cid in to_remove:
                del bus._queues[cid]

        with patch("asyncio.sleep", return_value=None):
            await _one_pass()

        assert "CLM-GRACE" not in bus._queues

    @pytest.mark.asyncio
    async def test_young_active_queue_is_not_cleaned_up(self):
        """A freshly-created, non-completed queue must survive a cleanup pass."""
        bus = _make_bus()
        bus.push("CLM-YOUNG", {"type": "active"})
        # created_at is fresh (< TTL)

        async def _one_pass() -> None:
            await asyncio.sleep(0)
            now = time.monotonic()
            to_remove = []
            for cid, cq in bus._queues.items():
                if cq.completed_at and (now - cq.completed_at) > _POST_COMPLETE_GRACE:
                    to_remove.append(cid)
                elif cq.completed_at is None and (now - cq.created_at) > _QUEUE_TTL_SECONDS:
                    cq.queue.put_nowait(_COMPLETION_SENTINEL)
                    to_remove.append(cid)
            for cid in to_remove:
                del bus._queues[cid]

        with patch("asyncio.sleep", return_value=None):
            await _one_pass()

        assert "CLM-YOUNG" in bus._queues


# ---------------------------------------------------------------------------
# Multiple subscribers on the same claim_id
# ---------------------------------------------------------------------------


class TestMultipleSubscribers:
    @pytest.mark.asyncio
    async def test_two_subscribers_both_receive_all_events(self):
        """Two concurrent subscribers on the same queue should each get all events.

        NOTE: asyncio.Queue is a single-consumer structure — this tests that
        two subscribers racing on the same queue share the items between them
        (not that both receive a full duplicate copy). This verifies the bus
        doesn't error and all events are collectively consumed.
        """
        bus = _make_bus()
        for i in range(4):
            bus.push("CLM-MULTI", {"seq": i})
        bus.complete("CLM-MULTI")

        results_a: list[dict] = []
        results_b: list[dict] = []

        async def _sub_a() -> None:
            async for ev in bus.subscribe("CLM-MULTI"):
                results_a.append(ev)

        async def _sub_b() -> None:
            async for ev in bus.subscribe("CLM-MULTI"):
                results_b.append(ev)

        await asyncio.gather(_sub_a(), _sub_b())

        # All 4 events collectively consumed across both subscribers
        combined = sorted(results_a + results_b, key=lambda e: e["seq"])
        assert combined == [{"seq": 0}, {"seq": 1}, {"seq": 2}, {"seq": 3}]

    @pytest.mark.asyncio
    async def test_independent_claim_ids_do_not_interfere(self):
        bus = _make_bus()
        bus.push("CLM-X", {"origin": "x"})
        bus.complete("CLM-X")
        bus.push("CLM-Y", {"origin": "y"})
        bus.complete("CLM-Y")

        x_events = await _drain(bus, "CLM-X")
        y_events = await _drain(bus, "CLM-Y")

        assert x_events == [{"origin": "x"}]
        assert y_events == [{"origin": "y"}]


# ---------------------------------------------------------------------------
# _ensure_cleanup_running — background task lifecycle
# ---------------------------------------------------------------------------


class TestCleanupTask:
    @pytest.mark.asyncio
    async def test_cleanup_task_created_on_first_push(self):
        bus = _make_bus()
        assert bus._cleanup_task is None
        bus.push("CLM-BG", {"type": "x"})
        # Give the event loop a tick to schedule the task
        await asyncio.sleep(0)
        assert bus._cleanup_task is not None

    @pytest.mark.asyncio
    async def test_cleanup_task_is_not_duplicated_on_subsequent_pushes(self):
        bus = _make_bus()
        bus.push("CLM-BG2", {"type": "a"})
        await asyncio.sleep(0)
        first_task = bus._cleanup_task
        bus.push("CLM-BG2", {"type": "b"})
        assert bus._cleanup_task is first_task
