"use client";

import Link from "next/link";
import { Clock } from "lucide-react";
import { ClaimData } from "@/lib/types";
import {
  cn,
  getRiskColor,
  getRiskCardClass,
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
  const riskClass = getRiskCardClass(fraudScore);
  const fraudColor = getRiskColor(fraudScore);
  const relativeTime = getRelativeTime(new Date(claim.created_at));
  const ageColor = getAgeColor(claim.created_at);
  const amount = claim.payout_recommendation?.recommended_amount;

  return (
    <Link
      href={`/claims/${claim.id}`}
      aria-label={`View case for ${claim.claimant_name}${fraudScore !== null ? `, risk score ${Math.round(fraudScore)}` : ""}`}
    >
      <div
        className={cn(
          "card card-interactive p-5 cursor-pointer group",
          riskClass
        )}
        data-testid={`claim-card-${claim.id}`}
      >
        {/* ── Top row: name + status | fraud score ── */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0 mr-4">
            <div className="flex items-center gap-2.5 mb-1.5">
              <h3
                className="text-sm font-semibold truncate transition-colors group-hover:text-[var(--accent-primary)]"
                style={{ color: "var(--text-primary)" }}
              >
                {claim.claimant_name}
              </h3>
              <StatusBadge status={claim.status} size="sm" />
            </div>
            <p
              className="type-mono tracking-wide"
              style={{ color: "var(--text-muted)" }}
            >
              {claim.id.length > 16 ? `${claim.id.slice(0, 16)}...` : claim.id}
            </p>
          </div>

          {fraudScore !== null && fraudScore !== undefined && (
            <div className="text-right flex-shrink-0">
              <div
                className="text-xl font-bold stat-value leading-none"
                style={{ color: fraudColor }}
              >
                {Math.round(fraudScore)}
              </div>
              <div
                className="type-micro mt-0.5"
                style={{ color: "var(--text-muted)" }}
              >
                Risk
              </div>
            </div>
          )}
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

        {/* ── Footer: relative time | amount ───── */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Clock className="w-3 h-3" style={{ color: ageColor }} />
            <span
              className="text-xs font-medium"
              style={{ color: ageColor }}
            >
              {relativeTime}
            </span>
          </div>

          {amount !== undefined && amount !== null && (
            <span
              className="text-xs font-semibold"
              style={{ color: "var(--text-secondary)" }}
            >
              {formatCurrency(amount)}
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
