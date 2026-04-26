"""
cadastre_agent.py — QLD Digital Cadastral Database (DCDB) boundary fetcher.

Queries the Queensland Government's free ArcGIS REST API to get the exact
legal property boundary polygon for any QLD address.

API: spatial-gis.information.qld.gov.au (free, no key, updated nightly)
  Layer 0: Addresses — point lookup by coordinates → returns lotplan ID
  Layer 4: Cadastral parcels — polygon lookup by lotplan → returns exact boundary

Returns:
  CadastreResult with:
    polygon       — list of (lat, lng) coordinates of property boundary
    area_sqm      — exact legal area in square metres
    lotplan       — lot/plan identifier (e.g. "1RP12345")
    lot_area      — official area from title register
    bbox          — (min_lat, min_lng, max_lat, max_lng) bounding box
"""

import logging
import math
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# QLD Land Parcel Property Framework REST endpoints (free, no key)
BASE_URL = "https://spatial-gis.information.qld.gov.au/arcgis/rest/services/PlanningCadastre/LandParcelPropertyFramework/MapServer"
ADDRESS_LAYER = f"{BASE_URL}/0/query"    # Layer 0: Addresses (point)
PARCEL_LAYER  = f"{BASE_URL}/4/query"   # Layer 4: Cadastral parcels (polygon)


@dataclass
class CadastreResult:
    """Exact property boundary from the QLD cadastre."""
    polygon: list[tuple[float, float]]   # [(lat, lng), ...] in WGS84
    area_sqm: float                       # Computed from polygon geometry
    lot_area_sqm: Optional[float]         # Official area from title (may differ slightly)
    lotplan: str                          # e.g. "1RP12345"
    bbox: tuple[float, float, float, float]  # (min_lat, min_lng, max_lat, max_lng)
    data_source: str = "qld_dcdb"


class CadastreAgent:
    """
    Fetches exact property boundaries from QLD DCDB via free ArcGIS REST API.

    Usage:
        agent = CadastreAgent()
        result = await agent.get_boundary(lat=-27.496, lng=152.982)
        if result:
            print(f"Block area: {result.area_sqm:.0f}m²")
            print(f"Lot/Plan: {result.lotplan}")
    """

    TIMEOUT = 12.0
    # Search radius in metres around the geocoded point to find the parcel
    SEARCH_RADIUS_M = 20

    async def get_boundary(
        self, lat: float, lng: float
    ) -> Optional[CadastreResult]:
        """
        Main entry point. Given coordinates, returns the property boundary.

        Pipeline:
          1. Find address point → get lotplan from Layer 0
          2. Query parcel polygon by lotplan from Layer 4
          3. Compute area from polygon
          4. Return CadastreResult
        """
        try:
            lotplan = await self._find_lotplan(lat, lng)
            if not lotplan:
                logger.warning(f"No lotplan found for ({lat:.5f}, {lng:.5f})")
                return None

            logger.info(f"Cadastre: found lotplan {lotplan} at ({lat:.5f}, {lng:.5f})")

            result = await self._get_parcel_polygon(lotplan)
            if not result:
                logger.warning(f"No parcel polygon found for lotplan {lotplan}")
                return None

            logger.info(
                f"Cadastre: {lotplan} — area={result.area_sqm:.0f}m², "
                f"bbox={result.bbox}"
            )
            return result

        except Exception as e:
            logger.error(f"Cadastre agent error: {e}", exc_info=True)
            return None

    # ── Step 1: Find lotplan from coordinates ─────────────────────────────────

    async def _find_lotplan(self, lat: float, lng: float) -> Optional[str]:
        """
        Query Layer 0 (Addresses) for the address nearest the given coordinates.
        Returns the lotplan identifier string.

        Uses a small spatial envelope (bounding box) around the point.
        """
        # Convert search radius to degree offset (~1 degree lat = 111km)
        offset = self.SEARCH_RADIUS_M / 111000.0

        # ArcGIS expects envelope as: xmin,ymin,xmax,ymax in WGS84
        envelope = f"{lng-offset},{lat-offset},{lng+offset},{lat+offset}"

        params = {
            "geometry":     envelope,
            "geometryType": "esriGeometryEnvelope",
            "inSR":         "4326",     # WGS84 input
            "spatialRel":   "esriSpatialRelIntersects",
            "outFields":    "lot,plan,lotplan",
            "returnGeometry": "false",
            "f":            "json",
            "resultRecordCount": "1",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(ADDRESS_LAYER, params=params)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            # Widen search if nothing found
            return await self._find_lotplan_wide(lat, lng)

        attrs = features[0].get("attributes", {})
        lotplan = attrs.get("lotplan") or f"{attrs.get('lot','')}{attrs.get('plan','')}"
        return lotplan.strip() if lotplan.strip() else None

    async def _find_lotplan_wide(self, lat: float, lng: float) -> Optional[str]:
        """Fallback: query the parcel layer directly by point intersection."""
        # Query Layer 4 directly with the point
        params = {
            "geometry":       f"{lng},{lat}",
            "geometryType":   "esriGeometryPoint",
            "inSR":           "4326",
            "spatialRel":     "esriSpatialRelIntersects",
            "outFields":      "lot,plan,lotplan,lot_area",
            "returnGeometry": "false",
            "f":              "json",
            "resultRecordCount": "1",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(PARCEL_LAYER, params=params)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return None

        attrs = features[0].get("attributes", {})
        lotplan = attrs.get("lotplan") or f"{attrs.get('lot','')}{attrs.get('plan','')}"
        return lotplan.strip() if lotplan.strip() else None

    # ── Step 2: Get parcel polygon from lotplan ────────────────────────────────

    async def _get_parcel_polygon(self, lotplan: str) -> Optional[CadastreResult]:
        """
        Query Layer 4 (Cadastral parcels) by lotplan to get the exact boundary polygon.
        Returns CadastreResult with polygon, area, and bounding box.
        """
        params = {
            "where":          f"lotplan='{lotplan}'",
            "outFields":      "lot,plan,lotplan,lot_area",
            "returnGeometry": "true",
            "outSR":          "4326",   # Return in WGS84
            "f":              "geojson",
        }

        async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
            resp = await client.get(PARCEL_LAYER, params=params)
            resp.raise_for_status()
            data = resp.json()

        features = data.get("features", [])
        if not features:
            return None

        feature = features[0]
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})

        if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
            logger.warning(f"Unexpected geometry type for {lotplan}: {geometry.get('type')}")
            return None

        # Extract polygon coordinates
        if geometry["type"] == "Polygon":
            # GeoJSON polygon: coordinates[0] is outer ring [lng, lat] pairs
            coords_raw = geometry["coordinates"][0]
        else:
            # MultiPolygon: take the largest ring
            coords_raw = max(
                geometry["coordinates"],
                key=lambda poly: len(poly[0])
            )[0]

        # Convert [lng, lat] → (lat, lng) tuples
        polygon = [(c[1], c[0]) for c in coords_raw]

        # Compute area from polygon
        area_sqm = _polygon_area_sqm(polygon)

        # Official area from DCDB (may be in hectares or m² — check magnitude)
        lot_area_raw = props.get("lot_area")
        lot_area_sqm = None
        if lot_area_raw:
            lot_area_sqm = float(lot_area_raw)
            # DCDB stores lot_area in m² but sanity check
            if lot_area_sqm < 10:
                lot_area_sqm = lot_area_sqm * 10000  # convert ha → m²

        # Bounding box
        lats = [p[0] for p in polygon]
        lngs = [p[1] for p in polygon]
        bbox = (min(lats), min(lngs), max(lats), max(lngs))

        lotplan_str = props.get("lotplan") or lotplan

        return CadastreResult(
            polygon=polygon,
            area_sqm=area_sqm,
            lot_area_sqm=lot_area_sqm,
            lotplan=lotplan_str,
            bbox=bbox,
        )


