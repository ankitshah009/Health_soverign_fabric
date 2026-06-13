"use client";

import Link from "next/link";
import { Clock } from "lucide-react";
import { ClaimData } from "@/lib/types";
import {
  cn,
  getRiskColor,
  getRelativeTime,
  getAgeColor,
  formatCurrency,
  getNumericFraudScore,
} from "@/lib/utils";
import StatusBadge from "./StatusBadge";

interface ClaimCardProps {
  claim: ClaimData;
}

export default function ClaimCard({ claim }: ClaimCardProps) {
  const fraudScore = getNumericFraudScore(claim.fraud_score);
  const fraudColor = getRiskColor(fraudScore);
  const relativeTime = getRelativeTime(new Date(claim.created_at));
  const ageColor = getAgeColor(claim.created_at);
  const amount = claim.payout_recommendation?.recommended_amount;

  return (
    <Link
      href={`/claims/${claim.id}`}
      aria-label={`View case for ${claim.claimant_name}${fraudScore !== null ? `, error score ${Math.round(fraudScore)}` : ""}`}
    >
      <div
        className={cn(
          "cursor-pointer group rounded-xl p-5 transition-all duration-[180ms]",
          "border"
        )}
        style={{
          background: "var(--bg-surface)",
          borderColor: "var(--border-subtle)",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.background = "var(--bg-elevated)";
          (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-default)";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.background = "var(--bg-surface)";
          (e.currentTarget as HTMLDivElement).style.borderColor = "var(--border-subtle)";
        }}
        data-testid={`claim-card-${claim.id}`}
      >
        {/* ── Top row: name + status badge ── */}
        <div className="flex items-start justify-between mb-2.5">
          <div className="flex-1 min-w-0 mr-3">
            <div className="flex items-center gap-2 mb-1">
              <h3
                className="text-sm font-semibold truncate transition-colors duration-150 group-hover:text-[var(--accent-primary)]"
                style={{ color: "var(--text-primary)" }}
              >
                {claim.claimant_name}
              </h3>
            </div>
            <p
              className="type-mono tracking-wide"
              style={{ color: "var(--text-muted)" }}
            >
              {claim.id.length > 16 ? `${claim.id.slice(0, 16)}...` : claim.id}
            </p>
          </div>

          <StatusBadge status={claim.status} size="sm" />
        </div>

        {/* ── Description ──────────────────────── */}
        {claim.incident_description && (
          <p
            className="text-xs leading-relaxed line-clamp-2 mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            {claim.incident_description}
          </p>
        )}

        {/* ── Footer: time left | score | recoverable ───── */}
        <div
          className="flex items-center justify-between pt-3"
          style={{ borderTop: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-1.5">
            <Clock className="w-3 h-3" style={{ color: ageColor }} aria-hidden="true" />
            <span
              className="text-xs font-medium"
              style={{ color: ageColor }}
            >
              {relativeTime}
            </span>
          </div>

          <div className="flex items-center gap-3">
            {fraudScore !== null && fraudScore !== undefined && (
              <span
                className="text-xs font-semibold stat-value tabular-nums"
                style={{ color: fraudColor }}
                title={`Error score: ${Math.round(fraudScore)}/100`}
              >
                {Math.round(fraudScore)}<span style={{ color: "var(--text-muted)", fontWeight: 400 }}>/100</span>
              </span>
            )}

            {amount !== undefined && amount !== null && (
              <span
                className="text-sm font-bold stat-value tabular-nums"
                style={{ color: "var(--accent-primary)" }}
              >
                {formatCurrency(amount)}
              </span>
            )}
          </div>
        </div>
      </div>
    </Link>
  );
}
