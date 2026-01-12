"""
Discord bot for racing odds and EV calculation
"""

import asyncio
import json
import os
import discord
from discord import app_commands
from discord.ext import tasks
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')
from config import DISCORD_TOKEN
from racing import RaceAggregator
from racing.formatting import format_race_embed, format_no_race_embed
from racing.tracker import get_tracker
from racing.sources.sportsbet import SportsbetSource

# File to persist dashboard settings
DASHBOARD_FILE = os.path.join(os.path.dirname(__file__), 'dashboard_channels.json')


def load_dashboard_channels():
    """Load dashboard channel IDs from file"""
    if os.path.exists(DASHBOARD_FILE):
        try:
            with open(DASHBOARD_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {'2/3': None, 'free_hit': None, 'bonus': None}


def save_dashboard_channels(channels):
    """Save dashboard channel IDs to file"""
    with open(DASHBOARD_FILE, 'w') as f:
        json.dump(channels, f)


# Dashboard channel IDs - loaded from file
DASHBOARD_CHANNELS = load_dashboard_channels()


class RacingBot(discord.Client):
    """Discord bot for racing odds"""

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.aggregator = RaceAggregator()

        # Store dashboard message IDs for each promo type
        self.dashboard_messages = {
            '2/3': None,
            'free_hit': None,
            'bonus': None,
        }

        # Tracker for EV logging
        self.tracker = None
        self._tracked_this_session = {}  # {race_key: {timing: bool}}

    async def setup_hook(self):
        # Start the dashboard update loop
        self.dashboard_loop.start()
        # Start the tracking loop
        self.tracking_loop.start()
        # Start the results loop
        self.results_loop.start()
        # Initialize tracker
        try:
            self.tracker = get_tracker()
            print("[INFO] EV Tracker initialized")
        except Exception as e:
            print(f"[WARN] Could not initialize tracker: {e}")

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        print(f'Connected to {len(self.guilds)} servers')

        # Sync commands to guilds (instant updates)
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced commands to {guild.name}")

        # Clear global commands to remove duplicates (after copying to guilds)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        print("Cleared global commands (duplicates removed)")

        # Initialize dashboards
        await self.init_dashboards()

    async def init_dashboards(self):
        """Create or find existing dashboard messages in each channel"""
        for promo, channel_id in DASHBOARD_CHANNELS.items():
            if channel_id is None:
                continue

            channel = self.get_channel(channel_id)
            if channel is None:
                print(f"[WARN] Dashboard channel for {promo} not found: {channel_id}")
                continue

            try:
                # Look for existing bot message in channel
                async for message in channel.history(limit=10):
                    if message.author == self.user and message.embeds:
                        self.dashboard_messages[promo] = message
                        print(f"[INFO] Found existing dashboard for {promo}")
                        break

                # Create new message if none found
                if self.dashboard_messages[promo] is None:
                    embed = discord.Embed(
                        description="```\nLoading dashboard...\n```",
                        color=0x808080
                    )
                    msg = await channel.send(embed=embed)
                    self.dashboard_messages[promo] = msg
                    print(f"[INFO] Created new dashboard for {promo}")
            except discord.Forbidden:
                print(f"[ERROR] No permission for {promo} channel {channel_id} - use /setup_dashboard in that channel")
            except Exception as e:
                print(f"[ERROR] Failed to init dashboard for {promo}: {e}")

    @tasks.loop(seconds=15)
    async def dashboard_loop(self):
        """Update all dashboards every 15 seconds"""
        for promo in ['2/3', 'free_hit', 'bonus']:
            await self.update_dashboard(promo)

    @dashboard_loop.before_loop
    async def before_dashboard_loop(self):
        """Wait for bot to be ready before starting loop"""
        await self.wait_until_ready()
        # Wait a bit more for dashboards to initialize
        await asyncio.sleep(5)

    @tasks.loop(seconds=10)
    async def tracking_loop(self):
        """Track best EV opportunities at 1min and 30s before race start"""
        if not self.tracker:
            return

        for promo in ['2/3', 'free_hit']:
            await self._track_promo(promo)

    async def _track_promo(self, promo: str):
        """Track a single promo type"""
        try:
            aggregator = RaceAggregator()
            try:
                race_data = await aggregator.get_next_race(international=False, promo=promo)
            finally:
                await aggregator.close()

            if not race_data:
                return

            seconds_until = race_data.get('seconds_until_start', 0)
            race_key = f"{race_data['venue']}_R{race_data['race_number']}_{promo}"

            if race_key not in self._tracked_this_session:
                self._tracked_this_session[race_key] = {'1min': False, '30s': False}

            # Track at 1 minute (50-70 seconds window)
            if 50 <= seconds_until <= 70 and not self._tracked_this_session[race_key]['1min']:
                self.tracker.log_opportunity(race_data, "1min")
                self._tracked_this_session[race_key]['1min'] = True
                print(f"[TRACK] Logged 1min for {race_data['venue']} R{race_data['race_number']} ({promo})")

            # Track at 30 seconds (20-40 seconds window)
            if 20 <= seconds_until <= 40 and not self._tracked_this_session[race_key]['30s']:
                self.tracker.log_opportunity(race_data, "30s")
                self._tracked_this_session[race_key]['30s'] = True
                print(f"[TRACK] Logged 30s for {race_data['venue']} R{race_data['race_number']} ({promo})")

        except Exception as e:
            print(f"[ERROR] Tracking failed for {promo}: {e}")

    @tracking_loop.before_loop
    async def before_tracking_loop(self):
        """Wait for bot to be ready before starting tracking"""
        await self.wait_until_ready()
        await asyncio.sleep(10)  # Extra delay to let tracker initialize

    @tasks.loop(minutes=5)
    async def results_loop(self):
        """Check for pending results and update from Sportsbet"""
        if not self.tracker:
            return

        try:
            pending = self.tracker.get_pending_results()
            if not pending:
                return

            print(f"[RESULTS] Checking {len(pending)} pending results...")

            sportsbet = SportsbetSource()
            try:
                for race in pending:
                    try:
                        # Find race on Sportsbet
                        sb_race = await sportsbet.find_race_by_venue_and_number(
                            venue=race['venue'],
                            race_number=int(race['race']),
                            date_str=race['date']
                        )

                        if not sb_race:
                            continue

                        # Get results
                        results = await sportsbet.get_race_results(sb_race['event_id'])
                        if not results:
                            continue

                        # Find our horse's result
                        horse_info = race['horse']  # Format: "#N HorseName"
                        horse_num = int(horse_info.split()[0].replace('#', ''))

                        if horse_num in results:
                            result = results[horse_num]
                            position = result['position']

                            # Skip void/scratched horses
                            if position == -1:
                                print(f"[RESULTS] Skipping {race['venue']} R{race['race']} - #{horse_num} was void/scratched")
                                continue

                            # Update tracker
                            success = self.tracker.update_results(
                                sheet_name=race['sheet'],
                                venue=race['venue'],
                                race_num=int(race['race']),
                                date_str=race['date'],
                                position=position
                            )

                            if success:
                                pos_str = {1: '1st', 2: '2nd/3rd', 0: '4th+'}
                                print(f"[RESULTS] Updated {race['venue']} R{race['race']} - #{horse_num} finished {pos_str.get(position, position)}")

                    except Exception as e:
                        print(f"[RESULTS] Error processing {race['venue']} R{race['race']}: {e}")

            finally:
                await sportsbet.close()

        except Exception as e:
            print(f"[RESULTS] Loop error: {e}")

    @results_loop.before_loop
    async def before_results_loop(self):
        """Wait for bot to be ready before checking results"""
        await self.wait_until_ready()
        await asyncio.sleep(60)  # Wait 1 minute before first check

    async def update_dashboard(self, promo: str):
        """Update a single dashboard"""
        message = self.dashboard_messages.get(promo)
        if message is None:
            return

        try:
            # Create fresh aggregator to avoid session issues
            aggregator = RaceAggregator()
            try:
                race_data = await aggregator.get_next_race(international=False, promo=promo)
            finally:
                await aggregator.close()

            if race_data is None:
                embed_data = format_no_race_embed()
            else:
                embed_data = format_race_embed(race_data)

            embed = discord.Embed(
                description=embed_data.get('description', ''),
                color=embed_data.get('color', 0x808080)
            )

            if embed_data.get('title'):
                embed.title = embed_data['title']

            await message.edit(embed=embed)

        except discord.NotFound:
            # Message was deleted, recreate it
            channel_id = DASHBOARD_CHANNELS.get(promo)
            if channel_id:
                channel = self.get_channel(channel_id)
                if channel:
                    embed = discord.Embed(
                        description="```\nReconnecting...\n```",
                        color=0x808080
                    )
                    msg = await channel.send(embed=embed)
                    self.dashboard_messages[promo] = msg
        except Exception as e:
            print(f"[ERROR] Dashboard update failed for {promo}: {e}")

    async def close(self):
        self.dashboard_loop.cancel()
        self.tracking_loop.cancel()
        self.results_loop.cancel()
        await self.aggregator.close()
        await super().close()


bot = RacingBot()


@bot.tree.command(name="next", description="Get the next race with promo EV calculations")
@app_commands.describe(promo="Select the promo type")
@app_commands.choices(promo=[
    app_commands.Choice(name="2nd/3rd - Stake back as bonus if 2nd or 3rd", value="2/3"),
    app_commands.Choice(name="Free Hit - Stake back as bonus if loses", value="free_hit"),
    app_commands.Choice(name="Bonus - SNR bonus bet retention (30%+)", value="bonus"),
])
async def next_race(interaction: discord.Interaction, promo: app_commands.Choice[str]):
    """Get the next race with promo EV"""
    await interaction.response.defer()

    try:
        print(f"[DEBUG] /next command called with promo={promo.value}")

        # Create fresh aggregator for each request to avoid session issues
        aggregator = RaceAggregator()
        try:
            race_data = await aggregator.get_next_race(international=False, promo=promo.value)
        finally:
            await aggregator.close()

        print(f"[DEBUG] race_data is None: {race_data is None}")
        if race_data:
            print(f"[DEBUG] Found: {race_data['venue']} R{race_data['race_number']}, {len(race_data['runners'])} runners")

        if race_data is None:
            embed_data = format_no_race_embed()
        else:
            embed_data = format_race_embed(race_data)

        embed = discord.Embed(
            description=embed_data.get('description', ''),
            color=embed_data.get('color', 0x808080)
        )

        if embed_data.get('title'):
            embed.title = embed_data['title']

        await interaction.followup.send(embed=embed)

    except Exception as e:
        import traceback
        print(f"[ERROR] Exception in /next command:")
        traceback.print_exc()
        embed = discord.Embed(
            title='Error',
            description=f"An error occurred: {str(e)}",
            color=0xFF0000
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="setup_dashboard", description="Set current channel as dashboard for a promo type")
@app_commands.describe(promo="Select the promo type for this dashboard")
@app_commands.choices(promo=[
    app_commands.Choice(name="2nd/3rd", value="2/3"),
    app_commands.Choice(name="Free Hit", value="free_hit"),
    app_commands.Choice(name="Bonus", value="bonus"),
])
async def setup_dashboard(interaction: discord.Interaction, promo: app_commands.Choice[str]):
    """Set current channel as a dashboard"""
    channel_id = interaction.channel_id

    # Update the dashboard channel and save to file
    DASHBOARD_CHANNELS[promo.value] = channel_id
    save_dashboard_channels(DASHBOARD_CHANNELS)

    # Create initial message
    embed = discord.Embed(
        description="```\nInitializing dashboard...\n```",
        color=0x808080
    )
    await interaction.response.send_message(embed=embed)

    # Get the message we just sent
    msg = await interaction.original_response()
    bot.dashboard_messages[promo.value] = msg

    # Trigger immediate update
    await bot.update_dashboard(promo.value)

    print(f"[INFO] Dashboard set for {promo.value} in channel {channel_id}")


@bot.tree.command(name="test", description="Show sample formatted output with colors")
async def test_format(interaction: discord.Interaction):
    """Show sample formatted output demonstrating alignment and colors"""
    from racing.formatting import (
        _format_bookie_name, _format_horse_num, _format_ev, _format_odds,
        _pad_right, _pad_left, COL_BOOKIE, COL_NUM, COL_EV, COL_ODDS
    )

    # Build sample data rows
    sample_rows = [
        ('amused', 8, -5.0, 2.40, 2.80),
        ('amused', 11, 12.0, 15.00, 10.00),
        ('betr', 8, -5.0, 2.40, 2.80),
        ('betr', 11, 15.0, 16.00, 10.00),
        ('pointsbet', 8, -3.0, 2.50, 2.80),
        ('pointsbet', 11, 8.0, 14.00, 10.00),
        ('sportsbet', 8, -8.0, 2.30, 2.80),
        ('sportsbet', 11, 11.0, 15.00, 10.00),
    ]

    lines = [
        "2h 15m 30s  Sandown R1 (9)",
        "",
        "Promo 2nd/3rd",
        "",
    ]

    # Header
    header = (
        f"{_pad_right('Bookie', COL_BOOKIE)} "
        f"{_pad_left('No', COL_NUM)}  "
        f"{_pad_left('EV %', COL_EV)}  "
        f"{_pad_left('Back', COL_ODDS)}  "
        f"{_pad_left('Lay', COL_ODDS)}"
    )
    lines.append(header)

    total_width = COL_BOOKIE + 1 + COL_NUM + 2 + COL_EV + 2 + COL_ODDS + 2 + COL_ODDS
    lines.append("-" * total_width)

    # Data rows
    current_bookie = None
    for bookie, num, ev, back, lay in sample_rows:
        if current_bookie and bookie != current_bookie:
            lines.append("")
        current_bookie = bookie

        line = (
            f"{_format_bookie_name(bookie)} "
            f"{_format_horse_num(num)}  "
            f"{_format_ev(ev)}  "
            f"{_format_odds(back)}  "
            f"{_format_odds(lay)}"
        )
        lines.append(line)

    description = "```ansi\n" + "\n".join(lines) + "\n```"

    embed = discord.Embed(
        description=description,
        color=0x00FF00
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stats", description="Show EV tracking statistics")
@app_commands.describe(sheet="Filter by specific sheet (optional)")
@app_commands.choices(sheet=[
    app_commands.Choice(name="All Sheets", value="all"),
    app_commands.Choice(name="2/3 - 1 min", value="2/3-1min"),
    app_commands.Choice(name="2/3 - 30s", value="2/3-30s"),
    app_commands.Choice(name="Free Hit - 1 min", value="FreeHit-1min"),
    app_commands.Choice(name="Free Hit - 30s", value="FreeHit-30s"),
])
async def stats_command(interaction: discord.Interaction, sheet: app_commands.Choice[str] = None):
    """Show EV tracking statistics from Google Sheets"""
    await interaction.response.defer()

    try:
        tracker = get_tracker()
        sheet_name = None if (sheet is None or sheet.value == "all") else sheet.value
        stats = tracker.get_stats(sheet_name)

        if 'error' in stats:
            embed = discord.Embed(
                title="Stats Error",
                description=f"Could not fetch stats: {stats['error']}",
                color=0xFF0000
            )
            await interaction.followup.send(embed=embed)
            return

        # Build stats display
        lines = []
        lines.append(f"Total Races Tracked: {stats['total_races']}")
        lines.append(f"Races with Results: {stats['with_results']}")
        lines.append("")

        if stats['with_results'] > 0:
            win_rate = stats['wins'] / stats['with_results'] * 100
            lines.append(f"Wins (1st): {stats['wins']} ({win_rate:.1f}%)")
            lines.append(f"Places (2nd/3rd): {stats['places']}")
            lines.append(f"Losses (4th+): {stats['losses']}")
            lines.append("")

        if stats['total_races'] > 0:
            lines.append("Average EV%:")
            lines.append(f"  No Lay:    {stats['avg_ev_no_lay']:+.1f}%")
            lines.append(f"  Half Lay:  {stats['avg_ev_half_lay']:+.1f}%")
            lines.append(f"  Full Lay:  {stats['avg_ev_full_lay']:+.1f}%")
            lines.append("")

        if stats['with_results'] > 0:
            lines.append("Total P/L (units):")
            lines.append(f"  No Lay:    {stats['total_pl_no_lay']:+.2f}")
            lines.append(f"  Half Lay:  {stats['total_pl_half_lay']:+.2f}")
            lines.append(f"  Full Lay:  {stats['total_pl_full_lay']:+.2f}")

        # Per-sheet breakdown
        if stats.get('by_sheet') and len(stats['by_sheet']) > 1:
            lines.append("")
            lines.append("By Sheet:")
            for sn, ss in stats['by_sheet'].items():
                if ss['races'] > 0:
                    lines.append(f"  {sn}: {ss['races']} races, P/L={ss['pl_no_lay']:+.2f} (no lay)")

        description = "```\n" + "\n".join(lines) + "\n```"

        embed = discord.Embed(
            title="EV Tracking Stats",
            description=description,
            color=0x00FF00 if stats.get('total_pl_no_lay', 0) >= 0 else 0xFF6600
        )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        import traceback
        print(f"[ERROR] Stats command failed:")
        traceback.print_exc()
        embed = discord.Embed(
            title="Error",
            description=f"Failed to get stats: {str(e)}",
            color=0xFF0000
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="update_result", description="Manually update a race result")
@app_commands.describe(
    sheet="Which tracking sheet",
    venue="Venue name (exact match)",
    race="Race number",
    date="Date YYYY-MM-DD",
    position="Finishing position"
)
@app_commands.choices(sheet=[
    app_commands.Choice(name="2/3 - 1 min", value="2/3-1min"),
    app_commands.Choice(name="2/3 - 30s", value="2/3-30s"),
    app_commands.Choice(name="Free Hit - 1 min", value="FreeHit-1min"),
    app_commands.Choice(name="Free Hit - 30s", value="FreeHit-30s"),
])
@app_commands.choices(position=[
    app_commands.Choice(name="1st (Winner)", value=1),
    app_commands.Choice(name="2nd", value=2),
    app_commands.Choice(name="3rd", value=3),
    app_commands.Choice(name="4th or worse", value=0),
])
async def update_result(
    interaction: discord.Interaction,
    sheet: app_commands.Choice[str],
    venue: str,
    race: int,
    date: str,
    position: app_commands.Choice[int]
):
    """Manually update a race result in the tracking sheet"""
    await interaction.response.defer()

    try:
        tracker = get_tracker()
        success = tracker.update_results(
            sheet_name=sheet.value,
            venue=venue,
            race_num=race,
            date_str=date,
            position=position.value
        )

        if success:
            embed = discord.Embed(
                title="Result Updated",
                description=f"Updated {venue} R{race} on {date} to position {position.name}",
                color=0x00FF00
            )
        else:
            embed = discord.Embed(
                title="Not Found",
                description=f"Could not find {venue} R{race} on {date} in {sheet.value}",
                color=0xFF6600
            )

        await interaction.followup.send(embed=embed)

    except Exception as e:
        embed = discord.Embed(
            title="Error",
            description=f"Failed to update: {str(e)}",
            color=0xFF0000
        )
        await interaction.followup.send(embed=embed)


def main():
    if DISCORD_TOKEN == "YOUR_DISCORD_TOKEN_HERE":
        print("Error: Please set your Discord token in config.py")
        return

    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("Error: Invalid Discord token")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
