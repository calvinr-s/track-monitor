"""
EV Tracker - Logs best EV opportunities to Google Sheets and tracks results
"""

import asyncio
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from zoneinfo import ZoneInfo
import os
import sys

sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')
from config import RETENTION_FACTOR, BETFAIR_COMMISSION, GOOGLE_CREDS_FILE, SPREADSHEET_ID

# Sheet names
SHEETS = {
    "2/3-1min": "2/3-1min",
    "2/3-30s": "2/3-30s",
    "FreeHit-1min": "FreeHit-1min",
    "FreeHit-30s": "FreeHit-30s",
}

# Column headers
HEADERS = [
    "Date",
    "Time",
    "Venue",
    "Race",
    "Horse",
    "Bookie",
    "Back",
    "Lay",
    "EV% No Lay",
    "EV% Half Lay",
    "EV% Full Lay",
    "Result",
    "P/L No Lay",
    "P/L Half Lay",
    "P/L Full Lay",
    "Cum No Lay",
    "Cum Half Lay",
    "Cum Full Lay",
]

# Bookmaker list
BOOKIES = ['amused', 'betr', 'boombet', 'palmerbet', 'playup', 'pointsbet', 'sportsbet', 'tab']

SYDNEY_TZ = ZoneInfo('Australia/Sydney')


