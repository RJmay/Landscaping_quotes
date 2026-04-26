"""
main.py — FastAPI app (Step 6: Production hardening)

New in Step 6:
  - Quote-level caching (same address+jobs → cached response for 24h)
  - Rate limiting (10 quotes/hour per IP, 5 satellite analyses/hour)
  - POST /booking — convert accepted quote into a booking record
  - GET /bookings — list bookings (owner dashboard)
  - PATCH /bookings/{id}/status — confirm/complete/cancel a booking
  - GET /admin/rate-tuning — run rate accuracy report
  - POST /admin/rate-tuning/apply — apply suggested rate adjustments
  - Periodic cache cleanup task
  - Supabase SSL fix (via updated database.py)
"""

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

import anthropic
from fastapi import FastAPI, HTTPException, Depends, Query, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, Booking, RateAdjustment
from db_repository import (
    get_all_active_job_rates,
    get_job_rates_by_ids,
    get_suburb_profile,
    save_quote,
    get_quote_by_id,
    get_recent_quotes,
    update_quote_with_actual_price,
    get_quote_accuracy_stats,
)
from jobs_config import build_pricing_prompt
from models import QuoteRequest, QuoteResponse, AreaAnalysisResponse, AreaMeasurement, LinearMeasurement
from maps_agent import maps_agent
from area_cache import area_cache
from condition_agent import condition_agent
from quote_cache import quote_cache
from rate_limiter import rate_limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

claude = anthropic.Anthropic()

QUOTE_EXPIRY_HOURS = 48   # Quotes expire after 48 hours


# ─── Startup / shutdown ───────────────────────────────────────────────────────


async def _seed_if_empty():
    """Auto-seed job rates on first run so the app works immediately."""
    from database import AsyncSessionLocal, JobRate
    from sqlalchemy import select, func
    async with AsyncSessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(JobRate))
        if count == 0:
            logger.info("No job rates found — running seed...")
            try:
                import subprocess, sys
                subprocess.run([sys.executable, "seed_db.py"], check=True, capture_output=True)
                logger.info("Seed complete")
            except Exception as e:
                logger.warning(f"Auto-seed failed (run seed_db.py manually): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Landscaping Quote API starting up (Step 6)")
    # Auto-create tables on startup (works for both SQLite and Postgres)
    from database import create_all_tables
    await create_all_tables()
    # Seed job rates if the table is empty
    await _seed_if_empty()
    yield
    logger.info("Shutting down — cleaning up caches")
    rate_limiter.cleanup()


app = FastAPI(
    title="Landscaping Quote API",
    version="5.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "status": "ok",
        "version": "5.0.0",
        "maps_vision_ready": bool(os.environ.get("GOOGLE_MAPS_API_KEY")),
    }


# ─── Jobs ─────────────────────────────────────────────────────────────────────

@app.get("/jobs")
async def get_jobs(db: AsyncSession = Depends(get_db)):
    rates = await get_all_active_job_rates(db)
    return {
        "jobs": [
            {
                "id": r.job_id,
                "name": r.name,
                "description": r.description,
                "unit": r.unit,
                "min_charge": r.min_charge,
            }
            for r in rates
        ]
    }


# ─── Property analysis ────────────────────────────────────────────────────────

@app.get("/analyse-property", response_model=AreaAnalysisResponse)
async def analyse_property(
    request: Request,
    address: str = Query(...),
):
    # Rate limit: 5 satellite analyses per IP per hour
    rate_limiter.check(request, "analyse_property")

    cached = area_cache.get(address)
    if cached:
        return _build_area_response(cached, from_cache=True, success=True, fallback=False)

    result = await maps_agent.analyse(address)

    if result.analysis:
        area_cache.set(address, result.analysis)

    return _build_area_response(
        result.analysis,
        from_cache=False,
        success=result.success,
        fallback=result.fallback_used,
        error=result.error,
    )


