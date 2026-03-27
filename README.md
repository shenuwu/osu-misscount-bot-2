# osu! Misscount Contest Bot

Discord bot die maandelijkse osu! misscount contests beheert. Scores worden automatisch opgehaald via de osu! API — deelnemers hoeven alleen hun account te linken en de map te spelen.

## Setup

### 1. Vereisten
- Python 3.11+
- Een Discord bot token
- Een osu! OAuth applicatie

### 2. Installeer dependencies
```bash
pip install -r requirements.txt
```

### 3. Discord bot aanmaken
1. Ga naar https://discord.com/developers/applications
2. New Application → Bot → Reset Token → kopieer token
3. Onder **Privileged Gateway Intents**: zet **Server Members Intent** aan
4. Invite link maken: OAuth2 → URL Generator → scopes: `bot`, `applications.commands` → permissions: `Manage Channels`, `Send Messages`, `Embed Links`

### 4. osu! OAuth applicatie aanmaken
1. Ga naar https://osu.ppy.sh/home/account/edit → "OAuth" sectie
2. New OAuth Application → naam invullen, callback URL mag leeg
3. Kopieer **Client ID** en **Client Secret**

### 5. .env instellen
```bash
cp .env.example .env
```
Vul in:
```
DISCORD_TOKEN=jouw_discord_bot_token
OSU_CLIENT_ID=jouw_client_id
OSU_CLIENT_SECRET=jouw_client_secret
CONTEST_ROLE=contest-submitter   # naam van de rol die maps mag indienen
```

### 6. Discord rol aanmaken
Maak in je server een rol aan met exact de naam uit `CONTEST_ROLE` (standaard: `contest-submitter`). Wijs deze toe aan mensen die maps mogen indienen.

### 7. Starten
```bash
python bot.py
```

---

## Commands

| Command | Beschrijving | Wie |
|---|---|---|
| `/link <username>` | Link jouw osu! account | Iedereen |
| `/submit <map_url>` | Dien een map in voor de contest | `contest-submitter` rol, 1x per maand |
| `/leaderboard` | Bekijk scores van huidige contest | Iedereen |
| `/rankings` | Bekijk de algemene puntenstand | Iedereen |
| `/endcontest` | Sluit contest handmatig af | Admin |

---

## Hoe het werkt

1. Iemand met de juiste rol dient een map in via `/submit <osu url>`
2. De bot maakt automatisch een contest-channel aan
3. Iedereen linkt hun osu! account via `/link`
4. De bot pollt elke 5 minuten of gelinkte users de map gespeeld hebben
5. Scores worden automatisch opgeslagen — alleen de beste score per persoon telt
6. Na 30 dagen (of via `/endcontest`) wordt de winnaar bepaald: **laagste misscount**, tiebreak op **hoogste accuracy**
7. De winnaar krijgt 1 punt in de algemene puntenstand

---

## Bestandsstructuur

```
osu-misscount-bot/
├── bot.py          # Bot entry point
├── database.py     # SQLite database functies
├── osu_api.py      # osu! API v2 wrapper
├── cogs/
│   └── contest.py  # Alle commands + polling loop
├── data/           # Wordt automatisch aangemaakt
│   └── contest.db
├── requirements.txt
└── .env
```
