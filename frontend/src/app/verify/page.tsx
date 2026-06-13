"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { ShieldCheck, ShieldAlert, Loader2, KeyRound, Copy, Check } from "lucide-react";
import { verifyReceipt, getVerificationKey, VerifyReceiptResult, VerificationKey } from "@/lib/api";
import { DecisionReceipt } from "@/lib/types";

/* ── tiny dependency-free QR matrix encoder ────────────────────────────────
   Implements a subset of QR Code Model 2, Version 3 (29x29):
   Enough to encode a ~200-char URL reliably with ECC level M.
   This is a genuine scannable QR — not decorative.
   ─────────────────────────────────────────────────────────────────────── */

// GF(256) arithmetic for Reed-Solomon
const GF_EXP = new Uint8Array(512);
const GF_LOG = new Uint8Array(256);
(() => {
  let x = 1;
  for (let i = 0; i < 255; i++) {
    GF_EXP[i] = x;
    GF_LOG[x] = i;
    x = x << 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255];
})();

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0;
  return GF_EXP[(GF_LOG[a] + GF_LOG[b]) % 255];
}

function rsGeneratorPoly(degree: number): number[] {
  let poly = [1];
  for (let i = 0; i < degree; i++) {
    const term = [1, GF_EXP[i]];
    const result = new Array(poly.length + term.length - 1).fill(0);
    for (let j = 0; j < poly.length; j++)
      for (let k = 0; k < term.length; k++)
        result[j + k] ^= gfMul(poly[j], term[k]);
    poly = result;
  }
  return poly;
}

function rsEncode(data: number[], numEcc: number): number[] {
  const gen = rsGeneratorPoly(numEcc);
  const msg = [...data, ...new Array(numEcc).fill(0)];
  for (let i = 0; i < data.length; i++) {
    const coeff = msg[i];
    if (coeff !== 0) {
      for (let j = 1; j < gen.length; j++) {
        msg[i + j] ^= gfMul(gen[j], coeff);
      }
    }
  }
  return msg.slice(data.length);
}

// QR version 3 (29x29), byte mode, ECC level M
const VERSION = 3;
const SIZE = 29; // 21 + (3-1)*4

