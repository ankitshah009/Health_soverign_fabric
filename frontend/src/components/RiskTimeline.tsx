"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import {
  FileSearch,
  ShieldCheck,
  Globe,
  AlertTriangle,
  BarChart2,
  Gavel,
  Loader2,
  Check,
  AlertCircle,
  Clock,
} from "lucide-react";
import { InvestigationEvent } from "@/lib/types";
import { createEventSource } from "@/lib/api";

/* ── Stage definitions ──────────────────────────────────────────────── */

interface TimelineStage {
  id: string;
  label: string;
  shortLabel: string;
  icon: React.ReactNode;
  eventType: string;
  /** Extract a numeric score (0–100) from the event data, if available */
  extractScore: (data: Record<string, unknown> | undefined) => number | null;
  /** Extract a short summary string from the event data */
  extractSummary: (data: Record<string, unknown> | undefined) => string | null;
}

function safeNumber(v: unknown): number | null {
  if (typeof v === "number" && isFinite(v)) return v;
  return null;
}

function safeString(v: unknown): string | null {
  if (typeof v === "string" && v.trim()) return v.trim();
  return null;
}

const TIMELINE_STAGES: TimelineStage[] = [
  {
    id: "document_analysis",
    label: "Document Analysis",
    shortLabel: "Docs",
    icon: <FileSearch className="w-4 h-4" />,
    eventType: "document_analyzed",
    extractScore: (data) => {
      if (!data) return null;
      const score = safeNumber(data.confidence) ?? safeNumber(data.document_confidence);
      return score !== null ? Math.round(score * 100) : null;
    },
    extractSummary: (data) => {
      if (!data) return null;
      return (
        safeString(data.document_type) ??
        safeString(data.summary) ??
        safeString(data.damage_type) ??
        null
      );
    },
  },
  {
    id: "coverage_check",
    label: "Coverage Check",
    shortLabel: "Coverage",
    icon: <ShieldCheck className="w-4 h-4" />,
    eventType: "coverage_checked",
    extractScore: (data) => {
      if (!data) return null;
      if (typeof data.covered === "boolean") return data.covered ? 95 : 5;
      return null;
    },
    extractSummary: (data) => {
      if (!data) return null;
      return (
        safeString(data.coverage_type) ??
        (typeof data.covered === "boolean"
          ? data.covered
            ? "Covered"
            : "Not covered"
          : null) ??
        null
      );
    },
  },
  {
    id: "web_investigation",
    label: "Web Investigation",
    shortLabel: "Web",
    icon: <Globe className="w-4 h-4" />,
    eventType: "entity_verification",
    extractScore: (data) => {
      if (!data) return null;
      const score =
        safeNumber(data.risk_score) ??
        safeNumber(data.fraud_indicators) ??
        null;
      return score !== null ? Math.round(score) : null;
    },
    extractSummary: (data) => {
      if (!data) return null;
      return (
        safeString(data.summary) ??
        safeString(data.finding) ??
        null
      );
    },
  },
  {
    id: "fraud_assessment",
    label: "Error Assessment",
    shortLabel: "Errors",
    icon: <AlertTriangle className="w-4 h-4" />,
    eventType: "fraud_assessed",
    extractScore: (data) => {
      if (!data) return null;
      const raw =
        safeNumber(data.overall_score) ??
        safeNumber(data.fraud_score) ??
        safeNumber(data.score) ??
        null;
      return raw !== null ? Math.round(raw) : null;
    },
    extractSummary: (data) => {
      if (!data) return null;
      const level = safeString(data.risk_level) ?? safeString(data.level);
      const score =
        safeNumber(data.overall_score) ??
        safeNumber(data.fraud_score) ??
        safeNumber(data.score);
      if (level && score !== null) return `${level} · ${Math.round(score)}/100`;
      return level ?? null;
    },
  },
  {
    id: "risk_evaluation",
    label: "Risk Evaluation",
    shortLabel: "Risk",
    icon: <BarChart2 className="w-4 h-4" />,
    eventType: "risk_evaluated",
    extractScore: (data) => {
      if (!data) return null;
      return (
        safeNumber(data.fraud_score) ??
        safeNumber(data.risk_score) ??
        null
      );
    },
    extractSummary: (data) => {
      if (!data) return null;
      const action =
        safeString(data.recommended_action) ??
        safeString(data.action) ??
        safeString(data.action_risk_level);
      return action ? action.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : null;
    },
  },
  {
    id: "final_decision",
    label: "Final Decision",
    shortLabel: "Decision",
    icon: <Gavel className="w-4 h-4" />,
    eventType: "pipeline_complete",
    extractScore: () => null,
    extractSummary: (data) => {
      if (!data) return null;
      return (
        safeString(data.decision) ??
        safeString(data.status) ??
        safeString(data.action) ??
        "Complete"
      );
    },
  },
];

