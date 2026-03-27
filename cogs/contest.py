import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import os

import database as db
import osu_api as osu

CONTEST_ROLE_NAME = os.getenv("CONTEST_ROLE", "contest-submitter")

def has_contest_role():
    async def predicate(interaction: discord.Interaction):
        role = discord.utils.get(interaction.guild.roles, name=CONTEST_ROLE_NAME)
        if role and role in interaction.user.roles:
            return True
        await interaction.response.send_message(
            f"Je hebt de **{CONTEST_ROLE_NAME}** rol nodig om een map in te dienen.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)

class Contest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_db()
        self.poll_scores.start()

    def cog_unload(self):
        self.poll_scores.cancel()

    # --- /link ---
    @app_commands.command(name="link", description="Link jouw osu! account aan de bot")
    @app_commands.describe(username="Jouw osu! gebruikersnaam")
    async def link(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        user_data = await osu.get_user(username)
        if not user_data:
            await interaction.followup.send(f"Gebruiker **{username}** niet gevonden op osu!", ephemeral=True)
            return

        db.link_user(
            discord_id=interaction.user.id,
            discord_username=str(interaction.user),
            osu_username=user_data["username"],
            osu_id=user_data["id"]
        )
        await interaction.followup.send(
            f"✅ Gelinkt aan osu! account **{user_data['username']}** (#{user_data['id']})", ephemeral=True
        )

    # --- /submit ---
    @app_commands.command(name="submit", description="Dien een map in voor de maandelijkse contest")
    @app_commands.describe(map_url="Link naar de osu! beatmap (beatmapsets of /b/ URL)")
    @has_contest_role()
    async def submit(self, interaction: discord.Interaction, map_url: str):
        await interaction.response.defer()

        if db.has_submitted_this_month(interaction.user.id):
            await interaction.followup.send("❌ Je hebt deze maand al een map ingediend.", ephemeral=True)
            return

        active = db.get_active_contest()
        if active:
            await interaction.followup.send("❌ Er is al een actieve contest. Wacht tot die afloopt.", ephemeral=True)
            return

        beatmap_id = osu.parse_beatmap_id_from_url(map_url)
        if not beatmap_id:
            await interaction.followup.send("❌ Ongeldige beatmap URL. Gebruik een link van osu.ppy.sh.", ephemeral=True)
            return

        beatmap = await osu.get_beatmap(beatmap_id)
        if not beatmap:
            await interaction.followup.send("❌ Beatmap niet gevonden.", ephemeral=True)
            return

        map_name = f"{beatmap['beatmapset']['artist']} - {beatmap['beatmapset']['title']} [{beatmap['version']}]"

        # Maak een channel aan voor de contest
        guild = interaction.guild
        category = interaction.channel.category
        channel_name = f"contest-{datetime.now().strftime('%Y-%m')}"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        contest_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Contest: {map_name}"
        )

        start = datetime.now()
        end = start + timedelta(days=30)

        contest_id = db.create_contest(
            beatmap_id=beatmap_id,
            map_name=map_name,
            submitted_by=interaction.user.id,
            channel_id=contest_channel.id,
            start_date=start,
            end_date=end
        )
        db.log_map_submission(interaction.user.id)

        embed = discord.Embed(
            title="🎵 Nieuwe contest gestart!",
            description=f"**[{map_name}]({map_url})**",
            color=discord.Color.pink()
        )
        embed.add_field(name="Ingediend door", value=interaction.user.mention)
        embed.add_field(name="Eindigt op", value=f"<t:{int(end.timestamp())}:F>")
        embed.add_field(
            name="Hoe meedoen",
            value="Link je osu! account met `/link` en speel de map. De bot detecteert je score automatisch.",
            inline=False
        )
        if beatmap['beatmapset'].get('covers', {}).get('cover'):
            embed.set_image(url=beatmap['beatmapset']['covers']['cover'])

        await contest_channel.send(embed=embed)
        await interaction.followup.send(f"✅ Contest aangemaakt in {contest_channel.mention}!")

    # --- /leaderboard ---
    @app_commands.command(name="leaderboard", description="Bekijk de scores van de huidige contest")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contest = db.get_active_contest()
        if not contest:
            await interaction.followup.send("Er is geen actieve contest.", ephemeral=True)
            return

        scores = db.get_leaderboard(contest["id"])
        if not scores:
            await interaction.followup.send("Nog geen scores ingediend!", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"📊 Leaderboard — {contest['map_name']}",
            color=discord.Color.blurple()
        )
        end_ts = int(datetime.fromisoformat(contest["end_date"]).timestamp())
        embed.set_footer(text=f"Contest eindigt op")
        embed.timestamp = datetime.fromisoformat(contest["end_date"])

        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(scores):
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(
                f"{medal} **{s['osu_username']}** — {s['misscount']}x miss | {s['accuracy']:.2f}%"
            )

        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # --- /rankings ---
    @app_commands.command(name="rankings", description="Bekijk de algemene puntenstand")
    async def rankings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        board = db.get_global_leaderboard()
        if not board:
            await interaction.followup.send("Nog geen punten uitgedeeld.", ephemeral=True)
            return

        embed = discord.Embed(title="🏆 Puntenstand", color=discord.Color.gold())
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, p in enumerate(board):
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{p['osu_username']}** — {p['points']} punt{'en' if p['points'] != 1 else ''}")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed)

    # --- /endcontest (admin only) ---
    @app_commands.command(name="endcontest", description="Sluit de huidige contest handmatig af (admin)")
    @app_commands.default_permissions(administrator=True)
    async def endcontest(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._close_active_contest(manual_channel=interaction.channel)
        await interaction.followup.send("✅ Contest afgesloten.")

    # --- Polling loop ---
    @tasks.loop(minutes=5)
    async def poll_scores(self):
        contest = db.get_active_contest()
        if not contest:
            return

        # Check of contest verlopen is
        end = datetime.fromisoformat(contest["end_date"])
        if datetime.now() > end:
            await self._close_active_contest()
            return

        users = db.get_all_linked_users()
        for user in users:
            try:
                scores = await osu.get_user_scores_on_beatmap(user["osu_id"], contest["beatmap_id"])
                if not scores:
                    continue

                # Beste score = laagste misses, tiebreak op accuracy
                best = min(scores, key=lambda s: (s["statistics"].get("count_miss", 999), -s["accuracy"]))
                data = osu.extract_score_data(best)

                updated = db.upsert_score(
                    contest_id=contest["id"],
                    user_id=user["discord_id"],
                    discord_username=user["discord_username"],
                    osu_username=user["osu_username"],
                    misscount=data["misscount"],
                    accuracy=data["accuracy"],
                    score_id=data["score_id"]
                )

                if updated:
                    channel = self.bot.get_channel(contest["channel_id"])
                    if channel:
                        await channel.send(
                            f"📥 **{user['osu_username']}** heeft een score ingediend: "
                            f"**{data['misscount']}x miss** | **{data['accuracy']:.2f}%**"
                        )
            except Exception as e:
                print(f"Poll error voor {user['osu_username']}: {e}")

    @poll_scores.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _close_active_contest(self, manual_channel=None):
        contest = db.get_active_contest()
        if not contest:
            return

        scores = db.get_leaderboard(contest["id"])
        db.close_contest(contest["id"])

        channel = self.bot.get_channel(contest["channel_id"]) or manual_channel
        if not channel:
            return

        if not scores:
            await channel.send("🏁 Contest afgelopen — geen scores ingediend.")
            return

        winner = scores[0]
        db.add_point(winner["user_id"], winner["discord_username"], winner["osu_username"])

        embed = discord.Embed(
            title="🏁 Contest afgelopen!",
            description=f"**{contest['map_name']}**",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="🥇 Winnaar",
            value=f"**{winner['osu_username']}** — {winner['misscount']}x miss | {winner['accuracy']:.2f}%",
            inline=False
        )

        lines = []
        for i, s in enumerate(scores[1:], start=2):
            lines.append(f"`#{i}` {s['osu_username']} — {s['misscount']}x miss | {s['accuracy']:.2f}%")
        if lines:
            embed.add_field(name="Overige deelnemers", value="\n".join(lines), inline=False)

        winner_member = channel.guild.get_member(winner["user_id"])
        mention = winner_member.mention if winner_member else winner["osu_username"]
        await channel.send(content=f"🎉 Gefeliciteerd {mention}!", embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Contest(bot))
