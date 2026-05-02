import os
import random
from datetime import datetime, timedelta

# ============================================================
# TOOL DEFINITIONS (for Claude's tool use API)
# ============================================================

TOOLS = [
    {
        "name": "search_flights",
        "description": "Search for flights between two cities on a given date. Returns available flight options with prices in INR.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Origin city name (e.g., 'Delhi', 'Mumbai')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination city name (e.g., 'Goa', 'Udaipur')"
                },
                "departure_date": {
                    "type": "string",
                    "description": "Departure date in YYYY-MM-DD format"
                },
                "return_date": {
                    "type": "string",
                    "description": "Return date in YYYY-MM-DD format (optional for one-way trips)"
                },
                "passengers": {
                    "type": "integer",
                    "description": "Number of passengers, default 1"
                }
            },
            "required": ["origin", "destination", "departure_date"]
        }
    },
    {
        "name": "search_hotels",
        "description": "Search for hotels in a destination for given check-in and check-out dates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Destination city name"
                },
                "check_in": {
                    "type": "string",
                    "description": "Check-in date in YYYY-MM-DD format"
                },
                "check_out": {
                    "type": "string",
                    "description": "Check-out date in YYYY-MM-DD format"
                },
                "guests": {
                    "type": "integer",
                    "description": "Number of guests, default 2"
                }
            },
            "required": ["destination", "check_in", "check_out"]
        }
    },
    {
        "name": "check_weather",
        "description": "Get weather forecast for a destination on a specific date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Destination city name"
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format"
                }
            },
            "required": ["destination", "date"]
        }
    },
    {
        "name": "create_booking",
        "description": "Create a booking once the user confirms their selected flight and hotel.",
        "input_schema": {
            "type": "object",
            "properties": {
                "flight_details": {
                    "type": "string",
                    "description": "Selected flight summary"
                },
                "hotel_details": {
                    "type": "string",
                    "description": "Selected hotel summary"
                },
                "total_price_inr": {
                    "type": "number",
                    "description": "Total price in INR"
                },
                "traveler_name": {
                    "type": "string",
                    "description": "Primary traveler's name (use 'Guest' if not provided)"
                }
            },
            "required": ["flight_details", "hotel_details", "total_price_inr"]
        }
    }
]


# ============================================================
# REALISTIC AIRLINE DATA BY ROUTE
# ============================================================

AIRLINES_BY_ROUTE = {
    "delhi-goa": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (3500, 6500), "duration_min": 150},
        {"airline": "Air India Express", "prefix": "IX", "price_range": (3200, 5800), "duration_min": 165},
        {"airline": "Vistara", "prefix": "UK", "price_range": (4500, 7800), "duration_min": 150},
        {"airline": "SpiceJet", "prefix": "SG", "price_range": (3000, 5500), "duration_min": 160},
    ],
    "mumbai-goa": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (2500, 4500), "duration_min": 75},
        {"airline": "Vistara", "prefix": "UK", "price_range": (3000, 5200), "duration_min": 80},
        {"airline": "Air India", "prefix": "AI", "price_range": (2800, 4800), "duration_min": 75},
    ],
    "delhi-mumbai": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (3800, 7000), "duration_min": 130},
        {"airline": "Vistara", "prefix": "UK", "price_range": (4500, 8500), "duration_min": 130},
        {"airline": "Air India", "prefix": "AI", "price_range": (4000, 7500), "duration_min": 135},
    ],
    "delhi-bangalore": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (4200, 7500), "duration_min": 165},
        {"airline": "Vistara", "prefix": "UK", "price_range": (5000, 9000), "duration_min": 165},
        {"airline": "Akasa Air", "prefix": "QP", "price_range": (4000, 7000), "duration_min": 170},
    ],
    "delhi-udaipur": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (3500, 6500), "duration_min": 90},
        {"airline": "Vistara", "prefix": "UK", "price_range": (4500, 7500), "duration_min": 90},
    ],
    "delhi-jaipur": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (2500, 4500), "duration_min": 60},
        {"airline": "Air India", "prefix": "AI", "price_range": (2800, 5000), "duration_min": 60},
    ],
    "delhi-srinagar": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (4500, 8500), "duration_min": 90},
        {"airline": "Vistara", "prefix": "UK", "price_range": (5500, 9500), "duration_min": 90},
        {"airline": "SpiceJet", "prefix": "SG", "price_range": (4200, 7800), "duration_min": 95},
    ],
    "default": [
        {"airline": "IndiGo", "prefix": "6E", "price_range": (3500, 7000), "duration_min": 150},
        {"airline": "Vistara", "prefix": "UK", "price_range": (4500, 8500), "duration_min": 150},
        {"airline": "Air India", "prefix": "AI", "price_range": (4000, 7500), "duration_min": 155},
    ]
}


