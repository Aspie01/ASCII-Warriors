"""Civilizations and their settlements."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from ..data import creatures as creature_data
from ..data import names as name_data
from ..engine import colors
from ..engine.colors import Color
from ..engine.rng import RNG

#: Site kind -> (glyph, colour, typical population range).
SITE_KINDS: Dict[str, Tuple[str, Color, Tuple[int, int]]] = {
    "fortress": ("#", colors.Color(198, 168, 120), (80, 260)),
    "hillocks": ("n", colors.Color(168, 148, 104), (30, 90)),
    "city": ("#", colors.Color(226, 214, 180), (200, 900)),
    "town": ("+", colors.Color(214, 198, 158), (60, 220)),
    "hamlet": ("o", colors.Color(190, 176, 140), (12, 50)),
    "castle": ("#", colors.Color(180, 180, 190), (40, 120)),
    "forest_retreat": ("A", colors.Color(120, 190, 120), (25, 90)),
    "dark_fortress": ("#", colors.Color(150, 70, 70), (100, 400)),
    "dark_pits": ("v", colors.Color(120, 60, 90), (40, 160)),
    "cave": ("0", colors.Color(130, 122, 112), (5, 40)),
    "ruin": ("x", colors.Color(120, 112, 100), (0, 0)),
    "tower": ("I", colors.Color(160, 120, 200), (1, 12)),
    "lair": ("!", colors.Color(180, 90, 60), (1, 4)),
    "camp": ("^", colors.Color(180, 150, 100), (4, 16)),
    "shrine": ("_", colors.Color(200, 200, 220), (0, 6)),
    "tomb": ("t", colors.Color(150, 140, 130), (0, 8)),
}

#: Race -> the site kinds it builds, by rank.
RACE_SITES: Dict[str, Dict[str, str]] = {
    "dwarf": {"capital": "fortress", "major": "fortress", "minor": "hillocks"},
    "human": {"capital": "city", "major": "town", "minor": "hamlet"},
    "elf": {"capital": "forest_retreat", "major": "forest_retreat",
            "minor": "forest_retreat"},
    "goblin": {"capital": "dark_fortress", "major": "dark_pits",
               "minor": "dark_pits"},
    "kobold": {"capital": "cave", "major": "cave", "minor": "cave"},
}

#: Race -> the biomes it prefers to settle, best first.
RACE_BIOMES: Dict[str, Tuple[str, ...]] = {
    "dwarf": ("mountain", "hills", "taiga", "tundra"),
    "human": ("grassland", "hills", "temperate_forest", "savanna", "shrubland",
              "temperate_broadleaf", "beach"),
    "elf": ("temperate_forest", "temperate_broadleaf", "tropical_forest",
            "jungle", "taiga"),
    "goblin": ("badlands", "shrubland", "savanna", "grassland", "swamp",
               "hills", "desert"),
    "kobold": ("mountain", "hills", "badlands", "swamp", "taiga"),
}

ETHICS_BY_RACE: Dict[str, Dict[str, str]] = {
    "dwarf": {"killing": "unthinkable", "theft": "unthinkable",
              "trespassing": "misguided", "slavery": "unthinkable",
              "eating_sapients": "unthinkable", "treefelling": "acceptable"},
    "human": {"killing": "unthinkable", "theft": "unthinkable",
              "trespassing": "misguided", "slavery": "personal_matter",
              "eating_sapients": "unthinkable", "treefelling": "acceptable"},
    "elf": {"killing": "unthinkable", "theft": "misguided",
            "trespassing": "shun", "slavery": "unthinkable",
            "eating_sapients": "acceptable", "treefelling": "unthinkable"},
    "goblin": {"killing": "acceptable", "theft": "acceptable",
               "trespassing": "acceptable", "slavery": "acceptable",
               "eating_sapients": "acceptable", "treefelling": "acceptable"},
    "kobold": {"killing": "acceptable", "theft": "required",
               "trespassing": "acceptable", "slavery": "misguided",
               "eating_sapients": "misguided", "treefelling": "acceptable"},
}


class Site:
    """A settlement, ruin or lair on the world map."""

    def __init__(
        self,
        sid: int,
        name: str,
        native_name: str,
        kind: str,
        wx: int,
        wy: int,
        race: str,
        civ_id: Optional[int] = None,
    ) -> None:
        self.id = sid
        self.name = name
        self.native_name = native_name
        self.kind = kind
        self.wx = wx
        self.wy = wy
        self.race = race
        self.civ_id = civ_id
        self.population = 0
        self.founded = 0
        self.destroyed: Optional[int] = None
        self.ruler_hf: Optional[int] = None
        self.owner_hf: Optional[int] = None
        self.buildings: List[str] = []
        self.wealth = 0
        self.visited = False

    @property
    def full_name(self) -> str:
        """``"Boatmurdered (Kadolmomuz)"``."""
        if self.native_name and self.native_name != self.name:
            return "%s (%s)" % (self.name, self.native_name)
        return self.name

    @property
    def kind_name(self) -> str:
        """Readable kind, e.g. ``"dark fortress"``."""
        return self.kind.replace("_", " ")

    @property
    def is_ruin(self) -> bool:
        """True if this site has been destroyed."""
        return self.destroyed is not None or self.kind == "ruin"

    @property
    def is_settlement(self) -> bool:
        """True for places with a living population."""
        return self.kind in (
            "fortress", "hillocks", "city", "town", "hamlet", "castle",
            "forest_retreat", "dark_fortress", "dark_pits", "cave",
        ) and not self.is_ruin

    @property
    def hostile(self) -> bool:
        """True if the locals attack strangers on sight."""
        return self.kind in ("dark_fortress", "dark_pits", "lair", "tower") or (
            self.race in ("goblin",) and self.is_settlement
        )

    def glyph(self) -> Tuple[str, Color]:
        """Map glyph and colour for the world map."""
        g, c, _pop = SITE_KINDS.get(self.kind, ("?", colors.WHITE, (0, 0)))
        if self.is_ruin:
            return ("x", colors.darken(c, 0.55))
        return (g, c)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the site."""
        return {
            "id": self.id, "name": self.name, "native": self.native_name,
            "kind": self.kind, "wx": self.wx, "wy": self.wy, "race": self.race,
            "civ": self.civ_id, "pop": self.population, "founded": self.founded,
            "destroyed": self.destroyed, "ruler": self.ruler_hf,
            "owner": self.owner_hf, "buildings": self.buildings,
            "wealth": self.wealth, "visited": self.visited,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Site":
        """Rebuild from :meth:`to_dict`."""
        s = cls(int(d["id"]), str(d["name"]), str(d.get("native", "")),
                str(d["kind"]), int(d["wx"]), int(d["wy"]), str(d["race"]),
                d.get("civ"))
        s.population = int(d.get("pop", 0))
        s.founded = int(d.get("founded", 0))
        s.destroyed = d.get("destroyed")
        s.ruler_hf = d.get("ruler")
        s.owner_hf = d.get("owner")
        s.buildings = list(d.get("buildings", []))
        s.wealth = int(d.get("wealth", 0))
        s.visited = bool(d.get("visited", False))
        return s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Site(%s, %s at %d,%d)" % (self.name, self.kind, self.wx, self.wy)


class Civilization:
    """A people with sites, a leader and enemies."""

    def __init__(
        self, cid: int, name: str, native_name: str, race: str, year: int = 0
    ) -> None:
        self.id = cid
        self.name = name
        self.native_name = native_name
        self.race = race
        self.sites: List[int] = []
        self.leader_hf: Optional[int] = None
        self.capital: Optional[int] = None
        self.at_war_with: Set[int] = set()
        self.ethics: Dict[str, str] = dict(ETHICS_BY_RACE.get(race, {}))
        self.year_founded = year
        self.destroyed: Optional[int] = None

    @property
    def full_name(self) -> str:
        """Translated name with the native form."""
        if self.native_name and self.native_name != self.name:
            return "%s (%s)" % (self.name, self.native_name)
        return self.name

    @property
    def adjective(self) -> str:
        """``"dwarven"``, ``"goblin"`` and so on."""
        return creature_data.get(self.race).adjective

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the civilization."""
        return {
            "id": self.id, "name": self.name, "native": self.native_name,
            "race": self.race, "sites": self.sites, "leader": self.leader_hf,
            "capital": self.capital, "war": sorted(self.at_war_with),
            "ethics": self.ethics, "founded": self.year_founded,
            "destroyed": self.destroyed,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Civilization":
        """Rebuild from :meth:`to_dict`."""
        c = cls(int(d["id"]), str(d["name"]), str(d.get("native", "")),
                str(d["race"]), int(d.get("founded", 0)))
        c.sites = [int(s) for s in d.get("sites", [])]
        c.leader_hf = d.get("leader")
        c.capital = d.get("capital")
        c.at_war_with = set(int(i) for i in d.get("war", []))
        c.ethics = dict(d.get("ethics") or {})
        c.destroyed = d.get("destroyed")
        return c

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Civilization(%s, %s, %d sites)" % (
            self.name, self.race, len(self.sites)
        )


# --------------------------------------------------------------------------- #
# Placement
# --------------------------------------------------------------------------- #


def site_kind_for(race: str, rank: str) -> str:
    """The kind of settlement a race builds at a given rank."""
    return RACE_SITES.get(race, RACE_SITES["human"]).get(rank, "hamlet")


def _site_score(world, race: str, x: int, y: int) -> float:
    """How much a race wants to settle a particular tile."""
    t = world.tile(x, y)
    if t.is_ocean or t.site_id is not None:
        return -1.0
    prefs = RACE_BIOMES.get(race, RACE_BIOMES["human"])
    if t.biome not in prefs:
        return -1.0
    score = 10.0 - prefs.index(t.biome) * 1.5
    if t.river:
        score += 2.0
    if any(world.tile(nx, ny).is_ocean for nx, ny in world.neighbours(x, y)):
        score += 1.0
    if race == "goblin":
        score += t.evil / 25.0
        score += t.savagery / 40.0
    elif race == "elf":
        score += (100 - t.evil) / 30.0
    elif race == "dwarf":
        score += t.elevation * 4.0
    score -= t.savagery / 60.0
    return score


def found_site(
    world, civ: Civilization, rng: RNG, kind: str, year: int = 0
) -> Optional[Site]:
    """Place a new settlement for a civilization, if anywhere suits."""
    best: List[Tuple[float, int, int]] = []
    for (x, y) in world.land_tiles():
        s = _site_score(world, civ.race, x, y)
        if s <= 0:
            continue
        # Keep settlements apart.
        too_close = False
        for site in world.sites:
            if abs(site.wx - x) <= 2 and abs(site.wy - y) <= 2:
                too_close = True
                break
        if too_close:
            continue
        s += rng.uniform(0.0, 2.5)
        best.append((s, x, y))
    if not best:
        return None
    best.sort(reverse=True)
    _score, x, y = best[0]

    native, translated = name_data.site_name(rng, civ.race, kind)
    site = Site(world.next_id("site"), translated, native, kind, x, y,
                civ.race, civ.id)
    lo, hi = SITE_KINDS.get(kind, ("?", colors.WHITE, (10, 40)))[2]
    site.population = rng.randint(lo, hi) if hi > 0 else 0
    site.founded = year
    site.wealth = site.population * rng.randint(4, 20)
    site.buildings = _buildings_for(kind, rng)
    world.sites.append(site)
    world.tile(x, y).site_id = site.id
    world.tile(x, y).civ_id = civ.id
    civ.sites.append(site.id)
    return site


def _buildings_for(kind: str, rng: RNG) -> List[str]:
    """Pick the notable buildings a settlement contains."""
    base = {
        "city": ["keep", "market", "tavern", "temple", "barracks", "well"],
        "town": ["market", "tavern", "temple", "well"],
        "hamlet": ["tavern", "well"],
        "castle": ["keep", "barracks", "well"],
        "fortress": ["great hall", "forge", "tavern", "temple", "barracks"],
        "hillocks": ["great hall", "tavern", "well"],
        "forest_retreat": ["grove", "tavern"],
        "dark_fortress": ["dark tower", "pit", "barracks", "torture chamber"],
        "dark_pits": ["pit", "barracks"],
        "cave": ["burrow"],
        "tower": ["dark tower", "library"],
        "ruin": [],
        "lair": [],
        "camp": ["tents"],
        "shrine": ["shrine"],
        "tomb": ["crypt"],
    }.get(kind, ["well"])
    out = list(base)
    if rng.chance(0.35) and kind in ("city", "town", "fortress"):
        out.append("library")
    if rng.chance(0.3) and kind in ("city", "fortress"):
        out.append("guildhall")
    return out


def place_lairs_and_ruins(world, rng: RNG) -> None:
    """Scatter caves, lairs, ruins, shrines and necromancer towers."""
    land = world.land_tiles()
    if not land:
        return
    count = max(4, len(land) // 90)

    def free(x: int, y: int) -> bool:
        return world.tile(x, y).site_id is None

    kinds = (
        ["cave"] * 4 + ["lair"] * 3 + ["ruin"] * 3 + ["shrine"] * 2
        + ["tomb"] * 2 + ["tower"] + ["camp"] * 2
    )
    for _ in range(count):
        x, y = rng.choice(land)
        if not free(x, y):
            continue
        t = world.tile(x, y)
        kind = rng.choice(kinds)
        if kind == "lair" and t.savagery < 40:
            kind = "cave"
        if kind == "tower" and t.evil < 55:
            kind = "ruin"
        race = {
            "cave": "kobold", "lair": "goblin", "ruin": "human",
            "shrine": "human", "tomb": "human", "tower": "human",
            "camp": "goblin",
        }.get(kind, "human")
        native, translated = name_data.site_name(rng, race, kind)
        site = Site(world.next_id("site"), translated, native, kind, x, y, race)
        lo, hi = SITE_KINDS.get(kind, ("?", colors.WHITE, (0, 0)))[2]
        site.population = rng.randint(lo, hi) if hi > 0 else 0
        site.founded = max(0, world.year - rng.randint(20, 400))
        site.wealth = rng.randint(20, 400)
        site.buildings = _buildings_for(kind, rng)
        if kind == "ruin":
            site.destroyed = site.founded + rng.randint(5, 100)
        world.sites.append(site)
        t.site_id = site.id
        t.feature = kind


def place_civilizations(world, rng: RNG, progress=None) -> None:
    """Found the world's civilizations and their first settlements."""
    races = list(creature_data.PLAYABLE_RACES)
    rng.shuffle(races)
    for race in races:
        native, translated = name_data.civ_name(rng, race)
        civ = Civilization(len(world.civs) + 1, translated, native, race, 1)
        world.civs.append(civ)
        capital = found_site(world, civ, rng, site_kind_for(race, "capital"), 1)
        if capital is None:
            world.civs.remove(civ)
            continue
        civ.capital = capital.id
        n_extra = rng.randint(1, 3)
        for _ in range(n_extra):
            found_site(world, civ, rng, site_kind_for(race, "minor"), 1)
    place_lairs_and_ruins(world, rng)


def sites_of_kind(world, kind: str) -> List[Site]:
    """Every site of a given kind."""
    return [s for s in world.sites if s.kind == kind]


def nearest_site(world, x: int, y: int, *, settlement_only: bool = False):
    """The closest site to a world coordinate."""
    best = None
    best_d = 1 << 30
    for s in world.sites:
        if settlement_only and not s.is_settlement:
            continue
        d = max(abs(s.wx - x), abs(s.wy - y))
        if d < best_d:
            best, best_d = s, d
    return best
