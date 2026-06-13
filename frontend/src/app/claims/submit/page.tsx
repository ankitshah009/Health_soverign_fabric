"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { submitClaim } from "@/lib/api";
import FileUpload from "@/components/FileUpload";
import { Shield, Loader2, ArrowRight } from "lucide-react";

export default function SubmitClaimPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [claimantName, setClaimantName] = useState(""); // maps to claimant_name API field
  const [policyNumber, setPolicyNumber] = useState("");
  const [incidentDescription, setIncidentDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isValid =
    file !== null &&
    claimantName.trim() !== "" &&
    policyNumber.trim() !== "" &&
    incidentDescription.trim() !== "";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!isValid || !file) return;

    setSubmitting(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("claimant_name", claimantName.trim());
      formData.append("policy_number", policyNumber.trim());
      formData.append("incident_description", incidentDescription.trim());

      const result = await submitClaim(formData);
      router.push(`/claims/${result.claim_id}`);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to submit case. Please try again."
      );
      setSubmitting(false);
    }
  }

  return (
    <div
      className="max-w-xl mx-auto px-0 py-2"
      style={{ paddingBottom: "4rem" }}
    >
      {/* ── Page header ───────────────────────── */}
      <div className="mb-10">
        <p
          className="type-overline mb-3"
          style={{ color: "var(--accent-primary)" }}
        >
          New case
        </p>
        <h1
          className="type-page-title mb-3"
          style={{ color: "var(--text-primary)" }}
        >
          Start a Review
        </h1>
        <p className="type-body" style={{ color: "var(--text-secondary)" }}>
          Upload your medical bill or denial letter. Sovereign uses Grok Vision to find
          overcharges, billing errors, and appealable denials automatically.
        </p>
      </div>

      {/* ── Form ──────────────────────────────── */}
      <form
        onSubmit={handleSubmit}
        aria-label="Submit a new medical billing case"
        className="flex flex-col gap-7"
        noValidate
      >
        {/* Supporting document */}
        <fieldset className="border-0 p-0 m-0">
          <legend
            className="type-caption font-semibold mb-2 block"
            style={{ color: "var(--text-secondary)", letterSpacing: "0.04em" }}
          >
            Supporting document
            <span
              aria-hidden="true"
              style={{ color: "var(--risk-critical)", marginLeft: 4 }}
            >
              *
            </span>
          </legend>
          <FileUpload
            onFileSelect={setFile}
            selectedFile={file}
            onRemove={() => setFile(null)}
          />
        </fieldset>

        {/* Patient name */}
        <div className="flex flex-col gap-2">
          <label
            htmlFor="claimantName"
            className="type-caption font-semibold"
            style={{ color: "var(--text-secondary)", letterSpacing: "0.04em" }}
          >
            Patient name
            <span
              aria-hidden="true"
              style={{ color: "var(--risk-critical)", marginLeft: 4 }}
            >
              *
            </span>
          </label>
          <input
            id="claimantName"
            type="text"
            value={claimantName}
            onChange={(e) => setClaimantName(e.target.value)}
            placeholder="Full name as it appears on the bill"
            autoComplete="name"
            required
            className="w-full rounded-xl px-4 py-3 text-sm input-recessed focus:outline-none"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Policy number */}
        <div className="flex flex-col gap-2">
          <label
            htmlFor="policyNumber"
            className="type-caption font-semibold"
            style={{ color: "var(--text-secondary)", letterSpacing: "0.04em" }}
          >
            Policy number
            <span
              aria-hidden="true"
              style={{ color: "var(--risk-critical)", marginLeft: 4 }}
            >
              *
            </span>
          </label>
          <input
            id="policyNumber"
            type="text"
            value={policyNumber}
            onChange={(e) => setPolicyNumber(e.target.value)}
            placeholder="e.g., POL-2024-001234"
            autoComplete="off"
            required
            className="w-full rounded-xl px-4 py-3 text-sm input-recessed focus:outline-none"
            style={{ color: "var(--text-primary)", fontVariantNumeric: "tabular-nums" }}
          />
        </div>

        {/* Incident description */}
        <div className="flex flex-col gap-2">
          <label
            htmlFor="incidentDescription"
            className="type-caption font-semibold"
            style={{ color: "var(--text-secondary)", letterSpacing: "0.04em" }}
          >
            Describe the issue
            <span
              aria-hidden="true"
              style={{ color: "var(--risk-critical)", marginLeft: 4 }}
            >
              *
            </span>
          </label>
          <p
            className="type-caption"
            style={{ color: "var(--text-muted)", marginTop: -4 }}
          >
            Unexpected charge, denied service, balance-billing concern — in your own words.
          </p>
          <textarea
            id="incidentDescription"
            value={incidentDescription}
            onChange={(e) => setIncidentDescription(e.target.value)}
            placeholder="e.g., I received a $4,200 bill for a procedure I was told would be covered…"
            rows={5}
            required
            className="w-full rounded-xl px-4 py-3 text-sm input-recessed resize-none focus:outline-none"
            style={{ color: "var(--text-primary)", lineHeight: "1.6" }}
          />
        </div>

        {/* Completion hint */}
        {!isValid && (
          <p className="type-caption" style={{ color: "var(--text-muted)" }}>
            Complete all fields above to continue.
          </p>
        )}

        {/* Error */}
        {error && (
          <div
            className="rounded-xl px-4 py-3 animate-fade-in"
            style={{
              background: "var(--risk-critical-bg)",
              border: "1px solid var(--risk-critical-border)",
            }}
            role="alert"
          >
            <p
              className="type-body"
              style={{ color: "var(--risk-critical)" }}
            >
              {error}
            </p>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!isValid || submitting}
          className="w-full py-3.5 rounded-xl font-semibold btn-press flex items-center justify-center gap-2.5 transition-all"
          style={{
            background:
              isValid && !submitting
                ? "var(--accent-primary)"
                : "var(--bg-elevated)",
            color:
              isValid && !submitting
                ? "var(--bg-base)"
                : "var(--text-muted)",
            cursor: isValid && !submitting ? "pointer" : "not-allowed",
            boxShadow:
              isValid && !submitting
                ? "0 4px 20px rgba(245, 166, 35, 0.30)"
                : "none",
            fontSize: "0.9375rem",
            letterSpacing: "-0.01em",
            transition: "background 0.2s ease, box-shadow 0.2s ease, color 0.2s ease",
          }}
        >
          {submitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
              Submitting…
            </>
          ) : (
            <>
              <Shield className="w-4 h-4" aria-hidden="true" />
              Start Review
              {isValid && (
                <ArrowRight className="w-4 h-4 ml-auto" aria-hidden="true" />
              )}
            </>
          )}
        </button>

        <p
          className="type-caption text-center"
          style={{ color: "var(--text-muted)" }}
        >
          Your documents are encrypted and never shared.
        </p>
      </form>
    </div>
  );
}
