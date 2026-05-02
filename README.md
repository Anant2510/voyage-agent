---
title: Voyage Concierge
emoji: ✈️
colorFrom: indigo
colorTo: purple
sdk: gradio
sdk_version: 6.14.0
app_file: app.py
pinned: false
license: mit
short_description: AI-powered travel concierge agent
---

# Voyage Concierge Agent

An AI-powered travel concierge that helps plan and book trips through natural conversation.

## Features

- Natural conversation about trip planning
- Intelligent clarifying questions
- Real-time flight and hotel search (simulated for demo)
- Weather forecasts
- Booking flow

## Try Asking

- "Plan a weekend getaway to Goa from Delhi, budget around 30K"
- "I want a romantic anniversary trip to Udaipur"
- "Adventure trip to Manali in December for 5 days"

## Tech Stack

- **LLM:** Claude Sonnet 4.5 (Anthropic)
- **UI:** Gradio
- **Backend:** Python with tool-use agent loop

## Note

This is a demo version using simulated travel data. In production, this would connect to real flight/hotel APIs (Amadeus, Booking.com, etc.).
