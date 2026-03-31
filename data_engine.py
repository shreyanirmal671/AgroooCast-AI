import requests
import pandas as pd
import logging
import os
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from satellite_engine import get_gee_satellite_indices
from data_sources.hyperlocal_weather import get_openweathermap_data, get_tomorrowio_data


logger = logging.getLogger(__name__)
_GEE_WARNING_SHOWN = False
_HYPERLOCAL_WARNING_SHOWN: dict[str, bool] = {}


# ==============================
# API ENDPOINTS
# ==============================

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"


def _http_session() -> requests.Session:
    retry = Retry(
        total=3,
        read=3,
        connect=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


# ==============================
# WEATHER DATA (Open-Meteo)
# ==============================

def get_weather_data(lat: float, lon: float) -> pd.DataFrame:
    """
    Fetch real-time hourly weather forecast from Open-Meteo API.
    """

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": [
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation_probability",
            "wind_speed_10m",
            "shortwave_radiation",
        ],
        "timezone": "auto"
    }

    try:
        response = _http_session().get(OPEN_METEO_URL, params=params, timeout=12)
        response.raise_for_status()

        data = response.json()

        hourly = data["hourly"]
        time_values = hourly["time"]
        solar_values = hourly.get("shortwave_radiation")
        if not solar_values or len(solar_values) != len(time_values):
            solar_values = [200.0] * len(time_values)

        df = pd.DataFrame({
            "datetime": time_values,
            "temp": hourly["temperature_2m"],
            "humidity": hourly["relative_humidity_2m"],
            "precip_prob": hourly["precipitation_probability"],
            "wind_speed": hourly["wind_speed_10m"],
            "solar_rad": solar_values,
        })

        df["datetime"] = pd.to_datetime(df["datetime"])

        return df

    except Exception as e:

        logger.warning("Weather API error: %s", e)

        # fallback dataframe (prevents ML crash)
        now = datetime.now()

        df = pd.DataFrame({
            "datetime": [now],
            "temp": [28],
            "humidity": [60],
            "precip_prob": [10],
            "wind_speed": [3],
            "solar_rad": [200],
        })

        return df


def get_hyperlocal_weather(lat: float, lon: float) -> list[dict]:
    """
    Fetch hourly weather forecast for 48 hours using a resilient provider chain:
    Tomorrow.io -> OpenWeatherMap -> Open-Meteo.
    """

    providers = [
        ("tomorrow.io", get_tomorrowio_data),
        ("openweathermap", get_openweathermap_data),
    ]

    provider_required_env = {
        "tomorrow.io": "TOMORROW_IO_API_KEY",
        "openweathermap": "OPENWEATHERMAP_API_KEY",
    }

    for provider_name, provider_fn in providers:
        required_env = provider_required_env.get(provider_name)
        if required_env and not os.getenv(required_env, "").strip():
            if not _HYPERLOCAL_WARNING_SHOWN.get(provider_name):
                logger.info(
                    "Hyperlocal provider %s skipped: set %s to enable.",
                    provider_name,
                    required_env,
                )
                _HYPERLOCAL_WARNING_SHOWN[provider_name] = True
            continue

        try:
            rows = provider_fn(lat, lon)
            if rows:
                return rows[:48]
        except Exception as exc:
            if not _HYPERLOCAL_WARNING_SHOWN.get(provider_name):
                logger.warning("Hyperlocal provider %s unavailable: %s", provider_name, exc)
                _HYPERLOCAL_WARNING_SHOWN[provider_name] = True

    # Final fallback to existing Open-Meteo pipeline with field normalization.
    weather_df = get_weather_data(lat, lon)
    normalized_rows: list[dict] = []
    for row in weather_df.head(48).to_dict(orient="records"):
        normalized_rows.append(
            {
                "temperature": float(row.get("temp", 0.0)),
                "humidity": float(row.get("humidity", 0.0)),
                "wind_speed": float(row.get("wind_speed", 0.0)),
                "precipitation": 0.0,
                "rain_probability": float(row.get("precip_prob", 0.0)),
                "timestamp": pd.to_datetime(row.get("datetime")).isoformat(),
            }
        )

    return normalized_rows


