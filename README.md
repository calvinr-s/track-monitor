# Track Monitor

Discord bot that monitors Australian horse racing odds and calculates EV% for 2nd/3rd place promotions.

## Features

- Fetches odds from multiple bookmakers in parallel:
  - **Betfair** - Exchange back/lay odds (WIN and PLACE markets)
  - **Sportsbet** - Fixed odds
  - **Amused** - Fixed odds
  - **Pointsbet** - Fixed odds

- Calculates EV% for "Promo 2nd/3rd" (stake back as SNR bonus bet if horse runs 2nd or 3rd)

- Displays results in formatted Discord embeds with color-coded EV values

## Installation

1. Install dependencies:
```bash
pip install discord.py aiohttp
```

2. Set your Discord bot token in `config.py`:
```python
DISCORD_TOKEN = "your_token_here"
```

3. Run the bot:
```bash
python bot.py
```

## Usage

In Discord, type:
```
next 2/3
```

The bot will:
1. Find the next Australian horse race
2. Fetch odds from all bookmakers in parallel
3. Calculate EV% for each horse at each bookmaker
4. Display results in a formatted table

## EV Calculation

The EV formula for 2nd/3rd promo:

```
EV = p1 * B + p2or3 * q - 1
```

Where:
- `p1 = 1/Lw` - Win probability (from Betfair lay odds)
- `p_place = 1/Lp` - Place probability (from Betfair lay odds)
- `p2or3 = max(p_place - p1, 0)` - Probability of 2nd or 3rd
- `q = 0.70` - Retention factor (70% of bonus bet value)
- `B` - Bookmaker win odds

## File Structure

```
Track Monitor/
├── bot.py                 # Discord bot entry point
├── config.py              # Configuration settings
├── README.md
└── racing/
    ├── __init__.py
    ├── aggregator.py      # Race matching and EV calculation
    ├── formatting.py      # Discord embed formatting
    └── sources/
        ├── __init__.py
        ├── betfair.py     # Betfair Exchange API
        ├── sportsbet.py   # Sportsbet API
        ├── amused.py      # Amused (Blackstream) API
        └── pointsbet.py   # Pointsbet API
```

## Testing Individual Sources

Each source can be tested independently:

```bash
python -m racing.sources.betfair
python -m racing.sources.sportsbet
python -m racing.sources.amused
python -m racing.sources.pointsbet
```

Test the aggregator:
```bash
python -m racing.aggregator
```

## Configuration

Edit `config.py` to customize:

- `DISCORD_TOKEN` - Your Discord bot token
- `BETFAIR_API_KEY` - Betfair API key (default provided)
- `RETENTION_FACTOR` - Bonus bet retention (default 0.70 = 70%)
- `SCRAPE_TIMEOUT` - HTTP request timeout in seconds
- `COMMAND_COOLDOWN` - Cooldown between commands per user
