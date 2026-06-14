"""
OpenTelemetry distributed tracing for the Aubric Sovereign pipeline.

(The OTLP service name, tracer name, and span-name prefix below intentionally keep
the historical ``claimguard`` token so existing dashboards/queries keep working.)

Provides:
  - OTEL SDK initialization with OTLP gRPC exporter
  - FastAPI auto-instrumentation (all routes get spans automatically)
  - Custom span helpers for each stage in the claims processing pipeline
  - Context propagation via W3C traceparent header
  - Configurable via environment variables (disabled by default)

Usage -- add this to backend/app/main.py in the lifespan startup:

    from app.services.telemetry import init_telemetry
    init_telemetry(app)

This single call will:
  1. Initialize the TracerProvider with an OTLP exporter
  2. Auto-instrument FastAPI (all HTTP routes)
  3. Make the module-level ``tracer`` available for custom spans

Environment variables:
  OTEL_ENABLED                  -- "true" to enable (default: "false")
  OTEL_SERVICE_NAME             -- service name (default: "aubric-claimguard")
  OTEL_EXPORTER_OTLP_ENDPOINT   -- OTLP gRPC endpoint (default: "http://localhost:4317")
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

from app.config import OTEL_ENABLED, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_SERVICE_NAME

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level tracer -- safe to import even when OTEL is disabled.
# When disabled, all span operations are no-ops.
# ---------------------------------------------------------------------------

tracer: Any = None

# Track whether we have been initialized
_initialized = False


# ---------------------------------------------------------------------------
# No-op fallbacks for when OTEL is disabled or packages are missing
# ---------------------------------------------------------------------------

class _NoOpSpan:
    """Dummy span that silently accepts any attribute/event calls."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: Any = None) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoOpTracer:
    """Dummy tracer that returns no-op spans."""

    def start_as_current_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoOpSpan:
        return _NoOpSpan()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_telemetry(app: Any) -> None:
    """Initialize OpenTelemetry tracing and instrument the FastAPI application.

    Safe to call even when OTEL is disabled -- becomes a no-op.  Also safe
    when the ``opentelemetry`` packages are not installed; a warning is logged
    and all tracing degrades to no-op spans.

    Args:
        app: The FastAPI application instance.
    """
    global tracer, _initialized

    if _initialized:
        logger.debug("Telemetry already initialized, skipping.")
        return

    _initialized = True

    if not OTEL_ENABLED:
        logger.info(
            "OpenTelemetry disabled (OTEL_ENABLED=false). "
            "Set OTEL_ENABLED=true to enable distributed tracing.",
        )
        tracer = _NoOpTracer()
        return

    # Attempt to import the OTEL SDK -- graceful fallback if missing.
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning(
            "OpenTelemetry packages not installed (%s). "
            "Install with: pip install opentelemetry-api opentelemetry-sdk "
            "opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp-proto-grpc  "
            "Tracing will be a no-op.",
            exc,
        )
        tracer = _NoOpTracer()
        return

    # Build resource with service name
    resource = Resource.create({SERVICE_NAME: OTEL_SERVICE_NAME})

    # Create and configure the TracerProvider
    provider = TracerProvider(resource=resource)

    # OTLP gRPC exporter -- sends spans to Jaeger / OTEL Collector / etc.
    otlp_exporter = OTLPSpanExporter(
        endpoint=OTEL_EXPORTER_OTLP_ENDPOINT,
        insecure=not OTEL_EXPORTER_OTLP_ENDPOINT.startswith("https"),
    )
    provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

    # Set as the global tracer provider
    trace.set_tracer_provider(provider)

    # Create our named tracer
    tracer = trace.get_tracer("aubric.claimguard", "1.0.0")

    # Auto-instrument FastAPI -- every route gets a span automatically,
    # and the traceparent header is read for context propagation.
    FastAPIInstrumentor.instrument_app(app)

    logger.info(
        "OpenTelemetry initialized: service=%s endpoint=%s",
        OTEL_SERVICE_NAME,
        OTEL_EXPORTER_OTLP_ENDPOINT,
    )


