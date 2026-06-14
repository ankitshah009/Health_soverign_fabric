/**
 * Shared utility functions for Sovereign frontend.
 */

import type { FraudScore, FraudSignal } from "./types";

/** Combine class names, filtering out falsy values */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

/**
 * Extract numeric fraud score from a claim's fraud_score field,
 * which may be a plain number or a FraudScore object.
 */
export function getNumericFraudScore(
  fs: number | FraudScore | null | undefined
): number | null {
  if (fs === null || fs === undefined) return null;
  if (typeof fs === "number") return fs;
  return fs.overall_score ?? null;
}

/**
 * Extract fraud signals from a FraudScore object.
 * Returns empty array if fraud_score is a plain number or null.
 */
export function extractFraudSignals(
  fs: number | FraudScore | null | undefined
): FraudSignal[] {
  if (fs === null || fs === undefined || typeof fs === "number") return [];
  return fs.signals ?? [];
}

/** Get risk color CSS variable for a fraud score */
export function getRiskColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return "var(--text-muted)";
  if (score >= 80) return "var(--risk-critical)";
  if (score >= 60) return "var(--risk-high)";
  if (score >= 30) return "var(--risk-medium)";
  return "var(--risk-low)";
}

/** Get risk background color CSS variable for a fraud score */
export function getRiskBgColor(score: number | null | undefined): string {
  if (score === null || score === undefined) return "transparent";
  if (score >= 80) return "var(--risk-critical-bg)";
  if (score >= 60) return "var(--risk-high-bg)";
  if (score >= 30) return "var(--risk-medium-bg)";
  return "var(--risk-low-bg)";
}

/** Get risk card class for a fraud score */
export function getRiskCardClass(score: number | null | undefined): string {
  if (score === null || score === undefined) return "";
  if (score >= 80) return "card-risk-critical";
  if (score >= 60) return "card-risk-high";
  if (score >= 30) return "card-risk-medium";
  return "card-risk-low";
}

/** Format a date for claim display */
export function formatClaimDate(
  date: string | Date,
  style: "short" | "long" | "relative" = "short"
): string {
  const d = typeof date === "string" ? new Date(date) : date;

  if (style === "relative") {
    return getRelativeTime(d);
  }

  if (style === "long") {
    return d.toLocaleString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Get relative time string with urgency level */
export function getRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return `${Math.floor(diffDays / 7)}w ago`;
}

/** Get neutral age color based on claim age.
 *  Routine timestamps must NOT use risk-critical/high — that implies an error.
 *  All values stay in the neutral text ramp so demo data looks clean. */
export function getAgeColor(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const hoursOld = (Date.now() - d.getTime()) / 3600000;

  if (hoursOld < 2) return "var(--text-tertiary)";
  if (hoursOld < 8) return "var(--text-tertiary)";
  if (hoursOld < 24) return "var(--text-muted)";
  return "var(--text-muted)";
}

/** Format currency amount */
export function formatCurrency(amount: number | undefined | null): string {
  if (amount === undefined || amount === null) return "--";
  if (amount >= 1_000_000) return `$${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `$${(amount / 1_000).toFixed(1)}K`;
  return `$${amount.toLocaleString()}`;
}
