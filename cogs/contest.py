import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import os

import database as db
import osu_api as osu
from mods import (
    parse_mods, is_banned, get_effective_mods, matches_required_mod,
    mods_display, normalize_mod_key, REQUIRED_MOD_CHOICES, BANNED_MODS, Mods
)

CONTEST_ROLE_NAME = os.getenv("CONTEST_ROLE", "contest-submitter")
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE", "contest-admin")
LOG_CHANNEL_NAME = os.getenv("LOG_CHANNEL", "bot-logs")

COLOR_PINK   = 0xFF69B4
COLOR_GOLD   = 0xFFD700
COLOR_PURPLE = 0x9B59B6
COLOR_BLUE   = 0x5865F2

MOD_COLORS = {
    "NM": 0xFFFFFF,
    "HR": 0xFF5555,
    "DT": 0xFFAA00,
    "EZ": 0x55FF55,
}

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

def extract_mods(mods) -> list[str]:
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

# ── Embed helpers ───────────────────────────────────────────────────────────
def make_contest_embed(contest: dict) -> discord.Embed:
    end = datetime.fromisoformat(contest["end_date"])
    start = datetime.fromisoformat(contest["start_date"])
    required_mod = contest.get("required_mod", "NM")
    color = MOD_COLORS.get(required_mod, COLOR_PINK)

    mod_label = {"NM": "NoMod", "DT": "Double Time", "HR": "Hard Rock", "EZ": "Easy"}.get(required_mod, required_mod)

    embed = discord.Embed(
        title="🎵  Nieuwe contest gestart!",
        description=f"### [{contest['map_name']}]({contest['map_url']})",
        color=color,
    )
    embed.add_field(name="🎯 Verplichte mod", value=f"**{mod_label}**\nHD en NF zijn altijd optioneel.", inline=False)
    embed.add_field(name="📅 Start", value=f"<t:{int(start.timestamp())}:D>", inline=True)
    embed.add_field(name="⏳ Eindigt", value=f"<t:{int(end.timestamp())}:R>", inline=True)
    embed.add_field(name="📆 Datum", value=f"<t:{int(end.timestamp())}:F>", inline=True)
    embed.add_field(
        name="📥 Meedoen",
        value="Koppel je account met `/link` en speel de map met de verplichte mod.\nDe bot pikt je score automatisch op binnen 5 minuten.",
        inline=False
    )
    embed.set_footer(text="Verboden mods: HalfTime · Relax · AutoPilot · Flashlight")
    if contest.get("cover_url"):
        embed.set_image(url=contest["cover_url"])
    return embed

def make_main_leaderboard_embed(contest: dict, scores: list) -> discord.Embed:
    required_mod = contest.get("required_mod", "NM")
    color = MOD_COLORS.get(required_mod, COLOR_PINK)
    mod_label = {"NM": "NoMod", "DT": "Double Time", "HR": "Hard Rock", "EZ": "Easy"}.get(required_mod, required_mod)
    medals = ["🥇", "🥈", "🥉"]

    embed = discord.Embed(
        title=f"🏆  {mod_label} Leaderboard",
        color=color,
    )
    if not scores:
        embed.description = "*Nog geen scores.*"
    else:
        lines = []
        for i, s in enumerate(scores):
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{s['osu_username']}** `{s['mods_display']}`\n　{s['misscount']}x miss · {s['accuracy']:.2f}%")
        embed.description = "\n".join(lines)
    return embed

def make_general_leaderboard_embed(contest: dict, scores: list) -> discord.Embed:
    embed = discord.Embed(
        title="📊  Algemeen Leaderboard",
        description="*Alle mod combos — telt niet mee voor punten.*",
        color=COLOR_BLUE,
    )
    if not scores:
        embed.description += "\n\n*Nog geen scores.*"
    else:
        lines = []
        medals = ["🥇", "🥈", "🥉"]
        for i, s in enumerate(scores[:20]):
            medal = medals[i] if i < 3 else f"`#{i+1}`"
            lines.append(f"{medal} **{s['osu_username']}** `{s['mods_display']}`\n　{s['misscount']}x miss · {s['accuracy']:.2f}%")
        embed.add_field(name="\u200b", value="\n".join(lines), inline=False)
    return embed

