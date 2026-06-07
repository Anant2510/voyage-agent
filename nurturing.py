"""
Nurturing Agent - Voyage Concierge (v3 - Multi-Touch Realism)
=============================================================

Industry-backed multi-touch sequence orchestration.

Key features:
  - Uses templates from sequence_templates.py - one per classification tier
  - Generates LLM content (subject + body + CTA + A/B variant) for top leads
  - Uses structured templates with merge variables for the rest
  - Calculates per-touch predicted performance + cost
  - Tracks compliance: consent verified, suppression checked, frequency capped
  - Handles Path A vs Path B channel constraints
  - Returns sequences with behavioral branching logic visible
"""

import os
import json
import time
from anthropic import Anthropic
from sequence_templates import (
    SEQUENCE_TEMPLATES, CHANNEL_CATALOG,
    get_template, get_channel_meta, get_allowed_channels,
    filter_touches_for_path, predict_touch_performance, calculate_sequence_cost,
)


CLASSIFICATION_CONVERSION = {
    "ready_to_book":      0.20,
    "switching_intent":   0.12,
    "active_research":    0.06,
    "advocacy":           0.04,
    "competitor_mention": 0.03,
    "dreaming":           0.015,
    "venting_only":       0.005,
    "off_topic":          0.001,
}

TIER_MULTIPLIERS = {
    "ready_to_book":      1.45,
    "switching_intent":   1.30,
    "active_research":    1.15,
    "advocacy":           1.10,
    "competitor_mention": 0.95,
    "dreaming":           0.80,
    "venting_only":       0.50,
    "off_topic":          0.40,
}


