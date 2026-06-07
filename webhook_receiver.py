"""
Webhook Receiver - Voyage Concierge (Two-Way Loop)

Lightweight HTTP server that accepts inbound replies from Resend (email)
and Twilio (SMS), then records them into the persona conversation thread.

Architecture:
  - Runs on port 7861 (separate from Gradio's 7860)
  - Uses Python's built-in http.server (no Flask dependency)
  - When Live Send 2-way is enabled, the user runs `ngrok http 7861`
    and pastes the public URL into Resend/Twilio webhook config

Endpoints:
  POST /webhook/email     - Resend inbound email webhook
  POST /webhook/sms       - Twilio inbound SMS webhook (form-encoded)
  GET  /webhook/status    - health check
  POST /webhook/test/<id> - manually inject a fake inbound reply for testing

CRITICAL: this is for DEMO use. Production webhook receivers should:
  - Verify Resend signing secret on inbound payloads
  - Verify Twilio X-Twilio-Signature header
  - Use HTTPS termination
  - Rate-limit and authenticate

This demo version logs receipts but does minimal verification.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from demo_personas import (
    identify_persona_from_email,
    identify_persona_from_sms,
    record_inbound,
    DEMO_PERSONAS,
)


_server_thread = None
_server_instance = None
_server_port = 7861
_receipt_log = []  # In-memory log of received webhooks


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP handler for inbound webhook events."""

    def log_message(self, format, *args):
        # Quiet the noisy default logging
        pass

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _send_json(self, status_code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/webhook/status":
            self._send_json(200, {
                "status": "ok",
                "received_count": len(_receipt_log),
                "personas_configured": list(DEMO_PERSONAS.keys()),
                "endpoints": ["/webhook/email", "/webhook/sms"],
            })
            return

        if path == "/":
            self._send_json(200, {
                "service": "Voyage Concierge webhook receiver",
                "endpoints": ["/webhook/email", "/webhook/sms", "/webhook/status"],
            })
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()
        ct = self.headers.get("Content-Type", "").lower()

        try:
            if path == "/webhook/email":
                self._handle_email(body, ct)
                return

            if path == "/webhook/sms":
                self._handle_sms(body, ct)
                return

            if path.startswith("/webhook/test/"):
                # Manual test injection: POST /webhook/test/priya with body content
                persona_id = path.split("/")[-1]
                self._handle_test_injection(persona_id, body, ct)
                return

            self._send_json(404, {"error": "Unknown endpoint"})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_email(self, body, ct):
        """
        Resend inbound webhook payload structure (simplified):
          {
            "type": "email.delivered" | "email.received" | ...,
            "data": {
              "to": ["[email protected]"],
              "from": "[email protected]",
              "subject": "...",
              "text": "...",
              "html": "..."
            }
          }
        """
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return

        event_type = payload.get("type", "")
        data = payload.get("data", {})

        # We only care about inbound or replied emails; deliveries and bounces are noise
        if event_type and event_type not in ("email.received", "email.replied", "inbound.email"):
            _receipt_log.append({"channel": "email", "event": event_type, "ignored": True})
            self._send_json(200, {"received": True, "action": "ignored", "reason": f"event type {event_type}"})
            return

        # Identify persona from To address
        to_addresses = data.get("to", [])
        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]

        persona = None
        for addr in to_addresses:
            persona = identify_persona_from_email(addr)
            if persona:
                break

        if not persona:
            _receipt_log.append({
                "channel": "email",
                "event": "no_persona_match",
                "to": to_addresses,
                "subject": data.get("subject"),
            })
            self._send_json(200, {"received": True, "action": "no_persona_match"})
            return

        subject = data.get("subject", "(no subject)")
        body_text = data.get("text") or data.get("html") or "(empty body)"

        record_inbound(persona["id"], "email", subject, body_text, payload.get("data", {}).get("email_id"))

        _receipt_log.append({
            "channel": "email",
            "event": "recorded",
            "persona": persona["id"],
            "subject": subject,
        })
        self._send_json(200, {
            "received": True,
            "action": "recorded",
            "persona": persona["first_name"],
            "subject": subject,
        })

    def _handle_sms(self, body, ct):
        """
        Twilio inbound SMS webhook (form-encoded):
          From=+15551234567&To=+15559876543&Body=Hi+thanks&MessageSid=SMxxxx
        """
        if "application/x-www-form-urlencoded" in ct:
            params = parse_qs(body.decode("utf-8"))
            params = {k: v[0] for k, v in params.items()}
        else:
            try:
                params = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(400, {"error": "Could not parse SMS payload"})
                return

        sms_body = params.get("Body", "")
        from_number = params.get("From", "")
        message_sid = params.get("MessageSid", "")

        # Identify persona from SMS body prefix ([PRIYA], [MARCUS], etc.)
        persona = identify_persona_from_sms(sms_body)

        if not persona:
            # No prefix - try the most recent outbound recipient as fallback
            # For simplicity here we record under a "_general" bucket
            _receipt_log.append({
                "channel": "sms",
                "event": "no_persona_match",
                "from": from_number,
                "body": sms_body[:80],
            })
            # Twilio requires TwiML response to acknowledge
            self.send_response(200)
            self.send_header("Content-Type", "application/xml")
            self.end_headers()
            self.wfile.write(b"<?xml version='1.0' encoding='UTF-8'?><Response></Response>")
            return

        record_inbound(persona["id"], "sms", None, sms_body, message_sid)

        _receipt_log.append({
            "channel": "sms",
            "event": "recorded",
            "persona": persona["id"],
            "from": from_number,
            "body": sms_body[:80],
        })

        # Respond to Twilio with empty TwiML
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(b"<?xml version='1.0' encoding='UTF-8'?><Response></Response>")

    def _handle_test_injection(self, persona_id, body, ct):
        """Manual test endpoint - lets you inject fake inbound replies without real webhook setup."""
        persona = DEMO_PERSONAS.get(persona_id)
        if not persona:
            self._send_json(404, {"error": f"Unknown persona: {persona_id}"})
            return

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except json.JSONDecodeError:
            payload = {}

        channel = payload.get("channel", "email")
        subject = payload.get("subject")
        body_text = payload.get("body", "Test inbound reply")

        record_inbound(persona_id, channel, subject, body_text)

        _receipt_log.append({
            "channel": channel,
            "event": "test_injection",
            "persona": persona_id,
            "body": body_text[:80],
        })
        self._send_json(200, {
            "received": True,
            "action": "recorded",
            "persona": persona["first_name"],
            "test_injection": True,
        })


def start_webhook_server(port=7861):
    """Start the webhook server in a background thread."""
    global _server_thread, _server_instance, _server_port

    if _server_thread and _server_thread.is_alive():
        return False, f"Server already running on port {_server_port}"

    _server_port = port

    try:
        _server_instance = HTTPServer(("0.0.0.0", port), WebhookHandler)
    except OSError as e:
        return False, f"Could not bind to port {port}: {e}"

    def serve():
        _server_instance.serve_forever()

    _server_thread = threading.Thread(target=serve, daemon=True)
    _server_thread.start()

    return True, f"Webhook server started on port {port}"


def stop_webhook_server():
    """Stop the webhook server."""
    global _server_instance, _server_thread
    if _server_instance:
        _server_instance.shutdown()
        _server_instance.server_close()
        _server_instance = None
        _server_thread = None
        return True, "Webhook server stopped"
    return False, "Server was not running"


def is_server_running():
    return _server_thread is not None and _server_thread.is_alive()


def get_receipt_log():
    """Return list of recent webhook receipts (newest first)."""
    return list(reversed(_receipt_log[-50:]))


def get_server_port():
    return _server_port
