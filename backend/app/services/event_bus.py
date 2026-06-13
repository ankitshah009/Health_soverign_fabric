"""In-memory event bus for near-instant SSE delivery.

Replaces the 300ms sleep-polling pattern in the SSE generator with
asyncio.Queue-based push delivery. Events are still persisted to the
database for audit trail and historical replay.

Architecture:
    Pipeline → push(claim_id, event) → asyncio.Queue (per claim)
    SSE endpoint → subscribe(claim_id) → yields from queue
    Pipeline → complete(claim_id) → signals end-of-stream
    TTL cleanup → abandoned queues destroyed after 5 min
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)

_COMPLETION_SENTINEL = object()
_QUEUE_TTL_SECONDS = 300  # 5 minutes — cleanup for crashed pipelines
_POST_COMPLETE_GRACE = 60  # 60 seconds after complete() before queue destruction


class _ClaimQueue:
    """Internal: a queue + metadata for one claim's event stream."""

    __slots__ = ("queue", "created_at", "completed_at")

    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict | object] = asyncio.Queue()
        self.created_at: float = time.monotonic()
        self.completed_at: float | None = None


class EventBus:
    """Push-based event delivery for claim pipeline SSE streams."""

    def __init__(self) -> None:
        self._queues: dict[str, _ClaimQueue] = {}
        self._cleanup_task: asyncio.Task | None = None

    def push(self, claim_id: str, event: dict) -> None:
        """Push an event to the claim's queue. Creates the queue if needed."""
        if claim_id not in self._queues:
            self._queues[claim_id] = _ClaimQueue()
            self._ensure_cleanup_running()
        self._queues[claim_id].queue.put_nowait(event)

    def complete(self, claim_id: str) -> None:
        """Signal that no more events will be pushed for this claim."""
        cq = self._queues.get(claim_id)
        if cq is not None:
            cq.completed_at = time.monotonic()
            cq.queue.put_nowait(_COMPLETION_SENTINEL)
            logger.debug("Event bus: claim %s marked complete", claim_id)

    async def subscribe(self, claim_id: str) -> AsyncIterator[dict]:
        """Yield events as they arrive. Blocks until next event or completion."""
        cq = self._queues.get(claim_id)
        if cq is None:
            return  # No active queue — caller should fall back to DB

        while True:
            try:
                item = await asyncio.wait_for(cq.queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                # Check if queue was abandoned
                if cq.completed_at is not None:
                    return
                continue

            if item is _COMPLETION_SENTINEL:
                return
            yield item  # type: ignore[misc]

    def has_active_queue(self, claim_id: str) -> bool:
        """Check if a claim has an active (non-completed) queue."""
        cq = self._queues.get(claim_id)
        return cq is not None and cq.completed_at is None

    def _ensure_cleanup_running(self) -> None:
        """Start the background cleanup task if not already running."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically remove abandoned and expired queues."""
        while self._queues:
            await asyncio.sleep(30)
            now = time.monotonic()
            to_remove = []
            for claim_id, cq in self._queues.items():
                # Remove queues that were completed > grace period ago
                if cq.completed_at and (now - cq.completed_at) > _POST_COMPLETE_GRACE:
                    to_remove.append(claim_id)
                # Remove queues that never completed but are > TTL old (crash safety)
                elif cq.completed_at is None and (now - cq.created_at) > _QUEUE_TTL_SECONDS:
                    logger.warning("Event bus: cleaning up abandoned queue for claim %s (%.0fs old)", claim_id, now - cq.created_at)
                    cq.queue.put_nowait(_COMPLETION_SENTINEL)
                    to_remove.append(claim_id)
            for claim_id in to_remove:
                del self._queues[claim_id]


# Module-level singleton
event_bus = EventBus()
