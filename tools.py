"""
Tools for the Voyage Acquisition agent.

In production these would call real APIs (Amadeus / Sabre for flights,
Booking.com / Expedia for hotels, OpenWeather for forecasts, internal
booking system for holds). For the demo we return realistic synthetic data.
"""

import random
from datetime import datetime, timedelta


# ============================================================
# TOOL DEFINITIONS — passed to the Anthropic API
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "search_flights",
        "description": "Search for flight options between two cities on specific dates. Use when the user has provided origin, destination, and at least one date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Departure city or airport code (e.g. 'Austin', 'AUS', 'New York')"
                },
                "destination": {
                    "type": "string",
                    "description": "Arrival city or airport code (e.g. 'Banff', 'YYC', 'Maldives')"
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format"
                },
                "return_date": {
                    "type": "string",
                    "description": "Return date in YYYY-MM-DD format. Optional for one-way."
                },
                "passengers": {
                    "type": "integer",
                    "description": "Number of passengers. Defaults to 1.",
                    "default": 1
                }
            },
            "required": ["origin", "destination", "departure_date"]
        }
    },
    {
        "name": "search_hotels",
        "description": "Search for hotel options at a destination for specific dates. Use when the user has destination + check-in date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Destination city (e.g. 'Banff', 'Tokyo', 'Maldives')"
                },
                "check_in": {
                    "type": "string",
                    "description": "Check-in date in YYYY-MM-DD format"
                },
                "check_out": {
                    "type": "string",
                    "description": "Check-out date in YYYY-MM-DD format"
                },
                "budget_tier": {
                    "type": "string",
                    "enum": ["budget", "mid", "luxury"],
                    "description": "Budget tier preference. Defaults to 'mid'.",
                    "default": "mid"
                }
            },
            "required": ["destination", "check_in", "check_out"]
        }
    },
    {
        "name": "check_weather",
        "description": "Get weather forecast or seasonal climate info for a destination. Use when the user asks about weather, climate, or 'is X a good time to visit'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Destination city"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format. Optional — if omitted returns seasonal climate."
                }
            },
            "required": ["destination"]
        }
    },
    {
        "name": "hold_booking",
        "description": "Hold a booking (flight + hotel package) for the user. Use ONLY after the user has confirmed they want to proceed with a specific package.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_id": {
                    "type": "string",
                    "description": "Flight ID from a previous search_flights result"
                },
                "hotel_id": {
                    "type": "string",
                    "description": "Hotel ID from a previous search_hotels result"
                },
                "customer_name": {
                    "type": "string",
                    "description": "Customer's full name"
                },
                "hold_duration_hours": {
                    "type": "integer",
                    "description": "How long to hold the booking. Defaults to 24.",
                    "default": 24
                }
            },
            "required": ["flight_id", "hotel_id", "customer_name"]
        }
    }
]


# ============================================================
# TOOL DISPATCH
# ============================================================

def execute_tool(tool_name, tool_input):
    """Dispatch a tool call to the right implementation."""
    if tool_name == "search_flights":
        return search_flights(**tool_input)
    elif tool_name == "search_hotels":
        return search_hotels(**tool_input)
    elif tool_name == "check_weather":
        return check_weather(**tool_input)
    elif tool_name == "hold_booking":
        return hold_booking(**tool_input)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


# ============================================================
# FLIGHT SEARCH
# ============================================================

def search_flights(origin, destination, departure_date, return_date=None, passengers=1):
    """Return a small set of realistic-looking flight options."""
    airlines = [
        ("Air Canada", "AC", 320),
        ("United", "UA", 350),
        ("WestJet", "WS", 280),
        ("Delta", "DL", 340),
    ]
    options = []
    base_price = random.randint(280, 480)

    for i, (name, code, baseline) in enumerate(airlines[:3]):
        price = base_price + (i * 35) + random.randint(-30, 60)
        duration_hours = random.randint(4, 9)
        stops = 0 if i == 0 else random.choice([0, 1])

        options.append({
            "flight_id": f"FL{code}{random.randint(1000, 9999)}",
            "airline": name,
            "origin": origin,
            "destination": destination,
            "departure_date": departure_date,
            "return_date": return_date,
            "duration_hours": duration_hours,
            "stops": stops,
            "price_per_passenger_usd": price,
            "total_price_usd": price * passengers
        })

    return {
        "search_summary": f"Found {len(options)} flight options for {origin} → {destination}",
        "options": options
    }


# ============================================================
# HOTEL SEARCH
# ============================================================

