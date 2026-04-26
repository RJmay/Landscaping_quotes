"""
rate_tuner.py — Step 6: Automated rate tuning from job feedback.

Analyses the gap between quoted prices and actual job prices,
then suggests (and optionally applies) rate adjustments to improve accuracy.

Usage:
  python rate_tuner.py --report          # Show accuracy report only
  python rate_tuner.py --apply           # Apply suggested rate changes to DB
  python rate_tuner.py --min-jobs 10     # Only tune jobs with 10+ data points

How it works:
  1. Loads all completed quotes (actual_price filled in)
  2. Groups by job type
  3. Computes average deviation: actual vs quoted midpoint
  4. If deviation > threshold, suggests a rate adjustment
  5. Optionally writes the adjustment back to job_rates table
"""

import asyncio
import argparse
import sys
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text
from database import AsyncSessionLocal, JobRate, Quote, RateAdjustment


# ─── Config ───────────────────────────────────────────────────────────────────

# Only suggest a rate change if we have at least this many completed jobs
MIN_JOBS_FOR_TUNING = 5

# Only adjust if the deviation exceeds this % of the quoted midpoint
# e.g. 0.10 = only adjust if consistently over/under by 10%+
ADJUSTMENT_THRESHOLD_PCT = 0.10

# Maximum rate change per tuning run (safety cap — prevents wild swings)
MAX_RATE_CHANGE_PCT = 0.20


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_rate_tuner(apply: bool = False, min_jobs: int = MIN_JOBS_FOR_TUNING):
    async with AsyncSessionLocal() as session:
        report = await build_report(session, min_jobs)
        print_report(report)

        if apply:
            await apply_adjustments(session, report)
            print("\n✓ Rate adjustments applied to database.")
        else:
            print("\nRun with --apply to write these changes to the database.")


async def build_report(session, min_jobs: int) -> dict:
    """
    Pull all completed quotes, group by job type, compute deviation stats.
    Returns a structured report with suggested adjustments.
    """
    # Pull completed quotes with actual prices
    result = await session.execute(
        text("""
            SELECT
                id, job_ids, total_min, total_max, actual_price,
                condition_score, lawn_sqm, roof_sqm, gutter_length_m,
                driveway_exposed_sqm, garden_sqm, area_source
            FROM quotes
            WHERE job_completed = TRUE
              AND actual_price IS NOT NULL
              AND actual_price > 0
            ORDER BY created_at DESC
        """)
    )
    rows = result.fetchall()

    if not rows:
        return {"error": "No completed jobs with actual prices found.", "job_stats": {}}

    # Load current job rates
    rate_result = await session.execute(select(JobRate))
    rates = {r.job_id: r for r in rate_result.scalars().all()}

    # Aggregate per job type
    job_data: dict[str, list[dict]] = {}
    for row in rows:
        job_ids = row.job_ids if isinstance(row.job_ids, list) else [row.job_ids]
        quoted_mid = (row.total_min + row.total_max) / 2

        for job_id in job_ids:
            if job_id not in job_data:
                job_data[job_id] = []
            job_data[job_id].append({
                "quote_id": row.id,
                "actual": row.actual_price,
                "quoted_mid": quoted_mid,
                "quoted_min": row.total_min,
                "quoted_max": row.total_max,
                "within_range": row.total_min <= row.actual_price <= row.total_max,
                "deviation_pct": (row.actual_price - quoted_mid) / quoted_mid if quoted_mid else 0,
            })

    # Compute stats and suggestions per job
    job_stats = {}
    for job_id, entries in job_data.items():
        if len(entries) < min_jobs:
            job_stats[job_id] = {
                "status": "insufficient_data",
                "job_count": len(entries),
                "min_required": min_jobs,
                "message": f"Only {len(entries)} completed jobs. Need {min_jobs} to tune."
            }
            continue

        avg_deviation_pct = sum(e["deviation_pct"] for e in entries) / len(entries)
        within_range_pct = sum(1 for e in entries if e["within_range"]) / len(entries) * 100
        avg_actual = sum(e["actual"] for e in entries) / len(entries)
        avg_quoted_mid = sum(e["quoted_mid"] for e in entries) / len(entries)

        # Determine adjustment direction
        suggestion = None
        current_rate = rates.get(job_id)

        if abs(avg_deviation_pct) >= ADJUSTMENT_THRESHOLD_PCT and current_rate:
            # Clamp to max change per run
            raw_change = avg_deviation_pct
            capped_change = max(-MAX_RATE_CHANGE_PCT, min(MAX_RATE_CHANGE_PCT, raw_change))

            field = "base_rate_per_m" if job_id == "gutter_cleaning" else "base_rate_per_sqm"
            current_val = getattr(current_rate, field, None) or current_rate.base_rate_per_sqm
            new_val = round(current_val * (1 + capped_change), 4)

            suggestion = {
                "field": field,
                "current_value": current_val,
                "suggested_value": new_val,
                "change_pct": round(capped_change * 100, 1),
                "direction": "increase" if capped_change > 0 else "decrease",
                "reason": (
                    f"Actual prices averaged {abs(avg_deviation_pct)*100:.1f}% "
                    f"{'above' if avg_deviation_pct > 0 else 'below'} quoted midpoint "
                    f"across {len(entries)} completed jobs."
                ),
            }

        job_stats[job_id] = {
            "status": "ok",
            "job_count": len(entries),
            "avg_actual": round(avg_actual, 2),
            "avg_quoted_mid": round(avg_quoted_mid, 2),
            "avg_deviation_pct": round(avg_deviation_pct * 100, 1),
            "within_range_pct": round(within_range_pct, 1),
            "needs_adjustment": suggestion is not None,
            "suggestion": suggestion,
        }

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "total_completed_quotes": len(rows),
        "job_stats": job_stats,
    }