# ==============================
# SATELLITE DATA (NASA POWER)
# ==============================

def get_satellite_indices(lat: float, lon: float) -> dict:
    """
    Fetch satellite-based climate indicators from NASA POWER API.
    """

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=1)

    params = {
        "parameters": "ALLSKY_SFC_SW_DWN,T2M,WS2M",
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
        "format": "JSON"
    }

    try:
        response = _http_session().get(NASA_POWER_URL, params=params, timeout=12)
        response.raise_for_status()
        data = response.json()

        solar_data = data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
        temp_data = data["properties"]["parameter"]["T2M"]

        latest_key = list(solar_data.keys())[-1]
        solar_radiation = round(float(solar_data[latest_key]), 2)
        surface_temp = round(float(temp_data[latest_key]), 2)

    except Exception as e:
        logger.warning("NASA POWER API error: %s", e)
        solar_radiation = 0.0
        surface_temp = 28.0

    global _GEE_WARNING_SHOWN

    try:
        gee_indices = get_gee_satellite_indices(lat, lon)
        ndvi = gee_indices["NDVI"]
        soil_moisture = gee_indices["Soil_Moisture"]
        source = "sentinel2+gee"
        _GEE_WARNING_SHOWN = False

    except Exception as e:
        if not _GEE_WARNING_SHOWN:
            message = str(e)
            if "GEE is disabled" in message:
                logger.info("GEE satellite pipeline disabled: %s", message)
            else:
                logger.warning("GEE satellite pipeline unavailable: %s", message)
            _GEE_WARNING_SHOWN = True
        try:
            # Open-Meteo soil moisture fallback (hourly reanalysis) if available.
            fallback_weather = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "hourly": ["soil_moisture_0_to_1cm", "temperature_2m"],
                    "timezone": "auto",
                },
                timeout=12,
            )
            fallback_weather.raise_for_status()
            wf = fallback_weather.json().get("hourly", {})
            soil_series = wf.get("soil_moisture_0_to_1cm", [])
            temp_series = wf.get("temperature_2m", [])

            soil_moisture = float(soil_series[-1]) if soil_series else 0.25
            latest_temp = float(temp_series[-1]) if temp_series else surface_temp

            # Conservative weather-derived approximation for NDVI when imagery is unavailable.
            ndvi = max(0.1, min(0.9, 0.75 - (latest_temp - 20) * 0.01 + soil_moisture * 0.25))
            source = "open-meteo-fallback"

        except Exception as fallback_error:
            logger.warning("Open-Meteo fallback unavailable: %s", fallback_error)
            soil_moisture = 0.25
            ndvi = 0.5
            source = "safe-default-fallback"

    indices = {
        "Solar_Radiation": solar_radiation,
        "Surface_Temp": surface_temp,
        "Elevation": 520,
        "NDVI": round(float(ndvi), 3),
        "Soil_Moisture": round(float(soil_moisture), 3),
        "Satellite_Source": source,
    }

    return indices


def search_locations(query: str, limit: int = 8) -> list[dict]:
    if not query.strip():
        return []

    response = _http_session().get(
        OPEN_METEO_GEO_URL,
        params={
            "name": query,
            "count": limit,
            "language": "en",
            "format": "json",
        },
        timeout=12,
    )
    response.raise_for_status()

    data = response.json().get("results", [])
    results = []

    for item in data:
        name = item.get("name")
        latitude = item.get("latitude")
        longitude = item.get("longitude")
        country = item.get("country")
        admin1 = item.get("admin1")

        if name is None or latitude is None or longitude is None:
            continue

        label_parts = [str(name)]
        if admin1:
            label_parts.append(str(admin1))
        if country:
            label_parts.append(str(country))

        results.append(
            {
                "label": ", ".join(label_parts),
                "lat": float(latitude),
                "lon": float(longitude),
            }
        )

    return results


# ==============================
# MODEL EVALUATION DATA
# ==============================

def get_mock_historical_data():
    """
    Generates evaluation dataset for ML model comparison graphs.
    """

    import numpy as np

    actual = np.random.uniform(20, 35, 100)
    predicted = actual + np.random.normal(0, 1.2, 100)

    return actual, predicted