def make_winner_embed(contest: dict, winner: dict | None) -> discord.Embed:
    required_mod = contest.get("required_mod", "NM")
    mod_label = {"NM": "NoMod", "DT": "Double Time", "HR": "Hard Rock", "EZ": "Easy"}.get(required_mod, required_mod)

    embed = discord.Embed(
        title="🏁  Contest afgelopen!",
        description=f"### [{contest['map_name']}]({contest['map_url']})",
        color=COLOR_GOLD,
    )
    if contest.get("cover_url"):
        embed.set_thumbnail(url=contest["cover_url"])

    if winner:
        embed.add_field(
            name=f"🥇 Winnaar — {mod_label}",
            value=f"**{winner['osu_username']}** `{winner['mods_display']}`\n{winner['misscount']}x miss · {winner['accuracy']:.2f}%",
            inline=False
        )
    else:
        embed.add_field(name=f"— {mod_label}", value="*Geen scores ingediend.*", inline=False)

    embed.set_footer(text="Punt is bijgewerkt in /rankings")
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

    async def update_leaderboard(self, contest: dict):
        msg_id = contest.get("leaderboard_message_id")
        if not msg_id:
            return
        channel = self.bot.get_channel(contest["channel_id"])
        if not channel:
            return
        try:
            msg = await channel.fetch_message(msg_id)
            main_scores = await db.get_main_leaderboard(contest["id"])
            general_scores = await db.get_general_leaderboard(contest["id"])
            end = datetime.fromisoformat(contest["end_date"])
            header = discord.Embed(
                title="📋  Leaderboard",
                description=f"**[{contest['map_name']}]({contest['map_url']})**\nEindigt <t:{int(end.timestamp())}:R>",
                color=COLOR_PURPLE,
            )
            if contest.get("cover_url"):
                header.set_thumbnail(url=contest["cover_url"])
            main_embed = make_main_leaderboard_embed(contest, main_scores)
            general_embed = make_general_leaderboard_embed(contest, general_scores)
            await msg.edit(embeds=[header, main_embed, general_embed])
        except Exception as e:
            print(f"[Leaderboard update] Fout: {e}")

    async def log(self, embed: discord.Embed):
        for guild in self.bot.guilds:
            channel = discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)
            if channel:
                try:
                    await channel.send(embed=embed)
                except Exception:
                    pass

    async def _poll_contest(self, contest: dict, users: list) -> int:
        """Poll scores voor één contest. Geeft aantal updates terug."""
        updated_count = 0
        contest_start = datetime.fromisoformat(contest["start_date"])
        required_mod = contest.get("required_mod", "NM")

        for user in users:
            try:
                raw_scores = await osu.get_user_scores_on_beatmap(user["osu_id"], contest["beatmap_id"])
                if not raw_scores:
                    continue

                best_main = None  # Beste score die voldoet aan verplichte mod
                general_scores: dict[str, dict] = {}  # mod_key -> beste score

                for score in raw_scores:
                    if not score.get("passed", True):
                        continue

                    ended_at = score.get("ended_at") or score.get("created_at")
                    if ended_at:
                        score_time = datetime.fromisoformat(ended_at.replace("Z", "+00:00")).replace(tzinfo=None)
                        if score_time < contest_start:
                            continue

                    mods_list = extract_mods(score.get("mods", []))
                    mods = parse_mods(mods_list)

                    if is_banned(mods):
                        continue

                    miss = score["statistics"].get("count_miss", 0)
                    acc = round(score.get("accuracy", 0) * 100, 2)
                    mod_key = normalize_mod_key(mods_list)
                    mod_str = mods_display(mods_list)

                    # Check hoofd leaderboard
                    if matches_required_mod(mods, required_mod):
                        if best_main is None:
                            best_main = score
                        else:
                            prev_miss = best_main["statistics"].get("count_miss", 0)
                            prev_acc = round(best_main.get("accuracy", 0) * 100, 2)
                            if miss < prev_miss or (miss == prev_miss and acc > prev_acc):
                                best_main = score
                    else:
                        # Gaat naar algemeen leaderboard
                        if mod_key not in general_scores:
                            general_scores[mod_key] = score
                        else:
                            prev = general_scores[mod_key]
                            prev_miss = prev["statistics"].get("count_miss", 0)
                            prev_acc = round(prev.get("accuracy", 0) * 100, 2)
                            if miss < prev_miss or (miss == prev_miss and acc > prev_acc):
                                general_scores[mod_key] = score

                # Sla hoofd score op
                if best_main is not None:
                    mods_list = extract_mods(best_main.get("mods", []))
                    miss = best_main["statistics"].get("count_miss", 0)
                    acc = round(best_main.get("accuracy", 0) * 100, 2)
                    mod_str = mods_display(mods_list)
                    updated = await db.upsert_score(
                        contest_id=contest["id"],
                        user_id=user["discord_id"],
                        discord_username=user["discord_username"],
                        osu_username=user["osu_username"],
                        misscount=miss,
                        accuracy=acc,
                        score_id=best_main.get("id", 0),
                        mods_display=mod_str,
                    )
                    if updated:
                        updated_count += 1
                        channel = self.bot.get_channel(contest["channel_id"])
                        if channel:
                            embed = discord.Embed(
                                description=f"**{user['osu_username']}** heeft een nieuwe beste score!\n`{mod_str}` · {miss}x miss · {acc:.2f}%",
                                color=MOD_COLORS.get(required_mod, COLOR_PINK)
                            )
                            await channel.send(embed=embed)

                        log_embed = discord.Embed(
                            title="📥 Nieuwe score",
                            description=f"**{user['osu_username']}** in contest **#{contest['id']}**",
                            color=MOD_COLORS.get(required_mod, COLOR_PINK),
                            timestamp=datetime.now()
                        )
                        log_embed.add_field(name="Map", value=contest["map_name"], inline=False)
                        log_embed.add_field(name="Mods", value=f"`{mod_str}`", inline=True)
                        log_embed.add_field(name="Score", value=f"{miss}x miss · {acc:.2f}%", inline=True)
                        await self.log(log_embed)

                # Sla algemeen scores op
                for mod_key, score in general_scores.items():
                    mods_list = extract_mods(score.get("mods", []))
                    miss = score["statistics"].get("count_miss", 0)
                    acc = round(score.get("accuracy", 0) * 100, 2)
                    mod_str = mods_display(mods_list)
                    await db.upsert_general_score(
                        contest_id=contest["id"],
                        user_id=user["discord_id"],
                        discord_username=user["discord_username"],
                        osu_username=user["osu_username"],
                        misscount=miss,
                        accuracy=acc,
                        score_id=score.get("id", 0),
                        mods_display=mod_str,
                        mod_key=mod_key,
                    )

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

        return updated_count

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
    @app_commands.command(name="submit", description="Dien een map in voor de contest")
    @app_commands.describe(
        map_url="Link naar de osu! beatmap",
        required_mod="Verplichte mod voor deze contest"
    )
    @app_commands.choices(required_mod=[
        app_commands.Choice(name="NoMod", value="NM"),
        app_commands.Choice(name="Double Time", value="DT"),
        app_commands.Choice(name="Hard Rock", value="HR"),
        app_commands.Choice(name="Easy", value="EZ"),
    ])
    @has_contest_role()
    async def submit(self, interaction: discord.Interaction, map_url: str, required_mod: str):
        await interaction.response.defer()

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
        safe_name = "".join(c for c in beatmap['beatmapset']['title'].lower() if c.isalnum() or c == " ").strip()[:25].strip()
        channel_name = f"contest-{required_mod.lower()}-{safe_name.replace(' ', '-')}"

        contest_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites={guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)},
            topic=f"🎵 Contest [{required_mod}]: {map_name}"
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
            required_mod=required_mod,
            start_date=start,
            end_date=end
        )

        contest = await db.get_contest_by_id(contest_id)
        embed = make_contest_embed(contest)
        await contest_channel.send(embed=embed)

        # Post initiële leaderboard
        end_ts = int(end.timestamp())
        header = discord.Embed(
            title="📋  Leaderboard",
            description=f"**[{map_name}]({map_url})**\nEindigt <t:{end_ts}:R>",
            color=COLOR_PURPLE,
        )
        if cover_url:
            header.set_thumbnail(url=cover_url)
        main_embed = make_main_leaderboard_embed(contest, [])
        general_embed = make_general_leaderboard_embed(contest, [])
        lb_msg = await contest_channel.send(embeds=[header, main_embed, general_embed])
        await db.set_leaderboard_message_id(contest_id, lb_msg.id)

        await interaction.followup.send(f"✅ Contest aangemaakt in {contest_channel.mention}!")

        log_embed = discord.Embed(
            title="🎵 Contest aangemaakt",
            description=f"**{interaction.user}** heeft een contest ingediend.",
            color=COLOR_PINK,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Map", value=f"[{map_name}]({map_url})", inline=False)
        log_embed.add_field(name="Mod", value=required_mod, inline=True)
        log_embed.add_field(name="Channel", value=contest_channel.mention, inline=True)
        log_embed.add_field(name="Contest ID", value=f"#{contest_id}", inline=True)
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
                lines = [f"`#{c['id']}` **{c['map_name']}** [{c['required_mod']}]" for c in contests]
                await interaction.followup.send(
                    f"Er zijn **{len(contests)}** actieve contests. Gebruik `/leaderboard <id>`:\n" + "\n".join(lines),
                    ephemeral=True
                )
                return

        main_scores = await db.get_main_leaderboard(contest["id"])
        general_scores = await db.get_general_leaderboard(contest["id"])
        end = datetime.fromisoformat(contest["end_date"])

        header = discord.Embed(
            title="📋  Leaderboard",
            description=f"**[{contest['map_name']}]({contest['map_url']})**\nEindigt <t:{int(end.timestamp())}:R>",
            color=COLOR_PURPLE,
        )
        if contest.get("cover_url"):
            header.set_thumbnail(url=contest["cover_url"])

        main_embed = make_main_leaderboard_embed(contest, main_scores)
        general_embed = make_general_leaderboard_embed(contest, general_scores)
        await interaction.followup.send(embeds=[header, main_embed, general_embed])

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

        embed.set_footer(text="Punten worden uitgedeeld aan de winnaar van het hoofd leaderboard")
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
            embed.title = f"📋  Contest #{contest['id']}"
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
        log_embed.add_field(name="Map", value=contest["map_name"], inline=False)
        await self.log(log_embed)

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
            lines.append(f"`#{c['id']}` {status} [{c['required_mod']}] — **{c['map_name']}**")
        embed.description = "\n".join(lines)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="refresh", description="[Admin] Refresh alle actieve leaderboards en poll scores opnieuw")
    @has_admin_role()
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        contests = await db.get_active_contests()
        if not contests:
            await interaction.followup.send("❌ Geen actieve contests.", ephemeral=True)
            return

        users = await db.get_all_linked_users()
        total_updates = 0

        for contest in contests:
            updated = await self._poll_contest(contest, users)
            total_updates += updated
            fresh_contest = await db.get_contest_by_id(contest["id"])
            await self.update_leaderboard(fresh_contest)

        await interaction.followup.send(
            f"✅ Refresh klaar — {len(contests)} contest(s) gecheckt, {total_updates} score(s) bijgewerkt.",
            ephemeral=True
        )

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

            await self._poll_contest(contest, users)
            fresh_contest = await db.get_contest_by_id(contest["id"])
            await self.update_leaderboard(fresh_contest)

    @poll_scores.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _close_contest(self, contest: dict, manual_channel=None):
        await db.close_contest(contest["id"])
        channel = self.bot.get_channel(contest["channel_id"]) or manual_channel
        if not channel:
            return

        main_scores = await db.get_main_leaderboard(contest["id"])
        winner = main_scores[0] if main_scores else None

        if winner:
            await db.add_point(winner["user_id"], winner["discord_username"], winner["osu_username"])
            member = channel.guild.get_member(winner["user_id"])
            mention = member.mention if member else winner["osu_username"]
        else:
            mention = ""

        embed = make_winner_embed(contest, winner)
        await channel.send(
            content=f"🎉 Gefeliciteerd {mention}!" if mention else "🎉",
            embed=embed
        )

        log_embed = discord.Embed(
            title="🏁 Contest afgesloten",
            description=f"Contest **#{contest['id']}** is afgesloten.",
            color=COLOR_GOLD,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Map", value=f"[{contest['map_name']}]({contest['map_url']})", inline=False)
        if winner:
            log_embed.add_field(
                name="🥇 Winnaar",
                value=f"{winner['osu_username']} `{winner['mods_display']}` · {winner['misscount']}x miss · {winner['accuracy']:.2f}%",
                inline=False
            )
        await self.log(log_embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Contest(bot))
