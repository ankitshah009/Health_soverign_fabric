"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { submitClaim } from "@/lib/api";
import FileUpload from "@/components/FileUpload";
import { Shield, Loader2 } from "lucide-react";

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
    <div className="max-w-2xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1
          className="type-page-title mb-1"
          style={{ color: "var(--text-primary)" }}
        >
          Start a New Case
        </h1>
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          Upload your medical bill or denial letter — Sovereign reads it with Grok Vision and hunts for overcharges, billing errors, and appealable denials.
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} aria-label="Submit a new medical billing case" className="space-y-6">
        {/* File upload */}
        <div>
          <label
            className="block text-sm font-medium mb-2"
            style={{ color: "var(--text-primary)" }}
          >
            Supporting Document <span style={{ color: "var(--risk-critical)" }}>*</span>
          </label>
          <FileUpload
            onFileSelect={setFile}
            selectedFile={file}
            onRemove={() => setFile(null)}
          />
        </div>

        {/* Patient name */}
        <div>
          <label
            htmlFor="claimantName"
            className="block text-sm font-medium mb-2"
            style={{ color: "var(--text-primary)" }}
          >
            Patient Name <span style={{ color: "var(--risk-critical)" }}>*</span>
          </label>
          <input
            id="claimantName"
            type="text"
            value={claimantName}
            onChange={(e) => setClaimantName(e.target.value)}
            placeholder="Enter full name"
            className="w-full rounded-lg px-4 py-2.5 text-sm input-recessed focus:outline-none"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Policy number */}
        <div>
          <label
            htmlFor="policyNumber"
            className="block text-sm font-medium mb-2"
            style={{ color: "var(--text-primary)" }}
          >
            Policy Number <span style={{ color: "var(--risk-critical)" }}>*</span>
          </label>
          <input
            id="policyNumber"
            type="text"
            value={policyNumber}
            onChange={(e) => setPolicyNumber(e.target.value)}
            placeholder="e.g., POL-2024-001234"
            className="w-full rounded-lg px-4 py-2.5 text-sm input-recessed focus:outline-none"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Issue description */}
        <div>
          <label
            htmlFor="incidentDescription"
            className="block text-sm font-medium mb-2"
            style={{ color: "var(--text-primary)" }}
          >
            Issue Description <span style={{ color: "var(--risk-critical)" }}>*</span>
          </label>
          <textarea
            id="incidentDescription"
            value={incidentDescription}
            onChange={(e) => setIncidentDescription(e.target.value)}
            placeholder="Describe the billing issue or denial — e.g., unexpected charge, service not covered, balance-billing concern..."
            rows={5}
            className="w-full rounded-lg px-4 py-2.5 text-sm input-recessed resize-none focus:outline-none"
            style={{ color: "var(--text-primary)" }}
          />
        </div>

        {/* Error */}
        {error && (
          <div
            className="rounded-lg p-3"
            style={{
              background: "var(--risk-critical-bg)",
              border: "1px solid var(--risk-critical-border)",
            }}
          >
            <p className="text-sm" style={{ color: "var(--risk-critical)" }}>{error}</p>
          </div>
        )}

        {/* Submit button - amber accent */}
        <button
          type="submit"
          disabled={!isValid || submitting}
          className="w-full py-3 rounded-lg text-sm font-semibold btn-press flex items-center justify-center gap-2"
          style={{
            background: isValid && !submitting ? "var(--accent-primary)" : "var(--bg-elevated)",
            color: isValid && !submitting ? "var(--bg-base)" : "var(--text-muted)",
            cursor: isValid && !submitting ? "pointer" : "not-allowed",
            boxShadow: isValid && !submitting ? "0 4px 14px rgba(245, 166, 35, 0.3)" : "none",
          }}
        >
          {submitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Submitting Case...
            </>
          ) : (
            <>
              <Shield className="w-4 h-4" />
              Start Review
            </>
          )}
        </button>
      </form>
    </div>
  );
}
