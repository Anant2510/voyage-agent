"""
Voyage Agent — Acquisition Stage (FINAL)
=========================================

Third stage of the multi-agent pipeline. Live booking conversation with
tool use. Receives leads transferred from the Nurturing pipeline with full
context (destinations, budget, classification, original post hook).

This is a standard agentic loop:
  1. Send user message + tool definitions to Claude
  2. If Claude wants to use a tool, execute it locally
  3. Send the tool result back to Claude
  4. Loop until Claude returns a final text response (no tool_use)
  5. Return that text to the user

Tools (defined in tools.py):
  - search_flights      — flight search by origin/destination/date
  - search_hotels       — hotel search by destination/check-in
  - check_weather       — weather forecast for trip dates
  - hold_booking        — provisional reservation hold

Resilient to API overload via retry+fallback (same pattern as other agents).
"""

import os
import time
from anthropic import Anthropic

from prompts import ACQUISITION_SYSTEM_PROMPT
from tools import TOOL_DEFINITIONS, execute_tool


class VoyageAgent:
    """
    Acquisition agent for live booking conversations.
    Stateful: maintains conversation history across turns.
    """

    def __init__(self):
        self.client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-5-20250929"
        self.fallback_model = "claude-haiku-4-5-20251001"
        self.messages = []  # conversation history
        self.max_tool_iterations = 10  # safety limit on tool-use loops

    def chat(self, user_message):
        """
        Send a user message, run the tool-use loop, return Claude's final text.
        """
        self.messages.append({"role": "user", "content": user_message})

        for iteration in range(self.max_tool_iterations):
            response = self._call_with_retry()

            # Add Claude's response to history
            self.messages.append({"role": "assistant", "content": response.content})

            # Did Claude stop because it wants to use a tool?
            if response.stop_reason == "tool_use":
                # Execute every tool_use block and return tool_result blocks
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        try:
                            result = execute_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": str(result)
                            })
                        except Exception as e:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"Error executing {block.name}: {str(e)}",
                                "is_error": True
                            })

                # Send tool results back to Claude
                self.messages.append({"role": "user", "content": tool_results})
                # Continue loop to get Claude's next response
                continue

            # No tool use — extract final text and return
            text_parts = [block.text for block in response.content if block.type == "text"]
            return "\n\n".join(text_parts) if text_parts else "(no response)"

        return "Hit the tool-use iteration limit. Try rephrasing your request."

    def _call_with_retry(self):
        """
        Wrapped API call with retry-and-fallback.
        Same pattern as discovery / nurturing agents.
        """
        max_retries = 4
        retry_delay = 2
        models_to_try = [self.model, self.fallback_model]

        last_error = None

        for model_idx, model_to_use in enumerate(models_to_try):
            for attempt in range(max_retries):
                try:
                    response = self.client.messages.create(
                        model=model_to_use,
                        max_tokens=4096,
                        system=ACQUISITION_SYSTEM_PROMPT,
                        tools=TOOL_DEFINITIONS,
                        messages=self.messages
                    )
                    if model_idx > 0:
                        print(f"   ℹ️  Used fallback model: {model_to_use}")
                    return response

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
                        print(f"   🔄 {model_to_use} overloaded. Falling back to {models_to_try[model_idx + 1]}...")
                        break
                    else:
                        raise

        raise last_error or Exception("All retry attempts failed")
