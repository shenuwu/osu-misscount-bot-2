import sqlite3
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "data/contest.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else "data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
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

    c.execute("""
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

    c.execute("""
        CREATE TABLE IF NOT EXISTS points (
            user_id INTEGER PRIMARY KEY,
            discord_username TEXT NOT NULL,
            osu_username TEXT NOT NULL,
            points INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS linked_users (
            discord_id INTEGER PRIMARY KEY,
            discord_username TEXT NOT NULL,
            osu_username TEXT NOT NULL,
            osu_id INTEGER NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS submission_log (
            user_id INTEGER NOT NULL,
            month TEXT NOT NULL,
            PRIMARY KEY (user_id, month)
        )
    """)

    conn.commit()
    conn.close()

def get_conn():
    return sqlite3.connect(DB_PATH)

# --- Linked users ---

def link_user(discord_id, discord_username, osu_username, osu_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO linked_users (discord_id, discord_username, osu_username, osu_id)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET osu_username=?, osu_id=?, discord_username=?
    """, (discord_id, discord_username, osu_username, osu_id, osu_username, osu_id, discord_username))
    conn.commit()
    conn.close()

def get_linked_user(discord_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discord_id, discord_username, osu_username, osu_id FROM linked_users WHERE discord_id=?", (discord_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"discord_id": row[0], "discord_username": row[1], "osu_username": row[2], "osu_id": row[3]}
    return None

def get_all_linked_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT discord_id, discord_username, osu_username, osu_id FROM linked_users")
    rows = c.fetchall()
    conn.close()
    return [{"discord_id": r[0], "discord_username": r[1], "osu_username": r[2], "osu_id": r[3]} for r in rows]

# --- Contests ---

def has_submitted_this_month(user_id):
    month = datetime.now().strftime("%Y-%m")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT 1 FROM submission_log WHERE user_id=? AND month=?", (user_id, month))
    result = c.fetchone() is not None
    conn.close()
    return result

def log_map_submission(user_id):
    month = datetime.now().strftime("%Y-%m")
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO submission_log (user_id, month) VALUES (?, ?)", (user_id, month))
    conn.commit()
    conn.close()

def create_contest(beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date, end_date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO contests (beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date, end_date)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (beatmap_id, map_name, map_url, cover_url, submitted_by, channel_id, start_date.isoformat(), end_date.isoformat()))
    contest_id = c.lastrowid
    conn.commit()
    conn.close()
    return contest_id

def get_active_contest():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM contests WHERE active=1 ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return _row_to_contest(row)

def get_contest_by_id(contest_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM contests WHERE id=?", (contest_id,))
    row = c.fetchone()
    conn.close()
    return _row_to_contest(row)

def get_all_contests():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM contests ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
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

def close_contest(contest_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE contests SET active=0 WHERE id=?", (contest_id,))
    conn.commit()
    conn.close()

def delete_contest(contest_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM scores WHERE contest_id=?", (contest_id,))
    c.execute("DELETE FROM contests WHERE id=?", (contest_id,))
    conn.commit()
    conn.close()

# --- Scores ---

def upsert_score(contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat()

    c.execute("""
        SELECT misscount, accuracy FROM scores
        WHERE contest_id=? AND user_id=? AND mod_category=?
    """, (contest_id, user_id, mod_category))
    existing = c.fetchone()

    if existing is None:
        c.execute("""
            INSERT INTO scores (contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (contest_id, user_id, discord_username, osu_username, misscount, accuracy, score_id, mod_category, mods_display, now))
        updated = True
    else:
        old_miss, old_acc = existing
        if misscount < old_miss or (misscount == old_miss and accuracy > old_acc):
            c.execute("""
                UPDATE scores SET misscount=?, accuracy=?, score_id=?, mods_display=?, submitted_at=?, discord_username=?, osu_username=?
                WHERE contest_id=? AND user_id=? AND mod_category=?
            """, (misscount, accuracy, score_id, mods_display, now, discord_username, osu_username, contest_id, user_id, mod_category))
            updated = True
        else:
            updated = False

    conn.commit()
    conn.close()
    return updated

def get_leaderboard(contest_id, mod_category=None):
    conn = get_conn()
    c = conn.cursor()
    if mod_category:
        c.execute("""
            SELECT user_id, discord_username, osu_username, misscount, accuracy, mods_display, submitted_at, mod_category
            FROM scores WHERE contest_id=? AND mod_category=?
            ORDER BY misscount ASC, accuracy DESC
        """, (contest_id, mod_category))
    else:
        c.execute("""
            SELECT user_id, discord_username, osu_username, misscount, accuracy, mods_display, submitted_at, mod_category
            FROM scores WHERE contest_id=?
            ORDER BY mod_category, misscount ASC, accuracy DESC
        """, (contest_id,))
    rows = c.fetchall()
    conn.close()
    return [{
        "user_id": r[0], "discord_username": r[1], "osu_username": r[2],
        "misscount": r[3], "accuracy": r[4], "mods_display": r[5],
        "submitted_at": r[6], "mod_category": r[7]
    } for r in rows]

def get_all_scores_for_contest(contest_id):
    """Alle scores gegroepeerd per categorie."""
    from mods import MOD_CATEGORIES
    result = {}
    for cat in MOD_CATEGORIES:
        result[cat] = get_leaderboard(contest_id, cat)
    return result

# --- Points ---

def add_point(user_id, discord_username, osu_username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO points (user_id, discord_username, osu_username, points) VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET points=points+1, discord_username=?, osu_username=?
    """, (user_id, discord_username, osu_username, discord_username, osu_username))
    conn.commit()
    conn.close()

def get_global_leaderboard():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT user_id, discord_username, osu_username, points FROM points ORDER BY points DESC")
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "discord_username": r[1], "osu_username": r[2], "points": r[3]} for r in rows]