/* ── Types ──────────────────────────────────────────────────────────── */

type NodeState = "pending" | "active" | "complete" | "error";

interface TimelineNode {
  stageId: string;
  state: NodeState;
  score: number | null;
  summary: string | null;
  timestamp: string | null;
}

/* ── Helpers ─────────────────────────────────────────────────────────  */

function getRiskColor(score: number | null): string {
  if (score === null) return "var(--text-muted)";
  if (score < 30) return "var(--risk-low)";
  if (score < 60) return "var(--risk-medium)";
  if (score < 80) return "var(--risk-high)";
  return "var(--risk-critical)";
}

function getRiskBg(score: number | null): string {
  if (score === null) return "var(--bg-elevated)";
  if (score < 30) return "var(--risk-low-bg)";
  if (score < 60) return "var(--risk-medium-bg)";
  if (score < 80) return "var(--risk-high-bg)";
  return "var(--risk-critical-bg)";
}

function getRiskBorder(score: number | null): string {
  if (score === null) return "var(--border-subtle)";
  if (score < 30) return "var(--risk-low-border)";
  if (score < 60) return "var(--risk-medium-border)";
  if (score < 80) return "var(--risk-high-border)";
  return "var(--risk-critical-border)";
}

function getRiskLabel(score: number | null): string {
  if (score === null) return "—";
  if (score < 30) return "Low";
  if (score < 60) return "Medium";
  if (score < 80) return "High";
  return "Critical";
}

function buildInitialNodes(status: string): TimelineNode[] {
  const terminalStatuses = ["approved", "auto_approved", "denied", "blocked"];
  const reviewStatuses = ["pending_review", "escalated"];
  const allComplete =
    terminalStatuses.includes(status) || reviewStatuses.includes(status);

  return TIMELINE_STAGES.map((stage) => ({
    stageId: stage.id,
    state: allComplete ? ("complete" as NodeState) : ("pending" as NodeState),
    score: null,
    summary: null,
    timestamp: null,
  }));
}

/* ── Node Icon ───────────────────────────────────────────────────────  */

function NodeIcon({ state, score }: { state: NodeState; score: number | null }) {
  const size = "w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 flex-shrink-0";

  if (state === "active") {
    return (
      <div
        className={`${size} animate-pulse-glow`}
        style={{
          background: "var(--accent-primary)",
          boxShadow: "0 0 20px rgba(245,166,35,0.4)",
        }}
      >
        <Loader2 className="w-5 h-5 text-white animate-spin" strokeWidth={2.5} />
      </div>
    );
  }

  if (state === "complete") {
    const color = getRiskColor(score);
    const bg = getRiskBg(score);
    return (
      <div
        className={size}
        style={{
          background: bg,
          border: `2px solid ${color}`,
          boxShadow: `0 0 12px ${color}40`,
        }}
      >
        <Check className="w-5 h-5" style={{ color }} strokeWidth={3} />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        className={size}
        style={{
          background: "var(--risk-critical-bg)",
          border: "2px solid var(--risk-critical)",
        }}
      >
        <AlertCircle className="w-5 h-5" style={{ color: "var(--risk-critical)" }} strokeWidth={2.5} />
      </div>
    );
  }

  // Pending
  return (
    <div
      className={size}
      style={{
        background: "transparent",
        border: "2px solid var(--border-subtle)",
      }}
    >
      <Clock className="w-4 h-4" style={{ color: "var(--text-muted)" }} strokeWidth={2} />
    </div>
  );
}

