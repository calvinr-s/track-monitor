#!/usr/bin/env python3
"""
Amused Australia Horse Racing Scraper
Extracts event IDs, horse numbers, and win odds
"""

import subprocess
import json
import time

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

def get_australian_races():
    """Fetch all Australian horse racing events"""
    url = 'https://api.blackstream.com.au/api/racing/v1/schedule?startDateTime=2026-01-07T13:00:00.000Z&endDateTime=2026-01-08T12:59:59.999Z&topfouroutcomes=true'

    response = curl_fetch(url)
    if not response:
        print("Error fetching schedule")
        return []

    try:
        data = json.loads(response)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return []

    all_events = []

    # Get thoroughbred races (horses)
    thoroughbred = data.get('data', {}).get('thoroughbred', [])

    for meeting in thoroughbred:
        # Filter for Australian races only
        if meeting.get('countryCode') != 'AUS':
            continue

        venue = meeting.get('venue', 'Unknown')
        meet_id = meeting.get('meetId')

        for race in meeting.get('races', []):
            all_events.append({
                'meet_id': meet_id,
                'race_id': race.get('eventId'),
                'venue': venue,
                'race_number': race.get('raceNumber'),
                'race_name': race.get('raceName'),
                'start_time': race.get('advertisedStartTime'),
                'is_open': race.get('isOpenForBetting', False)
            })

    return all_events

def get_race_odds(meet_id, race_id):
    """Fetch odds for a specific race"""
    url = f'https://api.blackstream.com.au/api/racing/v1/meetings/{meet_id}/races/{race_id}/racecard'

    response = curl_fetch(url)
    if response:
        try:
            return json.loads(response)
        except:
            return None
    return None

def parse_runner_data(race_data):
    """Parse race data to extract horse info and odds"""
    runners = []

    if not race_data:
        return runners

    try:
        race = race_data.get('data', {}).get('race', {})
        for runner in race.get('runners', []):
            horse_number = runner.get('outcomeId', 'N/A')
            horse_name = runner.get('runnerName', 'Unknown')
            is_scratched = runner.get('isScratched', False)

            # Get the last price in winPrices array (current odds)
            win_prices = runner.get('winPrices', [])
            win_odds = win_prices[-1] if win_prices else None

            runners.append({
                'horse_number': horse_number,
                'horse_name': horse_name,
                'win_odds': win_odds if win_odds else '-',
                'scratched': is_scratched
            })

    except Exception as e:
        print(f"Error parsing runner data: {e}")

    return runners

def main():
    print("=" * 70)
    print("AMUSED - HORSE RACING DATA SCRAPER")
    print("=" * 70)
    print()

    # Step 1: Get all Australian races
    print("Fetching Australian races...")
    events = get_australian_races()
    print(f"Found {len(events)} races\n")

    if not events:
        print("No races found. Exiting.")
        return

    all_race_data = []

    # Step 2: Get odds for each race
    for i, event in enumerate(events, 1):
        print(f"\n{'='*70}")
        print(f"RACE {i}/{len(events)}: {event['venue']} - {event['race_name']}")
        print(f"Race ID: {event['race_id']}")
        print("-" * 70)

        race_data = get_race_odds(event['meet_id'], event['race_id'])
        runners = parse_runner_data(race_data)

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
    output_file = '/Users/calvinsmith/Desktop/Track Monitor/amused_race_data.json'
    with open(output_file, 'w') as f:
        json.dump(all_race_data, f, indent=2)
    print(f"\nData saved to: {output_file}")

if __name__ == '__main__':
    main()
