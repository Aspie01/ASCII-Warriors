"""Procedural naming.

Each race has its own phonology, and site/civ/artifact names come in pairs: the
native word and its translation, so a fortress can be both "Kadolmomuz" and
"Boatmurdered".
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from ..engine.rng import RNG

# --------------------------------------------------------------------------- #
# Personal names
# --------------------------------------------------------------------------- #

_DWARF_FIRST_M = (
    "Urist", "Morul", "Kogan", "Datan", "Zulban", "Ineth", "Rovod", "Sazir",
    "Melbil", "Kadol", "Adil", "Bomrek", "Cog", "Dodok", "Endok", "Fikod",
    "Goden", "Ilral", "Kib", "Litast", "Mistem", "Nish", "Obok", "Rigoth",
    "Sodel", "Thob", "Udil", "Vabok", "Zon", "Aban", "Beal", "Deler",
)
_DWARF_FIRST_F = (
    "Libash", "Zasit", "Onul", "Sibrek", "Erith", "Kivish", "Mebzuth", "Asen",
    "Nil", "Tosid", "Vucar", "Zuglar", "Ashi", "Doren", "Etur", "Gemid",
    "Ineth", "Kosoth", "Lokum", "Momuz", "Nomal", "Reg", "Sarvesh", "Tulon",
)
_DWARF_LAST_A = (
    "Boat", "Axe", "Stone", "Iron", "Steel", "Gold", "Silver", "Copper", "Bone",
    "Blood", "Anvil", "Rock", "Mine", "Beard", "Ale", "Forge", "Hammer", "Coal",
    "Shield", "Gem", "Deep", "Bronze", "Diamond", "Rune", "Wall", "Oath",
)
_DWARF_LAST_B = (
    "murdered", "glazed", "helm", "hold", "gate", "born", "hammer", "delve",
    "keeper", "cleaved", "forged", "shield", "song", "bane", "guard", "hoard",
    "crag", "spire", "vault", "wrought", "chant", "grip", "seeker", "fist",
)

_HUMAN_FIRST_M = (
    "Alrick", "Bertram", "Cedric", "Darvin", "Edmund", "Faron", "Gareth",
    "Halden", "Ivor", "Jorund", "Kelric", "Lorn", "Maddox", "Norwin", "Osric",
    "Perrin", "Quintan", "Roland", "Sevren", "Tomas", "Ulric", "Varen", "Wendel",
)
_HUMAN_FIRST_F = (
    "Adelin", "Brienne", "Cerys", "Delia", "Elowen", "Fenna", "Gwyneth",
    "Hesper", "Isolde", "Jessa", "Katriel", "Lisbet", "Maren", "Nerys",
    "Ottilie", "Perrine", "Rosalind", "Sabra", "Thessaly", "Ysolde",
)
_HUMAN_LAST = (
    "Marsh", "Thorne", "Ashford", "Blackwood", "Crane", "Dunmoor", "Eastvale",
    "Fenwick", "Grimsby", "Hollow", "Ironvale", "Kettleby", "Larkspur",
    "Mallory", "Northgate", "Oakhurst", "Ravensford", "Stonebridge",
    "Tallow", "Vance", "Westmere", "Wintersell",
)

_ELF_SYL_A = ("Ala", "Cae", "Ely", "Fae", "Ith", "Lor", "Mel", "Nae", "Ori",
              "Sil", "Tha", "Val", "Yri", "Aer", "Bel", "Cyr")
_ELF_SYL_B = ("wen", "riel", "dor", "las", "mir", "thil", "nor", "sar", "lyn",
              "wyn", "thas", "reth", "vion", "ael", "sil", "dis")
_ELF_TITLES = ("of the Silver Bough", "Leafwhisper", "Dawnstrider",
               "Moonwood", "Greenmantle", "Riverbend", "Starcanopy")

_GOBLIN_SYL_A = ("Sna", "Gru", "Zog", "Nak", "Ust", "Bol", "Mek", "Uzz", "Vok",
                 "Gro", "Ska", "Thug", "Rag", "Dur", "Sme", "Krul")
_GOBLIN_SYL_B = ("gob", "zik", "mash", "rul", "gath", "nok", "zug", "bak",
                 "urk", "dush", "gul", "thak", "rak", "vosh")
_GOBLIN_LAST = ("the Cruel", "Bonegrinder", "Skullsplitter", "the Merciless",
                "Throatcutter", "the Foul", "Eyegouger", "the Pitiless",
                "Childstealer", "the Black")

_KOBOLD_SYL = ("kik", "yip", "snik", "tak", "rik", "zib", "quix", "nib", "pak",
               "chit", "vex", "sput")

# --------------------------------------------------------------------------- #
# Word lists for compound (translated) names
# --------------------------------------------------------------------------- #

_WORDS_NOUN = (
    "hammer", "anvil", "mountain", "tunnel", "gate", "vault", "forge", "shield",
    "axe", "sword", "crown", "throne", "pillar", "bridge", "tower", "chasm",
    "cavern", "torch", "lantern", "helm", "wall", "moat", "grave", "bone",
    "blood", "iron", "steel", "gold", "silver", "gem", "diamond", "coal",
    "ale", "beard", "oath", "song", "riddle", "boat", "wheel", "key", "lock",
    "mine", "quarry", "spring", "river", "lake", "peak", "star", "moon", "sun",
)
_WORDS_ADJ = (
    "iron", "golden", "silver", "black", "red", "deep", "high", "old", "lost",
    "hidden", "burning", "frozen", "silent", "roaring", "bloody", "sacred",
    "cursed", "eternal", "broken", "shining", "grim", "gilded", "sunken",
)
_WORDS_VERB = (
    "murdered", "cleaved", "forged", "delved", "sealed", "guarded", "shattered",
    "buried", "crowned", "sundered", "kindled", "quenched", "wrought", "bound",
    "hallowed", "cursed", "abandoned", "defended", "besieged", "raised",
)

_NATIVE_SYL_DWARF = (
    "kad", "ol", "mo", "muz", "ur", "ist", "ath", "el", "zul", "ban", "rig",
    "oth", "dum", "at", "lo", "kum", "sib", "rek", "gos", "in", "tar", "med",
    "bom", "rek", "usan", "eth", "kib", "uk", "dor", "ral", "nish", "tosid",
)
_NATIVE_SYL_HUMAN = (
    "am", "ber", "cast", "dun", "el", "far", "gor", "hal", "ith", "lan", "mor",
    "nes", "or", "pen", "rath", "sel", "tor", "ul", "ven", "wold", "yar",
)
_NATIVE_SYL_ELF = _ELF_SYL_A + _ELF_SYL_B
_NATIVE_SYL_GOBLIN = _GOBLIN_SYL_A + _GOBLIN_SYL_B
_NATIVE_SYL_KOBOLD = _KOBOLD_SYL

_NATIVE_SYLLABLES: Dict[str, Sequence[str]] = {
    "dwarf": _NATIVE_SYL_DWARF,
    "human": _NATIVE_SYL_HUMAN,
    "elf": _NATIVE_SYL_ELF,
    "goblin": _NATIVE_SYL_GOBLIN,
    "kobold": _NATIVE_SYL_KOBOLD,
}


def _native_word(rng: RNG, race: str, syllables: int = 3) -> str:
    """Build a pronounceable word in a race's language."""
    syls = _NATIVE_SYLLABLES.get(race, _NATIVE_SYL_HUMAN)
    word = "".join(rng.choice(syls) for _ in range(max(1, syllables)))
    return word.capitalize()


