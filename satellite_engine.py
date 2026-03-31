from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any


_EE_INIT_ATTEMPTED = False
_EE_INIT_FAILED = False
_EE_MODULE = None


def _init_earth_engine() -> Any:
    global _EE_INIT_ATTEMPTED, _EE_INIT_FAILED, _EE_MODULE

    # Keep GEE opt-in so local development does not block on auth/credentials.
    if os.getenv("ENABLE_GEE", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeError("GEE is disabled. Set ENABLE_GEE=true to enable satellite imagery pipeline.")

    if _EE_INIT_FAILED:
        raise RuntimeError("Google Earth Engine initialization failed previously.")

    if _EE_INIT_ATTEMPTED and _EE_MODULE is not None:
        return _EE_MODULE

    try:
        import ee  # type: ignore
    except Exception as exc:
        _EE_INIT_FAILED = True
        raise RuntimeError("earthengine-api is not installed") from exc

    project_id = os.getenv("GEE_PROJECT")
    service_account = os.getenv("GEE_SERVICE_ACCOUNT")
    private_key = os.getenv("GEE_PRIVATE_KEY")

    try:
        if service_account and private_key:
            credentials = ee.ServiceAccountCredentials(
                service_account,
                key_data=private_key.replace("\\n", "\n"),
            )
            ee.Initialize(credentials, project=project_id)
        elif project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()
    except Exception as exc:
        _EE_INIT_FAILED = True
        raise RuntimeError("Failed to initialize Google Earth Engine") from exc

    _EE_INIT_ATTEMPTED = True
    _EE_MODULE = ee
    return ee


def get_gee_satellite_indices(lat: float, lon: float) -> dict[str, float]:
    ee = _init_earth_engine()

    point = ee.Geometry.Point([lon, lat])
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=14)

    s2 = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(point)
        .filterDate(str(start_date), str(end_date))
        .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
    )

    s2_count = int(s2.size().getInfo())
    if s2_count == 0:
        raise RuntimeError("No recent Sentinel-2 imagery available for this location")

    ndvi_image = s2.median().normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndvi_val = ndvi_image.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point.buffer(300),
        scale=10,
        maxPixels=1e8,
    ).get("NDVI")

    smap = (
        ee.ImageCollection("NASA_USDA/HSL/SMAP10KM_soil_moisture")
        .filterBounds(point)
        .filterDate(str(start_date), str(end_date))
        .select("ssm")
        .mean()
    )

    soil_val = smap.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point.buffer(5000),
        scale=10000,
        maxPixels=1e8,
    ).get("ssm")

    ndvi = float(ndvi_val.getInfo()) if ndvi_val is not None else None
    soil = float(soil_val.getInfo()) if soil_val is not None else None

    if ndvi is None or soil is None:
        raise RuntimeError("GEE returned incomplete NDVI/soil moisture values")

    return {
        "NDVI": round(ndvi, 3),
        "Soil_Moisture": round(soil, 3),
    }
