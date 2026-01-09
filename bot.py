"""
Discord bot for racing odds and EV calculation
"""

import discord
from discord import app_commands
import sys

sys.path.append('/Users/calvinsmith/Desktop/Track Monitor')
from config import DISCORD_TOKEN
from racing import RaceAggregator
from racing.formatting import format_race_embed, format_no_race_embed


class RacingBot(discord.Client):
    """Discord bot for racing odds"""

    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.tree = app_commands.CommandTree(self)
        self.aggregator = RaceAggregator()

    async def setup_hook(self):
        pass

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

    async def close(self):
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
