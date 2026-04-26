"""
test_condition_agent.py — Test the condition scoring agent standalone.

Run with:
  python test_condition_agent.py

No API keys needed — Open-Meteo is free and keyless.
Requires only: pip install httpx
"""

import asyncio
from condition_agent import ConditionAgent


async def main():
    agent = ConditionAgent()

    test_cases = [
        {
            "label": "Calamvale — average suburban, all jobs",
            "lat": -27.617, "lng": 153.033,
            "suburb": "Calamvale",
            "job_ids": ["lawn_mowing", "gutter_cleaning", "pressure_washing_driveway"],
            "suburb_profile": MockProfile(maintenance_tier=3, tree_density="medium",
                avg_block_sqm=600, notes="Standard suburban blocks."),
        },
        {
            "label": "Ascot — prestige, high trees, gutter focus",
            "lat": -27.433, "lng": 153.058,
            "suburb": "Ascot",
            "job_ids": ["gutter_cleaning", "roof_cleaning"],
            "suburb_profile": MockProfile(maintenance_tier=1, tree_density="high",
                avg_block_sqm=700, notes="Large prestige blocks, high tree coverage."),
        },
        {
            "label": "Springwood — outer ring, large block",
            "lat": -27.617, "lng": 153.100,
            "suburb": "Springwood",
            "job_ids": ["lawn_mowing", "garden_tidy", "hedge_trimming"],
            "suburb_profile": MockProfile(maintenance_tier=4, tree_density="high",
                avg_block_sqm=700, notes="Large blocks, near bushland."),
        },
        {
            "label": "No suburb profile — fallback behaviour",
            "lat": -27.470, "lng": 153.021,
            "suburb": "Brisbane City",
            "job_ids": ["pressure_washing_driveway"],
            "suburb_profile": None,
        },
    ]

    for case in test_cases:
        print(f"\n{'='*65}")
        print(f"  {case['label']}")
        print(f"{'='*65}")

        result = await agent.score(
            lat=case["lat"],
            lng=case["lng"],
            suburb=case["suburb"],
            suburb_profile=case["suburb_profile"],
            job_ids=case["job_ids"],
        )

        print(f"  Weather available:    {result.weather_available}")
        print(f"  Suburb profile used:  {result.suburb_profile_used}")
        if result.weather:
            w = result.weather
            print(f"  Rainfall (60d):      {w.total_rainfall_mm}mm over {w.rain_days} rain days")
            print(f"  Avg temp:            {w.avg_temp_c}°C  (max {w.max_temp_c}°C)")
            print(f"  Longest dry spell:   {w.dry_streak_days} days")

        print(f"\n  Per-job condition scores:")
        for job_id in case["job_ids"]:
            score = result.scores.for_job(job_id)
            bar = "█" * int(score * 20)
            print(f"    {job_id:<35} {score:.2f}  {bar}")

        print(f"\n  Context excerpt:")
        ctx = result.condition_context
        # Print first 300 chars wrapped
        for i in range(0, min(len(ctx), 300), 100):
            print(f"    {ctx[i:i+100]}")
        if len(ctx) > 300:
            print(f"    ...")


class MockProfile:
    """Minimal suburb profile for testing without a database."""
    def __init__(self, maintenance_tier, tree_density, avg_block_sqm, notes=""):
        self.maintenance_tier = maintenance_tier
        self.tree_density = tree_density
        self.avg_block_sqm = avg_block_sqm
        self.notes = notes


if __name__ == "__main__":
    asyncio.run(main())