def search_hotels(destination, check_in, check_out, budget_tier="mid"):
    """Return realistic hotel options scaled to budget tier."""
    try:
        ci = datetime.strptime(check_in, "%Y-%m-%d")
        co = datetime.strptime(check_out, "%Y-%m-%d")
        nights = (co - ci).days
    except Exception:
        nights = 5

    price_ranges = {
        "budget": (90, 150),
        "mid": (180, 320),
        "luxury": (450, 1200)
    }
    low, high = price_ranges.get(budget_tier, (180, 320))

    hotel_templates = {
        "budget": [
            ("Hostelling International " + destination, 3.8),
            (destination + " Inn & Suites", 4.0),
            ("Budget Lodge " + destination, 3.6),
        ],
        "mid": [
            ("The " + destination + " Boutique Hotel", 4.4),
            (destination + " Plaza", 4.3),
            ("Hyatt Place " + destination, 4.5),
        ],
        "luxury": [
            ("Four Seasons " + destination, 4.9),
            ("The Ritz-Carlton " + destination, 4.8),
            ("Aman " + destination, 5.0),
        ]
    }

    options = []
    for name, rating in hotel_templates.get(budget_tier, hotel_templates["mid"])[:3]:
        price_per_night = random.randint(low, high)
        options.append({
            "hotel_id": f"HT{random.randint(10000, 99999)}",
            "name": name,
            "destination": destination,
            "check_in": check_in,
            "check_out": check_out,
            "nights": nights,
            "rating": rating,
            "price_per_night_usd": price_per_night,
            "total_price_usd": price_per_night * nights,
            "amenities": _amenities_for_tier(budget_tier)
        })

    return {
        "search_summary": f"Found {len(options)} {budget_tier}-tier hotels in {destination} for {nights} nights",
        "options": options
    }


def _amenities_for_tier(tier):
    if tier == "luxury":
        return ["Spa", "Concierge", "Fine dining", "Pool", "Gym", "Room service 24/7"]
    elif tier == "mid":
        return ["Pool", "Gym", "Restaurant", "Wifi", "Breakfast included"]
    else:
        return ["Wifi", "Common kitchen", "Shared lounge"]


# ============================================================
# WEATHER
# ============================================================

def check_weather(destination, date=None):
    """Return a forecast or seasonal climate snapshot."""
    seasonal = _seasonal_climate(destination, date)
    return {
        "destination": destination,
        "date": date or "seasonal_overview",
        "summary": seasonal["summary"],
        "temperature_c": seasonal["temp_c"],
        "temperature_f": seasonal["temp_f"],
        "conditions": seasonal["conditions"],
        "packing_tip": seasonal["packing"]
    }


def _seasonal_climate(destination, date_str):
    """Pretend climate data — varies by destination keyword and rough month."""
    dest = destination.lower()
    month = 10  # default October if no date
    if date_str:
        try:
            month = datetime.strptime(date_str, "%Y-%m-%d").month
        except Exception:
            pass

    # Rough mappings by destination type
    if any(k in dest for k in ["banff", "rockies", "alps", "whistler", "jackson"]):
        if month in [10, 11]:
            return {"summary": "Crisp fall, cool nights", "temp_c": "2–12", "temp_f": "36–54", "conditions": "Mostly clear, occasional snow at altitude", "packing": "Layers, waterproof shell, hiking boots, gloves"}
        elif month in [12, 1, 2, 3]:
            return {"summary": "Deep winter, full snow", "temp_c": "-15 to -3", "temp_f": "5–27", "conditions": "Snow, sub-zero nights", "packing": "Heavy down, base layers, insulated boots"}
        else:
            return {"summary": "Mild summer, long days", "temp_c": "10–22", "temp_f": "50–72", "conditions": "Sunny, occasional thunderstorms", "packing": "Layers, hiking gear, light rain shell"}

    if any(k in dest for k in ["maldives", "bali", "phuket", "fiji", "caribbean"]):
        return {"summary": "Tropical, warm year-round", "temp_c": "26–32", "temp_f": "79–90", "conditions": "Sunny with brief afternoon showers", "packing": "Swimwear, light cotton, sandals, sunscreen"}

    if any(k in dest for k in ["tokyo", "kyoto", "japan"]):
        if month in [10, 11]:
            return {"summary": "Stunning autumn, perfect temps", "temp_c": "12–20", "temp_f": "54–68", "conditions": "Clear, low humidity, fall colors", "packing": "Light jacket, layers, walking shoes"}
        elif month in [3, 4]:
            return {"summary": "Cherry blossom season", "temp_c": "10–18", "temp_f": "50–64", "conditions": "Mild, occasional rain", "packing": "Light jacket, umbrella, comfortable shoes"}
        else:
            return {"summary": "Variable", "temp_c": "15–25", "temp_f": "59–77", "conditions": "Varies by season", "packing": "Check forecast closer to date"}

    return {"summary": "Pleasant", "temp_c": "15–25", "temp_f": "59–77", "conditions": "Variable", "packing": "Layers"}


# ============================================================
# BOOKING HOLD
# ============================================================

def hold_booking(flight_id, hotel_id, customer_name, hold_duration_hours=24):
    """Create a provisional hold."""
    confirmation = f"VC-{random.randint(10000, 99999)}-HOLD"
    expires = datetime.now() + timedelta(hours=hold_duration_hours)
    return {
        "status": "HOLD_CONFIRMED",
        "confirmation_number": confirmation,
        "customer_name": customer_name,
        "flight_id": flight_id,
        "hotel_id": hotel_id,
        "hold_duration_hours": hold_duration_hours,
        "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S"),
        "next_step": f"Complete payment by {expires.strftime('%b %d, %I:%M %p')} to convert this hold into a confirmed booking."
    }
