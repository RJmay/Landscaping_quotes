"""
condition_agent.py — Step 5: Automatic condition scoring.

Replaces the hardcoded condition_score=0.4 placeholder from Steps 1–4.

Pipeline:
  1. Geocode coordinates from suburb name (reuses maps_agent geocoder)
  2. Fetch last 60 days of weather from Open-Meteo (free, no API key needed)
  3. Load suburb profile from database (maintenance tier, tree density)
  4. Score each job category independently based on weather + suburb signals
  5. Return ConditionResult with per-job scores + plain-English context string

Scores feed directly into jobs_config.py condition multipliers.
Score of 0.0 = pristine/just maintained. 1.0 = maximum difficulty/neglect.

Open-Meteo: https://open-meteo.com — completely free, no key, 10k req/day limit.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class WeatherSummary:
    """60-day weather snapshot for a location."""
    total_rainfall_mm: float           # Total precipitation over window
    avg_temp_c: float                  # Mean daily temperature
    rain_days: int                     # Days with >1mm rainfall
    max_temp_c: float                  # Peak temperature in window
    dry_streak_days: int               # Longest consecutive dry spell
    data_available: bool = True


@dataclass
class ConditionScores:
    """
    Per-job condition scores (0.0 = easy/pristine, 1.0 = maximum difficulty).

    Different jobs are affected by different conditions:
      - Lawn mowing: driven by rainfall + temperature (growth rate)
      - Gutter cleaning: driven by rainfall + tree density (leaf/debris accumulation)
      - Roof cleaning: driven by humidity, rainfall, time since last clean (moss/lichen)
      - Pressure washing: driven by rainfall (algae/moss on pavers) + dry streaks (dust)
      - Garden tidy: driven by rainfall + temperature (weed growth)
      - Hedge trimming: driven by temperature + season (growth rate)
    """
    lawn_mowing: float = 0.4
    gutter_cleaning: float = 0.4
    roof_cleaning: float = 0.4
    pressure_washing: float = 0.4
    garden_tidy: float = 0.4
    hedge_trimming: float = 0.4
    default: float = 0.4             # Used for any job not listed above

    def for_job(self, job_id: str) -> float:
        """Return the appropriate score for a given job type."""
        mapping = {
            "lawn_mowing":              self.lawn_mowing,
            "gutter_cleaning":          self.gutter_cleaning,
            "roof_cleaning":            self.roof_cleaning,
            "pressure_washing_driveway": self.pressure_washing,
            "garden_tidy":              self.garden_tidy,
            "hedge_trimming":           self.hedge_trimming,
        }
        return mapping.get(job_id, self.default)


@dataclass
class ConditionResult:
    """Full output from the condition agent."""
    scores: ConditionScores
    weather: Optional[WeatherSummary]

    # Rich context string passed to Claude in the pricing prompt
    condition_context: str

    # Source tracking
    weather_available: bool = True
    suburb_profile_used: bool = False
    fallback_used: bool = False


# ─── Condition agent ──────────────────────────────────────────────────────────

class ConditionAgent:
    """
    Scores property condition for each job type using weather data + suburb profile.

    Usage:
        agent = ConditionAgent()
        result = await agent.score(
            lat=-27.55,
            lng=153.02,
            suburb="Calamvale",
            suburb_profile=profile,   # SuburbProfile ORM object or None
            job_ids=["lawn_mowing", "gutter_cleaning"],
        )
        print(result.scores.lawn_mowing)   # e.g. 0.72
        print(result.condition_context)    # Rich string for Claude
    """

    # Window for weather analysis
    WEATHER_DAYS = 60

    # Open-Meteo endpoint — free, no key
    OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
    OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self):
        pass  # No API keys needed

    async def score(
        self,
        lat: float,
        lng: float,
        suburb: str,
        suburb_profile=None,        # SuburbProfile ORM object or None
        job_ids: list[str] = None,
    ) -> ConditionResult:
        """
        Main entry point. Fetches weather and computes condition scores.
        Always returns a result — falls back gracefully if weather unavailable.
        """
        job_ids = job_ids or []

        # Fetch weather
        weather = await self._fetch_weather(lat, lng)

        # Compute scores
        scores = self._compute_scores(weather, suburb_profile)

        # Build rich context string
        context = self._build_context(weather, suburb_profile, suburb, scores, job_ids)

        return ConditionResult(
            scores=scores,
            weather=weather,
            condition_context=context,
            weather_available=weather is not None and weather.data_available,
            suburb_profile_used=suburb_profile is not None,
            fallback_used=weather is None or not weather.data_available,
        )

    # ── Weather fetching ──────────────────────────────────────────────────────

    async def _fetch_weather(self, lat: float, lng: float) -> Optional[WeatherSummary]:
        """
        Fetches last 60 days of weather from Open-Meteo archive API.
        Returns None on network failure (scores fall back to defaults).
        """
        end_date = datetime.utcnow().date()
        start_date = end_date - timedelta(days=self.WEATHER_DAYS)

        params = {
            "latitude": lat,
            "longitude": lng,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "daily": [
                "precipitation_sum",
                "temperature_2m_max",
                "temperature_2m_mean",
            ],
            "timezone": "Australia/Brisbane",
        }

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(self.OPEN_METEO_ARCHIVE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            daily = data.get("daily", {})
            precip = daily.get("precipitation_sum", [])
            temp_max = daily.get("temperature_2m_max", [])
            temp_mean = daily.get("temperature_2m_mean", [])

            if not precip:
                logger.warning("Open-Meteo returned empty daily data")
                return self._fallback_weather()

            total_rain = sum(p for p in precip if p is not None)
            rain_days = sum(1 for p in precip if p is not None and p >= 1.0)
            avg_temp = (
                sum(t for t in temp_mean if t is not None) /
                max(len([t for t in temp_mean if t is not None]), 1)
            )
            max_temp = max((t for t in temp_max if t is not None), default=28.0)

            # Calculate longest dry streak
            dry_streak = 0
            current_streak = 0
            for p in precip:
                if p is None or p < 1.0:
                    current_streak += 1
                    dry_streak = max(dry_streak, current_streak)
                else:
                    current_streak = 0

            return WeatherSummary(
                total_rainfall_mm=round(total_rain, 1),
                avg_temp_c=round(avg_temp, 1),
                rain_days=rain_days,
                max_temp_c=round(max_temp, 1),
                dry_streak_days=dry_streak,
                data_available=True,
            )

        except Exception as e:
            logger.warning(f"Open-Meteo weather fetch failed: {e}")
            return self._fallback_weather()

    def _fallback_weather(self) -> WeatherSummary:
        """Brisbane seasonal average used when API unavailable."""
        return WeatherSummary(
            total_rainfall_mm=180.0,   # ~3mm/day average Brisbane
            avg_temp_c=24.0,
            rain_days=20,
            max_temp_c=30.0,
            dry_streak_days=14,
            data_available=False,
        )

    # ── Scoring logic ─────────────────────────────────────────────────────────

    def _compute_scores(
        self,
        weather: Optional[WeatherSummary],
        suburb_profile=None,
    ) -> ConditionScores:
        """
        Compute per-job difficulty scores (0.0–1.0) from weather + suburb signals.

        Each formula is independently tunable. The math is intentionally
        transparent so you can adjust thresholds when real job feedback comes in.
        """
        w = weather or self._fallback_weather()

        # ── Suburb signals ────────────────────────────────────────────────────
        # maintenance_tier: 1=prestige/easy → 5=outer/neglected
        # tree_density: low=0.0, medium=0.5, high=1.0
        maint_tier = getattr(suburb_profile, "maintenance_tier", 3) if suburb_profile else 3
        tree_density_str = getattr(suburb_profile, "tree_density", "medium") if suburb_profile else "medium"
        tree_density = {"low": 0.0, "medium": 0.5, "high": 1.0}.get(tree_density_str, 0.5)

        # Normalise maintenance tier to 0–1 (1=hardest)
        maint_factor = (maint_tier - 1) / 4.0   # tier 1→0.0, tier 5→1.0

        # ── Weather signals ───────────────────────────────────────────────────
        # Rainfall intensity (0–1): 0=drought, 1=very wet (>300mm/60days)
        rain_intensity = min(w.total_rainfall_mm / 300.0, 1.0)

        # Growth driver: warm + wet = fast plant growth
        # Temperature factor: 20°C=0.5 baseline, 35°C=1.0, 15°C=0.0
        temp_factor = max(0.0, min((w.avg_temp_c - 15.0) / 20.0, 1.0))
        growth_driver = (rain_intensity * 0.65) + (temp_factor * 0.35)

        # Algae/moss driver: wet + warm → roof/paver contamination
        # High rain + humid conditions = faster moss/lichen/algae growth
        algae_driver = (rain_intensity * 0.7) + (temp_factor * 0.3)

        # Dust/dirt driver: dry conditions → dust accumulation on pavers
        # Inverted from rain — dry streaks = dusty driveways
        dust_factor = min(w.dry_streak_days / 30.0, 1.0)

        # Debris driver: rain + trees → gutters fill faster
        debris_driver = (rain_intensity * 0.5) + (tree_density * 0.5)

        # ── Per-job scores ────────────────────────────────────────────────────

        # Lawn mowing: growth rate (rain + heat) + maintenance neglect prior
        lawn = _clamp(
            growth_driver * 0.70 +
            maint_factor * 0.30
        )

        # Gutter cleaning: debris accumulation (rain + trees) + maintenance tier
        gutter = _clamp(
            debris_driver * 0.65 +
            maint_factor * 0.25 +
            rain_intensity * 0.10
        )

        # Roof cleaning: algae/moss (wet + warm) + long-term neglect
        # Roof cleaning is less sensitive to short-term weather — moss takes months
        # We weight maintenance tier more heavily here
        roof = _clamp(
            algae_driver * 0.50 +
            maint_factor * 0.40 +
            rain_intensity * 0.10
        )

        # Pressure washing: combination of algae growth (rain → green pavers)
        # and dust accumulation (dry spells → dirty concrete)
        # These partially cancel — wet = algae, dry = dust. Both need cleaning.
        pressure = _clamp(
            algae_driver * 0.40 +
            dust_factor * 0.30 +
            maint_factor * 0.30
        )

        # Garden tidy: weed growth (rain + heat) + maintenance neglect
        garden = _clamp(
            growth_driver * 0.65 +
            maint_factor * 0.35
        )

        # Hedge trimming: driven more by temperature/season than rain
        hedge = _clamp(
            temp_factor * 0.60 +
            growth_driver * 0.25 +
            maint_factor * 0.15
        )

        return ConditionScores(
            lawn_mowing=lawn,
            gutter_cleaning=gutter,
            roof_cleaning=roof,
            pressure_washing=pressure,
            garden_tidy=garden,
            hedge_trimming=hedge,
            default=round((lawn + gutter + roof + pressure + garden + hedge) / 6, 2),
        )

    # ── Context string builder ────────────────────────────────────────────────

    def _build_context(
        self,
        weather: Optional[WeatherSummary],
        suburb_profile,
        suburb: str,
        scores: ConditionScores,
        job_ids: list[str],
    ) -> str:
        """
        Build the rich plain-English condition context passed to Claude's pricing prompt.
        Gives Claude specific, actionable context instead of just a number.
        """
        w = weather or self._fallback_weather()
        parts = []

        # Weather summary
        if w.data_available:
            rain_desc = _describe_rainfall(w.total_rainfall_mm)
            parts.append(
                f"Weather (last 60 days): {w.total_rainfall_mm}mm total rainfall "
                f"({rain_desc}), {w.rain_days} rain days, avg temp {w.avg_temp_c}°C "
                f"(max {w.max_temp_c}°C), longest dry spell {w.dry_streak_days} days."
            )
        else:
            parts.append("Weather data unavailable — using Brisbane seasonal averages.")

        # Suburb profile
        if suburb_profile:
            tier_desc = {1: "prestige/well-maintained", 2: "above-average", 3: "average suburban",
                         4: "outer suburban / mixed upkeep", 5: "outer/rural / high neglect typical"}
            tier = suburb_profile.maintenance_tier
            parts.append(
                f"Suburb profile ({suburb}): {tier_desc.get(tier, 'average')} area, "
                f"avg block {suburb_profile.avg_block_sqm}m², "
                f"tree density {suburb_profile.tree_density}. "
                f"{suburb_profile.notes or ''}"
            )

        # Per-job condition notes (only for selected jobs)
        job_notes = []
        for job_id in job_ids:
            score = scores.for_job(job_id)
            note = _job_condition_note(job_id, score, w, suburb_profile)
            if note:
                job_notes.append(note)

        if job_notes:
            parts.append("Job-specific conditions: " + " | ".join(job_notes))

        # Data quality note
        if not w.data_available:
            parts.append("Note: condition scores are estimates based on suburb profile only.")

        return " ".join(parts)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.05, hi: float = 0.95) -> float:
    """Clamp to [lo, hi] and round to 2dp. Never return 0 or 1 exactly."""
    return round(max(lo, min(hi, value)), 2)


def _describe_rainfall(mm: float) -> str:
    if mm < 40:   return "very dry / drought conditions"
    if mm < 100:  return "below average rainfall"
    if mm < 180:  return "average rainfall"
    if mm < 260:  return "above average rainfall"
    return "high rainfall / wet period"


def _job_condition_note(
    job_id: str,
    score: float,
    weather: WeatherSummary,
    suburb_profile,
) -> str:
    """Returns a specific, actionable note for each job based on its score."""
    severity = "minimal" if score < 0.35 else "moderate" if score < 0.60 else "significant" if score < 0.80 else "heavy"

    notes = {
        "lawn_mowing": (
            f"Lawn: {severity} growth expected — "
            f"{weather.total_rainfall_mm}mm rain + {weather.avg_temp_c}°C avg temp "
            f"{'drives fast growth' if score > 0.55 else 'moderate growth rate'}."
        ),
        "gutter_cleaning": (
            f"Gutters: {severity} debris load — "
            f"{'high tree density + ' if getattr(suburb_profile, 'tree_density', '') == 'high' else ''}"
            f"{weather.rain_days} rain days washes debris into gutters."
        ),
        "roof_cleaning": (
            f"Roof: {severity} moss/lichen growth — "
            f"{'wet conditions accelerate growth' if weather.total_rainfall_mm > 150 else 'average conditions'}."
        ),
        "pressure_washing_driveway": (
            f"Driveway: {severity} soiling — "
            f"{'algae/moss likely from wet period' if weather.total_rainfall_mm > 150 else ''}"
            f"{'dust accumulation from dry spell' if weather.dry_streak_days > 20 else ''}."
        ).rstrip(" —").rstrip(),
        "garden_tidy": (
            f"Garden: {severity} weed/growth — "
            f"warm wet conditions {'drive heavy weed growth' if score > 0.6 else 'produce average growth'}."
        ),
        "hedge_trimming": (
            f"Hedges: {severity} growth — "
            f"{'fast growth in warm weather' if weather.avg_temp_c > 24 else 'moderate growth rate'}."
        ),
    }
    return notes.get(job_id, "")


# ─── Singleton ────────────────────────────────────────────────────────────────
condition_agent = ConditionAgent()