/* ── Connector ───────────────────────────────────────────────────────  */

function VerticalConnector({ fromState, fromScore }: { fromState: NodeState; fromScore: number | null }) {
  const isComplete = fromState === "complete";
  const isActive = fromState === "active";
  const lineColor = isComplete ? getRiskColor(fromScore) : isActive ? "var(--accent-primary)" : "var(--border-subtle)";

  return (
    <div className="flex justify-center" style={{ margin: "0 19px" }}>
      <div
        className="w-0.5 h-8 transition-all duration-700"
        style={{
          background: isComplete
            ? lineColor
            : isActive
            ? `linear-gradient(to bottom, ${lineColor}, transparent)`
            : "var(--border-subtle)",
          opacity: isComplete || isActive ? 1 : 0.4,
        }}
      />
    </div>
  );
}

function HorizontalConnector({ fromState, fromScore }: { fromState: NodeState; fromScore: number | null }) {
  const isComplete = fromState === "complete";
  const isActive = fromState === "active";
  const lineColor = isComplete ? getRiskColor(fromScore) : isActive ? "var(--accent-primary)" : "var(--border-subtle)";

  return (
    <div className="flex items-center" style={{ marginTop: "19px" }}>
      <div
        className="flex-1 h-0.5 transition-all duration-700"
        style={{
          background: isComplete
            ? lineColor
            : isActive
            ? `linear-gradient(to right, ${lineColor}, transparent)`
            : "var(--border-subtle)",
          opacity: isComplete || isActive ? 1 : 0.4,
          minWidth: "12px",
        }}
      />
    </div>
  );
}

/* ── Node Card ───────────────────────────────────────────────────────  */

interface NodeCardProps {
  node: TimelineNode;
  stage: TimelineStage;
  isLast: boolean;
  layout: "vertical" | "horizontal";
}

function NodeCard({ node, stage, layout }: NodeCardProps) {
  const score = node.score;
  const riskColor = getRiskColor(score);
  const riskBg = getRiskBg(score);
  const riskBorder = getRiskBorder(score);
  const isPending = node.state === "pending";
  const isComplete = node.state === "complete";

  const time = node.timestamp
    ? new Date(node.timestamp).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : null;

  if (layout === "vertical") {
    return (
      <div
        className="flex gap-4"
        style={{ opacity: isPending ? 0.45 : 1, transition: "opacity 0.4s" }}
      >
        {/* Icon */}
        <div className="flex flex-col items-center">
          <NodeIcon state={node.state} score={score} />
        </div>

        {/* Content */}
        <div className="flex-1 pb-2">
          <div className="flex items-center gap-2 mb-1">
            <div style={{ color: "var(--text-muted)" }}>{stage.icon}</div>
            <span
              className="text-sm font-semibold"
              style={{
                color: isPending
                  ? "var(--text-muted)"
                  : node.state === "active"
                  ? "var(--accent-primary)"
                  : "var(--text-primary)",
              }}
            >
              {stage.label}
            </span>
            {time && (
              <span className="text-xs font-mono ml-auto" style={{ color: "var(--text-muted)" }}>
                {time}
              </span>
            )}
          </div>

          {/* Score pill + summary */}
          {isComplete && (
            <div className="flex items-center gap-2 flex-wrap">
              {score !== null && (
                <span
                  className="text-xs font-semibold px-2 py-0.5 rounded-full"
                  style={{
                    color: riskColor,
                    background: riskBg,
                    border: `1px solid ${riskBorder}`,
                  }}
                >
                  {getRiskLabel(score)} · {score}/100
                </span>
              )}
              {node.summary && (
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {node.summary}
                </span>
              )}
            </div>
          )}

          {node.state === "active" && (
            <span className="text-xs" style={{ color: "var(--accent-primary)" }}>
              Analyzing…
            </span>
          )}
        </div>
      </div>
    );
  }

  // Horizontal layout — compact card below the icon rail
  return (
    <div
      className="flex flex-col items-center"
      style={{ opacity: isPending ? 0.4 : 1, transition: "opacity 0.4s" }}
    >
      <NodeIcon state={node.state} score={score} />
      <div className="mt-2 text-center" style={{ maxWidth: "90px" }}>
        <div
          className="text-xs font-semibold"
          style={{
            color: isPending
              ? "var(--text-muted)"
              : node.state === "active"
              ? "var(--accent-primary)"
              : node.state === "complete"
              ? getRiskColor(score)
              : "var(--risk-critical)",
          }}
        >
          {stage.shortLabel}
        </div>
        {isComplete && score !== null && (
          <div
            className="text-xs mt-1 font-semibold"
            style={{ color: riskColor }}
          >
            {score}
          </div>
        )}
        {isComplete && node.summary && (
          <div
            className="text-xs mt-0.5 leading-tight"
            style={{ color: "var(--text-secondary)" }}
          >
            {node.summary.length > 20 ? node.summary.slice(0, 18) + "…" : node.summary}
          </div>
        )}
        {node.state === "active" && (
          <div className="text-xs mt-1" style={{ color: "var(--accent-primary)" }}>
            Analyzing…
          </div>
        )}
      </div>
    </div>
  );
}

