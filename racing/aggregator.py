"""
Race aggregator - finds next race, matches across bookmakers, calculates EV
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import sys
sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')

from config import RETENTION_FACTOR
from racing.sources import BetfairSource, SportsbetSource, AmusedSource, PointsbetSource, BetrSource


class RaceAggregator:
    """Aggregates race data from multiple sources and calculates EV"""

    def __init__(self):
        self.betfair = BetfairSource()
        self.sportsbet = SportsbetSource()
        self.amused = AmusedSource()
        self.pointsbet = PointsbetSource()
        self.betr = BetrSource()

    async def close(self):
        """Close all source sessions"""
        await asyncio.gather(
            self.betfair.close(),
            self.sportsbet.close(),
            self.amused.close(),
            self.pointsbet.close(),
            self.betr.close()
        )

    async def get_next_race(self, international: bool = False, promo: str = "2/3") -> Optional[Dict]:
        """
        Find the next race and aggregate odds from all bookmakers.
        Skips races where no bookmaker has odds.
        Args:
            international: If True, search international races (Betfair only).
                          If False, search Australian races with all bookmakers.
            promo: "2/3" for 2nd/3rd promo, "free_hit" for free hit promo.
        Returns combined race data with EV calculations.
        """
        # Find upcoming races from Betfair (our reference source)
        upcoming_races = await self.betfair.find_upcoming_races(international=international, limit=10)
        if not upcoming_races:
            return None

        # Try each race until we find one with bookmaker coverage
        for next_race in upcoming_races:
            venue = next_race['venue']
            race_number = next_race['race_number']
            start_time = next_race['start_time']
            market_id = next_race['market_id']
            country_code = next_race.get('country_code', 'AU')

            # Fetch all data in parallel
            betfair_task = self.betfair.get_race_with_place_odds(market_id)
            sportsbet_task = self._fetch_sportsbet(venue, race_number, start_time, international)
            amused_task = self._fetch_amused(venue, race_number, start_time, international)
            pointsbet_task = self._fetch_pointsbet(venue, race_number, start_time, international)
            betr_task = self._fetch_betr(venue, race_number, start_time, international)

            betfair_data, sportsbet_data, amused_data, pointsbet_data, betr_data = await asyncio.gather(
                betfair_task, sportsbet_task, amused_task, pointsbet_task, betr_task
            )

            # Check if at least one bookmaker has odds
            has_bookie_odds = (
                bool(sportsbet_data.get('runners')) or
                bool(amused_data.get('runners')) or
                bool(pointsbet_data.get('runners')) or
                bool(betr_data.get('runners'))
            )

            if not has_bookie_odds:
                print(f"[DEBUG] Skipping {venue} R{race_number} - no bookmaker odds")
                continue

            # Build combined runner data
            runners = self._combine_runner_data(
                betfair_data,
                sportsbet_data,
                amused_data,
                pointsbet_data,
                betr_data,
                promo=promo
            )

            return {
                'venue': venue,
                'country_code': country_code,
                'race_number': race_number,
                'race_name': next_race['race_name'],
                'start_time': start_time,
                'seconds_until_start': next_race['seconds_until_start'],
                'win_market_id': betfair_data.get('win_market_id'),
                'place_market_id': betfair_data.get('place_market_id'),
                'international': international,
                'promo': promo,
                'runners': runners,
                'fetched_at': datetime.now(timezone.utc)
            }

        # No race found with bookmaker coverage
        return None

    async def _fetch_sportsbet(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Dict:
        """Find and fetch Sportsbet odds for the race"""
        try:
            race = await self.sportsbet.find_race(venue, race_number, start_time, international=international)
            if race:
                return await self.sportsbet.get_race_odds(race['event_id'])
        except Exception as e:
            print(f"Sportsbet fetch error: {e}")
        return {}

    async def _fetch_amused(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Dict:
        """Find and fetch Amused odds for the race"""
        try:
            race = await self.amused.find_race(venue, race_number, start_time, international=international)
            if race:
                return await self.amused.get_race_odds(race['meet_id'], race['race_id'])
        except Exception as e:
            print(f"Amused fetch error: {e}")
        return {}

    async def _fetch_pointsbet(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Dict:
        """Find and fetch Pointsbet odds for the race"""
        try:
            race = await self.pointsbet.find_race(venue, race_number, start_time, international=international)
            if race:
                return await self.pointsbet.get_race_odds(race['race_id'])
        except Exception as e:
            print(f"Pointsbet fetch error: {e}")
        return {}

    async def _fetch_betr(self, venue: str, race_number: int, start_time: datetime, international: bool = False) -> Dict:
        """Find and fetch Betr odds for the race"""
        try:
            race = await self.betr.find_race(venue, race_number, start_time, international=international)
            if race:
                return await self.betr.get_race_odds(race['event_id'])
        except Exception as e:
            print(f"Betr fetch error: {e}")
        return {}

    def _combine_runner_data(
        self,
        betfair_data: Dict,
        sportsbet_data: Dict,
        amused_data: Dict,
        pointsbet_data: Dict,
        betr_data: Dict,
        promo: str = "2/3"
    ) -> List[Dict]:
        """
        Combine runner data from all sources and calculate EV.
        Uses Betfair as the base (for lay odds), then joins bookmaker odds.

        Args:
            promo: "2/3" for 2nd/3rd promo, "free_hit" for free hit promo
        """
        runners = []

        # Get Betfair runners as base
        betfair_runners = betfair_data.get('runners', {})

        # Index bookmaker data by horse number
        sportsbet_runners = sportsbet_data.get('runners', {})
        amused_runners = amused_data.get('runners', {})
        pointsbet_runners = pointsbet_data.get('runners', {})
        betr_runners = betr_data.get('runners', {})

        for horse_num, bf_runner in betfair_runners.items():
            # Skip scratched runners
            if bf_runner.get('status') == 'REMOVED':
                continue

            lay_win = bf_runner.get('lay_win')
            lay_win_size = bf_runner.get('lay_win_size')
            lay_place = bf_runner.get('lay_place')

            # Get bookmaker odds
            sb_runner = sportsbet_runners.get(horse_num, {})
            am_runner = amused_runners.get(horse_num, {})
            pb_runner = pointsbet_runners.get(horse_num, {})
            bt_runner = betr_runners.get(horse_num, {})

            sb_odds = sb_runner.get('win_odds') if not sb_runner.get('scratched') else None
            am_odds = am_runner.get('win_odds') if not am_runner.get('scratched') else None
            pb_odds = pb_runner.get('win_odds') if not pb_runner.get('scratched') else None
            bt_odds = bt_runner.get('win_odds') if not bt_runner.get('scratched') else None

            # Calculate EV for each bookmaker based on promo type
            if promo == "free_hit":
                sb_ev = self._calculate_ev_free_hit(sb_odds, lay_win)
                am_ev = self._calculate_ev_free_hit(am_odds, lay_win)
                pb_ev = self._calculate_ev_free_hit(pb_odds, lay_win)
                bt_ev = self._calculate_ev_free_hit(bt_odds, lay_win)
            elif promo == "bonus":
                sb_ev = self._calculate_retention_snr(sb_odds, lay_win)
                am_ev = self._calculate_retention_snr(am_odds, lay_win)
                pb_ev = self._calculate_retention_snr(pb_odds, lay_win)
                bt_ev = self._calculate_retention_snr(bt_odds, lay_win)
            else:  # Default to 2/3 promo
                sb_ev = self._calculate_ev_2nd3rd(sb_odds, lay_win, lay_place)
                am_ev = self._calculate_ev_2nd3rd(am_odds, lay_win, lay_place)
                pb_ev = self._calculate_ev_2nd3rd(pb_odds, lay_win, lay_place)
                bt_ev = self._calculate_ev_2nd3rd(bt_odds, lay_win, lay_place)

            runners.append({
                'horse_number': horse_num,
                'horse_name': bf_runner.get('horse_name', 'Unknown'),
                'lay_win': lay_win,
                'lay_win_size': lay_win_size,
                'lay_place': lay_place,
                'sportsbet': {'odds': sb_odds, 'ev': sb_ev},
                'amused': {'odds': am_odds, 'ev': am_ev},
                'pointsbet': {'odds': pb_odds, 'ev': pb_ev},
                'betr': {'odds': bt_odds, 'ev': bt_ev}
            })

        # Sort by horse number
        runners.sort(key=lambda x: x['horse_number'] or 0)

        return runners

    def _calculate_ev_2nd3rd(
        self,
        bookmaker_odds: Optional[float],
        lay_win: Optional[float],
        lay_place: Optional[float]
    ) -> Optional[float]:
        """
        Calculate EV% for 2nd/3rd promo.
        Stake back as SNR bonus if finishes 2nd or 3rd.

        EV = p1 * B + p2or3 * q - 1

        Where:
        - p1 = 1/Lw (probability of winning)
        - p_place = 1/Lp (probability of placing)
        - p2or3 = max(p_place - p1, 0) (probability of 2nd or 3rd)
        - q = retention factor (0.70)
        - B = bookmaker win odds
        """
        if not bookmaker_odds or not lay_win or not lay_place:
            return None

        try:
            p1 = 1 / lay_win
            p_place = 1 / lay_place
            p2or3 = max(p_place - p1, 0)
            ev = p1 * bookmaker_odds + p2or3 * RETENTION_FACTOR - 1
            return ev * 100
        except (ZeroDivisionError, TypeError):
            return None

    def _calculate_ev_free_hit(
        self,
        bookmaker_odds: Optional[float],
        lay_win: Optional[float]
    ) -> Optional[float]:
        """
        Calculate EV% for Free Hit promo.
        Stake back as SNR bonus if loses.

        EV = p_win * B + p_lose * q - 1

        Where:
        - p_win = 1/Lw (probability of winning)
        - p_lose = 1 - p_win (probability of losing)
        - q = retention factor (0.70)
        - B = bookmaker win odds
        """
        if not bookmaker_odds or not lay_win:
            return None

        try:
            p_win = 1 / lay_win
            p_lose = 1 - p_win
            ev = p_win * bookmaker_odds + p_lose * RETENTION_FACTOR - 1
            return ev * 100
        except (ZeroDivisionError, TypeError):
            return None

    def _calculate_retention_snr(
        self,
        bookmaker_odds: Optional[float],
        lay_win: Optional[float]
    ) -> Optional[float]:
        """
        Calculate retention % for SNR (Stake Not Returned) bonus bet.

        Retention = (Back - 1) / Lay

        This shows what percentage of the bonus bet face value
        can be extracted through matched betting.
        """
        if not bookmaker_odds or not lay_win:
            return None

        try:
            retention = (bookmaker_odds - 1) / lay_win
            return retention * 100
        except (ZeroDivisionError, TypeError):
            return None


async def test():
    """Test the aggregator"""
    agg = RaceAggregator()
    try:
        print("Finding next race and aggregating data...")
        race = await agg.get_next_race()

        if race:
            print(f"\n{race['venue']} R{race['race_number']} - {race['race_name']}")
            print(f"Starts in: {race['seconds_until_start']:.0f}s")
            print(f"Win Market: {race['win_market_id']}")
            print(f"Place Market: {race['place_market_id']}")
            print(f"\nRunners: {len(race['runners'])}")
            print("-" * 80)

            for runner in race['runners'][:5]:
                print(f"#{runner['horse_number']:2} {runner['horse_name'][:20]:20} "
                      f"Lw={runner['lay_win'] or '-':>6} Lp={runner['lay_place'] or '-':>6} | "
                      f"SB: {runner['sportsbet']['odds'] or '-':>5} ({runner['sportsbet']['ev'] or 0:+.1f}%) | "
                      f"AM: {runner['amused']['odds'] or '-':>5} ({runner['amused']['ev'] or 0:+.1f}%) | "
                      f"PB: {runner['pointsbet']['odds'] or '-':>5} ({runner['pointsbet']['ev'] or 0:+.1f}%)")
        else:
            print("No upcoming races found")

    finally:
        await agg.close()


if __name__ == "__main__":
    asyncio.run(test())
