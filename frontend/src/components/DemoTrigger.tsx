"use client";

import { useState, useCallback } from "react";
import { Loader2, CheckCircle2, AlertTriangle } from "lucide-react";
import { SOVEREIGN_OPEN_VOICE_EVENT } from "./ChatFab";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type TriggerState = "idle" | "uploading" | "done" | "error";

export default function DemoTrigger() {
  const [state, setState] = useState<TriggerState>("idle");
  const [errorMsg, setErrorMsg] = useState("");

  const handleClick = useCallback(async () => {
    if (state === "uploading") return;
    setState("uploading");
    setErrorMsg("");

    try {
      // 1. Fetch the bundled sample bill from /public
      const imgRes = await fetch("/sample-bill.png");
      if (!imgRes.ok) throw new Error(`Could not load /sample-bill.png (${imgRes.status})`);
      const blob = await imgRes.blob();
      const file = new File([blob], "sample-bill.png", { type: blob.type || "image/png" });

      // 2. POST as multipart to /api/pending-file
      const form = new FormData();
      form.append("file", file);
      const uploadRes = await fetch(`${API_BASE}/api/pending-file`, {
        method: "POST",
        body: form,
      });
      if (!uploadRes.ok) {
        const msg = await uploadRes.text().catch(() => "Upload failed");
        throw new Error(msg);
      }

      // 3. Mark done, then fire the custom event so ChatFab opens in voice mode
      setState("done");
      setTimeout(() => {
        window.dispatchEvent(new CustomEvent(SOVEREIGN_OPEN_VOICE_EVENT));
        setTimeout(() => setState("idle"), 3000);
      }, 300);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Unknown error");
      setState("error");
      setTimeout(() => setState("idle"), 4000);
    }
  }, [state]);

  const label =
    state === "uploading"
      ? "Uploading bill…"
      : state === "done"
      ? "Opening Sovereign…"
      : state === "error"
      ? "Failed — retry"
      : "📨 Simulate: new bill arrived";

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        disabled={state === "uploading" || state === "done"}
        title="Demo: upload a sample medical bill and open Sovereign Voice Advocate"
        className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all btn-press"
        style={{
          background:
            state === "done"
              ? "var(--risk-low-bg)"
              : state === "error"
              ? "var(--risk-critical-bg)"
              : "var(--accent-primary-bg)",
          border: `1px solid ${
            state === "done"
              ? "var(--risk-low-border)"
              : state === "error"
              ? "var(--risk-critical-border)"
              : "var(--accent-primary-border)"
          }`,
          color:
            state === "done"
              ? "var(--risk-low)"
              : state === "error"
              ? "var(--risk-critical)"
              : "var(--accent-primary)",
          cursor: state === "uploading" || state === "done" ? "not-allowed" : "pointer",
          opacity: state === "uploading" || state === "done" ? 0.75 : 1,
          whiteSpace: "nowrap",
        }}
      >
        {state === "uploading" && <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />}
        {state === "done" && <CheckCircle2 className="w-3.5 h-3.5 flex-shrink-0" />}
        {state === "error" && <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0" />}
        <span>{label}</span>
      </button>

      {state === "error" && errorMsg && (
        <div
          className="absolute top-full mt-1 left-0 z-50 rounded-lg px-3 py-2 text-xs shadow-lg animate-fade-in"
          style={{
            background: "var(--risk-critical-bg)",
            border: "1px solid var(--risk-critical-border)",
            color: "var(--risk-critical)",
            maxWidth: "260px",
            whiteSpace: "normal",
          }}
        >
          {errorMsg}
        </div>
      )}
    </div>
  );
}
