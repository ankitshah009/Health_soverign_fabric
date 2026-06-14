"use client";

import { Search, Shield, Building2, FileText, Network, UserCheck, Wallet } from "lucide-react";
import type { FraudSignal } from "@/lib/types";

/* ------------------------------------------------------------------ */
/* Types                                                               */
/* ------------------------------------------------------------------ */

interface WebInvestigationProps {
  signals: FraudSignal[];
}

/* ------------------------------------------------------------------ */
/* Entity config — icon, label, key fragment                           */
/* ------------------------------------------------------------------ */

interface EntityConfig {
  key: string;
  label: string;
  icon: React.ComponentType<React.SVGProps<SVGSVGElement> & { size?: number | string }>;
}

const ENTITY_CONFIGS: EntityConfig[] = [
  { key: "patient_history", label: "Patient History",         icon: Shield },
  { key: "provider_facility", label: "Provider / Facility",    icon: Building2 },
  { key: "coverage_corroboration", label: "Coverage Corroboration", icon: FileText },
  { key: "cpt_verification", label: "CPT / Code Verification",  icon: UserCheck },
  { key: "network_status", label: "Network Status",          icon: Network },
];

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

type SignalStatus = "verified" | "risk" | "pending";

function classifySignal(signalName: string): SignalStatus {
  if (signalName.includes("risk_") || signalName.includes("low_credibility_")) {
    return "risk";
  }
  if (signalName.includes("unverified_") || signalName.includes("pending_")) {
    return "pending";
  }
  if (signalName.includes("verified_") || signalName.includes("neutral_")) {
    return "verified";
  }
  return "pending"; // unverified or unknown
}

function statusLabel(status: SignalStatus): string {
  switch (status) {
    case "verified":
      return "Verified";
    case "risk":
      return "Risk Found";
    case "pending":
      return "Pending";
  }
}

function statusDotClass(status: SignalStatus): string {
  switch (status) {
    case "verified":
      return "bg-[var(--risk-low)]";
    case "risk":
      return "bg-[var(--accent-primary)]";
    case "pending":
      return "bg-[var(--text-muted)]";
  }
}

function statusTextClass(status: SignalStatus): string {
  switch (status) {
    case "verified":
      // --risk-low-text (#047857) is 5.8:1 on white — passes AA for small text
      return "text-[var(--risk-low-text)]";
    case "risk":
      return "text-[var(--accent-primary)]";
    case "pending":
      return "text-[var(--text-muted)]";
  }
}

// No thick left-border — status signaled via dot + text only
function cardBorderClass(_status: SignalStatus): string {
  return "";
}

function confidenceBarBg(status: SignalStatus): string {
  switch (status) {
    case "verified":
      return "bg-[var(--risk-low)]";
    case "risk":
      return "bg-[var(--accent-primary)]";
    case "pending":
      return "bg-[var(--text-muted)]";
  }
}

/* ------------------------------------------------------------------ */
/* Component                                                           */
/* ------------------------------------------------------------------ */

export default function WebInvestigation({ signals }: WebInvestigationProps) {
  // Filter to only yutori signals
  const yutoriSignals = signals.filter((s) => s.signal_name.startsWith("yutori_"));

  // Empty signals array
  if (signals.length === 0) {
    return (
      <div className="card p-6">
        <h3 className="type-section-title mb-4 flex items-center gap-2 text-[var(--text-primary)]">
          <Search className="w-5 h-5 text-[var(--accent-primary)]" />
          Web Investigation
        </h3>
        <div className="flex flex-col items-center justify-center py-8">
          <Search className="w-10 h-10 mb-3 text-[var(--text-muted)] opacity-30" strokeWidth={1.5} />
          <p className="text-sm text-[var(--text-muted)]">
            Web investigation results will appear here
          </p>
        </div>
      </div>
    );
  }

  // Signals present but none from Yutori
  if (yutoriSignals.length === 0) {
    return (
      <div className="card p-6">
        <h3 className="type-section-title mb-4 flex items-center gap-2 text-[var(--text-primary)]">
          <Search className="w-5 h-5 text-[var(--accent-primary)]" />
          Web Investigation
        </h3>
        <div className="flex flex-col items-center justify-center py-8">
          <Search className="w-10 h-10 mb-3 text-[var(--text-muted)] opacity-30" strokeWidth={1.5} />
          <p className="text-sm text-[var(--text-muted)]">
            No web investigation data available
          </p>
        </div>
      </div>
    );
  }

  // Match each entity config to its signal (if present)
  const cards = ENTITY_CONFIGS.map((config) => {
    const signal = yutoriSignals.find((s) => s.signal_name.includes(config.key));
    return { config, signal };
  }).filter(({ signal }) => signal !== undefined) as Array<{
    config: EntityConfig;
    signal: FraudSignal;
  }>;

  return (
    <div className="card p-6">
      <h3 className="type-section-title mb-5 flex items-center gap-2 text-[var(--text-primary)]">
        <Search className="w-5 h-5 text-[var(--accent-primary)]" />
        Web Investigation
      </h3>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 stagger-children">
        {cards.map(({ config, signal }) => {
          const Icon = config.icon;
          const status = classifySignal(signal.signal_name);
          const confidence = Math.round(signal.confidence * 100);

          return (
            <div
              key={config.key}
              className="rounded-xl p-4 transition-colors duration-[180ms]"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-subtle)",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-default)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-subtle)";
              }}
            >
              {/* Header row: icon + title + status */}
              <div className="flex items-start justify-between gap-3 mb-3">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center bg-[var(--accent-primary-bg)] shrink-0">
                    <Icon className="w-[18px] h-[18px] text-[var(--accent-primary)]" />
                  </div>
                  <h4 className="text-sm font-semibold text-[var(--text-primary)]">
                    {config.label}
                  </h4>
                </div>

                {/* Status indicator */}
                <div className="flex items-center gap-1.5 shrink-0">
                  <span className={`w-2 h-2 rounded-full ${statusDotClass(status)}`} />
                  <span className={`text-xs font-medium ${statusTextClass(status)}`}>
                    {statusLabel(status)}
                  </span>
                </div>
              </div>

              {/* Description */}
              <p className="text-sm leading-relaxed mb-3 text-[var(--text-secondary)]">
                {signal.description}
              </p>

              {/* Confidence bar */}
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                  Confidence
                </span>
                <div className="flex-1 h-1 rounded-full bg-[var(--border-subtle)] overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ease-out ${confidenceBarBg(status)}`}
                    style={{ width: `${confidence}%` }}
                  />
                </div>
                <span className="text-[10px] font-mono text-[var(--text-muted)]">
                  {confidence}%
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
