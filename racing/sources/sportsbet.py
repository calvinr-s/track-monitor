"""
Sportsbet data source - provides win odds
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')


class SportsbetSource:
    """Sportsbet bookmaker data source"""

    MEETINGS_URL = "https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing/AllRacing"
    MARKETS_URL = "https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing/Events/{event_id}/Markets"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'application/json'
    }

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.HEADERS)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_meetings(self, date: str = None, international: bool = False) -> List[Dict]:
        """
        Fetch horse racing meetings for a date
        Args:
            date: Date string YYYY-MM-DD (defaults to today)
            international: If True, fetch all countries. If False, only Australia.
        """
        if date is None:
            now = datetime.now(timezone.utc)
            date = now.strftime("%Y-%m-%d")

        url = f"{self.MEETINGS_URL}/{date}"
        session = await self._get_session()

        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"Sportsbet meetings error: {e}")
            return []

        meetings = []
        for date_obj in data.get('dates', []):
            for section in date_obj.get('sections', []):
                if section.get('raceType') != 'horse':
                    continue

                for meeting in section.get('meetings', []):
                    # Filter by region unless international
                    if not international and meeting.get('regionName') != 'Australia':
                        continue

                    venue = meeting.get('name', 'Unknown')
                    class_id = meeting.get('classId', 1)

                    races = []
                    for event in meeting.get('events', []):
                        # Parse start time from epoch
                        start_epoch = event.get('startTime')
                        start_time = None
                        if start_epoch:
                            start_time = datetime.fromtimestamp(start_epoch, tz=timezone.utc)

                        races.append({
                            'event_id': event.get('id'),
                            'race_number': event.get('raceNumber'),
                            'race_name': event.get('name'),
                            'start_time': start_time,
                            'class_id': class_id,
                            'status': event.get('bettingStatus')
                        })

                    meetings.append({
                        'venue': venue,
                        'races': races
                    })

        return meetings

    async def get_race_odds(self, event_id: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds
        """
        url = self.MARKETS_URL.format(event_id=event_id)
        session = await self._get_session()

        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                markets = await resp.json()
        except Exception as e:
            print(f"Sportsbet odds error: {e}")
            return {}

        result = {
            'event_id': event_id,
            'runners': {}
        }

        # Find Win or Place market
        for market in markets:
            market_name = market.get('name', '')
            if market_name in ['Win or Place', 'Win']:
                for selection in market.get('selections', []):
                    horse_number = selection.get('runnerNumber')
                    horse_name = selection.get('name', 'Unknown')
                    is_scratched = selection.get('isOut', False)

                    # Find the win price with priceCode "L" (live/fixed odds)
                    win_odds = None
                    for price in selection.get('prices', []):
                        if price.get('priceCode') == 'L':
                            win_odds = price.get('winPrice')
                            break

                    if horse_number:
                        result['runners'][horse_number] = {
                            'horse_number': horse_number,
                            'horse_name': horse_name,
                            'win_odds': win_odds,
                            'scratched': is_scratched
                        }

                break  # Only need first matching market

        return result

    async def find_race(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Optional[Dict]:
        """
        Find a specific race by venue and start time.
        Matches by time (within 5 min tolerance) since race numbers can differ between sources.
        """
        today = start_time.strftime("%Y-%m-%d")
        meetings = await self.get_meetings(today, international=international)

        for meeting in meetings:
            # Normalize venue names for matching
            meeting_venue = meeting['venue'].lower().replace(' ', '')
            search_venue = venue.lower().replace(' ', '')

            if meeting_venue not in search_venue and search_venue not in meeting_venue:
                continue

            # Find race with closest start time within tolerance
            best_match = None
            best_diff = 300  # 5 minutes tolerance

            for race in meeting['races']:
                if race['start_time']:
                    time_diff = abs((race['start_time'] - start_time).total_seconds())
                    if time_diff <= best_diff:
                        best_diff = time_diff
                        best_match = {
                            'event_id': race['event_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time']
                        }

            if best_match:
                return best_match

        return None

    async def get_race_results(self, event_id: str) -> Optional[Dict]:
        """
        Fetch race results for a completed race.
        Returns dict mapping horse_number to result code (W=win, P=place, L=lose)
        """
        url = self.MARKETS_URL.format(event_id=event_id)
        session = await self._get_session()

        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                markets = await resp.json()
        except Exception as e:
            print(f"Sportsbet results error: {e}")
            return None

        results = {}
        for market in markets:
            if market.get('name') in ['Win or Place', 'Win']:
                status = market.get('statusCode')
                if status != 'S':  # S = suspended (race finished)
                    return None  # Race not finished yet

                for selection in market.get('selections', []):
                    horse_num = selection.get('runnerNumber')
                    result_code = selection.get('result')
                    if horse_num and result_code:
                        # W=1st (winner), P=placed (2nd/3rd), V=void, L=lost (4th+)
                        if result_code == 'W':
                            position = 1
                        elif result_code == 'P':
                            position = 2  # Placed = 2nd or 3rd (counts for 2/3 promo)
                        elif result_code == 'V':
                            position = -1  # Void/scratched
                        else:
                            position = 0  # Lost (4th+)
                        results[horse_num] = {
                            'position': position,
                            'result_code': result_code,
                            'horse_name': selection.get('name')
                        }
                break

        return results if results else None

    async def find_race_by_venue_and_number(self, venue: str, race_number: int, date_str: str) -> Optional[Dict]:
        """Find a race by venue and race number on a specific date"""
        meetings = await self.get_meetings(date_str, international=False)

        for meeting in meetings:
            meeting_venue = meeting['venue'].lower().replace(' ', '')
            search_venue = venue.lower().replace(' ', '')

            if meeting_venue not in search_venue and search_venue not in meeting_venue:
                continue

            for race in meeting['races']:
                if race['race_number'] == race_number:
                    return {
                        'event_id': race['event_id'],
                        'venue': meeting['venue'],
                        'race_number': race['race_number'],
                        'status': race['status']
                    }

        return None


async def test():
    """Test the Sportsbet source"""
    source = SportsbetSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            first_meeting = meetings[0]
            print(f"First meeting: {first_meeting['venue']}")

            if first_meeting['races']:
                first_race = first_meeting['races'][0]
                print(f"First race: R{first_race['race_number']} - {first_race['race_name']}")

                print("\nFetching odds...")
                odds = await source.get_race_odds(first_race['event_id'])
                print(f"Runners: {len(odds['runners'])}")

                for num, runner in list(odds['runners'].items())[:3]:
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
