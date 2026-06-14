"use client";

import Image from "next/image";
import { useEffect, useState, useCallback, use } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { getClaim, submitApproval } from "@/lib/api";
import { ClaimData, FraudSignal } from "@/lib/types";
import { cn, getRiskColor, formatClaimDate, formatCurrency, getNumericFraudScore, extractFraudSignals } from "@/lib/utils";
import StatusBadge from "@/components/StatusBadge";
import RiskRadar from "@/components/RiskRadar";
import InvestigationFeed from "@/components/InvestigationFeed";
import SimulationCard from "@/components/SimulationCard";
import DecisionReceipt from "@/components/DecisionReceipt";
import PipelineStepper from "@/components/PipelineStepper";
import RiskTimeline from "@/components/RiskTimeline";
import WebInvestigation from "@/components/WebInvestigation";
import {
  FileText,
  BarChart3,
  FileCheck,
  AlertCircle,
  FileImage,
  File,
  Sparkles,
  Shield,
  Check,
  ArrowUpRight,
} from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** Extract error/overcharge signals from case — from fraud_signals field or error score object. */
function getFraudSignals(claim: ClaimData): FraudSignal[] {
  if (claim.fraud_signals && claim.fraud_signals.length > 0) {
    return claim.fraud_signals;
  }
  return extractFraudSignals(claim.fraud_score);
}

type TabId = "overview" | "analysis" | "decision";

const VALID_TABS: TabId[] = ["overview", "analysis", "decision"];

function isValidTab(tab: string | null): tab is TabId {
  return tab !== null && VALID_TABS.includes(tab as TabId);
}

function SectionSkeleton({ height = "h-48" }: { height?: string }) {
  return (
    <div className={`card p-6 ${height}`}>
      <div className="h-5 skeleton w-40 mb-4"></div>
      <div className="space-y-3">
        <div className="h-3 skeleton w-full"></div>
        <div className="h-3 skeleton w-3/4"></div>
        <div className="h-3 skeleton w-5/6"></div>
      </div>
    </div>
  );
}

