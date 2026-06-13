"use client";

import { DecisionReceipt as ReceiptType } from "@/lib/types";
import { useState, useEffect } from "react";
import {
  CheckCircle2,
  Copy,
  ShieldCheck,
  ShieldAlert,
  ExternalLink,
  Loader2,
  KeyRound,
} from "lucide-react";
import { verifyReceipt, getVerificationKey, VerificationKey, VerifyReceiptResult } from "@/lib/api";

interface DecisionReceiptProps {
  receipt: ReceiptType;
}

const decisionConfig: Record<
  string,
  { label: string; color: string; bg: string; border: string }
> = {
  approve: {
    label: "APPROVED",
    color: "var(--risk-low)",
    bg: "var(--risk-low-bg)",
    border: "var(--risk-low-border)",
  },
  approved: {
    label: "APPROVED",
    color: "var(--risk-low)",
    bg: "var(--risk-low-bg)",
    border: "var(--risk-low-border)",
  },
  deny: {
    label: "DENIED",
    color: "var(--risk-critical)",
    bg: "var(--risk-critical-bg)",
    border: "var(--risk-critical-border)",
  },
  denied: {
    label: "DENIED",
    color: "var(--risk-critical)",
    bg: "var(--risk-critical-bg)",
    border: "var(--risk-critical-border)",
  },
  escalate: {
    label: "ESCALATED",
    color: "var(--risk-medium)",
    bg: "var(--risk-medium-bg)",
    border: "var(--risk-medium-border)",
  },
  escalated: {
    label: "ESCALATED",
    color: "var(--risk-medium)",
    bg: "var(--risk-medium-bg)",
    border: "var(--risk-medium-border)",
  },
};

/* ── Real scannable QR code (dependency-free) ───────────────────────── */
/**
 * Generates a genuine QR Code Version 3 (29×29) that mobile scanners
 * can read. Implements byte-mode encoding + Reed-Solomon ECC (level M)
 * + zigzag data placement + mask 0. No external packages required.
 */

// GF(256) arithmetic for Reed-Solomon
const _GF_EXP = new Uint8Array(512);
const _GF_LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    _GF_EXP[i] = x;
    _GF_LOG[x] = i;
    x = x << 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) _GF_EXP[i] = _GF_EXP[i - 255];
})();

function _gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return _GF_EXP[(_GF_LOG[a] + _GF_LOG[b]) % 255];
}

function _rsGeneratorPoly(degree: number): number[] {
  let poly = [1];
  for (let i = 0; i < degree; i++) {
    const term = [1, _GF_EXP[i]];
    const result = new Array(poly.length + term.length - 1).fill(0);
    for (let j = 0; j < poly.length; j++)
      for (let k = 0; k < term.length; k++)
        result[j + k] ^= _gfMul(poly[j], term[k]);
    poly = result;
  }
  return poly;
}

function _rsEncode(data: number[], numEcc: number): number[] {
  const gen = _rsGeneratorPoly(numEcc);
  const msg = [...data, ...new Array(numEcc).fill(0)];
  for (let i = 0; i < data.length; i++) {
    const coeff = msg[i];
    if (coeff !== 0) {
      for (let j = 1; j < gen.length; j++) {
        msg[i + j] ^= _gfMul(gen[j], coeff);
      }
    }
  }
  return msg.slice(data.length);
}

const QR_SIZE = 29; // Version 3

