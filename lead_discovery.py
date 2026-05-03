"""
Lead Discovery Agent
Analyzes simulated social signals and identifies high-intent travel leads.
"""

import os
import json
from datetime import datetime, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# SIMULATED SOCIAL SIGNALS DATABASE
# ============================================================

SOCIAL_SIGNALS = [
    {
        "id": "sig_001",
        "platform": "Instagram",
        "user_handle": "@priya_wanderer",
        "post_content": "Work has been crazy. I need a vacation 😩 Any recommendations for a quick getaway from Mumbai?",
        "post_time": "2 hours ago",
        "engagement": "47 likes, 12 comments",
        "user_profile": "28F, lives in Mumbai, posts about food and travel",
    },
    {
        "id": "sig_002",
        "platform": "Reddit",
        "user_handle": "u/adventure_seeker_99",
        "post_content": "Best hill stations to visit in December? Looking for snow, decent budget. Coming from Delhi.",
        "post_time": "5 hours ago",
        "engagement": "23 upvotes, 8 comments in r/IndiaTravel",
        "user_profile": "M, late 20s, frequent Reddit traveler, asks detailed questions",
    },
    {
        "id": "sig_003",
        "platform": "Twitter",
        "user_handle": "@rajesh_corporate",
        "post_content": "5th anniversary coming up. Need to plan something special for the wife. She loves heritage and history. Suggestions welcome!",
        "post_time": "1 day ago",
        "engagement": "12 likes, 4 replies",
        "user_profile": "M, 35, corporate professional, married, based in Bangalore",
    },
    {
        "id": "sig_004",
        "platform": "Instagram",
        "user_handle": "@sneha_foodie",
        "post_content": "Just got my bonus! 💰 Time to plan that long-pending trip. Where should I go?",
        "post_time": "6 hours ago",
        "engagement": "89 likes, 24 comments",
        "user_profile": "26F, marketing professional, Hyderabad, posts about food and lifestyle",
    },
    {
        "id": "sig_005",
        "platform": "Reddit",
        "user_handle": "u/wedding_planner_pro",
        "post_content": "Honeymoon ideas for couple from Delhi - international preferred but open to domestic luxury. Budget around 3-4 lakhs.",
        "post_time": "8 hours ago",
        "engagement": "45 upvotes in r/IndianWeddings",
        "user_profile": "Helping a friend, mid-30s, Delhi",
    },
    {
        "id": "sig_006",
        "platform": "Search Trends",
        "user_handle": "Anonymous (cookies tracked)",
        "post_content": "Search history: 'maldives vs bali december', 'best resorts in goa', 'flight prices delhi to phuket', 'visa free countries for indians'",
        "post_time": "Last 3 days",
        "engagement": "12 searches, 4 site visits",
        "user_profile": "Returning visitor, 30s likely, comparing international destinations",
    },
    {
        "id": "sig_007",
        "platform": "Instagram",
        "user_handle": "@tech_dad_arjun",
        "post_content": "Family vacation time! Kids are 8 and 12. Need somewhere they won't get bored. Mountains > beach this time.",
        "post_time": "12 hours ago",
        "engagement": "34 likes, 9 comments",
        "user_profile": "M, 40s, family man, posts kid-friendly content",
    },
    {
        "id": "sig_008",
        "platform": "Twitter",
        "user_handle": "@finance_meera",
        "post_content": "WFH burnout is real. Considering a workation somewhere with good wifi and mountain views. Recommendations?",
        "post_time": "4 hours ago",
        "engagement": "67 likes, 15 replies",
        "user_profile": "29F, finance professional, Bangalore, remote worker",
    }
]


# ============================================================
# LEAD DISCOVERY AGENT
# ============================================================

class LeadDiscoveryAgent:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-5-20250929"
    
    def analyze_signal(self, signal):
        """Analyze a single social signal and determine if it's a high-intent travel lead."""
        
        prompt = f"""You are a lead qualification AI for a travel company. Analyze this social media signal and determine if it represents a high-intent travel lead.

SIGNAL DATA:
Platform: {signal['platform']}
User: {signal['user_handle']}
Post: "{signal['post_content']}"
Time: {signal['post_time']}
Engagement: {signal['engagement']}
User Profile: {signal['user_profile']}

Provide your analysis in this exact JSON format (no other text):
{{
  "intent_score": <0-100>,
  "intent_category": "<casual_browse|active_research|ready_to_book|booking_imminent>",
  "trip_type": "<short description of trip type>",
  "suggested_destinations": ["dest1", "dest2", "dest3"],
  "estimated_budget_inr": "<budget range>",
  "travel_window": "<when they likely want to travel>",
  "urgency": "<low|medium|high>",
  "personalization_hooks": ["hook1", "hook2", "hook3"],
  "recommended_first_message": "<the perfect opening message to send them>"
}}

Score factors to consider:
- Active intent words (need, want, planning, looking for) = higher score
- Specific details (dates, budget, destinations) = higher score
- Recent post = higher score
- Engagement on post = social proof
- User profile alignment with travel = higher score"""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            text = response.content[0].text.strip()
            # Remove markdown code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            
            analysis = json.loads(text)
            return analysis
        except (json.JSONDecodeError, IndexError) as e:
            return {
                "intent_score": 50,
                "intent_category": "active_research",
                "trip_type": "General travel interest",
                "suggested_destinations": ["TBD"],
                "estimated_budget_inr": "Unknown",
                "travel_window": "Unknown",
                "urgency": "medium",
                "personalization_hooks": ["General travel interest"],
                "recommended_first_message": "We noticed your post and would love to help plan your trip!",
                "error": str(e)
            }
    
    def scan_all_signals(self):
        """Scan all signals and return analyzed leads, sorted by intent score."""
        leads = []
        
        for signal in SOCIAL_SIGNALS:
            analysis = self.analyze_signal(signal)
            lead = {
                "signal": signal,
                "analysis": analysis,
                "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            leads.append(lead)
        
        # Sort by intent score, highest first
        leads.sort(key=lambda x: x["analysis"].get("intent_score", 0), reverse=True)
        return leads
