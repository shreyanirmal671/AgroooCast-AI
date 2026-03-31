from __future__ import annotations

import base64
import importlib
import os
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request

try:
    gTTS = getattr(importlib.import_module("gtts"), "gTTS", None)
except Exception:  # pragma: no cover - optional dependency
    gTTS = None

try:
    google_genai = importlib.import_module("google.genai")
    GeminiClient = getattr(google_genai, "Client", None)
except Exception:  # pragma: no cover - optional dependency
    google_genai = None
    GeminiClient = None

try:
    OpenAI = getattr(importlib.import_module("openai"), "OpenAI", None)
except Exception:  # pragma: no cover - optional dependency
    OpenAI = None

from backend_database import (
    Farm,
    FarmHistorySnapshot,
    FarmNotificationChannel,
    FarmAlertRule,
    FarmPlot,
    SessionLocal,
    User,
    create_farm_plot,
    create_db_and_tables,
    create_farm,
    create_history_snapshot,
    delete_farm,
    delete_plot,
    get_farm_by_id,
    get_or_create_alert_rule,
    get_or_create_notification_channel,
    get_plot_by_id,
    get_user_by_username,
    list_plots_for_farm,
    list_notification_delivery_logs,
    list_history_for_farm,
    list_farms_for_user,
)
from data_engine import get_hyperlocal_weather, get_satellite_indices, get_weather_data, search_locations
from ml_engine import predict_farm_microclimate
from processor import generate_risk_alerts, get_farmer_advice
from security import (
    create_access_token,
    create_refresh_token,
    get_bearer_token,
    get_current_user,
    require_roles,
)
from task_queue import NotificationTask, enqueue_notification_task, start_notification_worker


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = Flask(
    __name__,
    static_folder=str(FRONTEND_DIR),
    static_url_path="/assets",
    template_folder=str(TEMPLATE_DIR),
)
app.config["JSON_SORT_KEYS"] = False

_openai_client: Any | None = None
_openai_api_key_cached: str | None = None
_gemini_client: Any | None = None
_gemini_api_key_cached: str | None = None


def _get_openai_client() -> Any | None:
    global _openai_client, _openai_api_key_cached
    api_key = os.getenv("OPENAI_API_KEY")
    if OpenAI is None or not api_key:
        return None
    if _openai_client is None or _openai_api_key_cached != api_key:
        _openai_client = OpenAI(api_key=api_key)
        _openai_api_key_cached = api_key
    return _openai_client


def _get_gemini_client() -> Any | None:
    global _gemini_client, _gemini_api_key_cached
    api_key = _get_gemini_api_key()
    if GeminiClient is None or not api_key:
        return None
    if _gemini_client is None or _gemini_api_key_cached != api_key:
        _gemini_client = GeminiClient(api_key=api_key)
        _gemini_api_key_cached = api_key
    return _gemini_client


def _get_gemini_api_key() -> str | None:
    # Accept common environment variable names used by Gemini SDK examples.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GENAI_API_KEY"):
        value = os.getenv(name)
        if value:
            return value
    return None


def _json_error(detail: str, status_code: int):
    return jsonify({"detail": detail}), status_code


def _validate_lat_lon(payload: dict[str, Any]) -> tuple[float, float] | tuple[None, None]:
    try:
        lat = float(payload.get("lat"))
        lon = float(payload.get("lon"))
    except (TypeError, ValueError):
        return None, None

    if lat < -90 or lat > 90 or lon < -180 or lon > 180:
        return None, None
    return lat, lon


def _chatbot_dependencies_error() -> str | None:
    if _get_openai_client() is None:
        return "Whisper dependency is not configured. Install openai and set OPENAI_API_KEY."
    if not os.getenv("OPENAI_API_KEY"):
        return "Missing OPENAI_API_KEY environment variable."
    if _get_gemini_client() is None:
        return "Gemini dependency is not configured. Install google-genai and set GEMINI_API_KEY."
    if not _get_gemini_api_key():
        return "Missing Gemini API key. Set GEMINI_API_KEY (or GOOGLE_API_KEY / GENAI_API_KEY)."
    if gTTS is None:
        return "Text-to-speech dependency is not configured. Install gTTS."
    return None


def _chatbot_voice_dependencies_error() -> str | None:
    if _get_openai_client() is None:
        return "Whisper dependency is not configured. Install openai and set OPENAI_API_KEY."
    if not os.getenv("OPENAI_API_KEY"):
        return "Missing OPENAI_API_KEY environment variable."
    return None


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = [
        "insufficient_quota",
        "resource_exhausted",
        "quota exceeded",
        "exceeded your current quota",
        "error code: 429",
        "status': 'resource_exhausted'",
    ]
    return any(marker in text for marker in markers)


def _is_model_not_found_error(exc: Exception) -> bool:
    text = str(exc).lower()
    markers = [
        "404 not_found",
        "model is not found",
        "is not supported for generatecontent",
    ]
    return any(marker in text for marker in markers)


def _fallback_chatbot_answer(user_text: str) -> str:
    q = str(user_text or "").strip().lower()
    if not q:
        return "For healthy crops, keep soil moisture balanced, control weeds early, and monitor pests every 2 to 3 days."

    if any(word in q for word in ["crop", "farm", "farming", "how to farm", "cultivation"]):
        return "Start with the right seed and soil test, then keep timely irrigation and weed control. Monitor pests weekly and apply fertilizer in split doses, not all at once."
    if any(word in q for word in ["water", "irrigation", "dry", "soil moisture"]):
        return "Irrigate in early morning or evening to reduce water loss. Keep soil covered with mulch and avoid overwatering to prevent root disease."
    if any(word in q for word in ["fertilizer", "manure", "nutrient", "npk"]):
        return "Use soil-test based fertilizer and apply in split doses during crop stages. Add compost or organic manure to improve long-term soil health."
    if any(word in q for word in ["pest", "disease", "fungus", "insect"]):
        return "Inspect leaves and stems frequently and remove infected parts early. Use recommended pesticide only when needed and spray during low-wind hours."
    if any(word in q for word in ["rain", "weather", "temperature", "heat"]):
        return "Check local forecast before spraying or fertilizer application. During high heat, increase irrigation frequency and avoid heavy field work at noon."

    return "Plan weekly farm tasks by checking weather, soil moisture, and crop stage together. Small timely actions in irrigation, nutrition, and pest control prevent bigger losses."


