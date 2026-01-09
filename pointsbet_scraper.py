#!/usr/bin/env python3
"""
Pointsbet Australia Horse Racing Scraper
Extracts event IDs, horse numbers, and win odds (current)
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
    url = 'https://api.au.pointsbet.com/api/racing/v4/meetings?startDate=2026-01-08T00:00:00.000Z&endDate=2026-01-09T00:00:00.000Z'

    response = curl_fetch(url)
    if not response:
        print("Error fetching meetings")
        return []

    try:
        data = json.loads(response)
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return []

    all_events = []

    for group in data:
        for meeting in group.get('meetings', []):
            # Filter for Australian races only
            if meeting.get('countryCode') != 'AUS':
                continue

            # Filter for horse racing (racingType 1)
            if meeting.get('racingType') != 1:
                continue

            venue = meeting.get('venue', 'Unknown')
            meeting_id = meeting.get('meetingId')

            for race in meeting.get('races', []):
                all_events.append({
                    'meeting_id': meeting_id,
                    'race_id': race.get('raceId'),
                    'venue': venue,
                    'race_number': race.get('raceNumber'),
                    'race_name': race.get('name'),
                    'start_time': race.get('advertisedStartDateTimeUtc')
                })

    return all_events

def get_race_odds(race_id):
    """Fetch odds for a specific race"""
    url = f'https://api.au.pointsbet.com/api/racing/v3/races/{race_id}'

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
        for runner in race_data.get('runners', []):
            horse_number = runner.get('number', 'N/A')
            horse_name = runner.get('runnerName', 'Unknown')
            is_scratched = runner.get('isScratched', False)

            # Get current odds from fluctuations
            fluctuations = runner.get('fluctuations', {})
            win_odds = fluctuations.get('current')

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
    print("POINTSBET - HORSE RACING DATA SCRAPER")
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

        race_data = get_race_odds(event['race_id'])
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
    output_file = '/Users/calvinsmith/Desktop/Track Monitor/pointsbet_race_data.json'
    with open(output_file, 'w') as f:
        json.dump(all_race_data, f, indent=2)
    print(f"\nData saved to: {output_file}")

if __name__ == '__main__':
    main()
