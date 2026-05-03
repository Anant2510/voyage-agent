"""
Voyage Concierge Agent - Complete Demo
Multi-tab interface showing Lead Discovery → Nurturing → Acquisition
"""

import gradio as gr
import json
from agent import VoyageAgent
from lead_discovery import LeadDiscoveryAgent, SOCIAL_SIGNALS
from nurturing import NurturingAgent


# ============================================================
# GLOBAL STATE
# ============================================================

# Cache analyzed leads to avoid re-analyzing on every refresh
analyzed_leads_cache = []
nurture_campaigns_cache = {}


# ============================================================
# LEAD DISCOVERY HANDLERS
# ============================================================

def scan_signals():
    """Scan all signals and return formatted lead cards."""
    global analyzed_leads_cache
    
    yield "🔄 Initializing Lead Discovery Agent...", []
    
    agent = LeadDiscoveryAgent()
    
    yield "🔍 Analyzing social signals across platforms...", []
    
    leads = agent.scan_all_signals()
    analyzed_leads_cache = leads
    
    # Format as markdown cards
    cards = format_lead_cards(leads)
    summary = format_discovery_summary(leads)
    
    yield summary, cards


def format_discovery_summary(leads):
    """Generate a summary header for the discovery tab."""
    if not leads:
        return "No leads found. Click 'Scan for New Leads' to start."
    
    high_intent = sum(1 for l in leads if l["analysis"].get("intent_score", 0) >= 80)
    medium_intent = sum(1 for l in leads if 60 <= l["analysis"].get("intent_score", 0) < 80)
    total = len(leads)
    
    return f"""### 🎯 Discovery Results

**{total} leads identified** from social signals across Instagram, Reddit, Twitter, and search trends.

| Intent Level | Count | Action |
|--------------|-------|--------|
| 🔥 High (80+) | {high_intent} | Immediate outreach recommended |
| 🌟 Medium (60-79) | {medium_intent} | Add to nurturing campaign |
| 💡 Low (<60) | {total - high_intent - medium_intent} | Long-term remarketing |

*Powered by Claude — analyzing signals in real-time*"""


def format_lead_cards(leads):
    """Format leads as a list of choices for the dropdown."""
    choices = []
    for i, lead in enumerate(leads):
        signal = lead["signal"]
        analysis = lead["analysis"]
        score = analysis.get("intent_score", 0)
        
        emoji = "🔥" if score >= 80 else "🌟" if score >= 60 else "💡"
        label = f"{emoji} [{score}/100] {signal['user_handle']} - {analysis.get('trip_type', 'Unknown')[:50]}"
        choices.append((label, i))
    
    return gr.update(choices=choices, value=None)


def show_lead_detail(lead_index):
    """Show detailed view of a selected lead."""
    if lead_index is None or lead_index >= len(analyzed_leads_cache):
        return "Select a lead from the list above to see details."
    
    lead = analyzed_leads_cache[lead_index]
    signal = lead["signal"]
    analysis = lead["analysis"]
    
    score = analysis.get("intent_score", 0)
    score_emoji = "🔥" if score >= 80 else "🌟" if score >= 60 else "💡"
    
    detail = f"""## {score_emoji} Lead Profile

### 📍 Signal Source
- **Platform:** {signal['platform']}
- **User:** {signal['user_handle']}
- **Posted:** {signal['post_time']}
- **Engagement:** {signal['engagement']}
- **Profile:** {signal['user_profile']}

### 💬 Original Post
> "{signal['post_content']}"

### 🤖 AI Analysis

| Metric | Value |
|--------|-------|
| **Intent Score** | {score}/100 {score_emoji} |
| **Category** | {analysis.get('intent_category', 'N/A').replace('_', ' ').title()} |
| **Trip Type** | {analysis.get('trip_type', 'N/A')} |
| **Suggested Destinations** | {', '.join(analysis.get('suggested_destinations', []))} |
| **Budget Range** | {analysis.get('estimated_budget_inr', 'N/A')} |
| **Travel Window** | {analysis.get('travel_window', 'N/A')} |
| **Urgency** | {analysis.get('urgency', 'N/A').upper()} |

### 🎯 Personalization Hooks
{chr(10).join(f"- {hook}" for hook in analysis.get('personalization_hooks', []))}

### ✉️ AI-Recommended First Message
> "{analysis.get('recommended_first_message', 'N/A')}"

---

*Ready to nurture this lead? Go to the **Nurturing** tab and select this lead to generate a personalized campaign.*"""
    
    return detail


