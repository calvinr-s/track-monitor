"""
Configuration for the Racing Discord Bot
"""

import os

# Discord Bot Token
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")

# Betfair API Key
BETFAIR_API_KEY = os.environ.get("BETFAIR_API_KEY", "")

# Google Sheets credentials file path
GOOGLE_CREDS_FILE = os.environ.get("GOOGLE_CREDS_FILE", "")

# Google Sheets spreadsheet ID
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "17OSxgYrYVe96lM5jNeuDKbYKqKTHTLQWDW009D0rxbc")

# EV Calculation Settings
RETENTION_FACTOR = 0.70  # q = 70% - cash value per $1 bonus bet

# Betfair commission rates by state (racing)
BETFAIR_COMMISSION = {
    'NSW': 0.10,  # 10%
    'ACT': 0.10,  # 10%
    'VIC': 0.08,  # 8%
    'QLD': 0.08,  # 8%
    'SA': 0.08,   # 8%
    'WA': 0.08,   # 8%
    'TAS': 0.08,  # 8%
    'NT': 0.08,   # 8%
    'default': 0.08,  # Default 8% for unknown/international
}

# Request timeout for each bookmaker (seconds)
SCRAPE_TIMEOUT = 5.0

# Command cooldown (seconds)
COMMAND_COOLDOWN = 5

# Supported bookmakers
SUPPORTED_BOOKMAKERS = [
    "sportsbet",
    "amused",
    "pointsbet",
]

# Time tolerance for race matching (seconds)
RACE_MATCH_TOLERANCE = 300  # 5 minutes

# Minimum EV% to display
MIN_EV_PERCENT = 0.0

# Residential proxy for Betfair (optional - set to None to disable)
PROXY_URL = os.environ.get("PROXY_URL", None)