def _generate_chatbot_answer_with_fallback(user_text: str) -> tuple[str, str | None]:
    try:
        return _generate_chatbot_answer(user_text), None
    except Exception as exc:
        fallback = _fallback_chatbot_answer(user_text)
        error_text = str(exc).lower()
        if "gemini client not available" in error_text or "no api key was provided" in error_text:
            return fallback, "Gemini API key is missing in backend runtime environment; set GEMINI_API_KEY (or GOOGLE_API_KEY / GENAI_API_KEY)."
        if _is_model_not_found_error(exc):
            return fallback, "Gemini model is unavailable for this project/key. Using offline guidance response."
        if _is_quota_error(exc):
            return fallback, "AI quota exhausted, using offline guidance response."
        return fallback, "AI service is unavailable, using offline guidance response."


def _build_chat_context_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""

    lines: list[str] = []

    summary = payload.get("summary") or {}
    satellite = payload.get("satellite") or {}
    alerts = payload.get("alerts") or []
    advice = payload.get("advice")

    try:
        max_temp = float(summary.get("max_pred_temp"))
    except (TypeError, ValueError):
        max_temp = None
    try:
        avg_humidity = float(summary.get("avg_humidity"))
    except (TypeError, ValueError):
        avg_humidity = None
    try:
        max_precip = float(summary.get("max_precip"))
    except (TypeError, ValueError):
        max_precip = None

    summary_bits: list[str] = []
    if max_temp is not None:
        summary_bits.append(f"max predicted temp: {max_temp:.1f}C")
    if avg_humidity is not None:
        summary_bits.append(f"avg humidity: {avg_humidity:.0f}%")
    if max_precip is not None:
        summary_bits.append(f"max rain probability: {max_precip:.0f}%")
    if summary_bits:
        lines.append("Summary: " + ", ".join(summary_bits))

    try:
        ndvi = float(satellite.get("NDVI"))
    except (TypeError, ValueError):
        ndvi = None
    try:
        soil = float(satellite.get("Soil_Moisture"))
    except (TypeError, ValueError):
        soil = None
    try:
        surface = float(satellite.get("Surface_Temp"))
    except (TypeError, ValueError):
        surface = None

    satellite_bits: list[str] = []
    if ndvi is not None:
        satellite_bits.append(f"NDVI: {ndvi:.2f}")
    if soil is not None:
        satellite_bits.append(f"Soil moisture index: {soil:.2f}")
    if surface is not None:
        satellite_bits.append(f"Surface temp index: {surface:.2f}")
    if satellite_bits:
        lines.append("Satellite: " + ", ".join(satellite_bits))

    if isinstance(alerts, list):
        alert_lines: list[str] = []
        for item in alerts[:5]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            risk = str(item.get("risk") or "").strip()
            level = str(item.get("level") or "").strip()
            if not title and not risk and not level:
                continue
            label = ", ".join(part for part in [title, risk, level] if part)
            alert_lines.append(f"- {label}")
        if alert_lines:
            lines.append("Alerts:")
            lines.extend(alert_lines)

    if isinstance(advice, str) and advice.strip():
        lines.append("Advice summary: " + advice.strip())

    if not lines:
        return ""
    return "Farm context for today:\n" + "\n".join(lines)


def _generate_chatbot_answer(user_text: str) -> str:
    gemini_client = _get_gemini_client()
    if gemini_client is None:
        raise RuntimeError("Gemini client not available")

    prompt = (
        "You are AgroCast, a helpful agricultural assistant for Indian farmers. "
        f'The farmer said: "{user_text}". '
        "Answer in one or two short, simple sentences. "
        "Use clear, conversational language and avoid technical jargon."
    )
    model_candidates = [
        "gemini-2.5-flash",
        "models/gemini-2.5-flash",
        "gemini-2.0-flash",
        "models/gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "models/gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "models/gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "models/gemini-1.5-flash-8b",
    ]
    last_error: Exception | None = None

    for model_name in model_candidates:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = str(getattr(response, "text", "") or "").strip()
            if text:
                return text
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return "I can help with weather, crops, and farm alerts. Please ask in simple words."


def _tts_audio_base64(text: str, lang: str) -> str | None:
    if gTTS is None:
        return None

    safe_lang = "hi" if str(lang).lower().startswith("hi") else "en"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as temp_audio:
        temp_audio_path = temp_audio.name

    try:
        tts = gTTS(text=text, lang=safe_lang, slow=False)
        tts.save(temp_audio_path)
        with open(temp_audio_path, "rb") as audio_file:
            return base64.b64encode(audio_file.read()).decode("ascii")
    except Exception:
        # Keep chatbot text responses available even when TTS service is unreachable.
        return None
    finally:
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


