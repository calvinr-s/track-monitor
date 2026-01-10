"""
PalmerBet data source - provides win odds
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional


class PalmerBetSource:
    """PalmerBet bookmaker data source"""

    BASE_URL = "https://fixture.palmerbet.online/fixtures/racing"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Origin': 'https://www.palmerbet.com',
        'Referer': 'https://www.palmerbet.com/',
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

    async def get_meetings(self, international: bool = False) -> List[Dict]:
        """
        Fetch horse racing meetings for today
        Args:
            international: If True, fetch all countries. If False, only Australia.
        """
        # Get today's date in YYYY-MM-DD format
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        url = f"{self.BASE_URL}/{today}/HorseRacing"
        params = {'channel': 'website'}

        session = await self._get_session()

        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"PalmerBet meetings error: {e}")
            return []

        meetings = []

        # Data structure: { "meetings": [...] }
        for meeting in data.get('meetings', []):
            # venue is an object with 'title' field
            venue_obj = meeting.get('venue', {})
            venue = venue_obj.get('title', 'Unknown')
            country = meeting.get('country', 'AU')

            # Filter to Australian meetings unless international
            if not international and country != 'AU':
                continue

            races = []
            for race in meeting.get('races', []):
                start_time_str = race.get('startTime')
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    except:
                        pass

                races.append({
                    'race_number': race.get('number'),
                    'race_name': race.get('title'),
                    'start_time': start_time,
                    'status': race.get('status'),
                    'venue': venue,
                    'date': today
                })

            meetings.append({
                'venue': venue,
                'country': country,
                'races': races
            })

        return meetings

    async def get_race_odds(self, venue: str, race_number: int, date: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds
        """
        # First get the race details to find the Win market ID
        race_url = f"{self.BASE_URL}/{date}/HorseRacing/{venue}/{race_number}"
        params = {'channel': 'website'}

        session = await self._get_session()

        try:
            async with session.get(race_url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"PalmerBet race error: {e}")
            return {}

        # Race data is nested under 'race' key
        race_data = data.get('race', {})

        # Find the Win market ID
        win_market_id = None
        for market in race_data.get('markets', []):
            if market.get('title') == 'Win':
                win_market_id = market.get('id')
                break

        if not win_market_id:
            return {}

        # Now fetch the Win market odds
        market_url = f"{self.BASE_URL}/HorseRacing/markets/{win_market_id}"

        try:
            async with session.get(market_url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"PalmerBet market error: {e}")
            return {}

        # Market data is nested under 'market' key
        market_data = data.get('market', {})

        result = {
            'venue': venue,
            'race_number': race_number,
            'runners': {}
        }

        for outcome in market_data.get('outcomes', []):
            horse_number = outcome.get('runnerNumber')
            horse_name = outcome.get('title', 'Unknown')

            if horse_number is None:
                continue

            is_scratched = outcome.get('isScratched', False)

            # Get Fixed odds from prices array
            win_odds = None
            for price in outcome.get('prices', []):
                if price.get('name') == 'Fixed':
                    price_snapshot = price.get('priceSnapshot', {})
                    win_odds = price_snapshot.get('current')
                    break

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
        meetings = await self.get_meetings(international=international)

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
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time'],
                            'date': race['date']
                        }

            if best_match:
                return best_match

        return None


async def test():
    """Test the PalmerBet source"""
    source = PalmerBetSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            for meeting in meetings[:3]:
                print(f"\n{meeting['venue']} ({meeting['country']})")
                for race in meeting['races'][:2]:
                    print(f"  R{race['race_number']}: {race['race_name']}")

            # Test odds fetch
            first_meeting = meetings[0]
            if first_meeting['races']:
                first_race = first_meeting['races'][0]
                print(f"\nFetching odds for {first_meeting['venue']} R{first_race['race_number']}...")
                odds = await source.get_race_odds(
                    first_meeting['venue'],
                    first_race['race_number'],
                    first_race['date']
                )
                print(f"Runners: {len(odds.get('runners', {}))}")

                for num, runner in list(odds.get('runners', {}).items())[:5]:
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
