"""Yutori API service — web research for entity verification.

Yutori API docs: https://docs.yutori.com
- POST /v1/research/tasks  → creates a research task (async, returns task_id)
- GET  /v1/research/tasks/{task_id} → polls for results
- POST /v1/browse/tasks    → creates a browsing task (AI agent navigates websites)
- GET  /v1/browse/tasks/{task_id} → polls for browsing results
Auth: X-API-Key header
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import YUTORI_API_KEY, YUTORI_BASE_URL
from app.models.claim import ExtractedData

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_POOL_TIMEOUT = httpx.Timeout(60.0, connect=10.0, pool=5.0)

# Adaptive polling: 500ms, 1s, 2s, 4s, 4s, 4s, ... (cap at 4s)
_POLL_INITIAL = 0.5
_POLL_MAX = 4.0
_MAX_POLL_TIME = 60.0  # total polling budget (outer wait_for is 20s anyway)

# ── Shared HTTP client ───────────────────────────────────────────────────────
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared Yutori HTTP client."""
    if _client is None:
        raise RuntimeError("Yutori HTTP client not initialized. Call init_yutori_client() first.")
    return _client


async def init_yutori_client() -> None:
    """Create the shared HTTP client with connection pooling."""
    global _client
    _client = httpx.AsyncClient(timeout=_POOL_TIMEOUT, limits=_LIMITS)
    # Warm the connection pool
    try:
        await _client.get(f"{YUTORI_BASE_URL}/health", headers=_headers())
        logger.info("Yutori HTTP client initialized and connection warmed")
    except Exception:
        logger.info("Yutori HTTP client initialized (warm-up failed — non-blocking)")


