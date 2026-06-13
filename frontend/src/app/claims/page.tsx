"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { Plus, Filter, ArrowRight, Clock, AlertTriangle } from "lucide-react";
import { getClaims } from "@/lib/api";
import { ClaimData } from "@/lib/types";
import {
  cn,
  getRiskColor,
  getRelativeTime,
  getAgeColor,
  formatCurrency,
  getNumericFraudScore,
} from "@/lib/utils";
import StatusBadge from "@/components/StatusBadge";

/* ── Filter types ───────────────────────────────── */
type FilterTab = "all" | "pending" | "approved" | "denied" | "escalated";

const tabs: { key: FilterTab; label: string }[] = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "approved", label: "Approved" },
  { key: "denied", label: "Denied" },
  { key: "escalated", label: "Escalated" },
];

function filterClaims(claims: ClaimData[], tab: FilterTab): ClaimData[] {
  switch (tab) {
    case "pending":
      return claims.filter(
        (c) =>
          c.status === "submitted" ||
          c.status === "processing" ||
          c.status === "pending_review"
      );
    case "approved":
      return claims.filter(
        (c) => c.status === "approved" || c.status === "auto_approved"
      );
    case "denied":
      return claims.filter((c) => c.status === "denied");
    case "escalated":
      return claims.filter((c) => c.status === "escalated");
    default:
      return claims;
  }
}

/* ── Skeleton row ───────────────────────────────── */
function SkeletonRow() {
  return (
    <div
      className="flex items-center gap-4 px-5 py-4"
      style={{ borderBottom: "1px solid var(--border-subtle)" }}
    >
      <div className="flex-1 space-y-2">
        <div className="h-4 skeleton w-40"></div>
        <div className="h-3 skeleton w-56"></div>
      </div>
      <div className="h-5 skeleton w-20 rounded-full"></div>
      <div className="h-4 skeleton w-10"></div>
      <div className="h-4 skeleton w-16"></div>
      <div className="h-4 skeleton w-20"></div>
      <div className="h-4 skeleton w-12"></div>
    </div>
  );
}

