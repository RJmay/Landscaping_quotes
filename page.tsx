"use client";
// src/app/page.tsx — Step 4 update: satellite area detection integrated.
//
// New flow:
//   1. User enters address
//   2. On "Analyse property" click → calls /analyse-property
//   3. Detected m² values auto-fill the property inputs (read-only, satellite badge)
//   4. User picks services + optional modifiers
//   5. Quote submitted with area_source="maps_vision"

import { useEffect, useState, useCallback } from "react";
import AddressAutocomplete from "@/components/AddressAutocomplete";
import JobSelector from "@/components/JobSelector";
import PropertyInputs from "@/components/PropertyInputs";
import QuoteCard from "@/components/QuoteCard";
import QuoteLoading from "@/components/QuoteLoading";
import { fetchJobs, submitQuote, analyseProperty, Job, QuoteResponse, AreaAnalysisResult } from "@/lib/api";
import BookingForm from "@/components/BookingForm";
import BookingConfirmation from "@/components/BookingConfirmation";

// ─── Types ────────────────────────────────────────────────────────────────────

interface PropertySizes {
  lawn_sqm: number;
  roof_sqm: number;
  garden_sqm: number;
  gutter_length_m: number;
  driveway_exposed_sqm: number;
  driveway_covered_sqm: number;
}

interface FormState {
  addressDisplay: string;
  addressParsed: { full: string; suburb: string; state: string; postcode: string } | null;
  selectedJobIds: string[];
  sizes: PropertySizes;
  terrain: "flat" | "sloped" | "unknown";
  travel_zone: "A" | "B" | "C";
  access_notes: string;
}

const DEFAULT_SIZES: PropertySizes = {
  lawn_sqm: 250, roof_sqm: 155, garden_sqm: 35,
  gutter_length_m: 50, driveway_exposed_sqm: 40, driveway_covered_sqm: 0,
};

const INITIAL_FORM: FormState = {
  addressDisplay: "",
  addressParsed: null,
  selectedJobIds: [],
  sizes: DEFAULT_SIZES,
  terrain: "flat",
  travel_zone: "A",
  access_notes: "",
};

type Stage = "form" | "analysing" | "loading" | "result" | "booking" | "confirmed";

// ─── Component ────────────────────────────────────────────────────────────────

