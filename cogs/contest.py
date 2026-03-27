import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import os

import database as db
import osu_api as osu
from mods import parse_mods, is_banned, get_category, mods_display, MOD_CATEGORIES, MOD_COLORS, MOD_LABELS

CONTEST_ROLE_NAME = os.getenv("CONTEST_ROLE", "contest-submitter")
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE", "contest-admin")

# ── Kleuren ────────────────────────────────────────────────────────────────
COLOR_PINK    = 0xFF69B4
COLOR_GOLD    = 0xFFD700
COLOR_PURPLE  = 0x9B59B6
COLOR_DARK    = 0x2B2D31

# ── Checks ─────────────────────────────────────────────────────────────────
def has_contest_role():
    async def predicate(interaction: discord.Interaction):
        role = discord.utils.get(interaction.guild.roles, name=CONTEST_ROLE_NAME)
        if role and role in interaction.user.roles:
            return True
        await interaction.response.send_message(
            f"❌ Je hebt de **{CONTEST_ROLE_NAME}** rol nodig om dit te doen.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)

def has_admin_role():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.guild_permissions.administrator:
            return True
        role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
        if role and role in interaction.user.roles:
            return True
        await interaction.response.send_message(
            f"❌ Je hebt de **{ADMIN_ROLE_NAME}** rol of administrator rechten nodig.", ephemeral=True
        )
        return False
    return app_commands.check(predicate)

# ── Embed helpers ───────────────────────────────────────────────────────────
def make_contest_embed(contest: dict, beatmap: dict = None) -> discord.Embed:
    end = datetime.fromisoformat(contest["end_date"])
    start = datetime.fromisoformat(contest["start_date"])

    embed = discord.Embed(
        title="🎵  Nieuwe contest gestart!",
        description=f"### [{contest['map_name']}]({contest['map_url']})",
        color=COLOR_PINK,
    )
    embed.add_field(name="📅 Start", value=f"<t:{int(start.timestamp())}:D>", inline=True)
    embed.add_field(name="⏳ Eindigt", value=f"<t:{int(end.timestamp())}:R>", inline=True)
    embed.add_field(name="📆 Datum", value=f"<t:{int(end.timestamp())}:F>", inline=True)
    embed.add_field(
        name="🎯 Mod categorieën",
        value="NM · HR · DT · FL\nHD en NF tellen transparant mee.",
        inline=False
    )
    embed.add_field(
        name="📥 Meedoen",
        value="Koppel je account met `/link` en speel de map gewoon.\nDe bot pikt je score automatisch op binnen 5 minuten.",
        inline=False
    )
    embed.set_footer(text="Verboden mods: HalfTime · Relax · AutoPilot")
    if contest.get("cover_url"):
        embed.set_image(url=contest["cover_url"])
    return embed

def make_leaderboard_embed(contest: dict, scores_by_cat: dict) -> list[discord.Embed]:
    embeds = []
    medals = ["🥇", "🥈", "🥉"]
    end = datetime.fromisoformat(contest["end_date"])

    for cat in MOD_CATEGORIES:
        scores = scores_by_cat.get(cat, [])
        color = MOD_COLORS.get(cat, 0xFFFFFF)
        label = MOD_LABELS.get(cat, cat)

        embed = discord.Embed(
            title=f"{'🏆' if cat == 'NM' else '📊'}  {label}",
            color=color,
        )

        if not scores:
            embed.description = "*Nog geen scores in deze categorie.*"
        else:
            lines = []
            for i, s in enumerate(scores):
                medal = medals[i] if i < 3 else f"`#{i+1}`"
                lines.append(
                    f"{medal} **{s['osu_username']}** `{s['mods_display']}`\n"
                    f"　{s['misscount']}x miss · {s['accuracy']:.2f}%"
                )
            embed.description = "\n".join(lines)

        if cat == "FL":
            embed.set_footer(text=f"Contest — {contest['map_name']} · eindigt")
            embed.timestamp = end

        embeds.append(embed)
    return embeds

def make_winner_embed(contest: dict, winners_by_cat: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🏁  Contest afgelopen!",
        description=f"### [{contest['map_name']}]({contest['map_url']})",
        color=COLOR_GOLD,
    )
    if contest.get("cover_url"):
        embed.set_thumbnail(url=contest["cover_url"])

    for cat in MOD_CATEGORIES:
        winner = winners_by_cat.get(cat)
        label = MOD_LABELS.get(cat, cat)
        if winner:
            embed.add_field(
                name=f"🥇 {label}",
                value=f"**{winner['osu_username']}**\n{winner['misscount']}x miss · {winner['accuracy']:.2f}%",
                inline=True
            )
        else:
            embed.add_field(name=f"— {label}", value="*Geen scores*", inline=True)

    embed.set_footer(text="Punten zijn bijgewerkt in /rankings")
    return embed

# ── Cog ─────────────────────────────────────────────────────────────────────
class Contest(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        db.init_db()
        self.poll_scores.start()

    def cog_unload(self):
        self.poll_scores.cancel()

    # /link
    @app_commands.command(name="link", description="Koppel je osu! account aan de bot")
    @app_commands.describe(username="Jouw osu! gebruikersnaam")
    async def link(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        user_data = await osu.get_user(username)
        if not user_data:
            await interaction.followup.send(f"❌ Gebruiker **{username}** niet gevonden op osu!", ephemeral=True)
            return

        db.link_user(
            discord_id=interaction.user.id,
            discord_username=str(interaction.user),
            osu_username=user_data["username"],
            osu_id=user_data["id"]
        )

        embed = discord.Embed(
            title="✅  Account gekoppeld",
            description=f"Je Discord is nu gelinkt aan **{user_data['username']}**.",
            color=COLOR_PINK,
        )
        embed.set_thumbnail(url=user_data.get("avatar_url", ""))
        embed.set_footer(text=f"osu! ID: {user_data['id']}")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # /submit
    @app_commands.command(name="submit", description="Dien een map in voor de tweewekelijkse contest")
    @app_commands.describe(map_url="Link naar de osu! beatmap")
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
            await interaction.followup.send("❌ Ongeldige beatmap URL.", ephemeral=True)
            return

        beatmap = await osu.get_beatmap(beatmap_id)
        if not beatmap:
            await interaction.followup.send("❌ Beatmap niet gevonden.", ephemeral=True)
            return

        map_name = f"{beatmap['beatmapset']['artist']} - {beatmap['beatmapset']['title']} [{beatmap['version']}]"
        cover_url = beatmap["beatmapset"].get("covers", {}).get("cover@2x") or beatmap["beatmapset"].get("covers", {}).get("cover")

        guild = interaction.guild
        category = interaction.channel.category
        channel_name = f"contest-{datetime.now().strftime('%Y-%m')}"

        contest_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites={guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)},
            topic=f"🎵 Contest: {map_name}"
        )

        start = datetime.now()
        end = start + timedelta(weeks=2)

        contest_id = db.create_contest(
            beatmap_id=beatmap_id,
            map_name=map_name,
            map_url=map_url,
            cover_url=cover_url,
            submitted_by=interaction.user.id,
            channel_id=contest_channel.id,
            start_date=start,
            end_date=end
        )
        db.log_map_submission(interaction.user.id)

        contest = db.get_contest_by_id(contest_id)
        embed = make_contest_embed(contest)
        await contest_channel.send(embed=embed)
        await interaction.followup.send(f"✅ Contest aangemaakt in {contest_channel.mention}!")

    # /leaderboard
    @app_commands.command(name="leaderboard", description="Bekijk de scores van de huidige contest")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contest = db.get_active_contest()
        if not contest:
            await interaction.followup.send("❌ Er is geen actieve contest.", ephemeral=True)
            return

        scores_by_cat = db.get_all_scores_for_contest(contest["id"])
        embeds = make_leaderboard_embed(contest, scores_by_cat)

        end = datetime.fromisoformat(contest["end_date"])
        header = discord.Embed(
            title=f"📊  Leaderboard",
            description=f"**[{contest['map_name']}]({contest['map_url']})**\nEindigt <t:{int(end.timestamp())}:R>",
            color=COLOR_PURPLE,
        )
        if contest.get("cover_url"):
            header.set_thumbnail(url=contest["cover_url"])

        await interaction.followup.send(embeds=[header] + embeds)

    # /rankings
    @app_commands.command(name="rankings", description="Bekijk de totale puntenstand")
    async def rankings(self, interaction: discord.Interaction):
        await interaction.response.defer()
        board = db.get_global_leaderboard()

        embed = discord.Embed(title="🏆  Puntenstand", color=COLOR_GOLD)
        if not board:
            embed.description = "*Nog geen punten uitgedeeld.*"
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, p in enumerate(board):
                medal = medals[i] if i < 3 else f"`#{i+1}`"
                pts = p["points"]
                lines.append(f"{medal} **{p['osu_username']}** — {pts} punt{'en' if pts != 1 else ''}")
            embed.description = "\n".join(lines)

        embed.set_footer(text="Punten worden uitgedeeld per mod categorie")
        await interaction.followup.send(embed=embed)

    # /contestinfo
    @app_commands.command(name="contestinfo", description="Bekijk info over de huidige contest")
    async def contestinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contest = db.get_active_contest()
        if not contest:
            await interaction.followup.send("❌ Er is geen actieve contest.", ephemeral=True)
            return

        embed = make_contest_embed(contest)
        embed.title = "📋  Actieve contest"
        await interaction.followup.send(embed=embed)

    # ── Admin commands ──────────────────────────────────────────────────────

    # /endcontest
    @app_commands.command(name="endcontest", description="[Admin] Sluit de huidige contest vroegtijdig af")
    @has_admin_role()
    async def endcontest(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contest = db.get_active_contest()
        if not contest:
            await interaction.followup.send("❌ Geen actieve contest.", ephemeral=True)
            return
        await self._close_contest(contest, manual_channel=interaction.channel)
        await interaction.followup.send("✅ Contest afgesloten en winnaar bepaald.")

    # /cancelcontest
    @app_commands.command(name="cancelcontest", description="[Admin] Annuleer de huidige contest zonder winnaar")
    @has_admin_role()
    async def cancelcontest(self, interaction: discord.Interaction):
        await interaction.response.defer()
        contest = db.get_active_contest()
        if not contest:
            await interaction.followup.send("❌ Geen actieve contest.", ephemeral=True)
            return

        db.close_contest(contest["id"])
        channel = self.bot.get_channel(contest["channel_id"])

        embed = discord.Embed(
            title="🚫  Contest geannuleerd",
            description=f"**{contest['map_name']}**\nDeze contest is handmatig gestopt. Er worden geen punten uitgedeeld.",
            color=discord.Color.red()
        )
        if channel:
            await channel.send(embed=embed)
        await interaction.followup.send("✅ Contest geannuleerd zonder winnaar.")

    # /deletecontest
    @app_commands.command(name="deletecontest", description="[Admin] Verwijder een contest en alle bijbehorende scores permanent")
    @app_commands.describe(contest_id="Het ID van de contest (zie /listcontests)")
    @has_admin_role()
    async def deletecontest(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer(ephemeral=True)
        contest = db.get_contest_by_id(contest_id)
        if not contest:
            await interaction.followup.send(f"❌ Contest #{contest_id} niet gevonden.", ephemeral=True)
            return

        db.delete_contest(contest_id)
        await interaction.followup.send(
            f"✅ Contest **#{contest_id} — {contest['map_name']}** en alle scores zijn verwijderd.",
            ephemeral=True
        )

    # /listcontests
    @app_commands.command(name="listcontests", description="[Admin] Bekijk alle contests")
    @has_admin_role()
    async def listcontests(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        contests = db.get_all_contests()
        if not contests:
            await interaction.followup.send("Nog geen contests.", ephemeral=True)
            return

        embed = discord.Embed(title="📋  Alle contests", color=COLOR_PURPLE)
        lines = []
        for c in contests[:20]:
            status = "🟢 Actief" if c["active"] else "🔴 Gesloten"
            lines.append(f"`#{c['id']}` {status} — **{c['map_name']}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── Polling loop ────────────────────────────────────────────────────────
    @tasks.loop(minutes=5)
    async def poll_scores(self):
        contest = db.get_active_contest()
        if not contest:
            return

        end = datetime.fromisoformat(contest["end_date"])
        if datetime.now() > end:
            await self._close_contest(contest)
            return

        users = db.get_all_linked_users()
        for user in users:
            try:
                raw_scores = await osu.get_user_scores_on_beatmap(user["osu_id"], contest["beatmap_id"])
                if not raw_scores:
                    continue

                # Groepeer per mod categorie, houd beste score per categorie bij
                best_per_cat: dict[str, dict] = {}
                for score in raw_scores:
                    mods_list = [m["acronym"] for m in score.get("mods", [])] if isinstance(score.get("mods"), list) else score.get("mods", [])
                    mods = parse_mods(mods_list)

                    if is_banned(mods):
                        continue

                    cat = get_category(mods)
                    if cat is None:
                        continue

                    miss = score["statistics"].get("count_miss", 0)
                    acc = round(score.get("accuracy", 0) * 100, 2)

                    if cat not in best_per_cat:
                        best_per_cat[cat] = score
                    else:
                        prev = best_per_cat[cat]
                        prev_miss = prev["statistics"].get("count_miss", 0)
                        prev_acc = round(prev.get("accuracy", 0) * 100, 2)
                        if miss < prev_miss or (miss == prev_miss and acc > prev_acc):
                            best_per_cat[cat] = score

                for cat, score in best_per_cat.items():
                    mods_list = [m["acronym"] for m in score.get("mods", [])] if isinstance(score.get("mods"), list) else score.get("mods", [])
                    miss = score["statistics"].get("count_miss", 0)
                    acc = round(score.get("accuracy", 0) * 100, 2)
                    score_id = score.get("id", 0)
                    mod_str = mods_display(mods_list)

                    updated = db.upsert_score(
                        contest_id=contest["id"],
                        user_id=user["discord_id"],
                        discord_username=user["discord_username"],
                        osu_username=user["osu_username"],
                        misscount=miss,
                        accuracy=acc,
                        score_id=score_id,
                        mod_category=cat,
                        mods_display=mod_str,
                    )

                    if updated:
                        channel = self.bot.get_channel(contest["channel_id"])
                        if channel:
                            from mods import MOD_LABELS
                            label = MOD_LABELS.get(cat, cat)
                            embed = discord.Embed(
                                description=f"**{user['osu_username']}** heeft een nieuwe beste score in **{label}**\n`{mod_str}` · {miss}x miss · {acc:.2f}%",
                                color=MOD_COLORS.get(cat, COLOR_PINK)
                            )
                            await channel.send(embed=embed)

            except Exception as e:
                print(f"[Poll] Fout voor {user['osu_username']}: {e}")

    @poll_scores.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _close_contest(self, contest: dict, manual_channel=None):
        db.close_contest(contest["id"])
        channel = self.bot.get_channel(contest["channel_id"]) or manual_channel
        if not channel:
            return

        scores_by_cat = db.get_all_scores_for_contest(contest["id"])

        # Winnaars per categorie + punten uitdelen
        winners_by_cat = {}
        mentions = []
        for cat in MOD_CATEGORIES:
            scores = scores_by_cat.get(cat, [])
            if scores:
                winner = scores[0]
                winners_by_cat[cat] = winner
                db.add_point(winner["user_id"], winner["discord_username"], winner["osu_username"])
                member = channel.guild.get_member(winner["user_id"])
                if member:
                    mentions.append(member.mention)

        embed = make_winner_embed(contest, winners_by_cat)
        mention_str = " ".join(mentions) if mentions else ""
        await channel.send(content=f"🎉 Gefeliciteerd {mention_str}!" if mention_str else "🎉", embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Contest(bot))