/* ── All Cases page ─────────────────────────────── */
export default function AllClaimsPage() {
  const [claims, setClaims] = useState<ClaimData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<FilterTab>("all");

  const fetchClaims = useCallback(async () => {
    try {
      setError(null);
      const data = await getClaims();
      const list = Array.isArray(data) ? data : [];
      setClaims(list);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load cases"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchClaims();
  }, [fetchClaims]);

  const filtered = filterClaims(claims, activeTab).sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  return (
    <div data-testid="all-claims-page">
      {/* ── Header ─────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1
            className="type-page-title mb-1"
            style={{ color: "var(--text-primary)" }}
          >
            All Cases
          </h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {loading
              ? "Loading cases..."
              : `${claims.length} total case${claims.length !== 1 ? "s" : ""} \u2014 ${filtered.length} shown`}
          </p>
        </div>
        <Link
          href="/claims/submit"
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all hover:opacity-90"
          style={{
            background: "var(--accent-primary)",
            color: "var(--bg-base)",
          }}
        >
          <Plus className="w-4 h-4" />
          New Case
        </Link>
      </div>

      {/* ── Filter tabs ────────────────────────── */}
      <div className="flex items-center gap-3 mb-6">
        <Filter className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
        <div
          className="flex gap-1 rounded-xl p-1"
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          {tabs.map((tab) => {
            const isActive = activeTab === tab.key;
            const count = filterClaims(claims, tab.key).length;

            return (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  "relative px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 cursor-pointer",
                  isActive && "shadow-sm"
                )}
                style={{
                  background: isActive ? "var(--bg-elevated)" : "transparent",
                  color: isActive ? "var(--text-primary)" : "var(--text-secondary)",
                }}
                data-testid={`filter-tab-${tab.key}`}
              >
                {/* Amber active indicator */}
                {isActive && (
                  <span
                    className="absolute bottom-0 left-1/2 -translate-x-1/2 w-6 h-0.5 rounded-full"
                    style={{ background: "var(--accent-primary)" }}
                  />
                )}
                {tab.label}
                {!loading && (
                  <span
                    className="ml-1.5 text-xs"
                    style={{ color: isActive ? "var(--accent-primary)" : "var(--text-muted)" }}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── Error ──────────────────────────────── */}
      {error && (
        <div
          data-testid="claims-error"
          className="rounded-xl p-6 mb-6 text-center"
          style={{
            background: "var(--risk-critical-bg)",
            border: "1px solid var(--risk-critical-border)",
          }}
        >
          <AlertTriangle className="w-6 h-6 mx-auto mb-2" style={{ color: "var(--risk-critical)" }} />
          <p className="mb-3 text-sm" style={{ color: "var(--risk-critical)" }}>{error}</p>
          <button
            onClick={() => {
              setLoading(true);
              fetchClaims();
            }}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors cursor-pointer"
            style={{
              background: "var(--risk-critical)",
              color: "#ffffff",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Claims list ────────────────────────── */}
      <div className="card overflow-hidden" data-testid="claims-list">
        {/* Table header */}
        <div
          className="hidden md:grid grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-4 px-5 py-3"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <span className="label">Case</span>
          <span className="label w-28 text-center">Status</span>
          <span className="label w-20 text-right">Error Score</span>
          <span className="label w-24 text-right">Recoverable</span>
          <span className="label w-24 text-right">Date</span>
          <span className="label w-8 text-right sr-only">View</span>
        </div>

        {/* Loading skeletons */}
        {loading && (
          <div>
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} />
            ))}
          </div>
        )}

        {/* Claim rows */}
        {!loading && filtered.length > 0 && (
          <div className="stagger-children">
            {filtered.map((claim) => {
              const fraudScore = getNumericFraudScore(claim.fraud_score);
              const fraudColor = getRiskColor(fraudScore);
              const amount = claim.payout_recommendation?.recommended_amount;
              const relativeTime = getRelativeTime(new Date(claim.created_at));
              const ageColor = getAgeColor(claim.created_at);

              return (
                <Link
                  key={claim.id}
                  href={`/claims/${claim.id}`}
                  className="block transition-colors duration-150 hover:bg-[var(--bg-elevated)]"
                  data-testid={`claim-row-${claim.id}`}
                >
                  <div
                    className="grid grid-cols-1 md:grid-cols-[1fr_auto_auto_auto_auto_auto] items-center gap-3 md:gap-4 px-5 py-4"
                    style={{
                      borderBottom: "1px solid var(--border-subtle)",
                    }}
                  >
                    {/* Claim info */}
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 mb-0.5">
                        <span
                          className="font-semibold text-sm truncate"
                          style={{ color: "var(--text-primary)" }}
                        >
                          {claim.claimant_name}
                        </span>
                      </div>
                      <span
                        className="font-mono text-xs tracking-wide"
                        style={{ color: "var(--text-muted)" }}
                      >
                        {claim.id.length > 20
                          ? `${claim.id.slice(0, 20)}...`
                          : claim.id}
                      </span>
                      {claim.incident_description && (
                        <p
                          className="text-xs line-clamp-1 mt-1 md:hidden"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {claim.incident_description}
                        </p>
                      )}
                    </div>

                    {/* Status */}
                    <div className="w-28 flex justify-center">
                      <StatusBadge status={claim.status} size="sm" />
                    </div>

                    {/* Fraud score */}
                    <div className="w-20 text-right">
                      <span
                        className="font-bold text-sm tabular-nums"
                        style={{
                          color: fraudColor,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {fraudScore !== null && fraudScore !== undefined
                          ? Math.round(fraudScore)
                          : <span style={{ color: "var(--text-muted)" }}>—</span>}
                      </span>
                    </div>

                    {/* Amount */}
                    <div className="w-24 text-right">
                      <span
                        className="text-sm font-semibold tabular-nums"
                        style={{
                          color: amount !== undefined && amount !== null
                            ? "var(--recovered)"
                            : "var(--text-muted)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {formatCurrency(amount)}
                      </span>
                    </div>

                    {/* Date with age color */}
                    <div className="w-24 flex items-center justify-end gap-1.5">
                      <Clock className="w-3 h-3 flex-shrink-0" style={{ color: ageColor }} aria-hidden="true" />
                      <span
                        className="text-xs font-medium"
                        style={{ color: ageColor }}
                      >
                        {relativeTime}
                      </span>
                    </div>

                    {/* Action arrow */}
                    <div className="w-8 flex justify-end">
                      <ArrowRight
                        className="w-4 h-4 transition-transform duration-200"
                        style={{ color: "var(--text-muted)" }}
                        aria-hidden="true"
                      />
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        )}

        {/* Empty state */}
        {!loading && filtered.length === 0 && (
          <div className="p-12 text-center animate-fade-in" data-testid="claims-empty">
            <div
              className="w-12 h-12 rounded-xl flex items-center justify-center mx-auto mb-3"
              style={{ background: "var(--accent-primary-bg)" }}
            >
              <Filter className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />
            </div>
            <p
              className="text-sm font-medium mb-1"
              style={{ color: "var(--text-secondary)" }}
            >
              No cases match this filter
            </p>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              Try selecting a different tab or start a new case.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