async def apply_adjustments(session, report: dict):
    """Write suggested rate changes to the database and log them."""
    for job_id, stats in report.get("job_stats", {}).items():
        if not stats.get("needs_adjustment") or not stats.get("suggestion"):
            continue

        suggestion = stats["suggestion"]

        # Update the job rate
        result = await session.execute(
            select(JobRate).where(JobRate.job_id == job_id)
        )
        rate = result.scalar_one_or_none()
        if not rate:
            continue

        old_val = getattr(rate, suggestion["field"])
        setattr(rate, suggestion["field"], suggestion["suggested_value"])
        rate.updated_at = datetime.utcnow()

        # Log the adjustment
        adjustment = RateAdjustment(
            job_id=job_id,
            field_changed=suggestion["field"],
            old_value=old_val,
            new_value=suggestion["suggested_value"],
            reason=suggestion["reason"],
        )
        session.add(adjustment)

    await session.commit()


def print_report(report: dict):
    if "error" in report:
        print(f"\n⚠  {report['error']}")
        return

    print(f"\n{'='*65}")
    print(f"  RATE TUNING REPORT — {report['generated_at'][:10]}")
    print(f"  Total completed quotes analysed: {report['total_completed_quotes']}")
    print(f"{'='*65}")

    for job_id, stats in report["job_stats"].items():
        print(f"\n  {job_id}")
        print(f"  {'─'*50}")

        if stats["status"] == "insufficient_data":
            print(f"  ⏳ {stats['message']}")
            continue

        within = stats["within_range_pct"]
        dev = stats["avg_deviation_pct"]
        icon = "✓" if within >= 75 else "⚠" if within >= 50 else "✗"

        print(f"  {icon} {stats['job_count']} completed jobs")
        print(f"    Avg actual:       ${stats['avg_actual']:.2f}")
        print(f"    Avg quoted mid:   ${stats['avg_quoted_mid']:.2f}")
        print(f"    Avg deviation:    {'+' if dev >= 0 else ''}{dev}%  "
              f"({'underquoting' if dev > 0 else 'overquoting'})")
        print(f"    Within range:     {within}%")

        if stats["needs_adjustment"] and stats["suggestion"]:
            s = stats["suggestion"]
            arrow = "↑" if s["direction"] == "increase" else "↓"
            print(f"\n    {arrow} SUGGESTED ADJUSTMENT:")
            print(f"      {s['field']}: {s['current_value']} → {s['suggested_value']}  ({s['change_pct']:+.1f}%)")
            print(f"      Reason: {s['reason']}")
        else:
            print(f"    ✓ No adjustment needed")


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Landscaping quote rate tuner")
    parser.add_argument("--apply", action="store_true",
                        help="Apply suggested rate changes to the database")
    parser.add_argument("--min-jobs", type=int, default=MIN_JOBS_FOR_TUNING,
                        help=f"Minimum completed jobs needed to tune a rate (default: {MIN_JOBS_FOR_TUNING})")
    args = parser.parse_args()

    asyncio.run(run_rate_tuner(apply=args.apply, min_jobs=args.min_jobs))