INDIA_LOCATION_PRESETS = {
    "Madhya Pradesh": [
        {"name": "Indore", "lat": 22.7196, "lon": 75.8577},
        {"name": "Bhopal", "lat": 23.2599, "lon": 77.4126},
    ],
    "Maharashtra": [
        {"name": "Pune", "lat": 18.5204, "lon": 73.8567},
        {"name": "Nashik", "lat": 19.9975, "lon": 73.7898},
    ],
    "Gujarat": [
        {"name": "Ahmedabad", "lat": 23.0225, "lon": 72.5714},
        {"name": "Surat", "lat": 21.1702, "lon": 72.8311},
        {"name": "Rajkot", "lat": 22.3039, "lon": 70.8022},
    ],
    "Uttar Pradesh": [
        {"name": "Lucknow", "lat": 26.8467, "lon": 80.9462},
        {"name": "Kanpur", "lat": 26.4499, "lon": 80.3319},
    ],
    "Punjab": [
        {"name": "Ludhiana", "lat": 30.901, "lon": 75.8573},
        {"name": "Amritsar", "lat": 31.634, "lon": 74.8723},
    ],
    "Rajasthan": [
        {"name": "Jaipur", "lat": 26.9124, "lon": 75.7873},
        {"name": "Kota", "lat": 25.2138, "lon": 75.8648},
    ],
    "Karnataka": [
        {"name": "Bengaluru", "lat": 12.9716, "lon": 77.5946},
        {"name": "Mysuru", "lat": 12.2958, "lon": 76.6394},
    ],
    "Tamil Nadu": [
        {"name": "Coimbatore", "lat": 11.0168, "lon": 76.9558},
        {"name": "Madurai", "lat": 9.9252, "lon": 78.1198},
    ],
    "Bihar": [
        {"name": "Patna", "lat": 25.5941, "lon": 85.1376},
        {"name": "Gaya", "lat": 24.7955, "lon": 85.0002},
    ],
    "West Bengal": [
        {"name": "Kolkata", "lat": 22.5726, "lon": 88.3639},
        {"name": "Siliguri", "lat": 26.7271, "lon": 88.3953},
    ],
}


def _serialize_farm(farm) -> dict[str, Any]:
    return {
        "id": farm.id,
        "name": farm.name,
        "crop_type": farm.crop_type,
        "farm_size_acres": float(farm.farm_size_acres),
        "lat": float(farm.lat),
        "lon": float(farm.lon),
        "created_at": farm.created_at.isoformat(),
    }


def _serialize_history_row(row: FarmHistorySnapshot) -> dict[str, Any]:
    return {
        "captured_at": row.captured_at.isoformat(),
        "max_pred_temp": float(row.max_pred_temp),
        "avg_humidity": float(row.avg_humidity),
        "max_precip": float(row.max_precip),
        "ndvi": float(row.ndvi),
        "soil_moisture": float(row.soil_moisture),
        "surface_temp": float(row.surface_temp),
        "alert_count": int(row.alert_count),
    }


def _serialize_plot(plot: FarmPlot) -> dict[str, Any]:
    return {
        "id": plot.id,
        "farm_id": plot.farm_id,
        "latitude": float(plot.latitude),
        "longitude": float(plot.longitude),
        "plot_name": plot.plot_name,
        "soil_type": plot.soil_type,
        "crop_stage": plot.crop_stage,
        "created_at": plot.created_at.isoformat(),
    }