# ============================================================
# REALISTIC HOTEL DATA BY DESTINATION
# ============================================================

HOTELS_BY_DESTINATION = {
    "goa": [
        {"name": "Taj Holiday Village Resort & Spa", "rating": 4.7, "price_range": (12000, 18000), "type": "Luxury Beach Resort"},
        {"name": "Novotel Goa Resort & Spa", "rating": 4.5, "price_range": (8500, 12000), "type": "Premium Resort"},
        {"name": "The Park Calangute", "rating": 4.3, "price_range": (5500, 8500), "type": "Boutique Hotel"},
        {"name": "Treebo Trend Calangute", "rating": 4.0, "price_range": (2500, 4500), "type": "Budget Hotel"},
        {"name": "Cidade de Goa - IHCL SeleQtions", "rating": 4.6, "price_range": (10000, 15000), "type": "Heritage Beach Resort"},
    ],
    "udaipur": [
        {"name": "Taj Lake Palace", "rating": 4.9, "price_range": (35000, 65000), "type": "Heritage Luxury Palace"},
        {"name": "The Oberoi Udaivilas", "rating": 4.9, "price_range": (40000, 75000), "type": "Heritage Luxury"},
        {"name": "Trident Udaipur", "rating": 4.5, "price_range": (8500, 13000), "type": "Premium Hotel"},
        {"name": "Ramada by Wyndham Udaipur", "rating": 4.2, "price_range": (5500, 8500), "type": "Business Hotel"},
        {"name": "Hotel Boheda Palace", "rating": 4.0, "price_range": (3500, 5500), "type": "Boutique Heritage"},
    ],
    "manali": [
        {"name": "The Himalayan", "rating": 4.6, "price_range": (12000, 18000), "type": "Luxury Mountain Resort"},
        {"name": "Span Resort & Spa", "rating": 4.4, "price_range": (8500, 13000), "type": "Premium Resort"},
        {"name": "Snow Valley Resorts", "rating": 4.1, "price_range": (4500, 7000), "type": "Mountain Resort"},
        {"name": "Apple Country Resort", "rating": 4.0, "price_range": (3500, 5500), "type": "Mid-range Hotel"},
    ],
    "jaipur": [
        {"name": "Rambagh Palace", "rating": 4.9, "price_range": (35000, 60000), "type": "Heritage Luxury Palace"},
        {"name": "ITC Rajputana", "rating": 4.6, "price_range": (10000, 15000), "type": "Premium Hotel"},
        {"name": "Trident Jaipur", "rating": 4.5, "price_range": (8000, 12000), "type": "Premium Hotel"},
        {"name": "Holiday Inn Jaipur City Centre", "rating": 4.3, "price_range": (5500, 8000), "type": "Business Hotel"},
        {"name": "Hotel Pearl Palace", "rating": 4.1, "price_range": (2500, 4000), "type": "Heritage Budget"},
    ],
    "srinagar": [
        {"name": "The Lalit Grand Palace", "rating": 4.7, "price_range": (15000, 25000), "type": "Heritage Luxury"},
        {"name": "Vivanta Dal View", "rating": 4.5, "price_range": (10000, 15000), "type": "Premium Hotel"},
        {"name": "Sukoon Houseboat", "rating": 4.6, "price_range": (8000, 12000), "type": "Luxury Houseboat"},
        {"name": "Hotel Heevan", "rating": 4.2, "price_range": (5000, 7500), "type": "Mid-range Hotel"},
    ],
    "bangalore": [
        {"name": "The Leela Palace Bengaluru", "rating": 4.8, "price_range": (15000, 22000), "type": "Luxury Hotel"},
        {"name": "ITC Gardenia", "rating": 4.7, "price_range": (12000, 18000), "type": "Premium Hotel"},
        {"name": "Taj MG Road", "rating": 4.5, "price_range": (10000, 14000), "type": "Premium Hotel"},
        {"name": "Lemon Tree Premier", "rating": 4.2, "price_range": (5500, 8000), "type": "Mid-range Hotel"},
    ],
    "default": [
        {"name": "Taj Hotel", "rating": 4.6, "price_range": (10000, 15000), "type": "Luxury Hotel"},
        {"name": "ITC Hotel", "rating": 4.5, "price_range": (8500, 12500), "type": "Premium Hotel"},
        {"name": "Marriott", "rating": 4.4, "price_range": (7500, 11000), "type": "Premium Hotel"},
        {"name": "Lemon Tree Premier", "rating": 4.2, "price_range": (4500, 7000), "type": "Mid-range Hotel"},
        {"name": "Treebo Trend", "rating": 3.9, "price_range": (2500, 4500), "type": "Budget Hotel"},
    ]
}


