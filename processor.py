import pandas as pd


def generate_risk_alerts(prediction_df: pd.DataFrame,
                         current_weather: pd.DataFrame,
                         satellite_data: dict | None = None):
    """
    Analyze weather predictions + satellite indicators
    to generate farm-level climate risk alerts.

    Parameters
    ----------
    prediction_df : pd.DataFrame
        ML model predictions (future climate)
    current_weather : pd.DataFrame
        Real-time weather data
    satellite_data : dict
        Satellite indicators (optional)

    Returns
    -------
    list
        List of alert dictionaries
    """

    alerts = []

    if prediction_df.empty or current_weather.empty:
        return alerts

    # -------------------------
    # HEATWAVE DETECTION
    # -------------------------
    max_temp = prediction_df["predicted_temp"].max()

    if max_temp >= 42:
        alerts.append({
            "title": "🔴 Extreme Heatwave Warning",
            "msg": f"Temperature may reach {max_temp:.1f}°C. Severe crop stress likely.",
            "level": "Critical",
            "risk": "Heatwave"
        })

    elif max_temp >= 36:
        alerts.append({
            "title": "🟠 High Temperature Alert",
            "msg": f"High temperatures ({max_temp:.1f}°C) expected. Monitor irrigation.",
            "level": "Warning",
            "risk": "Heat"
        })

    # -------------------------
    # FROST RISK
    # -------------------------
    min_temp = prediction_df["predicted_temp"].min()

    if min_temp <= 3:
        alerts.append({
            "title": "❄️ Frost Risk",
            "msg": f"Temperature could drop to {min_temp:.1f}°C. Crop damage possible.",
            "level": "Critical",
            "risk": "Frost"
        })

    # -------------------------
    # FLOOD / HEAVY RAIN
    # -------------------------
    avg_rain = prediction_df["predicted_precip"].mean()

    if avg_rain > 70:
        alerts.append({
            "title": "🌧 Heavy Rainfall Risk",
            "msg": "High probability of rainfall may cause waterlogging.",
            "level": "Warning",
            "risk": "Flood"
        })

    # -------------------------
    # WIND DAMAGE
    # -------------------------
    avg_wind = current_weather["wind_speed"].mean()

    if avg_wind >= 30:
        alerts.append({
            "title": "💨 Strong Wind Alert",
            "msg": f"Winds averaging {avg_wind:.1f} km/h may damage crops.",
            "level": "Warning",
            "risk": "Wind"
        })

    # -------------------------
    # HUMIDITY DISEASE RISK
    # -------------------------
    avg_humidity = prediction_df["predicted_humidity"].mean()

    if avg_humidity > 85 and max_temp < 30:
        alerts.append({
            "title": "🍄 Crop Disease Risk",
            "msg": "High humidity + warm temperatures favor fungal diseases.",
            "level": "Warning",
            "risk": "Disease"
        })

    # -------------------------
    # SATELLITE SOIL MOISTURE
    # -------------------------
    if satellite_data:

        soil = satellite_data.get("Soil_Moisture")

        try:
            if isinstance(soil, str):
                soil_val = float(soil.replace("%", "").strip())
                # String value is generally percentage (0-100).
                dryness_threshold = 20.0
            else:
                soil_val = float(soil)
                # Numeric value from API is typically ratio (0-1).
                dryness_threshold = 0.20 if soil_val <= 1 else 20.0

            if soil_val < dryness_threshold:
                alerts.append({
                    "title": "🌵 Soil Dryness Detected",
                    "msg": "Satellite indicates low soil moisture.",
                    "level": "Warning",
                    "risk": "Drought"
                })
        except (TypeError, ValueError):
            pass

    return alerts


# --------------------------------------------------


def get_farmer_advice(alerts: list):
    """
    Convert alerts into actionable farm advice.

    Parameters
    ----------
    alerts : list

    Returns
    -------
    str
    """

    if not alerts:
        return "✅ Weather conditions are stable. Continue normal farming operations."

    advice_list = []

    for alert in alerts:

        risk = alert.get("risk")

        if risk == "Heatwave":
            advice_list.append("Increase irrigation and provide shade nets.")

        elif risk == "Heat":
            advice_list.append("Monitor soil moisture and irrigate early morning.")

        elif risk == "Frost":
            advice_list.append("Use crop covers or sprinkler frost protection.")

        elif risk == "Flood":
            advice_list.append("Ensure proper drainage to prevent waterlogging.")

        elif risk == "Wind":
            advice_list.append("Secure irrigation systems and protect tall crops.")

        elif risk == "Disease":
            advice_list.append("Apply preventive organic fungicide spray.")

        elif risk == "Drought":
            advice_list.append("Increase irrigation scheduling and mulch soil.")

    # Remove duplicates
    advice_list = list(set(advice_list))

    final_advice = "📋 **Recommended Actions:**\n\n"

    for tip in advice_list:
        final_advice += f"- {tip}\n"

    return final_advice