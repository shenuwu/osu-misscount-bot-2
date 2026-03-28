from enum import IntFlag

class Mods(IntFlag):
    NM = 0
    NF = 1 << 0
    EZ = 1 << 1
    TD = 1 << 2
    HD = 1 << 3
    HR = 1 << 4
    SD = 1 << 5
    DT = 1 << 6
    RX = 1 << 7
    HT = 1 << 8
    NC = 1 << 9
    FL = 1 << 10
    AU = 1 << 11
    SO = 1 << 12
    AP = 1 << 13
    PF = 1 << 14

# Mods die een score ongeldig maken
BANNED_MODS = Mods.HT | Mods.RX | Mods.AP | Mods.FL

# Mods die transparant zijn (tellen niet mee voor categorie)
TRANSPARENT_MODS = Mods.NF | Mods.HD | Mods.SD | Mods.PF | Mods.TD | Mods.SO

# Categorieën op volgorde van prioriteit
MOD_CATEGORIES = ["NM", "HR", "DT"]

MOD_COLORS = {
    "NM": 0xFFFFFF,
    "HR": 0xFF5555,
    "DT": 0xFFAA00,
}

MOD_LABELS = {
    "NM": "NoMod",
    "HR": "Hard Rock",
    "DT": "Double Time",
}

def parse_mods(mods_list: list) -> Mods:
    """Zet een lijst van mod strings om naar een Mods bitfield."""
    result = Mods.NM
    for mod in mods_list:
        try:
            result |= Mods[mod.upper()]
        except KeyError:
            pass
    return result

def is_banned(mods: Mods) -> bool:
    """True als de score een verboden mod bevat."""
    return bool(mods & BANNED_MODS)

def get_category(mods: Mods) -> str | None:
    """
    Bepaal de mod categorie van een score.
    Transparante mods (NF, HD, SD, PF) worden genegeerd.
    Geeft None terug als de score een verboden mod heeft.
    """
    if is_banned(mods):
        return None

    # Strip transparante mods
    effective = mods & ~TRANSPARENT_MODS

    if bool(effective & Mods.DT) or bool(effective & Mods.NC):
        return "DT"
    if bool(effective & Mods.HR):
        return "HR"
    if effective == Mods.NM:
        return "NM"

    # Onbekende mod combo (bijv. EZ, TD alleen) → negeer
    return None

def mods_display(mods_list: list) -> str:
    """Geeft een leesbare string van actieve mods, zonder transparante."""
    mods = parse_mods(mods_list)
    active = []
    for mod in ["EZ", "HR", "DT", "NC", "HT", "FL", "HD", "NF", "SD", "PF"]:
        if bool(mods & Mods[mod]):
            active.append(mod)
    return "+" + "".join(active) if active else "+NM"