# ============================================================
# WEATHER PATTERNS BY DESTINATION
# ============================================================

WEATHER_PATTERNS = {
    "goa": {
        "winter": {"temp": (24, 30), "conditions": "Sunny and pleasant", "rain_chance": 5},
        "summer": {"temp": (28, 34), "conditions": "Hot and humid", "rain_chance": 20},
        "monsoon": {"temp": (25, 30), "conditions": "Heavy rains and thunderstorms", "rain_chance": 80},
    },
    "manali": {
        "winter": {"temp": (-2, 8), "conditions": "Snowy and cold", "rain_chance": 30},
        "summer": {"temp": (15, 25), "conditions": "Pleasant and cool", "rain_chance": 20},
        "monsoon": {"temp": (12, 22), "conditions": "Rainy with occasional landslides", "rain_chance": 70},
    },
    "udaipur": {
        "winter": {"temp": (10, 24), "conditions": "Cool and clear", "rain_chance": 5},
        "summer": {"temp": (28, 40), "conditions": "Hot and dry", "rain_chance": 10},
        "monsoon": {"temp": (24, 32), "conditions": "Light to moderate rains", "rain_chance": 50},
    },
    "default": {
        "winter": {"temp": (15, 25), "conditions": "Pleasant", "rain_chance": 15},
        "summer": {"temp": (25, 35), "conditions": "Warm", "rain_chance": 20},
        "monsoon": {"temp": (22, 30), "conditions": "Rainy", "rain_chance": 60},
    }
}


def get_season(date_str):
    """Determine season based on date."""
    try:
        month = datetime.strptime(date_str, "%Y-%m-%d").month
        if month in [12, 1, 2]:
            return "winter"
        elif month in [6, 7, 8, 9]:
            return "monsoon"
        else:
            return "summer"
    except:
        return "winter"


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def search_flights(origin, destination, departure_date, return_date=None, passengers=1):
    """Generate realistic flight options."""
    
    route_key = f"{origin.lower().strip()}-{destination.lower().strip()}"
    airlines = AIRLINES_BY_ROUTE.get(route_key, AIRLINES_BY_ROUTE["default"])
    
    flights = []
    base_times = ["06:30", "09:15", "13:45", "18:20", "21:00"]
    
    selected_airlines = random.sample(airlines, min(3, len(airlines)))
    
    for i, airline_info in enumerate(selected_airlines):
        flight_num = f"{airline_info['prefix']}-{random.randint(100, 9999)}"
        depart_time = base_times[i % len(base_times)]
        
        duration_minutes = airline_info["duration_min"] + random.randint(-15, 15)
        depart_dt = datetime.strptime(f"{departure_date} {depart_time}", "%Y-%m-%d %H:%M")
        arrive_dt = depart_dt + timedelta(minutes=duration_minutes)
        
        price = random.randint(*airline_info["price_range"])
        
        flights.append({
            "airline": airline_info["airline"],
            "flight_number": flight_num,
            "departure": depart_dt.strftime("%Y-%m-%d %H:%M"),
            "arrival": arrive_dt.strftime("%Y-%m-%d %H:%M"),
            "duration": f"{duration_minutes // 60}h {duration_minutes % 60}m",
            "price_inr": price * passengers,
            "stops": "Non-stop",
            "baggage": "15 kg check-in, 7 kg cabin"
        })
    
    flights.sort(key=lambda x: x["price_inr"])
    
    return {
        "status": "success",
        "search_route": f"{origin.title()} to {destination.title()}",
        "departure_date": departure_date,
        "passengers": passengers,
        "flights_found": len(flights),
        "flights": flights
    }