class EVTracker:
    """Tracks EV opportunities and logs to Google Sheets"""

    def __init__(self):
        self.gc = None
        self.spreadsheet = None
        self._tracked_races = {}  # {race_key: {'1min': logged, '30s': logged}}

    def _get_client(self):
        """Get or create gspread client"""
        if self.gc is None:
            if not GOOGLE_CREDS_FILE:
                raise ValueError("GOOGLE_CREDS_FILE environment variable not set")
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive'
            ]
            creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
            self.gc = gspread.authorize(creds)
        return self.gc

    def _get_spreadsheet(self):
        """Get or open spreadsheet"""
        if self.spreadsheet is None:
            client = self._get_client()
            self.spreadsheet = client.open_by_key(SPREADSHEET_ID)
        return self.spreadsheet

    def ensure_sheets_exist(self):
        """Create sheets if they don't exist, with headers"""
        spreadsheet = self._get_spreadsheet()
        existing = [ws.title for ws in spreadsheet.worksheets()]

        for sheet_name in SHEETS.values():
            if sheet_name not in existing:
                ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(HEADERS))
                ws.append_row(HEADERS)
                print(f"[TRACKER] Created sheet: {sheet_name}")
            else:
                # Check if headers exist and resize if needed
                ws = spreadsheet.worksheet(sheet_name)
                try:
                    # Resize to ensure enough columns for cumulative totals
                    if ws.col_count < len(HEADERS):
                        ws.resize(cols=len(HEADERS))
                        print(f"[TRACKER] Resized {sheet_name} to {len(HEADERS)} columns")

                    first_row = ws.row_values(1)
                    if not first_row or first_row[0] != "Date":
                        ws.insert_row(HEADERS, 1)
                        print(f"[TRACKER] Added headers to: {sheet_name}")
                    elif len(first_row) < len(HEADERS):
                        # Update headers to include new columns
                        ws.update('A1', [HEADERS])
                        print(f"[TRACKER] Updated headers for: {sheet_name}")
                except:
                    ws.append_row(HEADERS)

    def _get_race_key(self, race_data: Dict) -> str:
        """Generate unique key for a race"""
        return f"{race_data['venue']}_R{race_data['race_number']}_{race_data['start_time'].strftime('%Y%m%d%H%M')}"

    def _find_best_ev(self, runners: List[Dict], promo: str) -> Optional[Dict]:
        """
        Find the single best EV opportunity across all runners and bookmakers.
        Returns dict with horse info, bookie, odds, and EV values for all lay modes.
        """
        best = None
        best_ev = -999

        for runner in runners:
            horse_num = runner.get('horse_number')
            horse_name = runner.get('horse_name', 'Unknown')
            lay_win = runner.get('lay_win')
            lay_place = runner.get('lay_place')

            for bookie in BOOKIES:
                bookie_data = runner.get(bookie, {})
                ev = bookie_data.get('ev')
                odds = bookie_data.get('odds')

                if ev is not None and ev > best_ev and odds is not None:
                    best_ev = ev
                    best = {
                        'horse_number': horse_num,
                        'horse_name': horse_name,
                        'bookie': bookie,
                        'back_odds': odds,
                        'lay_win': lay_win,
                        'lay_place': lay_place,
                    }

        if best:
            # Calculate EV for all lay modes
            if promo == "free_hit":
                best['ev_no_lay'] = self._calc_ev_free_hit(best['back_odds'], best['lay_win'], "no_lay")
                best['ev_half_lay'] = self._calc_ev_free_hit(best['back_odds'], best['lay_win'], "half_lay")
                best['ev_full_lay'] = self._calc_ev_free_hit(best['back_odds'], best['lay_win'], "lay")
            else:  # 2/3
                best['ev_no_lay'] = self._calc_ev_2nd3rd(best['back_odds'], best['lay_win'], best['lay_place'], "no_lay")
                best['ev_half_lay'] = self._calc_ev_2nd3rd(best['back_odds'], best['lay_win'], best['lay_place'], "half_lay")
                best['ev_full_lay'] = self._calc_ev_2nd3rd(best['back_odds'], best['lay_win'], best['lay_place'], "lay")

        return best

    def _calc_ev_2nd3rd(self, back: float, lay_win: float, lay_place: float, lay_mode: str, commission: float = 0.08) -> Optional[float]:
        """Calculate EV for 2nd/3rd promo"""
        if not back or not lay_win or not lay_place:
            return None
        try:
            p1 = 1 / lay_win
            p_place = 1 / lay_place
            p2or3 = max(p_place - p1, 0)
            ev = p1 * back + p2or3 * RETENTION_FACTOR - 1
            if lay_mode == "lay":
                commission_cost = (1 - p1) * commission * (back - 1) / lay_win
                ev -= commission_cost
            elif lay_mode == "half_lay":
                commission_cost = (1 - p1) * commission * (back - 1) / lay_win
                ev -= commission_cost / 2
            return ev * 100
        except:
            return None

    def _calc_ev_free_hit(self, back: float, lay_win: float, lay_mode: str, commission: float = 0.08) -> Optional[float]:
        """Calculate EV for Free Hit promo"""
        if not back or not lay_win:
            return None
        try:
            p_win = 1 / lay_win
            p_lose = 1 - p_win
            ev = p_win * back + p_lose * RETENTION_FACTOR - 1
            if lay_mode == "lay":
                commission_cost = p_lose * commission * (back - 1) / lay_win
                ev -= commission_cost
            elif lay_mode == "half_lay":
                commission_cost = p_lose * commission * (back - 1) / lay_win
                ev -= commission_cost / 2
            return ev * 100
        except:
            return None

    def log_opportunity(self, race_data: Dict, timing: str):
        """
        Log the best EV opportunity to the appropriate sheet.

        Args:
            race_data: Race data from aggregator
            timing: "1min" or "30s"
        """
        promo = race_data.get('promo', '2/3')

        # Determine sheet name
        if promo == "free_hit":
            sheet_name = f"FreeHit-{timing}"
        else:
            sheet_name = f"2/3-{timing}"

        # Check if already logged
        race_key = self._get_race_key(race_data)
        if race_key not in self._tracked_races:
            self._tracked_races[race_key] = {'1min': False, '30s': False}

        if self._tracked_races[race_key].get(timing):
            return  # Already logged

        # Find best opportunity
        best = self._find_best_ev(race_data['runners'], promo)
        if not best:
            print(f"[TRACKER] No valid opportunity for {race_data['venue']} R{race_data['race_number']}")
            return

        # Prepare row
        now = datetime.now(SYDNEY_TZ)
        start_time = race_data['start_time']
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        local_start = start_time.astimezone(SYDNEY_TZ)

        row = [
            local_start.strftime('%Y-%m-%d'),  # Date
            local_start.strftime('%H:%M'),     # Time
            race_data['venue'],                # Venue
            race_data['race_number'],          # Race
            f"#{best['horse_number']} {best['horse_name']}",  # Horse
            best['bookie'].title(),            # Bookie
            best['back_odds'],                 # Back
            best['lay_win'],                   # Lay
            round(best['ev_no_lay'], 1) if best['ev_no_lay'] else "",      # EV% No Lay
            round(best['ev_half_lay'], 1) if best['ev_half_lay'] else "",  # EV% Half Lay
            round(best['ev_full_lay'], 1) if best['ev_full_lay'] else "",  # EV% Full Lay
            "",  # Result (to be filled later)
            "",  # P/L No Lay
            "",  # P/L Half Lay
            "",  # P/L Full Lay
            "",  # Cum No Lay
            "",  # Cum Half Lay
            "",  # Cum Full Lay
        ]

        try:
            spreadsheet = self._get_spreadsheet()
            ws = spreadsheet.worksheet(sheet_name)
            ws.append_row(row)
            self._tracked_races[race_key][timing] = True
            print(f"[TRACKER] Logged to {sheet_name}: {race_data['venue']} R{race_data['race_number']} #{best['horse_number']} {best['bookie']} EV={best['ev_full_lay']:.1f}%")
        except Exception as e:
            print(f"[TRACKER] Error logging to sheet: {e}")

    def update_results(self, sheet_name: str, venue: str, race_num: int, date_str: str, position: int):
        """
        Update race result and calculate P/L.

        Args:
            sheet_name: Which sheet to update
            venue: Venue name
            race_num: Race number
            date_str: Date string YYYY-MM-DD
            position: Finishing position (1, 2, 3, or 0 for 4th+/loss)
        """
        try:
            spreadsheet = self._get_spreadsheet()
            ws = spreadsheet.worksheet(sheet_name)

            # Find the row
            data = ws.get_all_values()
            for i, row in enumerate(data[1:], start=2):  # Skip header
                if len(row) >= 8:
                    if row[0] == date_str and row[2] == venue and str(row[3]) == str(race_num):
                        # Found the row - update result and P/L
                        if position == 1:
                            result = "1st"
                        elif position == 2:
                            result = "2nd"
                        elif position == 3:
                            result = "3rd"
                        else:
                            result = "4th+"

                        # Get odds from row
                        back_odds = float(row[6]) if row[6] else 0
                        lay_odds = float(row[7]) if row[7] else 0
                        commission = 0.08  # Default commission

                        # Calculate lay stake ratio (B/L) for full lay
                        lay_ratio = back_odds / lay_odds if lay_odds > 0 else 0

                        # Calculate P/L based on promo type and position
                        is_free_hit = "FreeHit" in sheet_name

                        if is_free_hit:
                            # Free Hit: Win = back profit, Lose = bonus (0.70)
                            if position == 1:
                                # Win: back profit - lay loss
                                pl_no_lay = back_odds - 1
                                pl_half = (back_odds - 1) / 2 + (lay_ratio - 1) / 2
                                pl_full = lay_ratio - 1  # Small qualifying loss
                            else:
                                # Lose: get bonus worth 70%
                                pl_no_lay = RETENTION_FACTOR - 1  # -0.30
                                lay_profit = lay_ratio * (1 - commission)
                                pl_half = (RETENTION_FACTOR - 1) / 2 + (lay_profit - 1) / 2
                                pl_full = lay_profit - 1 + RETENTION_FACTOR
                        else:
                            # 2/3 Promo
                            if position == 1:
                                # 1st: back wins, lay loses
                                pl_no_lay = back_odds - 1
                                pl_half = (back_odds - 1) / 2 + (lay_ratio - 1) / 2
                                pl_full = lay_ratio - 1  # Small qualifying loss
                            elif position in (2, 3):
                                # 2nd/3rd: back loses, lay wins, get bonus
                                pl_no_lay = RETENTION_FACTOR - 1  # -0.30
                                lay_profit = lay_ratio * (1 - commission)
                                pl_half = (RETENTION_FACTOR - 1) / 2 + (lay_profit - 1) / 2
                                pl_full = lay_profit - 1 + RETENTION_FACTOR
                            else:
                                # 4th+: back loses, lay wins, no bonus
                                pl_no_lay = -1.0
                                lay_profit = lay_ratio * (1 - commission)
                                pl_half = -0.5 + (lay_profit - 1) / 2
                                pl_full = lay_profit - 1  # Small loss

                        # Update cells
                        ws.update_cell(i, 12, result)
                        ws.update_cell(i, 13, round(pl_no_lay, 2))
                        ws.update_cell(i, 14, round(pl_half, 2))
                        ws.update_cell(i, 15, round(pl_full, 2))

                        # Recalculate cumulative totals for this sheet
                        self._update_cumulative_totals(sheet_name)

                        print(f"[TRACKER] Updated result for {venue} R{race_num}: {result}")
                        return True

            print(f"[TRACKER] Race not found: {venue} R{race_num} on {date_str}")
            return False

        except Exception as e:
            print(f"[TRACKER] Error updating result: {e}")
            return False

    def _update_cumulative_totals(self, sheet_name: str):
        """Recalculate cumulative P/L totals for a sheet"""
        try:
            spreadsheet = self._get_spreadsheet()
            ws = spreadsheet.worksheet(sheet_name)
            data = ws.get_all_values()

            if len(data) <= 1:
                return

            # Calculate cumulative totals
            cum_no_lay = 0.0
            cum_half = 0.0
            cum_full = 0.0
            updates = []

            for i, row in enumerate(data[1:], start=2):
                if len(row) >= 15 and row[12]:  # Has P/L No Lay
                    try:
                        pl_no_lay = float(row[12]) if row[12] else 0
                        pl_half = float(row[13]) if row[13] else 0
                        pl_full = float(row[14]) if row[14] else 0

                        cum_no_lay += pl_no_lay
                        cum_half += pl_half
                        cum_full += pl_full

                        updates.append({
                            'range': f'P{i}:R{i}',
                            'values': [[round(cum_no_lay, 2), round(cum_half, 2), round(cum_full, 2)]]
                        })
                    except:
                        pass

            # Batch update all cumulative cells
            if updates:
                ws.batch_update(updates)

        except Exception as e:
            print(f"[TRACKER] Error updating cumulative totals: {e}")

    def get_stats(self, sheet_name: Optional[str] = None) -> Dict:
        """
        Get statistics from tracked races.

        Args:
            sheet_name: Specific sheet or None for all

        Returns:
            Stats dict with totals, averages, and P/L
        """
        try:
            spreadsheet = self._get_spreadsheet()
            sheets_to_check = [sheet_name] if sheet_name else list(SHEETS.values())

            stats = {
                'total_races': 0,
                'with_results': 0,
                'wins': 0,
                'places': 0,  # 2nd or 3rd
                'losses': 0,
                'avg_ev_no_lay': 0,
                'avg_ev_half_lay': 0,
                'avg_ev_full_lay': 0,
                'total_pl_no_lay': 0,
                'total_pl_half_lay': 0,
                'total_pl_full_lay': 0,
                'by_sheet': {}
            }

            ev_sums = {'no_lay': 0, 'half_lay': 0, 'full_lay': 0}
            ev_counts = {'no_lay': 0, 'half_lay': 0, 'full_lay': 0}

            for sn in sheets_to_check:
                try:
                    ws = spreadsheet.worksheet(sn)
                    data = ws.get_all_values()[1:]  # Skip header

                    sheet_stats = {
                        'races': len(data),
                        'with_results': 0,
                        'pl_no_lay': 0,
                        'pl_half_lay': 0,
                        'pl_full_lay': 0,
                    }

                    for row in data:
                        if len(row) >= 15:
                            stats['total_races'] += 1

                            # EV values
                            if row[8]:
                                ev_sums['no_lay'] += float(row[8])
                                ev_counts['no_lay'] += 1
                            if row[9]:
                                ev_sums['half_lay'] += float(row[9])
                                ev_counts['half_lay'] += 1
                            if row[10]:
                                ev_sums['full_lay'] += float(row[10])
                                ev_counts['full_lay'] += 1

                            # Results
                            if row[11]:  # Has result
                                stats['with_results'] += 1
                                sheet_stats['with_results'] += 1

                                if row[11] == "1st":
                                    stats['wins'] += 1
                                elif row[11] in ("2nd", "3rd"):
                                    stats['places'] += 1
                                else:
                                    stats['losses'] += 1

                                # P/L
                                if row[12]:
                                    pl = float(row[12])
                                    stats['total_pl_no_lay'] += pl
                                    sheet_stats['pl_no_lay'] += pl
                                if row[13]:
                                    pl = float(row[13])
                                    stats['total_pl_half_lay'] += pl
                                    sheet_stats['pl_half_lay'] += pl
                                if row[14]:
                                    pl = float(row[14])
                                    stats['total_pl_full_lay'] += pl
                                    sheet_stats['pl_full_lay'] += pl

                    stats['by_sheet'][sn] = sheet_stats

                except Exception as e:
                    print(f"[TRACKER] Error reading {sn}: {e}")

            # Calculate averages
            if ev_counts['no_lay']:
                stats['avg_ev_no_lay'] = ev_sums['no_lay'] / ev_counts['no_lay']
            if ev_counts['half_lay']:
                stats['avg_ev_half_lay'] = ev_sums['half_lay'] / ev_counts['half_lay']
            if ev_counts['full_lay']:
                stats['avg_ev_full_lay'] = ev_sums['full_lay'] / ev_counts['full_lay']

            return stats

        except Exception as e:
            print(f"[TRACKER] Error getting stats: {e}")
            return {'error': str(e)}

    def get_pending_results(self) -> List[Dict]:
        """Get list of races that need results updated"""
        try:
            spreadsheet = self._get_spreadsheet()
            pending = []

            for sheet_name in SHEETS.values():
                try:
                    ws = spreadsheet.worksheet(sheet_name)
                    data = ws.get_all_values()[1:]  # Skip header

                    for row in data:
                        if len(row) >= 12 and not row[11]:  # No result yet
                            # Check if race should be finished (more than 30 min ago)
                            try:
                                date_str = row[0]
                                time_str = row[1]
                                race_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                                race_dt = race_dt.replace(tzinfo=SYDNEY_TZ)

                                now = datetime.now(SYDNEY_TZ)
                                if (now - race_dt).total_seconds() > 900:  # 15 min
                                    pending.append({
                                        'sheet': sheet_name,
                                        'date': date_str,
                                        'time': time_str,
                                        'venue': row[2],
                                        'race': row[3],
                                        'horse': row[4],
                                    })
                            except:
                                pass
                except:
                    pass

            return pending

        except Exception as e:
            print(f"[TRACKER] Error getting pending: {e}")
            return []


# Singleton instance
_tracker = None

def get_tracker() -> EVTracker:
    """Get or create tracker instance"""
    global _tracker
    if _tracker is None:
        _tracker = EVTracker()
        _tracker.ensure_sheets_exist()
    return _tracker


async def test():
    """Test the tracker"""
    tracker = get_tracker()
    print("Tracker initialized")

    # Get stats
    stats = tracker.get_stats()
    print(f"Stats: {stats}")

    # Get pending results
    pending = tracker.get_pending_results()
    print(f"Pending results: {len(pending)}")


if __name__ == "__main__":
    asyncio.run(test())