# --------------------------------------------------------------------------- #
# Personal name generators
# --------------------------------------------------------------------------- #


def dwarf_name(rng: RNG, female: bool = False) -> str:
    """A dwarven given name plus a compound surname."""
    first = rng.choice(_DWARF_FIRST_F if female else _DWARF_FIRST_M)
    last = rng.choice(_DWARF_LAST_A) + rng.choice(_DWARF_LAST_B)
    return "%s %s" % (first, last)


def human_name(rng: RNG, female: bool = False) -> str:
    """A human given name and family name."""
    first = rng.choice(_HUMAN_FIRST_F if female else _HUMAN_FIRST_M)
    return "%s %s" % (first, rng.choice(_HUMAN_LAST))


def elf_name(rng: RNG, female: bool = False) -> str:
    """A flowing elven name and epithet."""
    name = rng.choice(_ELF_SYL_A) + rng.choice(_ELF_SYL_B)
    if rng.chance(0.35):
        name += rng.choice(_ELF_SYL_B)
    return "%s %s" % (name.capitalize(), rng.choice(_ELF_TITLES))


def goblin_name(rng: RNG, female: bool = False) -> str:
    """A harsh goblin name and epithet."""
    name = rng.choice(_GOBLIN_SYL_A) + rng.choice(_GOBLIN_SYL_B)
    return "%s %s" % (name.capitalize(), rng.choice(_GOBLIN_LAST))


def kobold_name(rng: RNG, female: bool = False) -> str:
    """A chittering kobold name."""
    n = rng.randint(2, 3)
    return "".join(rng.choice(_KOBOLD_SYL) for _ in range(n)).capitalize()


_NAME_FUNCS = {
    "dwarf": dwarf_name,
    "human": human_name,
    "elf": elf_name,
    "goblin": goblin_name,
    "kobold": kobold_name,
}


