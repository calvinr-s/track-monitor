"""
TAB data source - provides win odds
Uses curl_cffi to bypass TLS fingerprinting
"""

import asyncio
from curl_cffi.requests import AsyncSession
from datetime import datetime, timezone
from typing import Dict, List, Optional


class TABSource:
    """TAB bookmaker data source"""

    BASE_URL = "https://api.beta.tab.com.au/v1/tab-info-service/racing"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'application/json',
    }

    def __init__(self):
        self.session: Optional[AsyncSession] = None

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession(headers=self.HEADERS, impersonate="chrome")
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def get_meetings(self, date: str = None, international: bool = False) -> List[Dict]:
        """
        Fetch horse racing meetings for a date
        Args:
            date: Date string in YYYY-MM-DD format (defaults to today)
            international: If True, fetch all. If False, only Australian.
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        url = f"{self.BASE_URL}/dates/{date}/meetings"
        params = {
            'jurisdiction': 'NSW',
            'returnOffers': 'true',
            'returnPromo': 'false'
        }

        session = await self._get_session()

        try:
            resp = await session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"TAB meetings error: {e}")
            return []

        meetings = []

        for meeting in data.get('meetings', []):
            # Only thoroughbred racing (raceType = R)
            if meeting.get('raceType') != 'R':
                continue

            venue = meeting.get('meetingName', 'Unknown')
            venue_code = meeting.get('venueMnemonic', '')
            location = meeting.get('location', '')

            # Filter to Australian states unless international
            au_states = ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT']
            if not international and location not in au_states:
                continue

            races = []
            for race in meeting.get('races', []):
                start_time_str = race.get('raceStartTime')
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    except:
                        pass

                races.append({
                    'race_number': race.get('raceNumber'),
                    'race_name': race.get('raceName'),
                    'start_time': start_time,
                    'status': race.get('raceStatus'),
                    'venue_code': venue_code,
                    'date': date
                })

            meetings.append({
                'venue': venue,
                'venue_code': venue_code,
                'location': location,
                'races': races
            })

        return meetings

    async def get_race_odds(self, venue_code: str, race_number: int, date: str) -> Dict:
        """
        Fetch odds for a specific race
        Returns dict with runners and their win odds
        """
        url = f"{self.BASE_URL}/dates/{date}/meetings/R/{venue_code}/races/{race_number}"
        params = {
            'returnPromo': 'true',
            'returnOffers': 'true',
            'jurisdiction': 'NSW'
        }

        session = await self._get_session()

        try:
            resp = await session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except Exception as e:
            print(f"TAB odds error: {e}")
            return {}

        result = {
            'venue_code': venue_code,
            'race_number': race_number,
            'runners': {}
        }

        for runner in data.get('runners', []):
            horse_number = runner.get('runnerNumber')
            if horse_number is None:
                continue

            horse_name = runner.get('runnerName', 'Unknown')
            fixed_odds = runner.get('fixedOdds', {})

            # Check if scratched
            betting_status = fixed_odds.get('bettingStatus', '')
            is_scratched = 'Scratched' in betting_status

            # Get fixed win odds
            win_odds = fixed_odds.get('returnWin')

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
                            'venue_code': meeting['venue_code'],
                            'venue': meeting['venue'],
                            'state': meeting.get('location', ''),
                            'race_number': race['race_number'],
                            'race_name': race['race_name'],
                            'start_time': race['start_time'],
                            'date': race['date']
                        }

            if best_match:
                return best_match

        return None


async def test():
    """Test the TAB source"""
    source = TABSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            for meeting in meetings[:3]:
                print(f"\n{meeting['venue']} ({meeting['venue_code']})")
                for race in meeting['races'][:2]:
                    print(f"  R{race['race_number']}: {race['race_name']}")

            # Test odds fetch
            first_meeting = meetings[0]
            if first_meeting['races']:
                first_race = first_meeting['races'][0]
                print(f"\nFetching odds for {first_meeting['venue']} R{first_race['race_number']}...")
                odds = await source.get_race_odds(
                    first_meeting['venue_code'],
                    first_race['race_number'],
                    first_race['date']
                )
                print(f"Runners: {len(odds.get('runners', {}))}")

                for num, runner in list(odds.get('runners', {}).items())[:5]:
                    status = " (SCR)" if runner['scratched'] else ""
                    print(f"  #{num}: {runner['horse_name']} - ${runner['win_odds']}{status}")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
