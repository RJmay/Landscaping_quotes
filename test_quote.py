"""
test_quote.py — Run this directly to test the pricing core without a frontend.

Usage:
  python test_quote.py

Make sure ANTHROPIC_API_KEY is set in your environment first.
"""

import os
import json
import anthropic

from dotenv import load_dotenv
load_dotenv()

from jobs_config import JOBS, build_pricing_prompt
from models import QuoteRequest, QuoteResponse


def test_single_job():
    print("\n" + "="*60)
    print("TEST 1: Single job — lawn mowing only")
    print("="*60)

    request = QuoteRequest(
        address="42 Eucalyptus Drive",
        suburb="Calamvale",
        state="QLD",
        job_ids=["lawn_mowing"],
        lawn_sqm=320,
        driveway_sqm=55,
        roof_sqm=180,
        garden_sqm=40,
        condition_score=0.5,
        condition_context="Moderate grass growth. Last mowed approximately 6 weeks ago.",
        travel_zone="A",
        terrain="flat",
    )

    result = run_quote(request)
    print_result(result)


def test_multi_job():
    print("\n" + "="*60)
    print("TEST 2: Multi-job bundle — mowing + gutter cleaning + pressure wash")
    print("="*60)

    request = QuoteRequest(
        address="15 Banksia Street",
        suburb="Sunnybank Hills",
        state="QLD",
        job_ids=["lawn_mowing", "gutter_cleaning", "pressure_washing_driveway"],
        lawn_sqm=280,
        driveway_sqm=80,
        roof_sqm=200,
        garden_sqm=35,
        condition_score=0.75,
        condition_context="Heavy recent rainfall in Brisbane. Lawn is overgrown. Gutters likely full of jacaranda leaves. Driveway has algae growth.",
        travel_zone="B",
        terrain="flat",
        access_notes="Double gate on right side of house, fits standard equipment.",
    )

    result = run_quote(request)
    print_result(result)


def test_neglected_property():
    print("\n" + "="*60)
    print("TEST 3: High condition score — neglected property full clean")
    print("="*60)

    request = QuoteRequest(
        address="8 Wattle Court",
        suburb="Springwood",
        state="QLD",
        job_ids=["lawn_mowing", "hedge_trimming", "garden_tidy", "gutter_cleaning"],
        lawn_sqm=450,
        driveway_sqm=60,
        roof_sqm=160,
        garden_sqm=80,
        condition_score=0.9,
        condition_context="Property vacant for 3+ months. Lawn very overgrown (likely 30cm+). Hedges untrimmed. Garden beds weedy. Gutters blocked.",
        travel_zone="A",
        terrain="sloped",
        access_notes="Narrow side access, some manual carrying required.",
    )

    result = run_quote(request)
    print_result(result)


def run_quote(request: QuoteRequest) -> QuoteResponse:
    client = anthropic.Anthropic()
    prompt = build_pricing_prompt(request)

    print(f"\nAddress: {request.address}, {request.suburb} {request.state}")
    print(f"Jobs: {', '.join(request.job_ids)}")
    print(f"Condition score: {request.condition_score}")
    print("\nCalling Claude API...")

    message = client.messages.create(
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

    data = json.loads(clean)
    return QuoteResponse(**data)


def print_result(result: QuoteResponse):
    print(f"\nQUOTE: ${result.total_min:.0f} – ${result.total_max:.0f} {result.currency}")
    print(f"Confidence: {result.confidence}")
    print(f"Multi-job discount: {'Yes' if result.multi_job_discount_applied else 'No'}")
    print(f"\nBreakdown:")
    for item in result.line_items:
        print(f"  {item.job_name}: ${item.min:.0f} – ${item.max:.0f}")
        print(f"    → {item.notes}")
    print(f"\nSummary: {result.summary}")
    print(f"Caveats: {result.caveats}")


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
        print("Set it with: export ANTHROPIC_API_KEY=your_key_here")
        exit(1)

    test_single_job()
    test_multi_job()
    test_neglected_property()

    print("\n" + "="*60)
    print("All tests complete.")
    print("="*60)
