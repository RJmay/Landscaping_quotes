"""
maps_agent.py — Satellite property analysis agent.

AreaAnalysis fields (all required by quick-quote):
  lawn_sqm, lawn_confidence
  roof_sqm, roof_confidence
  garden_sqm, garden_confidence
  gutter_length_m, gutter_length_confidence   ← linear metres of roof perimeter
  driveway_exposed_sqm, driveway_confidence   ← open-air sealed area (priced)
  driveway_covered_sqm                        ← under overhang (excluded/reduced)
  overhang_detected, overhang_description
  overall_confidence, image_quality, terrain_detected, analysis_notes
  zoom_level, image_size

Without GOOGLE_MAPS_API_KEY: returns fallback Brisbane averages automatically.
"""

import os
import base64
import json
import math
import logging
from dataclasses import dataclass
from typing import Optional

import httpx
import anthropic

logger = logging.getLogger(__name__)


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class Coordinates:
    lat: float
    lng: float
    formatted_address: str


@dataclass
class AreaAnalysis:
    # Core areas
    lawn_sqm: float
    roof_sqm: float
    garden_sqm: float

    # Gutter — linear metres of roof perimeter
    gutter_length_m: float
    gutter_length_confidence: float

    # Driveway split — exposed (priced) vs covered/sheltered
    driveway_exposed_sqm: float
    driveway_covered_sqm: float
    overhang_detected: bool
    overhang_description: str

    # Confidence per measurement
    lawn_confidence: float
    driveway_confidence: float
    roof_confidence: float
    garden_confidence: float

    # Metadata
    overall_confidence: str      # "high" | "medium" | "low"
    image_quality: str           # "clear" | "partial" | "obscured"
    analysis_notes: str
    terrain_detected: str        # "flat" | "sloped" | "unknown"

    # Audit
    zoom_level: int
    image_size: str

    @property
    def driveway_sqm(self) -> float:
        """Total sealed area — exposed + covered."""
        return self.driveway_exposed_sqm + self.driveway_covered_sqm


@dataclass
class AgentResult:
    success: bool
    analysis: Optional[AreaAnalysis] = None
    error: Optional[str] = None
    fallback_used: bool = False


# ─── Agent ────────────────────────────────────────────────────────────────────

