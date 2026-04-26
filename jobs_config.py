"""
jobs_config.py — Job type definitions and prompt builder.

Key updates for gutter perimeter + overhang-aware pressure washing:
  - gutter_cleaning now uses gutter_length_m (linear metres) at $/m rate
  - pressure_washing_driveway now uses driveway_exposed_sqm only (not total driveway)
  - Covered driveway area is passed to Claude as context, may attract a reduced rate
"""

from models import QuoteRequest


JOBS_FALLBACK = {
    "lawn_mowing": {
        "name": "Lawn mowing",
        "description": "Standard ride-on or push mower service",
        "unit": "m² of lawn",
        "base_rate_per_sqm": 0.045,
        "min_charge": 80,
        "condition_multiplier_range": (1.0, 1.6),
        "notes": "Includes edging and blowing clippings off paths.",
    },
    "hedge_trimming": {
        "name": "Hedge trimming",
        "description": "Trim and shape hedges and shrubs",
        "unit": "m² of garden beds",
        "base_rate_per_sqm": 0.12,
        "min_charge": 90,
        "condition_multiplier_range": (1.0, 1.8),
        "notes": "Includes removal of clippings from site.",
    },
    "gutter_cleaning": {
        "name": "Gutter cleaning",
        "description": "Clear and flush all gutters",
        # NOTE: unit is now LINEAR METRES of gutter run, not roof m²
        "unit": "linear metres of gutter",
        "base_rate_per_m": 3.20,          # AUD per linear metre of gutter
        "base_rate_per_sqm": None,        # Not used for this job
        "min_charge": 120,
        "condition_multiplier_range": (1.0, 2.2),
        "notes": "Includes flushing downpipes and bagging debris.",
    },
    "pressure_washing_driveway": {
        "name": "Pressure washing (driveway/patio)",
        "description": "High-pressure clean of exposed driveway and paths",
        # NOTE: priced on EXPOSED area only — covered area excluded or reduced
        "unit": "m² of exposed sealed surface",
        "base_rate_per_sqm": 0.055,
        "min_charge": 100,
        "condition_multiplier_range": (1.0, 1.5),
        "notes": "Priced on open-air area only. Covered/sheltered areas assessed separately.",
    },
    "roof_cleaning": {
        "name": "Roof cleaning",
        "description": "Soft-wash moss, lichen, and dirt from roof tiles",
        "unit": "m² of roof",
        "base_rate_per_sqm": 0.09,
        "min_charge": 200,
        "condition_multiplier_range": (1.0, 1.9),
        "notes": "Includes moss inhibitor treatment.",
    },
    "garden_tidy": {
        "name": "Garden tidy",
        "description": "Weed, mulch, and general garden bed cleanup",
        "unit": "m² of garden beds",
        "base_rate_per_sqm": 0.15,
        "min_charge": 100,
        "condition_multiplier_range": (1.0, 2.0),
        "notes": "Includes weed removal and light mulching.",
    },
}