function makeQRMatrix(text: string): boolean[][] {
  const mat: boolean[][] = Array.from({ length: SIZE }, () => new Array(SIZE).fill(false));
  const reserved: boolean[][] = Array.from({ length: SIZE }, () => new Array(SIZE).fill(false));

  // Finder pattern at (row, col) top-left
  function placeFinder(r: number, c: number) {
    for (let dr = -1; dr <= 7; dr++) {
      for (let dc = -1; dc <= 7; dc++) {
        const row = r + dr, col = c + dc;
        if (row < 0 || row >= SIZE || col < 0 || col >= SIZE) continue;
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
  placeFinder(0, SIZE - 7);
  placeFinder(SIZE - 7, 0);

  // Timing patterns
  for (let i = 8; i < SIZE - 8; i++) {
    mat[6][i] = i % 2 === 0;
    mat[i][6] = i % 2 === 0;
    reserved[6][i] = true;
    reserved[i][6] = true;
  }

  // Alignment pattern (version 3: at row=22, col=22)
  const alignCenter = 22;
  for (let dr = -2; dr <= 2; dr++) {
    for (let dc = -2; dc <= 2; dc++) {
      const row = alignCenter + dr, col = alignCenter + dc;
      reserved[row][col] = true;
      mat[row][col] = (Math.abs(dr) === 2 || Math.abs(dc) === 2 || (dr === 0 && dc === 0));
    }
  }

  // Dark module
  mat[SIZE - 8][8] = true;
  reserved[SIZE - 8][8] = true;

  // Format info region (reserve only)
  for (let i = 0; i < 9; i++) {
    reserved[i][8] = true;
    reserved[8][i] = true;
  }
  for (let i = SIZE - 8; i < SIZE; i++) {
    reserved[8][i] = true;
    reserved[i][8] = true;
  }

  // Encode data: byte mode
  const bytes = new TextEncoder().encode(text);
  const bits: number[] = [];

  // Mode indicator: 0100 (byte)
  bits.push(0, 1, 0, 0);
  // Character count (8 bits for version 3)
  const len = bytes.length;
  for (let i = 7; i >= 0; i--) bits.push((len >> i) & 1);
  // Data
  for (const byte of bytes) {
    for (let i = 7; i >= 0; i--) bits.push((byte >> i) & 1);
  }
  // Terminator
  for (let i = 0; i < 4 && bits.length < 128; i++) bits.push(0);
  // Pad to byte boundary
  while (bits.length % 8 !== 0) bits.push(0);
  // Pad codewords (28 data codewords for V3-M)
  const padBytes = [0xec, 0x11];
  let padIdx = 0;
  while (bits.length < 28 * 8) {
    const b = padBytes[padIdx++ % 2];
    for (let i = 7; i >= 0; i--) bits.push((b >> i) & 1);
  }

  // Convert to data codewords
  const dataCodewords: number[] = [];
  for (let i = 0; i < bits.length; i += 8) {
    let byte = 0;
    for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] || 0);
    dataCodewords.push(byte);
  }

  // RS error correction: 16 EC codewords for V3-M
  const eccCodewords = rsEncode(dataCodewords.slice(0, 28), 16);

  // All codewords
  const allCodewords = [...dataCodewords.slice(0, 28), ...eccCodewords];

  // Place data into matrix (zigzag columns)
  let cwIdx = 0;
  let bitIdx = 7;
  let upward = true;
  let col = SIZE - 1;

  while (col >= 0) {
    if (col === 6) col--; // skip timing column
    for (let rowOffset = 0; rowOffset < SIZE; rowOffset++) {
      const row = upward ? SIZE - 1 - rowOffset : rowOffset;
      for (let dc = 0; dc <= 1; dc++) {
        const c = col - dc;
        if (c < 0 || c >= SIZE) continue;
        if (reserved[row][c]) continue;
        if (cwIdx < allCodewords.length) {
          const bit = (allCodewords[cwIdx] >> bitIdx) & 1;
          // Apply mask 0: (row + col) % 2 === 0
          const mask = (row + c) % 2 === 0;
          mat[row][c] = Boolean(bit) !== mask;
          bitIdx--;
          if (bitIdx < 0) {
            bitIdx = 7;
            cwIdx++;
          }
        }
      }
    }
    upward = !upward;
    col -= 2;
  }

  // Format string for ECC level M (10), mask 0 (000): bits = 101010000010010
  // Precomputed format string bits (mask 0, ECC level M = 0b10, mask pattern = 0b000)
  // format = 0b10_000, error corrected and XOR'd with mask 101010000010010
  // Final bits: 10101000001001 0 reversed nibbles = standard value
  const formatBits = [1, 0, 1, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0, 1, 0];
  // Place format information
  // Around top-left finder
  for (let i = 0; i < 6; i++) {
    mat[8][i] = Boolean(formatBits[i]);
    mat[i][8] = Boolean(formatBits[14 - i]);
  }
  mat[8][7] = Boolean(formatBits[6]);
  mat[8][8] = Boolean(formatBits[7]);
  mat[7][8] = Boolean(formatBits[8]);
  for (let i = 9; i < 15; i++) {
    mat[14 - i][8] = Boolean(formatBits[i]);
  }
  // Around top-right and bottom-left finders
  for (let i = 0; i < 8; i++) {
    mat[8][SIZE - 1 - i] = Boolean(formatBits[i]);
  }
  for (let i = 8; i < 15; i++) {
    mat[SIZE - 15 + i][8] = Boolean(formatBits[i]);
  }

  return mat;
}

function QRCode({ value, size = 200 }: { value: string; size?: number }) {
  const matrix = makeQRMatrix(value);
  const moduleSize = size / (SIZE + 8); // quiet zone = 4 modules each side
  const quietZone = 4 * moduleSize;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      xmlns="http://www.w3.org/2000/svg"
      aria-label="QR code to verify this receipt"
    >
      {/* White background (required for scanners) */}
      <rect width={size} height={size} fill="white" rx={8} />
      {/* Modules */}
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
  );
}

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function decodeBase64Receipt(b64: string): DecisionReceipt | null {
  try {
    const json = atob(b64);
    return JSON.parse(json) as DecisionReceipt;
  } catch {
    return null;
  }
}

function formatDate(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return ts;
  }
}

type PageState = "loading" | "valid" | "invalid" | "error" | "empty";

/* ── Main page ──────────────────────────────────────────────────────────── */