class MapsVisionAgent:

    ZOOM_LEVEL = 19
    IMAGE_SIZE = "640x640"
    IMAGE_FORMAT = "png"

    def __init__(self):
        self.google_key = os.environ.get("GOOGLE_MAPS_API_KEY")
        self.claude = anthropic.Anthropic()
        if not self.google_key:
            logger.warning(
                "GOOGLE_MAPS_API_KEY not set — satellite analysis will use fallback estimates."
            )

    async def analyse(self, address: str) -> AgentResult:
        """Full pipeline: geocode → satellite image → Claude vision → measurements."""
        if not self.google_key:
            return AgentResult(
                success=False,
                error="GOOGLE_MAPS_API_KEY not configured",
                fallback_used=True,
                analysis=self._fallback_analysis(),
            )

        try:
            coords = await self._geocode(address)
            if not coords:
                return AgentResult(
                    success=False,
                    error=f"Could not geocode: {address}",
                    fallback_used=True,
                    analysis=self._fallback_analysis(),
                )

            image_bytes = await self._fetch_satellite_image(coords.lat, coords.lng)
            if not image_bytes:
                return AgentResult(
                    success=False,
                    error="Could not fetch satellite image",
                    fallback_used=True,
                    analysis=self._fallback_analysis(),
                )

            analysis = await self._analyse_image(image_bytes, coords, address)
            return AgentResult(success=True, analysis=analysis)

        except Exception as e:
            logger.error(f"Maps Vision agent error for '{address}': {e}", exc_info=True)
            return AgentResult(
                success=False,
                error=str(e),
                fallback_used=True,
                analysis=self._fallback_analysis(),
            )

    # ── Geocoding ─────────────────────────────────────────────────────────────

    async def _geocode(self, address: str) -> Optional[Coordinates]:
        url = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": address,
            "region": "au",
            "components": "country:AU",
            "key": self.google_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "OK" or not data.get("results"):
            logger.warning(f"Geocoding failed for '{address}': {data.get('status')}")
            return None

        result = data["results"][0]
        loc = result["geometry"]["location"]
        return Coordinates(
            lat=loc["lat"],
            lng=loc["lng"],
            formatted_address=result.get("formatted_address", address),
        )

    # ── Satellite image ───────────────────────────────────────────────────────

    async def _fetch_satellite_image(self, lat: float, lng: float) -> Optional[bytes]:
        url = "https://maps.googleapis.com/maps/api/staticmap"
        params = {
            "center": f"{lat},{lng}",
            "zoom": 19,
            "size": "640x640",
            "maptype": "hybrid",           # satellite + road labels
            "markers": f"color:red|{lat},{lng}",  # red pin on the property
            "format": "png",
            "key": self.google_key,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        if resp.status_code != 200 or len(resp.content) < 1000:
            return None
        return resp.content

    # ── Claude vision ─────────────────────────────────────────────────────────

    async def _analyse_image(
        self, image_bytes: bytes, coords: Coordinates, original_address: str
    ) -> AreaAnalysis:
        image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        prompt = self._build_vision_prompt(coords.lat, coords.lng)

        message = self.claude.messages.create(
            model="claude-opus-4-5",
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )

        raw = message.content[0].text
        return self._parse_vision_response(raw)

    def _build_vision_prompt(self, lat: float, lng: float) -> str:
        return f"""You are a property measurement expert analysing a satellite image of a residential property in Australia.

Image specs:
  - Zoom level: {self.ZOOM_LEVEL} (overhead satellite)
  - Coordinates: {lat:.6f}, {lng:.6f} (Australia)
  - Scale: full image covers roughly 40m x 40m real-world area

TARGET: The CENTRAL property in the middle of the image only.

MEASUREMENTS REQUIRED:

1. lawn_sqm — all grass/turf within the property boundary

2. roof_sqm — main dwelling footprint from above (NOT carport/pergola)

3. gutter_length_m — total LINEAR METRES of the roof perimeter (= gutter run)
   Method: trace all outer eave edges and sum. A 12m x 10m house = 2x(12+10) = 44m.
   Typical Brisbane home: 35-65 linear metres.

4. driveway_exposed_sqm — sealed surfaces OPEN TO THE SKY (rain-affected, gets dirty)

5. driveway_covered_sqm — sealed surfaces UNDER a roof structure (carport/porch/verandah)
   Return 0 if none exists.

6. overhang_detected — true if any roof structure covers part of the sealed area

7. overhang_description — one sentence e.g. "Double carport covers ~24m2 of driveway"
   or "No overhang detected."

8. garden_sqm — planted/mulched areas (not lawn, not sealed)

CALIBRATION:
  - Sedan: 4.5m x 1.8m = ~8m2
  - Single carport bay: ~6m x 3m = 18m2
  - Standard driveway width: 3-4m single, 5-6m double
  - Typical brick home width: 10-14m

RULES:
  - Central property only, not neighbours
  - Return 0 for any field not applicable (apartment with no lawn etc.)
  - Partially obscured: estimate and flag low confidence

Respond ONLY with valid JSON, no markdown, no preamble:

{{
  "lawn_sqm": <number>,
  "roof_sqm": <number>,
  "garden_sqm": <number>,
  "gutter_length_m": <number>,
  "gutter_length_confidence": <0.0-1.0>,
  "driveway_exposed_sqm": <number>,
  "driveway_covered_sqm": <number>,
  "overhang_detected": <true|false>,
  "overhang_description": "<string>",
  "lawn_confidence": <0.0-1.0>,
  "driveway_confidence": <0.0-1.0>,
  "roof_confidence": <0.0-1.0>,
  "garden_confidence": <0.0-1.0>,
  "overall_confidence": "high"|"medium"|"low",
  "image_quality": "clear"|"partial"|"obscured",
  "terrain_detected": "flat"|"sloped"|"unknown",
  "analysis_notes": "<2-3 sentences describing what you saw>"
}}"""

    def _parse_vision_response(self, raw: str) -> AreaAnalysis:
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        data = json.loads(clean)

        roof_sqm = float(data.get("roof_sqm", 150))
        # Fallback gutter estimate if model omits it: 4.5 * sqrt(roof area)
        default_gutter = round(4.5 * math.sqrt(max(roof_sqm, 1)), 1)

        return AreaAnalysis(
            lawn_sqm=float(data.get("lawn_sqm", 200)),
            roof_sqm=roof_sqm,
            garden_sqm=float(data.get("garden_sqm", 30)),

            gutter_length_m=float(data.get("gutter_length_m", default_gutter)),
            gutter_length_confidence=float(data.get("gutter_length_confidence", 0.5)),

            driveway_exposed_sqm=float(data.get("driveway_exposed_sqm", 40)),
            driveway_covered_sqm=float(data.get("driveway_covered_sqm", 0)),
            overhang_detected=bool(data.get("overhang_detected", False)),
            overhang_description=str(data.get("overhang_description", "No overhang detected.")),

            lawn_confidence=float(data.get("lawn_confidence", 0.5)),
            driveway_confidence=float(data.get("driveway_confidence", 0.5)),
            roof_confidence=float(data.get("roof_confidence", 0.5)),
            garden_confidence=float(data.get("garden_confidence", 0.5)),

            overall_confidence=data.get("overall_confidence", "medium"),
            image_quality=data.get("image_quality", "partial"),
            analysis_notes=data.get("analysis_notes", ""),
            terrain_detected=data.get("terrain_detected", "unknown"),
            zoom_level=self.ZOOM_LEVEL,
            image_size=self.IMAGE_SIZE,
        )

    def _fallback_analysis(self) -> AreaAnalysis:
        """
        Average Brisbane suburban property estimates.
        Used when Maps API unavailable — prices still work, just wider range.
        """
        return AreaAnalysis(
            lawn_sqm=250.0,
            roof_sqm=155.0,
            garden_sqm=35.0,

            gutter_length_m=50.0,
            gutter_length_confidence=0.2,

            driveway_exposed_sqm=45.0,
            driveway_covered_sqm=0.0,
            overhang_detected=False,
            overhang_description="Satellite analysis unavailable. Overhang not assessed.",

            lawn_confidence=0.2,
            driveway_confidence=0.2,
            roof_confidence=0.2,
            garden_confidence=0.2,

            overall_confidence="low",
            image_quality="obscured",
            analysis_notes=(
                "Satellite analysis unavailable — using average Brisbane suburban estimates. "
                "All measurements should be verified on-site. "
                "Price range is wider to account for measurement uncertainty."
            ),
            terrain_detected="unknown",
            zoom_level=self.ZOOM_LEVEL,
            image_size=self.IMAGE_SIZE,
        )


# ─── Singleton ────────────────────────────────────────────────────────────────
maps_agent = MapsVisionAgent()