export default function HomePage() {
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>("form");
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [areaResult, setAreaResult] = useState<AreaAnalysisResult | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [showModifiers, setShowModifiers] = useState(false);
  const [bookingId, setBookingId] = useState<string | null>(null);
  const [customerName, setCustomerName] = useState<string>("");

  useEffect(() => {
    fetchJobs()
      .then(setJobs)
      .catch(() => setJobsError("Could not load services. Is the backend running?"));
  }, []);

  const updateForm = useCallback((key: keyof FormState, value: unknown) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => { const n = { ...prev }; delete n[key as string]; return n; });
  }, []);

  // ── Step 4: Satellite analysis ─────────────────────────────────────────────

  const handleAnalyseProperty = async () => {
    if (!form.addressDisplay.trim()) {
      setErrors({ address: "Please enter your property address first" });
      return;
    }
    setApiError(null);
    setStage("analysing");

    try {
      const result = await analyseProperty(form.addressDisplay);
      setAreaResult(result);

      // Auto-fill sizes from satellite detection
      setForm((prev) => ({
        ...prev,
        sizes: {
          lawn_sqm: result.lawn.value_sqm,
          roof_sqm: result.roof.value_sqm,
          garden_sqm: result.garden.value_sqm,
          gutter_length_m: result.gutter.value_m,
          driveway_exposed_sqm: result.driveway_exposed.value_sqm,
          driveway_covered_sqm: result.driveway_covered.value_sqm,
        },
        // Apply detected terrain
        terrain: result.terrain_detected === "unknown" ? prev.terrain : result.terrain_detected,
      }));
    } catch (err: unknown) {
      // Non-fatal — fall back to manual input
      setAreaResult(null);
      setApiError(
        "Could not analyse property from satellite. You can enter sizes manually below."
      );
    } finally {
      setStage("form");
    }
  };

  // ── Quote submission ───────────────────────────────────────────────────────

  const validate = (): boolean => {
    const e: Record<string, string> = {};
    if (!form.addressDisplay.trim()) e.address = "Please enter your property address";
    if (form.selectedJobIds.length === 0) e.jobs = "Please select at least one service";
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleSubmit = async () => {
    if (!validate()) return;
    setApiError(null);
    setStage("loading");

    const suburb = form.addressParsed?.suburb || extractSuburb(form.addressDisplay);
    const state = form.addressParsed?.state || "QLD";
    const areaSource = areaResult?.success && !areaResult.fallback_used ? "maps_vision" : "manual";

    const conditionContext = areaResult
      ? `${areaResult.analysis_notes} Property in ${suburb}, ${state}.`
      : `Standard suburban property in ${suburb}, ${state}. No automated condition data available.`;

    try {
      const result = await submitQuote({
        address: form.addressDisplay,
        suburb,
        state,
        job_ids: form.selectedJobIds,
        lawn_sqm: form.sizes.lawn_sqm,
        roof_sqm: form.sizes.roof_sqm,
        garden_sqm: form.sizes.garden_sqm,
        gutter_length_m: form.sizes.gutter_length_m,
        driveway_exposed_sqm: form.sizes.driveway_exposed_sqm,
        driveway_covered_sqm: form.sizes.driveway_covered_sqm,
        overhang_detected: areaResult?.overhang_detected ?? false,
        overhang_description: areaResult?.overhang_description ?? "No overhang detected.",
        condition_score: 0.4,      // Step 5 will compute this
        condition_context: conditionContext,
        travel_zone: form.travel_zone,
        terrain: form.terrain,
        access_notes: form.access_notes || undefined,
        area_source: areaSource,
      });
      setQuote(result);
      setStage("result");
    } catch (err: unknown) {
      setApiError(err instanceof Error ? err.message : "Something went wrong.");
      setStage("form");
    }
  };

  const handleReset = () => {
    setForm(INITIAL_FORM);
    setQuote(null);
    setApiError(null);
    setAreaResult(null);
    setErrors({});
    setBookingId(null);
    setCustomerName("");
    setStage("form");
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div style={{ minHeight: "100vh", background: "var(--mist)", paddingBottom: 80 }}>

      {/* Hero */}
      <header style={{
        background: "var(--bark)", padding: "40px 24px 48px",
        textAlign: "center", position: "relative", overflow: "hidden",
      }}>
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: `radial-gradient(circle at 20% 50%, rgba(90,154,74,0.15) 0%, transparent 60%),
                            radial-gradient(circle at 80% 20%, rgba(196,151,90,0.1) 0%, transparent 50%)`,
          pointerEvents: "none",
        }} />
        <div style={{ position: "relative" }}>
          <p style={{ fontSize: 13, color: "var(--sage)", fontWeight: 500, letterSpacing: "0.1em", textTransform: "uppercase" as const, marginBottom: 12 }}>
            🛰 AI-powered instant pricing
          </p>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: "clamp(28px, 6vw, 48px)", color: "#f5f0e8", marginBottom: 12, fontStyle: "italic" }}>
            Get your landscaping quote
          </h1>
          <p style={{ fontSize: 15, color: "rgba(240,237,230,0.7)", maxWidth: 460, margin: "0 auto" }}>
            Enter your address and we&apos;ll automatically measure your property from satellite imagery, then price your selected services.
          </p>
        </div>
      </header>

      <main style={{ maxWidth: 640, margin: "0 auto", padding: "0 16px", marginTop: -20 }}>

        {jobsError && (
          <div style={{ background: "#fff0f0", border: "1px solid #f5c6c6", borderRadius: "var(--radius-md)", padding: "14px 18px", marginBottom: 16, fontSize: 14, color: "#8b2020" }}>
            ⚠ {jobsError}
          </div>
        )}

        {/* ── FORM ─────────────────────────────────────────────────────── */}
        {(stage === "form" || stage === "analysing") && (
          <div className="animate-fade-up" style={{
            background: "var(--parchment)", borderRadius: "var(--radius-lg)",
            padding: "28px 24px", boxShadow: "var(--shadow-float)",
            border: "1px solid var(--fog)", display: "flex", flexDirection: "column", gap: 28,
          }}>

            {/* Section 1: Address + Satellite button */}
            <section>
              <SectionLabel number={1} title="Your property address" />
              <AddressAutocomplete
                value={form.addressDisplay}
                onChange={(display, parsed) => {
                  updateForm("addressDisplay", display);
                  updateForm("addressParsed", parsed);
                  // Clear previous analysis when address changes
                  if (areaResult) setAreaResult(null);
                }}
                error={errors.address}
                disabled={stage === "analysing"}
              />

              {/* Satellite analyse button */}
              <button
                type="button"
                onClick={handleAnalyseProperty}
                disabled={stage === "analysing" || !form.addressDisplay.trim()}
                style={{
                  marginTop: 10,
                  width: "100%",
                  padding: "12px 16px",
                  background: stage === "analysing" ? "var(--fog)" : "var(--bark)",
                  color: stage === "analysing" ? "var(--clay)" : "#f5f0e8",
                  border: "none",
                  borderRadius: "var(--radius-md)",
                  fontSize: 14,
                  fontWeight: 500,
                  fontFamily: "var(--font-body)",
                  cursor: stage === "analysing" || !form.addressDisplay.trim() ? "not-allowed" : "pointer",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  transition: "all 0.2s",
                  opacity: !form.addressDisplay.trim() ? 0.5 : 1,
                }}
              >
                {stage === "analysing" ? (
                  <>
                    <div style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid var(--clay)", borderTopColor: "var(--meadow)", animation: "spin 0.7s linear infinite" }} />
                    Analysing from satellite...
                  </>
                ) : areaResult?.success && !areaResult.fallback_used ? (
                  <>🛰 Re-analyse from satellite</>
                ) : (
                  <>🛰 Auto-detect property sizes from satellite</>
                )}
              </button>

              {/* Analysis result badge */}
              {areaResult && (
                <SatelliteResultBadge result={areaResult} />
              )}
            </section>

            {/* Section 2: Services */}
            <section>
              <SectionLabel number={2} title="Services needed" />
              {jobs.length === 0 && !jobsError ? (
                <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "16px 0" }}>
                  <div style={{ width: 16, height: 16, borderRadius: "50%", border: "2px solid var(--sage)", borderTopColor: "var(--meadow)", animation: "spin 0.7s linear infinite" }} />
                  <span style={{ fontSize: 13, color: "var(--clay)" }}>Loading services...</span>
                </div>
              ) : (
                <JobSelector jobs={jobs} selected={form.selectedJobIds} onChange={(ids) => updateForm("selectedJobIds", ids)} error={errors.jobs} />
              )}
            </section>

            {/* Section 3: Property sizes */}
            <section>
              <SectionLabel
                number={3}
                title="Property sizes"
                subtitle={
                  areaResult?.success && !areaResult.fallback_used
                    ? "Auto-detected from satellite · click Re-analyse to refresh"
                    : "Use presets or enter manually · satellite auto-detect available above"
                }
              />
              <PropertyInputs
                values={form.sizes}
                onChange={(key, val) => updateForm("sizes", { ...form.sizes, [key]: val })}
                autoDetected={!!(areaResult?.success && !areaResult.fallback_used)}
                overhangDetected={areaResult?.overhang_detected}
                overhangDescription={areaResult?.overhang_description}
                onOverride={() => setAreaResult(null)}
              />
            </section>

            {/* Section 4: Optional modifiers */}
            <section>
              <button type="button" onClick={() => setShowModifiers(!showModifiers)} style={{
                background: "none", border: "none", color: "var(--clay)", fontSize: 13,
                fontFamily: "var(--font-body)", cursor: "pointer", display: "flex",
                alignItems: "center", gap: 6, padding: 0,
              }}>
                <span style={{ transform: showModifiers ? "rotate(90deg)" : "none", transition: "transform 0.2s", display: "inline-block" }}>▶</span>
                Additional details (optional)
              </button>

              {showModifiers && (
                <div className="animate-fade-up" style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
                  {/* Terrain */}
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 500, color: "var(--bark)", display: "block", marginBottom: 6 }}>Terrain</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {(["flat", "sloped", "unknown"] as const).map((t) => (
                        <button key={t} type="button" onClick={() => updateForm("terrain", t)} style={{
                          padding: "8px 16px", fontSize: 13, fontFamily: "var(--font-body)", fontWeight: 500,
                          background: form.terrain === t ? "var(--meadow)" : "var(--parchment)",
                          border: `1.5px solid ${form.terrain === t ? "var(--meadow)" : "var(--fog)"}`,
                          borderRadius: "var(--radius-sm)",
                          color: form.terrain === t ? "#fff" : "var(--bark)", cursor: "pointer", transition: "all 0.15s", textTransform: "capitalize" as const,
                        }}>{t}</button>
                      ))}
                    </div>
                    {areaResult?.terrain_detected && areaResult.terrain_detected !== "unknown" && (
                      <p style={{ fontSize: 11, color: "var(--meadow)", marginTop: 4 }}>
                        🛰 Satellite detected: {areaResult.terrain_detected}
                      </p>
                    )}
                  </div>

                  {/* Travel zone */}
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 500, color: "var(--bark)", display: "block", marginBottom: 6 }}>Distance from depot</label>
                    <div style={{ display: "flex", gap: 8 }}>
                      {[{ zone: "A", label: "Within 10km" }, { zone: "B", label: "10–25km" }, { zone: "C", label: "25km+" }].map(({ zone, label }) => (
                        <button key={zone} type="button" onClick={() => updateForm("travel_zone", zone)} style={{
                          flex: 1, padding: "8px 8px", fontSize: 12, fontFamily: "var(--font-body)", fontWeight: 500,
                          background: form.travel_zone === zone ? "var(--meadow)" : "var(--parchment)",
                          border: `1.5px solid ${form.travel_zone === zone ? "var(--meadow)" : "var(--fog)"}`,
                          borderRadius: "var(--radius-sm)",
                          color: form.travel_zone === zone ? "#fff" : "var(--bark)", cursor: "pointer", transition: "all 0.15s",
                        }}>{label}</button>
                      ))}
                    </div>
                  </div>

                  {/* Access notes */}
                  <div>
                    <label style={{ fontSize: 12, fontWeight: 500, color: "var(--bark)", display: "block", marginBottom: 6 }}>Access notes</label>
                    <textarea value={form.access_notes} onChange={(e) => updateForm("access_notes", e.target.value)}
                      placeholder="e.g. narrow side gate, dogs on property, steep driveway..."
                      rows={2} style={{
                        width: "100%", padding: "10px 12px", fontSize: 14, fontFamily: "var(--font-body)",
                        background: "var(--parchment)", border: "1.5px solid var(--fog)",
                        borderRadius: "var(--radius-sm)", color: "var(--soil)", resize: "vertical" as const, outline: "none",
                      }}
                      onFocus={(e) => (e.target.style.borderColor = "var(--meadow)")}
                      onBlur={(e) => (e.target.style.borderColor = "var(--fog)")}
                    />
                  </div>
                </div>
              )}
            </section>

            {/* API error */}
            {apiError && (
              <div style={{ padding: "12px 16px", background: "#fff8ee", border: "1px solid #f5d9a0", borderRadius: "var(--radius-sm)", fontSize: 13, color: "#7a5c1a" }}>
                ⚠ {apiError}
              </div>
            )}

            {/* Submit */}
            <button type="button" onClick={handleSubmit} disabled={jobs.length === 0} style={{
              width: "100%", padding: "16px",
              background: "var(--meadow)", color: "#fff", border: "none",
              borderRadius: "var(--radius-md)", fontSize: 16, fontWeight: 600,
              fontFamily: "var(--font-body)", cursor: jobs.length === 0 ? "not-allowed" : "pointer",
              opacity: jobs.length === 0 ? 0.6 : 1, transition: "all 0.2s", letterSpacing: "0.01em",
            }}
              onMouseEnter={(e) => {
                if (jobs.length > 0) {
                  (e.currentTarget as HTMLButtonElement).style.background = "var(--grass)";
                  (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
                  (e.currentTarget as HTMLButtonElement).style.boxShadow = "0 6px 20px rgba(61,107,53,0.3)";
                }
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "var(--meadow)";
                (e.currentTarget as HTMLButtonElement).style.transform = "none";
                (e.currentTarget as HTMLButtonElement).style.boxShadow = "none";
              }}
            >
              Get my instant quote →
            </button>
          </div>
        )}

        {/* ── LOADING ────────────────────────────────────────────────── */}
        {stage === "loading" && <QuoteLoading />}

        {/* ── RESULT ─────────────────────────────────────────────────── */}
        {stage === "result" && quote && (
          <QuoteCard
            quote={quote}
            address={form.addressDisplay}
            areaResult={areaResult}
            onReset={handleReset}
            onBook={() => setStage("booking")}
          />
        )}

        {/* ── BOOKING FORM ─────────────────────────────────────────────── */}
        {stage === "booking" && quote?.quote_id && (
          <BookingForm
            quoteId={quote.quote_id}
            address={form.addressDisplay}
            priceMin={quote.total_min}
            priceMax={quote.total_max}
            onSuccess={(id, name) => { setBookingId(id); setCustomerName(name); setStage("confirmed"); }}
            onCancel={() => setStage("result")}
          />
        )}

        {/* ── CONFIRMATION ─────────────────────────────────────────────── */}
        {stage === "confirmed" && bookingId && (
          <BookingConfirmation
            bookingId={bookingId}
            customerName={customerName || "there"}
            address={form.addressDisplay}
            onReset={handleReset}
          />
        )}
      </main>

      <footer style={{ textAlign: "center", padding: "40px 16px 0", fontSize: 12, color: "var(--clay)", opacity: 0.7 }}>
        Quotes are estimates only. Final price confirmed on-site.
      </footer>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SectionLabel({ number, title, subtitle }: { number: number; title: string; subtitle?: string }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          width: 24, height: 24, borderRadius: "50%", background: "var(--meadow)",
          color: "#fff", fontSize: 12, fontWeight: 700, display: "flex",
          alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>{number}</span>
        <h2 style={{ fontFamily: "var(--font-display)", fontSize: 18, color: "var(--bark)" }}>{title}</h2>
      </div>
      {subtitle && <p style={{ fontSize: 11, color: "var(--clay)", marginTop: 4, marginLeft: 34 }}>{subtitle}</p>}
    </div>
  );
}

