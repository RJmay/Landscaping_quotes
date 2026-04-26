"""
db_repository.py — All database queries in one place.

This keeps SQL/ORM logic out of main.py and jobs_config.py.
Every function takes a session and returns clean Python objects.
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import JobRate, SuburbProfile, Quote


# ---------------------------------------------------------------------------
# Job rates
# ---------------------------------------------------------------------------

async def get_all_active_job_rates(session: AsyncSession) -> list[JobRate]:
    """Fetch all active job types from the database."""
    result = await session.execute(
        select(JobRate).where(JobRate.active == True).order_by(JobRate.name)
    )
    return result.scalars().all()


async def get_job_rate_by_id(session: AsyncSession, job_id: str) -> Optional[JobRate]:
    """Fetch a single job rate by its job_id slug."""
    result = await session.execute(
        select(JobRate).where(JobRate.job_id == job_id)
    )
    return result.scalar_one_or_none()


async def get_job_rates_by_ids(session: AsyncSession, job_ids: list[str]) -> dict[str, JobRate]:
    """Fetch multiple job rates at once. Returns {job_id: JobRate}."""
    result = await session.execute(
        select(JobRate).where(JobRate.job_id.in_(job_ids))
    )
    rates = result.scalars().all()
    return {rate.job_id: rate for rate in rates}


# ---------------------------------------------------------------------------
# Suburb profiles
# ---------------------------------------------------------------------------

async def get_suburb_profile(
    session: AsyncSession,
    suburb: str,
    state: str
) -> Optional[SuburbProfile]:
    """
    Fetch a suburb profile. Returns None if suburb not in database.
    Step 5 (condition scoring) uses this as a prior.
    """
    result = await session.execute(
        select(SuburbProfile).where(
            SuburbProfile.suburb.ilike(suburb),
            SuburbProfile.state.ilike(state)
        )
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

async def save_quote(
    session: AsyncSession,
    request_data: dict,
    response_data: dict,
    area_source: str = "manual",
    condition_source: str = "manual",
) -> Quote:
    """
    Persist a generated quote to the database.
    Called automatically by the /quote endpoint after Claude responds.
    """
    quote = Quote(
        # Address
        address=request_data["address"],
        suburb=request_data["suburb"],
        state=request_data.get("state", "QLD"),

        # Jobs
        job_ids=request_data["job_ids"],

        # Measurements
        lawn_sqm=request_data.get("lawn_sqm"),
        driveway_sqm=request_data.get("driveway_sqm"),
        roof_sqm=request_data.get("roof_sqm"),
        garden_sqm=request_data.get("garden_sqm"),

        # Condition
        condition_score=request_data.get("condition_score"),
        condition_context=request_data.get("condition_context"),

        # Modifiers
        travel_zone=request_data.get("travel_zone"),
        terrain=request_data.get("terrain"),
        access_notes=request_data.get("access_notes"),

        # Response
        total_min=response_data["total_min"],
        total_max=response_data["total_max"],
        confidence=response_data["confidence"],
        line_items=response_data["line_items"],
        summary=response_data["summary"],
        caveats=response_data["caveats"],

        # Metadata
        area_source=area_source,
        condition_source=condition_source,
    )
    session.add(quote)
    await session.commit()
    await session.refresh(quote)
    return quote


async def get_quote_by_id(session: AsyncSession, quote_id: str) -> Optional[Quote]:
    """Fetch a single saved quote by ID."""
    result = await session.execute(
        select(Quote).where(Quote.id == quote_id)
    )
    return result.scalar_one_or_none()


async def get_recent_quotes(
    session: AsyncSession,
    limit: int = 20,
    suburb: Optional[str] = None
) -> list[Quote]:
    """Fetch recent quotes, optionally filtered by suburb."""
    query = select(Quote).order_by(Quote.created_at.desc()).limit(limit)
    if suburb:
        query = query.where(Quote.suburb.ilike(suburb))
    result = await session.execute(query)
    return result.scalars().all()


async def update_quote_with_actual_price(
    session: AsyncSession,
    quote_id: str,
    actual_price: float,
    completion_notes: Optional[str] = None,
) -> Optional[Quote]:
    """
    Record the real price after a job is completed.
    This is your feedback loop data — over time it lets you tune rates.
    """
    quote = await get_quote_by_id(session, quote_id)
    if not quote:
        return None

    quote.actual_price = actual_price
    quote.job_completed = True
    quote.completion_notes = completion_notes
    quote.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(quote)
    return quote


async def get_quote_accuracy_stats(session: AsyncSession) -> dict:
    """
    Compare quoted ranges to actual prices for completed jobs.
    Returns stats to help you tune your rates over time.
    """
    result = await session.execute(
        text("""
            SELECT
                COUNT(*) as total_completed,
                AVG(actual_price) as avg_actual,
                AVG(total_min) as avg_quoted_min,
                AVG(total_max) as avg_quoted_max,
                AVG(actual_price - (total_min + total_max) / 2) as avg_deviation,
                SUM(CASE WHEN actual_price BETWEEN total_min AND total_max THEN 1 ELSE 0 END) as within_range_count
            FROM quotes
            WHERE job_completed = TRUE AND actual_price IS NOT NULL
        """)
    )
    row = result.fetchone()
    if not row or row.total_completed == 0:
        return {"message": "No completed jobs with actual prices yet."}

    within_range_pct = (row.within_range_count / row.total_completed) * 100

    return {
        "total_completed_jobs": row.total_completed,
        "avg_actual_price": round(row.avg_actual, 2),
        "avg_quoted_min": round(row.avg_quoted_min, 2),
        "avg_quoted_max": round(row.avg_quoted_max, 2),
        "avg_deviation_from_midpoint": round(row.avg_deviation, 2),
        "pct_quotes_within_range": round(within_range_pct, 1),
        "note": "Positive deviation = actual was higher than quoted midpoint (underquoting). Negative = overquoting."
    }
