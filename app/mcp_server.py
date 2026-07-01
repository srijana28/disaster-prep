# ruff: noqa
import asyncio
import sys
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Initialize server
app = Server("disaster-prep-mcp")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="get_hazard_warnings",
            description="Get current active hazards and severity level (e.g. Flood, Wildfire, Storm) for a specific city or area.",
            inputSchema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The city, zip code, or area to check for hazards."}
                },
                "required": ["location"]
            }
        ),
        Tool(
            name="get_shelters",
            description="Get a list of emergency shelters, their address, distance, capacity, and current occupancy near a location.",
            inputSchema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The location to search for shelters near."}
                },
                "required": ["location"]
            }
        ),
        Tool(
            name="get_weather_conditions",
            description="Get current weather details (wind speed, visibility, rain, temperature) that might impact evacuation routes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "The location to check weather conditions for."}
                },
                "required": ["location"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Stdio transport requires that logs go to stderr to prevent corrupting stdout
    print(f"Calling tool: {name} with args {arguments}", file=sys.stderr)
    location = arguments.get("location", "unknown location")
    
    if name == "get_hazard_warnings":
        if "san francisco" in location.lower() or "sf" in location.lower() or "941" in location:
            result = {
                "location": location,
                "active_hazards": [
                    {"type": "Flood Warning", "severity": "High", "details": "Coastal flooding and high surf advisory."},
                    {"type": "High Winds", "severity": "Medium", "details": "Winds up to 45 mph."}
                ]
            }
        elif "los angeles" in location.lower() or "la" in location.lower():
            result = {
                "location": location,
                "active_hazards": [
                    {"type": "Wildfire Warning", "severity": "Critical", "details": "Red Flag warning in nearby canyons."}
                ]
            }
        else:
            result = {
                "location": location,
                "active_hazards": [
                    {"type": "Heavy Rain", "severity": "Low", "details": "Potential for slick roads."}
                ]
            }
        return [TextContent(type="text", text=json.dumps(result))]
        
    elif name == "get_shelters":
        if "san francisco" in location.lower() or "sf" in location.lower() or "941" in location:
            result = {
                "location": location,
                "shelters": [
                    {"name": "Civic Center Auditorium", "address": "99 Grove St, San Francisco", "capacity": 500, "occupancy": 350, "status": "Open"},
                    {"name": "Sunset Recreation Center", "address": "2201 Lawton St, San Francisco", "capacity": 200, "occupancy": 80, "status": "Open"}
                ]
            }
        else:
            result = {
                "location": location,
                "shelters": [
                    {"name": "Community High School Shelter", "address": "100 Main St, Local", "capacity": 300, "occupancy": 120, "status": "Open"}
                ]
            }
        return [TextContent(type="text", text=json.dumps(result))]
        
    elif name == "get_weather_conditions":
        if "san francisco" in location.lower() or "sf" in location.lower() or "941" in location:
            result = {
                "location": location,
                "wind_speed_mph": 28,
                "visibility_miles": 2,
                "rain_inches": 1.5,
                "temperature_f": 58
            }
        else:
            result = {
                "location": location,
                "wind_speed_mph": 12,
                "visibility_miles": 10,
                "rain_inches": 0.1,
                "temperature_f": 72
            }
        return [TextContent(type="text", text=json.dumps(result))]
        
    else:
        raise ValueError(f"Tool not found: {name}")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
