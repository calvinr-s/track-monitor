"""
Ladbrokes/Neds data source - provides win odds via GraphQL + WebSocket
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from curl_cffi.requests import AsyncSession
import socketio


def normalize_horse_name(name: str) -> str:
    """Normalize horse name for matching - removes punctuation and extra spaces"""
    if not name:
        return ''
    normalized = re.sub(r"['\-\.]", '', name)
    normalized = re.sub(r'\s+', ' ', normalized).strip().upper()
    return normalized


class LadbrokesSource:
    """Ladbrokes/Neds bookmaker data source"""

    GQL_URL = "https://api.ladbrokes.com.au/gql/router"
    WS_URL = "https://push.ladbrokes.com.au"

    # GraphQL persisted query hash for meetings
    MEETINGS_HASH = "77c712df2987b69fb85009665192c9be3140c5ceb0f49bac061632deeccfe691"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'application/json',
        'Origin': 'https://www.ladbrokes.com.au',
        'Referer': 'https://www.ladbrokes.com.au/',
    }

    def __init__(self):
        self.session: Optional[AsyncSession] = None
        self.sio: Optional[socketio.AsyncClient] = None

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession(headers=self.HEADERS, impersonate="chrome")
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None
        if self.sio and self.sio.connected:
            await self.sio.disconnect()
            self.sio = None

    async def get_meetings(self, date: str = None, international: bool = False) -> List[Dict]:
        """
        Fetch horse racing meetings for a date using GraphQL
        """
        if date is None:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        session = await self._get_session()

        params = {
            'variables': json.dumps({
                'date': date,
                'horse': True,
                'greyhound': False,
                'harness': False,
                'regions': ['DOMESTIC'] if not international else ['DOMESTIC', 'INTERNATIONAL']
            }),
            'operationName': 'RacingHomeScreenWeb',
            'extensions': json.dumps({
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': self.MEETINGS_HASH
                }
            })
        }

        try:
            resp = await session.get(self.GQL_URL, params=params, timeout=15)
            if resp.status_code != 200:
                return []
            data = resp.json()
        except Exception as e:
            print(f"Ladbrokes meetings error: {e}")
            return []

        meetings = []

        for meeting in data.get('data', {}).get('horse', {}).get('nodes', []):
            venue = meeting.get('name', 'Unknown')
            venue_info = meeting.get('venue', {})
            country = venue_info.get('country', 'AUS')
            state = venue_info.get('state', '')

            # Filter to Australian meetings unless international
            if not international and country != 'AUS':
                continue

            races = []
            for race in meeting.get('races', {}).get('nodes', []):
                start_time_str = race.get('advertisedStart')
                start_time = None
                if start_time_str:
                    try:
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                    except:
                        pass

                market = race.get('finalFieldMarket', {})
                market_id = market.get('id', '').replace('RacingMarket:', '')

                races.append({
                    'race_id': race.get('id', '').replace('RacingRace:', ''),
                    'race_number': race.get('number'),
                    'start_time': start_time,
                    'status': market.get('status'),
                    'market_id': market_id,
                    'date': date
                })

            meetings.append({
                'venue': venue,
                'country': country,
                'state': state,
                'races': races
            })

        return meetings

    # Persisted query hash for race entrant info
    ENTRANT_INFO_HASH = "1de3f28631ad07111fe7944e94a60b18f47a3b79ba9451f0eb1593e2b51e2c39"

    async def get_runner_info(self, race_id: str, market_id: str = None) -> Dict:
        """
        Fetch runner details for a race to get horse numbers mapped to entrant IDs.
        Uses BlackbookRaceEntrantInfo persisted query.
        """
        session = await self._get_session()

        params = {
            'variables': json.dumps({
                'raceId': f"RacingRace:{race_id}"
            }),
            'operationName': 'BlackbookRaceEntrantInfo',
            'extensions': json.dumps({
                'persistedQuery': {
                    'version': 1,
                    'sha256Hash': self.ENTRANT_INFO_HASH
                }
            })
        }

        try:
            resp = await session.get(self.GQL_URL, params=params, timeout=15)
            if resp.status_code != 200:
                return await self._get_runner_info_rest(race_id, market_id)
            data = resp.json()
            if 'errors' in data:
                return await self._get_runner_info_rest(race_id, market_id)
        except Exception:
            return await self._get_runner_info_rest(race_id, market_id)

        # Build mapping: entrant_id -> horse_number
        runner_map = {}
        race_data = data.get('data', {}).get('race', {})
        entrants = race_data.get('entrants', {}).get('nodes', [])
        for entrant in entrants:
            entrant_id = entrant.get('id', '').replace('RacingEntrant:', '')
            tab_no = entrant.get('tabNo')
            scratched = entrant.get('scratched', False)
            if entrant_id and tab_no:
                runner_map[entrant_id] = {
                    'horse_number': tab_no,
                    'horse_name': entrant.get('name', 'Unknown'),
                    'scratched': scratched
                }

        return runner_map if runner_map else await self._get_runner_info_rest(race_id, market_id)

    async def _get_runner_info_rest(self, race_id: str, market_id: str = None) -> Dict:
        """
        Fetch runner info via the entrant-forms endpoint.
        Returns mapping of entrant_id -> {horse_name, scratched}

        Note: We use horse name for matching since the API doesn't expose tab numbers.
        """
        session = await self._get_session()
        url = f"https://api.ladbrokes.com.au/v2/racing/get-entrant-forms?race_id={race_id}"

        try:
            resp = await session.get(
                url,
                headers={**self.HEADERS, 'Content-Type': 'application/json'},
                timeout=15
            )
            if resp.status_code != 200:
                return {}
            data = resp.json()
        except Exception:
            return {}

        runner_map = {}
        entrant_forms = data.get('entrant_forms', {})

        if isinstance(entrant_forms, dict):
            for entrant_id, form in entrant_forms.items():
                runner_info = form.get('runner_info', {})
                name = runner_info.get('name', '').strip()
                if name:
                    scratched = runner_info.get('status') == 'Scratched'
                    runner_map[entrant_id] = {
                        'horse_name': name,
                        'scratched': scratched
                    }

        return runner_map

    async def get_race_odds(self, market_id: str, race_id: str = None) -> Dict:
        """
        Fetch odds for a specific race market via WebSocket.
        Returns dict with runners keyed by normalized horse name (uppercase).
        """
        result = {
            'market_id': market_id,
            'runners': {}
        }

        # Fetch runner mapping (entrant_id -> horse_name)
        runner_map = {}
        if race_id:
            runner_map = await self.get_runner_info(race_id, market_id)

        import time

        def fetch_prices():
            """Fetch prices via WebSocket with fast timeout"""
            class PriceState:
                def __init__(self):
                    self.prices = {}
                    self.received = False

            state = PriceState()
            sio = socketio.Client(logger=False, engineio_logger=False)

            @sio.on('subscription')
            def on_subscription(data):
                if data.get('handler') == 'pricing' and data.get('method') == 'prices':
                    inner = data.get('data', {})
                    entries = inner.get('data', {})
                    for key, runner_data in entries.items():
                        if not isinstance(runner_data, dict):
                            continue
                        odds_info = runner_data.get('odds', {})
                        decimal = odds_info.get('decimal')
                        if decimal is None:
                            num = odds_info.get('numerator')
                            denom = odds_info.get('denominator')
                            if num is not None and denom is not None and denom > 0:
                                decimal = (num / denom) + 1
                        if decimal:
                            parts = key.split(':')
                            entrant_id = parts[0] if parts else None
                            if entrant_id:
                                state.prices[entrant_id] = float(decimal)
                                state.received = True

            try:
                sio.connect(
                    'https://push.ladbrokes.com.au',
                    transports=['websocket'],
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Origin': 'https://www.ladbrokes.com.au',
                    }
                )
                time.sleep(0.2)
                sio.emit('subscribe', {
                    'handler': 'pricing',
                    'method': 'prices',
                    'market_ids': [market_id]
                })

                # Fast timeout - 2 seconds max
                for i in range(20):
                    time.sleep(0.1)
                    if state.received and len(state.prices) >= 5:
                        break

                sio.disconnect()
            except Exception:
                pass

            return state.prices

        # Run in thread to avoid blocking event loop
        prices_by_entrant = await asyncio.to_thread(fetch_prices)

        # Map entrant_id prices to horse names
        for entrant_id, win_odds in prices_by_entrant.items():
            runner_info = runner_map.get(entrant_id, {})
            horse_name = runner_info.get('horse_name')
            scratched = runner_info.get('scratched', False)

            if horse_name and not scratched:
                # Key by normalized horse name for matching
                name_key = normalize_horse_name(horse_name)
                result['runners'][name_key] = {
                    'horse_name': horse_name,
                    'win_odds': win_odds,
                    'scratched': scratched
                }

        return result

    async def find_race(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Optional[Dict]:
        """
        Find a specific race by venue and start time.
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
                            'market_id': race['market_id'],
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
    """Test the Ladbrokes source"""
    source = LadbrokesSource()
    try:
        print("Fetching meetings...")
        meetings = await source.get_meetings()
        print(f"Found {len(meetings)} meetings")

        if meetings:
            for meeting in meetings[:3]:
                print(f"\n{meeting['venue']} ({meeting['state']})")
                for race in meeting['races'][:2]:
                    status = race.get('status', 'Unknown')
                    print(f"  R{race['race_number']}: Market {race['market_id'][:8]}... ({status})")

            # Find an OPEN race to test odds
            for meeting in meetings:
                for race in meeting['races']:
                    if race.get('status') == 'OPEN':
                        print(f"\nFetching odds for {meeting['venue']} R{race['race_number']}...")
                        odds = await source.get_race_odds(race['market_id'], race['race_id'])
                        print(f"Runners: {len(odds.get('runners', {}))}")
                        for name_key, runner in list(odds.get('runners', {}).items())[:5]:
                            print(f"  {runner['horse_name']}: ${runner['win_odds']}")
                        break
                else:
                    continue
                break
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
