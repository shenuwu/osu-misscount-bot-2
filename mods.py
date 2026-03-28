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

# Mods die een score altijd ongeldig maken
BANNED_MODS = Mods.HT | Mods.RX | Mods.AP

# Mods die transparant zijn (tellen niet mee voor categorie bepaling)
TRANSPARENT_MODS = Mods.NF | Mods.HD | Mods.SD | Mods.PF | Mods.TD | Mods.SO

# Verplichte mods die gekozen kunnen worden bij /submit
REQUIRED_MOD_CHOICES = ["NM", "DT", "HR", "EZ"]

def parse_mods(mods_list: list) -> Mods:
    result = Mods.NM
    for mod in mods_list:
        try:
            result |= Mods[mod.upper()]
        except KeyError:
            pass
    return result

def is_banned(mods: Mods) -> bool:
    return bool(mods & BANNED_MODS)

def get_effective_mods(mods: Mods) -> Mods:
    """Strip transparante mods, geeft de 'echte' mods terug."""
    return mods & ~TRANSPARENT_MODS

def matches_required_mod(mods: Mods, required_mod: str) -> bool:
    """
    Checkt of een score voldoet aan de verplichte mod.
    HD en NF zijn altijd transparant en tellen mee.
    De score mag ALLEEN de verplichte mod hebben (+ HD/NF).
    """
    effective = get_effective_mods(mods)

    if required_mod == "NM":
        return effective == Mods.NM
    elif required_mod == "DT":
        return effective == Mods.DT or effective == (Mods.DT | Mods.NC)
    elif required_mod == "HR":
        return effective == Mods.HR
    elif required_mod == "EZ":
        return effective == Mods.EZ
    return False

def mods_display(mods_list: list) -> str:
    """Leesbare mod string."""
    mods = parse_mods(mods_list)
    active = []
    for mod in ["EZ", "HD", "HR", "DT", "NC", "FL", "NF", "SD", "PF"]:
        if bool(mods & Mods[mod]):
            active.append(mod)
    return "+" + "".join(active) if active else "+NM"

def normalize_mod_key(mods_list: list) -> str:
    """Geeft een gesorteerde, genormaliseerde mod string voor gebruik als unieke sleutel."""
    mods = parse_mods(mods_list)
    active = []
    for mod in ["EZ", "HD", "HR", "DT", "NC", "HT", "FL", "NF", "SD", "PF"]:
        if bool(mods & Mods[mod]):
            active.append(mod)
    return "".join(active) if active else "NM"
