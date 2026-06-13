"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { createEventSource } from "@/lib/api";
import { PipelineStep, StepState, InvestigationEvent } from "@/lib/types";
import { Check, Circle, AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface PipelineStepperProps {
  claimId: string;
  status: string;
}

const PIPELINE_STAGES: Array<{ id: string; label: string }> = [
  { id: "intake", label: "Intake" },
  { id: "vision_ai", label: "Vision AI" },
  { id: "coverage", label: "Coverage" },
  { id: "fraud", label: "Error Scan" },
  { id: "payout", label: "Savings" },
  { id: "simulate", label: "Simulate" },
  { id: "risk_eval", label: "Risk Eval" },
];

function mapEventToStageIndex(eventType: string): number {
  const mapping: Record<string, number> = {
    pipeline_start: 0,
    document_analyzed: 1,
    coverage_checked: 2,
    fraud_assessed: 3,
    payout_recommended: 4,
    simulation_complete: 5,
    risk_evaluated: 6,
    pipeline_complete: 7, // all done
  };
  return mapping[eventType] ?? -1;
}

function getInitialSteps(status: string): PipelineStep[] {
  // If the claim is already in a terminal state, show all steps as complete
  const terminalStatuses = [
    "approved",
    "auto_approved",
    "denied",
    "blocked",
  ];
  if (terminalStatuses.includes(status)) {
    return PIPELINE_STAGES.map((s) => ({
      id: s.id as PipelineStep["id"],
      label: s.label,
      state: "complete" as StepState,
    }));
  }

  if (status === "error") {
    return PIPELINE_STAGES.map((s) => ({
      id: s.id as PipelineStep["id"],
      label: s.label,
      state: "error" as StepState,
    }));
  }

  // For processing/submitted, start with intake active
  if (status === "processing" || status === "submitted") {
    return PIPELINE_STAGES.map((s, i) => ({
      id: s.id as PipelineStep["id"],
      label: s.label,
      state: (i === 0 ? "active" : "pending") as StepState,
    }));
  }

  // For pending_review / escalated, show all up to risk_eval complete
  if (status === "pending_review" || status === "escalated") {
    return PIPELINE_STAGES.map((s) => ({
      id: s.id as PipelineStep["id"],
      label: s.label,
      state: "complete" as StepState,
    }));
  }

  // Default: all pending
  return PIPELINE_STAGES.map((s) => ({
    id: s.id as PipelineStep["id"],
    label: s.label,
    state: "pending" as StepState,
  }));
}

function StepCircle({ state }: { state: StepState }) {
  const base =
    "w-10 h-10 rounded-full flex items-center justify-center transition-all duration-300 relative";

  if (state === "complete") {
    return (
      <div
        className={base}
        style={{
          background: "var(--risk-low)",
          boxShadow: "0 0 12px rgba(34, 197, 94, 0.3)",
        }}
      >
        <Check className="w-5 h-5 text-white" strokeWidth={3} />
      </div>
    );
  }

  if (state === "active") {
    return (
      <div
        className={cn(base, "animate-pulse-glow")}
        style={{
          background: "var(--accent-primary)",
          boxShadow: "0 0 20px rgba(245, 166, 35, 0.5), 0 0 40px rgba(245, 166, 35, 0.2)",
        }}
      >
        <Loader2 className="w-5 h-5 text-white animate-spin" strokeWidth={2.5} />
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        className={base}
        style={{
          background: "var(--risk-critical)",
          boxShadow: "0 0 12px rgba(239, 68, 68, 0.3)",
        }}
      >
        <AlertCircle className="w-5 h-5 text-white" strokeWidth={2.5} />
      </div>
    );
  }

  // Pending
  return (
    <div
      className={base}
      style={{
        background: "transparent",
        border: "2px solid var(--border-subtle)",
      }}
    >
      <Circle
        className="w-4 h-4"
        style={{ color: "var(--border-subtle)" }}
        strokeWidth={2}
      />
    </div>
  );
}

function ConnectingLine({
  leftState,
}: {
  leftState: StepState;
  rightState: StepState;
}) {
  const isCompleted = leftState === "complete";
  const isActive = leftState === "active";

  return (
    <div className="flex-1 h-1 mx-1 rounded-full overflow-hidden relative"
      style={{
        background: "var(--border-subtle)",
        minWidth: "24px",
      }}
    >
      <div
        className="absolute inset-0 rounded-full transition-all duration-700 ease-out"
        style={{
          background: isCompleted
            ? "var(--risk-low)"
            : isActive
            ? "linear-gradient(90deg, var(--accent-primary), transparent)"
            : "transparent",
          width: isCompleted ? "100%" : isActive ? "60%" : "0%",
        }}
      />
    </div>
  );
}

export default function PipelineStepper({ claimId, status }: PipelineStepperProps) {
  const [steps, setSteps] = useState<PipelineStep[]>(() => getInitialSteps(status));
  const highestCompletedRef = useRef(-1);

  // Update steps based on SSE events
  const handleSSEEvent = useCallback((event: InvestigationEvent) => {
    const stageIndex = mapEventToStageIndex(event.event_type);
    if (stageIndex === -1) return;

    if (stageIndex === 7) {
      // pipeline_complete: mark all complete
      setSteps((prev) =>
        prev.map((s) => ({ ...s, state: "complete" as StepState }))
      );
      highestCompletedRef.current = 6;
      return;
    }

    if (event.status === "error" || event.status === "failed") {
      setSteps((prev) =>
        prev.map((s, i) => {
          if (i < stageIndex) return { ...s, state: "complete" as StepState };
          if (i === stageIndex) return { ...s, state: "error" as StepState };
          return { ...s, state: "pending" as StepState };
        })
      );
      return;
    }

    // Mark completed stages and set the next one as active
    highestCompletedRef.current = Math.max(highestCompletedRef.current, stageIndex);

    setSteps((prev) =>
      prev.map((s, i) => {
        if (i <= highestCompletedRef.current) return { ...s, state: "complete" as StepState };
        if (i === highestCompletedRef.current + 1) return { ...s, state: "active" as StepState };
        return { ...s, state: "pending" as StepState };
      })
    );
  }, []);

  // Connect to SSE for real-time updates
  useEffect(() => {
    // Only connect SSE for active claims
    if (
      status !== "processing" &&
      status !== "submitted"
    ) {
      return;
    }

    const es = createEventSource(claimId);

    es.onmessage = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        const event: InvestigationEvent = {
          event_type: parsed.event_type ?? "",
          message: parsed.message ?? "",
          status: parsed.status ?? "info",
          data: parsed.data ?? null,
          timestamp: parsed.timestamp ?? new Date().toISOString(),
        };
        handleSSEEvent(event);
      } catch {
        // skip unparseable
      }
    };

    es.onerror = () => {
      es.close();
    };

    return () => {
      es.close();
    };
  }, [claimId, status, handleSSEEvent]);

  const displaySteps =
    status === "error"
      ? steps.map((step) => ({ ...step, state: "error" as StepState }))
      : ["approved", "auto_approved", "denied", "blocked", "pending_review", "escalated"].includes(status)
      ? steps.map((step) => ({ ...step, state: "complete" as StepState }))
      : steps;

  return (
    <div
      data-testid="pipeline-stepper"
      className="w-full rounded-xl px-6 py-6 sm:px-8 sm:py-8"
      style={{
        background: "linear-gradient(180deg, var(--bg-surface) 0%, var(--bg-base) 100%)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {/* Title row */}
      <div className="flex items-center gap-2 mb-6">
        <div
          className="w-2 h-2 rounded-full"
          style={{
            background:
              displaySteps.some((s) => s.state === "active")
                ? "var(--accent-primary)"
                : displaySteps.every((s) => s.state === "complete")
                ? "var(--risk-low)"
                : displaySteps.some((s) => s.state === "error")
                ? "var(--risk-critical)"
                : "var(--text-muted)",
          }}
        />
        <span
          className="text-xs font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-muted)" }}
        >
          Sovereign Review Pipeline
        </span>
      </div>

      {/* Hero timeline */}
      <div className="flex items-center w-full">
        {displaySteps.map((step, idx) => (
          <div
            key={step.id}
            data-testid={`pipeline-step-${step.id}`}
            className="contents"
          >
            {/* Step column */}
            <div className="flex flex-col items-center flex-shrink-0">
              <StepCircle state={step.state} />
              <span
                className={cn(
                  "text-xs mt-2.5 font-medium whitespace-nowrap transition-colors duration-300",
                  step.state === "pending" && "opacity-40"
                )}
                style={{
                  color:
                    step.state === "complete"
                      ? "var(--risk-low)"
                      : step.state === "active"
                      ? "var(--accent-primary)"
                      : step.state === "error"
                      ? "var(--risk-critical)"
                      : "var(--text-muted)",
                }}
              >
                {step.label}
              </span>
            </div>

            {/* Connecting line (not after last step) */}
            {idx < steps.length - 1 && (
              <ConnectingLine
                leftState={step.state}
                rightState={displaySteps[idx + 1].state}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
