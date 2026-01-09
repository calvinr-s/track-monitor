"""
Pointsbet data source - provides win odds
"""

import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')


class PointsbetSource:
    """Pointsbet bookmaker data source"""

    MEETINGS_URL = "https://api.au.pointsbet.com/api/racing/v4/meetings"
    RACE_URL = "https://api.au.pointsbet.com/api/racing/v3/races/{race_id}"

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
        end_date = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
        end = end_date.strftime("%Y-%m-%dT00:00:00.000Z")

        params = {
            'startDate': start,
            'endDate': end
        }

        session = await self._get_session()

        try:
            async with session.get(self.MEETINGS_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"Pointsbet meetings error: {e}")
            return []

        meetings = []

        for group in data:
            for meeting in group.get('meetings', []):
                # Filter by country unless international
                if not international and meeting.get('countryCode') != 'AUS':
                    continue
                if meeting.get('racingType') != 1:  # 1 = horses
                    continue

                venue = meeting.get('venue', 'Unknown')
                meeting_id = meeting.get('meetingId')

                races = []
                for race in meeting.get('races', []):
                    start_str = race.get('advertisedStartDateTimeUtc')
                    start_time = None
                    if start_str:
                        try:
                            start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                        except:
                            pass

                    races.append({
                        'race_id': race.get('raceId'),
                        'race_number': race.get('raceNumber'),
                        'race_name': race.get('name'),
                        'start_time': start_time
                    })

                meetings.append({
                    'venue': venue,
                    'meeting_id': meeting_id,
                    'races': races
                })

        return meetings

    async def get_race_odds(self, race_id: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds (from fluctuations.current)
        """
        url = self.RACE_URL.format(race_id=race_id)
        session = await self._get_session()

        try:
            async with session.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"Pointsbet odds error: {e}")
            return {}

        result = {
            'race_id': race_id,
            'runners': {}
        }

        for runner in data.get('runners', []):
            horse_number = runner.get('number')
            horse_name = runner.get('runnerName', 'Unknown')
            is_scratched = runner.get('isScratched', False)

            # Get current odds from fluctuations
            fluctuations = runner.get('fluctuations', {})
            win_odds = fluctuations.get('current')

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
        Find a specific race by venue, race number, and approximate start time
        """
        today = start_time.strftime("%Y-%m-%d")
        meetings = await self.get_meetings(today, international=international)

        for meeting in meetings:
            # Normalize venue names for matching
            meeting_venue = meeting['venue'].lower().replace(' ', '')
            search_venue = venue.lower().replace(' ', '')

            if meeting_venue not in search_venue and search_venue not in meeting_venue:
                continue

            for race in meeting['races']:
                if race['race_number'] != race_number:
                    continue

                # Check time tolerance (5 minutes)
                if race['start_time']:
                    time_diff = abs((race['start_time'] - start_time).total_seconds())
                    if time_diff <= 300:  # 5 minutes tolerance
                        return {
                            'race_id': race['race_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time']
                        }

        return None


async def test():
    """Test the Pointsbet source"""
    source = PointsbetSource()
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
                odds = await source.get_race_odds(first_race['race_id'])
                print(f"Runners: {len(odds['runners'])}")

                for num, runner in list(odds['runners'].items())[:3]:
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
