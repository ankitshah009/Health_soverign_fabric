"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Activity, Check, Loader2, X } from "lucide-react";
import { InvestigationEvent } from "@/lib/types";
import { createEventSource } from "@/lib/api";

interface InvestigationFeedProps {
  claimId: string;
  status?: string;
  onEventReceived?: (event: InvestigationEvent) => void;
}

function EventIcon({ status }: { status: string }) {
  if (status === "running" || status === "processing") {
    return (
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center"
        style={{
          background: "var(--accent-primary-bg)",
          border: "1px solid var(--accent-primary-border)",
          animation: "amberPulse 2s ease-in-out infinite",
        }}
      >
        <Loader2
          className="w-4 h-4 animate-spin"
          style={{ color: "var(--accent-primary)" }}
        />
      </div>
    );
  }

  if (status === "completed") {
    return (
      <div
        className="w-8 h-8 rounded-full flex items-center justify-center"
        style={{
          background: "var(--risk-low-bg)",
          border: "1px solid var(--risk-low-border)",
        }}
      >
        <Check className="w-4 h-4" style={{ color: "var(--risk-low)" }} />
      </div>
    );
  }

  return (
    <div
      className="w-8 h-8 rounded-full flex items-center justify-center"
      style={{
        background: "var(--risk-critical-bg)",
        border: "1px solid var(--risk-critical-border)",
      }}
    >
      <X className="w-4 h-4" style={{ color: "var(--risk-critical)" }} />
    </div>
  );
}

const COMPLETED_STATUSES = [
  "approved", "auto_approved", "denied", "blocked",
  "pending_review", "escalated",
];

/**
 * Parse an SSE MessageEvent into an InvestigationEvent.
 * The backend sends unnamed SSE events with event_type inside the JSON payload.
 */
