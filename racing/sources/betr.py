"""
Betr data source - provides win odds
Uses BlueBet API (Betr is powered by BlueBet)
"""

import asyncio
import aiohttp
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')


class BetrSource:
    """Betr bookmaker data source"""

    MEETINGS_URL = "https://web20-api.bluebet.com.au/GroupedRaceCard"
    RACE_URL = "https://web20-api.bluebet.com.au/Race"

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
        Fetch horse racing meetings for today
        Args:
            date: Not used (API only supports today via DaysToRace)
            international: If True, fetch all countries. If False, only Australia.
        """
        params = {'DaysToRace': '0'}

        session = await self._get_session()

        try:
            async with session.get(self.MEETINGS_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"Betr meetings error: {e}")
            return []

        meetings = []

        # Thoroughbred contains list of meetings, each meeting is a list of races
        thoroughbred = data.get('Thoroughbred', [])

        for meeting_races in thoroughbred:
            if not meeting_races:
                continue

            # Get venue info from first race
            first_race = meeting_races[0]
            venue = first_race.get('Venue', 'Unknown')
            country_code = first_race.get('CountryCode', 'AUS')

            # Filter by country unless international
            if not international and country_code != 'AUS':
                continue

            races = []
            for race in meeting_races:
                start_str = race.get('AdvertisedStartTime')
                start_time = None
                if start_str:
                    try:
                        # Handle format: 2026-01-08T05:00:00.0000000Z
                        start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00').split('.')[0] + '+00:00')
                    except:
                        pass

                races.append({
                    'event_id': race.get('EventId'),
                    'race_number': race.get('RaceNumber'),
                    'race_name': race.get('EventName'),
                    'start_time': start_time,
                    'is_open': race.get('IsOpenForBetting', False)
                })

            meetings.append({
                'venue': venue,
                'country_code': country_code,
                'races': races
            })

        return meetings

    async def get_race_odds(self, event_id: int) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds
        """
        params = {'eventId': str(event_id)}
        session = await self._get_session()

        try:
            async with session.get(self.RACE_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"Betr odds error: {e}")
            return {}

        result = {
            'event_id': event_id,
            'runners': {}
        }

        for runner in data.get('Outcomes', []):
            # OutcomeId is the saddle cloth number
            horse_number = runner.get('OutcomeId')
            if horse_number is not None:
                try:
                    horse_number = int(horse_number)
                except:
                    continue

            horse_name = runner.get('OutcomeName', 'Unknown')
            is_scratched = runner.get('Scratched', False)

            # Get WIN odds from FixedPrices
            win_odds = None
            for fp in runner.get('FixedPrices', []):
                if fp.get('MarketTypeCode') == 'WIN':
                    win_odds = fp.get('Price')
                    break

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
        meetings = await self.get_meetings(international=international)

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
                            'event_id': race['event_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time']
                        }

        return None


async def test():
    """Test the Betr source"""
    source = BetrSource()
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
