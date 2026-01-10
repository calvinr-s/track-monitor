"""
BoomBet data source - provides win odds
"""

import asyncio
import aiohttp
from datetime import datetime, timezone
from typing import Dict, List, Optional


class BoomBetSource:
    """BoomBet bookmaker data source"""

    MEETINGS_URL = "https://sb-saturn.azurefd.net/api/v3/race/getracecardsall"
    RACE_URL = "https://sb-saturn.azurefd.net/api/v3/race/event"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Origin': 'https://www.boombet.com.au',
        'Referer': 'https://www.boombet.com.au/',
        'sp-deviceid': 'dev',
        'sp-platformid': '2',
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
        params = {
            'day': '7',  # 7 = thoroughbred
            'onExactDate': '991231'  # Special value for all dates
        }

        session = await self._get_session()

        try:
            async with session.get(self.MEETINGS_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        except Exception as e:
            print(f"BoomBet meetings error: {e}")
            return []

        meetings = []

        # Data is a list of meetings
        for meeting in data:
            # type 4 = thoroughbred
            if meeting.get('type') != 4:
                continue

            venue = meeting.get('meetingName', 'Unknown')
            state = meeting.get('state', '')

            # Filter to Australian states unless international
            au_states = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT']
            if not international and state not in au_states:
                continue

            races = []
            for race in meeting.get('races', []):
                jump_time_str = race.get('jumpTime') or race.get('outcomeTime')
                start_time = None
                if jump_time_str:
                    try:
                        start_time = datetime.fromisoformat(jump_time_str.replace('Z', '+00:00'))
                    except:
                        pass

                races.append({
                    'event_id': race.get('eventId'),
                    'race_number': race.get('raceNumber'),
                    'race_name': race.get('description'),
                    'start_time': start_time,
                    'status': race.get('status'),
                    'jumps_in_sec': race.get('jumpsInSec', 0)
                })

            meetings.append({
                'venue': venue,
                'state': state,
                'races': races
            })

        return meetings

    async def get_race_odds(self, event_id: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds
        """
        url = f"{self.RACE_URL}/{event_id}"
        params = {
            'checkHotBet': 'false',
            'includeForm': 'false'
        }

        session = await self._get_session()

        try:
            async with session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            print(f"BoomBet odds error: {e}")
            return {}

        result = {
            'event_id': event_id,
            'runners': {}
        }

        for runner in data.get('runners', []):
            horse_number = runner.get('number')
            if horse_number is None:
                continue

            horse_name = runner.get('name', 'Unknown')
            is_scratched = runner.get('isEliminated', False) or runner.get('scratchedDateTime') is not None

            # Get Fixed Win odds from odds array
            win_odds = None
            for odds_entry in runner.get('odds', []):
                product = odds_entry.get('product', {})
                if product.get('specialType') == 'FWIN':
                    win_odds = odds_entry.get('value')
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
                            'event_id': race['event_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time']
                        }

            if best_match:
                return best_match

        return None


async def test():
    """Test the BoomBet source"""
    source = BoomBetSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            for meeting in meetings[:3]:
                print(f"\n{meeting['venue']} ({meeting['state']})")
                for race in meeting['races'][:2]:
                    print(f"  R{race['race_number']}: {race['race_name']} (ID: {race['event_id']})")

            # Test odds fetch
            first_meeting = meetings[0]
            if first_meeting['races']:
                first_race = first_meeting['races'][0]
                print(f"\nFetching odds for {first_meeting['venue']} R{first_race['race_number']}...")
                odds = await source.get_race_odds(first_race['event_id'])
                print(f"Runners: {len(odds.get('runners', {}))}")

                for num, runner in list(odds.get('runners', {}).items())[:3]:
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
