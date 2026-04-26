"""
models.py — Complete request/response models (Steps 1–6).

Replace your existing models.py with this file entirely.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal


# ── Quote request ──────────────────────────────────────────────────────────────

class QuoteRequest(BaseModel):
    # Address
    address: str = Field(..., description="Full street address")
    suburb: str = Field(..., description="Suburb name")
    state: str = Field(default="QLD")

    # Job selections
    job_ids: List[str] = Field(..., description="List of job type IDs to quote")

    # Core area measurements (Step 4 auto-fills these from satellite)
    lawn_sqm: float = Field(default=200.0, ge=0)
    roof_sqm: float = Field(default=150.0, ge=0)
    garden_sqm: float = Field(default=30.0, ge=0)

    # Gutter cleaning — linear metres of roof perimeter (Step 4b)
    gutter_length_m: float = Field(
        default=50.0, ge=0,
        description="Linear metres of gutter run (roof perimeter)."
    )

    # Pressure washing — exposed vs sheltered split (Step 4b)
    driveway_exposed_sqm: float = Field(
        default=40.0, ge=0,
        description="Sealed area open to sky — priced for pressure washing."
    )
    driveway_covered_sqm: float = Field(
        default=0.0, ge=0,
        description="Sealed area under roof overhang — excluded or reduced rate."
    )
    overhang_detected: bool = Field(default=False)
    overhang_description: str = Field(default="No overhang detected.")

    # Condition scoring (Step 5 computes this automatically from weather)
    condition_score: float = Field(default=0.4, ge=0.0, le=1.0)
    condition_context: str = Field(
        default="Average suburban property, no specific condition data available."
    )

    # Modifiers
    travel_zone: Literal["A", "B", "C"] = Field(default="A")
    terrain: Literal["flat", "sloped", "unknown"] = Field(default="flat")
    access_notes: Optional[str] = Field(default=None)

    # Source tracking
    area_source: str = Field(default="manual", description="manual | maps_vision")

    @field_validator("job_ids")
    @classmethod
    def job_ids_not_empty(cls, v):
        if not v:
            raise ValueError("At least one job must be selected")
        return v

    @property
    def driveway_sqm(self) -> float:
        return self.driveway_exposed_sqm + self.driveway_covered_sqm

    model_config = {
        "json_schema_extra": {
            "example": {
                "address": "42 Eucalyptus Drive",
                "suburb": "Calamvale",
                "state": "QLD",
                "job_ids": ["lawn_mowing", "gutter_cleaning"],
                "lawn_sqm": 320,
                "roof_sqm": 180,
                "garden_sqm": 40,
                "gutter_length_m": 54,
                "driveway_exposed_sqm": 38,
                "driveway_covered_sqm": 18,
                "overhang_detected": True,
                "overhang_description": "Single carport on left side, covers ~18m².",
                "condition_score": 0.6,
                "condition_context": "Above-average growth following recent Brisbane rainfall.",
                "travel_zone": "A",
                "terrain": "flat",
            }
        }
    }


# ── Quote response ─────────────────────────────────────────────────────────────

class LineItem(BaseModel):
    job_id: str
    job_name: str
    min: float
    max: float
    notes: str


class QuoteResponse(BaseModel):
    total_min: float
    total_max: float
    currency: str = "AUD"
    confidence: Literal["high", "medium", "low"]
    multi_job_discount_applied: bool
    line_items: List[LineItem]
    summary: str
    caveats: str


# ── Area analysis (Step 4) ─────────────────────────────────────────────────────

class AreaMeasurement(BaseModel):
    """A single area measurement with confidence score."""
    value_sqm: float
    confidence: float   # 0.0–1.0


class LinearMeasurement(BaseModel):
    """Linear measurement in metres (used for gutter length)."""
    value_m: float
    confidence: float   # 0.0–1.0


class AreaAnalysisResponse(BaseModel):
    """Response from GET /analyse-property — satellite property measurements."""
    success: bool
    fallback_used: bool
    from_cache: bool = False

    # Core areas
    lawn: AreaMeasurement
    roof: AreaMeasurement
    garden: AreaMeasurement

    # Gutter perimeter in linear metres (Step 4b)
    gutter: LinearMeasurement

    # Driveway split — exposed (priced) vs covered/sheltered (Step 4b)
    driveway_exposed: AreaMeasurement
    driveway_covered: AreaMeasurement
    overhang_detected: bool
    overhang_description: str

    # Metadata
    overall_confidence: Literal["high", "medium", "low"]
    image_quality: Literal["clear", "partial", "obscured"]
    terrain_detected: Literal["flat", "sloped", "unknown"]
    analysis_notes: str

    error: Optional[str] = None


# ── Booking (Step 6) ───────────────────────────────────────────────────────────

class BookingRequest(BaseModel):
    quote_id: str
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = "flexible"
    special_instructions: Optional[str] = None


class ActualPriceUpdate(BaseModel):
    actual_price: float
    completion_notes: Optional[str] = None


class BookingStatusUpdate(BaseModel):
    status: str
    notes: Optional[str] = None
