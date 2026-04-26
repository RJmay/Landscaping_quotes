"""
test_maps_agent.py — Test the satellite area detection pipeline.

Run with:
  python test_maps_agent.py

Requires:
  ANTHROPIC_API_KEY  — for Claude vision analysis
  GOOGLE_MAPS_API_KEY — for geocoding + satellite imagery

Without GOOGLE_MAPS_API_KEY it will test the fallback path.
"""

import asyncio
import os

from dotenv import load_dotenv
load_dotenv()

from maps_agent import MapsVisionAgent
from area_cache import AreaAnalysisCache


async def test_agent():
    agent = MapsVisionAgent()
    cache = AreaAnalysisCache()

    test_addresses = [
        "1 William Street, Brisbane QLD 4000",       # Known landmark (tall building, no lawn)
        "42 Eucalyptus Drive, Calamvale QLD 4116",   # Typical suburban
    ]

    for address in test_addresses:
        print(f"\n{'='*60}")
        print(f"Analysing: {address}")
        print("="*60)

        # Check cache first
        cached = cache.get(address)
        if cached:
            print("(From cache)")
            print_analysis(cached)
            continue

        result = await agent.analyse(address)

        if result.success:
            print(f"SUCCESS (fallback={result.fallback_used})")
            print_analysis(result.analysis)
            # Save to cache
            cache.set(address, result.analysis)
        else:
            print(f"FAILED: {result.error}")
            if result.analysis:
                print("Fallback estimates:")
                print_analysis(result.analysis)

    # Test cache hit
    print(f"\n{'='*60}")
    print("Testing cache (second call to first address):")
    print("="*60)
    cached = cache.get(test_addresses[0])
    if cached:
        print(f"Cache HIT — lawn: {cached.lawn_sqm}m²")
    else:
        print("Cache miss (expected if first test failed)")

    print(f"\nCache stats: {cache.stats()}")


def print_analysis(analysis):
    if not analysis:
        return
    print(f"  Lawn:      {analysis.lawn_sqm:.0f} m²  (confidence: {analysis.lawn_confidence:.0%})")
    print(f"  Driveway:  {analysis.driveway_sqm:.0f} m²  (confidence: {analysis.driveway_confidence:.0%})")
    print(f"  Roof:      {analysis.roof_sqm:.0f} m²  (confidence: {analysis.roof_confidence:.0%})")
    print(f"  Garden:    {analysis.garden_sqm:.0f} m²  (confidence: {analysis.garden_confidence:.0%})")
    print(f"  Overall:   {analysis.overall_confidence} confidence")
    print(f"  Terrain:   {analysis.terrain_detected}")
    print(f"  Image:     {analysis.image_quality}")
    print(f"  Notes:     {analysis.analysis_notes}")


if __name__ == "__main__":
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("GOOGLE_MAPS_API_KEY"):
        print("Warning: GOOGLE_MAPS_API_KEY not set — will test fallback path only")

    if "ANTHROPIC_API_KEY" in missing:
        print(f"Error: {', '.join(missing)} environment variable(s) not set.")
        exit(1)

    asyncio.run(test_agent())