def _build_area_response(a, from_cache, success, fallback, error=None) -> AreaAnalysisResponse:
    return AreaAnalysisResponse(
        success=success,
        fallback_used=fallback,
        from_cache=from_cache,
        lawn=AreaMeasurement(value_sqm=a.lawn_sqm, confidence=a.lawn_confidence),
        roof=AreaMeasurement(value_sqm=a.roof_sqm, confidence=a.roof_confidence),
        garden=AreaMeasurement(value_sqm=a.garden_sqm, confidence=a.garden_confidence),
        gutter=LinearMeasurement(value_m=a.gutter_length_m, confidence=a.gutter_length_confidence),
        driveway_exposed=AreaMeasurement(value_sqm=a.driveway_exposed_sqm, confidence=a.driveway_confidence),
        driveway_covered=AreaMeasurement(value_sqm=a.driveway_covered_sqm, confidence=a.driveway_confidence),
        overhang_detected=a.overhang_detected,
        overhang_description=a.overhang_description,
        overall_confidence=a.overall_confidence,
        image_quality=a.image_quality,
        terrain_detected=a.terrain_detected,
        analysis_notes=a.analysis_notes,
        error=error,
    )


# ─── Quick quote — fully automatic ──────────────────────────────────────────
#
# This is the endpoint you should use when testing via /docs.
# Only two fields required: address and job_ids.
# Everything else (area measurements, condition score, suburb) is automatic.

class QuickQuoteRequest(BaseModel):
    address: str
    job_ids: list[str]
    # Optional overrides — leave blank to let the system detect automatically
    travel_zone: str = "A"          # A=within 10km, B=10-25km, C=25km+
    terrain: str = "flat"           # flat | sloped | unknown
    access_notes: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "address": "15 Banksia Street, Sunnybank Hills QLD 4109",
                "job_ids": ["lawn_mowing", "gutter_cleaning"],
                "travel_zone": "A",
                "terrain": "flat",
            }
        }
    }


