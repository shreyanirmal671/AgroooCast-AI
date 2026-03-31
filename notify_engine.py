from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from typing import Any

import requests


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _safe_phone(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("+"):
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return ""
    if digits.startswith("91"):
        return f"+{digits}"
    return f"+91{digits}"


def _as_whatsapp_address(value: str) -> str:
    value = value.strip()
    if value.startswith("whatsapp:"):
        return value
    return f"whatsapp:{value}"


def _build_alert_message(farm_name: str, alerts: list[dict[str, Any]]) -> str:
    header = f"AgroCast Alert for farm: {farm_name}"
    lines = [header, ""]
    for alert in alerts:
        title = str(alert.get("title", "Alert"))
        msg = str(alert.get("msg", ""))
        lines.append(f"- {title}: {msg}")
    lines.append("")
    lines.append("Please review your farm dashboard for recommended actions.")
    return "\n".join(lines)


def _send_twilio_message(to_addr: str, from_addr: str, body: str) -> tuple[bool, str]:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    if not sid or not token:
        return False, "Missing TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    try:
        response = requests.post(
            url,
            data={"To": to_addr, "From": from_addr, "Body": body},
            auth=(sid, token),
            timeout=12,
        )
        if response.status_code >= 300:
            return False, f"Twilio error {response.status_code}: {response.text[:300]}"
        return True, "sent"
    except Exception as exc:
        return False, str(exc)


def _send_email_message(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", username).strip()
    use_tls = _env_flag("SMTP_USE_TLS", True)

    if not host or not from_addr:
        return False, "Missing SMTP_HOST or SMTP_FROM"

    if not to_addr:
        return False, "Missing recipient email"

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.sendmail(from_addr, [to_addr], msg.as_string())
        return True, "sent"
    except Exception as exc:
        return False, str(exc)


def dispatch_custom_alert_notifications(
    farm_name: str,
    custom_alerts: list[dict[str, Any]],
    channel_config: dict[str, Any],
) -> dict[str, Any]:
    enabled = _env_flag("ENABLE_LIVE_ALERT_DISPATCH", True)
    report: dict[str, Any] = {
        "enabled": enabled,
        "attempted": 0,
        "sent": 0,
        "channels": [],
        "errors": [],
    }

    if not enabled:
        report["errors"].append("Live dispatch disabled by ENABLE_LIVE_ALERT_DISPATCH=false")
        return report

    if not custom_alerts:
        report["errors"].append("No custom alerts to dispatch")
        return report

    body = _build_alert_message(farm_name, custom_alerts)

    if bool(channel_config.get("whatsapp_enabled")) and str(channel_config.get("whatsapp_number", "")).strip():
        report["attempted"] += 1
        to_value = _safe_phone(str(channel_config.get("whatsapp_number", "")))
        from_value = os.getenv("TWILIO_WHATSAPP_FROM", "").strip()
        if not to_value or not from_value:
            report["errors"].append("WhatsApp channel missing TWILIO_WHATSAPP_FROM or valid number")
        else:
            ok, detail = _send_twilio_message(_as_whatsapp_address(to_value), _as_whatsapp_address(from_value), body)
            report["channels"].append({"channel": "whatsapp", "status": "sent" if ok else "failed", "detail": detail})
            if ok:
                report["sent"] += 1
            else:
                report["errors"].append(f"whatsapp: {detail}")

    if bool(channel_config.get("sms_enabled")) and str(channel_config.get("sms_number", "")).strip():
        report["attempted"] += 1
        to_value = _safe_phone(str(channel_config.get("sms_number", "")))
        from_value = os.getenv("TWILIO_SMS_FROM", "").strip()
        if not to_value or not from_value:
            report["errors"].append("SMS channel missing TWILIO_SMS_FROM or valid number")
        else:
            ok, detail = _send_twilio_message(to_value, from_value, body)
            report["channels"].append({"channel": "sms", "status": "sent" if ok else "failed", "detail": detail})
            if ok:
                report["sent"] += 1
            else:
                report["errors"].append(f"sms: {detail}")

    if bool(channel_config.get("email_enabled")) and str(channel_config.get("email_address", "")).strip():
        report["attempted"] += 1
        ok, detail = _send_email_message(str(channel_config.get("email_address", "")).strip(), f"AgroCast Custom Alerts: {farm_name}", body)
        report["channels"].append({"channel": "email", "status": "sent" if ok else "failed", "detail": detail})
        if ok:
            report["sent"] += 1
        else:
            report["errors"].append(f"email: {detail}")

    if report["attempted"] == 0:
        report["errors"].append("No active channels configured for this farm")

    return report