def search_hotels(destination, check_in, check_out, guests=2):
    """Generate realistic hotel options."""
    
    dest_key = destination.lower().strip()
    hotels_data = HOTELS_BY_DESTINATION.get(dest_key, HOTELS_BY_DESTINATION["default"])
    
    nights = (datetime.strptime(check_out, "%Y-%m-%d") - datetime.strptime(check_in, "%Y-%m-%d")).days
    nights = max(1, nights)
    
    hotels = []
    selected_hotels = random.sample(hotels_data, min(4, len(hotels_data)))
    
    amenities_pool = [
        "Free WiFi", "Pool", "Spa", "Gym", "Restaurant", "Bar",
        "Room Service", "Free Breakfast", "Parking", "Airport Shuttle",
        "Concierge", "Beach Access", "Mountain View", "Lake View", "Garden"
    ]
    
    for hotel_info in selected_hotels:
        nightly_price = random.randint(*hotel_info["price_range"])
        num_amenities = 7 if hotel_info["rating"] >= 4.5 else 5
        amenities = random.sample(amenities_pool, num_amenities)
        
        hotels.append({
            "name": hotel_info["name"],
            "type": hotel_info["type"],
            "rating": hotel_info["rating"],
            "review_score": round(hotel_info["rating"] * 2 - 0.3, 1),
            "price_per_night_inr": nightly_price,
            "total_price_inr": nightly_price * nights,
            "nights": nights,
            "amenities": amenities,
            "location": destination.title(),
            "cancellation": "Free cancellation until 24h before check-in"
        })
    
    hotels.sort(key=lambda x: x["price_per_night_inr"])
    
    return {
        "status": "success",
        "destination": destination.title(),
        "check_in": check_in,
        "check_out": check_out,
        "nights": nights,
        "guests": guests,
        "hotels_found": len(hotels),
        "hotels": hotels
    }


def check_weather(destination, date):
    """Get weather forecast (simulated based on seasonal patterns)."""
    
    dest_key = destination.lower().strip()
    weather_info = WEATHER_PATTERNS.get(dest_key, WEATHER_PATTERNS["default"])
    season = get_season(date)
    pattern = weather_info[season]
    
    temp = random.randint(*pattern["temp"])
    rain_chance = pattern["rain_chance"] + random.randint(-10, 10)
    rain_chance = max(0, min(100, rain_chance))
    
    if rain_chance > 60:
        recommendation = "Pack rain gear and waterproof shoes"
    elif rain_chance > 30:
        recommendation = "Light rain possible — carry an umbrella"
    elif temp > 30:
        recommendation = "Pack light cottons and sunscreen"
    elif temp < 10:
        recommendation = "Pack warm clothing and jackets"
    else:
        recommendation = "Pleasant weather expected — pack regular clothing"
    
    return {
        "status": "success",
        "destination": destination.title(),
        "date": date,
        "season": season,
        "temperature_celsius": temp,
        "conditions": pattern["conditions"],
        "rain_probability_percent": rain_chance,
        "recommendation": recommendation
    }


def create_booking(flight_details, hotel_details, total_price_inr, traveler_name="Guest"):
    """Create a mock booking confirmation."""
    
    booking_id = f"VYG-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    
    return {
        "status": "CONFIRMED",
        "booking_id": booking_id,
        "traveler_name": traveler_name,
        "flight": flight_details,
        "hotel": hotel_details,
        "total_paid_inr": total_price_inr,
        "payment_method": "Demo Payment (Simulated)",
        "confirmation_email": "Itinerary sent to your email",
        "support_contact": "support@voyageagent.com",
        "message": f"Booking {booking_id} confirmed! Have an amazing trip."
    }


# ============================================================
# TOOL DISPATCHER
# ============================================================

def execute_tool(tool_name, tool_input):
    """
    Routes tool calls to the right function with caching.
    Cache flow: Check cache -> Run tool if miss -> Save result to cache
    """
    from cache import get_cached, set_cached
    
    # Check cache first
    cached_result = get_cached(tool_name, tool_input)
    if cached_result is not None:
        print(f"   Cache HIT - instant response")
        return cached_result
    
    # Cache miss - run the actual tool
    tool_map = {
        "search_flights": search_flights,
        "search_hotels": search_hotels,
        "check_weather": check_weather,
        "create_booking": create_booking,
    }
    
    if tool_name not in tool_map:
        return {"error": f"Unknown tool: {tool_name}"}
    
    try:
        result = tool_map[tool_name](**tool_input)
        
        # Save successful result to cache
        if "error" not in result:
            set_cached(tool_name, tool_input, result)
        
        return result
    except Exception as e:
        return {"error": str(e), "tool": tool_name}
