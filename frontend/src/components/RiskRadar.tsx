"use client";

import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  ResponsiveContainer,
} from "recharts";
import { Activity } from "lucide-react";
import { RiskAssessment } from "@/lib/types";

interface RiskRadarProps {
  fraudScore: number | null | undefined;
  riskLevel: string | null | undefined;
  riskAssessment: RiskAssessment | null | undefined;
}

interface RadarDataItem {
  axis: string;
  value: number;
  fullMark: number;
}

const defaultData: RadarDataItem[] = [
  { axis: "Identity", value: 0, fullMark: 100 },
  { axis: "Document", value: 0, fullMark: 100 },
  { axis: "Consistency", value: 0, fullMark: 100 },
  { axis: "History", value: 0, fullMark: 100 },
  { axis: "Web Check", value: 0, fullMark: 100 },
  { axis: "Financial", value: 0, fullMark: 100 },
];

/* Recharts renders to SVG/Canvas — CSS vars don't work.
   These must be raw hex values matching the design tokens. */
const CHART_COLORS = {
  grid: "#1F1F2A",         // --border-subtle
  axisLabel: "#A8A8B3",    // --text-secondary
  axisTick: "#5C5C6B",     // --text-muted
  riskLow: "#22C55E",      // --risk-low
  riskMedium: "#EAB308",   // --risk-medium
  riskCritical: "#EF4444", // --risk-critical
  riskLowBg: "rgba(34, 197, 94, 0.10)",
  riskMediumBg: "rgba(234, 179, 8, 0.10)",
  riskCriticalBg: "rgba(239, 68, 68, 0.10)",
};

function getScoreColor(score: number): string {
  if (score < 30) return CHART_COLORS.riskLow;
  if (score < 60) return CHART_COLORS.riskMedium;
  return CHART_COLORS.riskCritical;
}

function getScoreBgColor(score: number): string {
  if (score < 30) return CHART_COLORS.riskLowBg;
  if (score < 60) return CHART_COLORS.riskMediumBg;
  return CHART_COLORS.riskCriticalBg;
}

function getRiskLabel(level: string | null | undefined): string {
  switch (level) {
    case "low":
      return "Low Risk";
    case "medium":
      return "Medium Risk";
    case "high":
      return "High Risk";
    case "critical":
      return "Critical Risk";
    default:
      return "Calculating...";
  }
}

function getRadarData(
  riskAssessment: RiskAssessment | null | undefined
): RadarDataItem[] {
  if (!riskAssessment) {
    return defaultData;
  }

  const identityScore = Math.round((riskAssessment.identity_confidence || 0) * 100);
  const documentScore = Math.round((riskAssessment.document_authenticity_confidence || 0) * 100);
  const fraudConcern = Math.round((riskAssessment.fraud_concern_level || 0) * 100);
  const overallFraud = Math.round(riskAssessment.fraud_score || 0);

  return [
    { axis: "Identity", value: identityScore, fullMark: 100 },
    { axis: "Document", value: documentScore, fullMark: 100 },
    { axis: "Overcharge Risk", value: fraudConcern, fullMark: 100 },
    { axis: "Overall Error", value: overallFraud, fullMark: 100 },
    { axis: "Threshold", value: Math.round((riskAssessment.approval_threshold || 0) * 100), fullMark: 100 },
    { axis: "Financial", value: Math.min(100, Math.round(riskAssessment.monetary_value / 500)), fullMark: 100 },
  ];
}

export default function RiskRadar({ fraudScore, riskLevel, riskAssessment }: RiskRadarProps) {
  const overallScore = fraudScore ?? 0;
  const scoreColor = getScoreColor(overallScore);
  const scoreBg = getScoreBgColor(overallScore);
  const riskLabel = getRiskLabel(riskLevel);
  const chartData = getRadarData(riskAssessment);

  return (
    <div className="card p-6">
      <h3
        className="type-section-title mb-4 flex items-center gap-2"
        style={{ color: "var(--text-primary)" }}
      >
        <Activity className="w-5 h-5" style={{ color: "var(--accent-primary)" }} />
        Risk Radar
      </h3>

      <div className="flex flex-col items-center">
        {/* Score display with amber accent border/glow */}
        <div
          className="w-28 h-28 rounded-full flex flex-col items-center justify-center mb-4"
          style={{
            backgroundColor: scoreBg,
            border: `2px solid ${scoreColor}`,
            boxShadow: `0 0 20px ${scoreColor}33`,
          }}
        >
          <span className="text-3xl font-bold stat-value" style={{ color: scoreColor }}>
            {Math.round(overallScore)}
          </span>
          <span className="text-xs" style={{ color: "var(--text-secondary)" }}>/100</span>
        </div>

        <span
          className="text-sm font-medium mb-6 px-3 py-1 rounded-full"
          style={{ color: scoreColor, backgroundColor: scoreBg }}
        >
          {riskLabel}
        </span>

        {/* Radar chart with charcoal grid lines */}
        <div className="w-full" style={{ height: 280, minWidth: 200 }}>
          <ResponsiveContainer width="100%" height="100%" minWidth={200} minHeight={200}>
            <RadarChart data={chartData} cx="50%" cy="50%" outerRadius="70%">
              <PolarGrid stroke={CHART_COLORS.grid} strokeOpacity={0.6} />
              <PolarAngleAxis dataKey="axis" tick={{ fill: CHART_COLORS.axisLabel, fontSize: 11 }} />
              <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fill: CHART_COLORS.axisTick, fontSize: 10 }} axisLine={false} />
              <Radar
                name="Risk"
                dataKey="value"
                stroke={scoreColor}
                fill={scoreColor}
                fillOpacity={0.25}
                isAnimationActive={true}
                animationDuration={1200}
                animationEasing="ease-out"
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>

        {/* Risk assessment reasoning - glass-panel */}
        {riskAssessment?.reasoning && (
          <div className="w-full mt-4 glass-panel rounded-lg p-3">
            <h4 className="label mb-2">
              Sovereign Assessment
            </h4>
            <p className="text-sm" style={{ color: "var(--text-primary)" }}>
              {riskAssessment.reasoning}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
