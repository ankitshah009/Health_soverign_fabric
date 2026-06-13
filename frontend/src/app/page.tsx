"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Plus,
  Inbox,
  ImagePlus,
  X,
  Check,
} from "lucide-react";
import { getClaims, uploadPendingFile, clearPendingFile } from "@/lib/api";
import { ClaimData } from "@/lib/types";
import { cn, getNumericFraudScore } from "@/lib/utils";
import ClaimCard from "@/components/ClaimCard";
import DemoTrigger from "@/components/DemoTrigger";

/* ── Animated counter hook ──────────────────────── */
function useAnimatedCounter(target: number, duration: number = 600): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const safeTarget = Number.isFinite(target) ? target : 0;

    if (safeTarget === 0) {
      const frameId = requestAnimationFrame(() => {
        setCount(0);
      });

      return () => cancelAnimationFrame(frameId);
    }

    let frameId = 0;
    const startTime = performance.now();

    function animate(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);

      setCount(Math.round(eased * safeTarget));

      if (progress < 1) {
        frameId = requestAnimationFrame(animate);
      }
    }

    frameId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frameId);
    };
  }, [target, duration]);

  return count;
}

/* ── Summary types ──────────────────────────────── */
interface SummaryStats {
  total: number;
  pending: number;
  approved: number;
  flagged: number;
}

/* ── Stat card ──────────────────────────────────── */
interface StatCardProps {
  label: string;
  value: number;
  icon: React.ReactNode;
  iconColor: string;
  iconBg: string;
}

function StatCard({ label, value, icon, iconColor, iconBg }: StatCardProps) {
  const animatedValue = useAnimatedCounter(value);

  return (
    <div className="card p-5 group" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="label">{label}</p>
          <p
            className="text-3xl type-stat"
            style={{ color: iconColor }}
          >
            {animatedValue}
          </p>
        </div>
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center transition-transform duration-200 group-hover:scale-110"
          style={{ backgroundColor: iconBg }}
        >
          {icon}
        </div>
      </div>
    </div>
  );
}

/* ── Skeleton components ────────────────────────── */
function SkeletonCard() {
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between">
        <div className="space-y-2 flex-1">
          <div className="h-4 skeleton w-24"></div>
          <div className="h-8 skeleton w-16"></div>
        </div>
        <div className="w-11 h-11 skeleton rounded-xl"></div>
      </div>
    </div>
  );
}

function SkeletonClaimCard() {
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between mb-3">
        <div className="space-y-2 flex-1">
          <div className="h-4 skeleton w-40"></div>
          <div className="h-3 skeleton w-56"></div>
        </div>
        <div className="h-8 w-12 skeleton rounded"></div>
      </div>
      <div className="h-3 skeleton w-full mb-2"></div>
      <div className="h-3 skeleton w-2/3"></div>
    </div>
  );
}