# ---------------------------------------------------------------------------
# Custom span helpers for the Sovereign processing pipeline
# (span names keep the ``claimguard.*`` prefix as a stable telemetry namespace)
# ---------------------------------------------------------------------------

@contextmanager
def _trace_stage(
    span_name: str,
    claim_id: str,
    extra_attrs: dict[str, Any] | None = None,
) -> Generator[Any, None, None]:
    """Factory for pipeline stage spans — eliminates duplication."""
    if tracer is None or isinstance(tracer, _NoOpTracer):
        yield _NoOpSpan()
        return
    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("claim.id", claim_id)
        for k, v in (extra_attrs or {}).items():
            span.set_attribute(k, v)
        yield span


@contextmanager
def trace_pipeline(claim_id: str) -> Generator[Any, None, None]:
    """Parent span wrapping the entire claim processing pipeline."""
    with _trace_stage("claimguard.pipeline", claim_id) as span:
        yield span


@contextmanager
def trace_document_analysis(claim_id: str) -> Generator[Any, None, None]:
    """Span wrapping the Grok vision document analysis call."""
    with _trace_stage("claimguard.document_analysis", claim_id, {
        "model.name": "grok-4-1-fast-reasoning", "model.tier": "vision",
    }) as span:
        yield span


@contextmanager
def trace_coverage_lookup(claim_id: str) -> Generator[Any, None, None]:
    """Span wrapping the coverage/policy lookup."""
    with _trace_stage("claimguard.coverage_lookup", claim_id, {
        "skill.name": "coverage_lookup",
    }) as span:
        yield span


@contextmanager
def trace_web_investigation(claim_id: str) -> Generator[Any, None, None]:
    """Span wrapping the Yutori web research/verification step."""
    with _trace_stage("claimguard.web_investigation", claim_id, {
        "service.name": "yutori",
    }) as span:
        yield span


@contextmanager
def trace_fraud_assessment(claim_id: str) -> Generator[Any, None, None]:
    """Span wrapping the fraud signal skill assessment."""
    with _trace_stage("claimguard.fraud_assessment", claim_id, {
        "skill.name": "fraud_signal", "model.name": "grok-4-1-fast-reasoning",
    }) as span:
        yield span


@contextmanager
def trace_risk_evaluation(claim_id: str) -> Generator[Any, None, None]:
    """Span wrapping the Aubric risk engine evaluation."""
    with _trace_stage("claimguard.risk_evaluation", claim_id, {
        "engine.name": "aubric_risk_engine",
    }) as span:
        yield span


# ---------------------------------------------------------------------------
# Utility: add attributes to the current span from anywhere
# ---------------------------------------------------------------------------

def set_span_attributes(**attrs: Any) -> None:
    """Set attributes on the currently active span (no-op if tracing is off).

    All attribute keys are prefixed with ``claimguard.`` to avoid collisions.

    Usage::

        set_span_attributes(
            fraud_score=72.5,
            risk_level="high",
            payout_amount=15000.00,
        )
    """
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            for key, value in attrs.items():
                span.set_attribute(f"claimguard.{key}", value)
    except Exception:
        pass  # Never break application logic for telemetry


def record_exception(exc: Exception) -> None:
    """Record an exception on the currently active span (no-op if tracing is off).

    Usage::

        except Exception as exc:
            record_exception(exc)
            raise
    """
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
    except Exception:
        pass  # Never break application logic for telemetry


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

def shutdown_telemetry() -> None:
    """Flush and shut down the tracer provider. Call on application shutdown."""
    if not OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            provider.shutdown()
            logger.info("OpenTelemetry tracer provider shut down.")
    except Exception as exc:
        logger.warning("Error shutting down OpenTelemetry: %s", exc)