function parseSSEEvent(e: MessageEvent): InvestigationEvent | null {
  try {
    const parsed = JSON.parse(e.data);
    return {
      event_type: parsed.event_type ?? "",
      message: parsed.message ?? "",
      status: parsed.status ?? "info",
      data: parsed.data ?? null,
      timestamp: parsed.timestamp ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export default function InvestigationFeed({
  claimId,
  status,
  onEventReceived,
}: InvestigationFeedProps) {
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamEnded, setStreamEnded] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);
  const onEventReceivedRef = useRef(onEventReceived);
  const esRef = useRef<EventSource | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());
  const completedTimerRef = useRef<number | null>(null);

  useEffect(() => {
    onEventReceivedRef.current = onEventReceived;
  }, [onEventReceived]);

  const addEvent = useCallback((event: InvestigationEvent) => {
    // Dedupe by timestamp+event_type
    const key = `${event.timestamp}-${event.event_type}`;
    if (seenIdsRef.current.has(key)) return;
    seenIdsRef.current.add(key);

    setEvents((prev) => [...prev, event]);
    onEventReceivedRef.current?.(event);

    // Detect stream end
    if (event.event_type === "pipeline_complete" || event.event_type === "pipeline_error") {
      setStreamEnded(true);
    }
  }, []);

  const connectSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
    }
    const es = createEventSource(claimId);
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
    };

    es.onmessage = (e: MessageEvent) => {
      const event = parseSSEEvent(e);
      if (event) addEvent(event);
    };

    es.onerror = () => {
      setConnected(false);
      es.close();
      esRef.current = null;
      // Only show error if we got zero events AND stream hasn't ended normally
      setEvents((prev) => {
        if (prev.length === 0) {
          setError("Connection lost. Click retry to reconnect.");
        }
        return prev;
      });
    };

    return es;
  }, [claimId, addEvent]);

  const clearCompletedTimer = useCallback(() => {
    if (completedTimerRef.current !== null) {
      window.clearTimeout(completedTimerRef.current);
      completedTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    clearCompletedTimer();

    // For completed claims: one-shot fetch via SSE, auto-close after events arrive
    if (status && COMPLETED_STATUSES.includes(status)) {
      const es = createEventSource(claimId);
      esRef.current = es;
      es.onopen = () => {
        setConnected(true);
      };
      es.onmessage = (e: MessageEvent) => {
        const event = parseSSEEvent(e);
        if (event) addEvent(event);
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        esRef.current = null;
        setEvents((prev) => {
          if (prev.length === 0) {
            setError("Unable to load investigation events. Refresh to retry.");
          }
          return prev;
        });
      };
      // Backend sends all existing events immediately, then stream continues polling.
      // Close after 2s — enough time to receive all buffered events.
      completedTimerRef.current = window.setTimeout(() => {
        setConnected(false);
        es.close();
        esRef.current = null;
        setEvents((prev) => {
          if (prev.length === 0) {
            setError("No investigation events are available for this claim.");
          }
          return prev;
        });
      }, 2000);
      return () => {
        clearCompletedTimer();
        setConnected(false);
        es.close();
        esRef.current = null;
      };
    }

    // Active claim — keep SSE open for real-time updates
    const es = connectSSE();
    return () => {
      clearCompletedTimer();
      setConnected(false);
      es.close();
      esRef.current = null;
    };
  }, [claimId, status, connectSSE, addEvent, clearCompletedTimer]);

  // Auto-scroll
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight;
    }
  }, [events]);

  return (
    <div className="card p-6">
      <style>{`
        @keyframes amberPulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(245, 166, 35, 0.3); }
          50% { box-shadow: 0 0 12px 4px rgba(245, 166, 35, 0.15); }
        }
      `}</style>

      <div className="flex items-center justify-between mb-4">
        <h3
          className="type-section-title flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <Activity className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />
          Investigation Feed
        </h3>
        <div className="flex items-center gap-2">
          {connected && !streamEnded && (
            <span
              className="flex items-center gap-1.5 text-xs"
              style={{ color: "var(--accent-primary)" }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: "var(--accent-primary)" }}
              />
              Live
            </span>
          )}
          {streamEnded && events.length > 0 && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Complete
            </span>
          )}
        </div>
      </div>

      {error && (
        <div
          className="mb-4 p-3 rounded-lg flex items-center justify-between"
          style={{
            background: "var(--risk-critical-bg)",
            border: "1px solid var(--risk-critical-border)",
          }}
        >
          <span className="text-sm" style={{ color: "var(--risk-critical)" }}>{error}</span>
          <button
            onClick={() => {
              setEvents([]);
              seenIdsRef.current.clear();
              setStreamEnded(false);
              setError(null);
              connectSSE();
            }}
            aria-label="Retry investigation feed connection"
            className="text-xs underline px-2 py-1 min-h-[44px] min-w-[44px] cursor-pointer"
            style={{ color: "var(--risk-critical)" }}
          >
            Retry
          </button>
        </div>
      )}

      <div
        ref={feedRef}
        className="space-y-0 max-h-96 overflow-y-auto pr-2"
      >
        {events.length === 0 && !error && (
          <div className="text-center py-8">
            <div
              className="w-8 h-8 mx-auto mb-3 rounded-full flex items-center justify-center"
              style={{ background: "var(--accent-primary-bg)" }}
            >
              <Loader2
                className="w-4 h-4 animate-spin"
                style={{ color: "var(--accent-primary)" }}
              />
            </div>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Waiting for investigation to begin...
            </p>
          </div>
        )}

        {events.map((event, i) => {
          const time = new Date(event.timestamp).toLocaleTimeString("en-US", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          });
          const isLast = i === events.length - 1;

          return (
            <div
              key={`${event.timestamp}-${event.event_type}-${i}`}
              className="animate-slide-in"
            >
              <div className="flex gap-3 py-2.5">
                <div className="flex flex-col items-center">
                  <EventIcon status={event.status} />
                  {!isLast && (
                    <div
                      className="w-px flex-1 mt-1"
                      style={{
                        background: "linear-gradient(to bottom, var(--border-subtle) 60%, transparent)",
                        minHeight: "12px",
                      }}
                    />
                  )}
                </div>

                <div className="flex-1 min-w-0 pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <p
                      className="text-sm"
                      style={{
                        color:
                          event.status === "processing"
                            ? "var(--accent-primary)"
                            : event.status === "completed"
                            ? "var(--text-primary)"
                            : "var(--risk-critical)",
                      }}
                    >
                      {event.message}
                    </p>
                    <span
                      className="text-xs flex-shrink-0 font-mono"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {time}
                    </span>
                  </div>

                  {event.event_type && (
                    <span
                      className="inline-block mt-1 text-xs px-1.5 py-0.5 rounded"
                      style={{
                        color: "var(--text-muted)",
                        background: "var(--bg-elevated)",
                      }}
                    >
                      {event.event_type}
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