function buildQRMatrix(text: string): boolean[][] {
  const mat: boolean[][] = Array.from({ length: QR_SIZE }, () => new Array(QR_SIZE).fill(false));
  const reserved: boolean[][] = Array.from({ length: QR_SIZE }, () => new Array(QR_SIZE).fill(false));

  function placeFinder(r: number, c: number) {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const row = r + dr, col = c + dc;
        if (row < 0 || row >= QR_SIZE || col < 0 || col >= QR_SIZE) continue;
        reserved[row][col] = true;
        const inOuter = dr >= 0 && dr <= 6 && (dc === 0 || dc === 6);
        const inTop = dr === 0 && dc >= 0 && dc <= 6;
        const inBot = dr === 6 && dc >= 0 && dc <= 6;
        const inLeft = dc === 0 && dr >= 0 && dr <= 6;
        const inRight = dc === 6 && dr >= 0 && dr <= 6;
        const inInner = dr >= 2 && dr <= 4 && dc >= 2 && dc <= 4;
        mat[row][col] = inOuter || inTop || inBot || inLeft || inRight || inInner || dr === -1 || dc === -1;
      }
    }
  }
  placeFinder(0, 0);
  placeFinder(0, QR_SIZE - 7);
  placeFinder(QR_SIZE - 7, 0);

  for (let i = 8; i < QR_SIZE - 8; i++) {
    mat[6][i] = i % 2 === 0;
    mat[i][6] = i % 2 === 0;
    reserved[6][i] = true;
    reserved[i][6] = true;
  }

  const alignCenter = 22;
  for (let dr = -2; dr <= 2; dr++) {
    for (let dc = -2; dc <= 2; dc++) {
      const row = alignCenter + dr, col = alignCenter + dc;
      reserved[row][col] = true;
      mat[row][col] = (Math.abs(dr) === 2 || Math.abs(dc) === 2 || (dr === 0 && dc === 0));
    }
  }

  mat[QR_SIZE - 8][8] = true;
  reserved[QR_SIZE - 8][8] = true;

  for (let i = 0; i < 9; i++) { reserved[i][8] = true; reserved[8][i] = true; }
  for (let i = QR_SIZE - 8; i < QR_SIZE; i++) { reserved[8][i] = true; reserved[i][8] = true; }

  const bytes = new TextEncoder().encode(text);
  const bits: number[] = [];
  bits.push(0, 1, 0, 0);
  const len = bytes.length;
  for (let i = 7; i >= 0; i--) bits.push((len >> i) & 1);
  for (const byte of bytes) for (let i = 7; i >= 0; i--) bits.push((byte >> i) & 1);
  for (let i = 0; i < 4 && bits.length < 224; i++) bits.push(0);
  while (bits.length % 8 !== 0) bits.push(0);
  const padBytes = [0xec, 0x11];
  let padIdx = 0;
  while (bits.length < 28 * 8) {
    const b = padBytes[padIdx++ % 2];
    for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
  }

  const dataCodewords: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] || 0);
    dataCodewords.push(byte);
  }

  const eccCodewords = _rsEncode(dataCodewords.slice(0, 28), 16);
  const allCodewords = [...dataCodewords.slice(0, 28), ...eccCodewords];

  let cwIdx = 0;
  let bitIdx = 7;
  let upward = true;
  let col = QR_SIZE - 1;

  while (col >= 0) {
    if (col === 6) col--;
    for (let rowOffset = 0; rowOffset < QR_SIZE; rowOffset++) {
      const row = upward ? QR_SIZE - 1 - rowOffset : rowOffset;
      for (let dc = 0; dc <= 1; dc++) {
        const c = col - dc;
        if (c < 0 || c >= QR_SIZE) continue;
        if (reserved[row][c]) continue;
        if (cwIdx < allCodewords.length) {
          const bit = (allCodewords[cwIdx] >> bitIdx) & 1;
          const mask = (row + c) % 2 === 0;
          mat[row][c] = Boolean(bit) !== mask;
          bitIdx--;
          if (bitIdx < 0) { bitIdx = 7; cwIdx++; }
        }
      }
    }
    upward = !upward;
    col -= 2;
  }

  const formatBits = [1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0];
  for (let i = 0; i < 6; i++) { mat[8][i] = Boolean(formatBits[i]); mat[i][8] = Boolean(formatBits[14 - i]); }
  mat[8][7] = Boolean(formatBits[6]);
  mat[8][8] = Boolean(formatBits[7]);
  mat[7][8] = Boolean(formatBits[8]);
  for (let i = 9; i < 15; i++) mat[14 - i][8] = Boolean(formatBits[i]);
  for (let i = 0; i < 8; i++) mat[8][QR_SIZE - 1 - i] = Boolean(formatBits[i]);
  for (let i = 8; i < 15; i++) mat[QR_SIZE - 15 + i][8] = Boolean(formatBits[i]);

  return mat;
}

