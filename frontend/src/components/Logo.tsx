"use client";

import { useId } from "react";

/* Sovereign brand mark — a shield (protection/advocacy) with a checkmark
   carved out as negative space ("it signs its work"). Azure brand gradient. */

const SHIELD =
  "M24 4.8 L38 9.6 Q39.8 10.2 39.8 12.2 L39.8 22.8 C39.8 32.4 33 39.7 24 43.4 C15 39.7 8.2 32.4 8.2 22.8 L8.2 12.2 Q8.2 10.2 10 9.6 Z";
const CHECK = "M16.4 24.6 L21.7 29.9 L32 17.8";

export function SovereignMark({
  size = 40,
  variant = "icon",
}: {
  size?: number;
  /** "icon" = rounded azure tile + dark shield; "mark" = standalone gradient shield */
  variant?: "icon" | "mark";
}) {
  const uid = useId().replace(/[:]/g, "");
  const grad = `sov-grad-${uid}`;
  const mask = `sov-check-${uid}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      role="img"
      aria-label="Sovereign"
      style={{
        display: "block",
        flexShrink: 0,
        borderRadius: variant === "icon" ? size * 0.25 : 0,
        boxShadow: variant === "icon" ? "0 6px 18px rgba(77,155,255,0.30)" : "none",
      }}
    >
      <defs>
        <linearGradient id={grad} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#7DB2FF" />
          <stop offset="1" stopColor="#2B82F0" />
        </linearGradient>
        <mask id={mask}>
          <rect width="48" height="48" fill="#fff" />
          <path
            d={CHECK}
            fill="none"
            stroke="#000"
            strokeWidth="3.7"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </mask>
      </defs>

      {variant === "icon" ? (
        <>
          <rect width="48" height="48" rx="12" fill={`url(#${grad})`} />
          <g transform="translate(9.2 8.2) scale(0.617)">
            <path d={SHIELD} fill="#07182E" mask={`url(#${mask})`} />
          </g>
        </>
      ) : (
        <path d={SHIELD} fill={`url(#${grad})`} mask={`url(#${mask})`} />
      )}
    </svg>
  );
}

export function SovereignLogo({
  markSize = 44,
  orientation = "horizontal",
}: {
  markSize?: number;
  orientation?: "horizontal" | "stacked";
}) {
  const stacked = orientation === "stacked";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: stacked ? "column" : "row",
        alignItems: "center",
        gap: stacked ? 14 : 16,
        textAlign: stacked ? "center" : "left",
      }}
    >
      <SovereignMark size={markSize} variant="mark" />
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: stacked ? "center" : "flex-start" }}>
        <span
          style={{
            fontFamily: "var(--font-serif)",
            fontWeight: 400,
            fontSize: markSize * 0.82,
            lineHeight: 0.9,
            letterSpacing: "-0.005em",
            color: "var(--text-primary)",
          }}
        >
          Sovereign
        </span>
        <span
          style={{
            fontFamily: "var(--font-sans)",
            fontWeight: 600,
            fontSize: Math.max(9, markSize * 0.18),
            letterSpacing: "0.34em",
            textTransform: "uppercase",
            color: "var(--accent-primary)",
          }}
        >
          Patient Advocate
        </span>
      </div>
    </div>
  );
}

export default SovereignMark;