# ============================================================
# NURTURING HANDLERS
# ============================================================

def get_lead_choices_for_nurturing():
    """Get list of leads to populate nurturing dropdown."""
    if not analyzed_leads_cache:
        return gr.update(choices=[], value=None)
    
    choices = []
    for i, lead in enumerate(analyzed_leads_cache):
        signal = lead["signal"]
        analysis = lead["analysis"]
        score = analysis.get("intent_score", 0)
        emoji = "🔥" if score >= 80 else "🌟" if score >= 60 else "💡"
        label = f"{emoji} [{score}/100] {signal['user_handle']}"
        choices.append((label, i))
    
    return gr.update(choices=choices, value=None)


def generate_campaign(lead_index):
    """Generate a nurturing campaign for the selected lead."""
    if lead_index is None or lead_index >= len(analyzed_leads_cache):
        yield "Please select a lead from the dropdown above first.", ""
        return
    
    yield "🤖 Generating personalized nurturing campaign...", ""
    
    lead = analyzed_leads_cache[lead_index]
    
    # Check cache
    if lead_index in nurture_campaigns_cache:
        campaign = nurture_campaigns_cache[lead_index]
    else:
        agent = NurturingAgent()
        campaign = agent.generate_nurture_campaign(lead)
        nurture_campaigns_cache[lead_index] = campaign
    
    summary = format_campaign_summary(lead, campaign)
    timeline = format_campaign_timeline(campaign)
    
    yield summary, timeline


def format_campaign_summary(lead, campaign):
    """Format campaign summary header."""
    signal = lead["signal"]
    
    return f"""## 🌱 Nurturing Campaign for {signal['user_handle']}

**Campaign:** {campaign.get('campaign_name', 'Custom Campaign')}  
**Duration:** {campaign.get('total_duration_days', 7)} days  
**Expected Conversion:** {campaign.get('expected_conversion_probability', 'N/A')}%  
**Touchpoints:** {len(campaign.get('touchpoints', []))} across multiple channels

*Each message is uniquely personalized using AI based on this lead's profile and behavior.*"""


def format_campaign_timeline(campaign):
    """Format the campaign as a visual timeline."""
    touchpoints = campaign.get("touchpoints", [])
    
    if not touchpoints:
        return "No touchpoints generated. Try again."
    
    channel_emojis = {
        "email": "📧",
        "whatsapp": "💬",
        "sms": "📱",
        "ad": "🎯",
        "social_dm": "💌"
    }
    
    type_emojis = {
        "welcome": "👋",
        "inspiration": "✨",
        "offer": "🎁",
        "urgency": "⏰",
        "social_proof": "⭐",
        "handoff": "🤖"
    }
    
    timeline = "## 📅 Campaign Timeline\n\n"
    
    for tp in touchpoints:
        day = tp.get("day", "?")
        channel = tp.get("channel", "email").lower()
        tp_type = tp.get("type", "outreach").lower()
        
        c_emoji = channel_emojis.get(channel, "📨")
        t_emoji = type_emojis.get(tp_type, "📌")
        
        timeline += f"### Day {day} — {c_emoji} {channel.title()} {t_emoji} {tp_type.replace('_', ' ').title()}\n\n"
        
        if tp.get("subject_line"):
            timeline += f"**Subject:** {tp['subject_line']}\n\n"
        
        timeline += f"**Message:**\n\n> {tp.get('full_message', tp.get('message_preview', 'N/A'))}\n\n"
        
        if tp.get("personalization_used"):
            timeline += f"**Personalization:** {', '.join(tp['personalization_used'])}\n\n"
        
        timeline += f"**Expected:** {tp.get('expected_action', 'engagement')}\n\n"
        timeline += "---\n\n"
    
    if campaign.get("handoff_trigger"):
        timeline += f"\n## 🤖 Handoff to Acquisition Agent\n\n**Trigger:** {campaign['handoff_trigger']}\n\n*Lead is now ready for the live booking conversation. Switch to the **Acquisition** tab.*"
    
    return timeline


