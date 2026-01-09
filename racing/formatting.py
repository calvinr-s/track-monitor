"""
Discord embed formatting for race data
"""

import re
from typing import Dict, List, Optional
from datetime import datetime, timezone

# Country code mapping for display
COUNTRY_NAMES = {
    'AU': 'AUS',
    'NZ': 'NZ',
    'GB': 'UK',
    'IE': 'IRE',
    'FR': 'FRA',
    'ZA': 'RSA',
}

# Bookmaker display order
BOOKIE_ORDER = [
    'amused',
    'betr',
    'pointsbet',
    'sportsbet',
]

# Bookmaker display names (all padded to same length for consistency)
BOOKIE_NAMES = {
    'amused': 'Amused',
    'betr': 'Betr',
    'pointsbet': 'PointsBet',
    'sportsbet': 'SportsBet',
}

# ANSI color codes for Discord code blocks
ANSI_RESET = "\u001b[0m"
ANSI_RED = "\u001b[0;31m"
ANSI_GREEN = "\u001b[0;32m"
ANSI_YELLOW = "\u001b[0;33m"
ANSI_BLUE = "\u001b[0;34m"
ANSI_MAGENTA = "\u001b[0;35m"
ANSI_CYAN = "\u001b[0;36m"
ANSI_LIGHT_BLUE = "\u001b[1;34m"  # Bright blue
ANSI_ORANGE = "\u001b[0;33m"  # Yellow/Orange (ANSI doesn't have true orange)

BOOKIE_COLORS = {
    'amused': ANSI_MAGENTA,
    'betr': ANSI_BLUE,        # Dark blue
    'pointsbet': ANSI_RED,
    'sportsbet': ANSI_CYAN,   # Light blue/cyan (#3CDFF-ish)
}

