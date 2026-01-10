"""
PlayUp data source - provides win odds via REST API
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from curl_cffi.requests import AsyncSession


class PlayUpSource:
    """PlayUp bookmaker data source"""

    BASE_URL = "https://wagering-api.playup.io/v1"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
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

    async def get_meetings(self, date: str = None) -> List[Dict]:
        """Fetch horse racing meetings for a date"""
        if date is None:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        session = await self._get_session()
        url = f"{self.BASE_URL}/meetings/?date={date}&include=races"

        try:
            resp = await session.get(url, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"PlayUp meetings error: {e}")
            return []

        meetings = []
        included = data.get('included', [])

        # Build race lookup from included
        races_by_meeting = {}
        for item in included:
            if item.get('type') == 'races':
                attrs = item.get('attributes', {})
                meeting_info = attrs.get('meeting', {})
                meeting_id = meeting_info.get('id')

                if meeting_id not in races_by_meeting:
                    races_by_meeting[meeting_id] = []

                start_time_str = attrs.get('start_time')
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    except:
                        pass

                status = attrs.get('status', {}).get('name', '')
                race_type = attrs.get('race_type', {}).get('name', '')

                # Only include gallop races that are open
                if race_type == 'Gallop':
                    races_by_meeting[meeting_id].append({
                        'race_id': item.get('id'),
                        'race_number': attrs.get('race_number'),
                        'start_time': start_time,
                        'status': status,
                        'date': date
                    })

        # Build meetings list
        for meeting in data.get('data', []):
            attrs = meeting.get('attributes', {})
            meeting_id = int(meeting.get('id', 0))

            races = races_by_meeting.get(meeting_id, [])
            if races:
                meetings.append({
                    'venue': attrs.get('name', 'Unknown'),
                    'state': attrs.get('state', ''),
                    'country': attrs.get('country', 'AU'),
                    'races': races
                })

        return meetings

    async def get_race_odds(self, race_id: str) -> Dict:
        """Fetch odds for a specific race"""
        session = await self._get_session()
        url = f"{self.BASE_URL}/races/{race_id}/?include=meeting,available_bet_types,selections.prices,result,promotions,easy_form"

        result = {
            'race_id': race_id,
            'runners': {}
        }

        try:
            resp = await session.get(url, timeout=15)
            if resp.status_code != 200:
                return result
            data = resp.json()
        except Exception as e:
            print(f"PlayUp odds error: {e}")
            return result

        included = data.get('included', [])

        # Build price lookup - price id format is "{selection_id}-{product_id}-{bet_type_id}"
        prices = {}
        for item in included:
            if item.get('type') == 'prices':
                attrs = item.get('attributes', {})
                bet_type = attrs.get('bet_type', {}).get('id')
                if bet_type == 2:  # Win
                    price_id = item.get('id', '')
                    sel_id = price_id.split('-')[0]
                    prices[sel_id] = attrs.get('d_price')

        # Build runners
        for item in included:
            if item.get('type') == 'selections':
                attrs = item.get('attributes', {})
                sel_id = item.get('id')
                number = attrs.get('number')
                name = attrs.get('name', '')
                status = attrs.get('status', {}).get('name', '')

                scratched = status != 'Active'
                win_price = prices.get(sel_id)

                if number and win_price and not scratched:
                    result['runners'][number] = {
                        'horse_name': name,
                        'win_odds': float(win_price),
                        'scratched': scratched
                    }

        return result

    async def find_race(self, venue: str, race_number: int, start_time: datetime) -> Optional[Dict]:
        """Find a specific race by venue and race number"""
        today = start_time.strftime("%Y-%m-%d")
        meetings = await self.get_meetings(today)

        for meeting in meetings:
            meeting_venue = meeting['venue'].lower().replace(' ', '')
            search_venue = venue.lower().replace(' ', '')

            if meeting_venue not in search_venue and search_venue not in meeting_venue:
                continue

            # Find race by number or closest start time
            for race in meeting['races']:
                if race['race_number'] == race_number:
                    return {
                        'race_id': race['race_id'],
                        'venue': meeting['venue'],
                        'race_number': race['race_number'],
                        'start_time': race['start_time'],
                        'date': race['date']
                    }

            # Fallback: find by closest start time
            best_match = None
            best_diff = 300  # 5 minutes tolerance

            for race in meeting['races']:
                if race['start_time']:
                    time_diff = abs((race['start_time'] - start_time).total_seconds())
                    if time_diff <= best_diff:
                        best_diff = time_diff
                        best_match = {
                            'race_id': race['race_id'],
                            'venue': meeting['venue'],
                            'race_number': race['race_number'],
                            'start_time': race['start_time'],
                            'date': race['date']
                        }

            if best_match:
                return best_match

        return None


async def test():
    """Test the PlayUp source"""
    source = PlayUpSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            for meeting in meetings[:3]:
                print(f"\n{meeting['venue']} ({meeting['state']})")
                for race in meeting['races'][:2]:
                    status = race.get('status', 'Unknown')
                    print(f"  R{race['race_number']}: {race['race_id']} ({status})")

            # Find an Open race to test odds
            for meeting in meetings:
                for race in meeting['races']:
                    if race.get('status') == 'Open':
                        print(f"\nFetching odds for {meeting['venue']} R{race['race_number']}...")
                        odds = await source.get_race_odds(race['race_id'])
                        print(f"Runners: {len(odds.get('runners', {}))}")
                        for num, runner in sorted(odds.get('runners', {}).items())[:5]:
                            print(f"  #{num} {runner['horse_name']}: ${runner['win_odds']}")
                        break
                else:
                    continue
                break
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