/* ── Greeting helper ────────────────────────────── */
function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/* ── Dashboard page ─────────────────────────────── */
export default function DashboardPage() {
  const [claims, setClaims] = useState<ClaimData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pending file state for voice/chat photo uploads
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pendingPreview, setPendingPreview] = useState<string | null>(null);
  const [pendingUploading, setPendingUploading] = useState(false);
  const [pendingReady, setPendingReady] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchClaims = useCallback(async () => {
    try {
      setError(null);
      const data = await getClaims();
      const list = Array.isArray(data) ? data : [];
      setClaims(list);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load claims"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchClaims();
  }, [fetchClaims]);

  const handlePendingFile = useCallback(async (file: File) => {
    // Only accept images
    if (!file.type.startsWith("image/")) return;
    setPendingFile(file);
    setPendingPreview(URL.createObjectURL(file));
    setPendingUploading(true);
    try {
      await uploadPendingFile(file);
      setPendingReady(true);
    } catch {
      setPendingFile(null);
      setPendingPreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    } finally {
      setPendingUploading(false);
    }
  }, []);

  const handleRemovePending = useCallback(async () => {
    if (pendingPreview) URL.revokeObjectURL(pendingPreview);
    setPendingFile(null);
    setPendingPreview(null);
    setPendingReady(false);
    try {
      await clearPendingFile();
    } catch {
      // ignore
    }
  }, [pendingPreview]);

  const stats: SummaryStats = {
    total: claims.length,
    pending: claims.filter(
      (c) =>
        c.status === "processing" ||
        c.status === "pending_review" ||
        c.status === "submitted"
    ).length,
    approved: claims.filter((c) => c.status === "approved" || c.status === "auto_approved").length,
    flagged: claims.filter(
      (c) => {
        const score = getNumericFraudScore(c.fraud_score);
        return score !== null && score >= 60;
      }
    ).length,
  };

  const needsAttention = claims.filter(
    (c) => c.status === "pending_review" || c.status === "escalated"
  ).sort(
    (a, b) =>
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );

  const recentClaims = [...claims]
    .sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
    .slice(0, 9);

  const attentionCount = needsAttention.length;

  return (
    <div data-testid="dashboard-page">
      {/* ── Header ─────────────────────────────── */}
      <div className="mb-8 flex items-start justify-between gap-4 flex-wrap" data-testid="dashboard-header">
        <div>
          <h1 className="type-page-title mb-1" style={{ color: "var(--text-primary)" }}>
            {loading
              ? "Loading dashboard..."
              : `${getGreeting()} \u2014 ${attentionCount > 0 ? `${attentionCount} case${attentionCount !== 1 ? "s" : ""} need${attentionCount === 1 ? "s" : ""} your attention` : "all clear for now"}`}
          </h1>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Your AI patient advocate — with a provable conscience.
          </p>
        </div>
        <div className="flex-shrink-0 pt-1">
          <DemoTrigger />
        </div>
      </div>

      {/* ── Summary stat cards ─────────────────── */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8 stagger-children">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8 stagger-children">
          <StatCard
            label="Total Cases"
            value={stats.total}
            iconColor="var(--accent-primary)"
            iconBg="var(--accent-primary-bg)"
            icon={<FileText className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />}
          />
          <StatCard
            label="Pending Review"
            value={stats.pending}
            iconColor="var(--risk-medium)"
            iconBg="var(--risk-medium-bg)"
            icon={<Clock className="w-5 h-5" style={{ color: "var(--risk-medium)" }} />}
          />
          <StatCard
            label="Approved"
            value={stats.approved}
            iconColor="var(--risk-low)"
            iconBg="var(--risk-low-bg)"
            icon={<CheckCircle2 className="w-5 h-5" style={{ color: "var(--risk-low)" }} />}
          />
          <StatCard
            label="Overcharge Flagged"
            value={stats.flagged}
            iconColor="var(--risk-critical)"
            iconBg="var(--risk-critical-bg)"
            icon={<AlertTriangle className="w-5 h-5" style={{ color: "var(--risk-critical)" }} />}
          />
        </div>
      )}

      {/* ── Pending photo drop zone ────────────── */}
      {!loading && (
        <div className="mb-8" data-testid="pending-photo-section">
          {!pendingReady ? (
            <div
              className={cn(
                "rounded-xl border-2 border-dashed p-6 text-center transition-all duration-200 cursor-pointer",
                dragOver
                  ? "border-amber-400 bg-amber-400/10"
                  : "border-[var(--border-secondary)] hover:border-amber-400/60 hover:bg-amber-400/5"
              )}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files?.[0];
                if (file) handlePendingFile(file);
              }}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                aria-label="Upload a medical bill or EOB image to use with voice or chat"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handlePendingFile(file);
                }}
              />
              <div className="flex flex-col items-center gap-2">
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center"
                  style={{ background: "var(--accent-primary-bg)" }}
                >
                  <ImagePlus className="w-6 h-6" style={{ color: "var(--accent-primary)" }} />
                </div>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {pendingUploading
                    ? "Uploading..."
                    : "Drop a medical bill or EOB here to use with voice or chat"}
                </p>
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Accepts JPG, PNG, HEIC up to 10 MB
                </p>
              </div>
            </div>
          ) : (
            <div
              className="rounded-xl p-4 flex items-center gap-4 animate-fade-in"
              style={{
                background: "var(--bg-card)",
                border: "2px solid #d97706",
                boxShadow: "0 0 16px rgba(217,119,6,0.25)",
              }}
            >
              {pendingPreview && (
                <div className="relative w-20 h-20 flex-shrink-0 rounded-lg overflow-hidden">
                  <Image
                    src={pendingPreview}
                    alt="Pending bill document"
                    fill
                    className="object-cover"
                  />
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <Check className="w-4 h-4 text-amber-500 flex-shrink-0" />
                  <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                    {pendingFile?.name}
                  </p>
                </div>
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  Document ready — start a voice or chat conversation to review this bill
                </p>
              </div>
              <button
                onClick={handleRemovePending}
                aria-label="Remove uploaded document"
                className="w-11 h-11 rounded-lg flex items-center justify-center transition-colors hover:bg-white/10 flex-shrink-0 cursor-pointer"
                title="Remove photo"
              >
                <X className="w-4 h-4" style={{ color: "var(--text-muted)" }} aria-hidden="true" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* ── Error state ────────────────────────── */}
      {error && (
        <div
          data-testid="dashboard-error"
          className="rounded-xl p-6 mb-8 text-center"
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
              color: "var(--text-primary)",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Needs Attention section ────────────── */}
      {!loading && needsAttention.length > 0 && (
        <div className="mb-8" data-testid="needs-attention-section">
          <div className="flex items-center gap-2 mb-4">
            <div
              className="w-2 h-2 rounded-full animate-pulse-glow"
              style={{ background: "var(--accent-primary)" }}
            />
            <h2
              className="type-section-title"
              style={{ color: "var(--text-primary)" }}
            >
              Needs Attention
            </h2>
            <span
              className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{
                color: "var(--accent-primary)",
                background: "var(--accent-primary-bg)",
                border: "1px solid var(--accent-primary-border)",
              }}
            >
              {needsAttention.length}
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 stagger-children">
            {needsAttention.slice(0, 6).map((claim) => (
              <ClaimCard key={claim.id} claim={claim} />
            ))}
          </div>
        </div>
      )}

      {/* ── Recent claims ──────────────────────── */}
      <div data-testid="recent-claims-section">
        <div className="flex items-center justify-between mb-4">
          <h2
            className="type-section-title"
            style={{ color: "var(--text-primary)" }}
          >
            Recent Cases
          </h2>
          <Link
            href="/claims"
            aria-label="View all cases"
            className="inline-flex items-center gap-1.5 text-sm font-medium transition-colors hover:opacity-80"
            style={{ color: "var(--accent-primary)" }}
          >
            View all
            <ArrowRight className="w-4 h-4" aria-hidden="true" />
          </Link>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 stagger-children">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonClaimCard key={i} />
            ))}
          </div>
        ) : recentClaims.length === 0 ? (
          <div className="card p-12 text-center animate-fade-in" data-testid="empty-state">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: "var(--accent-primary-bg)" }}
            >
              <Inbox className="w-8 h-8" style={{ color: "var(--accent-primary)" }} />
            </div>
            <h3
              className="type-section-title mb-2"
              style={{ color: "var(--text-primary)" }}
            >
              No cases yet
            </h3>
            <p
              className="text-sm mb-6 max-w-sm mx-auto"
              style={{ color: "var(--text-muted)" }}
            >
              Ready when you are. Submit a medical bill or denial letter and let Sovereign find every dollar you are owed.
            </p>
            <Link
              href="/claims/submit"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold btn-press"
              style={{
                background: "var(--accent-primary)",
                color: "var(--bg-base)",
              }}
            >
              <Plus className="w-4 h-4" />
              Start a Case
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 stagger-children">
            {recentClaims.map((claim) => (
              <ClaimCard key={claim.id} claim={claim} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