def build_pricing_prompt(request: QuoteRequest, job_rates: dict = None) -> str:
    """
    Builds the structured pricing prompt for Claude.

    Gutter cleaning: priced on gutter_length_m at a per-metre rate.
    Pressure washing: priced on driveway_exposed_sqm; covered area shown as context.
    """
    use_db = job_rates is not None

    job_lines = []
    for job_id in request.job_ids:
        if use_db:
            rate = job_rates[job_id]
            name = rate.name
            unit = rate.unit
            min_charge = rate.min_charge
            mult_min = rate.condition_mult_min
            mult_max = rate.condition_mult_max
            notes = rate.notes
            # DB stores base_rate_per_sqm; for gutter we also store base_rate_per_m
            base_rate_sqm = rate.base_rate_per_sqm
            base_rate_m = getattr(rate, "base_rate_per_m", None) or rate.base_rate_per_sqm
        else:
            job = JOBS_FALLBACK[job_id]
            name = job["name"]
            unit = job["unit"]
            min_charge = job["min_charge"]
            mult_min, mult_max = job["condition_multiplier_range"]
            notes = job["notes"]
            base_rate_sqm = job.get("base_rate_per_sqm")
            base_rate_m = job.get("base_rate_per_m")

        condition_mult = mult_min + (mult_max - mult_min) * request.condition_score

        # ── Gutter cleaning — per linear metre ────────────────────────────────
        if job_id == "gutter_cleaning":
            length = request.gutter_length_m
            rate_m = base_rate_m or 3.20
            base_cost = length * rate_m
            estimated_cost = max(base_cost * condition_mult, min_charge)

            job_lines.append(f"""
  Job: {name}
    Billing unit: linear metres of gutter run
    Gutter length detected: {length:.1f} m
    Base rate: ${rate_m:.2f} per linear metre
    Min charge: ${min_charge}
    Condition multiplier: {condition_mult:.2f}x (score: {request.condition_score})
    Computed estimate: ${estimated_cost:.0f}
    Notes: {notes}
    Context: Gutter length is the roof perimeter. Longer gutters + overhanging trees = more debris.""")

        # ── Pressure washing — exposed area only, context on covered ─────────
        elif job_id == "pressure_washing_driveway":
            exposed = request.driveway_exposed_sqm
            covered = request.driveway_covered_sqm
            rate_sqm = base_rate_sqm or 0.055
            base_cost = exposed * rate_sqm
            estimated_cost = max(base_cost * condition_mult, min_charge)

            # Covered area note — may attract a small additional charge if very dirty
            covered_note = ""
            if request.overhang_detected and covered > 0:
                covered_note = (
                    f"\n    Covered/sheltered area: {covered:.0f} m² ({request.overhang_description})"
                    f"\n    Covered areas are sheltered from rain so are typically cleaner."
                    f"\n    If the covered area also needs cleaning, add a small surcharge (suggest $0.025–$0.035/m²)."
                )

            job_lines.append(f"""
  Job: {name}
    Billing unit: m² of exposed (open-air) sealed surface
    Exposed driveway/patio area: {exposed:.0f} m²
    Base rate: ${rate_sqm} per m²
    Min charge: ${min_charge}
    Condition multiplier: {condition_mult:.2f}x (score: {request.condition_score})
    Computed estimate (exposed area only): ${estimated_cost:.0f}
    Notes: {notes}{covered_note}""")

        # ── All other jobs — standard per-m² pricing ─────────────────────────
        else:
            relevant_area = _get_relevant_area(job_id, request)
            rate_sqm = base_rate_sqm or 0.05
            base_cost = relevant_area * rate_sqm
            estimated_cost = max(base_cost * condition_mult, min_charge)

            job_lines.append(f"""
  Job: {name}
    Area used: {relevant_area} m² ({unit})
    Base rate: ${rate_sqm} per m²
    Min charge: ${min_charge}
    Condition multiplier: {condition_mult:.2f}x (score: {request.condition_score})
    Computed estimate: ${estimated_cost:.0f}
    Notes: {notes}""")

    jobs_block = "\n".join(job_lines)

    modifiers = []
    if request.travel_zone == "A":
        modifiers.append("Travel zone A: within 10km (+$0)")
    elif request.travel_zone == "B":
        modifiers.append("Travel zone B: 10-25km (+$15 flat fee)")
    elif request.travel_zone == "C":
        modifiers.append("Travel zone C: 25km+ (+$30 flat fee)")
    if request.access_notes:
        modifiers.append(f"Access notes: {request.access_notes}")
    if request.terrain == "sloped":
        modifiers.append("Terrain: sloped — increases labour ~20%")
    elif request.terrain == "flat":
        modifiers.append("Terrain: flat — standard labour time")

    modifiers_block = "\n  ".join(modifiers) if modifiers else "No special modifiers."

    prompt = f"""You are a pricing engine for a professional landscaping company in {request.suburb}, {request.state}, Australia.

Review the computed estimates below and return a realistic final price range.
Use your knowledge of Australian market rates to sanity-check each figure.

PROPERTY DETAILS:
  Address: {request.address}, {request.suburb} {request.state}
  Lawn: {request.lawn_sqm} m²
  Roof: {request.roof_sqm} m²
  Gutter run: {request.gutter_length_m:.1f} linear metres
  Driveway exposed: {request.driveway_exposed_sqm:.0f} m² (open to weather)
  Driveway covered: {request.driveway_covered_sqm:.0f} m² (under overhang)
  Garden beds: {request.garden_sqm} m²
  Overhang: {"Yes — " + request.overhang_description if request.overhang_detected else "None detected"}
  Condition score: {request.condition_score}/1.0 (0=pristine, 1=severely neglected)
  Condition context: {request.condition_context}

SELECTED JOBS + ESTIMATES:
{jobs_block}

MODIFIERS:
  {modifiers_block}

INSTRUCTIONS:
1. Review each estimate. Adjust if your market knowledge suggests a different figure.
2. For gutter cleaning: validate the per-metre rate is realistic for Brisbane (typical: $3–$5/m).
3. For pressure washing: confirm that pricing only the EXPOSED area is correct.
   If the covered area is large and also needs cleaning, note this in caveats.
4. Apply 5-10% multi-service discount if 2+ jobs selected.
5. Add travel modifier if applicable.
6. Widen the range if confidence is low (condition > 0.7, unclear measurements).

Respond ONLY with valid JSON. No preamble, no markdown.

{{
  "total_min": <number>,
  "total_max": <number>,
  "currency": "AUD",
  "confidence": "high" | "medium" | "low",
  "multi_job_discount_applied": <boolean>,
  "line_items": [
    {{
      "job_id": "<id>",
      "job_name": "<name>",
      "min": <number>,
      "max": <number>,
      "notes": "<one sentence on what drives this price>"
    }}
  ],
  "summary": "<2-3 sentences for the customer>",
  "caveats": "<important conditions, especially around overhang areas or gutter access>"
}}"""

    return prompt


def _get_relevant_area(job_id: str, request: QuoteRequest) -> float:
    """
    Maps standard jobs to their billing area.
    Gutter cleaning and pressure washing are handled separately in build_pricing_prompt.
    """
    area_map = {
        "lawn_mowing":   request.lawn_sqm,
        "hedge_trimming": request.garden_sqm,
        "roof_cleaning":  request.roof_sqm,
        "garden_tidy":    request.garden_sqm,
        # Fallback for any new job types not yet given special handling
        "gutter_cleaning": request.gutter_length_m,
        "pressure_washing_driveway": request.driveway_exposed_sqm,
    }
    return area_map.get(job_id, request.lawn_sqm)