function DataField({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="flex items-start justify-between gap-4 py-2 last:border-0"
      style={{ borderBottom: "1px solid var(--border-subtle)" }}
    >
      <span className="label flex-shrink-0">{label}</span>
      <span className="text-sm text-right" style={{ color: "var(--text-primary)" }}>
        {value}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Tab Navigation                                                      */
/* ------------------------------------------------------------------ */

function TabNav({
  activeTab,
  onTabChange,
  isTerminal,
}: {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
  isTerminal: boolean;
}) {
  const tabs: Array<{ id: TabId; label: string; icon: React.ReactNode; hidden?: boolean }> = [
    {
      id: "overview",
      label: "Overview",
      icon: <FileText className="w-4 h-4" />,
    },
    {
      id: "analysis",
      label: "Analysis",
      icon: <BarChart3 className="w-4 h-4" />,
    },
    {
      id: "decision",
      label: "Decision",
      icon: <FileCheck className="w-4 h-4" />,
      hidden: !isTerminal,
    },
  ];

  return (
    <div
      className="flex gap-1 rounded-lg p-1"
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {tabs
        .filter((t) => !t.hidden)
        .map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              data-testid={`tab-${tab.id}`}
              onClick={() => onTabChange(tab.id)}
              className={cn(
                "flex items-center gap-2 px-5 py-2.5 rounded-md text-sm font-medium transition-all duration-200 relative",
                isActive && "shadow-sm"
              )}
              style={{
                background: isActive ? "var(--bg-elevated)" : "transparent",
                color: isActive ? "var(--accent-primary)" : "var(--text-muted)",
                borderBottom: isActive ? "3px solid var(--accent-primary)" : "3px solid transparent",
              }}
            >
              {tab.icon}
              {tab.label}
            </button>
          );
        })}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Overview Tab                                                        */
/* ------------------------------------------------------------------ */

function OverviewTab({
  claim,
  canApprove,
  approverName,
  setApproverName,
  approvalNotes,
  setApprovalNotes,
  submittingApproval,
  approvalError,
  handleApproval,
}: {
  claim: ClaimData;
  canApprove: boolean;
  approverName: string;
  setApproverName: (v: string) => void;
  approvalNotes: string;
  setApprovalNotes: (v: string) => void;
  submittingApproval: boolean;
  approvalError: string | null;
  handleApproval: (decision: "approve" | "deny" | "escalate") => void;
}) {
  const imageUrl = claim.file_path
    ? `${API_BASE}/uploads/${claim.file_path.split("/").pop()}`
    : null;
  const isImage = claim.file_type?.startsWith("image/");

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Side-by-side Evidence View */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Document preview */}
        <div className="card p-6">
          <h3
            className="type-section-title mb-4 flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <FileImage className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />
            Submitted Document
          </h3>
          {imageUrl && isImage ? (
            <div
              className="rounded-lg overflow-hidden"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
              }}
            >
              <Image
                src={imageUrl}
                alt="Claim document"
                width={1200}
                height={900}
                sizes="(max-width: 1024px) 100vw, 50vw"
                className="w-full h-auto max-h-96 object-contain"
              />
            </div>
          ) : (
            <div
              className="flex items-center justify-center h-48 rounded-lg"
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
              }}
            >
              <div className="text-center">
                <File
                  className="w-12 h-12 mx-auto mb-2"
                  style={{ color: "var(--text-muted)" }}
                  strokeWidth={1}
                />
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {claim.file_type || "Document uploaded"}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Right: AI-extracted data */}
        <div className="card p-6">
          <h3
            className="type-section-title mb-4 flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <Sparkles className="w-5 h-5" style={{ color: "var(--risk-low)" }} />
            AI-Extracted Data
          </h3>

          {claim.extracted_data ? (
            <div className="space-y-3">
              {claim.extracted_data.document_type && (
                <DataField label="Document Category" value={claim.extracted_data.document_type} />
              )}
              {claim.extracted_data.damage_type && (
                <DataField label="Document Sub-type" value={claim.extracted_data.damage_type} />
              )}
              {claim.extracted_data.vehicle_info && (
                <DataField label="Provider" value={claim.extracted_data.vehicle_info} />
              )}
              {claim.extracted_data.estimated_cost !== undefined &&
                claim.extracted_data.estimated_cost > 0 && (
                  <DataField
                    label="Total Billed"
                    value={`$${claim.extracted_data.estimated_cost.toLocaleString()}`}
                  />
                )}
              {claim.extracted_data.incident_details && (
                <DataField label="Line Items / Description" value={claim.extracted_data.incident_details} />
              )}
              {claim.extracted_data.key_findings &&
                claim.extracted_data.key_findings.length > 0 && (
                  <div
                    className="pt-3 mt-3"
                    style={{ borderTop: "1px solid var(--border-subtle)" }}
                  >
                    <span className="label block mb-2">Notable Findings</span>
                    <ul className="space-y-1.5">
                      {claim.extracted_data.key_findings.map((finding, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm">
                          <Check
                            className="w-4 h-4 mt-0.5 flex-shrink-0"
                            style={{ color: "var(--risk-low)" }}
                            strokeWidth={2}
                          />
                          <span style={{ color: "var(--text-primary)" }}>{finding}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="h-4 skeleton w-full"></div>
              <div className="h-4 skeleton w-3/4"></div>
              <div className="h-4 skeleton w-5/6"></div>
            </div>
          )}
        </div>
      </div>

      {/* Coverage Details */}
      {claim.coverage_result && (
        <div className="card p-6">
          <h3
            className="type-section-title mb-4 flex items-center gap-2"
            style={{ color: "var(--text-primary)" }}
          >
            <Shield className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />
            Coverage Details
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div>
              <span className="label block mb-1">Coverage Status</span>
              <span
                className="text-sm font-semibold"
                style={{
                  color: claim.coverage_result.covered
                    ? "var(--risk-low)"
                    : "var(--risk-critical)",
                }}
              >
                {claim.coverage_result.covered ? "Covered" : "Not Covered"}
              </span>
            </div>
            <div>
              <span className="label block mb-1">Coverage Type</span>
              <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                {claim.coverage_result.coverage_type}
              </span>
            </div>
            <div>
              <span className="label block mb-1">Deductible</span>
              <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                {formatCurrency(claim.coverage_result.deductible)}
              </span>
            </div>
            <div>
              <span className="label block mb-1">Coverage Limit</span>
              <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                {formatCurrency(claim.coverage_result.coverage_limit)}
              </span>
            </div>
          </div>
          <p
            className="text-sm mt-4 pt-4"
            style={{
              color: "var(--text-secondary)",
              borderTop: "1px solid var(--border-subtle)",
            }}
          >
            {claim.coverage_result.explanation}
          </p>
        </div>
      )}

      {/* Approval Panel */}
      {canApprove && (
        <div className="card p-6 animate-fade-in" data-testid="approval-panel">
          <h3
            className="type-section-title mb-1"
            style={{ color: "var(--text-primary)" }}
          >
            Advocate Action Panel
          </h3>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
            Review the findings and choose an action on behalf of the patient
          </p>

          {/* AI Recommendation */}
          {claim.risk_assessment && (
            <div className="glass-panel p-4 mb-6">
              <div className="flex items-start gap-3">
                <div
                  className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                  style={{ background: "var(--accent-primary-bg)" }}
                >
                  <Sparkles
                    className="w-4 h-4"
                    style={{ color: "var(--accent-primary)" }}
                  />
                </div>
                <div>
                  <h4
                    className="text-sm font-semibold mb-1"
                    style={{ color: "var(--accent-primary)" }}
                  >
                    Sovereign Recommendation
                  </h4>
                  <p
                    className="text-lg font-bold"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {claim.risk_assessment.recommended_action
                      .replace(/_/g, " ")
                      .replace(/\b\w/g, (c) => c.toUpperCase())}
                  </p>
                  <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
                    {claim.risk_assessment.reasoning}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Approval form */}
          <div className="space-y-4">
            <div>
              <label
                className="block text-sm font-medium mb-2"
                style={{ color: "var(--text-primary)" }}
              >
                Advocate Name{" "}
                <span style={{ color: "var(--risk-critical)" }}>*</span>
              </label>
              <input
                type="text"
                value={approverName}
                onChange={(e) => setApproverName(e.target.value)}
                placeholder="Your full name"
                className="w-full rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 transition-all"
                style={
                  {
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    color: "var(--text-primary)",
                    "--tw-ring-color": "var(--accent-primary)",
                  } as React.CSSProperties
                }
              />
            </div>

            <div>
              <label
                className="block text-sm font-medium mb-2"
                style={{ color: "var(--text-primary)" }}
              >
                Notes (optional)
              </label>
              <textarea
                value={approvalNotes}
                onChange={(e) => setApprovalNotes(e.target.value)}
                placeholder="Add any notes about your decision..."
                rows={3}
                className="w-full rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:ring-2 transition-all resize-none"
                style={
                  {
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    color: "var(--text-primary)",
                    "--tw-ring-color": "var(--accent-primary)",
                  } as React.CSSProperties
                }
              />
            </div>

            {approvalError && (
              <div
                className="rounded-lg p-3"
                style={{
                  background: "var(--risk-critical-bg)",
                  border: "1px solid var(--risk-critical-border)",
                }}
              >
                <p className="text-sm" style={{ color: "var(--risk-critical)" }}>
                  {approvalError}
                </p>
              </div>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={() => handleApproval("approve")}
                disabled={submittingApproval}
                data-testid="btn-approve"
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center justify-center gap-2"
                style={{
                  background: submittingApproval
                    ? "var(--bg-elevated)"
                    : "var(--risk-low)",
                  color: submittingApproval ? "var(--text-muted)" : "#fff",
                }}
              >
                <Check className="w-4 h-4" />
                File Appeal
              </button>
              <button
                onClick={() => handleApproval("deny")}
                disabled={submittingApproval}
                data-testid="btn-deny"
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center justify-center gap-2"
                style={{
                  background: submittingApproval
                    ? "var(--bg-elevated)"
                    : "transparent",
                  color: submittingApproval
                    ? "var(--text-muted)"
                    : "var(--risk-critical)",
                  border: submittingApproval
                    ? "1px solid var(--border-subtle)"
                    : "1px solid var(--risk-critical)",
                }}
              >
                <AlertCircle className="w-4 h-4" />
                Dispute Bill
              </button>
              <button
                onClick={() => handleApproval("escalate")}
                disabled={submittingApproval}
                data-testid="btn-escalate"
                className="flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors flex items-center justify-center gap-2"
                style={{
                  background: submittingApproval
                    ? "var(--bg-elevated)"
                    : "transparent",
                  color: submittingApproval
                    ? "var(--text-muted)"
                    : "var(--status-escalated)",
                  border: submittingApproval
                    ? "1px solid var(--border-subtle)"
                    : "1px solid var(--status-escalated)",
                }}
              >
                <ArrowUpRight className="w-4 h-4" />
                Escalate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Analysis Tab                                                        */
/* ------------------------------------------------------------------ */

function AnalysisTab({
  claim,
  claimId,
}: {
  claim: ClaimData;
  claimId: string;
}) {
  const fraudSignals = getFraudSignals(claim);
  const numericScore = getNumericFraudScore(claim.fraud_score);

  return (
    <div className="space-y-8 animate-fade-in">
      {/* Findings section */}
      <section aria-labelledby="findings-heading">
        <h2
          id="findings-heading"
          className="text-xs font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Findings
        </h2>
        <WebInvestigation signals={fraudSignals} />
      </section>

      {/* Severity + Recovery side by side */}
      <section aria-labelledby="severity-recovery-heading">
        <h2
          id="severity-recovery-heading"
          className="text-xs font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Severity &amp; Recovery Simulation
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <RiskRadar
            fraudScore={numericScore}
            riskLevel={claim.risk_level}
            riskAssessment={claim.risk_assessment}
          />
          <SimulationCard simulation={claim.simulation_result} />
        </div>
      </section>

      {/* Pipeline timeline */}
      <section aria-labelledby="pipeline-heading">
        <h2
          id="pipeline-heading"
          className="text-xs font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Review Timeline
        </h2>
        <RiskTimeline claimId={claimId} status={claim.status} />
      </section>

      {/* Investigation Feed */}
      <section aria-labelledby="feed-heading">
        <h2
          id="feed-heading"
          className="text-xs font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Live Investigation Feed
        </h2>
        <InvestigationFeed key={claimId} claimId={claimId} status={claim.status} />
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Decision Tab                                                        */
/* ------------------------------------------------------------------ */

function DecisionTab({ claim }: { claim: ClaimData }) {
  if (!claim.receipt) {
    return (
      <div className="animate-fade-in">
        <h2
          className="text-xs font-semibold uppercase tracking-widest mb-4"
          style={{ color: "var(--text-muted)" }}
        >
          Signed Receipt
        </h2>
        <div
          className="card p-12 text-center"
          style={{ color: "var(--text-muted)" }}
        >
          <FileCheck className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p className="text-sm">No decision receipt available yet.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in space-y-4">
      <h2
        className="text-xs font-semibold uppercase tracking-widest"
        style={{ color: "var(--text-muted)" }}
      >
        Signed Receipt
      </h2>
      <DecisionReceipt receipt={claim.receipt} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Main Page Component                                                 */
/* ------------------------------------------------------------------ */

export default function ClaimDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const resolvedParams = use(params);
  const claimId = resolvedParams.id;

  const searchParams = useSearchParams();
  const router = useRouter();

  // Tab state from URL
  const rawTab = searchParams.get("tab");
  const activeTab: TabId = isValidTab(rawTab) ? rawTab : "overview";

  const setActiveTab = useCallback(
    (tab: TabId) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tab);
      router.push(`?${params.toString()}`, { scroll: false });
    },
    [searchParams, router]
  );

  const [claim, setClaim] = useState<ClaimData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Approval form state
  const [approverName, setApproverName] = useState("");
  const [approvalNotes, setApprovalNotes] = useState("");
  const [submittingApproval, setSubmittingApproval] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  const fetchClaim = useCallback(async () => {
    try {
      setError(null);
      const data = await getClaim(claimId);
      setClaim(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load claim");
    } finally {
      setLoading(false);
    }
  }, [claimId]);

  useEffect(() => {
    fetchClaim();
  }, [fetchClaim]);

  // Poll for updates while processing
  useEffect(() => {
    const activeStatuses: ClaimData["status"][] = ["processing", "submitted"];
    if (!claim || !activeStatuses.includes(claim.status))
      return;

    let mounted = true;
    const interval = setInterval(async () => {
      try {
        const data = await getClaim(claimId);
        if (mounted) setClaim(data);
      } catch {
        // silent fail on poll
      }
    }, 2000);

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [claim, claimId]);

  const handleApproval = useCallback(
    async (decision: "approve" | "deny" | "escalate") => {
      if (!approverName.trim()) {
        setApprovalError("Advocate name is required");
        return;
      }

      setSubmittingApproval(true);
      setApprovalError(null);

      try {
        await submitApproval({
          claim_id: claimId,
          decision,
          approver_name: approverName.trim(),
          notes: approvalNotes.trim() || undefined,
        });
        const data = await getClaim(claimId);
        setClaim(data);
      } catch (err) {
        setApprovalError(
          err instanceof Error ? err.message : "Failed to submit decision"
        );
      } finally {
        setSubmittingApproval(false);
      }
    },
    [claimId, approverName, approvalNotes]
  );

  /* ---- Loading state ---- */
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 skeleton w-64 mb-2"></div>
        <div className="h-4 skeleton w-96"></div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mt-6">
          <SectionSkeleton height="h-64" />
          <SectionSkeleton height="h-64" />
        </div>
        <SectionSkeleton height="h-80" />
      </div>
    );
  }

  /* ---- Error state ---- */
  if (error || !claim) {
    return (
      <div
        className="rounded-xl p-12 text-center"
        style={{
          background: "var(--risk-critical-bg)",
          border: "1px solid var(--risk-critical-border)",
        }}
      >
        <AlertCircle
          className="w-12 h-12 mx-auto mb-4"
          style={{ color: "var(--risk-critical)" }}
          strokeWidth={1.5}
        />
        <h2
          className="text-xl font-bold mb-2"
          style={{ color: "var(--risk-critical)" }}
        >
          Unable to load case
        </h2>
        <p
          className="mb-4"
          style={{ color: "var(--risk-critical)", opacity: 0.7 }}
        >
          {error || "Case not found"}
        </p>
        <button
          onClick={fetchClaim}
          className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
          style={{
            background: "var(--risk-critical)",
            color: "#ffffff",
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  /* ---- Derived state ---- */
  const fraudScore = getNumericFraudScore(claim.fraud_score);
  const fraudScoreColor = getRiskColor(fraudScore);
  const isTerminal =
    claim.status === "approved" ||
    claim.status === "auto_approved" ||
    claim.status === "denied" ||
    claim.status === "blocked" ||
    claim.status === "analyzed" ||
    claim.status === "ready" ||
    claim.status === "needs_consent";
  const canApprove =
    claim.status === "pending_review" ||
    claim.status === "escalated" ||
    claim.status === "analyzed" ||
    claim.status === "ready" ||
    claim.status === "needs_consent";

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Hero: Pipeline Stepper (full width) */}
      <PipelineStepper claimId={claimId} status={claim.status} />

      {/* Case Header Card */}
      <div className="card p-6" data-testid="claim-header">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1
                className="text-xl font-bold"
                style={{ color: "var(--text-primary)" }}
              >
                {claim.claimant_name}
              </h1>
              <StatusBadge status={claim.status} size="md" />
            </div>
            <div
              className="flex items-center gap-4 text-sm flex-wrap"
              style={{ color: "var(--text-secondary)" }}
            >
              <span
                className="font-mono text-xs px-2 py-1 rounded"
                style={{ background: "var(--bg-elevated)" }}
              >
                {claim.id}
              </span>
              <span>{formatClaimDate(claim.created_at, "long")}</span>
              {claim.policy_number && (
                <span>
                  Member ID:{" "}
                  <span style={{ color: "var(--text-primary)" }}>
                    {claim.policy_number}
                  </span>
                </span>
              )}
            </div>
          </div>
          {fraudScore !== null && fraudScore !== undefined && (
            <div className="flex-shrink-0 text-right">
              <div
                className="text-4xl font-bold tabular-nums leading-none"
                style={{
                  color: fraudScoreColor,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {Math.round(fraudScore)}
                <span className="text-xl font-normal" style={{ color: "var(--text-muted)" }}>
                  /100
                </span>
              </div>
              <div
                className="text-[10px] font-semibold uppercase tracking-widest mt-1"
                style={{ color: "var(--text-muted)" }}
              >
                Overcharge Score
              </div>
            </div>
          )}
        </div>
        {claim.incident_description && (
          <p
            className="mt-4 text-sm pt-4"
            style={{
              color: "var(--text-secondary)",
              borderTop: "1px solid var(--border-subtle)",
            }}
          >
            {claim.incident_description}
          </p>
        )}
      </div>

      {/* Tab Navigation */}
      <TabNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
        isTerminal={isTerminal}
      />

      {/* Tab Content */}
      <div data-testid={`tab-content-${activeTab}`}>
        {activeTab === "overview" && (
          <OverviewTab
            claim={claim}
            canApprove={canApprove}
            approverName={approverName}
            setApproverName={setApproverName}
            approvalNotes={approvalNotes}
            setApprovalNotes={setApprovalNotes}
            submittingApproval={submittingApproval}
            approvalError={approvalError}
            handleApproval={handleApproval}
          />
        )}
        {activeTab === "analysis" && (
          <AnalysisTab claim={claim} claimId={claimId} />
        )}
        {activeTab === "decision" && isTerminal && <DecisionTab claim={claim} />}
      </div>
    </div>
  );
}
