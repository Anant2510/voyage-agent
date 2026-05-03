"""
Nurturing Agent
Generates personalized multi-touch campaigns for leads.
"""

import os
import json
from datetime import datetime, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()


class NurturingAgent:
    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-5-20250929"
    
    def generate_nurture_campaign(self, lead):
        """Generate a complete nurturing campaign for a lead."""
        
        signal = lead["signal"]
        analysis = lead["analysis"]
        
        prompt = f"""You are a nurturing campaign strategist for a travel company. Design a personalized 7-day multi-channel nurturing campaign for this lead.

LEAD INFORMATION:
- Platform: {signal['platform']}
- User: {signal['user_handle']}
- Original Post: "{signal['post_content']}"
- User Profile: {signal['user_profile']}

LEAD ANALYSIS:
- Intent Score: {analysis.get('intent_score', 'N/A')}/100
- Trip Type: {analysis.get('trip_type', 'N/A')}
- Suggested Destinations: {', '.join(analysis.get('suggested_destinations', []))}
- Budget: {analysis.get('estimated_budget_inr', 'N/A')}
- Urgency: {analysis.get('urgency', 'N/A')}
- Personalization Hooks: {', '.join(analysis.get('personalization_hooks', []))}

Design a 5-touchpoint campaign over 7 days. Mix channels (email, WhatsApp, social DM, retargeting ad). Each touchpoint should feel personal and progressively move them toward booking.

Provide response in this exact JSON format (no other text):
{{
  "campaign_name": "<short campaign name>",
  "total_duration_days": 7,
  "expected_conversion_probability": <0-100>,
  "touchpoints": [
    {{
      "day": 1,
      "channel": "<email|whatsapp|sms|ad|social_dm>",
      "type": "<welcome|inspiration|offer|urgency|social_proof|handoff>",
      "subject_line": "<for emails>",
      "message_preview": "<first 30 words of the actual message>",
      "full_message": "<complete personalized message>",
      "personalization_used": ["element1", "element2"],
      "expected_action": "<open|click|reply|book>"
    }}
  ],
  "handoff_trigger": "<what action triggers handoff to acquisition agent>"
}}

Make it feel like a thoughtful friend reaching out, NOT corporate spam. Use the user's actual interests and language style from their original post."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            
            campaign = json.loads(text)
            return campaign
        except (json.JSONDecodeError, IndexError) as e:
            return {
                "error": str(e),
                "campaign_name": "Default Campaign",
                "touchpoints": []
            }
