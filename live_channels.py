"""
Live Channels - Voyage Concierge

Wrappers for real email/SMS/social sending in demo mode.

CRITICAL SAFETY:
  All messages are routed to DEMO_RECIPIENT_* addresses (the user's own
  test channels), NEVER to the actual prospect. The prospect's contact
  info is shown in the UI for "production would send to" framing only.

Channel adapters:
  - send_email_via_resend()      uses Resend (3000/mo free)
  - send_sms_via_twilio()        uses Twilio trial credit
  - send_to_discord_or_slack()   uses incoming webhook URL

Each adapter:
  - Returns a dict: {"success": bool, "message_id": str, "details": str, "error": str|None, "is_mock": bool}
  - If the API key/credential is missing, falls back to a mock send and marks is_mock=True
  - Never raises - failures return success=False with details

Configuration via env vars (see .env.example):
  RESEND_API_KEY
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
  DISCORD_WEBHOOK_URL or SLACK_WEBHOOK_URL
  DEMO_RECIPIENT_EMAIL, DEMO_RECIPIENT_PHONE
"""

import os
import time
import json
import html as html_mod
from datetime import datetime


def _text_to_html(text):
    """Convert plain text email body to safe HTML."""
    if not text:
        return ""
    escaped = html_mod.escape(text)
    paragraphs = escaped.split("\n\n")
    html_paragraphs = "".join(
        f'<p style="margin:0 0 12px 0; line-height:1.55;">{p.replace(chr(10), "<br>")}</p>'
        for p in paragraphs if p.strip()
    )
    return f'''<!DOCTYPE html>
<html><body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; padding: 24px; color: #0f172a;">
<div style="background:#fef3c7; border:1px solid #f59e0b; border-radius:8px; padding:10px 14px; margin-bottom:18px; font-size:12px; color:#92400e;">
🧪 <strong>DEMO MESSAGE</strong> - this is a test from the Voyage Concierge nurturing pipeline. In production, this would be sent to the actual prospect with proper consent.
</div>
{html_paragraphs}
<hr style="border:none; border-top:1px solid #e2e8f0; margin:24px 0 12px 0;">
<p style="font-size:11px; color:#94a3b8;">Sent by Voyage Concierge - AI-orchestrated travel nurturing</p>
</body></html>'''


# ============================================================
# CONFIG ACCESS
# ============================================================

def get_demo_recipients():
    """Return the configured demo recipient channels."""
    return {
        "email": os.getenv("DEMO_RECIPIENT_EMAIL", "").strip(),
        "phone": os.getenv("DEMO_RECIPIENT_PHONE", "").strip(),
        "discord_webhook": os.getenv("DISCORD_WEBHOOK_URL", "").strip(),
        "slack_webhook": os.getenv("SLACK_WEBHOOK_URL", "").strip(),
    }


def get_channel_status():
    """
    Return which channels are configured (have credentials) vs unconfigured.
    The UI uses this to show 'configured / mock-only' badges.
    """
    recipients = get_demo_recipients()
    return {
        "resend": {
            "configured": bool(os.getenv("RESEND_API_KEY", "").strip()),
            "has_recipient": bool(recipients["email"]),
            "label": "Email (Resend)",
            "recipient": recipients["email"] or "(set DEMO_RECIPIENT_EMAIL)",
            "free_tier": "3,000/mo · 100/day",
        },
        "twilio": {
            "configured": all([
                os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
                os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
                os.getenv("TWILIO_FROM_NUMBER", "").strip(),
            ]),
            "has_recipient": bool(recipients["phone"]),
            "label": "SMS (Twilio)",
            "recipient": recipients["phone"] or "(set DEMO_RECIPIENT_PHONE)",
            "free_tier": "Trial $15 credit ~ 1,500 SMS",
        },
        "discord": {
            "configured": bool(recipients["discord_webhook"]),
            "has_recipient": bool(recipients["discord_webhook"]),
            "label": "Social proxy (Discord)",
            "recipient": "#leads channel" if recipients["discord_webhook"] else "(set DISCORD_WEBHOOK_URL)",
            "free_tier": "Unlimited",
        },
        "slack": {
            "configured": bool(recipients["slack_webhook"]),
            "has_recipient": bool(recipients["slack_webhook"]),
            "label": "Social proxy (Slack)",
            "recipient": "#leads channel" if recipients["slack_webhook"] else "(set SLACK_WEBHOOK_URL)",
            "free_tier": "Unlimited",
        },
    }


