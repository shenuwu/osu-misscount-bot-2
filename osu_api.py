import aiohttp
import os

OSU_API_BASE = "https://osu.ppy.sh/api/v2"
TOKEN_URL = "https://osu.ppy.sh/oauth/token"

_token_cache = {"token": None, "expires_at": 0}

async def get_token() -> str:
    import time
    if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    client_id = os.getenv("OSU_CLIENT_ID")
    client_secret = os.getenv("OSU_CLIENT_SECRET")

    async with aiohttp.ClientSession() as session:
        async with session.post(TOKEN_URL, json={
            "client_id": int(client_id),
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "public"
        }) as r:
            data = await r.json()
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = time.time() + data["expires_in"]
            return _token_cache["token"]

async def get_headers() -> dict:
    token = await get_token()
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

async def get_user(username: str) -> dict | None:
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OSU_API_BASE}/users/{username}/osu", headers=headers) as r:
            if r.status == 404:
                return None
            return await r.json()

async def get_beatmap(beatmap_id: int) -> dict | None:
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OSU_API_BASE}/beatmaps/{beatmap_id}", headers=headers) as r:
            if r.status == 404:
                return None
            return await r.json()

async def get_user_recent_scores(osu_user_id: int, limit: int = 100) -> list:
    """Haal recente scores op van een user (inclusief fails)."""
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{OSU_API_BASE}/users/{osu_user_id}/scores/recent",
            headers=headers,
            params={"limit": limit, "include_fails": 1, "mode": "osu"}
        ) as r:
            if r.status != 200:
                return []
            return await r.json()

async def get_user_scores_on_beatmap(osu_user_id: int, beatmap_id: int) -> list:
    """Haal alle scores van een user op een specifieke beatmap op."""
    headers = await get_headers()
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{OSU_API_BASE}/beatmaps/{beatmap_id}/scores/users/{osu_user_id}/all",
            headers=headers,
            params={"mode": "osu"}
        ) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("scores", [])

def parse_beatmap_id_from_url(url: str) -> int | None:
    """Haal beatmap ID uit een osu! URL. Ondersteunt /b/, /beatmaps/, en #osu/ formaten."""
    import re
    patterns = [
        r"osu\.ppy\.sh/beatmapsets/\d+#osu/(\d+)",
        r"osu\.ppy\.sh/beatmaps/(\d+)",
        r"osu\.ppy\.sh/b/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return int(m.group(1))
    return None

def extract_score_data(score: dict) -> dict:
    """Haal misscount, accuracy en score_id uit een raw API score object."""
    stats = score.get("statistics", {})
    misscount = stats.get("count_miss", 0)
    accuracy = round(score.get("accuracy", 0) * 100, 2)
    score_id = score.get("id", 0)
    return {"misscount": misscount, "accuracy": accuracy, "score_id": score_id}