@app.post("/quick-quote")
async def quick_quote(
    request_obj: Request,
    body: QuickQuoteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Fully automatic quote — only needs address and job_ids.

    The backend automatically:
      1. Checks the quote cache (returns instantly if same address+jobs within 24h)
      2. Geocodes the address to extract suburb/state
      3. Runs satellite analysis to detect lawn, roof, gutter, driveway measurements
      4. Fetches 60 days of weather data for condition scoring
      5. Loads job rates from database
      6. Calls Claude to synthesise a realistic price range
      7. Saves the quote and returns it with a quote_id
    """
    rate_limiter.check(request_obj, "quote")

    # ── Cache check ───────────────────────────────────────────────────────────
    cached = quote_cache.get(body.address, body.job_ids)
    if cached:
        logger.info(f"Quick-quote cache HIT: {body.address[:40]}")
        cached["from_cache"] = True
        return cached

    # ── Step 1: Geocode to get suburb/state/coordinates ───────────────────────
    logger.info(f"Quick-quote: geocoding {body.address}")
    coords = await maps_agent._geocode(body.address)
    if not coords:
        raise HTTPException(
            status_code=400,
            detail=f"Could not find address: '{body.address}'. Check the spelling and include suburb and state (e.g. 'Calamvale QLD')."
        )

    # Parse suburb and state from the geocoded formatted address
    suburb, state = _parse_suburb_state(coords.formatted_address)
    logger.info(f"Geocoded to: {suburb}, {state} ({coords.lat:.4f}, {coords.lng:.4f})")

    # ── Step 2: Satellite area detection ─────────────────────────────────────
    logger.info(f"Quick-quote: running satellite analysis")
    area_result = area_cache.get(body.address)
    area_source = "manual"

    if not area_result:
        agent_result = await maps_agent.analyse(body.address)
        if agent_result.analysis:
            area_result = agent_result.analysis
            area_cache.set(body.address, area_result)
            area_source = "maps_vision" if agent_result.success and not agent_result.fallback_used else "manual"
    else:
        area_source = "maps_vision"
        logger.info("Quick-quote: area from cache")

    # If satellite completely unavailable, use suburb average block size as fallback
    if not area_result:
        from maps_agent import MapsVisionAgent
        area_result = MapsVisionAgent()._fallback_analysis()

    # ── Step 3: Condition scoring from weather ────────────────────────────────
    logger.info(f"Quick-quote: scoring condition for {suburb}")
    suburb_profile = await get_suburb_profile(db, suburb, state)
    condition_result = None
    condition_source = "manual"

    try:
        condition_result = await condition_agent.score(
            lat=coords.lat,
            lng=coords.lng,
            suburb=suburb,
            suburb_profile=suburb_profile,
            job_ids=body.job_ids,
        )
        condition_source = "weather_api" if condition_result.weather_available else "suburb_profile"
    except Exception as e:
        logger.warning(f"Condition scoring failed: {e}")

    # Compute per-job condition score
    if condition_result:
        job_scores = [condition_result.scores.for_job(jid) for jid in body.job_ids]
        condition_score = round(sum(job_scores) / len(job_scores), 2)
        condition_context = condition_result.condition_context
    else:
        condition_score = 0.4
        condition_context = f"Average suburban property in {suburb}, {state}."
        if suburb_profile:
            condition_context += f" Suburb maintenance tier {suburb_profile.maintenance_tier}/5, tree density {suburb_profile.tree_density}."

    # ── Step 4: Load job rates ────────────────────────────────────────────────
    job_rates = await get_job_rates_by_ids(db, body.job_ids)
    missing = [jid for jid in body.job_ids if jid not in job_rates]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown job type(s): {missing}. Call GET /jobs to see valid options."
        )

    # ── Step 5: Build the full QuoteRequest from auto-detected data ───────────
    # Detect terrain from satellite if unknown
    terrain = body.terrain
    if terrain == "flat" and area_result.terrain_detected == "sloped":
        terrain = "sloped"

    full_request = QuoteRequest(
        address=body.address,
        suburb=suburb,
        state=state,
        job_ids=body.job_ids,
        # Measurements from satellite (or fallback averages)
        lawn_sqm=area_result.lawn_sqm,
        roof_sqm=area_result.roof_sqm,
        garden_sqm=area_result.garden_sqm,
        gutter_length_m=area_result.gutter_length_m,
        driveway_exposed_sqm=area_result.driveway_exposed_sqm,
        driveway_covered_sqm=area_result.driveway_covered_sqm,
        overhang_detected=area_result.overhang_detected,
        overhang_description=area_result.overhang_description,
        # Condition from weather + suburb
        condition_score=condition_score,
        condition_context=condition_context,
        # Modifiers
        travel_zone=body.travel_zone,
        terrain=terrain,
        access_notes=body.access_notes,
        area_source=area_source,
    )

    # ── Step 6: Call Claude for the price ─────────────────────────────────────
    logger.info(f"Quick-quote: calling Claude (condition={condition_score}, area_source={area_source})")
    prompt = build_pricing_prompt(full_request, job_rates=job_rates)

    message = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Claude returned non-JSON: {raw[:200]}")

    # ── Step 7: Save and return ───────────────────────────────────────────────
    data["expires_at"] = (datetime.utcnow() + timedelta(hours=48)).isoformat()
    data["from_cache"] = False
    data["area_source"] = area_source
    data["condition_score"] = condition_score
    data["condition_source"] = condition_source
    data["suburb_detected"] = suburb
    data["measurements"] = {
        "lawn_sqm": round(area_result.lawn_sqm),
        "roof_sqm": round(area_result.roof_sqm),
        "gutter_length_m": round(area_result.gutter_length_m, 1),
        "driveway_exposed_sqm": round(area_result.driveway_exposed_sqm),
        "driveway_covered_sqm": round(area_result.driveway_covered_sqm),
        "garden_sqm": round(area_result.garden_sqm),
        "overhang_detected": area_result.overhang_detected,
        "satellite_confidence": area_result.overall_confidence,
    }

    try:
        saved = await save_quote(
            db,
            request_data=full_request.model_dump(),
            response_data=data,
            area_source=area_source,
            condition_source=condition_source,
        )
        data["quote_id"] = saved.id
    except Exception as e:
        logger.warning(f"Failed to save quote: {e}")

    quote_cache.set(body.address, body.job_ids, data)
    background_tasks.add_task(rate_limiter.cleanup)

    return data


def _parse_suburb_state(formatted_address: str) -> tuple[str, str]:
    """
    Extract suburb and state from a Google-formatted Australian address.
    e.g. '15 Banksia St, Sunnybank Hills QLD 4109, Australia' → ('Sunnybank Hills', 'QLD')
    """
    au_states = {"QLD", "NSW", "VIC", "WA", "SA", "TAS", "ACT", "NT"}
    parts = [p.strip() for p in formatted_address.split(",")]

    suburb = "Unknown"
    state = "QLD"

    for part in parts:
        tokens = part.strip().split()
        for i, token in enumerate(tokens):
            if token in au_states:
                state = token
                # Suburb is everything before the state code in this segment
                suburb_candidate = " ".join(tokens[:i]).strip()
                if suburb_candidate:
                    suburb = suburb_candidate
                break

    # Fallback: second-to-last comma segment often has the suburb
    if suburb == "Unknown" and len(parts) >= 3:
        suburb = parts[-3].strip()

    return suburb, state


# ─── Quote endpoint ───────────────────────────────────────────────────────────

@app.post("/quote")
async def get_quote(
    request_obj: Request,
    request: QuoteRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    # Rate limit: 10 quotes/hour per IP
    rate_limiter.check(request_obj, "quote")

    # ── Quote cache check ─────────────────────────────────────────────────────
    cached_quote = quote_cache.get(request.address, request.job_ids)
    if cached_quote:
        logger.info(f"Quote cache HIT: {request.address[:40]}")
        cached_quote["from_cache"] = True
        return cached_quote

    # ── Load job rates from DB ────────────────────────────────────────────────
    job_rates = await get_job_rates_by_ids(db, request.job_ids)
    missing = [jid for jid in request.job_ids if jid not in job_rates]
    if missing:
        raise HTTPException(status_code=400, detail=f"Unknown job type(s): {missing}")

    # ── Condition scoring (Step 5) ────────────────────────────────────────────
    suburb_profile = await get_suburb_profile(db, request.suburb, request.state)
    condition_result = None
    condition_source = "manual"

    try:
        suburb_coords = await _geocode_suburb(request.suburb, request.state)
        if suburb_coords:
            lat, lng = suburb_coords
            condition_result = await condition_agent.score(
                lat=lat, lng=lng,
                suburb=request.suburb,
                suburb_profile=suburb_profile,
                job_ids=request.job_ids,
            )
            condition_source = "weather_api" if condition_result.weather_available else "suburb_profile"
    except Exception as e:
        logger.warning(f"Condition scoring failed: {e}")

    if condition_result:
        job_scores = [condition_result.scores.for_job(jid) for jid in request.job_ids]
        auto_score = round(sum(job_scores) / len(job_scores), 2)
        enriched_ctx = condition_result.condition_context
        if request.area_source == "maps_vision":
            enriched_ctx += " [Measurements from satellite imagery.]"
        request = request.model_copy(update={
            "condition_score": auto_score,
            "condition_context": enriched_ctx,
        })
    else:
        enriched_ctx = request.condition_context
        if suburb_profile:
            enriched_ctx += (
                f" [Suburb: maintenance tier {suburb_profile.maintenance_tier}/5, "
                f"tree density {suburb_profile.tree_density}.]"
            )
        request = request.model_copy(update={"condition_context": enriched_ctx})

    # ── Call Claude ───────────────────────────────────────────────────────────
    prompt = build_pricing_prompt(request, job_rates=job_rates)
    message = claude.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail=f"Claude returned non-JSON: {raw[:200]}")

    # ── Set quote expiry ──────────────────────────────────────────────────────
    expires_at = datetime.utcnow() + timedelta(hours=QUOTE_EXPIRY_HOURS)
    data["expires_at"] = expires_at.isoformat()
    data["from_cache"] = False

    # ── Save to DB ────────────────────────────────────────────────────────────
    try:
        saved = await save_quote(
            db,
            request_data=request.model_dump(),
            response_data=data,
            area_source=request.area_source,
            condition_source=condition_source,
        )
        data["quote_id"] = saved.id
    except Exception as e:
        logger.warning(f"Failed to save quote: {e}")

    # ── Cache the result ──────────────────────────────────────────────────────
    quote_cache.set(request.address, request.job_ids, data)

    # ── Cleanup in background ─────────────────────────────────────────────────
    background_tasks.add_task(rate_limiter.cleanup)

    return data


# ─── Quote history ────────────────────────────────────────────────────────────

@app.get("/quotes")
async def list_quotes(
    limit: int = 20,
    suburb: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    quotes = await get_recent_quotes(db, limit=limit, suburb=suburb)
    return {
        "count": len(quotes),
        "quotes": [
            {
                "id": q.id,
                "address": q.address,
                "suburb": q.suburb,
                "job_ids": q.job_ids,
                "total_min": q.total_min,
                "total_max": q.total_max,
                "confidence": q.confidence,
                "area_source": q.area_source,
                "condition_source": q.condition_source,
                "job_completed": q.job_completed,
                "actual_price": q.actual_price,
                "booking_requested": q.booking_requested,
                "created_at": q.created_at.isoformat(),
            }
            for q in quotes
        ]
    }


@app.get("/quotes/{quote_id}")
async def get_quote_detail(quote_id: str, db: AsyncSession = Depends(get_db)):
    quote = await get_quote_by_id(db, quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "id": quote.id,
        "address": quote.address,
        "suburb": quote.suburb,
        "job_ids": quote.job_ids,
        "total_min": quote.total_min,
        "total_max": quote.total_max,
        "confidence": quote.confidence,
        "line_items": quote.line_items,
        "summary": quote.summary,
        "caveats": quote.caveats,
        "condition_score": quote.condition_score,
        "area_source": quote.area_source,
        "condition_source": quote.condition_source,
        "job_completed": quote.job_completed,
        "actual_price": quote.actual_price,
        "booking_requested": quote.booking_requested,
        "created_at": quote.created_at.isoformat(),
    }


# ─── Feedback loop ────────────────────────────────────────────────────────────

class ActualPriceUpdate(BaseModel):
    actual_price: float
    completion_notes: Optional[str] = None


@app.patch("/quotes/{quote_id}/actual-price")
async def record_actual_price(
    quote_id: str,
    body: ActualPriceUpdate,
    db: AsyncSession = Depends(get_db),
):
    updated = await update_quote_with_actual_price(
        db, quote_id, body.actual_price, body.completion_notes
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "quote_id": quote_id,
        "actual_price": updated.actual_price,
        "quoted_range": f"${updated.total_min}–${updated.total_max}",
        "within_range": updated.total_min <= updated.actual_price <= updated.total_max,
    }


# ─── Step 6: Bookings ─────────────────────────────────────────────────────────

class BookingRequest(BaseModel):
    quote_id: str
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    preferred_date: Optional[str] = None      # "ASAP" or "2025-03-15"
    preferred_time: Optional[str] = "flexible"  # "morning" / "afternoon" / "flexible"
    special_instructions: Optional[str] = None


@app.post("/booking")
async def create_booking(body: BookingRequest, db: AsyncSession = Depends(get_db)):
    """
    Convert an accepted quote into a booking.
    Called when the customer clicks "Book this job" on the quote card.
    """
    quote = await get_quote_by_id(db, body.quote_id)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    booking = Booking(
        quote_id=body.quote_id,
        customer_name=body.customer_name,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        address=quote.address,
        suburb=quote.suburb,
        job_ids=quote.job_ids,
        agreed_price_min=quote.total_min,
        agreed_price_max=quote.total_max,
        preferred_date=body.preferred_date,
        preferred_time=body.preferred_time,
        special_instructions=body.special_instructions,
        status="pending",
    )
    db.add(booking)

    # Mark the quote as having a booking request
    quote.booking_requested = True
    quote.customer_name = body.customer_name
    quote.customer_email = body.customer_email
    quote.customer_phone = body.customer_phone

    await db.commit()
    await db.refresh(booking)

    logger.info(f"Booking created: {booking.id} for {quote.address}")

    return {
        "booking_id": booking.id,
        "status": booking.status,
        "address": booking.address,
        "jobs": booking.job_ids,
        "agreed_price_range": f"${booking.agreed_price_min}–${booking.agreed_price_max} AUD",
        "preferred_date": booking.preferred_date,
        "preferred_time": booking.preferred_time,
        "message": "Your booking request has been received. We'll be in touch to confirm.",
    }


@app.get("/bookings")
async def list_bookings(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """List bookings — for the owner's dashboard."""
    query = select(Booking).order_by(Booking.created_at.desc()).limit(limit)
    if status:
        query = query.where(Booking.status == status)
    result = await db.execute(query)
    bookings = result.scalars().all()

    return {
        "count": len(bookings),
        "bookings": [
            {
                "id": b.id,
                "quote_id": b.quote_id,
                "customer_name": b.customer_name,
                "customer_email": b.customer_email,
                "customer_phone": b.customer_phone,
                "address": b.address,
                "suburb": b.suburb,
                "job_ids": b.job_ids,
                "agreed_price_min": b.agreed_price_min,
                "agreed_price_max": b.agreed_price_max,
                "preferred_date": b.preferred_date,
                "preferred_time": b.preferred_time,
                "special_instructions": b.special_instructions,
                "status": b.status,
                "created_at": b.created_at.isoformat(),
            }
            for b in bookings
        ]
    }


class BookingStatusUpdate(BaseModel):
    status: str   # "confirmed" | "completed" | "cancelled"
    notes: Optional[str] = None


@app.patch("/bookings/{booking_id}/status")
async def update_booking_status(
    booking_id: str,
    body: BookingStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update booking status — used by the owner to confirm/complete/cancel."""
    valid_statuses = {"pending", "confirmed", "completed", "cancelled"}
    if body.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {valid_statuses}")

    result = await db.execute(select(Booking).where(Booking.id == booking_id))
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = body.status
    booking.notes = body.notes
    booking.updated_at = datetime.utcnow()
    await db.commit()

    return {"booking_id": booking_id, "status": booking.status}


# ─── Condition check ──────────────────────────────────────────────────────────

@app.get("/condition")
async def check_condition(
    request: Request,
    address: str = Query(...),
    suburb: str = Query(...),
    state: str = Query(default="QLD"),
    job_ids: str = Query(default="lawn_mowing"),
    db: AsyncSession = Depends(get_db),
):
    rate_limiter.check(request, "condition")
    job_list = [j.strip() for j in job_ids.split(",")]
    suburb_profile = await get_suburb_profile(db, suburb, state)
    coords = await _geocode_suburb(suburb, state)

    if not coords:
        raise HTTPException(status_code=400, detail=f"Could not geocode suburb: {suburb}")

    lat, lng = coords
    result = await condition_agent.score(
        lat=lat, lng=lng,
        suburb=suburb,
        suburb_profile=suburb_profile,
        job_ids=job_list,
    )

    return {
        "suburb": suburb,
        "state": state,
        "weather_available": result.weather_available,
        "suburb_profile_found": result.suburb_profile_used,
        "scores": {
            "lawn_mowing":              result.scores.lawn_mowing,
            "gutter_cleaning":          result.scores.gutter_cleaning,
            "roof_cleaning":            result.scores.roof_cleaning,
            "pressure_washing_driveway": result.scores.pressure_washing,
            "garden_tidy":              result.scores.garden_tidy,
            "hedge_trimming":           result.scores.hedge_trimming,
        },
        "weather_summary": {
            "total_rainfall_mm": result.weather.total_rainfall_mm if result.weather else None,
            "avg_temp_c":        result.weather.avg_temp_c if result.weather else None,
            "rain_days":         result.weather.rain_days if result.weather else None,
            "dry_streak_days":   result.weather.dry_streak_days if result.weather else None,
        } if result.weather else None,
        "condition_context": result.condition_context,
    }


# ─── Admin ────────────────────────────────────────────────────────────────────

@app.get("/admin/stats")
async def quote_accuracy_stats(db: AsyncSession = Depends(get_db)):
    return await get_quote_accuracy_stats(db)


@app.get("/admin/suburb/{suburb}")
async def suburb_info(suburb: str, state: str = "QLD", db: AsyncSession = Depends(get_db)):
    profile = await get_suburb_profile(db, suburb, state)
    if not profile:
        return {"found": False, "suburb": suburb}
    return {
        "found": True, "suburb": profile.suburb, "state": profile.state,
        "maintenance_tier": profile.maintenance_tier,
        "avg_block_sqm": profile.avg_block_sqm,
        "tree_density": profile.tree_density, "notes": profile.notes,
    }


@app.get("/admin/cache-stats")
async def cache_stats():
    return {
        "area_cache": area_cache.stats(),
        "quote_cache": quote_cache.stats(),
        "maps_api_configured": bool(os.environ.get("GOOGLE_MAPS_API_KEY")),
    }


@app.delete("/admin/cache/area")
async def invalidate_area_cache(address: str = Query(...)):
    area_cache.invalidate(address)
    return {"invalidated": f"area cache for: {address}"}


@app.delete("/admin/cache/quote")
async def invalidate_quote_cache(
    address: str = Query(...),
    job_ids: str = Query(..., description="Comma-separated job IDs"),
):
    job_list = [j.strip() for j in job_ids.split(",")]
    quote_cache.invalidate(address, job_list)
    return {"invalidated": f"quote cache for: {address} / {job_list}"}


@app.get("/admin/rate-tuning")
async def rate_tuning_report(
    min_jobs: int = Query(default=5, description="Min completed jobs to include a rate in analysis"),
    db: AsyncSession = Depends(get_db),
):
    """
    Show rate tuning report — compares quoted prices to actual prices.
    Run this after you've completed and recorded 5+ jobs per service type.
    """
    from rate_tuner import build_report
    report = await build_report(db, min_jobs)
    return report


@app.post("/admin/rate-tuning/apply")
async def apply_rate_tuning(
    min_jobs: int = Query(default=5),
    db: AsyncSession = Depends(get_db),
):
    """
    Apply suggested rate adjustments from the tuning report.
    This modifies your job_rates table — changes take effect immediately.
    """
    from rate_tuner import build_report, apply_adjustments
    report = await build_report(db, min_jobs)
    await apply_adjustments(db, report)

    adjusted = [
        jid for jid, stats in report.get("job_stats", {}).items()
        if stats.get("needs_adjustment")
    ]
    return {
        "adjusted_jobs": adjusted,
        "message": f"Rate adjustments applied for: {', '.join(adjusted) or 'none needed'}",
        "report": report,
    }


@app.get("/admin/rate-history")
async def rate_history(
    job_id: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    """Show history of all rate changes."""
    query = select(RateAdjustment).order_by(RateAdjustment.changed_at.desc()).limit(limit)
    if job_id:
        query = query.where(RateAdjustment.job_id == job_id)
    result = await db.execute(query)
    adjustments = result.scalars().all()
    return {
        "count": len(adjustments),
        "history": [
            {
                "job_id": a.job_id,
                "field": a.field_changed,
                "old_value": a.old_value,
                "new_value": a.new_value,
                "change_pct": round((a.new_value - a.old_value) / a.old_value * 100, 1) if a.old_value else None,
                "reason": a.reason,
                "changed_at": a.changed_at.isoformat(),
            }
            for a in adjustments
        ]
    }


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _geocode_suburb(suburb: str, state: str) -> Optional[tuple[float, float]]:
    address = f"{suburb}, {state}, Australia"
    coords = await maps_agent._geocode(address)
    if coords:
        return (coords.lat, coords.lng)
    return None