async def close_yutori_client() -> None:
    """Close the shared HTTP client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Yutori HTTP client closed")


def _headers() -> dict[str, str]:
    return {
        "X-API-Key": YUTORI_API_KEY,
        "Content-Type": "application/json",
    }


class YutoriService:
    """Async service for Yutori web research API."""

    def _verification_vectors(
        self,
        extracted_data: ExtractedData,
        claimant_name: str,
        incident_description: str = "",
    ) -> list[dict[str, str]]:
        """Build the SIU research vectors used for claim verification."""
        vectors: list[dict[str, str]] = [
            {
                "entity_name": claimant_name,
                "entity_type": "claimant_history",
                "context": (
                    f"Search for prior insurance claims, lawsuits, or fraud allegations involving '{claimant_name}'. "
                    f"Check court records, news articles, and public litigation databases. "
                    f"Report any history of multiple claims, suspicious patterns, or known fraud involvement."
                ),
            },
            {
                "entity_name": extracted_data.damage_type or "claim repair",
                "entity_type": "repair_provider",
                "context": (
                    f"Investigate the legitimacy of auto repair or service providers related to this claim. "
                    f"Claim details: '{extracted_data.damage_type}', estimated cost ${extracted_data.estimated_cost:,.0f}. "
                    f"Check BBB ratings, Yelp reviews, complaints, and any known associations with fraud rings or inflated estimates."
                ),
            },
            {
                "entity_name": claimant_name,
                "entity_type": "financial_stress",
                "context": (
                    f"Search for public indicators of financial distress for '{claimant_name}'. "
                    f"Check for bankruptcy filings, foreclosure notices, debt collection lawsuits, "
                    f"or other financial pressure that might motivate insurance fraud."
                ),
            },
        ]

        vehicle_or_property = extracted_data.vehicle_info or extracted_data.damage_type
        if vehicle_or_property:
            vectors.insert(
                1,
                {
                    "entity_name": vehicle_or_property,
                    "entity_type": "vehicle_property",
                    "context": (
                        f"Verify the vehicle/property described as '{vehicle_or_property}'. "
                        f"Check for salvage title history, prior total loss, stolen vehicle reports, "
                        f"or property liens. Search VIN databases and public records."
                    ),
                },
            )

        incident_text = incident_description or extracted_data.incident_details or ""
        if incident_text:
            vectors.insert(
                2,
                {
                    "entity_name": incident_text[:100],
                    "entity_type": "incident_corroboration",
                    "context": (
                        f"Verify the following insurance claim incident: '{incident_text[:200]}'. "
                        f"Check for matching police reports, weather conditions at the time, "
                        f"traffic camera data, or news coverage that corroborates or contradicts the claim."
                    ),
                },
            )

        return vectors

    def pending_verification_results(
        self,
        extracted_data: ExtractedData,
        claimant_name: str,
        incident_description: str = "",
        *,
        summary: str = "Research in progress — results pending.",
    ) -> list[dict[str, Any]]:
        """Return placeholder results for vectors that have not completed yet."""
        return [
            {
                "entity_name": vector["entity_name"],
                "entity_type": vector["entity_type"],
                "status": "verification_pending",
                "results": {"summary": summary},
            }
            for vector in self._verification_vectors(
                extracted_data,
                claimant_name,
                incident_description=incident_description,
            )
        ]

    async def research_entity(
        self,
        entity_name: str,
        entity_type: str,
        context: str,
    ) -> dict[str, Any]:
        """Research a single entity (person, business, address) via Yutori.

        Flow: POST to create task → poll GET for results → return.
        """
        query = (
            f"Investigate {entity_type} '{entity_name}' in the context of "
            f"an insurance claim. {context}. "
            f"Determine if this entity is legitimate, check for any fraud indicators, "
            f"and assess credibility."
        )

        body: dict[str, Any] = {
            "query": query,
        }

        try:
            client = get_client()

            # Step 1: Create the research task
            resp = await client.post(
                f"{YUTORI_BASE_URL}/research/tasks",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            task_data = resp.json()
            task_id = task_data.get("task_id")

            if not task_id:
                logger.warning("Yutori returned no task_id for %s", entity_name)
                return {
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "status": "completed",
                    "results": task_data,
                }

            logger.info("Yutori research task created: %s for %s", task_id, entity_name)

            # Step 2: Adaptive polling (500ms → 1s → 2s → 4s cap)
            poll_interval = _POLL_INITIAL
            elapsed = 0.0
            poll_count = 0
            while elapsed < _MAX_POLL_TIME:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                poll_count += 1

                poll_resp = await client.get(
                    f"{YUTORI_BASE_URL}/research/tasks/{task_id}",
                    headers=_headers(),
                )
                poll_resp.raise_for_status()
                result = poll_resp.json()
                status = result.get("status", "")

                if status in ("succeeded", "completed"):
                    logger.info("Yutori research completed for %s (polls=%d, %.1fs)", entity_name, poll_count, elapsed)
                    return {
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "status": "completed",
                        "results": result,
                    }
                elif status == "failed":
                    logger.warning("Yutori research failed for %s: %s", entity_name, result)
                    return {
                        "entity_name": entity_name,
                        "entity_type": entity_type,
                        "status": "verification_pending",
                        "results": {"summary": f"Research task failed: {result.get('error', 'unknown')}"},
                    }

                # Exponential backoff, capped at _POLL_MAX
                poll_interval = min(poll_interval * 2, _POLL_MAX)

            # Timed out polling
            logger.warning("Yutori research timed out for %s after %d polls (%.1fs)", entity_name, poll_count, elapsed)
            return {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "status": "verification_pending",
                "results": {"summary": "Research in progress — results pending."},
            }

        except httpx.PoolTimeout as exc:
            logger.error("Yutori API pool exhausted for %s: %s", entity_name, exc)
            return {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "status": "verification_pending",
                "results": {"summary": "Verification pending — connection pool exhausted."},
            }
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Yutori API HTTP error for %s: %s %s",
                entity_name, exc.response.status_code, exc.response.text[:200],
            )
            return {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "status": "verification_pending",
                "results": {
                    "summary": f"Verification pending — API returned status {exc.response.status_code}."
                },
            }
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            logger.warning("Yutori API timeout for %s: %s", entity_name, exc)
            return {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "status": "verification_pending",
                "results": {"summary": "Verification pending — request timed out."},
            }
        except Exception as exc:
            logger.error("Yutori API unexpected error for %s: %s", entity_name, exc)
            return {
                "entity_name": entity_name,
                "entity_type": entity_type,
                "status": "verification_pending",
                "results": {"summary": f"Verification pending — error: {exc}"},
            }

    async def verify_claim_entities(
        self,
        extracted_data: ExtractedData,
        claimant_name: str,
        incident_description: str = "",
    ) -> list[dict[str, Any]]:
        """Run 5 targeted SIU research vectors in parallel to verify claim entities."""
        tasks: list[asyncio.Task[dict[str, Any]]] = []
        for vector in self._verification_vectors(
            extracted_data,
            claimant_name,
            incident_description=incident_description,
        ):
            tasks.append(
                asyncio.create_task(
                    self.research_entity(
                        entity_name=vector["entity_name"],
                        entity_type=vector["entity_type"],
                        context=vector["context"],
                    )
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        verified: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Entity verification task failed: %s", r)
                verified.append({
                    "entity_name": "unknown",
                    "entity_type": "unknown",
                    "status": "verification_pending",
                    "results": {"summary": f"Verification failed: {r}"},
                })
            else:
                verified.append(r)

        return verified

    # ── Browsing API ──────────────────────────────────────────────────────────

    async def browse_and_verify(
        self,
        instruction: str,
        context: str = "",
    ) -> dict[str, Any]:
        """Use Yutori Browsing API to navigate a website and extract data.

        The Browsing API sends an AI agent to actually navigate websites,
        click buttons, fill forms, and extract structured data.

        Flow: POST /browse/tasks → poll GET /browse/tasks/{task_id} → return.
        """
        body: dict[str, Any] = {"instruction": instruction}

        try:
            client = get_client()

            # Step 1: Create the browsing task
            resp = await client.post(
                f"{YUTORI_BASE_URL}/browse/tasks",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            task_data = resp.json()
            task_id = task_data.get("task_id")

            if not task_id:
                logger.warning("Yutori browse returned no task_id for instruction: %s", instruction[:80])
                return {
                    "instruction": instruction[:120],
                    "status": "completed",
                    "results": task_data,
                }

            logger.info("Yutori browse task created: %s", task_id)

            # Step 2: Adaptive polling
            poll_interval = _POLL_INITIAL
            elapsed = 0.0
            poll_count = 0
            while elapsed < _MAX_POLL_TIME:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval
                poll_count += 1

                poll_resp = await client.get(
                    f"{YUTORI_BASE_URL}/browse/tasks/{task_id}",
                    headers=_headers(),
                )
                poll_resp.raise_for_status()
                result = poll_resp.json()
                status = result.get("status", "")

                if status in ("succeeded", "completed"):
                    logger.info("Yutori browse completed (polls=%d, %.1fs)", poll_count, elapsed)
                    return {
                        "instruction": instruction[:120],
                        "status": "completed",
                        "results": result,
                    }
                elif status == "failed":
                    logger.warning("Yutori browse task failed: %s", result)
                    return {
                        "instruction": instruction[:120],
                        "status": "verification_pending",
                        "results": {"summary": f"Browse task failed: {result.get('error', 'unknown')}"},
                    }

                poll_interval = min(poll_interval * 2, _POLL_MAX)

            # Timed out polling
            logger.warning("Yutori browse timed out after %d polls (%.1fs)", poll_count, elapsed)
            return {
                "instruction": instruction[:120],
                "status": "verification_pending",
                "results": {"summary": "Browsing in progress — results pending."},
            }

        except httpx.PoolTimeout as exc:
            logger.error("Yutori Browse API pool exhausted: %s", exc)
            return {
                "instruction": instruction[:120],
                "status": "verification_pending",
                "results": {"summary": "Browse verification pending — connection pool exhausted."},
            }
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code == 404:
                logger.warning(
                    "Yutori Browsing API not available (404). "
                    "Endpoint /browse/tasks may not exist — skipping."
                )
            else:
                logger.warning(
                    "Yutori Browse API HTTP error: %s %s",
                    status_code, exc.response.text[:200],
                )
            return {
                "instruction": instruction[:120],
                "status": "verification_pending",
                "results": {
                    "summary": f"Browse verification pending — API returned status {status_code}."
                },
            }
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            logger.warning("Yutori Browse API timeout: %s", exc)
            return {
                "instruction": instruction[:120],
                "status": "verification_pending",
                "results": {"summary": "Browse verification pending — request timed out."},
            }
        except Exception as exc:
            logger.error("Yutori Browse API unexpected error: %s", exc)
            return {
                "instruction": instruction[:120],
                "status": "verification_pending",
                "results": {"summary": f"Browse verification pending — error: {exc}"},
            }

    async def run_browsing_investigations(
        self,
        claimant_name: str,
        damage_type: str,
        estimated_cost: float,
    ) -> list[dict[str, Any]]:
        """Run 2 targeted browsing investigations in parallel.

        These are deep-web investigations that use a real browser AI agent:
        1. BBB Verification — check business ratings & complaints
        2. Court Records / News — search for prior fraud cases

        This is the "second pass" investigation triggered only when the
        first-pass research flagged risk indicators (fraud_score > 30).
        """
        tasks: list[asyncio.Task[dict[str, Any]]] = []

        # ── Browse 1: BBB Verification ────────────────────────────────────
        bbb_instruction = (
            f"Go to bbb.org. Search for auto body shops or repair businesses "
            f"related to the following insurance claim. Claim involves {damage_type} "
            f"with estimated cost of ${estimated_cost:,.0f}. Extract any business ratings, "
            f"complaint counts, and accreditation status you find."
        )
        tasks.append(
            asyncio.create_task(self.browse_and_verify(instruction=bbb_instruction))
        )

        # ── Browse 2: News / Court Records ────────────────────────────────
        court_instruction = (
            f"Search public court records and local news for any insurance fraud cases, "
            f"lawsuits, or criminal charges involving '{claimant_name}'. "
            f"Check county court websites and local news outlets."
        )
        tasks.append(
            asyncio.create_task(self.browse_and_verify(instruction=court_instruction))
        )

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        browsing_results: list[dict[str, Any]] = []
        entity_types = ["browse_bbb", "browse_court_records"]

        for idx, r in enumerate(raw_results):
            entity_type = entity_types[idx] if idx < len(entity_types) else "browse_unknown"
            if isinstance(r, Exception):
                logger.error("Browsing investigation %s failed: %s", entity_type, r)
                browsing_results.append({
                    "entity_name": claimant_name,
                    "entity_type": entity_type,
                    "status": "verification_pending",
                    "results": {"summary": f"Browsing investigation failed: {r}"},
                })
            else:
                # Normalize the browse result to match the entity result format
                # so fraud_signal_skill can process it uniformly
                browsing_results.append({
                    "entity_name": claimant_name,
                    "entity_type": entity_type,
                    "status": r.get("status", "verification_pending"),
                    "results": r.get("results", {}),
                })

        return browsing_results


# Module-level singleton
yutori_service = YutoriService()
