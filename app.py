"""
Voyage Concierge Agent - Web UI (Gradio 6.x compatible)
Run with: python web_app.py
Then open: http://localhost:7860
"""

import gradio as gr
from agent import VoyageAgent


# ============================================================
# AGENT MANAGEMENT
# ============================================================

def create_new_agent():
    """Create a fresh agent instance."""
    return VoyageAgent()


def chat_handler(message, history, agent_state):
    """Handle a user message in the chat."""
    if agent_state is None:
        agent_state = create_new_agent()
    
    if not message or not message.strip():
        return "", history, agent_state
    
    try:
        response = agent_state.chat(message)
    except Exception as e:
        response = f"Sorry, I hit an error: {str(e)}\n\nCould you try rephrasing your request?"
    
    # Append to history (Gradio 6 messages format - list of dicts)
    history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": response}
    ]
    
    return "", history, agent_state


def reset_chat():
    """Reset the conversation and create a fresh agent."""
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
    max-width: 900px !important;
    margin: auto !important;
}

.header-text {
    text-align: center;
    padding: 20px 0 10px 0;
}

.header-title {
    font-size: 32px;
    font-weight: 700;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin-bottom: 8px;
}

.header-subtitle {
    color: #6b7280;
    font-size: 15px;
}

footer {
    display: none !important;
}
"""


# ============================================================
# BUILD INTERFACE
# ============================================================

with gr.Blocks(title="Voyage Concierge") as demo:
    
    # Header
    gr.HTML("""
        <div class="header-text">
            <div class="header-title">Voyage Concierge</div>
            <div class="header-subtitle">
                Your AI-powered travel planner. Just describe your dream trip in plain English.
            </div>
        </div>
    """)
    
    # Session state for the agent
    agent_state = gr.State(None)
    
    # Chat interface (Gradio 6 syntax)
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
    
    # Input area
    with gr.Row():
        msg_input = gr.Textbox(
            placeholder="e.g., 'Plan a romantic weekend in Udaipur next month, budget around 50K'",
            show_label=False,
            scale=8,
            container=False,
            autofocus=True
        )
        send_btn = gr.Button("Send", scale=1, variant="primary")
    
    # Action buttons
    with gr.Row():
        reset_btn = gr.Button("Start New Trip", size="sm", variant="secondary")
    
    # Example prompts
    gr.Markdown("### Try these examples:")
    
    with gr.Row():
        ex1 = gr.Button(
            "Weekend in Goa from Delhi, budget 30K",
            size="sm"
        )
        ex2 = gr.Button(
            "Romantic anniversary trip to Udaipur",
            size="sm"
        )
    
    with gr.Row():
        ex3 = gr.Button(
            "Adventure trip to Manali in December",
            size="sm"
        )
        ex4 = gr.Button(
            "Surprise me with a relaxing 3-day getaway",
            size="sm"
        )
    
    # Footer
    gr.Markdown(
        """
        ---
        <div style='text-align: center; color: #9ca3af; font-size: 12px; padding: 10px;'>
        Powered by Claude AI · Demo version with simulated travel data
        </div>
        """
    )
    
    # ============================================================
    # WIRE UP EVENTS
    # ============================================================
    
    # Send message on Enter
    msg_input.submit(
        chat_handler,
        inputs=[msg_input, chatbot, agent_state],
        outputs=[msg_input, chatbot, agent_state]
    )
    
    # Send button click
    send_btn.click(
        chat_handler,
        inputs=[msg_input, chatbot, agent_state],
        outputs=[msg_input, chatbot, agent_state]
    )
    
    # Reset chat
    reset_btn.click(
        reset_chat,
        outputs=[chatbot, agent_state]
    )
    
    # Example prompts - fill input box
    ex1.click(
        lambda: "Plan a weekend trip to Goa from Delhi next month, budget around 30K",
        outputs=msg_input
    )
    ex2.click(
        lambda: "Plan a romantic anniversary trip to Udaipur for 3 days",
        outputs=msg_input
    )
    ex3.click(
        lambda: "I want an adventure trip to Manali in December for 5 days",
        outputs=msg_input
    )
    ex4.click(
        lambda: "Surprise me with a relaxing 3-day getaway from Delhi, somewhere peaceful",
        outputs=msg_input
    )


# ============================================================
# LAUNCH
# ============================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  VOYAGE CONCIERGE - Web Interface")
    print("=" * 60)
    print("  Starting server...")
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
