"""
seed_db.py — Create tables and populate initial data.

Run once after setting up your database:
  python seed_db.py

Safe to re-run — uses upsert logic so it won't duplicate data.
"""

import asyncio
import os
from sqlalchemy import text, select
from sqlalchemy.orm import Session

from dotenv import load_dotenv
load_dotenv()

from database import engine, Base, JobRate, SuburbProfile, AsyncSessionLocal


# ---------------------------------------------------------------------------
# Initial job rates — mirrors the hardcoded JOBS dict from Step 1
# Edit these here, then re-run seed_db.py to update the database
# ---------------------------------------------------------------------------

INITIAL_JOB_RATES = [
    {
        "job_id": "lawn_mowing",
        "name": "Lawn mowing",
        "description": "Standard ride-on or push mower service",
        "unit": "m² of lawn",
        "base_rate_per_sqm": 0.045,
        "min_charge": 80.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 1.6,
        "notes": "Includes edging and blowing clippings off paths.",
        "active": True,
    },
    {
        "job_id": "hedge_trimming",
        "name": "Hedge trimming",
        "description": "Trim and shape hedges and shrubs",
        "unit": "m² of garden beds",
        "base_rate_per_sqm": 0.12,
        "min_charge": 90.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 1.8,
        "notes": "Includes removal of clippings from site.",
        "active": True,
    },
    {
        "job_id": "gutter_cleaning",
        "name": "Gutter cleaning",
        "description": "Clear and flush all gutters",
        "unit": "linear metres of gutter",
        "base_rate_per_sqm": 3.20,   # Stored in base_rate_per_sqm col; treated as $/linear m in code
        "min_charge": 120.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 2.2,
        "notes": "Includes flushing downpipes and bagging debris. Priced per linear metre of gutter run.",
        "active": True,
    },
    {
        "job_id": "pressure_washing_driveway",
        "name": "Pressure washing (driveway)",
        "description": "High-pressure clean of driveway and paths",
        "unit": "m² of sealed surface",
        "base_rate_per_sqm": 0.055,
        "min_charge": 100.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 1.5,
        "notes": "Priced on exposed (open-air) area only. Sheltered/covered areas assessed separately.",
        "active": True,
    },
    {
        "job_id": "roof_cleaning",
        "name": "Roof cleaning",
        "description": "Soft-wash moss, lichen, and dirt from roof tiles",
        "unit": "m² of roof",
        "base_rate_per_sqm": 0.09,
        "min_charge": 200.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 1.9,
        "notes": "Includes moss inhibitor treatment.",
        "active": True,
    },
    {
        "job_id": "garden_tidy",
        "name": "Garden tidy",
        "description": "Weed, mulch, and general garden bed cleanup",
        "unit": "m² of garden beds",
        "base_rate_per_sqm": 0.15,
        "min_charge": 100.0,
        "condition_mult_min": 1.0,
        "condition_mult_max": 2.0,
        "notes": "Includes weed removal and light mulching.",
        "active": True,
    },
]


# ---------------------------------------------------------------------------
# Brisbane/SEQ suburb profiles
# Add suburbs relevant to your service area
# maintenance_tier: 1=prestige/easy, 3=average, 5=outer/large/neglected
# ---------------------------------------------------------------------------

