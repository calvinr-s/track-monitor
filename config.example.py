"""
Configuration for the Racing Discord Bot

Copy this file to config.py and fill in your values:
    cp config.example.py config.py
"""

# Discord Bot Token - get from https://discord.com/developers/applications
DISCORD_TOKEN = "YOUR_DISCORD_TOKEN_HERE"

# Betfair API Key - get from https://developer.betfair.com/
BETFAIR_API_KEY = "YOUR_BETFAIR_API_KEY_HERE"

# EV Calculation Settings
RETENTION_FACTOR = 0.70  # q = 70% - cash value per $1 bonus bet

# Betfair commission (for future use)
BETFAIR_COMMISSION = 0.05  # 5%

# Request timeout for each bookmaker (seconds)
SCRAPE_TIMEOUT = 5.0

# Command cooldown (seconds)
COMMAND_COOLDOWN = 5

# Supported bookmakers
SUPPORTED_BOOKMAKERS = [
    "sportsbet",
    "amused",
    "pointsbet",
    "betr",
]

# Time tolerance for race matching (seconds)
RACE_MATCH_TOLERANCE = 300  # 5 minutes

# Minimum EV% to display
MIN_EV_PERCENT = 0.0