function SatelliteResultBadge({ result }: { result: AreaAnalysisResult }) {
  const isReal = result.success && !result.fallback_used;
  const bg = isReal ? "rgba(61,107,53,0.07)" : "rgba(154,109,26,0.07)";
  const border = isReal ? "rgba(61,107,53,0.2)" : "rgba(154,109,26,0.2)";
  const color = isReal ? "var(--meadow)" : "#9a6d1a";
  const icon = isReal ? "🛰" : "⚠";

  return (
    <div style={{ marginTop: 10, padding: "10px 14px", background: bg, border: `1px solid ${border}`, borderRadius: "var(--radius-sm)" }}>
      <p style={{ fontSize: 13, color, fontWeight: 500, marginBottom: 4 }}>
        {icon} {isReal
          ? result.from_cache
            ? "Property sizes loaded from cache"
            : `Satellite analysis complete · ${result.overall_confidence} confidence`
          : "Satellite analysis unavailable · using estimates"}
      </p>
      {isReal && (
        <p style={{ fontSize: 12, color: "var(--clay)", lineHeight: 1.5 }}>
          {result.analysis_notes}
        </p>
      )}
      {!isReal && result.error && (
        <p style={{ fontSize: 12, color: "#9a6d1a" }}>{result.error}</p>
      )}
    </div>
  );
}

function extractSuburb(address: string): string {
  const parts = address.split(",").map((p) => p.trim());
  if (parts.length >= 2) return parts[parts.length - 2].replace(/\s+QLD.*/, "").trim();
  return "Unknown";
}
