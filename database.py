import aiosqlite
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/contest.db")

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "data", exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS contests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                beatmap_id INTEGER NOT NULL,
                map_name TEXT NOT NULL,
                map_url TEXT NOT NULL,
                cover_url TEXT,
                submitted_by INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                active INTEGER DEFAULT 1
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contest_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                discord_username TEXT NOT NULL,
                osu_username TEXT NOT NULL,
                misscount INTEGER NOT NULL,
                accuracy REAL NOT NULL,
                score_id INTEGER NOT NULL,
                mod_category TEXT NOT NULL DEFAULT 'NM',
                mods_display TEXT NOT NULL DEFAULT '+NM',
                submitted_at TEXT NOT NULL,
                FOREIGN KEY (contest_id) REFERENCES contests(id),
                UNIQUE(contest_id, user_id, mod_category)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS points (
                user_id INTEGER PRIMARY KEY,
                discord_username TEXT NOT NULL,
                osu_username TEXT NOT NULL,
                points INTEGER DEFAULT 0
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS linked_users (
                discord_id INTEGER PRIMARY KEY,
                discord_username TEXT NOT NULL,
                osu_username TEXT NOT NULL,
                osu_id INTEGER NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS submission_log (
                user_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                PRIMARY KEY (user_id, month)
            )
        """)
        await conn.commit()

# --- Linked users ---

async def link_user(discord_id, discord_username, osu_username, osu_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO linked_users (discord_id, discord_username, osu_username, osu_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(discord_id) DO UPDATE SET osu_username=?, osu_id=?, discord_username=?
        """, (discord_id, discord_username, osu_username, osu_id, osu_username, osu_id, discord_username))
        await conn.commit()

async def get_linked_user(discord_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT discord_id, discord_username, osu_username, osu_id FROM linked_users WHERE discord_id=?",
            (discord_id,)
        ) as cursor:
            row = await cursor.fetchone()
    if row:
        return {"discord_id": row[0], "discord_username": row[1], "osu_username": row[2], "osu_id": row[3]}
    return None

async def get_all_linked_users():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT discord_id, discord_username, osu_username, osu_id FROM linked_users"
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"discord_id": r[0], "discord_username": r[1], "osu_username": r[2], "osu_id": r[3]} for r in rows]

# --- Contests ---

async def has_submitted_this_month(user_id):
    month = datetime.now().strftime("%Y-%m")
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT 1 FROM submission_log WHERE user_id=? AND month=?", (user_id, month)
        ) as cursor:
            return await cursor.fetchone() is not None

async def log_map_submission(user_id):
    month = datetime.now().strftime("%Y-%m")
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute(
            "INSERT OR IGNORE INTO submission_log (user_id, month) VALUES (?, ?)", (user_id, month)
        )
        await conn.commit()

async def create_contest(beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date, end_date):
    async with aiosqlite.connect(DB_PATH) as conn:
        cursor = await conn.execute("""
            INSERT INTO contests (beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date.isoformat(), end_date.isoformat()))
        contest_id = cursor.lastrowid
        await conn.commit()
    return contest_id

async def get_active_contest():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT * FROM contests WHERE active=1 ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_contest(row)

async def get_contest_by_id(contest_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT * FROM contests WHERE id=?", (contest_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return _row_to_contest(row)

async def get_all_contests():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("SELECT * FROM contests ORDER BY id DESC") as cursor:
            rows = await cursor.fetchall()
    return [_row_to_contest(r) for r in rows]

def _row_to_contest(row):
    if not row:
        return None
    return {
        "id": row[0], "beatmap_id": row[1], "map_name": row[2],
        "map_url": row[3], "cover_url": row[4],
        "submitted_by": row[5], "channel_id": row[6],
        "start_date": row[7], "end_date": row[8], "active": row[9]
    }

async def close_contest(contest_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE contests SET active=0 WHERE id=?", (contest_id,))
        await conn.commit()

async def delete_contest(contest_id):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("DELETE FROM scores WHERE contest_id=?", (contest_id,))
        await conn.execute("DELETE FROM contests WHERE id=?", (contest_id,))
        await conn.commit()

# --- Scores ---

async def upsert_score(contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display):
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute("""
            SELECT misscount, accuracy FROM scores
            WHERE contest_id=? AND user_id=? AND mod_category=?
        """, (contest_id, user_id, mod_category)) as cursor:
            existing = await cursor.fetchone()

        if existing is None:
            await conn.execute("""
                INSERT INTO scores (contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display, submitted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display, now))
            updated = True
        else:
            old_miss, old_acc = existing
            if misscount < old_miss or (misscount == old_miss and accuracy > old_acc):
                await conn.execute("""
                    UPDATE scores SET misscount=?, accuracy=?, score_id=?, mods_display=?, submitted_at=?, discord_username=?, osu_username=?
                    WHERE contest_id=? AND user_id=? AND mod_category=?
                """, (misscount, accuracy, score_id, mods_display, now, discord_username, osu_username, contest_id, user_id, mod_category))
                updated = True
            else:
                updated = False

        await conn.commit()
    return updated

async def get_leaderboard(contest_id, mod_category=None):
    async with aiosqlite.connect(DB_PATH) as conn:
        if mod_category:
            async with conn.execute("""
                SELECT user_id, discord_username, osu_username, misscount, accuracy, mods_display, submitted_at, mod_category
                FROM scores WHERE contest_id=? AND mod_category=?
                ORDER BY misscount ASC, accuracy DESC
            """, (contest_id, mod_category)) as cursor:
                rows = await cursor.fetchall()
        else:
            async with conn.execute("""
                SELECT user_id, discord_username, osu_username, misscount, accuracy, mods_display, submitted_at, mod_category
                FROM scores WHERE contest_id=?
                ORDER BY mod_category, misscount ASC, accuracy DESC
            """, (contest_id,)) as cursor:
                rows = await cursor.fetchall()
    return [{
        "user_id": r[0], "discord_username": r[1], "osu_username": r[2],
        "misscount": r[3], "accuracy": r[4], "mods_display": r[5],
        "submitted_at": r[6], "mod_category": r[7]
    } for r in rows]

async def get_all_scores_for_contest(contest_id):
    from mods import MOD_CATEGORIES
    result = {}
    for cat in MOD_CATEGORIES:
        result[cat] = await get_leaderboard(contest_id, cat)
    return result

# --- Points ---

async def add_point(user_id, discord_username, osu_username):
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("""
            INSERT INTO points (user_id, discord_username, osu_username, points) VALUES (?, ?, ?, 1)
            ON CONFLICT(user_id) DO UPDATE SET points=points+1, discord_username=?, osu_username=?
        """, (user_id, discord_username, osu_username, discord_username, osu_username))
        await conn.commit()

async def get_global_leaderboard():
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT user_id, discord_username, osu_username, points FROM points ORDER BY points DESC"
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"user_id": r[0], "discord_username": r[1], "osu_username": r[2], "points": r[3]} for r in rows]
