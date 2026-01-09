#!/usr/bin/env python3
"""
Betfair Australia Horse Racing Scraper
Extracts event IDs, horse numbers, back/lay odds, and liquidity
Uses curl to bypass Cloudflare protection
"""

import subprocess
import json
import time
import urllib.parse

def curl_fetch(url, params=None):
    """Fetch URL using curl to bypass Cloudflare"""
    if params:
        # Build URL with params
        query_string = '&'.join([f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()])
        full_url = f"{url}?{query_string}"
    else:
        full_url = url

    cmd = [
        'curl', '-s',
        full_url,
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        '-H', 'Accept: application/json',
        '-H', 'Referer: https://www.betfair.com.au/',
        '-H', 'Origin: https://www.betfair.com.au'
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        print(f"Curl error: {e}")
        return None

def get_australian_races():
    """Fetch all Australian horse racing events"""
    url = 'https://apieds.betfair.com.au/api/eds/meeting-races/v4'
    params = {
        '_ak': 'nzIFcwyWhrlwYMrh',
        'countriesGroup': '[["AU"]]',
        'countriesList': '["AU"]',
        'eventTypeId': '7',
        'marketStartingAfter': '2026-01-07T13:00:00.000Z',
        'marketStartingBefore': '2026-01-08T12:59:59.999Z'
    }

    response = curl_fetch(url, params)
    if not response:
        print("Error fetching races")
        return []

    try:
        data = json.loads(response)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        print(f"Response: {response[:500]}")
        return []

    all_markets = []
    for country in data:
        for meeting in country.get('meetings', []):
            venue = meeting.get('venue', 'Unknown')
            meeting_id = meeting.get('meetingId')
            for race in meeting.get('races', []):
                all_markets.append({
                    'venue': venue,
                    'meeting_id': meeting_id,
                    'race_number': race.get('raceNumber'),
                    'race_name': race.get('marketName'),
                    'market_id': race.get('marketId'),
                    'start_time': race.get('startTime')
                })

    return all_markets

def get_race_odds(market_id):
    """Fetch odds and liquidity for a specific race"""
    url = 'https://ero.betfair.com.au/www/sports/exchange/readonly/v1/bymarket'
    params = {
        '_ak': 'nzIFcwyWhrlwYMrh',
        'currencyCode': 'AUD',
        'marketIds': market_id,
        'rollupLimit': '5',
        'rollupModel': 'STAKE',
        'types': 'MARKET_STATE,RUNNER_STATE,RUNNER_EXCHANGE_PRICES_BEST,RUNNER_DESCRIPTION'
    }

    response = curl_fetch(url, params)
    if response:
        try:
            return json.loads(response)
        except:
            return None
    return None

def parse_runner_data(odds_data):
    """Parse runner data to extract horse info, odds, and liquidity"""
    runners = []

    if not odds_data:
        return runners

    try:
        event_types = odds_data.get('eventTypes', [])
        for et in event_types:
            for event_node in et.get('eventNodes', []):
                for market_node in event_node.get('marketNodes', []):
                    for runner in market_node.get('runners', []):
                        runner_name = runner.get('description', {}).get('runnerName', 'Unknown')

                        # Extract horse number from name (e.g., "1. Diamond Flash One" -> 1)
                        horse_number = runner_name.split('.')[0].strip() if '.' in runner_name else 'N/A'
                        horse_name = runner_name.split('.', 1)[1].strip() if '.' in runner_name else runner_name

                        exchange = runner.get('exchange', {})

                        # Back prices (what you can bet on)
                        back_prices = exchange.get('availableToBack', [])
                        best_back = back_prices[0] if back_prices else {'price': '-', 'size': 0}

                        # Lay prices (what you can bet against)
                        lay_prices = exchange.get('availableToLay', [])
                        best_lay = lay_prices[0] if lay_prices else {'price': '-', 'size': 0}

                        # Total liquidity (sum of all available)
                        back_liquidity = sum(p.get('size', 0) for p in back_prices)
                        lay_liquidity = sum(p.get('size', 0) for p in lay_prices)

                        runners.append({
                            'horse_number': horse_number,
                            'horse_name': horse_name,
                            'back_odds': best_back.get('price', '-'),
                            'back_size': best_back.get('size', 0),
                            'lay_odds': best_lay.get('price', '-'),
                            'lay_size': best_lay.get('size', 0),
                            'back_liquidity': round(back_liquidity, 2),
                            'lay_liquidity': round(lay_liquidity, 2),
                            'status': runner.get('state', {}).get('status', 'Unknown')
                        })
    except Exception as e:
        print(f"Error parsing runner data: {e}")

    return runners

def main():
    print("=" * 80)
    print("BETFAIR AUSTRALIA - HORSE RACING DATA SCRAPER")
    print("=" * 80)
    print()

    # Step 1: Get all Australian races
    print("Fetching Australian races...")
    markets = get_australian_races()
    print(f"Found {len(markets)} races\n")

    if not markets:
        print("No races found. Exiting.")
        return

    all_race_data = []

    # Step 2: Get odds for each race
    for i, market in enumerate(markets, 1):
        print(f"\n{'='*80}")
        print(f"RACE {i}/{len(markets)}: {market['venue']} - {market['race_name']}")
        print(f"Market ID: {market['market_id']}")
        print(f"Start Time: {market['start_time']}")
        print("-" * 80)

        odds_data = get_race_odds(market['market_id'])
        runners = parse_runner_data(odds_data)

        if runners:
            print(f"{'#':<4} {'Horse Name':<25} {'Back Odds':<12} {'Back Liq':<12} {'Lay Odds':<12} {'Lay Liq':<12}")
            print("-" * 80)

            for runner in runners:
                if runner['status'] == 'ACTIVE':
                    back_odds_str = str(runner['back_odds'])
                    lay_odds_str = str(runner['lay_odds'])
                    print(f"{runner['horse_number']:<4} {runner['horse_name'][:24]:<25} "
                          f"{back_odds_str:<12} ${runner['back_size']:<11.2f} "
                          f"{lay_odds_str:<12} ${runner['lay_size']:<11.2f}")

            all_race_data.append({
                'market': market,
                'runners': runners
            })
        else:
            print("No runner data available")

        # Small delay to avoid rate limiting
        time.sleep(0.5)

    print("\n" + "=" * 80)
    print(f"COMPLETE: Scraped {len(all_race_data)} races with odds data")
    print("=" * 80)

    # Save to JSON
    output_file = '/Users/calvinsmith/Desktop/Track Monitor/betfair_race_data.json'
    with open(output_file, 'w') as f:
        json.dump(all_race_data, f, indent=2)
    print(f"\nData saved to: {output_file}")

if __name__ == '__main__':
    main()
