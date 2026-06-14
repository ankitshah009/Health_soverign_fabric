"use client";

interface StatusBadgeProps {
  status: string;
  size?: "sm" | "md" | "lg";
}

const statusConfig: Record<string, { label: string; color: string; bg: string; border: string; pulse?: boolean; dot?: boolean }> = {
  submitted: {
    label: "Submitted",
    color: "var(--text-secondary)",
    bg: "var(--hover-overlay)",
    border: "var(--border-subtle)",
    dot: true,
  },
  processing: {
    label: "Analyzing",
    color: "var(--accent-primary)",
    bg: "var(--accent-primary-bg)",
    border: "var(--accent-primary-border)",
    pulse: true,
  },
  pending_review: {
    label: "Under Review",
    // --risk-high-text (#C2410C) is 4.65:1 on white — passes AA
    color: "var(--risk-high-text)",
    bg: "var(--status-review-bg)",
    border: "var(--risk-high-border)",
    dot: true,
  },
  auto_approved: {
    label: "Auto-Approved",
    // --risk-low-text (#047857) is 5.8:1 on white — passes AA
    color: "var(--risk-low-text)",
    bg: "var(--status-approved-bg)",
    border: "var(--risk-low-border)",
  },
  approved: {
    label: "Approved",
    // --risk-low-text (#047857) is 5.8:1 on white — passes AA
    color: "var(--risk-low-text)",
    bg: "var(--status-approved-bg)",
    border: "var(--risk-low-border)",
  },
  denied: {
    label: "Denied",
    color: "var(--status-denied)",
    bg: "var(--status-denied-bg)",
    border: "rgba(251,113,133,0.40)",
  },
  escalated: {
    label: "Escalated",
    color: "var(--status-escalated)",
    bg: "var(--status-escalated-bg)",
    border: "rgba(167,139,250,0.40)",
  },
  // "blocked" is renamed to patient-facing "Needs Escalation" (violet/amber, NOT red)
  blocked: {
    label: "Needs Escalation",
    color: "var(--status-escalated)",
    bg: "var(--status-escalated-bg)",
    border: "rgba(167,139,250,0.40)",
  },
  error: {
    label: "Error",
    color: "var(--danger)",
    bg: "var(--danger-bg)",
    border: "var(--danger-border)",
  },
};

const sizeClasses = {
  sm: "text-[10px] px-2 py-0.5 gap-1",
  md: "text-xs px-2.5 py-1 gap-1.5",
  lg: "text-sm px-3 py-1.5 gap-1.5",
};

export default function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    label: status.replace(/_/g, " "),
    color: "var(--text-secondary)",
    bg: "var(--hover-overlay)",
    border: "var(--border-subtle)",
  };

  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold uppercase tracking-wider ${sizeClasses[size]}`}
      style={{
        color: config.color,
        background: config.bg,
        border: `1px solid ${config.border}`,
      }}
    >
      {config.pulse && (
        <span className="relative flex h-1.5 w-1.5">
          <span
            className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-75"
            style={{ background: config.color }}
          />
          <span
            className="relative inline-flex h-1.5 w-1.5 rounded-full"
            style={{ background: config.color }}
          />
        </span>
      )}
      {config.dot && !config.pulse && (
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: config.color }}
        />
      )}
      {config.label}
    </span>
  );
}
