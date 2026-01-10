"""
Amused (Bluebet) data source - provides win odds
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')


class AmusedSource:
    """Amused/Bluebet bookmaker data source"""

    SCHEDULE_URL = "https://api.blackstream.com.au/api/racing/v1/schedule"
    RACECARD_URL = "https://api.blackstream.com.au/api/racing/v1/meetings/{meet_id}/races/{race_id}/racecard"

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

        # Build date range
        start = f"{date}T00:00:00.000Z"
        end = f"{date}T23:59:59.999Z"

        params = {
            'startDateTime': start,
            'endDateTime': end,
            'topfouroutcomes': 'true'
        }

        session = await self._get_session()

        try:
            async with session.get(self.SCHEDULE_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"Amused meetings error: {e}")
            return []

        meetings = []

        # Get thoroughbred (horse) races
        thoroughbred = data.get('data', {}).get('thoroughbred', [])

        for meeting in thoroughbred:
            # Filter by country unless international
            if not international and meeting.get('countryCode') != 'AUS':
                continue

            venue = meeting.get('venue', 'Unknown')
            meet_id = meeting.get('meetId')

            races = []
            for race in meeting.get('races', []):
                start_str = race.get('advertisedStartTime')
                start_time = None
                if start_str:
                    try:
                        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    except:
                        pass

                races.append({
                    'race_id': race.get('eventId'),
                    'race_number': race.get('raceNumber'),
                    'race_name': race.get('raceName'),
                    'start_time': start_time,
                    'is_open': race.get('isOpenForBetting', False)
                })

            meetings.append({
                'venue': venue,
                'meet_id': meet_id,
                'races': races
            })

        return meetings

    async def get_race_odds(self, meet_id: str, race_id: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds (last price in winPrices array)
        """
        url = self.RACECARD_URL.format(meet_id=meet_id, race_id=race_id)
        session = await self._get_session()

        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"Amused odds error: {e}")
            return {}

        result = {
            'race_id': race_id,
            'runners': {}
        }

        race_data = data.get('data', {}).get('race', {})

        for runner in race_data.get('runners', []):
            horse_number = runner.get('outcomeId')
            horse_name = runner.get('runnerName', 'Unknown')
            is_scratched = runner.get('isScratched', False)

            # Get the last price in winPrices array (current odds)
            win_prices = runner.get('winPrices', [])
            win_odds = win_prices[-1] if win_prices else None

            if horse_number:
                result['runners'][horse_number] = {
                    'horse_number': horse_number,
                    'horse_name': horse_name,
                    'win_odds': win_odds,
                    'scratched': is_scratched
                }

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
                            'meet_id': meeting['meet_id'],
                            'race_id': race['race_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time']
                        }

            if best_match:
                return best_match

        return None


async def test():
    """Test the Amused source"""
    source = AmusedSource()
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
                odds = await source.get_race_odds(first_meeting['meet_id'], first_race['race_id'])
                print(f"Runners: {len(odds['runners'])}")

                for num, runner in list(odds['runners'].items())[:3]:
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