INITIAL_SUBURB_PROFILES = [
    # Inner Brisbane — prestige, small blocks, well maintained
    {"suburb": "Paddington", "state": "QLD", "postcode": "4064", "avg_block_sqm": 400, "maintenance_tier": 1, "dominant_property_type": "house", "tree_density": "medium", "notes": "Character homes, well maintained gardens."},
    {"suburb": "New Farm", "state": "QLD", "postcode": "4005", "avg_block_sqm": 350, "maintenance_tier": 1, "dominant_property_type": "house", "tree_density": "medium", "notes": "High-income suburb, regularly serviced properties."},
    {"suburb": "Ascot", "state": "QLD", "postcode": "4007", "avg_block_sqm": 700, "maintenance_tier": 1, "dominant_property_type": "house", "tree_density": "high", "notes": "Large prestige blocks, high tree coverage, frequent gutter jobs."},
    {"suburb": "Bulimba", "state": "QLD", "postcode": "4171", "avg_block_sqm": 500, "maintenance_tier": 2, "dominant_property_type": "house", "tree_density": "medium", "notes": "Mix of character and new homes."},

    # Middle ring — average suburban
    {"suburb": "Calamvale", "state": "QLD", "postcode": "4116", "avg_block_sqm": 600, "maintenance_tier": 3, "dominant_property_type": "house", "tree_density": "medium", "notes": "Standard suburban blocks, mix of maintenance levels."},
    {"suburb": "Sunnybank Hills", "state": "QLD", "postcode": "4109", "avg_block_sqm": 650, "maintenance_tier": 3, "dominant_property_type": "house", "tree_density": "medium", "notes": "Large multicultural community, varied property upkeep."},
    {"suburb": "Chermside", "state": "QLD", "postcode": "4032", "avg_block_sqm": 550, "maintenance_tier": 3, "dominant_property_type": "house", "tree_density": "low", "notes": "Mixed residential, some rental properties."},
    {"suburb": "Mount Gravatt", "state": "QLD", "postcode": "4122", "avg_block_sqm": 600, "maintenance_tier": 3, "dominant_property_type": "house", "tree_density": "medium", "notes": "Hilly terrain common — flag as sloped for mowing jobs."},

    # Outer ring — larger blocks, more variation
    {"suburb": "Springwood", "state": "QLD", "postcode": "4127", "avg_block_sqm": 700, "maintenance_tier": 4, "dominant_property_type": "house", "tree_density": "high", "notes": "Large blocks, near bushland, high leaf/gutter demand."},
    {"suburb": "Ormeau", "state": "QLD", "postcode": "4208", "avg_block_sqm": 800, "maintenance_tier": 4, "dominant_property_type": "house", "tree_density": "medium", "notes": "New estates and established homes, growing area."},
    {"suburb": "Narangba", "state": "QLD", "postcode": "4504", "avg_block_sqm": 750, "maintenance_tier": 4, "dominant_property_type": "house", "tree_density": "medium", "notes": "Outer northern suburbs, families, larger lawns."},

    # Acreage / rural fringe
    {"suburb": "Samford Valley", "state": "QLD", "postcode": "4520", "avg_block_sqm": 8000, "maintenance_tier": 5, "dominant_property_type": "acreage", "tree_density": "high", "notes": "Large rural blocks, significant travel, high difficulty multiplier."},
    {"suburb": "Dayboro", "state": "QLD", "postcode": "4521", "avg_block_sqm": 10000, "maintenance_tier": 5, "dominant_property_type": "acreage", "tree_density": "high", "notes": "Remote rural, long travel times, quote individually."},
]


async def create_tables():
    """Create all tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables created (or already exist)")


async def seed_job_rates():
    """Upsert job rates — updates existing records, inserts new ones."""
    async with AsyncSessionLocal() as session:
        for rate_data in INITIAL_JOB_RATES:
            result = await session.execute(
                select(JobRate).where(JobRate.job_id == rate_data["job_id"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                for key, value in rate_data.items():
                    setattr(existing, key, value)
            else:
                session.add(JobRate(**rate_data))
        await session.commit()
    print(f"✓ Seeded {len(INITIAL_JOB_RATES)} job rates")


async def seed_suburb_profiles():
    """Upsert suburb profiles — safe to re-run."""
    async with AsyncSessionLocal() as session:
        for profile_data in INITIAL_SUBURB_PROFILES:
            # Check if exists first (no unique constraint on suburb+state combination by default)
            result = await session.execute(
                text("SELECT id FROM suburb_profiles WHERE suburb = :suburb AND state = :state"),
                {"suburb": profile_data["suburb"], "state": profile_data["state"]}
            )
            existing = result.fetchone()
            if existing:
                await session.execute(
                    text("""
                        UPDATE suburb_profiles
                        SET avg_block_sqm = :avg_block_sqm,
                            maintenance_tier = :maintenance_tier,
                            tree_density = :tree_density,
                            notes = :notes
                        WHERE suburb = :suburb AND state = :state
                    """),
                    profile_data
                )
            else:
                obj = SuburbProfile(**profile_data)
                session.add(obj)
        await session.commit()
    print(f"✓ Seeded {len(INITIAL_SUBURB_PROFILES)} suburb profiles")


async def main():
    print("\nSetting up landscaping quote database...\n")
    await create_tables()
    await seed_job_rates()
    await seed_suburb_profiles()
    print("\n✓ Database setup complete. You're ready to run the API.\n")


if __name__ == "__main__":
    asyncio.run(main())
