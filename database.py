"""
database.py — Works locally with SQLite OR with Supabase in production.

LOCAL TESTING (no Supabase needed):
  Just run uvicorn — uses a local SQLite file automatically.
  No .env, no setup. Tables created on first startup.

PRODUCTION (Supabase):
  Set in .env:
    DATABASE_URL=postgresql+asyncpg://postgres.REF:PASSWORD@HOST:5432/postgres?ssl=require
  Get it from: Supabase > Settings > Database > Direct connection > URI
  Change postgresql:// to postgresql+asyncpg:// and add ?ssl=require
"""

from dotenv import load_dotenv
load_dotenv()   # MUST be first — loads .env before any os.environ.get() runs

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import Column, String, Float, Boolean, Integer, Text, DateTime, JSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase


def get_database_url() -> tuple:
    url = os.environ.get("DATABASE_URL", "")

    if url:
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        if "supabase" in url and "ssl" not in url:
            url += "?ssl=require"
        connect_args = {"ssl": "require"} if ("supabase" in url or "ssl=require" in url) else {}
        return url, connect_args

    # Fallback: local SQLite (no setup needed)
    db_path = Path(__file__).parent / "landscaping_quotes.db"
    print(f"WARNING: DATABASE_URL not set — using local SQLite: {db_path}")
    return f"sqlite+aiosqlite:///{db_path}", {"check_same_thread": False}


_db_url, _connect_args = get_database_url()
_is_sqlite = _db_url.startswith("sqlite")

engine = create_async_engine(
    _db_url,
    connect_args=_connect_args,
    echo=False,
    **({} if _is_sqlite else {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}),
)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_all_tables():
    """Create all tables — called on startup so SQLite works out of the box."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class Base(DeclarativeBase):
    pass


class JobRate(Base):
    __tablename__ = "job_rates"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    unit = Column(String)
    base_rate_per_sqm = Column(Float, nullable=False)
    base_rate_per_m = Column(Float, nullable=True)
    min_charge = Column(Float, nullable=False)
    condition_mult_min = Column(Float, default=1.0)
    condition_mult_max = Column(Float, default=2.0)
    notes = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SuburbProfile(Base):
    __tablename__ = "suburb_profiles"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    suburb = Column(String, nullable=False)
    state = Column(String, nullable=False)
    postcode = Column(String)
    avg_block_sqm = Column(Float)
    maintenance_tier = Column(Integer)
    dominant_property_type = Column(String, default="house")
    tree_density = Column(String, default="medium")
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class Quote(Base):
    __tablename__ = "quotes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    address = Column(String, nullable=False)
    suburb = Column(String, nullable=False)
    state = Column(String, default="QLD")
    job_ids = Column(JSON, nullable=False)
    lawn_sqm = Column(Float)
    driveway_sqm = Column(Float)
    roof_sqm = Column(Float)
    garden_sqm = Column(Float)
    gutter_length_m = Column(Float)
    driveway_exposed_sqm = Column(Float)
    driveway_covered_sqm = Column(Float)
    condition_score = Column(Float)
    condition_context = Column(Text)
    travel_zone = Column(String)
    terrain = Column(String)
    access_notes = Column(Text)
    total_min = Column(Float)
    total_max = Column(Float)
    confidence = Column(String)
    line_items = Column(JSON)
    summary = Column(Text)
    caveats = Column(Text)
    actual_price = Column(Float, nullable=True)
    job_completed = Column(Boolean, default=False)
    completion_notes = Column(Text, nullable=True)
    area_source = Column(String, default="manual")
    condition_source = Column(String, default="manual")
    customer_name = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    booking_requested = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Booking(Base):
    __tablename__ = "bookings"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    quote_id = Column(String, nullable=False)
    customer_name = Column(String, nullable=False)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    address = Column(String, nullable=False)
    suburb = Column(String, nullable=False)
    job_ids = Column(JSON, nullable=False)
    agreed_price_min = Column(Float)
    agreed_price_max = Column(Float)
    preferred_date = Column(String, nullable=True)
    preferred_time = Column(String, nullable=True)
    special_instructions = Column(Text, nullable=True)
    status = Column(String, default="pending")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RateAdjustment(Base):
    __tablename__ = "rate_adjustments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(String, nullable=False)
    field_changed = Column(String, nullable=False)
    old_value = Column(Float)
    new_value = Column(Float)
    reason = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=datetime.utcnow)