def name_for_race(race: str, rng: RNG, female: bool = False) -> str:
    """Generate a personal name for any race, falling back to human names."""
    func = _NAME_FUNCS.get(race)
    if func:
        return func(rng, female)
    if race in ("bandit", "guard", "merchant", "peasant", "necromancer",
                "vampire", "werewolf"):
        return human_name(rng, female)
    if race in ("hammerdwarf", "axedwarf"):
        return dwarf_name(rng, female)
    if race == "elf_archer":
        return elf_name(rng, female)
    if race == "goblin_snatcher":
        return goblin_name(rng, female)
    return human_name(rng, female)


# --------------------------------------------------------------------------- #
# Place, civ and artifact names
# --------------------------------------------------------------------------- #

_SITE_PATTERNS: Dict[str, Tuple[str, ...]] = {
    "fortress": ("{adj}{noun}", "{noun}{verb}", "{noun}{noun2}"),
    "hillocks": ("{adj}{noun}", "{noun}{noun2}"),
    "town": ("{noun}{suffix}", "{adj} {noun}", "{noun}{noun2}"),
    "hamlet": ("{noun}{suffix}", "{adj} {noun}"),
    "city": ("{noun}{suffix}", "{adj} {noun}"),
    "castle": ("{noun}{verb}", "{adj}{noun}"),
    "forest_retreat": ("{adj} {noun}", "{noun} of the {noun2}"),
    "dark_fortress": ("{noun}{verb}", "{adj}{noun}"),
    "dark_pits": ("{noun}{verb}", "{adj}{noun}"),
    "cave": ("{adj} {noun}", "{noun} {noun2}"),
    "ruin": ("{adj} {noun}", "{noun}{verb}"),
    "tower": ("{adj}{noun}", "{noun}{verb}"),
    "lair": ("{adj} {noun}", "{noun} {noun2}"),
    "camp": ("{noun} camp", "{adj} camp"),
    "shrine": ("shrine of {noun}", "{adj} shrine"),
    "tomb": ("tomb of {noun}", "{adj} tomb"),
}

_TOWN_SUFFIX = ("ton", "ford", "bury", "hold", "gate", "mere", "wick", "burg",
                "stead", "haven", "reach", "moor", "vale", "crest")


def _expand(rng: RNG, pattern: str) -> str:
    """Expand a name pattern, never repeating a word inside one name."""
    used: set = set()

    def pick(pool: Sequence[str]) -> str:
        for _ in range(8):
            w = rng.choice(pool)
            if w not in used:
                used.add(w)
                return w
        return rng.choice(pool)

    out = pattern
    for token, pool in (
        ("{adj2}", _WORDS_ADJ), ("{adj}", _WORDS_ADJ),
        ("{noun2}", _WORDS_NOUN), ("{noun}", _WORDS_NOUN),
        ("{verb}", _WORDS_VERB), ("{suffix}", _TOWN_SUFFIX),
    ):
        while token in out:
            out = out.replace(token, pick(pool), 1)
    return out


def _fill(rng: RNG, pattern: str) -> str:
    """Expand a name pattern into English words."""
    return _expand(rng, pattern)


def _titleize(s: str) -> str:
    """Capitalise a translated name without touching small joining words."""
    small = {"of", "the", "and"}
    parts = s.split(" ")
    return " ".join(
        p if (i and p in small) else (p[:1].upper() + p[1:]) for i, p in enumerate(parts)
    )


def site_name(rng: RNG, race: str, kind: str) -> Tuple[str, str]:
    """``(native_name, translated_name)`` for a settlement."""
    patterns = _SITE_PATTERNS.get(kind, ("{adj}{noun}",))
    translated = _titleize(_fill(rng, rng.choice(patterns)))
    native = _native_word(rng, race, rng.randint(2, 4))
    return (native, translated)


def civ_name(rng: RNG, race: str) -> Tuple[str, str]:
    """``(native_name, translated_name)`` for a civilization."""
    forms = (
        "The {adj} {noun}s", "The {noun}s of the {noun2}", "The {verb} {noun}s",
        "The {adj} {noun} of the {noun2}", "The {noun} {noun2}s",
    )
    translated = _titleize(_expand(rng, rng.choice(forms)))
    native = _native_word(rng, race, rng.randint(3, 4))
    return (native, translated)


def artifact_name(rng: RNG, race: str) -> Tuple[str, str]:
    """``(native_name, translated_name)`` for a legendary object."""
    forms = ("The {adj} {noun}", "{noun}{verb}", "The {noun} of the {noun2}",
             "{adj}{noun}")
    translated = _titleize(_expand(rng, rng.choice(forms)))
    native = _native_word(rng, race, rng.randint(2, 4))
    return (native, translated)


