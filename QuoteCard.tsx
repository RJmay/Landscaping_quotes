"use client";
// src/components/QuoteCard.tsx
// Displays the returned quote with price range, line items, summary, and CTA.

import { QuoteResponse } from "@/lib/api";

interface Props {
  areaResult?: import("@/lib/api").AreaAnalysisResult | null;
  quote: QuoteResponse & { from_cache?: boolean; expires_at?: string };
  address: string;
  onReset: () => void;
  onBook: () => void;
}

const CONFIDENCE_CONFIG = {
  high:   { label: "High confidence",   color: "var(--meadow)",  bg: "rgba(61,107,53,0.08)",  dot: "#3D6B35" },
  medium: { label: "Medium confidence", color: "#9a6d1a",        bg: "rgba(154,109,26,0.08)", dot: "#C4975A" },
  low:    { label: "Low confidence",    color: "#a03030",        bg: "rgba(160,48,48,0.08)",  dot: "#c0392b" },
};

export default function QuoteCard({ quote, address, areaResult, onReset, onBook }: Props) {
  const conf = CONFIDENCE_CONFIG[quote.confidence];
  const midpoint = Math.round((quote.total_min + quote.total_max) / 2);

  return (
    <div
      className="animate-fade-up"
      style={{
        background: "var(--parchment)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
        boxShadow: "var(--shadow-float)",
        border: "1px solid var(--fog)",
      }}
    >
      {/* Header banner */}
      <div
        style={{
          background: "var(--meadow)",
          padding: "28px 28px 24px",
          position: "relative",
          overflow: "hidden",
        }}
      >
        {/* Decorative circles */}
        <div style={{
          position: "absolute", top: -30, right: -30,
          width: 140, height: 140,
          borderRadius: "50%",
          background: "rgba(255,255,255,0.06)",
          pointerEvents: "none",
        }} />
        <div style={{
          position: "absolute", bottom: -20, right: 60,
          width: 80, height: 80,
          borderRadius: "50%",
          background: "rgba(255,255,255,0.04)",
          pointerEvents: "none",
        }} />

        <p style={{ fontSize: 12, color: "rgba(255,255,255,0.7)", marginBottom: 6, fontWeight: 500 }}>
          📍 {address}
        </p>

        <p style={{ fontSize: 13, color: "rgba(255,255,255,0.75)", marginBottom: 4 }}>
          Estimated price
        </p>

        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 4 }}>
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 48,
              color: "#fff",
              lineHeight: 1,
            }}
          >
            ${quote.total_min.toFixed(0)}
          </span>
          <span style={{ fontSize: 22, color: "rgba(255,255,255,0.6)" }}>—</span>
          <span
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 48,
              color: "#fff",
              lineHeight: 1,
            }}
          >
            ${quote.total_max.toFixed(0)}
          </span>
          <span style={{ fontSize: 14, color: "rgba(255,255,255,0.65)", marginLeft: 4 }}>
            {quote.currency}
          </span>
        </div>

        {/* Confidence badge */}
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            background: "rgba(255,255,255,0.15)",
            borderRadius: 20,
            marginTop: 8,
          }}
        >
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#fff", display: "inline-block" }} />
          <span style={{ fontSize: 12, color: "#fff", fontWeight: 500 }}>{conf.label}</span>
        </div>

        {quote.multi_job_discount_applied && (
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "4px 10px",
              background: "rgba(255,255,255,0.15)",
              borderRadius: 20,
              marginTop: 8,
              marginLeft: 8,
            }}
          >
            <span style={{ fontSize: 12, color: "#fff", fontWeight: 500 }}>🏷 Multi-service discount</span>
          </div>
        )}
      </div>

      {/* Line items */}
      <div style={{ padding: "20px 28px 0" }}>
        <p style={{ fontSize: 12, fontWeight: 600, color: "var(--clay)", textTransform: "uppercase" as const, letterSpacing: "0.06em", marginBottom: 12 }}>
          Breakdown
        </p>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {quote.line_items.map((item, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
                padding: "12px 14px",
                background: "var(--mist)",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--fog)",
                gap: 12,
              }}
            >
              <div style={{ flex: 1 }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: "var(--bark)", marginBottom: 2 }}>
                  {item.job_name}
                </p>
                <p style={{ fontSize: 12, color: "var(--clay)", lineHeight: 1.4 }}>
                  {item.notes}
                </p>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <p style={{ fontSize: 14, fontWeight: 600, color: "var(--bark)", whiteSpace: "nowrap" as const }}>
                  ${item.min.toFixed(0)}–${item.max.toFixed(0)}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Summary */}
      <div style={{ padding: "16px 28px 0" }}>
        <p style={{ fontSize: 13.5, color: "var(--soil)", lineHeight: 1.65 }}>
          {quote.summary}
        </p>
      </div>

      {/* Caveats */}
      {quote.caveats && (
        <div
          style={{
            margin: "14px 28px 0",
            padding: "10px 14px",
            background: "rgba(196,151,90,0.08)",
            borderLeft: "3px solid var(--straw)",
            borderRadius: "0 var(--radius-sm) var(--radius-sm) 0",
          }}
        >
          <p style={{ fontSize: 12, color: "#7a5c2e", lineHeight: 1.5 }}>
            ⚠ {quote.caveats}
          </p>
        </div>
      )}


      {/* Satellite source badge */}
      {areaResult?.success && !areaResult.fallback_used && (
        <div style={{ margin: "0 28px", padding: "8px 12px", background: "rgba(61,107,53,0.06)", borderRadius: "var(--radius-sm)", border: "1px solid rgba(61,107,53,0.15)" }}>
          <p style={{ fontSize: 11, color: "var(--meadow)", fontWeight: 500 }}>
            🛰 Property measured from satellite imagery · {areaResult.image_quality} image quality
          </p>
        </div>
      )}

      {/* CTAs */}
      <div style={{ padding: "20px 28px 28px", display: "flex", gap: 10, flexWrap: "wrap" as const }}>
        {/* Primary CTA — Book this job */}
        <button
          type="button"
          onClick={onBook}
          style={{
            width: "100%", padding: "16px",
            background: "var(--meadow)", color: "#fff",
            border: "none", borderRadius: "var(--radius-md)",
            fontSize: 15, fontWeight: 600, fontFamily: "var(--font-body)",
            cursor: "pointer", transition: "all 0.2s", letterSpacing: "0.01em",
            marginBottom: 10,
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "var(--grass)";
            (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
            (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 6px 20px rgba(61,107,53,0.3)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "var(--meadow)";
            (e.currentTarget as HTMLButtonElement).style.transform = "none";
            (e.currentTarget as HTMLButtonElement).style.boxShadow = "none";
          }}
        >
          Book this job →
        </button>

        <a
          href={`mailto:?subject=Landscaping Quote&body=Your quote is $${quote.total_min}–$${quote.total_max} AUD for ${address}.`}
          style={{
            flex: 1,
            minWidth: 140,
            padding: "14px 20px",
            background: "var(--meadow)",
            color: "#fff",
            borderRadius: "var(--radius-md)",
            textAlign: "center" as const,
            textDecoration: "none",
            fontSize: 14,
            fontWeight: 600,
            fontFamily: "var(--font-body)",
            transition: "opacity 0.15s",
          }}
          onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = "0.88")}
          onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = "1")}
        >
          Email this quote
        </a>

        <button
          type="button"
          onClick={() => {
            const text = `Landscaping quote for ${address}:\n$${quote.total_min}–$${quote.total_max} AUD\n\n${quote.summary}`;
            navigator.clipboard.writeText(text).then(() => alert("Quote copied to clipboard!"));
          }}
          style={{
            flex: 1,
            minWidth: 140,
            padding: "14px 20px",
            background: "transparent",
            border: "1.5px solid var(--fog)",
            color: "var(--bark)",
            borderRadius: "var(--radius-md)",
            fontSize: 14,
            fontWeight: 500,
            fontFamily: "var(--font-body)",
            cursor: "pointer",
            transition: "all 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--clay)";
            (e.currentTarget as HTMLButtonElement).style.background = "var(--mist)";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.borderColor = "var(--fog)";
            (e.currentTarget as HTMLButtonElement).style.background = "transparent";
          }}
        >
          Copy quote
        </button>

        <button
          type="button"
          onClick={onReset}
          style={{
            width: "100%",
            padding: "11px",
            background: "transparent",
            border: "none",
            color: "var(--clay)",
            fontSize: 13,
            fontFamily: "var(--font-body)",
            cursor: "pointer",
            textDecoration: "underline",
          }}
        >
          Get another quote →
        </button>
      </div>


        {/* Cache indicator */}
        {quote.from_cache && (
          <p style={{ textAlign: "center" as const, fontSize: 11, color: "var(--clay)", opacity: 0.6, marginTop: -4 }}>
            ⚡ Cached result · prices valid for 24h
          </p>
        )}

      {/* Quote ID (small, for feedback loop) */}
      {quote.quote_id && (
        <p
          style={{
            textAlign: "center",
            fontSize: 10,
            color: "var(--clay)",
            opacity: 0.5,
            paddingBottom: 12,
          }}
        >
          Quote #{quote.quote_id.slice(0, 8)}
        </p>
      )}
    </div>
  );
}