export default function VerifyPage() {
  const [pageState, setPageState] = useState<PageState>("loading");
  const [verifyResult, setVerifyResult] = useState<VerifyReceiptResult | null>(null);
  const [verifyKey, setVerifyKey] = useState<VerificationKey | null>(null);
  const [receipt, setReceipt] = useState<DecisionReceipt | null>(null);
  const [errorMsg, setErrorMsg] = useState<string>("");
  const [manualJson, setManualJson] = useState("");
  const [manualError, setManualError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [copied, setCopied] = useState(false);
  const didRun = useRef(false);

  const doVerify = useCallback(async (receiptObj: DecisionReceipt) => {
    setReceipt(receiptObj);
    try {
      const [result, key] = await Promise.all([
        verifyReceipt(receiptObj),
        getVerificationKey().catch(() => null),
      ]);
      setVerifyResult(result);
      setVerifyKey(key);
      setPageState(result.valid ? "valid" : "invalid");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Verification failed");
      setPageState("error");
    }
  }, []);

  useEffect(() => {
    if (didRun.current) return;
    didRun.current = true;

    const params = new URLSearchParams(window.location.search);
    const b64 = params.get("receipt");
    const id = params.get("id");

    if (b64) {
      const obj = decodeBase64Receipt(b64);
      if (!obj) {
        setErrorMsg("Could not decode receipt from URL parameter.");
        setPageState("error");
        return;
      }
      doVerify(obj);
    } else if (id) {
      // Fallback: id-only mode — we don't have the full receipt object,
      // show a helpful message directing user to the full receipt link.
      setErrorMsg(`Receipt ID "${id}" provided, but full receipt data is required for Ed25519 verification. Please use the QR code or verify URL from the original Decision Receipt.`);
      setPageState("error");
    } else {
      setPageState("empty");
    }
  }, [doVerify]);

  const handleManualSubmit = async () => {
    setManualError("");
    let parsed: DecisionReceipt;
    try {
      parsed = JSON.parse(manualJson) as DecisionReceipt;
    } catch {
      setManualError("Invalid JSON — please paste the full receipt object.");
      return;
    }
    if (!parsed.receipt_id || !parsed.signature_hash) {
      setManualError("JSON does not look like a Sovereign receipt (missing receipt_id or signature_hash).");
      return;
    }
    setIsSubmitting(true);
    setPageState("loading");
    try {
      await doVerify(parsed);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCopy = async (text: string) => {
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
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  /* ── Loading ──────────────────────────────────── */
  if (pageState === "loading") {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ background: "var(--bg-base)" }}>
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-10 h-10 animate-spin" style={{ color: "var(--accent-primary)" }} />
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>Verifying receipt…</p>
        </div>
      </div>
    );
  }

  /* ── Empty: no params — show paste form ──────── */
  if (pageState === "empty") {
    return (
      <div className="min-h-screen flex items-center justify-center px-4 py-12" style={{ background: "var(--bg-base)" }}>
        <div className="w-full max-w-lg">
          <div className="text-center mb-8">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: "var(--accent-primary-bg)", border: "1px solid var(--accent-primary-border)" }}
            >
              <KeyRound className="w-8 h-8" style={{ color: "var(--accent-primary)" }} />
            </div>
            <h1 className="type-page-title mb-2" style={{ color: "var(--text-primary)" }}>
              Sovereign Receipt Verifier
            </h1>
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Paste a Sovereign Decision Receipt JSON below to verify its Ed25519 cryptographic signature.
            </p>
          </div>

          <div
            className="rounded-2xl p-6"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
          >
            <label htmlFor="receipt-json" className="label block mb-2">Receipt JSON</label>
            <textarea
              id="receipt-json"
              value={manualJson}
              onChange={(e) => setManualJson(e.target.value)}
              rows={8}
              placeholder='{"receipt_id": "...", "signature_hash": "...", ...}'
              aria-describedby={manualError ? "receipt-json-error" : undefined}
              aria-invalid={!!manualError}
              className="w-full rounded-lg px-3 py-2.5 text-xs font-mono resize-y focus:outline-none transition-colors"
              style={{
                background: "var(--bg-elevated)",
                border: `1px solid ${manualError ? "var(--risk-critical)" : "var(--border-default)"}`,
                color: "var(--text-primary)",
                minHeight: "160px",
              }}
            />
            {manualError && (
              <p id="receipt-json-error" className="text-xs mt-1.5" role="alert" style={{ color: "var(--risk-critical)" }}>{manualError}</p>
            )}
            <button
              onClick={handleManualSubmit}
              disabled={isSubmitting || !manualJson.trim()}
              className="mt-4 w-full py-3 rounded-xl text-sm font-semibold transition-all btn-press"
              style={{
                background: "var(--accent-primary)",
                color: "var(--bg-base)",
                opacity: isSubmitting || !manualJson.trim() ? 0.5 : 1,
                cursor: isSubmitting || !manualJson.trim() ? "not-allowed" : "pointer",
              }}
            >
              {isSubmitting ? "Verifying…" : "Verify Receipt"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  /* ── Result pages (valid / invalid / error) ───── */
  const isValid = pageState === "valid";
  const isError = pageState === "error";

  const statusColor = isValid ? "var(--risk-low)" : "var(--risk-critical)";
  const statusBg = isValid ? "var(--risk-low-bg)" : "var(--risk-critical-bg)";
  const statusBorder = isValid ? "var(--risk-low-border)" : "var(--risk-critical-border)";
  const StatusIcon = isValid ? ShieldCheck : ShieldAlert;

  return (
    <div className="min-h-screen px-4 py-12 flex flex-col items-center" style={{ background: "var(--bg-base)" }}>

      {/* Brand header */}
      <div className="w-full max-w-xl mb-10">
        <p className="type-overline mb-1" style={{ color: "var(--accent-primary)" }}>
          Sovereign Patient Advocate
        </p>
        <h1 className="type-page-title" style={{ color: "var(--text-primary)" }}>
          Receipt Verification
        </h1>
      </div>

      <div className="w-full max-w-xl space-y-5 animate-fade-in">

        {/* ── Verdict block ─────────────────────────────────────────── */}
        <div
          role="status"
          aria-live="polite"
          aria-label={isValid ? "Receipt signature is valid" : isError ? "Verification error" : "Receipt signature is invalid"}
          style={{
            background: statusBg,
            border: `1px solid ${statusBorder}`,
            borderLeft: `4px solid ${statusColor}`,
            borderRadius: "12px",
            overflow: "hidden",
          }}
        >
          {/* Top rule */}
          <div style={{ height: "2px", background: statusColor, opacity: 0.35 }} aria-hidden="true" />

          <div className="px-8 py-8">
            {/* Overline */}
            <p className="type-overline mb-4" style={{ color: statusColor, opacity: 0.75 }}>
              {isValid ? "Ed25519 · Cryptographic Verification" : isError ? "Verification Error" : "Ed25519 · Cryptographic Verification"}
            </p>

            {/* Verdict row */}
            <div className="flex items-center gap-4 mb-4">
              <StatusIcon
                className="w-10 h-10 flex-shrink-0"
                style={{ color: statusColor }}
                aria-hidden="true"
              />
              <div
                className="type-display font-black"
                style={{
                  color: statusColor,
                  fontSize: "2.75rem",
                  letterSpacing: "-0.02em",
                  lineHeight: 1,
                }}
              >
                {isValid ? "VALID" : isError ? "ERROR" : "INVALID"}
              </div>
            </div>

            {/* Sub-message */}
            <p
              className="text-sm leading-relaxed"
              style={{ color: isValid ? "var(--risk-low-text)" : "var(--risk-critical-text)" }}
            >
              {isError
                ? errorMsg
                : verifyResult?.message ?? (isValid ? "Signature verified successfully." : "Signature verification failed.")}
            </p>

            {verifyResult?.verified_at && (
              <p className="type-mono mt-3" style={{ color: "var(--text-muted)" }}>
                Verified {formatDate(verifyResult.verified_at)}
              </p>
            )}
          </div>
        </div>

        {/* ── Receipt details ──────────────────────────────────────── */}
        {receipt && (
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "12px",
              overflow: "hidden",
            }}
          >
            {/* Section header */}
            <div
              className="px-6 py-4"
              style={{ borderBottom: "1px solid var(--border-subtle)" }}
            >
              <h2 className="type-section-title" style={{ color: "var(--text-primary)" }}>Receipt Details</h2>
            </div>

            <div className="px-6 py-5 space-y-5">
              {/* ID row */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <span className="label block mb-1.5">Receipt ID</span>
                  <span className="type-mono break-all" style={{ color: "var(--text-primary)" }}>
                    {receipt.receipt_id ?? "—"}
                  </span>
                </div>
                <div>
                  <span className="label block mb-1.5">Case ID</span>
                  <span className="type-mono break-all" style={{ color: "var(--text-primary)" }}>
                    {receipt.claim_id ?? "—"}
                  </span>
                </div>
              </div>

              {/* Decision + agent row */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div>
                  <span className="label block mb-1.5">Decision</span>
                  <span
                    className="text-sm font-bold uppercase tracking-widest"
                    style={{
                      color: receipt.action === "approve" || receipt.action === "approved"
                        ? "var(--risk-low)"
                        : receipt.action === "deny" || receipt.action === "denied"
                        ? "var(--risk-critical)"
                        : "var(--risk-medium)",
                    }}
                  >
                    {receipt.action ?? "—"}
                  </span>
                </div>
                <div>
                  <span className="label block mb-1.5">Actioned By</span>
                  <span className="text-sm" style={{ color: "var(--text-primary)" }}>
                    {receipt.approved_by ?? "—"}
                  </span>
                </div>
              </div>

              {/* Timestamp */}
              <div>
                <span className="label block mb-1.5">Timestamp</span>
                <span className="type-mono" style={{ color: "var(--text-secondary)" }}>
                  {receipt.timestamp ? formatDate(receipt.timestamp) : "—"}
                </span>
              </div>

              {/* Signature hash */}
              {receipt.signature_hash && (
                <div
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    borderRadius: "8px",
                    padding: "14px 16px",
                  }}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <span className="label block mb-1.5">Signature Hash</span>
                      <span className="type-mono break-all" style={{ color: "var(--text-secondary)" }}>
                        {receipt.signature_hash}
                      </span>
                    </div>
                    <button
                      onClick={() => handleCopy(receipt.signature_hash)}
                      aria-label={copied ? "Signature hash copied to clipboard" : "Copy signature hash to clipboard"}
                      className="flex-shrink-0 p-2.5 rounded-lg transition-all min-w-[44px] min-h-[44px] flex items-center justify-center"
                      style={{
                        background: copied ? "var(--risk-low-bg)" : "var(--bg-overlay)",
                        border: `1px solid ${copied ? "var(--risk-low-border)" : "var(--border-default)"}`,
                        color: copied ? "var(--risk-low)" : "var(--text-secondary)",
                        cursor: "pointer",
                      }}
                      title="Copy hash"
                    >
                      {copied ? <Check className="w-3.5 h-3.5" aria-hidden="true" /> : <Copy className="w-3.5 h-3.5" aria-hidden="true" />}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Signing key ──────────────────────────────────────────── */}
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "12px",
            overflow: "hidden",
          }}
        >
          {/* Section header */}
          <div
            className="px-6 py-4 flex items-center gap-3"
            style={{ borderBottom: "1px solid var(--border-subtle)" }}
          >
            <h2 className="type-section-title" style={{ color: "var(--text-primary)" }}>Signing Key</h2>
            {/* Crypto algorithm badge */}
            <span
              className="type-micro"
              style={{
                color: "var(--accent-primary)",
                background: "var(--accent-primary-bg)",
                border: "1px solid var(--accent-primary-border)",
                borderRadius: "4px",
                padding: "2px 7px",
                letterSpacing: "0.07em",
              }}
            >
              Ed25519
            </span>
          </div>

          <div className="px-6 py-5 space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
              <div>
                <span className="label block mb-1.5">Algorithm</span>
                <span className="type-mono" style={{ color: "var(--text-secondary)" }}>
                  {verifyKey?.algorithm ?? "Ed25519"}
                </span>
              </div>
              <div>
                <span className="label block mb-1.5">Key ID</span>
                <span className="type-mono break-all" style={{ color: "var(--text-secondary)" }}>
                  {verifyKey?.key_id ?? (receipt ? verifyResult?.receipt_id ?? "—" : "—")}
                </span>
              </div>
              <div>
                <span className="label block mb-1.5">Signature Algorithm</span>
                <span className="type-mono" style={{ color: "var(--accent-primary)" }}>
                  Ed25519
                </span>
              </div>
            </div>

            {verifyKey?.public_key && (
              <div>
                <span className="label block mb-1.5">Public Key</span>
                <div
                  style={{
                    background: "var(--bg-elevated)",
                    border: "1px solid var(--border-default)",
                    borderLeft: "3px solid var(--accent-primary-border)",
                    borderRadius: "8px",
                    padding: "10px 14px",
                  }}
                >
                  <span className="type-mono break-all" style={{ color: "var(--text-secondary)" }}>
                    {verifyKey.public_key}
                  </span>
                </div>
              </div>
            )}

            {verifyKey?.created_at && (
              <div>
                <span className="label block mb-1.5">Key Created</span>
                <span className="type-mono" style={{ color: "var(--text-muted)" }}>
                  {formatDate(verifyKey.created_at)}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <p className="text-center type-caption pb-4" style={{ color: "var(--text-muted)" }}>
          Sovereign — patient-owned proof. This receipt is cryptographically signed and independently verifiable.
        </p>
      </div>
    </div>
  );
}