class NurturingAgent:
    """Multi-touch sequence orchestrator."""

    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-5-20250929"
        self.fallback_model = "claude-haiku-4-5-20251001"

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------
    def generate_sequence(self, lead, use_llm=False):
        analysis = lead.get("analysis", {})
        path = lead.get("path", {})
        classification = analysis.get("classification", "active_research")

        template = get_template(classification)
        if not template:
            return {
                "lead": lead,
                "sequence": self._no_sequence_placeholder(classification),
                "is_llm_generated": False,
            }

        path_key = path.get("path", "B")
        filtered_touches = filter_touches_for_path(template["touches"], path_key)
        merge_vars = self._build_merge_vars(lead)

        if use_llm:
            try:
                touches = self._generate_touches_with_llm(filtered_touches, lead, merge_vars)
                is_llm = True
            except Exception as e:
                print(f"   LLM generation failed: {e}. Falling back to templates.")
                touches = self._generate_touches_from_template(filtered_touches, lead, merge_vars)
                is_llm = False
        else:
            touches = self._generate_touches_from_template(filtered_touches, lead, merge_vars)
            is_llm = False

        # Enrich each touch with prediction + cost + compliance
        tier_mult = TIER_MULTIPLIERS.get(classification, 1.0)
        for t in touches:
            channel_meta = get_channel_meta(t["channel"])
            t["channel_meta"] = channel_meta
            perf = predict_touch_performance(t, channel_meta, classification, tier_mult)
            t["predicted_open"] = round(perf["open_rate"], 3)
            t["predicted_ctr"] = round(perf["ctr"], 3)
            t["cost"] = channel_meta["cost_per_send"]
            t["compliance"] = self._check_compliance(t, lead, channel_meta)

        total_cost, cost_breakdown = calculate_sequence_cost(touches)
        expected_conv = CLASSIFICATION_CONVERSION.get(classification, 0.05)

        sequence = {
            "name": template["name"],
            "description": template["description"],
            "duration_days": template["duration_days"],
            "exit_triggers": template["exit_triggers"],
            "touches": touches,
            "totals": {
                "touch_count": len(touches),
                "cost": round(total_cost, 4),
                "cost_breakdown": {k: round(v, 4) for k, v in cost_breakdown.items()},
                "predicted_conversion": expected_conv,
                "expected_bookings_per_100": round(expected_conv * 100, 1),
            },
            "merge_vars": merge_vars,
        }

        return {
            "lead": lead,
            "sequence": sequence,
            "is_llm_generated": is_llm,
        }

    def generate_bulk(self, leads, top_n_llm=3, progress_callback=None):
        """Generate sequences for many leads. Top-N get LLM-generated content."""
        sorted_leads = sorted(
            enumerate(leads),
            key=lambda x: x[1].get("analysis", {}).get("intent_score", 0),
            reverse=True,
        )
        llm_indices = {idx for idx, _ in sorted_leads[:top_n_llm]}

        results = []
        total = len(leads)
        for i, lead in enumerate(leads):
            use_llm = i in llm_indices
            try:
                result = self.generate_sequence(lead, use_llm=use_llm)
            except Exception as e:
                print(f"   Error on lead {i}: {e}")
                result = {"lead": lead, "sequence": self._no_sequence_placeholder("error"), "is_llm_generated": False}
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, total, lead, result["sequence"])
        return results

    # ----------------------------------------------------------
    # Template-based touch generation (no LLM)
    # ----------------------------------------------------------
    def _generate_touches_from_template(self, template_touches, lead, merge_vars):
        touches = []
        for t in template_touches:
            subject = self._apply_merge(t.get("subject_template"), merge_vars) if t.get("subject_template") else None
            cta = self._apply_merge(t.get("cta_template"), merge_vars) if t.get("cta_template") else None
            body_text = self._template_body_for_touch(t, lead, merge_vars)

            touches.append({
                "id": t["id"],
                "day": t["day"],
                "hour": t["hour"],
                "channel": t["channel"],
                "purpose": t["purpose"],
                "subject": subject,
                "subject_variant_b": self._make_subject_variant(subject, lead) if subject else None,
                "body": body_text,
                "cta": cta,
                "personalization_vars": merge_vars,
                "branching": t.get("branching", {}),
                "is_llm_generated": False,
            })
        return touches

    def _template_body_for_touch(self, touch, lead, merge_vars):
        purpose = touch.get("purpose", "")
        channel = touch.get("channel", "email")
        first_name = merge_vars.get("first_name", "there")
        destination = merge_vars.get("destination", "your destination")
        trip_type = merge_vars.get("trip_type", "trip")

        if channel == "sms":
            return f"Hi {first_name}, your {destination} quote expires in 6 hrs. Tap to lock in: voya.ge/q/{lead['signal']['id'][:8]}"
        if channel == "retargeting":
            return f"Display ad: {destination} imagery + tagline 'Your {trip_type} awaits' + 'Plan with experts' CTA"
        if channel == "ig_reply":
            return f"@{merge_vars.get('user_handle', 'there').lstrip('@')} Love that you're thinking about {destination}! We just helped a guest plan something similar - happy to share insider tips if helpful."
        if channel == "ig_dm":
            return f"Hi {first_name}! Saw your post about {destination} - we'd love to feature it. Mind if we share with credit? Small thank-you gift on us."
        if channel == "lookalike_ad":
            return f"Lookalike ad: positioning {destination} package to anonymous audience matching {first_name}'s profile"

        return (
            f"Hi {first_name},\n\n"
            f"{purpose}.\n\n"
            f"Based on your interest in {destination}, here are some thoughts:\n"
            f"- {trip_type} ideas matching your interests\n"
            f"- Itinerary inspiration\n"
            f"- Talk to a destination specialist\n\n"
            f"Best,\n"
            f"The Voyage Concierge team"
        )

    def _make_subject_variant(self, subject_a, lead):
        if not subject_a:
            return None
        variants = [
            f"Re: {subject_a}",
            subject_a.replace("Your", "About your"),
            f"{subject_a} (action needed)",
            f"Quick question - {subject_a.lower()}",
        ]
        idx = sum(ord(c) for c in lead["signal"]["id"]) % len(variants)
        return variants[idx]

    def _apply_merge(self, template_str, vars_dict):
        if not template_str:
            return template_str
        result = template_str
        for k, v in vars_dict.items():
            result = result.replace("{" + k + "}", str(v))
        return result

    def _build_merge_vars(self, lead):
        signal = lead.get("signal", {})
        analysis = lead.get("analysis", {})
        path = lead.get("path", {})

        first_name = "there"
        if path.get("customer_record"):
            first_name = path["customer_record"].get("first_name", "there")
        else:
            handle = signal.get("user_handle", "").lstrip("u/@").split("_")[0].split(".")[0]
            if handle and len(handle) > 1 and handle[0].isalpha():
                first_name = handle.capitalize()

        destinations = analysis.get("suggested_destinations", [])
        primary_dest = destinations[0] if destinations else "your dream destination"
        alt_dest_1 = destinations[1] if len(destinations) > 1 else "an underrated gem"

        post = signal.get("post_content", "").lower()
        competitor = "your old provider"
        competitors = ["expedia", "booking.com", "airbnb", "delta", "united", "american airlines", "marriott", "hilton"]
        for c in competitors:
            if c in post:
                competitor = c.title()
                break

        return {
            "first_name": first_name,
            "user_handle": signal.get("user_handle", "@there"),
            "destination": primary_dest,
            "destination_alternative_1": alt_dest_1,
            "trip_type": analysis.get("trip_type", "trip"),
            "budget": analysis.get("estimated_budget", "your budget"),
            "competitor": competitor,
            "travel_window": analysis.get("travel_window", "soon"),
        }

    # ----------------------------------------------------------
    # LLM-backed touch generation (for top leads)
    # ----------------------------------------------------------
    def _generate_touches_with_llm(self, template_touches, lead, merge_vars):
        prompt = self._build_touch_generation_prompt(template_touches, lead, merge_vars)
        response = self._call_llm_with_retry(prompt)

        try:
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            llm_touches = json.loads(text)
        except (json.JSONDecodeError, IndexError, AttributeError) as e:
            print(f"   Could not parse LLM touch response: {e}")
            return self._generate_touches_from_template(template_touches, lead, merge_vars)

        touches = []
        for i, template_t in enumerate(template_touches):
            llm_t = llm_touches.get("touches", [])
            llm_content = llm_t[i] if i < len(llm_t) else {}

            touches.append({
                "id": template_t["id"],
                "day": template_t["day"],
                "hour": template_t["hour"],
                "channel": template_t["channel"],
                "purpose": template_t["purpose"],
                "subject": llm_content.get("subject"),
                "subject_variant_b": llm_content.get("subject_variant_b"),
                "body": llm_content.get("body", ""),
                "cta": llm_content.get("cta"),
                "personalization_vars": merge_vars,
                "branching": template_t.get("branching", {}),
                "is_llm_generated": True,
            })
        return touches

    def _build_touch_generation_prompt(self, template_touches, lead, merge_vars):
        signal = lead.get("signal", {})
        analysis = lead.get("analysis", {})
        path = lead.get("path", {})

        lead_summary = f"""LEAD CONTEXT:
- User: {signal.get('user_handle', 'unknown')}
- Original post: "{signal.get('post_content', '')[:400]}..."
- Classification: {analysis.get('classification')}
- Intent score: {analysis.get('intent_score')}/100
- Suggested destinations: {', '.join(analysis.get('suggested_destinations', [])) or 'none stated'}
- Estimated budget: {analysis.get('estimated_budget')}
- Travel window: {analysis.get('travel_window')}
- Path: {path.get('path')} ({path.get('label')})
- Personalization hooks: {'; '.join(analysis.get('personalization_hooks', []))}
"""

        touches_outline = ""
        for t in template_touches:
            ch = t["channel"]
            ch_emoji = CHANNEL_CATALOG.get(ch, {}).get("emoji", "📨")
            touches_outline += f"""
Touch {t['id']} | Day {t['day']} | {ch_emoji} {ch.upper()}
  Purpose: {t['purpose']}
  Body hint: {t.get('body_hint', 'Standard outreach')}
  Subject template (refine this): {t.get('subject_template') or '(none for this channel)'}
  CTA template (refine this): {t.get('cta_template') or '(none for this channel)'}
"""

        return f"""You are a senior travel marketer writing a multi-touch nurture sequence.

{lead_summary}

You need to write content for {len(template_touches)} touches in this sequence:
{touches_outline}

For each touch, write:
  - subject: subject line (under 60 chars, attention-grabbing, personalized) - or null for non-email channels
  - subject_variant_b: alternative subject for A/B testing - or null
  - body: actual message body. For email: 80-150 words, warm but professional. For SMS: under 160 chars. For ig_reply/ig_dm: under 100 words, conversational. For retargeting/lookalike_ad: describe the ad creative in one sentence.
  - cta: call-to-action button/link text (3-7 words)

Use these personalization variables naturally (don't show the curly braces in output):
  first_name: {merge_vars.get('first_name')}
  destination: {merge_vars.get('destination')}
  trip_type: {merge_vars.get('trip_type')}
  competitor: {merge_vars.get('competitor')}

WRITING RULES:
- Don't be salesy. Be helpful, specific, and warm.
- Reference details from their actual post when possible.
- Match the channel's tone (SMS = brief, email = detailed, social = casual).
- For Path B leads (anonymous), don't pretend you know them personally.
- For switching_intent: acknowledge their frustration without trashing the competitor.

Return ONLY this JSON:
{{
  "touches": [
    {{"subject": "...", "subject_variant_b": "...", "body": "...", "cta": "..."}}
  ]
}}

Return one entry per touch in the same order. Return ONLY the JSON. No preamble."""

    def _call_llm_with_retry(self, prompt):
        max_retries = 4
        retry_delay = 2
        models_to_try = [self.model, self.fallback_model]
        response = None
        last_error = None

        for model_idx, model_to_use in enumerate(models_to_try):
            for attempt in range(max_retries):
                try:
                    response = self.client.messages.create(
                        model=model_to_use,
                        max_tokens=3500,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    if model_idx > 0:
                        print(f"   Used fallback model: {model_to_use}")
                    return response
                except Exception as e:
                    last_error = e
                    error_msg = str(e).lower()
                    is_retryable = any(k in error_msg for k in ["overload", "529", "503", "rate"])
                    if attempt < max_retries - 1 and is_retryable:
                        wait = retry_delay * (2 ** attempt)
                        print(f"   {model_to_use} busy, retrying in {wait}s...")
                        time.sleep(wait)
                        continue
                    elif is_retryable and model_idx < len(models_to_try) - 1:
                        break
                    else:
                        raise
        if response is None:
            raise last_error or Exception("All retry attempts failed")
        return response

    # ----------------------------------------------------------
    # Compliance simulation
    # ----------------------------------------------------------
    def _check_compliance(self, touch, lead, channel_meta):
        path = lead.get("path", {})
        path_key = path.get("path", "B")
        consent_required = channel_meta.get("consent_required", True)
        path_b_allowed = channel_meta.get("path_b_allowed", False)

        checks = {}
        if consent_required:
            if path_key == "A":
                checks["consent_verified"] = {
                    "status": "pass",
                    "label": "Consent verified (CDP record)",
                    "detail": "Opt-in recorded on customer profile",
                }
            else:
                checks["consent_verified"] = {
                    "status": "fail",
                    "label": "No consent on file",
                    "detail": "Touch should have been filtered out",
                }
        else:
            checks["consent_verified"] = {
                "status": "pass",
                "label": "Anonymous channel - consent banner sufficient",
                "detail": "Cookie-based, GDPR compliant",
            }

        checks["suppression_list"] = {
            "status": "pass",
            "label": "Not on suppression list",
            "detail": "Real-time API check before send",
        }

        weekly_cap = 4
        used_this_week = touch["id"] - 1
        checks["frequency_cap"] = {
            "status": "pass" if used_this_week < weekly_cap else "warn",
            "label": f"Weekly cap: {used_this_week}/{weekly_cap}",
            "detail": "Prevents message fatigue",
        }

        send_hour = touch.get("hour", 10)
        quiet_violation = send_hour < 8 or send_hour > 21
        checks["quiet_hours"] = {
            "status": "warn" if quiet_violation else "pass",
            "label": f"Sending at {send_hour}:00 local time",
            "detail": "Respects 8 AM - 9 PM quiet hours policy",
        }

        checks["brand_voice"] = {
            "status": "pass",
            "label": "Brand voice approved",
            "detail": "AI content reviewed against brand guidelines",
        }

        if path_key == "B" and not path_b_allowed:
            checks["path_constraint"] = {
                "status": "fail",
                "label": "Channel not allowed for Path B",
                "detail": "Net-new anonymous - no email/SMS/DM allowed",
            }
        else:
            checks["path_constraint"] = {
                "status": "pass",
                "label": f"Channel allowed for Path {path_key}",
                "detail": "Path policy enforced",
            }

        statuses = [v["status"] for v in checks.values()]
        if "fail" in statuses:
            overall = "blocked"
        elif "warn" in statuses:
            overall = "warning"
        else:
            overall = "approved"

        return {"overall": overall, "checks": checks}

    # ----------------------------------------------------------
    # Placeholders for disqualified leads
    # ----------------------------------------------------------
    def _no_sequence_placeholder(self, classification):
        if classification == "venting_only":
            return {
                "name": "No sequence - Disqualified lead",
                "description": "This lead is in the venting_only tier. Outreach is not recommended (could damage brand). Routed to social ops/support team for sentiment monitoring instead of sales.",
                "duration_days": 0,
                "exit_triggers": ["N/A - no sequence"],
                "touches": [],
                "totals": {"touch_count": 0, "cost": 0.0, "cost_breakdown": {}, "predicted_conversion": 0.0, "expected_bookings_per_100": 0.0},
                "merge_vars": {},
            }
        if classification == "off_topic":
            return {
                "name": "No sequence - Off-topic",
                "description": "Scope filter caught noise. No travel intent detected.",
                "duration_days": 0,
                "exit_triggers": ["N/A"],
                "touches": [],
                "totals": {"touch_count": 0, "cost": 0.0, "cost_breakdown": {}, "predicted_conversion": 0.0, "expected_bookings_per_100": 0.0},
                "merge_vars": {},
            }
        return {
            "name": "Sequence unavailable",
            "description": "Could not generate sequence for this lead",
            "duration_days": 0,
            "exit_triggers": [],
            "touches": [],
            "totals": {"touch_count": 0, "cost": 0.0, "cost_breakdown": {}, "predicted_conversion": 0.0, "expected_bookings_per_100": 0.0},
            "merge_vars": {},
        }


# Backwards compatibility shim
def _shim_generate_campaign(self, lead):
    """Legacy entry point - redirects to generate_sequence."""
    return self.generate_sequence(lead, use_llm=False)

NurturingAgent.generate_campaign = _shim_generate_campaign
