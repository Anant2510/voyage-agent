"""
Lead Discovery Agent — Voyage Concierge (FINAL v2)
====================================================

The first stage of the multi-agent pipeline. Listens to a (simulated) social
firehose, filters against a configurable scope, then uses an LLM to classify
intent and score each match.

Three-stage flow per signal:
  1. SCOPE FILTER (rules-based, no LLM)
       Match against configured hashtags, keywords, competitors.
       Reject if exclusion keyword present. Cheap, fast, deterministic.

  2. CLASSIFY + SCORE (LLM call)
       Categorize into one of 7 intent types and assign 0–100 score.
       Returns structured JSON with trip_type, destinations, budget,
       urgency, personalization hooks, recommended first message.

  3. IDENTITY RESOLUTION (rules-based, no LLM)
       Look up social handle in customer DB.
         - Match found    → Path A (full channel mix: email, SMS, DM, ads)
         - No match       → Path B (organic engagement + lookalike only)

Resilience: every LLM call is wrapped in retry-with-exponential-backoff and
falls back automatically to Haiku 4.5 if Sonnet 4.5 is overloaded.

The SOCIAL_SIGNALS list at the bottom is a simulated firehose of 15 posts
designed to exercise all 7 classifications and both paths.
"""

import os
import json
import time
from anthropic import Anthropic
from customer_database import find_customer_by_social_handle, classify_lead_path


# ============================================================
# AGENT CLASS
# ============================================================

