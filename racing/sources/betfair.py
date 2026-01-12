"""
Betfair data source - provides back/lay odds and liquidity
Includes both WIN and PLACE markets
Uses curl_cffi to bypass Cloudflare protection
"""

import asyncio
from curl_cffi.requests import AsyncSession
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')
from config import BETFAIR_API_KEY
try:
    from config import PROXY_URL
except ImportError:
    PROXY_URL = None


class BetfairSource:
    """Betfair Exchange data source"""

    BASE_URL = "https://apieds.betfair.com.au/api/eds/meeting-races/v4"
    ODDS_URL = "https://ero.betfair.com.au/www/sports/exchange/readonly/v1/bymarket"

    def __init__(self):
        self.session: Optional[AsyncSession] = None

    async def _get_session(self) -> AsyncSession:
        if self.session is None:
            self.session = AsyncSession(impersonate="chrome")
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def _fetch_json(self, url: str, params: dict) -> Optional[Any]:
        """Fetch JSON from URL with Cloudflare bypass"""
        session = await self._get_session()
        try:
            resp = await session.get(
                url,
                params=params,
                timeout=15,
                proxy=PROXY_URL
            )
            if resp.status_code != 200:
                print(f"Betfair status {resp.status_code} for {url.split('/')[-1]}")
                return None
            # Check if response is JSON
            content_type = resp.headers.get('content-type', '')
            if 'json' not in content_type:
                print(f"Betfair got HTML instead of JSON for {url.split('/')[-1]}")
                return None
            return resp.json()
        except Exception as e:
            print(f"Betfair fetch error: {e}")
            return None

    async def get_meetings(self, date: str = None, international: bool = False) -> List[Dict]:
        """
        Fetch horse racing meetings for a date
        Args:
            date: Date string YYYY-MM-DD (defaults to today)
            international: If True, fetch all countries. If False, only Australia.
        Returns list of meetings with races
        """
        if date is None:
            now = datetime.now(timezone.utc)
            date = now.strftime("%Y-%m-%d")

        # Build date range for the day
        start = f"{date}T00:00:00.000Z"
        end = f"{date}T23:59:59.999Z"

        params = {
            '_ak': BETFAIR_API_KEY,
            'eventTypeId': '7',
            'marketStartingAfter': start,
            'marketStartingBefore': end
        }

        # Filter to Australia only if not international
        if not international:
            params['countriesGroup'] = '[["AU"]]'
            params['countriesList'] = '["AU"]'

        data = await self._fetch_json(self.BASE_URL, params)
        if not data:
            return []

        meetings = []
        for country in data:
            country_codes = country.get('countryCodes', ['??'])
            country_code = country_codes[0] if country_codes else '??'

            for meeting in country.get('meetings', []):
                venue = meeting.get('venue', 'Unknown')
                meeting_id = meeting.get('meetingId')

                races = []
                for race in meeting.get('races', []):
                    races.append({
                        'market_id': race.get('marketId'),
                        'race_number': int(race.get('raceNumber', '0').replace('R', '')),
                        'race_name': race.get('marketName'),
                        'start_time': race.get('startTime'),
                        'status': race.get('status')
                    })

                meetings.append({
                    'venue': venue,
                    'meeting_id': meeting_id,
                    'country_code': country_code,
                    'races': races
                })

        return meetings

    async def get_race_odds(self, market_id: str) -> Dict:
        """
        Fetch odds for a specific WIN market
        Returns dict with runners and their back/lay odds
        """
        params = {
            '_ak': BETFAIR_API_KEY,
            'currencyCode': 'AUD',
            'marketIds': market_id,
            'rollupLimit': '5',
            'rollupModel': 'STAKE',
            'types': 'MARKET_STATE,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST,RUNNER_DESCRIPTION'
        }

        data = await self._fetch_json(self.ODDS_URL, params)
        if not data:
            return {}

        return self._parse_odds_response(data)

    async def get_place_market_id(self, win_market_id: str) -> Optional[str]:
        """
        Find the PLACE market ID corresponding to a WIN market
        Place markets typically have a different market ID but same event
        """
        params = {
            '_ak': BETFAIR_API_KEY,
            'currencyCode': 'AUD',
            'marketIds': win_market_id,
            'rollupLimit': '1',
            'rollupModel': 'STAKE',
            'types': 'MARKET_STATE'
        }

        data = await self._fetch_json(self.ODDS_URL, params)
        if not data:
            return None

        try:
            # Get event ID
            event_types = data.get('eventTypes', [])
            if not event_types:
                return None

            event_nodes = event_types[0].get('eventNodes', [])
            if not event_nodes:
                return None

            event_id = event_nodes[0].get('eventId')

            # Now search for place market for this event
            nav_url = "https://ero.betfair.com.au/www/sports/navigation/facet/v1/search"
            nav_params = {
                '_ak': BETFAIR_API_KEY,
                'eventId': event_id,
                'marketBettingTypes': 'ODDS',
                'maxResults': '10'
            }

            nav_data = await self._fetch_json(nav_url, nav_params)
            if nav_data:
                # Look for TO_BE_PLACED or PLACE market
                attachments = nav_data.get('attachments', {})
                markets = attachments.get('markets', {})

                for mid, market_info in markets.items():
                    market_type = market_info.get('marketType', '')
                    if 'PLACE' in market_type.upper() or 'TO_BE_PLACED' in market_type.upper():
                        return mid

            # Fallback: try sequential ID
            base_id = win_market_id.split('.')
            if len(base_id) == 2:
                place_id = f"{base_id[0]}.{int(base_id[1]) + 1}"
                return place_id

        except Exception as e:
            print(f"Betfair place market search error: {e}")

        return None

    async def get_race_with_place_odds(self, win_market_id: str) -> Dict:
        """
        Fetch both WIN and PLACE odds for a race
        Returns combined data structure
        """
        # Fetch win odds
        win_data = await self.get_race_odds(win_market_id)

        # Try to find and fetch place odds
        place_market_id = await self.get_place_market_id(win_market_id)
        place_data = {}

        if place_market_id:
            place_data = await self.get_race_odds(place_market_id)

        # Combine the data
        result = {
            'win_market_id': win_market_id,
            'place_market_id': place_market_id,
            'runners': {}
        }

        # Add win odds
        for runner in win_data.get('runners', []):
            horse_num = runner.get('horse_number')
            if horse_num:
                result['runners'][horse_num] = {
                    'horse_number': horse_num,
                    'horse_name': runner.get('horse_name'),
                    'back_win': runner.get('back_odds'),
                    'back_win_size': runner.get('back_size'),
                    'lay_win': runner.get('lay_odds'),
                    'lay_win_size': runner.get('lay_size'),
                    'back_place': None,
                    'lay_place': None,
                    'status': runner.get('status')
                }

        # Add place odds
        for runner in place_data.get('runners', []):
            horse_num = runner.get('horse_number')
            if horse_num and horse_num in result['runners']:
                result['runners'][horse_num]['back_place'] = runner.get('back_odds')
                result['runners'][horse_num]['lay_place'] = runner.get('lay_odds')

        return result

    def _parse_odds_response(self, data: Dict) -> Dict:
        """Parse Betfair odds API response"""
        result = {
            'runners': [],
            'market_status': None,
            'total_matched': 0
        }

        try:
            event_types = data.get('eventTypes', [])
            for et in event_types:
                for event_node in et.get('eventNodes', []):
                    for market_node in event_node.get('marketNodes', []):
                        state = market_node.get('state', {})
                        result['market_status'] = state.get('status')
                        result['total_matched'] = state.get('totalMatched', 0)
                        result['num_runners'] = state.get('numberOfActiveRunners', 0)

                        for idx, runner in enumerate(market_node.get('runners', []), start=1):
                            runner_name = runner.get('description', {}).get('runnerName', 'Unknown')

                            # Extract horse number from name (AU format: "1. Horse Name")
                            horse_number = None
                            horse_name = runner_name
                            if '.' in runner_name:
                                parts = runner_name.split('.', 1)
                                try:
                                    horse_number = int(parts[0].strip())
                                    horse_name = parts[1].strip()
                                except:
                                    pass

                            # For UK/international races without numbers, use index
                            if horse_number is None:
                                horse_number = idx

                            exchange = runner.get('exchange', {})
                            back_prices = exchange.get('availableToBack', [])
                            lay_prices = exchange.get('availableToLay', [])

                            best_back = back_prices[0] if back_prices else {}
                            best_lay = lay_prices[0] if lay_prices else {}

                            runner_status = runner.get('state', {}).get('status', 'Unknown')

                            result['runners'].append({
                                'horse_number': horse_number,
                                'horse_name': horse_name,
                                'back_odds': best_back.get('price'),
                                'back_size': best_back.get('size', 0),
                                'lay_odds': best_lay.get('price'),
                                'lay_size': best_lay.get('size', 0),
                                'status': runner_status
                            })
        except Exception as e:
            print(f"Betfair parse error: {e}")

        return result

    async def find_next_race(self, international: bool = False) -> Optional[Dict]:
        """
        Find the next race to start
        Args:
            international: If True, search all countries. If False, only Australia.
        Returns race info with market_id
        """
        races = await self.find_upcoming_races(international=international, limit=1)
        return races[0] if races else None

    async def find_upcoming_races(self, international: bool = False, limit: int = 10) -> List[Dict]:
        """
        Find the next N upcoming races, sorted by start time.
        Args:
            international: If True, search all countries. If False, only Australia.
            limit: Maximum number of races to return
        Returns list of race info dicts
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)

        # Search from now to 18 hours ahead (covers overnight into next day)
        meetings = await self.get_meetings_by_time(
            start_time=now,
            end_time=now + timedelta(hours=18),
            international=international
        )

        upcoming = []

        for meeting in meetings:
            venue = meeting['venue']
            country_code = meeting.get('country_code', 'AU')
            for race in meeting['races']:
                if race['status'] not in ('OPEN', 'SUSPENDED'):
                    continue

                start_str = race['start_time']
                try:
                    start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                except:
                    continue

                delta = (start_time - now).total_seconds()

                # Only consider future races
                if delta > 0:
                    upcoming.append({
                        'venue': venue,
                        'country_code': country_code,
                        'race_number': race['race_number'],
                        'race_name': race['race_name'],
                        'market_id': race['market_id'],
                        'start_time': start_time,
                        'seconds_until_start': delta
                    })

        # Sort by start time and limit
        upcoming.sort(key=lambda x: x['seconds_until_start'])
        return upcoming[:limit]

    async def get_meetings_by_time(self, start_time: datetime, end_time: datetime, international: bool = False) -> List[Dict]:
        """
        Fetch meetings within a specific time range
        """
        start = start_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = end_time.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        params = {
            '_ak': BETFAIR_API_KEY,
            'eventTypeId': '7',
            'marketStartingAfter': start,
            'marketStartingBefore': end
        }

        if not international:
            params['countriesGroup'] = '[["AU"]]'
            params['countriesList'] = '["AU"]'

        data = await self._fetch_json(self.BASE_URL, params)
        if not data:
            return []

        meetings = []
        for country in data:
            country_codes = country.get('countryCodes', ['??'])
            country_code = country_codes[0] if country_codes else '??'

            for meeting in country.get('meetings', []):
                venue = meeting.get('venue', 'Unknown')
                meeting_id = meeting.get('meetingId')

                races = []
                for race in meeting.get('races', []):
                    races.append({
                        'market_id': race.get('marketId'),
                        'race_number': int(race.get('raceNumber', '0').replace('R', '')),
                        'race_name': race.get('marketName'),
                        'start_time': race.get('startTime'),
                        'status': race.get('status')
                    })

                meetings.append({
                    'venue': venue,
                    'meeting_id': meeting_id,
                    'country_code': country_code,
                    'races': races
                })

        return meetings


async def test():
    """Test the Betfair source"""
    source = BetfairSource()
    try:
        print("Finding next race...")
        next_race = await source.find_next_race()
        if next_race:
            print(f"Next race: {next_race['venue']} R{next_race['race_number']}")
            print(f"Starts in: {next_race['seconds_until_start']:.0f}s")
            print(f"Market ID: {next_race['market_id']}")

            print("\nFetching odds...")
            odds = await source.get_race_with_place_odds(next_race['market_id'])
            print(f"Win Market: {odds['win_market_id']}")
            print(f"Place Market: {odds['place_market_id']}")
            print(f"Runners: {len(odds['runners'])}")

            for num, runner in list(odds['runners'].items())[:3]:
                print(f"  #{num}: Lay Win={runner['lay_win']}, Lay Place={runner['lay_place']}")
        else:
            print("No upcoming races found")
    finally:
        await source.close()


if __name__ == "__main__":
    asyncio.run(test())