# ============================================================
# ACQUISITION HANDLERS (existing chat agent)
# ============================================================

def create_new_agent():
    return VoyageAgent()


def chat_handler(message, history, agent_state):
    if agent_state is None:
        agent_state = create_new_agent()
    
    if not message or not message.strip():
        return "", history, agent_state
    
    try:
        response = agent_state.chat(message)
    except Exception as e:
        response = f"Sorry, I hit an error: {str(e)}\n\nCould you try rephrasing?"
    
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response}
    ]
    
    return "", history, agent_state


def reset_chat():
    initial_message = [{
        "role": "assistant",
        "content": "Hi! I'm Voyage, your AI travel concierge. Tell me about the trip you're dreaming of!"
    }]
    return initial_message, create_new_agent()


# ============================================================
# CUSTOM CSS
# ============================================================

CUSTOM_CSS = """
.gradio-container {
    max-width: 1200px !important;
    margin: auto !important;
}

.header-text {
    text-align: center;
    padding: 20px 0 10px 0;
}

.header-title {
    font-size: 36px;
    font-weight: 700;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
}

.header-subtitle {
    color: #6b7280;
    font-size: 16px;
}

.tab-description {
    background: #f3f4f6;
    border-left: 4px solid #667eea;
    padding: 12px 16px;
    border-radius: 4px;
    margin-bottom: 16px;
}

footer {
    display: none !important;
}
"""


# ============================================================
# BUILD INTERFACE
# ============================================================

