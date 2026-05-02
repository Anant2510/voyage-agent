import os
from anthropic import Anthropic
from dotenv import load_dotenv
from datetime import datetime
from prompts import SYSTEM_PROMPT
from tools import TOOLS, execute_tool

load_dotenv()


class VoyageAgent:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
        
        self.client = Anthropic(api_key=api_key)
        self.conversation_history = []
        self.model = "claude-sonnet-4-5-20250929"
        self.max_tokens = 4096
    
    def chat(self, user_message):
        """Process a user message and return the agent's response."""
        
        self.conversation_history.append({
            "role": "user",
            "content": user_message
        })
        
        system_with_date = SYSTEM_PROMPT + f"\n\n## Current Context\nToday's date is: {datetime.now().strftime('%A, %B %d, %Y')}"
        
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_with_date,
                tools=TOOLS,
                messages=self.conversation_history
            )
            
            self.conversation_history.append({
                "role": "assistant",
                "content": response.content
            })
            
            if response.stop_reason == "tool_use":
                tool_results = []
                
                for block in response.content:
                    if block.type == "tool_use":
                        print(f"\n🔧 Calling tool: {block.name}")
                        print(f"   Input: {block.input}")
                        
                        result = execute_tool(block.name, block.input)
                        print(f"   ✓ Tool executed successfully")
                        
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result)
                        })
                
                self.conversation_history.append({
                    "role": "user",
                    "content": tool_results
                })
                continue
            
            else:
                text_response = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text_response += block.text
                
                return text_response
        
        return "I'm having trouble completing that request. Could you try rephrasing?"
    
    def reset(self):
        """Reset conversation history."""
        self.conversation_history = []