/* ── SSE event → stage mapper ────────────────────────────────────────  */

function mapEventToStage(eventType: string): number {
  for (let i = 0; i < TIMELINE_STAGES.length; i++) {
    if (TIMELINE_STAGES[i].eventType === eventType) return i;
  }
  return -1;
}

/* ── Main component ──────────────────────────────────────────────────  */

interface RiskTimelineProps {
  claimId: string;
  status: string;
}

const COMPLETED_STATUSES = ["approved", "auto_approved", "denied", "blocked", "pending_review", "escalated"];

export default function RiskTimeline({ claimId, status }: RiskTimelineProps) {
  const [nodes, setNodes] = useState<TimelineNode[]>(() =>
    buildInitialNodes(status)
  );

  const esRef = useRef<EventSource | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const completedTimerRef = useRef<number | null>(null);

  const applyEvent = useCallback((event: InvestigationEvent) => {
    const key = `${event.timestamp}-${event.event_type}`;
    if (seenRef.current.has(key)) return;
    seenRef.current.add(key);

    const idx = mapEventToStage(event.event_type);
    if (idx === -1) return;

    const stage = TIMELINE_STAGES[idx];
    const score = stage.extractScore(event.data);
    const summary = stage.extractSummary(event.data);

    setNodes((prev) =>
      prev.map((node, i) => {
        if (i < idx) {
          // Earlier stages — mark complete if still pending/active
          if (node.state === "pending" || node.state === "active") {
            return { ...node, state: "complete" };
          }
          return node;
        }
        if (i === idx) {
          const isError =
            event.status === "error" || event.status === "failed";
          return {
            ...node,
            state: isError ? "error" : "complete",
            score: score ?? node.score,
            summary: summary ?? node.summary,
            timestamp: event.timestamp,
          };
        }
        // Next stage — set active if this one just completed
        if (i === idx + 1 && node.state === "pending") {
          return { ...node, state: "active" };
        }
        return node;
      })
    );
  }, []);

  useEffect(() => {
    if (completedTimerRef.current) window.clearTimeout(completedTimerRef.current);

    const isCompleted = COMPLETED_STATUSES.includes(status);
    const isActive = status === "processing" || status === "submitted";

    if (!isCompleted && !isActive) return;

    const es = createEventSource(claimId);
    esRef.current = es;

    es.onmessage = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        const evt: InvestigationEvent = {
          event_type: parsed.event_type ?? "",
          message: parsed.message ?? "",
          status: parsed.status ?? "info",
          data: parsed.data ?? undefined,
          timestamp: parsed.timestamp ?? new Date().toISOString(),
        };
        applyEvent(evt);
      } catch {
        // ignore parse errors
      }
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
    };

    if (isCompleted) {
      // Close after 2.5s — enough to receive all buffered historical events
      completedTimerRef.current = window.setTimeout(() => {
        es.close();
        esRef.current = null;
      }, 2500);
    }

    return () => {
      if (completedTimerRef.current) window.clearTimeout(completedTimerRef.current);
      es.close();
      esRef.current = null;
    };
  }, [claimId, status, applyEvent]);

  // Compute cumulative max risk score for the header indicator
  const completedScores = nodes
    .filter((n) => n.state === "complete" && n.score !== null)
    .map((n) => n.score as number);
  const peakScore = completedScores.length > 0 ? Math.max(...completedScores) : null;
  const peakColor = getRiskColor(peakScore);

  const isProcessing = nodes.some((n) => n.state === "active");
  const allComplete = nodes.every((n) => n.state === "complete");

  return (
    <div
      className="card p-6"
      data-testid="risk-timeline"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <BarChart2
            className="w-5 h-5"
            style={{ color: "var(--accent-primary)" }}
          />
          <h3
            className="type-section-title"
            style={{ color: "var(--text-primary)" }}
          >
            Risk Timeline
          </h3>
        </div>
        <div className="flex items-center gap-3">
          {peakScore !== null && (
            <span
              className="text-xs font-semibold px-2.5 py-1 rounded-full"
              style={{
                color: peakColor,
                background: getRiskBg(peakScore),
                border: `1px solid ${getRiskBorder(peakScore)}`,
              }}
            >
              Peak risk: {peakScore}/100
            </span>
          )}
          {isProcessing && (
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
          {allComplete && (
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Complete
            </span>
          )}
        </div>
      </div>

      {/* Desktop: horizontal rail */}
      <div className="hidden md:block">
        <div className="flex items-start">
          {TIMELINE_STAGES.map((stage, idx) => (
            <div key={stage.id} className="contents">
              <NodeCard
                node={nodes[idx]}
                stage={stage}
                isLast={idx === TIMELINE_STAGES.length - 1}
                layout="horizontal"
              />
              {idx < TIMELINE_STAGES.length - 1 && (
                <HorizontalConnector
                  fromState={nodes[idx].state}
                  fromScore={nodes[idx].score}
                />
              )}
            </div>
          ))}
        </div>

        {/* Score trajectory sparkline-style bar */}
        {completedScores.length > 1 && (
          <div
            className="mt-6 pt-4"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="label">Risk Trajectory</span>
            </div>
            <div className="flex items-end gap-1 h-8">
              {nodes
                .filter((n) => n.state === "complete" && n.score !== null)
                .map((n, i) => {
                  const s = n.score as number;
                  return (
                    <div
                      key={i}
                      className="flex-1 rounded-sm transition-all duration-500"
                      style={{
                        height: `${Math.max(8, (s / 100) * 32)}px`,
                        background: getRiskColor(s),
                        opacity: 0.8,
                        minWidth: "8px",
                      }}
                      title={`${s}/100`}
                    />
                  );
                })}
            </div>
          </div>
        )}
      </div>

      {/* Mobile: vertical stack */}
      <div className="md:hidden space-y-0">
        {TIMELINE_STAGES.map((stage, idx) => (
          <div key={stage.id}>
            <NodeCard
              node={nodes[idx]}
              stage={stage}
              isLast={idx === TIMELINE_STAGES.length - 1}
              layout="vertical"
            />
            {idx < TIMELINE_STAGES.length - 1 && (
              <VerticalConnector
                fromState={nodes[idx].state}
                fromScore={nodes[idx].score}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