with gr.Blocks(title="Voyage Concierge - Multi-Agent System") as demo:
    
    gr.HTML("""
        <div class="header-text">
            <div class="header-title">✈️ Voyage Concierge</div>
            <div class="header-subtitle">
                End-to-end Agentic AI: Lead Discovery → Nurturing → Acquisition
            </div>
        </div>
    """)
    
    with gr.Tabs():
        
        # ==========================================
        # TAB 1: LEAD DISCOVERY
        # ==========================================
        with gr.Tab("🔍 Lead Discovery"):
            
            gr.Markdown("""
            <div class="tab-description">
            <strong>Lead Discovery Agent</strong> — Continuously monitors social platforms (Reddit, Instagram, Twitter, search trends) 
            and uses AI to identify high-intent travel leads. Each signal is analyzed for intent score, trip preferences, 
            and personalization hooks.
            </div>
            """, elem_classes="tab-description")
            
            with gr.Row():
                scan_btn = gr.Button(
                    "🔄 Scan for New Leads",
                    variant="primary",
                    size="lg"
                )
            
            discovery_summary = gr.Markdown("Click 'Scan for New Leads' to analyze social signals.")
            
            gr.Markdown("### 🎯 Identified Leads")
            
            lead_dropdown = gr.Dropdown(
                label="Select a lead to see details",
                choices=[],
                interactive=True
            )
            
            lead_detail = gr.Markdown("Select a lead from the dropdown above to see full analysis.")
            
            # Wire up events
            scan_btn.click(
                scan_signals,
                outputs=[discovery_summary, lead_dropdown]
            )
            
            lead_dropdown.change(
                show_lead_detail,
                inputs=[lead_dropdown],
                outputs=[lead_detail]
            )
        
        # ==========================================
        # TAB 2: NURTURING
        # ==========================================
        with gr.Tab("🌱 Nurturing"):
            
            gr.Markdown("""
            <div class="tab-description">
            <strong>Nurturing Agent</strong> — Generates personalized multi-channel campaigns for each lead. 
            Email, WhatsApp, SMS, retargeting ads — all uniquely written for each lead's specific interests and behavior.
            No templates, no spam — every message is AI-crafted.
            </div>
            """, elem_classes="tab-description")
            
            refresh_leads_btn = gr.Button("🔄 Refresh Leads from Discovery", size="sm")
            
            nurture_lead_dropdown = gr.Dropdown(
                label="Select a lead to generate campaign",
                choices=[],
                interactive=True
            )
            
            generate_btn = gr.Button(
                "🌱 Generate Nurturing Campaign",
                variant="primary",
                size="lg"
            )
            
            campaign_summary = gr.Markdown("Select a lead and click 'Generate Campaign' to start.")
            
            campaign_timeline = gr.Markdown("")
            
            # Wire up events
            refresh_leads_btn.click(
                get_lead_choices_for_nurturing,
                outputs=[nurture_lead_dropdown]
            )
            
            generate_btn.click(
                generate_campaign,
                inputs=[nurture_lead_dropdown],
                outputs=[campaign_summary, campaign_timeline]
            )
        
        # ==========================================
        # TAB 3: ACQUISITION (Live Agent)
        # ==========================================
        with gr.Tab("💬 Acquisition"):
            
            gr.Markdown("""
            <div class="tab-description">
            <strong>Acquisition Agent</strong> — The live booking conversation. Once a nurtured lead clicks through, 
            they land here. Multi-turn conversation, real-time tool use (flight search, hotel search, weather), 
            personalized recommendations, end-to-end booking flow.
            </div>
            """, elem_classes="tab-description")
            
            agent_state = gr.State(None)
            
            chatbot = gr.Chatbot(
                label="Conversation",
                height=500,
                show_label=False,
                value=[
                    {
                        "role": "assistant",
                        "content": "Hi! I'm Voyage, your AI travel concierge. Tell me about the trip you're dreaming of, and I'll help plan and book it.\n\nTry one of the example prompts below, or just describe what you have in mind!"
                    }
                ]
            )
            
            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="e.g., 'Plan a romantic weekend in Udaipur next month, budget around 50K'",
                    show_label=False,
                    scale=8,
                    container=False,
                    autofocus=True
                )
                send_btn = gr.Button("Send", scale=1, variant="primary")
            
            with gr.Row():
                reset_btn = gr.Button("Start New Trip", size="sm", variant="secondary")
            
            gr.Markdown("### Try these examples:")
            
            with gr.Row():
                ex1 = gr.Button("Weekend in Goa from Delhi, budget 30K", size="sm")
                ex2 = gr.Button("Romantic anniversary trip to Udaipur", size="sm")
            
            with gr.Row():
                ex3 = gr.Button("Adventure trip to Manali in December", size="sm")
                ex4 = gr.Button("Surprise me with a relaxing 3-day getaway", size="sm")
            
            # Wire up events
            msg_input.submit(
                chat_handler,
                inputs=[msg_input, chatbot, agent_state],
                outputs=[msg_input, chatbot, agent_state]
            )
            
            send_btn.click(
                chat_handler,
                inputs=[msg_input, chatbot, agent_state],
                outputs=[msg_input, chatbot, agent_state]
            )
            
            reset_btn.click(
                reset_chat,
                outputs=[chatbot, agent_state]
            )
            
            ex1.click(lambda: "Plan a weekend trip to Goa from Delhi next month, budget around 30K", outputs=msg_input)
            ex2.click(lambda: "Plan a romantic anniversary trip to Udaipur for 3 days", outputs=msg_input)
            ex3.click(lambda: "I want an adventure trip to Manali in December for 5 days", outputs=msg_input)
            ex4.click(lambda: "Surprise me with a relaxing 3-day getaway from Delhi, somewhere peaceful", outputs=msg_input)
    
    gr.Markdown(
        """
        ---
        <div style='text-align: center; color: #9ca3af; font-size: 12px; padding: 10px;'>
        Powered by Claude AI · Multi-Agent System Demo · End-to-End Lead Lifecycle
        </div>
        """
    )


# ============================================================
# LAUNCH
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  VOYAGE CONCIERGE - Multi-Agent Demo")
    print("=" * 60)
    print("  Tabs: Lead Discovery | Nurturing | Acquisition")
    print("  Open in browser: http://localhost:7860")
    print("  Press Ctrl+C to stop")
    print("=" * 60 + "\n")
    
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(
            primary_hue="indigo",
            secondary_hue="purple",
            neutral_hue="slate"
        ),
        inbrowser=True
    )