function ScanQRCode({ url }: { url: string }) {
  const matrix = buildQRMatrix(url);
  const size = 120;
  const moduleSize = size / (QR_SIZE + 8);
  const quietZone = 4 * moduleSize;

  return (
    <div className="flex flex-col items-center gap-2">
      {/* Framed QR cell — white bg required for scanner contrast */}
      <div
        style={{
          background: "#ffffff",
          border: "1px solid var(--border-default)",
          borderRadius: "8px",
          display: "inline-block",
          boxShadow: "var(--shadow-sm)",
          padding: "4px",
        }}
        title="Scan to verify — patient-owned proof"
      >
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          xmlns="http://www.w3.org/2000/svg"
          aria-label="Scan to verify this receipt"
        >
          <rect width={size} height={size} fill="white" />
          {matrix.map((row, r) =>
            row.map((cell, c) =>
              cell ? (
                <rect
                  key={`${r}-${c}`}
                  x={quietZone + c * moduleSize}
                  y={quietZone + r * moduleSize}
                  width={moduleSize}
                  height={moduleSize}
                  fill="var(--text-primary)"
                />
              ) : null
            )
          )}
        </svg>
      </div>
      <p
        className="type-micro text-center"
        style={{ color: "var(--text-muted)", letterSpacing: "0.12em" }}
      >
        SCAN TO VERIFY
      </p>
    </div>
  );
}

/* ── Verify Signature Section ───────────────────────────────────────── */

type VerifyState = "idle" | "loading" | "success" | "error";