# Column widths (fixed for consistent alignment)
COL_BOOKIE = 9   # Bookie name
COL_NUM = 2      # Horse number
COL_EV = 6       # EV percentage (e.g., "+15 %" or " -5 %")
COL_ODDS = 6     # Back/Lay odds
COL_LIQ = 5      # Liquidity


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from string to get visual length"""
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text)


def _visual_len(text: str) -> int:
    """Get the visual display length of a string (excluding ANSI codes)"""
    return len(_strip_ansi(text))


def _pad_right(text: str, width: int) -> str:
    """Pad string to width, accounting for ANSI codes"""
    visual = _visual_len(text)
    padding = max(0, width - visual)
    return text + ' ' * padding


def _pad_left(text: str, width: int) -> str:
    """Right-align string to width, accounting for ANSI codes"""
    visual = _visual_len(text)
    padding = max(0, width - visual)
    return ' ' * padding + text


def _colorize(text: str, color: str) -> str:
    """Wrap text in ANSI color codes"""
    return f"{color}{text}{ANSI_RESET}"


def _format_ev(ev_pct: Optional[float]) -> str:
    """
    Format EV percentage with color coding.
    Returns fixed-width string (6 chars visual) with color.

    Color rules:
    - EV <= 0: Red
    - 0 < EV <= 10: Orange/Yellow
    - EV > 10: Green
    """
    if ev_pct is None:
        return _pad_left("-", COL_EV)

    ev_int = round(ev_pct)

    # Determine color based on EV value
    if ev_int <= 0:
        color = ANSI_RED
    elif ev_int <= 10:
        color = ANSI_ORANGE
    else:
        color = ANSI_GREEN

    # Format: "+15 %" or " -5 %" (always 6 chars visual)
    if ev_int >= 0:
        ev_text = f"+{ev_int}%"
    else:
        ev_text = f"{ev_int}%"

    # Pad to fixed width, then colorize
    padded = _pad_left(ev_text, COL_EV)
    return _colorize(padded, color)


def _format_odds(odds: Optional[float]) -> str:
    """
    Format odds value, right-aligned to COL_ODDS width.
    Handles decimal alignment by using consistent formatting.
    """
    if odds is None:
        return _pad_left("-", COL_ODDS)

    if odds >= 100:
        text = f"{odds:.0f}"
    elif odds >= 10:
        text = f"{odds:.1f}"
    else:
        text = f"{odds:.2f}"

    return _pad_left(text, COL_ODDS)


def _format_liquidity(liq: Optional[float]) -> str:
    """
    Format liquidity value, right-aligned to COL_LIQ width.
    Shows as integer with $ prefix.
    """
    if liq is None:
        return _pad_left("-", COL_LIQ)

    if liq >= 1000:
        text = f"${liq/1000:.0f}k"
    else:
        text = f"${liq:.0f}"

    return _pad_left(text, COL_LIQ)


def _format_horse_num(num: Optional[int]) -> str:
    """Format horse number, right-aligned"""
    if num is None:
        return _pad_left("-", COL_NUM)
    return _pad_left(str(num), COL_NUM)


def _format_bookie_name(bookie_key: str) -> str:
    """Format bookmaker name with color, left-aligned to fixed width"""
    name = BOOKIE_NAMES.get(bookie_key, bookie_key.title())
    color = BOOKIE_COLORS.get(bookie_key, '')

    # Pad name first (without color), then apply color
    padded_name = _pad_right(name, COL_BOOKIE)

    if color:
        return _colorize(padded_name, color)
    return padded_name


def format_race_embed(race_data: Dict) -> Dict:
    """
    Format race data into a Discord embed structure.
    Returns dict with 'description' and 'color'.
    """
    venue = race_data['venue']
    race_num = race_data['race_number']
    seconds_until = race_data.get('seconds_until_start', 0)
    country_code = race_data.get('country_code', 'AU')
    runners = race_data['runners']

    # Format countdown
    countdown_str = _format_countdown(seconds_until)

    # Format venue with country code for international
    if country_code != 'AU':
        country_display = COUNTRY_NAMES.get(country_code, country_code)
        venue_str = f"[{country_display}] {venue}"
    else:
        venue_str = venue

    # Get promo type
    promo = race_data.get('promo', '2/3')

    # Build the bookmaker-centric table
    table = format_bookie_table(
        runners=runners,
        countdown_str=countdown_str,
        venue=venue_str,
        race_no=race_num,
        runner_count=len(runners),
        promo=promo
    )

    # Determine embed color based on best EV
    best_ev = _find_best_ev(runners)
    if best_ev is None or best_ev <= 0:
        color = 0x808080  # Grey - no positive EV
    elif best_ev > 10:
        color = 0x00FF00  # Green - strong EV
    else:
        color = 0xFFA500  # Orange - moderate EV

    return {
        'title': None,
        'description': table,
        'color': color
    }


PROMO_NAMES = {
    '2/3': 'Promo 2nd/3rd',
    'free_hit': 'Promo Free Hit',
    'bonus': 'SNR Bonus Bet',
}


def format_bookie_table(runners: List[Dict], countdown_str: str, venue: str, race_no: int, runner_count: int, promo: str = "2/3", fetched_at: Optional[datetime] = None) -> str:
    """
    Build bookmaker-centric table with perfect column alignment.
    """
    # Set threshold based on promo type
    if promo == "bonus":
        ev_threshold = 30  # Only show 30%+ retention for bonus bets
    else:
        ev_threshold = -10  # Show -10%+ EV for other promos

    # Build rows: {bookie, horse_no, ev_pct, back_odds, lay_odds}
    rows = []

    for runner in runners:
        horse_no = runner.get('horse_number')
        lay_win = runner.get('lay_win')
        lay_liq = runner.get('lay_win_size')

        # Check each bookmaker
        for bookie_key in BOOKIE_ORDER:
            bookie_data = runner.get(bookie_key, {})
            ev = bookie_data.get('ev')
            back_odds = bookie_data.get('odds')

            # Include only if we have EV calculated and it's above threshold
            if ev is not None and ev >= ev_threshold:
                rows.append({
                    'bookie': bookie_key,
                    'horse_no': horse_no,
                    'ev_pct': ev,
                    'back_odds': back_odds,
                    'lay_odds': lay_win,
                    'lay_liq': lay_liq
                })

    # Sort by bookmaker order, then by EV descending
    def sort_key(row):
        try:
            bookie_idx = BOOKIE_ORDER.index(row['bookie'])
        except ValueError:
            bookie_idx = 999
        ev = row['ev_pct'] if row['ev_pct'] is not None else -999
        return (bookie_idx, -ev)

    rows.sort(key=sort_key)

    # Build output lines
    lines = []

    # Header info
    lines.append(f"{countdown_str}  {venue} R{race_no} ({runner_count})")
    lines.append("")
    lines.append(PROMO_NAMES.get(promo, f"Promo {promo}"))
    lines.append("")

    if not rows:
        if promo == "bonus":
            lines.append("No opportunities found (Retention > 30%).")
        else:
            lines.append("No opportunities found (EV > -10%).")
    else:
        # Column headers (matching the data column widths)
        ev_label = "Ret %" if promo == "bonus" else "EV %"
        header = (
            f"{_pad_right('Bookie', COL_BOOKIE)} "
            f"{_pad_left('No', COL_NUM)}  "
            f"{_pad_left(ev_label, COL_EV)}  "
            f"{_pad_left('Back', COL_ODDS)}  "
            f"{_pad_left('Lay', COL_ODDS)}  "
            f"{_pad_left('Liq', COL_LIQ)}"
        )
        lines.append(header)

        # Separator line (matches total width)
        total_width = COL_BOOKIE + 1 + COL_NUM + 2 + COL_EV + 2 + COL_ODDS + 2 + COL_ODDS + 2 + COL_LIQ
        lines.append("-" * total_width)

        # Data rows grouped by bookmaker
        current_bookie = None
        for row in rows:
            # Add blank line between bookmaker groups
            if current_bookie is not None and row['bookie'] != current_bookie:
                lines.append("")
            current_bookie = row['bookie']

            # Format each column
            bookie_col = _format_bookie_name(row['bookie'])
            num_col = _format_horse_num(row['horse_no'])
            ev_col = _format_ev(row['ev_pct'])
            back_col = _format_odds(row['back_odds'])
            lay_col = _format_odds(row['lay_odds'])
            liq_col = _format_liquidity(row['lay_liq'])

            # Assemble row with consistent spacing
            line = f"{bookie_col} {num_col}  {ev_col}  {back_col}  {lay_col}  {liq_col}"
            lines.append(line)

    # Add timestamp footer
    if fetched_at:
        # Convert to local Sydney time for display
        import pytz
        sydney_tz = pytz.timezone('Australia/Sydney')
        local_time = fetched_at.astimezone(sydney_tz)
        lines.append("")
        lines.append(f"Fetched: {local_time.strftime('%H:%M:%S')}")

    return "```ansi\n" + "\n".join(lines) + "\n```"


def _format_countdown(seconds: float) -> str:
    """Format seconds into 0h 0m 0s format"""
    if seconds < 0:
        return "Started"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    return f"{hours}h {minutes}m {secs}s"


def _find_best_ev(runners: List[Dict]) -> Optional[float]:
    """Find the best EV value across all runners and bookmakers"""
    best = None
    for runner in runners:
        for bookie in BOOKIE_ORDER:
            bookie_data = runner.get(bookie, {})
            ev = bookie_data.get('ev')
            if ev is not None:
                if best is None or ev > best:
                    best = ev
    return best


def format_error_embed(message: str) -> Dict:
    """Format an error message embed"""
    return {
        'title': 'Error',
        'description': message,
        'color': 0xFF0000
    }


def format_no_race_embed(international: bool = False) -> Dict:
    """Format a 'no races found' embed"""
    region = "international" if international else "Australian"
    return {
        'title': 'No Races Found',
        'description': f'No upcoming {region} horse races found.',
        'color': 0x808080
    }
