import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import os

import database as db
import osu_api as osu
from mods import parse_mods, is_banned, get_category, mods_display, MOD_CATEGORIES, MOD_COLORS, MOD_LABELS

def extract_mods(mods) -> list[str]:
    """Zet osu! API mods om naar een lijst van mod strings, ongeacht formaat."""
    if not mods:
        return []
    if isinstance(mods, list):
        result = []
        for m in mods:
            if isinstance(m, str):
                result.append(m)
            elif isinstance(m, dict):
                acronym = m.get("acronym") or m.get("name") or m.get("mod")
                if acronym:
                    result.append(acronym)
        return result
    return []

CONTEST_ROLE_NAME = os.getenv("CONTEST_ROLE", "contest-submitter")
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE", "contest-admin")
LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL", "bot-logs")

# ── Kleuren ────────────────────────────────────────────────────────────────
COLOR_PINK   = 0xFF69B4
COLOR_GOLD   = 0xFFD700
COLOR_PURPLE = 0x9B59B6
COLOR_DARK   = 0x2B2D31

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

def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    role = discord.utils.get(interaction.guild.roles, name=ADMIN_ROLE_NAME)
    return bool(role and role in interaction.user.roles)

# ── Embed helpers ───────────────────────────────────────────────────────────
def make_contest_embed(contest: dict) -> discord.Embed:
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
        self.poll_scores.start()

    async def cog_load(self):
        await db.init_db()

    def cog_unload(self):
        self.poll_scores.cancel()

    async def log(self, embed: discord.Embed):
        """Stuur een log embed naar het bot-logs kanaal in elke guild."""
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass

    # /link
    @app_commands.command(name="link", description="Koppel je osu! account aan de bot")
    @app_commands.describe(username="Jouw osu! gebruikersnaam")
    async def link(self, interaction: discord.Interaction, username: str):
        await interaction.response.defer(ephemeral=True)
        user_data = await osu.get_user(username)
        if not user_data:
            await interaction.followup.send(f"❌ Gebruiker **{username}** niet gevonden op osu!", ephemeral=True)
            return

        await db.link_user(
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

        log_embed = discord.Embed(
            title="🔗 Account gelinkt",
            description=f"**{interaction.user}** heeft osu! account **{user_data['username']}** gekoppeld.",
            color=COLOR_PINK,
            timestamp=datetime.now()
        )
        log_embed.set_footer(text=f"Discord ID: {interaction.user.id} · osu! ID: {user_data['id']}")
        await self.log(log_embed)

    # /submit
    @app_commands.command(name="submit", description="Dien een map in voor de tweewekelijkse contest")
    @app_commands.describe(map_url="Link naar de osu! beatmap")
    @has_contest_role()
    async def submit(self, interaction: discord.Interaction, map_url: str):
        await interaction.response.defer()

        # Admins mogen altijd indienen, anderen alleen als ze geen actieve contest hebben
        if not is_admin(interaction):
            if await db.has_active_submission(interaction.user.id):
                await interaction.followup.send(
                    "❌ Je hebt al een actieve contest lopen. Wacht tot die afloopt voor je een nieuwe indient.",
                    ephemeral=True
                )
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

        # Unieke channel naam op basis van map naam (ingekort)
        safe_name = "".join(c for c in beatmap['beatmapset']['title'].lower() if c.isalnum() or c == " ").strip()[:30].strip()
        channel_name = f"contest-{safe_name.replace(' ', '-')}"

        contest_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites={guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)},
            topic=f"🎵 Contest: {map_name}"
        )

        start = datetime.now()
        end = start + timedelta(weeks=2)

        contest_id = await db.create_contest(
            beatmap_id=beatmap_id,
            map_name=map_name,
            map_url=map_url,
            cover_url=cover_url,
            submitted_by=interaction.user.id,
            channel_id=contest_channel.id,
            start_date=start,
            end_date=end
        )

        contest = await db.get_contest_by_id(contest_id)
        embed = make_contest_embed(contest)
        await contest_channel.send(embed=embed)
        await interaction.followup.send(f"✅ Contest aangemaakt in {contest_channel.mention}!")

        log_embed = discord.Embed(
            title="🎵 Contest aangemaakt",
            description=f"**{interaction.user}** heeft een contest ingediend.",
            color=COLOR_PINK,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Map", value=f"[{map_name}]({map_url})", inline=False)
        log_embed.add_field(name="Channel", value=contest_channel.mention, inline=True)
        log_embed.add_field(name="Contest ID", value=f"#{contest_id}", inline=True)
        log_embed.add_field(name="Eindigt", value=f"<t:{int(end.timestamp())}:R>", inline=True)
        await self.log(log_embed)

    # /leaderboard
    @app_commands.command(name="leaderboard", description="Bekijk de scores van een actieve contest")
    @app_commands.describe(contest_id="Contest ID (optioneel, zie /listcontests)")
    async def leaderboard(self, interaction: discord.Interaction, contest_id: int = None):
        await interaction.response.defer()

        if contest_id:
            contest = await db.get_contest_by_id(contest_id)
            if not contest:
                await interaction.followup.send(f"❌ Contest #{contest_id} niet gevonden.", ephemeral=True)
                return
        else:
            contests = await db.get_active_contests()
            if not contests:
                await interaction.followup.send("❌ Er zijn geen actieve contests.", ephemeral=True)
                return
            if len(contests) == 1:
                contest = contests[0]
            else:
                # Meerdere actieve contests — toon lijst
                lines = [f"`#{c['id']}` **{c['map_name']}**" for c in contests]
                await interaction.followup.send(
                    f"Er zijn **{len(contests)}** actieve contests. Gebruik `/leaderboard <id>` om een specifieke te bekijken:\n" + "\n".join(lines),
                    ephemeral=True
                )
                return

        scores_by_cat = await db.get_all_scores_for_contest(contest["id"])
        embeds = make_leaderboard_embed(contest, scores_by_cat)

        end = datetime.fromisoformat(contest["end_date"])
        header = discord.Embed(
            title="📊  Leaderboard",
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
        board = await db.get_global_leaderboard()

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
    @app_commands.command(name="contestinfo", description="Bekijk info over actieve contests")
    @app_commands.describe(contest_id="Contest ID (optioneel)")
    async def contestinfo(self, interaction: discord.Interaction, contest_id: int = None):
        await interaction.response.defer()

        if contest_id:
            contest = await db.get_contest_by_id(contest_id)
            if not contest:
                await interaction.followup.send(f"❌ Contest #{contest_id} niet gevonden.", ephemeral=True)
                return
            embed = make_contest_embed(contest)
            embed.title = "📋  Contest info"
            await interaction.followup.send(embed=embed)
        else:
            contests = await db.get_active_contests()
            if not contests:
                await interaction.followup.send("❌ Er zijn geen actieve contests.", ephemeral=True)
                return
            for contest in contests:
                embed = make_contest_embed(contest)
                embed.title = f"📋  Contest #{contest['id']}"
                await interaction.followup.send(embed=embed)

    # ── Admin commands ──────────────────────────────────────────────────────

    # /endcontest
    @app_commands.command(name="endcontest", description="[Admin] Sluit een contest vroegtijdig af")
    @app_commands.describe(contest_id="Contest ID (zie /listcontests)")
    @has_admin_role()
    async def endcontest(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer()
        contest = await db.get_contest_by_id(contest_id)
        if not contest or not contest["active"]:
            await interaction.followup.send(f"❌ Geen actieve contest met ID #{contest_id}.", ephemeral=True)
            return
        await self._close_contest(contest, manual_channel=interaction.channel)
        await interaction.followup.send(f"✅ Contest #{contest_id} afgesloten en winnaar bepaald.")

    # /cancelcontest
    @app_commands.command(name="cancelcontest", description="[Admin] Annuleer een contest zonder winnaar")
    @app_commands.describe(contest_id="Contest ID (zie /listcontests)")
    @has_admin_role()
    async def cancelcontest(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer()
        contest = await db.get_contest_by_id(contest_id)
        if not contest or not contest["active"]:
            await interaction.followup.send(f"❌ Geen actieve contest met ID #{contest_id}.", ephemeral=True)
            return

        await db.close_contest(contest["id"])
        channel = self.bot.get_channel(contest["channel_id"])

        embed = discord.Embed(
            title="🚫  Contest geannuleerd",
            description=f"**{contest['map_name']}**\nDeze contest is handmatig gestopt. Er worden geen punten uitgedeeld.",
            color=discord.Color.red()
        )
        if channel:
            await channel.send(embed=embed)
        await interaction.followup.send(f"✅ Contest #{contest_id} geannuleerd zonder winnaar.")

        log_embed = discord.Embed(
            title="🚫 Contest geannuleerd",
            description=f"**{interaction.user}** heeft contest **#{contest['id']}** geannuleerd.",
            color=discord.Color.red(),
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Map", value=contest['map_name'], inline=False)
        await self.log(log_embed)

    # /deletecontest
    @app_commands.command(name="deletecontest", description="[Admin] Verwijder een contest permanent")
    @app_commands.describe(contest_id="Het ID van de contest (zie /listcontests)")
    @has_admin_role()
    async def deletecontest(self, interaction: discord.Interaction, contest_id: int):
        await interaction.response.defer(ephemeral=True)
        contest = await db.get_contest_by_id(contest_id)
        if not contest:
            await interaction.followup.send(f"❌ Contest #{contest_id} niet gevonden.", ephemeral=True)
            return

        await db.delete_contest(contest_id)
        await interaction.followup.send(
            f"✅ Contest **#{contest_id} — {contest['map_name']}** en alle scores zijn verwijderd.",
            ephemeral=True
        )

    # /listcontests
    @app_commands.command(name="listcontests", description="[Admin] Bekijk alle contests")
    @has_admin_role()
    async def listcontests(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        contests = await db.get_all_contests()
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
        contests = await db.get_active_contests()
        if not contests:
            return

        users = await db.get_all_linked_users()

        for contest in contests:
            end = datetime.fromisoformat(contest["end_date"])
            if datetime.now() > end:
                await self._close_contest(contest)
                continue

            for user in users:
                try:
                    raw_scores = await osu.get_user_scores_on_beatmap(user["osu_id"], contest["beatmap_id"])
                    if not raw_scores:
                        continue

                    best_per_cat: dict[str, dict] = {}
                    contest_start = datetime.fromisoformat(contest["start_date"])

                    for score in raw_scores:
                        # Sla scores over die voor de contest start gespeeld zijn
                        ended_at = score.get("ended_at") or score.get("created_at")
                        if ended_at:
                            score_time = datetime.fromisoformat(ended_at.replace("Z", "+00:00")).replace(tzinfo=None)
                            if score_time < contest_start:
                                continue

                        mods_list = extract_mods(score.get("mods", []))
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
                        mods_list = extract_mods(score.get("mods", []))
                        miss = score["statistics"].get("count_miss", 0)
                        acc = round(score.get("accuracy", 0) * 100, 2)
                        score_id = score.get("id", 0)
                        mod_str = mods_display(mods_list)

                        updated = await db.upsert_score(
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
                                label = MOD_LABELS.get(cat, cat)
                                embed = discord.Embed(
                                    description=f"**{user['osu_username']}** heeft een nieuwe beste score in **{label}**\n`{mod_str}` · {miss}x miss · {acc:.2f}%",
                                    color=MOD_COLORS.get(cat, COLOR_PINK)
                                )
                                await channel.send(embed=embed)

                except Exception as e:
                    print(f"[Poll] Fout voor {user['osu_username']} in contest #{contest['id']}: {e}")
                    log_embed = discord.Embed(
                        title="⚠️ Poll error",
                        description=f"Fout bij het ophalen van scores voor **{user['osu_username']}** in contest **#{contest['id']}**.",
                        color=discord.Color.orange(),
                        timestamp=datetime.now()
                    )
                    log_embed.add_field(name="Error", value=f"```{str(e)[:500]}```", inline=False)
                    await self.log(log_embed)

    @poll_scores.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _close_contest(self, contest: dict, manual_channel=None):
        await db.close_contest(contest["id"])
        channel = self.bot.get_channel(contest["channel_id"]) or manual_channel
        if not channel:
            return

        scores_by_cat = await db.get_all_scores_for_contest(contest["id"])

        winners_by_cat = {}
        mentions = []
        for cat in MOD_CATEGORIES:
            scores = scores_by_cat.get(cat, [])
            if scores:
                winner = scores[0]
                winners_by_cat[cat] = winner
                await db.add_point(winner["user_id"], winner["discord_username"], winner["osu_username"])
                member = channel.guild.get_member(winner["user_id"])
                if member:
                    mentions.append(member.mention)

        embed = make_winner_embed(contest, winners_by_cat)
        mention_str = " ".join(mentions) if mentions else ""
        await channel.send(content=f"🎉 Gefeliciteerd {mention_str}!" if mention_str else "🎉", embed=embed)

        log_embed = discord.Embed(
            title="🏁 Contest afgesloten",
            description=f"Contest **#{contest['id']}** is afgesloten.",
            color=COLOR_GOLD,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Map", value=f"[{contest['map_name']}]({contest['map_url']})", inline=False)
        for cat, winner in winners_by_cat.items():
            label = MOD_LABELS.get(cat, cat)
            log_embed.add_field(
                name=f"🥇 {label}",
                value=f"{winner['osu_username']} · {winner['misscount']}x miss · {winner['accuracy']:.2f}%",
                inline=True
            )
        await self.log(log_embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Contest(bot))