_REGION_ADJ = (
    "Sunken", "Whispering", "Mirthful", "Dying", "Endless", "Glittering",
    "Shattered", "Weeping", "Hidden", "Howling", "Silent", "Ashen", "Emerald",
    "Iron", "Golden", "Forsaken", "Blessed", "Wandering", "Shivering",
)
_REGION_NOUN: Dict[str, Tuple[str, ...]] = {
    "forest": ("Woods", "Forest", "Thicket", "Grove", "Wilds", "Canopy"),
    "mountain": ("Peaks", "Range", "Spires", "Heights", "Crags", "Ridges"),
    "desert": ("Sands", "Wastes", "Dunes", "Expanse", "Barrens"),
    "grass": ("Plains", "Fields", "Steppes", "Meadows", "Downs"),
    "water": ("Deeps", "Waters", "Shallows", "Straits", "Sea"),
    "wetland": ("Marshes", "Mire", "Fens", "Bog", "Swamps"),
    "frozen": ("Tundra", "Frost", "Waste", "Snows", "Glaciers"),
    "other": ("Lands", "Reaches", "Wilds", "Country", "Territories"),
}


def region_name(rng: RNG, biome: str) -> str:
    """A poetic region name such as ``"The Sunken Wilds"``."""
    from . import biomes as biome_data

    b = biome_data.get(biome)
    group = "other"
    for flag, key in (
        ("FOREST", "forest"), ("MOUNTAIN", "mountain"), ("DESERT", "desert"),
        ("WATER", "water"), ("WETLAND", "wetland"), ("FROZEN", "frozen"),
        ("GRASS", "grass"),
    ):
        if b.has(flag):
            group = key
            break
    return "The %s %s" % (
        rng.choice(_REGION_ADJ), rng.choice(_REGION_NOUN[group])
    )


_BEAST_SYL_A = ("Us", "Ngo", "Ath", "Xel", "Ubb", "Vor", "Zha", "Qoth", "Mur",
                "Ith", "Gzu", "Rha", "Sso", "Tza", "Ykk")
_BEAST_SYL_B = ("tuth", "mek", "olor", "grath", "sith", "vak", "noth", "rull",
                "xeb", "morg", "zul", "thak", "quun", "veth")


def beast_name(rng: RNG) -> str:
    """A two-word name for a forgotten beast or titan."""
    def word() -> str:
        w = rng.choice(_BEAST_SYL_A) + rng.choice(_BEAST_SYL_B)
        if rng.chance(0.3):
            w += rng.choice(_BEAST_SYL_B)
        return w
    return "%s %s" % (word(), word())


_GROUP_PREFIX = ("The", "The", "The")
_GROUP_ADJ = ("Iron", "Bloody", "Silent", "Black", "Crimson", "Broken", "Grim",
              "Golden", "Savage", "Cold", "Burning", "Laughing")
_GROUP_NOUN: Dict[str, Tuple[str, ...]] = {
    "bandit": ("Knives", "Wolves", "Hands", "Crows", "Jackals", "Nooses"),
    "mercenary": ("Blades", "Spears", "Shields", "Lances", "Banners"),
    "temple": ("Circle", "Order", "Congregation", "Faithful", "Devout"),
    "guild": ("Guild", "Company", "League", "Union", "Fellowship"),
    "other": ("Company", "Band", "Order", "Host"),
}


def group_name(rng: RNG, kind: str) -> str:
    """A name for a band of bandits, mercenaries, a temple or a guild."""
    nouns = _GROUP_NOUN.get(kind, _GROUP_NOUN["other"])
    return "%s %s %s" % (
        rng.choice(_GROUP_PREFIX), rng.choice(_GROUP_ADJ), rng.choice(nouns)
    )


_TITLES_BY_RANK: Dict[str, Tuple[str, ...]] = {
    "leader": ("King", "Queen", "Lord", "Lady", "Chieftain", "Warlord",
               "High Priest", "Overseer"),
    "noble": ("Baron", "Baroness", "Count", "Countess", "Duke", "Duchess",
              "Thane", "Marshal"),
    "hero": ("the Brave", "the Bold", "Beastslayer", "the Undefeated",
             "Dragonbane", "the Ironclad", "the Wanderer"),
    "monster": ("the Devourer", "the Scourge", "the Terror", "Doom of the Deep",
                "the Unmaker", "the Endless Hunger"),
}


def title_for(rng: RNG, rank: str, female: bool = False) -> str:
    """A title appropriate to a rank."""
    titles = _TITLES_BY_RANK.get(rank, _TITLES_BY_RANK["noble"])
    choices: List[str] = list(titles)
    if rank in ("leader", "noble"):
        gendered = {
            "King": "Queen", "Lord": "Lady", "Baron": "Baroness",
            "Count": "Countess", "Duke": "Duchess",
        }
        if female:
            choices = [gendered.get(t, t) for t in choices]
        else:
            reverse = {v: k for k, v in gendered.items()}
            choices = [reverse.get(t, t) for t in choices]
        choices = list(dict.fromkeys(choices))
    return rng.choice(choices)