# ============================================================
# RESEND - email
# ============================================================

def send_email_via_resend(subject, body, recipient_override=None, prospect_handle=None):
    """
    Send an email via Resend's API.

    Args:
      subject: email subject line
      body: plain-text or basic-HTML body
      recipient_override: optional - override DEMO_RECIPIENT_EMAIL
      prospect_handle: the actual prospect's handle (for activity log framing only,
                       never used as the actual recipient)
    """
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    recipient = (recipient_override or os.getenv("DEMO_RECIPIENT_EMAIL", "")).strip()

    if not api_key:
        return _mock_send("email", subject, body, recipient, "RESEND_API_KEY not set", prospect_handle)
    if not recipient:
        return _mock_send("email", subject, body, "(unset)", "DEMO_RECIPIENT_EMAIL not set", prospect_handle)

    try:
        import resend
        resend.api_key = api_key

        # Convert plain-text newlines to <br> for HTML; keep both for safety
        html_body = _text_to_html(body)

        params = {
            "from": "Voyage Concierge <[email protected]>",
            "to": [recipient],
            "subject": f"[DEMO] {subject}",
            "html": html_body,
            "text": body,
        }
        response = resend.Emails.send(params)
        message_id = response.get("id", "unknown")

        return {
            "success": True,
            "message_id": message_id,
            "details": f"Email sent to {recipient} (would have gone to {prospect_handle or 'prospect'} in production)",
            "error": None,
            "is_mock": False,
            "vendor": "Resend",
            "recipient": recipient,
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        return _mock_send("email", subject, body, recipient, "resend python package not installed (pip install resend)", prospect_handle)
    except Exception as e:
        return {
            "success": False,
            "message_id": None,
            "details": f"Email send failed: {str(e)[:200]}",
            "error": str(e),
            "is_mock": False,
            "vendor": "Resend",
            "recipient": recipient,
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================
# TWILIO - SMS
# ============================================================

def send_sms_via_twilio(body, recipient_override=None, prospect_handle=None):
    """
    Send an SMS via Twilio's API.

    Args:
      body: SMS text (will be truncated to 1600 chars - Twilio's hard cap)
      recipient_override: optional - override DEMO_RECIPIENT_PHONE
      prospect_handle: prospect's handle for activity log framing only
    """
    account_sid = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    from_number = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    recipient = (recipient_override or os.getenv("DEMO_RECIPIENT_PHONE", "")).strip()

    missing = []
    if not account_sid: missing.append("TWILIO_ACCOUNT_SID")
    if not auth_token: missing.append("TWILIO_AUTH_TOKEN")
    if not from_number: missing.append("TWILIO_FROM_NUMBER")
    if not recipient: missing.append("DEMO_RECIPIENT_PHONE")

    if missing:
        return _mock_send("sms", None, body, recipient or "(unset)", f"Missing env vars: {', '.join(missing)}", prospect_handle)

    try:
        from twilio.rest import Client
        client = Client(account_sid, auth_token)

        # Truncate to safe SMS length
        sms_body = f"[DEMO] {body}"
        if len(sms_body) > 1600:
            sms_body = sms_body[:1597] + "..."

        message = client.messages.create(
            body=sms_body,
            from_=from_number,
            to=recipient,
        )

        return {
            "success": True,
            "message_id": message.sid,
            "details": f"SMS sent to {recipient} (would have gone to {prospect_handle or 'prospect'} in production)",
            "error": None,
            "is_mock": False,
            "vendor": "Twilio",
            "recipient": recipient,
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        return _mock_send("sms", None, body, recipient, "twilio python package not installed (pip install twilio)", prospect_handle)
    except Exception as e:
        return {
            "success": False,
            "message_id": None,
            "details": f"SMS send failed: {str(e)[:200]}",
            "error": str(e),
            "is_mock": False,
            "vendor": "Twilio",
            "recipient": recipient,
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================
# DISCORD / SLACK - social proxy via incoming webhook
# ============================================================

def send_to_discord_or_slack(touch_summary, message_body, prospect_handle=None, channel_label=None):
    """
    Post a rich message to a Discord or Slack incoming webhook.
    Prefers Discord if both configured.

    Args:
      touch_summary: short context line ("Touch 1 of Hot lead sequence")
      message_body: the actual content to deliver
      prospect_handle: prospect's handle for framing
      channel_label: friendly name of the original channel (e.g. "Instagram DM")
    """
    discord_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    slack_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    if discord_url:
        return _send_discord_webhook(discord_url, touch_summary, message_body, prospect_handle, channel_label)
    if slack_url:
        return _send_slack_webhook(slack_url, touch_summary, message_body, prospect_handle, channel_label)

    return _mock_send("social", touch_summary, message_body, "(no webhook configured)",
                      "Neither DISCORD_WEBHOOK_URL nor SLACK_WEBHOOK_URL is set", prospect_handle)


def _send_discord_webhook(webhook_url, touch_summary, body, prospect_handle, channel_label):
    """Post to a Discord webhook with a rich embed."""
    try:
        import httpx

        # Discord supports rich embeds
        payload = {
            "username": "Voyage Concierge",
            "avatar_url": "https://i.imgur.com/AfFp7pu.png",
            "embeds": [{
                "title": f"📣 {touch_summary}",
                "description": body[:2000],  # Discord embed description limit
                "color": 0x3b82f6,  # blue
                "fields": [
                    {"name": "Original channel", "value": channel_label or "Unknown", "inline": True},
                    {"name": "Prospect", "value": prospect_handle or "Unknown", "inline": True},
                    {"name": "Mode", "value": "🧪 DEMO - test send", "inline": True},
                ],
                "footer": {"text": f"Voyage Concierge · {datetime.now().strftime('%H:%M:%S')}"}
            }]
        }
        r = httpx.post(webhook_url, json=payload, timeout=10.0)
        r.raise_for_status()

        return {
            "success": True,
            "message_id": f"discord_{int(time.time())}",
            "details": f"Posted to Discord channel (would have gone to {prospect_handle or 'prospect'} on {channel_label or 'social'} in production)",
            "error": None,
            "is_mock": False,
            "vendor": "Discord webhook",
            "recipient": "#leads",
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        return _mock_send("social", touch_summary, body, "Discord channel", "httpx package not installed (pip install httpx)", prospect_handle)
    except Exception as e:
        return {
            "success": False,
            "message_id": None,
            "details": f"Discord post failed: {str(e)[:200]}",
            "error": str(e),
            "is_mock": False,
            "vendor": "Discord webhook",
            "recipient": "#leads",
            "timestamp": datetime.now().isoformat(),
        }


def _send_slack_webhook(webhook_url, touch_summary, body, prospect_handle, channel_label):
    """Post to a Slack incoming webhook with block kit formatting."""
    try:
        import httpx

        payload = {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"📣 {touch_summary[:140]}"}
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Channel:* {channel_label or 'Unknown'}"},
                        {"type": "mrkdwn", "text": f"*Prospect:* `{prospect_handle or 'Unknown'}`"},
                        {"type": "mrkdwn", "text": "*Mode:* 🧪 DEMO - test send"},
                        {"type": "mrkdwn", "text": f"*Time:* {datetime.now().strftime('%H:%M:%S')}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"```{body[:2900]}```"}
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": "Voyage Concierge nurturing pipeline"}]
                }
            ]
        }
        r = httpx.post(webhook_url, json=payload, timeout=10.0)
        r.raise_for_status()

        return {
            "success": True,
            "message_id": f"slack_{int(time.time())}",
            "details": f"Posted to Slack channel (would have gone to {prospect_handle or 'prospect'} on {channel_label or 'social'} in production)",
            "error": None,
            "is_mock": False,
            "vendor": "Slack webhook",
            "recipient": "#leads",
            "timestamp": datetime.now().isoformat(),
        }
    except ImportError:
        return _mock_send("social", touch_summary, body, "Slack channel", "httpx package not installed (pip install httpx)", prospect_handle)
    except Exception as e:
        return {
            "success": False,
            "message_id": None,
            "details": f"Slack post failed: {str(e)[:200]}",
            "error": str(e),
            "is_mock": False,
            "vendor": "Slack webhook",
            "recipient": "#leads",
            "timestamp": datetime.now().isoformat(),
        }


# ============================================================
# MOCK FALLBACK
# ============================================================

def _mock_send(channel_type, subject, body, recipient, reason, prospect_handle=None):
    """
    Used when credentials are missing or a package isn't installed.
    Returns a 'success' response but marks is_mock=True so UI can show a warning.
    """
    return {
        "success": True,
        "message_id": f"mock_{channel_type}_{int(time.time())}",
        "details": f"MOCK SEND (no real {channel_type} fired). Reason: {reason}",
        "error": None,
        "is_mock": True,
        "vendor": f"Mock ({channel_type})",
        "recipient": recipient,
        "timestamp": datetime.now().isoformat(),
    }


# ============================================================
# UNIFIED DISPATCH
# ============================================================

def fire_touch(touch, lead):
    """
    Fire a single touch via the appropriate live channel.

    Routes based on touch["channel"] AND whether the lead matches a demo persona:
      - If lead is a demo persona: route to persona-tagged recipient
        (email gets +tag plus-alias, SMS gets [PERSONA] prefix, social gets persona label)
      - If not a persona: route to default DEMO_RECIPIENT_* env vars

    Returns a result dict with success status + details.
    """
    # Detect demo persona for per-persona routing
    try:
        from demo_personas import (
            is_demo_persona_handle,
            get_persona_email_recipient,
            get_persona_sms_recipient,
            get_persona_sms_prefix,
            get_persona_social_label,
            record_outbound,
        )
        signal = lead.get("signal", {})
        handle = signal.get("user_handle", "")
        # Also check _demo_persona_id from injected simulated posts
        persona_id = signal.get("_demo_persona_id")
        if persona_id:
            from demo_personas import get_persona_by_id
            persona = get_persona_by_id(persona_id)
        else:
            persona = is_demo_persona_handle(handle)
    except ImportError:
        persona = None
        record_outbound = None

    channel = touch.get("channel", "email")
    subject = touch.get("subject") or f"Touch {touch.get('id', '?')} via {channel}"
    body = touch.get("body", "") or "(no body)"
    prospect = lead.get("signal", {}).get("user_handle", "unknown")

    channel_meta = touch.get("channel_meta", {})
    channel_label = channel_meta.get("label", channel)

    # Per-persona recipient routing
    if persona:
        if channel == "email":
            recipient = get_persona_email_recipient(persona)
            tagged_subject = f"[{persona['first_name'].upper()}] {subject}"
            result = send_email_via_resend(tagged_subject, body, recipient_override=recipient, prospect_handle=prospect)
            if record_outbound and result.get("success"):
                record_outbound(persona["id"], "email", subject, body, result.get("message_id"), success=not result.get("is_mock"))
            return result

        if channel == "sms":
            prefix = get_persona_sms_prefix(persona)
            tagged_body = f"{prefix} {body}" if prefix else body
            recipient = get_persona_sms_recipient(persona)
            result = send_sms_via_twilio(tagged_body, recipient_override=recipient, prospect_handle=prospect)
            if record_outbound and result.get("success"):
                record_outbound(persona["id"], "sms", None, body, result.get("message_id"), success=not result.get("is_mock"))
            return result

        # Social proxy channels
        touch_summary = f"[{get_persona_social_label(persona)}] [{channel.upper()}] Touch {touch.get('id', '?')} - {touch.get('purpose', '')[:60]}"
        display_body = body
        if subject:
            display_body = f"Subject: {subject}\n\n{body}"
        result = send_to_discord_or_slack(touch_summary, display_body, prospect, channel_label)
        if record_outbound and result.get("success"):
            record_outbound(persona["id"], "social", subject, body, result.get("message_id"), success=not result.get("is_mock"))
        return result

    # Default routing (no persona match) - original logic
    if channel == "email":
        return send_email_via_resend(subject, body, prospect_handle=prospect)

    if channel == "sms":
        return send_sms_via_twilio(body, prospect_handle=prospect)

    touch_summary = f"[{channel.upper()}] Touch {touch.get('id', '?')} - {touch.get('purpose', '')[:60]}"
    display_body = body
    if subject:
        display_body = f"Subject: {subject}\n\n{body}"
    return send_to_discord_or_slack(touch_summary, display_body, prospect, channel_label)