# ─── Geometry helpers ─────────────────────────────────────────────────────────

def _polygon_area_sqm(polygon: list[tuple[float, float]]) -> float:
    """
    Compute polygon area in square metres using the Shoelace formula
    with a local Mercator projection for accuracy.

    Input: list of (lat, lng) tuples in WGS84 degrees.
    """
    if len(polygon) < 3:
        return 0.0

    # Project to local flat coordinates using metres
    # Use the centroid latitude for the cos correction
    centroid_lat = sum(p[0] for p in polygon) / len(polygon)
    cos_lat = math.cos(math.radians(centroid_lat))

    # Degrees to metres conversion
    lat_to_m = 111320.0           # 1 degree latitude ≈ 111,320m
    lng_to_m = 111320.0 * cos_lat # 1 degree longitude varies with latitude

    # Convert to local metres
    points = [
        (lat * lat_to_m, lng * lng_to_m)
        for lat, lng in polygon
    ]

    # Shoelace formula
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]

    return abs(area) / 2.0


def bbox_to_map_params(bbox: tuple[float, float, float, float]) -> dict:
    """
    Convert a cadastral bounding box to Google Maps Static API parameters.
    Returns center coordinates and an appropriate zoom level.

    Used to generate a satellite image that frames the exact property boundary.
    """
    min_lat, min_lng, max_lat, max_lng = bbox

    center_lat = (min_lat + max_lat) / 2
    center_lng = (min_lng + max_lng) / 2

    # Compute span
    lat_span = max_lat - min_lat
    lng_span = max_lng - min_lng
    max_span = max(lat_span, lng_span)

    # Pick zoom level so the full block fits in ~640px
    # Approximate: at zoom Z, 1 degree ≈ 256 * 2^Z / 360 pixels at equator
    # We want max_span degrees to fit in ~500px (with margin)
    # Rearranging: Z = log2((500 / 256) * (360 / max_span))
    if max_span > 0:
        zoom = math.log2((500 / 256) * (360 / max_span))
        zoom = max(16, min(20, int(zoom)))  # clamp to sane range
    else:
        zoom = 19

    return {
        "center_lat": center_lat,
        "center_lng": center_lng,
        "zoom": zoom,
    }


# ─── Singleton ────────────────────────────────────────────────────────────────
cadastre_agent = CadastreAgent()