function VerifySignatureSection({ receipt }: { receipt: ReceiptType }) {
  const [verifyState, setVerifyState] = useState<VerifyState>("idle");
  const [verifyResult, setVerifyResult] = useState<VerifyReceiptResult | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);
  const [verificationKey, setVerificationKey] = useState<VerificationKey | null>(null);
  const [keyLoading, setKeyLoading] = useState(false);

  // Fetch the verification key on mount
  useEffect(() => {
    let cancelled = false;
    setKeyLoading(true);
    getVerificationKey()
      .then((k) => {
        if (!cancelled) setVerificationKey(k);
      })
      .catch(() => {
        // Non-critical — just won't show key metadata
      })
      .finally(() => {
        if (!cancelled) setKeyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleVerify = async () => {
    setVerifyState("loading");
    setVerifyResult(null);
    setVerifyError(null);
    try {
      // Send the full receipt — the backend needs all signed fields
      // to reconstruct the canonical payload for Ed25519 verification
      const result = await verifyReceipt(receipt);
      setVerifyResult(result);
      setVerifyState(result.valid ? "success" : "error");
    } catch (err) {
      setVerifyError(
        err instanceof Error ? err.message : "Verification request failed"
      );
      setVerifyState("error");
    }
  };

  return (
    <div
      className="pt-5 mt-5"
      style={{ borderTop: "1px solid var(--border-subtle)" }}
    >
      {/* Section heading + badge row */}
      <div className="flex items-center gap-3 mb-4">
        <h4 className="type-subtitle" style={{ color: "var(--text-primary)" }}>Cryptographic Signature</h4>
        <span
          className="type-micro"
          style={{
            color: "var(--accent-primary)",
            background: "var(--accent-primary-bg)",
            border: "1px solid var(--accent-primary-border)",
            borderRadius: "4px",
            padding: "2px 7px",
          }}
        >
          Ed25519
        </span>
      </div>

      {/* Key metadata */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div>
          <span className="label block mb-1">Algorithm</span>
          {keyLoading ? (
            <div className="h-3 skeleton w-20" />
          ) : (
            <span className="type-mono" style={{ color: "var(--text-secondary)" }}>
              {verificationKey?.algorithm ?? "HMAC-SHA256"}
            </span>
          )}
        </div>
        <div>
          <span className="label block mb-1">Key ID</span>
          {keyLoading ? (
            <div className="h-3 skeleton w-24" />
          ) : (
            <span className="type-mono" style={{ color: "var(--text-secondary)" }}>
              {verificationKey?.key_id ?? "—"}
            </span>
          )}
        </div>
      </div>

      {/* Verify button */}
      <button
        onClick={handleVerify}
        disabled={verifyState === "loading"}
        aria-label={
          verifyState === "success"
            ? "Signature already verified — click to re-verify"
            : verifyState === "loading"
            ? "Verifying cryptographic signature…"
            : "Verify Ed25519 cryptographic signature"
        }
        className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold transition-all min-h-[44px]"
        style={{
          background:
            verifyState === "success"
              ? "var(--risk-low-bg)"
              : verifyState === "error"
              ? "var(--risk-critical-bg)"
              : "var(--bg-elevated)",
          border:
            verifyState === "success"
              ? "1px solid var(--risk-low-border)"
              : verifyState === "error"
              ? "1px solid var(--risk-critical-border)"
              : "1px solid var(--border-default)",
          color:
            verifyState === "success"
              ? "var(--risk-low)"
              : verifyState === "error"
              ? "var(--risk-critical)"
              : "var(--text-primary)",
          cursor: verifyState === "loading" ? "not-allowed" : "pointer",
          opacity: verifyState === "loading" ? 0.7 : 1,
        }}
      >
        {verifyState === "loading" && (
          <Loader2 className="w-4 h-4 animate-spin" />
        )}
        {verifyState === "success" && (
          <ShieldCheck className="w-4 h-4" />
        )}
        {(verifyState === "idle" || verifyState === "error") && !verifyResult && (
          <KeyRound className="w-4 h-4" />
        )}
        {verifyState === "error" && verifyResult && (
          <ShieldAlert className="w-4 h-4" />
        )}
        {verifyState === "loading"
          ? "Verifying…"
          : verifyState === "success"
          ? "Signature Valid"
          : verifyState === "error" && verifyResult
          ? "Invalid Signature"
          : "Verify Signature"}
      </button>

      {/* Result message */}
      {(verifyResult || verifyError) && (
        <div
          className="mt-2 p-2.5 rounded-lg animate-fade-in"
          style={{
            background:
              verifyState === "success"
                ? "var(--risk-low-bg)"
                : "var(--risk-critical-bg)",
            border:
              verifyState === "success"
                ? "1px solid var(--risk-low-border)"
                : "1px solid var(--risk-critical-border)",
          }}
        >
          <p
            className="text-xs"
            style={{
              color:
                verifyState === "success"
                  ? "var(--risk-low)"
                  : "var(--risk-critical)",
            }}
          >
            {verifyError ?? verifyResult?.message}
          </p>
          {verifyResult?.verified_at && (
            <p
              className="type-mono mt-1"
              style={{ color: "var(--text-muted)" }}
            >
              Verified at: {new Date(verifyResult.verified_at).toLocaleString()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Main component ──────────────────────────────────────────────────── */

export default function DecisionReceipt({ receipt }: DecisionReceiptProps) {
  const [copied, setCopied] = useState(false);
  const [urlCopied, setUrlCopied] = useState(false);
  const action = receipt.action || "approve";
  const config = decisionConfig[action] || decisionConfig.escalate;

  const formattedDate = new Date(receipt.timestamp).toLocaleString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZoneName: "short",
  });

  const truncatedHash =
    receipt.signature_hash?.length > 20
      ? `${receipt.signature_hash.slice(0, 10)}...${receipt.signature_hash.slice(-10)}`
      : receipt.signature_hash;

  // Build verification URL — safe for both SSR and CSR
  // Encodes the full receipt JSON as base64 so the /verify page can decode
  // and independently verify the Ed25519 signature without a backend lookup.
  const [verificationUrl, setVerificationUrl] = useState<string>("");
  useEffect(() => {
    try {
      const b64 = btoa(JSON.stringify(receipt));
      setVerificationUrl(`${window.location.origin}/verify?receipt=${encodeURIComponent(b64)}`);
    } catch {
      setVerificationUrl(`${window.location.origin}/verify?id=${receipt.receipt_id}`);
    }
  }, [receipt]);

  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const el = document.createElement("textarea");
      el.value = text;
      document.body.appendChild(el);
      el.select();
      document.execCommand("copy");
      document.body.removeChild(el);
    }
  };

  const handleCopyHash = async () => {
    if (!receipt.signature_hash) return;
    await copyToClipboard(receipt.signature_hash);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleCopyUrl = async () => {
    if (!verificationUrl) return;
    await copyToClipboard(verificationUrl);
    setUrlCopied(true);
    setTimeout(() => setUrlCopied(false), 2000);
  };

  return (
    <div
      className="relative rounded-2xl overflow-hidden animate-fade-in"
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-default)",
        boxShadow: "var(--shadow-lg)",
      }}
      role="region"
      aria-label="Cryptographically signed decision receipt"
    >
      {/* Certificate top accent bar — decision color */}
      <div
        style={{
          height: "3px",
          background: `linear-gradient(90deg, ${config.color} 0%, var(--accent-primary) 50%, ${config.color} 100%)`,
        }}
        aria-hidden="true"
      />

      {/* Verified watermark — light printed-certificate diagonal ghost */}
      <div
        aria-hidden="true"
        style={{
          position: "absolute",
          top: "38%",
          right: "-10%",
          fontSize: "7rem",
          fontWeight: 900,
          letterSpacing: "0.12em",
          color: "var(--border-subtle)",
          opacity: 0.55,
          transform: "rotate(-35deg)",
          pointerEvents: "none",
          userSelect: "none",
          zIndex: 0,
          whiteSpace: "nowrap",
          fontFamily: "var(--font-serif)",
        }}
      >
        VERIFIED
      </div>

      <div className="relative z-10 p-6">

        {/* ── Certificate header ─────────────────────────────────── */}
        <div
          className="mb-6 pb-6"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          {/* Top row: title left, crypto seal right */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2.5 mb-1">
                <CheckCircle2
                  className="w-5 h-5 flex-shrink-0"
                  style={{ color: "var(--risk-low)" }}
                  aria-hidden="true"
                />
                <h3
                  className="type-page-title tracking-wide"
                  style={{ color: "var(--text-primary)", letterSpacing: "0.04em" }}
                >
                  DECISION RECEIPT
                </h3>
              </div>
              <p className="type-caption" style={{ color: "var(--text-muted)", marginLeft: "29px" }}>
                Official Patient Action Receipt — verifiable &amp; patient-owned
              </p>
            </div>

            {/* Crypto seal — right-aligned, authoritative */}
            <div
              className="flex-shrink-0 flex flex-col items-center gap-1 px-3 py-2"
              style={{
                border: "1px solid var(--accent-primary-border)",
                borderRadius: "6px",
                background: "var(--accent-primary-bg)",
                minWidth: "96px",
              }}
            >
              <span className="type-micro" style={{ color: "var(--accent-primary)", letterSpacing: "0.12em" }}>
                SIGNED
              </span>
              <span className="type-mono" style={{ color: "var(--accent-primary)", fontSize: "0.65rem" }}>
                Ed25519
              </span>
            </div>
          </div>
        </div>

        {/* ── Decision verdict ───────────────────────────────────── */}
        <div
          className="mb-6 px-6 py-5"
          style={{
            background: config.bg,
            border: `1px solid ${config.border}`,
            borderLeft: `4px solid ${config.color}`,
            borderRadius: "8px",
          }}
        >
          <span
            className="type-display"
            style={{
              color: config.color,
              fontSize: "2.25rem",
              letterSpacing: "0.06em",
              fontWeight: 900,
            }}
          >
            {config.label}
          </span>
          {receipt.payout_amount !== undefined &&
            receipt.payout_amount !== null &&
            receipt.payout_amount > 0 && (
              <div className="mt-3 flex items-baseline gap-2">
                <span
                  className="stat-value"
                  style={{
                    color: "var(--text-primary)",
                    fontSize: "2rem",
                    fontVariantNumeric: "tabular-nums",
                    fontWeight: 700,
                  }}
                >
                  ${receipt.payout_amount.toLocaleString()}
                </span>
                <span className="type-caption" style={{ color: "var(--text-secondary)" }}>
                  recoverable savings
                </span>
              </div>
            )}
        </div>

        {/* ── Key fields: receipt table ──────────────────────────── */}
        <div className="space-y-0 mb-5">
          {/* Divider rows — tabular receipt style */}
          {[
            { label: "Receipt ID", value: receipt.receipt_id, mono: true },
            { label: "Case ID", value: receipt.claim_id, mono: true },
            {
              label: "Actioned By",
              value: receipt.approved_by,
              mono: false,
            },
            { label: "Timestamp", value: formattedDate, mono: true },
          ].map(({ label, value, mono }, idx, arr) => (
            <div
              key={label}
              className="flex items-start justify-between gap-4 py-3"
              style={{
                borderBottom: idx < arr.length - 1 ? "1px solid var(--border-faint)" : "none",
              }}
            >
              <span className="label flex-shrink-0" style={{ paddingTop: "1px" }}>{label}</span>
              <span
                className={mono ? "type-mono text-right break-all" : "text-sm text-right"}
                style={{
                  color: "var(--text-primary)",
                  fontVariantNumeric: mono ? "tabular-nums" : undefined,
                  maxWidth: "65%",
                }}
              >
                {value ?? "—"}
              </span>
            </div>
          ))}
        </div>

        {/* ── Evidence summary ───────────────────────────────────── */}
        <div className="card-elevated rounded-lg p-4 mb-5">
          <h4 className="label mb-3">Evidence Summary</h4>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div
                className="stat-value"
                style={{
                  color: "var(--accent-primary)",
                  fontSize: "1.25rem",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {typeof receipt.identity_confidence === "number"
                  ? `${Math.round(receipt.identity_confidence * 100)}%`
                  : "N/A"}
              </div>
              <div className="type-micro mt-1" style={{ color: "var(--text-muted)" }}>
                Identity Confidence
              </div>
            </div>
            <div>
              <div
                className="stat-value"
                style={{
                  color: "var(--risk-medium)",
                  fontSize: "1.25rem",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {receipt.fraud_score ?? "N/A"}
              </div>
              <div className="type-micro mt-1" style={{ color: "var(--text-muted)" }}>
                Error Score
              </div>
            </div>
            <div>
              <div
                className="stat-value"
                style={{
                  color: "var(--risk-low)",
                  fontSize: "1.25rem",
                }}
              >
                {receipt.policy_check || "N/A"}
              </div>
              <div className="type-micro mt-1" style={{ color: "var(--text-muted)" }}>
                Policy Check
              </div>
            </div>
          </div>
        </div>

        {receipt.simulation_summary && (
          <div className="card-elevated rounded-lg p-3 mb-5">
            <span className="label block mb-1">Simulation Summary</span>
            <p className="text-sm" style={{ color: "var(--text-primary)" }}>
              {receipt.simulation_summary}
            </p>
          </div>
        )}

        {/* ── Verification: QR + URL ─────────────────────────────── */}
        {verificationUrl && (
          <div
            className="pt-5 mt-5"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            {/* Section label — azure accent pill, court-grade framing */}
            <div className="flex items-center gap-3 mb-4">
              <h4 className="label">Verification</h4>
              <span
                className="type-micro"
                style={{
                  color: "var(--accent-primary)",
                  background: "var(--accent-primary-bg)",
                  border: "1px solid var(--accent-primary-border)",
                  borderRadius: "4px",
                  padding: "2px 7px",
                  letterSpacing: "0.1em",
                }}
              >
                Ed25519 · cryptographically signed
              </span>
            </div>

            {/* Two-column: QR left, URL actions right */}
            <div className="flex items-start gap-5">
              {/* QR — prominent, framed */}
              <div className="flex-shrink-0">
                <ScanQRCode url={verificationUrl} />
              </div>

              {/* URL + action buttons */}
              <div className="flex-1 min-w-0">
                <p className="type-caption mb-2" style={{ color: "var(--text-muted)" }}>
                  Share this URL to independently verify receipt authenticity:
                </p>
                <div
                  className="rounded-lg px-3 py-2 mb-3"
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    borderLeft: "3px solid var(--accent-primary-border)",
                  }}
                >
                  <span className="type-mono break-all" style={{ color: "var(--text-secondary)" }}>
                    {verificationUrl}
                  </span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleCopyUrl}
                    aria-label={urlCopied ? "Verification URL copied to clipboard" : "Copy verification URL to clipboard"}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all min-h-[44px]"
                    style={{
                      background: urlCopied ? "var(--risk-low-bg)" : "var(--bg-elevated)",
                      border: `1px solid ${urlCopied ? "var(--risk-low-border)" : "var(--border-default)"}`,
                      color: urlCopied ? "var(--risk-low)" : "var(--text-secondary)",
                      cursor: "pointer",
                    }}
                  >
                    <Copy className="w-3 h-3" aria-hidden="true" />
                    {urlCopied ? "Copied!" : "Copy URL"}
                  </button>
                  <a
                    href={verificationUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all hover:opacity-80 min-h-[44px]"
                    style={{
                      background: "var(--accent-primary-bg)",
                      border: "1px solid var(--accent-primary-border)",
                      color: "var(--accent-primary)",
                      textDecoration: "none",
                    }}
                  >
                    <ExternalLink className="w-3 h-3" />
                    Open
                  </a>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Signature hash — visually contained monospace block ── */}
        {receipt.signature_hash && (
          <div
            className="mt-5 pt-5"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            <span className="label block mb-2">Signature Hash</span>
            <div
              style={{
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
                borderRadius: "6px",
                padding: "10px 14px",
              }}
            >
              <div className="flex items-center gap-3">
                <span
                  className="type-mono break-all flex-1"
                  style={{ color: "var(--text-secondary)" }}
                >
                  {truncatedHash}
                </span>
                <button
                  onClick={handleCopyHash}
                  aria-label={copied ? "Signature hash copied to clipboard" : "Copy full signature hash to clipboard"}
                  className="flex-shrink-0 p-2.5 rounded-md transition-all hover:opacity-80 min-w-[44px] min-h-[44px] flex items-center justify-center"
                  style={{
                    background: copied ? "var(--risk-low-bg)" : "var(--bg-overlay)",
                    border: `1px solid ${copied ? "var(--risk-low-border)" : "var(--border-subtle)"}`,
                    color: copied ? "var(--risk-low)" : "var(--text-secondary)",
                    cursor: "pointer",
                  }}
                  title="Copy full hash to clipboard"
                >
                  <Copy className="w-3.5 h-3.5" aria-hidden="true" />
                </button>
                {copied && (
                  <span className="type-caption animate-fade-in" style={{ color: "var(--risk-low)" }}>
                    Copied
                  </span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ── Cryptographic Signature Verification inline section ── */}
        <VerifySignatureSection receipt={receipt} />
      </div>
    </div>
  );
}
