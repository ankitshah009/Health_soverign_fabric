"use client";

import { FlaskConical } from "lucide-react";
import { SimulationResult } from "@/lib/types";

interface SimulationCardProps {
  simulation: SimulationResult | null | undefined;
}

function ProgressBar({
  value,
  label,
  colorVar,
}: {
  value: number;
  label: string;
  colorVar: string;
}) {
  const pct = Math.min(100, Math.max(0, Math.round(value)));
  const isHigh = pct > 70;
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-sm" style={{ color: "var(--text-primary)" }}>{label}</span>
        <span className="text-sm font-semibold stat-value" style={{ color: colorVar }}>{pct}%</span>
      </div>
      <div
        className="h-2 rounded-full overflow-hidden"
        style={{ background: "var(--bg-elevated)" }}
      >
        <div
          className="h-full rounded-full transition-all duration-1000 ease-out"
          style={{
            width: `${pct}%`,
            background: colorVar,
            boxShadow: isHigh ? `0 0 8px ${colorVar}80` : "none",
          }}
        />
      </div>
    </div>
  );
}

function getLikelihoodLevel(value: number | string): "low" | "medium" | "high" {
  if (typeof value === "string") {
    if (value === "low" || value === "medium" || value === "high") return value;
    return "medium";
  }
  if (value < 0.33) return "low";
  if (value < 0.66) return "medium";
  return "high";
}

function LikelihoodBadge({ level }: { level: "low" | "medium" | "high" }) {
  const config: Record<string, { label: string; color: string; bg: string; border: string }> = {
    low: {
      label: "Low",
      color: "var(--risk-low)",
      bg: "var(--risk-low-bg)",
      border: "var(--risk-low-border)",
    },
    medium: {
      label: "Medium",
      color: "var(--risk-medium)",
      bg: "var(--risk-medium-bg)",
      border: "var(--risk-medium-border)",
    },
    high: {
      label: "High",
      color: "var(--risk-critical)",
      bg: "var(--risk-critical-bg)",
      border: "var(--risk-critical-border)",
    },
  };
  const c = config[level];
  return (
    <span
      className="inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium"
      style={{
        color: c.color,
        background: c.bg,
        border: `1px solid ${c.border}`,
      }}
    >
      {c.label}
    </span>
  );
}

export default function SimulationCard({ simulation }: SimulationCardProps) {
  if (!simulation) {
    return (
      <div className="gradient-border p-6">
        <h3
          className="type-section-title mb-4 flex items-center gap-2"
          style={{ color: "var(--text-primary)" }}
        >
          <FlaskConical className="w-5 h-5" style={{ color: "var(--status-escalated)" }} />
          Recovery Simulation
        </h3>
        <div className="space-y-3">
          <div className="h-4 skeleton w-3/4"></div>
          <div className="h-2 skeleton w-full"></div>
          <div className="h-4 skeleton w-2/3"></div>
          <div className="h-2 skeleton w-full"></div>
        </div>
      </div>
    );
  }

  const approvalPct = simulation.approval_probability * 100;
  const disputePct = simulation.dispute_risk * 100;
  const fraudLevel = getLikelihoodLevel(simulation.fraud_escalation_likelihood);

  return (
    <div className="gradient-border p-6">
      <h3
        className="type-section-title mb-1 flex items-center gap-2"
        style={{ color: "var(--text-primary)" }}
      >
        <FlaskConical className="w-5 h-5" style={{ color: "var(--status-escalated)" }} />
        Recovery Simulation
      </h3>
      <p className="text-xs mb-6" style={{ color: "var(--text-muted)" }}>
        If this appeal is filed now
      </p>

      <div className="space-y-5">
        <ProgressBar
          value={approvalPct}
          label="Appeal Success Probability"
          colorVar="var(--risk-low)"
        />
        <ProgressBar
          value={disputePct}
          label="Dispute Risk"
          colorVar={disputePct > 50 ? "var(--risk-critical)" : "var(--risk-medium)"}
        />

        <div className="flex items-center justify-between">
          <span className="text-sm" style={{ color: "var(--text-primary)" }}>Escalation Likelihood</span>
          <LikelihoodBadge level={fraudLevel} />
        </div>

        <div
          className="flex items-center justify-between pt-3"
          style={{ borderTop: "1px solid var(--border-subtle)" }}
        >
          <span className="text-sm" style={{ color: "var(--text-secondary)" }}>Financial Exposure</span>
          <span
            className="text-xl font-bold tabular-nums"
            style={{
              color: "var(--text-primary)",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            ${simulation.financial_exposure?.toLocaleString() || "0"}
          </span>
        </div>

        {simulation.historical_comparison && (
          <div className="card-elevated rounded-lg p-4 mt-4">
            <h4 className="label mb-2">Historical Comparison</h4>
            <p className="text-sm" style={{ color: "var(--text-primary)" }}>{simulation.historical_comparison}</p>
          </div>
        )}

        {simulation.recommended_action && (
          <div className="glass-panel p-3">
            <p className="text-sm" style={{ color: "var(--accent-primary)" }}>
              <span className="font-semibold">Recommendation:</span>{" "}
              {simulation.recommended_action.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase())}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