class LeadDiscoveryAgent:
    """
    Lead Discovery agent.
    Responsibilities: classify-and-score (LLM) and identity-resolve (DB lookup).
    Scope-filtering is handled by `hashtag_config.signal_matches_config()`
    so this agent only sees signals that have already passed the cheap filter.
    """

    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-5-20250929"  # primary; auto-falls-back to Haiku
        self.fallback_model = "claude-haiku-4-5-20251001"

    # ----------------------------------------------------------
    # Stage 2 — LLM classification + scoring
    # ----------------------------------------------------------
    def classify_and_score(self, signal, scope_name):
        """
        Given a raw social signal (text post + author + engagement metrics) and
        the listening scope name, returns a structured JSON analysis with:
          - classification     (one of 7 categories)
          - classification_reason
          - intent_score       (0–100, calibrated to category)
          - trip_type, suggested_destinations, estimated_budget
          - travel_window, urgency, lead_value_tier
          - personalization_hooks
          - recommended_first_message

        Resilient to API overload via retry+fallback.
        """
        prompt = self._build_classification_prompt(signal, scope_name)

        # ============================================================
        # Retry logic with model fallback for transient API errors
        # ============================================================
        max_retries = 4
        retry_delay = 2  # seconds, doubled each attempt (2, 4, 8, 16)
        models_to_try = [self.model, self.fallback_model]

        response = None
        last_error = None

        for model_idx, model_to_use in enumerate(models_to_try):
            for attempt in range(max_retries):
                try:
                    response = self.client.messages.create(
                        model=model_to_use,
                        max_tokens=1200,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    if model_idx > 0:
                        print(f"   ℹ️  Used fallback model: {model_to_use}")
                    break  # success — exit retry loop

                except Exception as e:
                    last_error = e
                    error_msg = str(e).lower()
                    is_overload = (
                        "overload" in error_msg
                        or "529" in error_msg
                        or "503" in error_msg
                        or "rate" in error_msg
                    )

                    if attempt < max_retries - 1 and is_overload:
                        wait = retry_delay * (2 ** attempt)
                        print(f"   ⏳ {model_to_use} busy, retrying in {wait}s (attempt {attempt + 1}/{max_retries})...")
                        time.sleep(wait)
                        continue
                    elif is_overload and model_idx < len(models_to_try) - 1:
                        print(f"   🔄 {model_to_use} overloaded after {max_retries} attempts. Falling back to {models_to_try[model_idx + 1]}...")
                        break  # try next model
                    else:
                        raise

            if response is not None:
                break

        if response is None:
            raise last_error or Exception("All retry attempts failed")

        # Parse the JSON response defensively
        try:
            text = response.content[0].text.strip()
            # Strip code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            analysis = json.loads(text)
        except (json.JSONDecodeError, IndexError, AttributeError) as e:
            print(f"   ⚠️  Could not parse LLM response as JSON: {e}")
            # Defensive fallback so the UI doesn't crash
            analysis = {
                "classification": "active_research",
                "classification_reason": "Parse error — defaulted to active_research",
                "intent_score": 50,
                "confidence_score": 30,
                "bant_signals": {},
                "trip_type": "Unknown",
                "suggested_destinations": [],
                "estimated_budget": "Unknown",
                "travel_window": "Unknown",
                "urgency": "medium",
                "lead_value_tier": "standard",
                "personalization_hooks": [],
                "recommended_first_message": ""
            }

        # Defensive: ensure all expected keys exist with sensible defaults
        defaults = {
            "classification": "active_research",
            "classification_reason": "",
            "intent_score": 50,
            "confidence_score": 50,
            "bant_signals": {},
            "trip_type": "Travel",
            "suggested_destinations": [],
            "estimated_budget": "Unknown",
            "travel_window": "Flexible",
            "urgency": "medium",
            "lead_value_tier": "standard",
            "personalization_hooks": [],
            "recommended_first_message": ""
        }
        for key, fallback_value in defaults.items():
            if key not in analysis or analysis[key] is None:
                analysis[key] = fallback_value

        # Ensure bant_signals has all expected keys with False defaults
        bant_defaults = {
            "destination_specific": False,
            "timeline_concrete": False,
            "budget_stated": False,
            "authority_clear": False,
            "action_language": False,
            "switching_language": False,
            "competitor_named": False,
        }
        if not isinstance(analysis.get("bant_signals"), dict):
            analysis["bant_signals"] = {}
        for k, v in bant_defaults.items():
            if k not in analysis["bant_signals"]:
                analysis["bant_signals"][k] = v

        # Normalize structured fields: model may return {"value": X, "source": Y}
        # OR a flat value (in fallback case). Flatten to legacy shape but preserve
        # source info as `_sources` dict so the UI can show stated vs inferred badges.
        structured_keys = ["trip_type", "suggested_destinations", "estimated_budget", "travel_window"]
        sources = {}
        for key in structured_keys:
            val = analysis[key]
            if isinstance(val, dict) and "value" in val and "source" in val:
                # New structured shape from updated prompt
                analysis[key] = val["value"] if val["value"] is not None else defaults[key]
                sources[key] = val["source"]
            else:
                # Legacy flat shape (or fallback) — assume inferred unless obviously empty
                if val == defaults[key] or val in ("Unknown", "Flexible", "Travel", []):
                    sources[key] = "unknown"
                else:
                    sources[key] = "inferred"
        analysis["_sources"] = sources

        # ----------------------------------------------------------
        # QUALITY GATE ENFORCEMENT
        # Post-LLM validation: even if model is confident, enforce that
        # tier claims must be backed by actual signals. This prevents
        # score inflation and false-positive Hot leads.
        # ----------------------------------------------------------
        analysis = self._enforce_quality_gates(analysis)

        return analysis

    # ----------------------------------------------------------
    # Quality gate enforcement (Python-side validation)
    # ----------------------------------------------------------
    def _enforce_quality_gates(self, analysis):
        """
        Apply BANT-style quality gates to the LLM's classification.
        Downgrade tier/score if the required signals aren't actually present.
        Add transparency notes about adjustments.
        """
        bant = analysis.get("bant_signals", {})
        cls = analysis.get("classification", "active_research")
        score = analysis.get("intent_score", 50)
        adjustments = []

        # Count concrete BANT signals present
        bant_count = sum([
            bant.get("destination_specific", False),
            bant.get("timeline_concrete", False),
            bant.get("budget_stated", False),
        ])

        original_cls = cls
        original_score = score

        # Gate 1: ready_to_book requires destination + (timeline OR action)
        if cls == "ready_to_book":
            has_dest = bant.get("destination_specific", False)
            has_time_or_action = bant.get("timeline_concrete", False) or bant.get("action_language", False)
            if not (has_dest and has_time_or_action):
                cls = "active_research"
                score = min(score, 65)
                adjustments.append("Downgraded from ready_to_book → active_research: missing destination + timeline/action signals required for Hot tier")

        # Gate 2: switching_intent requires complaint + (switching language OR competitor mention + alternatives discussion)
        if cls == "switching_intent":
            has_switching = bant.get("switching_language", False) or bant.get("competitor_named", False)
            if not has_switching:
                # Downgrade to venting_only — they're upset but not switching
                cls = "venting_only"
                score = min(score, 20)
                adjustments.append("Downgraded from switching_intent → venting_only: complaint detected but no switching/alternatives language - not a sales lead")

        # Gate 3: Score >85 requires ≥3 BANT signals
        if score > 85 and bant_count < 3:
            score = 85
            adjustments.append(f"Score capped at 85: only {bant_count} concrete BANT signals (need ≥3 for >85)")

        # Gate 4: Score >70 requires ≥2 BANT signals
        if score > 70 and bant_count < 2:
            score = 70
            adjustments.append(f"Score capped at 70: only {bant_count} concrete BANT signals (need ≥2 for >70)")

        # Gate 5: Score >55 requires ≥1 BANT signal
        if score > 55 and bant_count < 1:
            score = 50
            adjustments.append(f"Score capped at 50: no concrete BANT signals (destination, timeline, or budget)")

        # Gate 6: venting_only and off_topic — clear out any sales recommendation
        if cls in ("venting_only", "off_topic"):
            if analysis.get("recommended_first_message"):
                adjustments.append("Cleared sales outreach recommendation (disqualified lead - belongs to support/social ops, not sales)")
            analysis["recommended_first_message"] = ""

        # Apply changes
        analysis["classification"] = cls
        analysis["intent_score"] = int(max(0, min(100, score)))
        analysis["_quality_gates"] = {
            "bant_signal_count": bant_count,
            "adjustments_made": adjustments,
            "original_classification": original_cls if original_cls != cls else None,
            "original_score": original_score if original_score != score else None,
        }

        return analysis

    # ----------------------------------------------------------
    # Stage 3 — identity resolution (rules-based lookup)
    # ----------------------------------------------------------
    def resolve_identity(self, signal):
        """
        Look up the social handle in the customer database.
        Returns a path object with:
          - path                  ("A" or "B")
          - label                 (display name)
          - description           (one-line explanation)
          - lawful_basis          (consent / legitimate interest / aggregated)
          - channels_available    (list of {label, available, rationale})
          - customer_record       (if Path A, the full customer dict)
        """
        handle = signal.get("user_handle", "")
        platform = signal.get("platform", "instagram").lower()

        customer = find_customer_by_social_handle(platform, handle)
        return classify_lead_path(customer)

    # ----------------------------------------------------------
    # Prompt construction
    # ----------------------------------------------------------
    def _build_classification_prompt(self, signal, scope_name):
        return f"""You are a lead qualification agent for a travel company. Use BANT-style criteria
(Budget, Authority, Need, Timeline) adapted for travel to qualify this social media signal.

CRITICAL PRINCIPLE: Be conservative. False positives (over-qualifying) waste sales time
and damage brand trust. When in doubt, downgrade the tier.

LISTENING SCOPE: {scope_name}
This scope determines what's considered a relevant travel signal in this context.

SIGNAL TO ANALYZE:
- Platform: {signal.get('platform', 'unknown')}
- User: {signal.get('user_handle', 'unknown')}
- User profile: {signal.get('user_profile', 'unknown')}
- Posted: {signal.get('post_time', 'unknown')}
- Engagement: {signal.get('engagement', 'unknown')}
- Post content: "{signal.get('post_content', '')}"

============================================================
STEP 1 — Detect BANT-Equivalent Signals
============================================================

For each signal below, detect whether the user EXPLICITLY mentioned it in their post.
Be strict — only mark a signal as detected if the user actually wrote it.

  destination_specific:  Did they name a specific place (city/region/country)?
                         YES: "thinking about Banff" / "Japan in October" / "Maldives or Bali"
                         NO:  "want to travel somewhere warm" / "need a vacation"

  timeline_concrete:     Did they mention concrete dates or a near timeframe (<6 months)?
                         YES: "next month" / "October 2026" / "in 3 weeks" / "before Christmas"
                         NO:  "someday" / "eventually" / "this year maybe"

  budget_stated:         Did they mention a budget amount (any currency, any range)?
                         YES: "$5K to spend" / "around 3000" / "under £2000"
                         NO:  No money figure mentioned

  authority_clear:       Are they the decision-maker (solo/independent) OR have they
                         already gotten alignment ("we decided", "wife and I")?
                         YES: solo language, "I'm planning", "we already decided"
                         NO:  "asking my partner", "need to convince husband", "if mom says yes"
                         UNCLEAR: not addressed in the post

  action_language:       Are they using booking-intent verbs?
                         YES: "looking to book", "ready to buy", "where do I book"
                         NO:  Just discussing or dreaming

  switching_language:    For complaints: are they explicitly considering alternatives?
                         YES: "looking at other airlines", "done with X, suggestions?", "switching to..."
                         NO:  Just venting frustration with no forward action

  competitor_named:      Did they explicitly mention a competitor brand?
                         (Expedia, Booking.com, Marriott, Delta, etc.)

============================================================
STEP 2 — Classify into ONE of these 8 categories
============================================================

🔥 HOT TIER (Ready to convert — 8-25% conversion rate)
  ready_to_book        Requires: destination_specific=true
                       AND (timeline_concrete=true OR action_language=true)
                       AND ideally budget_stated=true
                       Examples: "Booking Japan trip next month, budget ~$5K, need recommendations"

  switching_intent     Requires: clear complaint about competitor
                       AND (switching_language=true OR competitor_named=true)
                       AND active comparison/alternatives mention
                       Examples: "Done with Delta after that nightmare flight - what airlines do you recommend?"

🌟 WARM TIER (Genuine planning — 4-8% conversion rate)
  active_research      Requires: destination_specific=true
                       AND (timeline_concrete=true OR budget_stated=true OR specific itinerary questions)
                       Examples: "Planning Iceland for 2 weeks in summer 2026, what's the best route?"

  advocacy             Positive past travel experience worth amplifying (UGC).
                       Not a direct lead but useful for amplification/referral.
                       Examples: "Just got back from amazing Tokyo trip, here's what we did"

💡 COOL TIER (Early interest — 1-3% conversion rate)
  competitor_mention   Mentions competitor without clear intent signal or comparison context.
                       Examples: "Used Expedia last year for my flights"

  dreaming             Aspirational, no concrete details. No destination + no timeline + no budget.
                       Examples: "One day I'd love to go to Greece" / "Manifesting beach vacation"

❌ DISQUALIFIED TIER (Not actionable leads — <1% conversion)
  venting_only         IMPORTANT: Complaint with NO forward action.
                       Just frustration, no switching language, no alternatives mention.
                       Examples: "American Airlines sucks, never flying with them again" (no follow-up plan)
                       "My layover was awful" (just venting)
                       These are NOT leads. They're feedback that may belong to support/social ops,
                       not sales. Sales follow-up here damages brand trust.

  off_topic            Not about travel at all. Caught by scope filter as noise.

============================================================
STEP 3 — Calculate intent_score with STRICT quality gates
============================================================

Base scoring bands (these are CEILINGS, not floors):
  ready_to_book       80-95   (must have ≥2 BANT signals)
  switching_intent    70-85   (must have switching_language + complaint)
  active_research     55-75   (must have ≥1 BANT signal beyond just destination)
  advocacy            45-65
  competitor_mention  35-60
  dreaming            25-45
  venting_only        10-25   (low because it's not a sales lead)
  off_topic           0-15

QUALITY GATES — Even within a category, score is bounded by signals present:
  Score >85 REQUIRES at least 3 BANT signals (destination, timeline, budget, etc.)
  Score >70 REQUIRES at least 2 BANT signals
  Score >55 REQUIRES at least 1 concrete signal (destination OR timeline OR budget)
  Otherwise, cap score at 50 regardless of urgency words

============================================================
STEP 4 — Confidence scoring
============================================================

Assign confidence_score (0-100) based on:
  90-100  Multiple explicit signals, classification is unambiguous
  70-89   Clear signals but some interpretation needed
  50-69   Mixed signals, judgment call between two categories
  30-49   Ambiguous post, classification could go either way
  0-29    Very limited information, low-confidence guess

============================================================
STEP 5 — Return ONLY this JSON object (no preamble, no markdown fences)
============================================================

{{
  "classification": "one of: ready_to_book | switching_intent | active_research | advocacy | competitor_mention | dreaming | venting_only | off_topic",
  "classification_reason": "One-sentence explanation citing specific BANT signals detected",
  "intent_score": <0-100 integer>,
  "confidence_score": <0-100 integer>,
  "bant_signals": {{
    "destination_specific": <true|false>,
    "timeline_concrete":    <true|false>,
    "budget_stated":        <true|false>,
    "authority_clear":      <true|false>,
    "action_language":      <true|false>,
    "switching_language":   <true|false>,
    "competitor_named":     <true|false>
  }},
  "trip_type":              {{"value": "Short descriptor like 'Solo mountain retreat'",      "source": "stated|inferred|unknown"}},
  "suggested_destinations": {{"value": ["destination1", "destination2"],                     "source": "stated|inferred|unknown"}},
  "estimated_budget":       {{"value": "Range like '$3,000-5,000 USD' or null",              "source": "stated|inferred|unknown"}},
  "travel_window":          {{"value": "When they likely want to go, or null",               "source": "stated|inferred|unknown"}},
  "urgency": "low | medium | high",
  "lead_value_tier": "standard | premium | vip",
  "personalization_hooks": ["hook1", "hook2", "hook3"],
  "recommended_first_message": "A short opening line a human agent could send (or empty for disqualified leads)"
}}

REMEMBER:
- For venting_only: NO sales outreach should be recommended. recommended_first_message should be empty.
- Be conservative. A 92-score lead must EARN it with multiple explicit signals.
- The "source" field on trip details should reflect what was actually written vs. inferred.

Return ONLY the JSON object. No other text."""


# ============================================================
# SIMULATED FIREHOSE — 15 signals
# ============================================================
# Designed to:
#   - Exercise all 7 classification categories
#   - Include known customers (Sarah, Marcus, Emma) for Path A demos
#   - Include net-new prospects for Path B demos
#   - Mix relevant and off-topic signals so the scope filter has something to reject
#   - Span destinations, budgets, urgency levels

SOCIAL_SIGNALS = [
    # ---- Path A demo lead (Sarah is in customer DB) ----
    {
        "id": "sig_001",
        "platform": "Instagram",
        "user_handle": "@sarah.wanders",
        "user_profile": "Marketing Director · Austin, TX · Travel enthusiast · 1.2K followers",
        "post_time": "2 hours ago",
        "engagement": "47 likes · 12 comments",
        "post_content": "Q4 broke me. Need to disappear into the mountains for a week. Anyone done Banff or Jackson Hole in the off-season? Want crisp air, no crowds, real silence. Cancun was fun but I need altitude this time. #wanderlust #travelplanning #mountainsareclose"
    },

    # ---- High-intent Path B ready-to-book ----
    {
        "id": "sig_002",
        "platform": "Twitter",
        "user_handle": "@dad_of_three",
        "user_profile": "Software engineer · Seattle · Dad to 3 · Disney annual passholder",
        "post_time": "5 hours ago",
        "engagement": "23 likes · 8 replies",
        "post_content": "Booking Disney World for spring break. We have dates locked (April 8-13), need flights + hotel package. Budget around $6k for the whole family. Best site to book it all in one shot? Got tired of piecing it together myself. #disneyworld #familytravel"
    },

    # ---- Complaint / switching ----
    {
        "id": "sig_003",
        "platform": "Twitter",
        "user_handle": "@fed_up_flyer",
        "user_profile": "Sales VP · Chicago · 100K+ frequent flyer miles",
        "post_time": "1 day ago",
        "engagement": "189 likes · 47 replies",
        "post_content": "That's IT. American Airlines just cancelled my third flight this month. Stranded again in DFW. @AmericanAir your operational meltdown is unacceptable. Switching all my business travel. Recommendations for a reliable carrier? Willing to pay more for not-this. #flightdeals #neveragain"
    },

    # ---- Active research ----
    {
        "id": "sig_004",
        "platform": "Reddit",
        "user_handle": "u/sf_techie_nomad",
        "user_profile": "r/digitalnomad · 18K karma · Posts about remote work + travel",
        "post_time": "3 hours ago",
        "engagement": "62 upvotes · 24 comments",
        "post_content": "Comparing Lisbon vs. Bali for a 3-month remote work stint starting January. Looking at apartment rentals, coworking spaces, visa requirements. Anyone done both? Trying to decide between Mediterranean fall vs. tropical heat. Budget around $4k/mo all in. #digitalnomad #remotework #travelplanning"
    },

    # ---- Path A: Marcus (partial consent) ----
    {
        "id": "sig_005",
        "platform": "Instagram",
        "user_handle": "@marcuschen",
        "user_profile": "Founder · San Francisco · Travel + food · 8.4K followers",
        "post_time": "6 hours ago",
        "engagement": "320 likes · 28 comments",
        "post_content": "Tokyo cherry blossom season hits different. The izakayas in Shibuya, the silence of Meiji shrine at 6am... I need to plan a return trip. Maybe late October for autumn colors? Anyone done Kyoto in fall? #wanderlust #honeymoon"
    },

    # ---- Path A: Emma (family) ----
    {
        "id": "sig_006",
        "platform": "Instagram",
        "user_handle": "@emmarodriguez_",
        "user_profile": "Family adventures · Miami · Mom of 2 · Travel blogger · 22K followers",
        "post_time": "1 day ago",
        "engagement": "1.4K likes · 67 comments",
        "post_content": "Planning the BIG one — taking the kids to see real penguins. Looking at Patagonia/Antarctic expedition cruises for next winter. Anyone done this with kids 8-12? Budget is flexible, this is once-in-a-lifetime. #familytravel #wanderlust"
    },

    # ---- Dreaming ----
    {
        "id": "sig_007",
        "platform": "Twitter",
        "user_handle": "@office_dreamer",
        "user_profile": "Accountant · Indianapolis · Mom of 2 · Cat lover",
        "post_time": "30 minutes ago",
        "engagement": "4 likes · 1 reply",
        "post_content": "Manifesting a trip to Santorini one day. Those white buildings and blue water just look so peaceful. Maybe when the kids are older. Until then, scrolling Pinterest. #travelplanning #wanderlust"
    },

    # ---- Competitor mention ----
    {
        "id": "sig_008",
        "platform": "Twitter",
        "user_handle": "@points_pirate",
        "user_profile": "Travel hacker · Toronto · Award travel obsessed",
        "post_time": "4 hours ago",
        "engagement": "78 likes · 31 replies",
        "post_content": "Just used Expedia for a Madrid+Lisbon multi-city in May. Their multi-city tool is decent but Booking.com had better hotel prices. Why doesn't anyone do good package deals anymore? #flightdeals #travelhacks"
    },

    # ---- Advocacy ----
    {
        "id": "sig_009",
        "platform": "Instagram",
        "user_handle": "@kayla_explores",
        "user_profile": "Photographer · Denver · Solo female traveler · 3.5K followers",
        "post_time": "yesterday",
        "engagement": "412 likes · 18 comments",
        "post_content": "Iceland just BLEW MY MIND. Six days of waterfalls, black sand beaches, and the Northern Lights on night four. The whole trip cost less than I expected too. Anyone planning Iceland for this winter — DM me, I'll send my itinerary. #wanderlust #adventuretravel"
    },

    # ---- Ready to book (Path B) ----
    {
        "id": "sig_010",
        "platform": "Instagram",
        "user_handle": "@emma_londoner",
        "user_profile": "Lifestyle blogger · London · 15K followers · Fashion + travel",
        "post_time": "8 hours ago",
        "engagement": "234 likes · 19 comments",
        "post_content": "Right, decided on Maldives for honeymoon in October. Need overwater villa, 7 nights, all-inclusive. Budget £8k for two. Send me your best operators! I want this booked by end of next week. #honeymoon #luxurytravel"
    },

    # ---- Off-topic noise (should be filtered) ----
    {
        "id": "sig_011",
        "platform": "Twitter",
        "user_handle": "@career_pivot_kim",
        "user_profile": "Career coach · Portland",
        "post_time": "1 hour ago",
        "engagement": "12 likes · 3 replies",
        "post_content": "Just got my flight school enrollment confirmation! Becoming a pilot has been my dream for years. Studying for the PPL exam now. #aviationdreams"
    },

    # ---- Active research (Reddit, public) ----
    {
        "id": "sig_012",
        "platform": "Reddit",
        "user_handle": "u/honeymoon_planning_23",
        "user_profile": "r/honeymoons · 4.2K karma · Engagement ring posts",
        "post_time": "12 hours ago",
        "engagement": "89 upvotes · 41 comments",
        "post_content": "Hawaii vs. Maldives for October honeymoon. Both look amazing in different ways. Husband-to-be wants beaches + snorkeling, I want a mix of beach and culture. Budget $10k for 10 days. Help us decide? #honeymoon #travelplanning"
    },

    # ---- Ready to book (luxury) ----
    {
        "id": "sig_013",
        "platform": "Instagram",
        "user_handle": "@theworldis_round",
        "user_profile": "PE partner · NYC · Husband, dog dad · 890 followers",
        "post_time": "3 hours ago",
        "engagement": "31 likes · 4 comments",
        "post_content": "Anniversary trip locked: Four Seasons Bora Bora, 5 nights end of November. Just need to coordinate the flights from JFK to PPT. Anyone know the best routing? Open to a 1-stop if it saves a few hours. #luxurytravel #anniversary"
    },

    # ---- Competitor complaint (airline) ----
    {
        "id": "sig_014",
        "platform": "Twitter",
        "user_handle": "@miles_and_misery",
        "user_profile": "Consultant · Atlanta · 1M+ Delta miles",
        "post_time": "2 hours ago",
        "engagement": "67 likes · 23 replies",
        "post_content": "Delta devalued SkyMiles AGAIN. Same award now costs 40% more miles. Time to diversify. Looking at Star Alliance partners — what's everyone's favorite for international biz class redemptions? #milesandpoints #flightdeals"
    },

    # ---- Dreaming with brand mention ----
    {
        "id": "sig_015",
        "platform": "Instagram",
        "user_handle": "@jenna_explores",
        "user_profile": "Teacher · Boston · Aspiring traveler · 540 followers",
        "post_time": "1 day ago",
        "engagement": "18 likes · 2 comments",
        "post_content": "Saving every penny for a real vacation one day. Probably Italy — Tuscany rolling hills, espresso in piazzas, the works. For now I'm just collecting Pinterest boards. The dream! #wanderlust #travelplanning"
    },
]
