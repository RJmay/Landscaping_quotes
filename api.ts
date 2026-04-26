// src/lib/api.ts — Updated: gutter_length_m, driveway_exposed/covered, overhang fields.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Job {
  id: string;
  name: string;
  description: string;
  unit: string;
  min_charge: number;
}

export interface QuoteRequest {
  address: string;
  suburb: string;
  state: string;
  job_ids: string[];
  // Core areas
  lawn_sqm: number;
  roof_sqm: number;
  garden_sqm: number;
  // Gutter — linear metres
  gutter_length_m: number;
  // Driveway split
  driveway_exposed_sqm: number;
  driveway_covered_sqm: number;
  overhang_detected: boolean;
  overhang_description: string;
  // Condition
  condition_score: number;
  condition_context: string;
  // Modifiers
  travel_zone: "A" | "B" | "C";
  terrain: "flat" | "sloped" | "unknown";
  access_notes?: string;
  area_source?: "manual" | "maps_vision";
}

export interface LineItem {
  job_id: string;
  job_name: string;
  min: number;
  max: number;
  notes: string;
}

export interface QuoteResponse {
  quote_id?: string;
  total_min: number;
  total_max: number;
  currency: string;
  confidence: "high" | "medium" | "low";
  multi_job_discount_applied: boolean;
  line_items: LineItem[];
  summary: string;
  caveats: string;
  from_cache?: boolean;
  expires_at?: string;
}

// Area analysis types
export interface AreaMeasurement {
  value_sqm: number;
  confidence: number;
}

export interface LinearMeasurement {
  value_m: number;
  confidence: number;
}

export interface AreaAnalysisResult {
  success: boolean;
  fallback_used: boolean;
  from_cache: boolean;
  // Core areas
  lawn: AreaMeasurement;
  roof: AreaMeasurement;
  garden: AreaMeasurement;
  // Gutter perimeter
  gutter: LinearMeasurement;
  // Driveway split
  driveway_exposed: AreaMeasurement;
  driveway_covered: AreaMeasurement;
  overhang_detected: boolean;
  overhang_description: string;
  // Metadata
  overall_confidence: "high" | "medium" | "low";
  image_quality: "clear" | "partial" | "obscured";
  terrain_detected: "flat" | "sloped" | "unknown";
  analysis_notes: string;
  error?: string;
}

export async function fetchJobs(): Promise<Job[]> {
  const res = await fetch(`${API_BASE}/jobs`);
  if (!res.ok) throw new Error("Failed to load job types");
  const data = await res.json();
  return data.jobs;
}

export async function analyseProperty(address: string): Promise<AreaAnalysisResult> {
  const params = new URLSearchParams({ address });
  const res = await fetch(`${API_BASE}/analyse-property?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Property analysis failed (${res.status})`);
  }
  return res.json();
}

export async function submitQuote(request: QuoteRequest): Promise<QuoteResponse> {
  const res = await fetch(`${API_BASE}/quote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Quote request failed (${res.status})`);
  }
  return res.json();
}