def _serialize_rule(rule: FarmAlertRule) -> dict[str, Any]:
    return {
        "max_temp_threshold": float(rule.max_temp_threshold),
        "min_ndvi_threshold": float(rule.min_ndvi_threshold),
        "min_soil_moisture_threshold": float(rule.min_soil_moisture_threshold),
        "max_wind_threshold": float(rule.max_wind_threshold),
        "max_precip_threshold": float(rule.max_precip_threshold),
        "is_enabled": bool(rule.is_enabled),
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _serialize_channel(channel: FarmNotificationChannel) -> dict[str, Any]:
    return {
        "whatsapp_enabled": bool(channel.whatsapp_enabled),
        "sms_enabled": bool(channel.sms_enabled),
        "email_enabled": bool(channel.email_enabled),
        "whatsapp_number": channel.whatsapp_number,
        "sms_number": channel.sms_number,
        "email_address": channel.email_address,
        "updated_at": channel.updated_at.isoformat() if channel.updated_at else None,
    }


def _recommended_rule_for_farm(farm: Farm) -> tuple[dict[str, Any], str]:
    # Baseline defaults tuned for mixed-crop Indian farm conditions.
    rule = {
        "max_temp_threshold": 38.0,
        "min_ndvi_threshold": 0.35,
        "min_soil_moisture_threshold": 0.20,
        "max_wind_threshold": 28.0,
        "max_precip_threshold": 75.0,
        "is_enabled": True,
    }

    reasons: list[str] = ["baseline mixed-crop profile"]
    lat = float(getattr(farm, "lat", 0.0) or 0.0)
    crop = str(getattr(farm, "crop_type", "") or "").strip().lower()

    # Climate zone adjustments by latitude.
    if abs(lat) >= 25.0:
        rule["max_temp_threshold"] = 36.5
        rule["max_wind_threshold"] = 24.0
        reasons.append("cooler/wind-sensitive latitude profile")
    elif abs(lat) <= 15.0:
        rule["max_temp_threshold"] = 39.5
        rule["max_precip_threshold"] = 68.0
        reasons.append("warm-humid latitude profile")

    # Crop-specific overrides.
    if "rice" in crop or "paddy" in crop:
        rule["max_temp_threshold"] = min(rule["max_temp_threshold"], 36.0)
        rule["min_ndvi_threshold"] = 0.40
        rule["min_soil_moisture_threshold"] = 0.30
        rule["max_precip_threshold"] = min(rule["max_precip_threshold"], 65.0)
        reasons.append("rice/paddy moisture-sensitive profile")
    elif "wheat" in crop:
        rule["max_temp_threshold"] = min(rule["max_temp_threshold"], 34.5)
        rule["min_ndvi_threshold"] = 0.33
        rule["min_soil_moisture_threshold"] = 0.22
        reasons.append("wheat heat-sensitive profile")
    elif "cotton" in crop:
        rule["max_temp_threshold"] = max(rule["max_temp_threshold"], 39.0)
        rule["min_ndvi_threshold"] = 0.30
        rule["min_soil_moisture_threshold"] = 0.18
        rule["max_wind_threshold"] = min(rule["max_wind_threshold"], 26.0)
        reasons.append("cotton warm-dry profile")
    elif "sugarcane" in crop:
        rule["max_temp_threshold"] = min(rule["max_temp_threshold"], 37.0)
        rule["min_ndvi_threshold"] = 0.38
        rule["min_soil_moisture_threshold"] = 0.28
        reasons.append("sugarcane high-water profile")
    elif "soy" in crop or "soybean" in crop:
        rule["max_temp_threshold"] = min(rule["max_temp_threshold"], 35.5)
        rule["min_ndvi_threshold"] = 0.34
        rule["min_soil_moisture_threshold"] = 0.24
        reasons.append("soybean moderate profile")

    rationale = ", ".join(reasons)
    return rule, rationale


def _build_custom_alerts(
    prediction_df,
    weather_df,
    satellite_data: dict[str, Any],
    rule: FarmAlertRule | None,
    channel: FarmNotificationChannel | None,
) -> list[dict[str, Any]]:
    if not rule or not rule.is_enabled:
        return []

    alerts: list[dict[str, Any]] = []

    max_temp = float(prediction_df["predicted_temp"].max())
    max_precip = float(prediction_df["predicted_precip"].max())
    avg_wind = float(weather_df["wind_speed"].mean()) if "wind_speed" in weather_df.columns else 0.0
    ndvi = float(satellite_data.get("NDVI", 0.0))
    soil = float(satellite_data.get("Soil_Moisture", 0.0))

    if max_temp >= float(rule.max_temp_threshold):
        alerts.append({
            "title": "Custom Heat Alert",
            "msg": f"Predicted temperature {max_temp:.1f}C crossed threshold {rule.max_temp_threshold:.1f}C.",
            "risk": "CustomHeat",
            "level": "Warning",
        })

    if max_precip >= float(rule.max_precip_threshold):
        alerts.append({
            "title": "Custom Rain Alert",
            "msg": f"Rain probability {max_precip:.1f}% crossed threshold {rule.max_precip_threshold:.1f}%.",
            "risk": "CustomRain",
            "level": "Warning",
        })

    if avg_wind >= float(rule.max_wind_threshold):
        alerts.append({
            "title": "Custom Wind Alert",
            "msg": f"Average wind {avg_wind:.1f} km/h crossed threshold {rule.max_wind_threshold:.1f} km/h.",
            "risk": "CustomWind",
            "level": "Warning",
        })

    if ndvi <= float(rule.min_ndvi_threshold):
        alerts.append({
            "title": "Custom NDVI Alert",
            "msg": f"NDVI {ndvi:.2f} is below threshold {rule.min_ndvi_threshold:.2f}.",
            "risk": "CustomNDVI",
            "level": "Warning",
        })

    if soil <= float(rule.min_soil_moisture_threshold):
        alerts.append({
            "title": "Custom Soil Moisture Alert",
            "msg": f"Soil moisture {soil:.2f} is below threshold {rule.min_soil_moisture_threshold:.2f}.",
            "risk": "CustomSoil",
            "level": "Warning",
        })

    channels = []
    if channel:
        if channel.whatsapp_enabled and channel.whatsapp_number:
            channels.append("whatsapp")
        if channel.sms_enabled and channel.sms_number:
            channels.append("sms")
        if channel.email_enabled and channel.email_address:
            channels.append("email")

    for item in alerts:
        item["channels"] = channels

    return alerts


@app.before_request
def startup_once() -> None:
    if not getattr(app, "_db_initialized", False):
        create_db_and_tables()
        setattr(app, "_db_initialized", True)
    if not getattr(app, "_worker_started", False):
        start_notification_worker()
        setattr(app, "_worker_started", True)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/auth/signup")
def signup():
    payload = request.get_json(silent=True) or {}

    name = str(payload.get("name", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()
    role = str(payload.get("role", "farmer")).strip().lower()

    if len(name) < 2 or len(username) < 3 or len(password) < 6:
        return _json_error("Invalid signup payload", 400)

    if role not in {"farmer", "admin"}:
        role = "farmer"

    db = SessionLocal()
    try:
        existing = get_user_by_username(db, username)
        if existing:
            return _json_error("Username already exists", 409)

        from backend_database import create_user

        create_user(db, name, username, password, role=role)
        return jsonify({"message": "Account created successfully"})
    finally:
        db.close()


@app.post("/auth/login")
def login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not username or not password:
        return _json_error("Username and password are required", 400)

    db = SessionLocal()
    try:
        user = get_user_by_username(db, username)
        if not user:
            return _json_error("Invalid credentials", 401)

        from backend_database import verify_user_password

        if not verify_user_password(user, password):
            return _json_error("Invalid credentials", 401)

        token = create_access_token({"sub": user.username, "role": user.role})
        refresh_token = create_refresh_token({"sub": user.username, "role": user.role})

        return jsonify(
            {
                "access_token": token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
                "username": user.username,
                "role": user.role,
            }
        )
    finally:
        db.close()


@app.post("/auth/refresh")
def refresh_access_token():
    token = get_bearer_token(request.headers.get("Authorization", ""))
    if not token:
        return _json_error("Missing refresh token", 401)

    db = SessionLocal()
    try:
        user, error = get_current_user(db, token, expect_refresh=True)
        if error:
            return _json_error(error, 401)

        access_token = create_access_token({"sub": user.username, "role": user.role})
        return jsonify({"access_token": access_token, "token_type": "bearer"})
    finally:
        db.close()


@app.post("/api/chatbot-text")
def chatbot_text():
    payload = request.get_json(silent=True) or {}
    user_text = str(payload.get("message", "")).strip()
    raw_context = payload.get("context")
    context_payload = raw_context if isinstance(raw_context, dict) else None
    context_text = _build_chat_context_text(context_payload)
    effective_text = f"{user_text}\n\n{context_text}" if context_text else user_text
    language = str(payload.get("lang", "en")).strip().lower() or "en"

    if len(user_text) < 2:
        return _json_error("Message is required", 400)

    db = SessionLocal()
    try:
        _, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        reply_text, warning = _generate_chatbot_answer_with_fallback(effective_text)
        audio_base64 = _tts_audio_base64(reply_text, language)
        response_payload = {
            "transcript": user_text,
            "text": reply_text,
            "audio_base64": audio_base64,
            "audio_mime": "audio/mpeg" if audio_base64 else None,
        }
        if warning:
            response_payload["warning"] = warning
        return jsonify(response_payload)
    except Exception as exc:
        if _is_quota_error(exc):
            fallback = _fallback_chatbot_answer(user_text)
            fallback_audio = _tts_audio_base64(fallback, language)
            return jsonify(
                {
                    "transcript": user_text,
                    "text": fallback,
                    "audio_base64": fallback_audio,
                    "audio_mime": "audio/mpeg" if fallback_audio else None,
                    "warning": "AI quota exhausted, using offline guidance response.",
                }
            )
        return _json_error("Chatbot is temporarily unavailable. Please try again shortly.", 503)
    finally:
        db.close()


@app.post("/api/chatbot-voice")
def chatbot_voice():
    if "audio" not in request.files:
        return _json_error("No audio file provided", 400)

    dep_error = _chatbot_voice_dependencies_error()
    if dep_error:
        return _json_error(dep_error, 503)

    language = str(request.form.get("lang", "en")).strip().lower() or "en"
    audio_file = request.files["audio"]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
        audio_file.save(temp_audio.name)
        temp_audio_path = temp_audio.name

    db = SessionLocal()
    try:
        _, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        try:
            with open(temp_audio_path, "rb") as stream:
                openai_client = _get_openai_client()
                if openai_client is None:
                    return _json_error("Whisper dependency is not configured. Install openai and set OPENAI_API_KEY.", 503)
                transcription = openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=stream,
                    prompt="The user is a farmer asking about weather, crops, alerts, or farm advice.",
                )
        except Exception as exc:
            if _is_quota_error(exc):
                return _json_error("Voice transcription quota is exhausted. Please use text chat mode for now.", 429)
            raise

        user_text = str(getattr(transcription, "text", "") or "").strip()
        if not user_text:
            return _json_error("Could not transcribe audio", 400)

        reply_text, warning = _generate_chatbot_answer_with_fallback(user_text)
        audio_base64 = _tts_audio_base64(reply_text, language)

        response_payload = {
            "transcript": user_text,
            "text": reply_text,
            "audio_base64": audio_base64,
            "audio_mime": "audio/mpeg" if audio_base64 else None,
        }
        if warning:
            response_payload["warning"] = warning
        return jsonify(response_payload)
    except Exception as exc:
        if _is_quota_error(exc):
            return _json_error("Voice chatbot quota is exhausted. Please retry shortly or use text chat.", 429)
        return _json_error("Voice chatbot is temporarily unavailable. Please try again shortly.", 503)
    finally:
        db.close()
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


@app.post("/weather")
def weather():
    payload = request.get_json(silent=True) or {}
    lat, lon = _validate_lat_lon(payload)
    if lat is None:
        return _json_error("Invalid latitude/longitude", 400)

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        weather_df = get_weather_data(lat, lon)
        return jsonify(
            {
                "lat": lat,
                "lon": lon,
                "rows": len(weather_df),
                "weather": weather_df.to_dict(orient="records"),
                "username": user.username,
            }
        )
    except Exception as exc:
        return _json_error(f"Weather fetch failed: {exc}", 500)
    finally:
        db.close()


@app.post("/satellite")
def satellite():
    payload = request.get_json(silent=True) or {}
    lat, lon = _validate_lat_lon(payload)
    if lat is None:
        return _json_error("Invalid latitude/longitude", 400)

    db = SessionLocal()
    try:
        _, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        data = get_satellite_indices(lat, lon)
        return jsonify({"lat": lat, "lon": lon, "satellite": data})
    except Exception as exc:
        return _json_error(f"Satellite fetch failed: {exc}", 500)
    finally:
        db.close()


@app.post("/forecast")
def forecast():
    payload = request.get_json(silent=True) or {}
    include_raw_weather = bool(payload.get("include_raw_weather", False))

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm_id = payload.get("farm_id")
        if farm_id is not None:
            try:
                farm_id_int = int(farm_id)
            except (TypeError, ValueError):
                return _json_error("farm_id must be an integer", 400)

            farm = get_farm_by_id(db, farm_id_int)
            if not farm or farm.user_id != user.id:
                return _json_error("Farm not found", 404)
            lat = float(farm.lat)
            lon = float(farm.lon)
        else:
            lat, lon = _validate_lat_lon(payload)
            if lat is None:
                return _json_error("Invalid latitude/longitude", 400)

        weather_df = get_weather_data(lat, lon)
        hyperlocal_weather = get_hyperlocal_weather(lat, lon)
        sat_data = get_satellite_indices(lat, lon)

        prediction_df = predict_farm_microclimate(weather_df, sat_data)
        alerts = generate_risk_alerts(
            prediction_df=prediction_df,
            current_weather=weather_df,
            satellite_data=sat_data,
        )

        rule = None
        channel = None
        if farm_id is not None:
            rule = get_or_create_alert_rule(db, farm_id_int)
            channel = get_or_create_notification_channel(db, farm_id_int)

        custom_alerts = _build_custom_alerts(prediction_df, weather_df, sat_data, rule, channel)
        alerts.extend(custom_alerts)

        notification_delivery = {
            "enabled": False,
            "attempted": 0,
            "sent": 0,
            "channels": [],
            "errors": ["Farm-specific channels are required for dispatch"],
        }

        if farm_id is not None and channel is not None:
            channel_payload = _serialize_channel(channel)
            notification_delivery = {
                "enabled": True,
                "attempted": len([ch for ch in ["whatsapp", "sms", "email"] if channel_payload.get(f"{ch}_enabled")]),
                "sent": 0,
                "channels": [],
                "errors": [],
                "queued": bool(custom_alerts),
            }

            if custom_alerts:
                enqueue_notification_task(
                    NotificationTask(
                        farm_id=farm_id_int,
                        farm_name=farm.name,
                        custom_alerts=custom_alerts,
                        channel_config=channel_payload,
                        retries_left=2,
                    )
                )
            else:
                notification_delivery["errors"] = ["No custom alerts to dispatch"]

        response: dict[str, Any] = {
            "lat": lat,
            "lon": lon,
            "satellite": sat_data,
            "predictions": prediction_df.to_dict(orient="records"),
            "hyperlocal_forecast": [
                {
                    "time": row.get("timestamp"),
                    "temperature": float(row.get("temperature", 0.0)),
                    "humidity": float(row.get("humidity", 0.0)),
                    "rain_probability": float(row.get("rain_probability", 0.0)),
                }
                for row in hyperlocal_weather[:48]
            ],
            "alerts": alerts,
            "custom_alerts": custom_alerts,
            "notification_delivery": notification_delivery,
            "advice": get_farmer_advice(alerts),
            "summary": {
                "max_pred_temp": float(prediction_df["predicted_temp"].max()),
                "avg_humidity": float(prediction_df["predicted_humidity"].mean()),
                "max_precip": float(prediction_df["predicted_precip"].max()),
            },
        }

        if farm_id is not None:
            create_history_snapshot(
                db,
                farm_id=farm_id_int,
                max_pred_temp=response["summary"]["max_pred_temp"],
                avg_humidity=response["summary"]["avg_humidity"],
                max_precip=response["summary"]["max_precip"],
                ndvi=float(sat_data.get("NDVI", 0.0)),
                soil_moisture=float(sat_data.get("Soil_Moisture", 0.0)),
                surface_temp=float(sat_data.get("Surface_Temp", 0.0)),
                alert_count=len(alerts),
            )

        if include_raw_weather:
            response["weather"] = weather_df.to_dict(orient="records")

        return jsonify(response)
    except Exception as exc:
        return _json_error(f"Forecast pipeline failed: {exc}", 500)
    finally:
        db.close()


@app.post("/farms/add_plot")
def add_plot():
    payload = request.get_json(silent=True) or {}

    try:
        farm_id = int(payload.get("farm_id"))
    except (TypeError, ValueError):
        return _json_error("farm_id is required", 400)

    lat, lon = _validate_lat_lon({"lat": payload.get("latitude"), "lon": payload.get("longitude")})
    if lat is None:
        return _json_error("Invalid latitude/longitude", 400)

    plot_name = str(payload.get("plot_name", "")).strip() or "Plot"
    soil_type = str(payload.get("soil_type", "")).strip()
    crop_stage = str(payload.get("crop_stage", "")).strip()

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        plot = create_farm_plot(
            db,
            farm_id=farm.id,
            latitude=lat,
            longitude=lon,
            plot_name=plot_name,
            soil_type=soil_type,
            crop_stage=crop_stage,
        )
        return jsonify({"message": "Plot saved", "plot": _serialize_plot(plot)})
    finally:
        db.close()


@app.get("/farms/<int:farm_id>/plots")
def list_plots(farm_id: int):
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        plots = list_plots_for_farm(db, farm_id=farm_id)
        return jsonify({"count": len(plots), "plots": [_serialize_plot(plot) for plot in plots]})
    finally:
        db.close()


@app.delete("/plots/<int:plot_id>")
def remove_plot(plot_id: int):
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        plot = get_plot_by_id(db, plot_id)
        if not plot:
            return _json_error("Plot not found", 404)

        farm = get_farm_by_id(db, plot.farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Plot not found", 404)

        delete_plot(db, plot)
        return jsonify({"message": "Plot deleted"})
    finally:
        db.close()


@app.get("/admin/users")
def list_users():
    db = SessionLocal()
    try:
        user, error = require_roles(db, get_bearer_token(request.headers.get("Authorization", "")), {"admin"})
        if error:
            return _json_error(error, 403 if "permissions" in error.lower() else 401)

        users = db.query(User).all()
        return jsonify(
            {
                "count": len(users),
                "users": [{"username": u.username, "role": u.role, "name": u.name} for u in users],
            }
        )
    finally:
        db.close()


@app.patch("/admin/users/<string:username>/role")
def update_user_role(username: str):
    payload = request.get_json(silent=True) or {}
    role = str(payload.get("role", "")).strip().lower()
    if role not in {"farmer", "admin"}:
        return _json_error("Role must be farmer or admin", 400)

    db = SessionLocal()
    try:
        _, error = require_roles(db, get_bearer_token(request.headers.get("Authorization", "")), {"admin"})
        if error:
            return _json_error(error, 403 if "permissions" in error.lower() else 401)

        user = get_user_by_username(db, username)
        if not user:
            return _json_error("User not found", 404)

        user.role = role
        db.commit()
        return jsonify({"message": f"Updated {username} role to {role}"})
    finally:
        db.close()


@app.get("/locations/search")
def locations_search():
    query = str(request.args.get("q", "")).strip()
    if len(query) < 2:
        return jsonify({"query": query, "results": []})

    try:
        return jsonify({"query": query, "results": search_locations(query)})
    except Exception as exc:
        return _json_error(f"Location search failed: {exc}", 500)


@app.get("/locations/presets")
def location_presets():
    return jsonify({"states": INDIA_LOCATION_PRESETS})


@app.get("/farms")
def farms_list():
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farms = list_farms_for_user(db, user.id)
        return jsonify({"count": len(farms), "farms": [_serialize_farm(f) for f in farms]})
    finally:
        db.close()


@app.post("/farms")
def farms_create():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    crop_type = str(payload.get("crop_type", "Mixed")).strip() or "Mixed"
    try:
        farm_size = float(payload.get("farm_size_acres", 1.0))
    except (TypeError, ValueError):
        return _json_error("farm_size_acres must be a number", 400)

    lat, lon = _validate_lat_lon(payload)
    if lat is None:
        return _json_error("Invalid latitude/longitude", 400)

    if len(name) < 2:
        return _json_error("Farm name is required", 400)

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = create_farm(
            db,
            user_id=user.id,
            name=name,
            crop_type=crop_type,
            farm_size_acres=max(farm_size, 0.1),
            lat=lat,
            lon=lon,
        )
        return jsonify({"message": "Farm created", "farm": _serialize_farm(farm)})
    finally:
        db.close()


@app.put("/farms/<int:farm_id>")
def farms_update(farm_id: int):
    payload = request.get_json(silent=True) or {}

    # Keep existing lat/lon schema and accept latitude/longitude aliases for compatibility.
    lat_candidate = payload.get("lat", payload.get("latitude"))
    lon_candidate = payload.get("lon", payload.get("longitude"))
    lat, lon = _validate_lat_lon({"lat": lat_candidate, "lon": lon_candidate})
    if lat is None:
        return _json_error("Invalid latitude/longitude", 400)

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        if "name" in payload:
            name = str(payload.get("name", "")).strip()
            if len(name) >= 2:
                farm.name = name

        if "crop_type" in payload:
            crop_type = str(payload.get("crop_type", "")).strip()
            if crop_type:
                farm.crop_type = crop_type

        if "farm_size_acres" in payload or "size" in payload:
            raw_size = payload.get("farm_size_acres", payload.get("size"))
            try:
                farm.farm_size_acres = max(float(raw_size), 0.1)
            except (TypeError, ValueError):
                return _json_error("farm_size_acres must be a number", 400)

        farm.lat = lat
        farm.lon = lon

        db.commit()
        db.refresh(farm)
        return jsonify({"message": "Farm updated", "farm": _serialize_farm(farm)})
    finally:
        db.close()


@app.delete("/farms/<int:farm_id>")
def farms_delete(farm_id: int):
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        delete_farm(db, farm)
        return jsonify({"message": "Farm deleted"})
    finally:
        db.close()


@app.get("/farms/<int:farm_id>/history")
def farm_history(farm_id: int):
    limit = int(request.args.get("limit", 60))
    if limit < 1:
        limit = 1
    if limit > 365:
        limit = 365

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        rows = list_history_for_farm(db, farm_id=farm_id, limit=limit)
        rows.reverse()
        return jsonify({
            "farm": _serialize_farm(farm),
            "count": len(rows),
            "history": [_serialize_history_row(row) for row in rows],
        })
    finally:
        db.close()


@app.post("/farms/compare")
def farm_compare():
    payload = request.get_json(silent=True) or {}
    farm_ids = payload.get("farm_ids", [])
    if not isinstance(farm_ids, list) or not farm_ids:
        return _json_error("farm_ids list is required", 400)

    limit = int(payload.get("limit", 30))
    if limit < 1:
        limit = 1
    if limit > 120:
        limit = 120

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        series: list[dict[str, Any]] = []
        for raw_farm_id in farm_ids:
            try:
                farm_id = int(raw_farm_id)
            except (TypeError, ValueError):
                continue

            farm = get_farm_by_id(db, farm_id)
            if not farm or farm.user_id != user.id:
                continue

            rows = list_history_for_farm(db, farm_id=farm_id, limit=limit)
            rows.reverse()
            series.append({
                "farm": _serialize_farm(farm),
                "history": [_serialize_history_row(row) for row in rows],
            })

        return jsonify({"count": len(series), "series": series})
    finally:
        db.close()


@app.get("/farms/<int:farm_id>/settings")
def farm_settings_get(farm_id: int):
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        rule = get_or_create_alert_rule(db, farm_id)
        channel = get_or_create_notification_channel(db, farm_id)

        return jsonify({
            "farm": _serialize_farm(farm),
            "rule": _serialize_rule(rule),
            "channels": _serialize_channel(channel),
        })
    finally:
        db.close()


@app.get("/farms/<int:farm_id>/settings/recommendations")
def farm_settings_recommendations(farm_id: int):
    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        rule, rationale = _recommended_rule_for_farm(farm)
        recommended_channels = {
            "whatsapp_enabled": True,
            "sms_enabled": False,
            "email_enabled": True,
        }

        return jsonify(
            {
                "farm": _serialize_farm(farm),
                "recommended_rule": rule,
                "recommended_channels": recommended_channels,
                "rationale": rationale,
            }
        )
    finally:
        db.close()


@app.put("/farms/<int:farm_id>/settings")
def farm_settings_update(farm_id: int):
    payload = request.get_json(silent=True) or {}
    rule_data = payload.get("rule", {}) or {}
    channels_data = payload.get("channels", {}) or {}

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        rule = get_or_create_alert_rule(db, farm_id)
        channel = get_or_create_notification_channel(db, farm_id)

        if "max_temp_threshold" in rule_data:
            rule.max_temp_threshold = float(rule_data["max_temp_threshold"])
        if "min_ndvi_threshold" in rule_data:
            rule.min_ndvi_threshold = float(rule_data["min_ndvi_threshold"])
        if "min_soil_moisture_threshold" in rule_data:
            rule.min_soil_moisture_threshold = float(rule_data["min_soil_moisture_threshold"])
        if "max_wind_threshold" in rule_data:
            rule.max_wind_threshold = float(rule_data["max_wind_threshold"])
        if "max_precip_threshold" in rule_data:
            rule.max_precip_threshold = float(rule_data["max_precip_threshold"])
        if "is_enabled" in rule_data:
            rule.is_enabled = bool(rule_data["is_enabled"])

        if "whatsapp_enabled" in channels_data:
            channel.whatsapp_enabled = bool(channels_data["whatsapp_enabled"])
        if "sms_enabled" in channels_data:
            channel.sms_enabled = bool(channels_data["sms_enabled"])
        if "email_enabled" in channels_data:
            channel.email_enabled = bool(channels_data["email_enabled"])
        if "whatsapp_number" in channels_data:
            channel.whatsapp_number = str(channels_data["whatsapp_number"] or "").strip()
        if "sms_number" in channels_data:
            channel.sms_number = str(channels_data["sms_number"] or "").strip()
        if "email_address" in channels_data:
            channel.email_address = str(channels_data["email_address"] or "").strip()

        db.commit()
        db.refresh(rule)
        db.refresh(channel)

        return jsonify({
            "message": "Farm settings updated",
            "rule": _serialize_rule(rule),
            "channels": _serialize_channel(channel),
        })
    except (TypeError, ValueError):
        db.rollback()
        return _json_error("Invalid settings payload", 400)
    finally:
        db.close()


@app.post("/farms/<int:farm_id>/alerts/test")
def farm_test_alert(farm_id: int):
    payload = request.get_json(silent=True) or {}
    custom_message = str(payload.get("message", "")).strip()

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        channel = get_or_create_notification_channel(db, farm_id)
        channel_payload = _serialize_channel(channel)

        active_channels = [
            ch
            for ch in ["whatsapp", "sms", "email"]
            if bool(channel_payload.get(f"{ch}_enabled"))
        ]
        if not active_channels:
            return _json_error("Enable at least one notification channel first", 400)

        has_destination = any(
            [
                bool(channel_payload.get("whatsapp_enabled") and str(channel_payload.get("whatsapp_number", "")).strip()),
                bool(channel_payload.get("sms_enabled") and str(channel_payload.get("sms_number", "")).strip()),
                bool(channel_payload.get("email_enabled") and str(channel_payload.get("email_address", "")).strip()),
            ]
        )
        if not has_destination:
            return _json_error("Add contact details for enabled channels before sending a test alert", 400)

        message = custom_message or "This is a test alert from AgroCast. Notification setup is active for your farm."
        enqueue_notification_task(
            NotificationTask(
                farm_id=farm.id,
                farm_name=farm.name,
                custom_alerts=[
                    {
                        "title": "Test Alert",
                        "msg": message,
                        "severity": "moderate",
                        "source": "manual_test",
                    }
                ],
                channel_config=channel_payload,
                retries_left=1,
            )
        )

        return jsonify(
            {
                "message": "Test alert queued",
                "farm": _serialize_farm(farm),
                "active_channels": active_channels,
            }
        )
    finally:
        db.close()


@app.get("/farms/<int:farm_id>/delivery-logs")
def farm_delivery_logs(farm_id: int):
    limit = int(request.args.get("limit", 50))
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    db = SessionLocal()
    try:
        user, error = get_current_user(db, get_bearer_token(request.headers.get("Authorization", "")))
        if error:
            return _json_error(error, 401)

        farm = get_farm_by_id(db, farm_id)
        if not farm or farm.user_id != user.id:
            return _json_error("Farm not found", 404)

        rows = list_notification_delivery_logs(db, farm_id=farm_id, limit=limit)
        return jsonify(
            {
                "farm": _serialize_farm(farm),
                "count": len(rows),
                "logs": [
                    {
                        "id": row.id,
                        "channel": row.channel,
                        "status": row.status,
                        "detail": row.detail,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ],
            }
        )
    finally:
        db.close()


@app.get("/")
def frontend_root():
    return redirect("/login")


@app.get("/login")
def frontend_login():
    return render_template("login.html", page="login")


@app.get("/app/<string:page_name>")
def frontend_app_page(page_name: str):
    allowed_pages = {"dashboard", "forecast", "map", "alerts", "insights", "assistant", "admin"}
    if page_name not in allowed_pages:
        return _json_error("Page not found", 404)

    return render_template(f"app_{page_name}.html", page=page_name)


@app.get("/<path:full_path>")
def frontend_routes(full_path: str):
    reserved_prefixes = ("auth/", "admin/", "weather", "satellite", "forecast", "health", "locations/")
    if full_path.startswith(reserved_prefixes):
        return _json_error("Route not found", 404)
    return redirect("/login")


if __name__ == "__main__":
    create_db_and_tables()
    app.run(host="127.0.0.1", port=8000, debug=True)
