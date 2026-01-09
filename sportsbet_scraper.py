#!/usr/bin/env python3
"""
Sportsbet Australia Horse Racing Scraper
Extracts event IDs, horse numbers, and win odds
"""

import subprocess
import json
import time
import urllib.parse

def curl_fetch(url):
    """Fetch URL using curl"""
    cmd = [
        'curl', '-s',
        url,
        '-H', 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        '-H', 'Accept: application/json'
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception as e:
        print(f"Curl error: {e}")
        return None

def get_australian_races(date='2026-01-08'):
    """Fetch all Australian horse racing events for a given date"""
    url = f'https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing/AllRacing/{date}'

    response = curl_fetch(url)
    if not response:
        print("Error fetching races")
        return []

    try:
        data = json.loads(response)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return []

    all_events = []

    # Navigate the structure: dates -> sections -> meetings -> events
    for date_obj in data.get('dates', []):
        for section in date_obj.get('sections', []):
            # Only get horse racing
            if section.get('raceType') != 'horse':
                continue

            for meeting in section.get('meetings', []):
                # Filter for Australian races only
                region = meeting.get('regionName', '')
                if region != 'Australia':
                    continue

                venue = meeting.get('name', 'Unknown')
                class_id = meeting.get('classId', 1)

                for event in meeting.get('events', []):
                    all_events.append({
                        'event_id': event.get('id'),
                        'venue': venue,
                        'race_number': event.get('raceNumber'),
                        'race_name': event.get('name'),
                        'start_time': event.get('startTime'),
                        'class_id': class_id,
                        'distance': event.get('distance'),
                        'status': event.get('bettingStatus')
                    })

    return all_events

def get_race_odds(event_id, class_id=1):
    """Fetch odds for a specific race"""
    url = f'https://www.sportsbet.com.au/apigw/sportsbook-racing/Sportsbook/Racing/Events/{event_id}/Markets'

    response = curl_fetch(url)
    if response:
        try:
            return json.loads(response)
        except:
            return None
    return None

def parse_runner_data(markets_data):
    """Parse market data to extract horse info and odds"""
    runners = []

    if not markets_data:
        return runners

    try:
        # Find the "Win or Place" or "Win" market
        for market in markets_data:
            market_name = market.get('name', '')
            if market_name in ['Win or Place', 'Win']:
                for selection in market.get('selections', []):
                    horse_number = selection.get('runnerNumber', 'N/A')
                    horse_name = selection.get('name', 'Unknown')
                    is_scratched = selection.get('isOut', False)

                    # Find the win price (look for "L" price code - live price)
                    win_odds = None
                    for price in selection.get('prices', []):
                        if price.get('priceCode') == 'L':
                            win_odds = price.get('winPrice')
                            break

                    # If no L price, try to get any winPrice
                    if win_odds is None:
                        for price in selection.get('prices', []):
                            if 'winPrice' in price:
                                win_odds = price.get('winPrice')
                                break

                    runners.append({
                        'horse_number': horse_number,
                        'horse_name': horse_name,
                        'win_odds': win_odds if win_odds else '-',
                        'scratched': is_scratched
                    })

                # Only use the first matching market
                break

    except Exception as e:
        print(f"Error parsing runner data: {e}")

    return runners

def main():
    print("=" * 70)
    print("SPORTSBET AUSTRALIA - HORSE RACING DATA SCRAPER")
    print("=" * 70)
    print()

    # Step 1: Get all Australian races
    print("Fetching Australian races...")
    events = get_australian_races('2026-01-08')
    print(f"Found {len(events)} races\n")

    if not events:
        print("No races found. Exiting.")
        return

    all_race_data = []

    # Step 2: Get odds for each race
    for i, event in enumerate(events, 1):
        print(f"\n{'='*70}")
        print(f"RACE {i}/{len(events)}: {event['venue']} - {event['race_name']}")
        print(f"Event ID: {event['event_id']}")
        print("-" * 70)

        markets_data = get_race_odds(event['event_id'], event['class_id'])
        runners = parse_runner_data(markets_data)

        if runners:
            print(f"{'#':<4} {'Horse Name':<30} {'Win Odds':<12}")
            print("-" * 50)

            for runner in runners:
                if not runner['scratched']:
                    odds_str = str(runner['win_odds'])
                    print(f"{runner['horse_number']:<4} {runner['horse_name'][:29]:<30} {odds_str:<12}")
                else:
                    print(f"{runner['horse_number']:<4} {runner['horse_name'][:29]:<30} SCRATCHED")

            all_race_data.append({
                'event': event,
                'runners': runners
            })
        else:
            print("No runner data available")

        # Small delay to avoid rate limiting
        time.sleep(0.3)

    print("\n" + "=" * 70)
    print(f"COMPLETE: Scraped {len(all_race_data)} races with odds data")
    print("=" * 70)

    # Save to JSON
    output_file = '/Users/calvinsmith/Desktop/Track Monitor/sportsbet_race_data.json'
    with open(output_file, 'w') as f:
        json.dump(all_race_data, f, indent=2)
    print(f"\nData saved to: {output_file}")

if __name__ == '__main__':
    main()
