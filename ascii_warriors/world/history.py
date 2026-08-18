"""Historical simulation.

Runs the world forward year by year: leaders rise and die, civilizations expand
and go to war, megabeasts sack settlements, heroes hunt them down and artifacts
are forged, stolen and lost. Everything it records is queryable by the legends
viewer and quoted back at the player by NPCs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..data import creatures as creature_data
from ..data import items as item_data
from ..data import materials as mat_data
from ..data import names as name_data
from ..data.descriptors import indefinite_article
from ..engine.rng import RNG

#: Every kind of event the world records, checked against what `record` is
#: actually called with. Four were missing: the three a fortress ending or a
#: reclaim writes, and the one the living world writes when somebody moves
#: back into a ruin.
#:
#: A tavern_founded was here too and nothing has ever written one. Unquoted,
#: because the test that keeps this list honest counts string literals.
#:
#: `founded_site` and `site_founded` are both here and both real, which is a
#: wart rather than a typo. Worldgen and the living world write the first and
#: `art.py` and `artforms.py` match engraving phrases against it; the fortress
#: writes the second. Renaming either would silently stop an engraving being
#: about anything.
EVENT_KINDS: Tuple[str, ...] = (
    "founded_civ", "founded_site", "site_founded", "became_leader",
    "birth", "death", "war_declared", "peace", "battle",
    "site_destroyed", "site_conquered", "site_abandoned", "site_reclaimed",
    "resettled",
    "artifact_created", "artifact_stolen", "beast_attack", "beast_slain",
    "hero_rose", "became_necromancer", "tower_built", "curse", "banditry",
    "marriage", "migration", "plague", "performance",
)


class HistoricalFigure:
    """Someone the world remembers."""

    def __init__(
        self,
        hf_id: int,
        name: str,
        native_name: str,
        race: str,
        female: bool,
        born: int,
    ) -> None:
        self.id = hf_id
        self.name = name
        self.native_name = native_name
        self.race = race
        self.female = female
        self.born = born
        self.died: Optional[int] = None
        self.death_cause = ""
        self.civ_id: Optional[int] = None
        self.site_id: Optional[int] = None
        self.profession = "peasant"
        self.titles: List[str] = []
        self.kills: List[int] = []
        self.relationships: Dict[int, str] = {}
        self.flags: Set[str] = set()
        self.stats: Dict[str, int] = {}
        self.creature_id = ""

    def alive(self, year: int) -> bool:
        """True if this figure is alive in *year*."""
        return self.died is None and year >= self.born

    @property
    def display_name(self) -> str:
        """Name with the highest title attached."""
        if self.titles:
            return "%s %s" % (self.name, self.titles[-1])
        return self.name

    def summary(self) -> str:
        """A one-line biography."""
        race = creature_data.get(self.creature_id or self.race)
        bits = ["%s, %s %s" % (self.display_name, race.adjective, self.profession)]
        if self.died is not None:
            bits.append("(%d-%d)" % (self.born, self.died))
        else:
            bits.append("(b. %d)" % self.born)
        if self.kills:
            bits.append("- %d notable kills" % len(self.kills))
        return " ".join(bits)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the figure."""
        return {
            "id": self.id, "name": self.name, "native": self.native_name,
            "race": self.race, "female": self.female, "born": self.born,
            "died": self.died, "cause": self.death_cause, "civ": self.civ_id,
            "site": self.site_id, "prof": self.profession, "titles": self.titles,
            "kills": self.kills, "rel": {str(k): v for k, v in
                                         self.relationships.items()},
            "flags": sorted(self.flags), "stats": self.stats,
            "creature": self.creature_id,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "HistoricalFigure":
        """Rebuild from :meth:`to_dict`."""
        f = cls(int(d["id"]), str(d["name"]), str(d.get("native", "")),
                str(d["race"]), bool(d.get("female", False)), int(d["born"]))
        f.died = d.get("died")
        f.death_cause = str(d.get("cause", ""))
        f.civ_id = d.get("civ")
        f.site_id = d.get("site")
        f.profession = str(d.get("prof", "peasant"))
        f.titles = list(d.get("titles", []))
        f.kills = [int(k) for k in d.get("kills", [])]
        f.relationships = {int(k): v for k, v in (d.get("rel") or {}).items()}
        f.flags = set(d.get("flags", []))
        f.stats = dict(d.get("stats") or {})
        f.creature_id = str(d.get("creature", ""))
        return f

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "HistoricalFigure(%s)" % self.summary()


class HistoricalEvent:
    """Something that happened in a particular year."""

    def __init__(self, eid: int, year: int, kind: str, text: str) -> None:
        self.id = eid
        self.year = year
        self.kind = kind
        self.text = text
        self.figures: List[int] = []
        self.sites: List[int] = []
        self.civs: List[int] = []

    def describe(self, world=None) -> str:
        """The event as a sentence, prefixed with its year."""
        return "%d: %s" % (self.year, self.text)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the event."""
        return {
            "id": self.id, "year": self.year, "kind": self.kind,
            "text": self.text, "figures": self.figures, "sites": self.sites,
            "civs": self.civs,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "HistoricalEvent":
        """Rebuild from :meth:`to_dict`."""
        e = cls(int(d["id"]), int(d["year"]), str(d["kind"]), str(d["text"]))
        e.figures = [int(i) for i in d.get("figures", [])]
        e.sites = [int(i) for i in d.get("sites", [])]
        e.civs = [int(i) for i in d.get("civs", [])]
        return e

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "HistoricalEvent(%d, %s)" % (self.year, self.kind)


class Artifact:
    """A named object of legend."""

    def __init__(
        self, aid: int, name: str, native_name: str, item_def: str, material: str
    ) -> None:
        self.id = aid
        self.name = name
        self.native_name = native_name
        self.item_def = item_def
        self.material = material
        self.creator_hf: Optional[int] = None
        self.created = 0
        self.site_id: Optional[int] = None
        self.holder_hf: Optional[int] = None
        self.description = ""
        self.lost = False

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the artifact."""
        return {
            "id": self.id, "name": self.name, "native": self.native_name,
            "item": self.item_def, "mat": self.material,
            "creator": self.creator_hf, "created": self.created,
            "site": self.site_id, "holder": self.holder_hf,
            "desc": self.description, "lost": self.lost,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Artifact":
        """Rebuild from :meth:`to_dict`."""
        a = cls(int(d["id"]), str(d["name"]), str(d.get("native", "")),
                str(d["item"]), str(d["mat"]))
        a.creator_hf = d.get("creator")
        a.created = int(d.get("created", 0))
        a.site_id = d.get("site")
        a.holder_hf = d.get("holder")
        a.description = str(d.get("desc", ""))
        a.lost = bool(d.get("lost", False))
        return a

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Artifact(%s)" % self.name


# --------------------------------------------------------------------------- #
# Recording
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Who people were to each other
# --------------------------------------------------------------------------- #
#
# `HistoricalFigure.relationships` is a `Dict[int, str]` that has been declared,
# serialised and reloaded since figures existed, and never once written to or
# read from. `"marriage"` has been in EVENT_KINDS just as long and was never
# recorded either. So the world had heroes and rulers and slain beasts, and
# nobody in it was anybody's anything.

#: The reciprocal of each relationship. A relationship written one way only is
#: a relationship half the code will fail to find.
OPPOSITE: Dict[str, str] = {
    "spouse": "spouse", "parent": "child", "child": "parent",
    "sibling": "sibling", "slayer": "slain_by", "slain_by": "slayer",
    "enemy": "enemy", "lord": "subject", "subject": "lord",
}

#: How relationships read on the legends page.
RELATION_NAMES: Dict[str, str] = {
    "spouse": "married to", "parent": "parent of", "child": "child of",
    "sibling": "sibling of", "slayer": "slayer of",
    "slain_by": "slain by", "enemy": "enemy of", "lord": "lord of",
    "subject": "subject of",
}

#: Odds per year that two eligible figures of a people marry.
MARRY_ODDS = 0.30

#: And that a married pair have a child the world remembers. Low, and capped
#: below, because the first cut let one prolific couple accumulate fifteen
#: children and eight siblings apiece and made births four hundred of the
#: world's four hundred and sixty-seven historical figures. A history where
#: most of the names are somebody's youngest child is not a history.
CHILD_ODDS = 0.12

#: The most children one couple is remembered for.
MAX_CHILDREN = 4

#: Nobody marries before this age, or after their people's prime.
MARRY_AGE = 18


def relate(a, b, kind: str) -> None:
    """Record that *a* is *kind* to *b*, and *b* the opposite to *a*."""
    if a is None or b is None or a.id == b.id:
        return
    a.relationships[b.id] = kind
    b.relationships[a.id] = OPPOSITE.get(kind, kind)


def relations_of(world, figure) -> List[Tuple[str, Any]]:
    """Everybody this figure was something to, as ``(kind, figure)``."""
    out = []
    for other_id, kind in sorted(figure.relationships.items()):
        other = world.figures.get(other_id)
        if other is not None:
            out.append((kind, other))
    return out


def kin_of(world, figure) -> List[Any]:
    """Blood and marriage. The ones who mind when somebody dies."""
    return [f for kind, f in relations_of(world, figure)
            if kind in ("spouse", "parent", "child", "sibling")]


def _marriages(world, rng: RNG, year: int, civs) -> None:
    """People marry and have children, and the world writes it down."""
    for civ in civs:
        if not rng.chance(MARRY_ODDS):
            continue
        pool = [f for f in world.figures.values()
                if f.civ_id == civ.id and f.alive(year)
                and year - f.born >= MARRY_AGE
                and "monster" not in f.flags
                and not any(k == "spouse" for k in f.relationships.values())]
        if len(pool) < 2:
            continue
        a, b = rng.sample(pool, 2)
        if a.female == b.female:
            continue
        relate(a, b, "spouse")
        record(world, year, "marriage",
               "%s and %s were married." % (a.display_name, b.display_name),
               [a.id, b.id], [a.site_id] if a.site_id else [], [civ.id])

    for civ in civs:
        if not rng.chance(CHILD_ODDS):
            continue
        parents = [f for f in world.figures.values()
                   if f.civ_id == civ.id and f.alive(year)
                   and any(k == "spouse" for k in f.relationships.values())]
        if not parents:
            continue
        parents = [f for f in parents
                   if sum(1 for k in f.relationships.values() if k == "child")
                   < MAX_CHILDREN]
        if not parents:
            continue
        parent = rng.choice(parents)
        spouse = next((world.figures.get(i)
                       for i, k in parent.relationships.items()
                       if k == "spouse"), None)
        child = new_figure(world, rng, civ.race, civ.id, parent.site_id,
                           year=year, profession="peasant")
        child.born = year
        _take_family_name(child, parent)
        relate(parent, child, "parent")
        if spouse is not None:
            relate(spouse, child, "parent")
            for sib_id, kind in list(parent.relationships.items()):
                if kind == "child" and sib_id != child.id:
                    relate(world.figures[sib_id], child, "sibling")
        record(world, year, "birth",
               "%s was born to %s." % (child.display_name,
                                       parent.display_name),
               [child.id, parent.id],
               [parent.site_id] if parent.site_id else [], [civ.id])


def _take_family_name(child, parent) -> None:
    """A child carries its parent's family name, where the race has one.

    Generated names are ``given surname``; a child of Varen Kettleby called
    Adelin Fenwick is two strangers, and a family the legends screen cannot
    show as one.
    """
    theirs = parent.name.split()
    mine = child.name.split()
    if len(theirs) < 2 or len(mine) < 2:
        return
    child.name = "%s %s" % (mine[0], " ".join(theirs[1:]))


def record(
    world,
    year: int,
    kind: str,
    text: str,
    figures: Sequence[int] = (),
    sites: Sequence[int] = (),
    civs: Sequence[int] = (),
) -> HistoricalEvent:
    """Append an event to the world's history."""
    ev = HistoricalEvent(world.next_id("event"), year, kind, text)
    ev.figures = [int(f) for f in figures]
    ev.sites = [int(s) for s in sites]
    ev.civs = [int(c) for c in civs]
    world.events.append(ev)
    return ev


def new_figure(
    world,
    rng: RNG,
    race: str,
    civ_id: Optional[int] = None,
    site_id: Optional[int] = None,
    *,
    year: int = 0,
    profession: str = "peasant",
    creature_id: str = "",
    age: Optional[int] = None,
) -> HistoricalFigure:
    """Create and register a historical figure."""
    female = rng.chance(0.5)
    name = name_data.name_for_race(race, rng, female)
    native = name_data._native_word(rng, race, rng.randint(2, 3))
    born = year - (age if age is not None else rng.randint(18, 45))
    fig = HistoricalFigure(world.next_id("hf"), name, native, race, female, born)
    fig.civ_id = civ_id
    fig.site_id = site_id
    fig.profession = profession
    fig.creature_id = creature_id or race
    fig.stats = {
        "prowess": rng.randint(1, 10),
        "cunning": rng.randint(1, 10),
        "renown": 0,
    }
    world.figures[fig.id] = fig
    return fig


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #

_MEGABEAST_NAMES_USED: Set[str] = set()


def _pick_leader(world, rng: RNG, civ, year: int) -> Optional[HistoricalFigure]:
    """Crown a new leader for a civilization."""
    if civ.destroyed is not None:
        return None
    fig = new_figure(world, rng, civ.race, civ.id, civ.capital, year=year,
                     profession="ruler")
    fig.titles.append(name_data.title_for(rng, "leader", fig.female))
    fig.flags.add("leader")
    civ.leader_hf = fig.id
    # The leader before this one, and whoever leads the peoples they are at
    # war with. A crown is a set of relationships more than it is a hat.
    for other in _living_civs(world):
        if other.id == civ.id or civ.id not in other.at_war_with:
            continue
        rival = world.figures.get(other.leader_hf) if other.leader_hf else None
        if rival is not None and rival.alive(year):
            relate(fig, rival, "enemy")
    site = world.site(civ.capital) if civ.capital else None
    if site is not None:
        site.ruler_hf = fig.id
    record(
        world, year, "became_leader",
        "%s became the leader of %s." % (fig.display_name, civ.name),
        [fig.id], [civ.capital] if civ.capital else [], [civ.id],
    )
    return fig


def _spawn_megabeast(world, rng: RNG, year: int) -> Optional[HistoricalFigure]:
    """Bring a megabeast into the world."""
    beasts = [c for c in creature_data.megabeasts() if c.frequency > 0]
    if not beasts:
        return None
    defn = rng.choice(beasts)
    name = name_data.beast_name(rng)
    fig = new_figure(world, rng, "human", None, None, year=year,
                     profession=defn.name, creature_id=defn.id,
                     age=rng.randint(100, 900))
    fig.name = name
    fig.flags.add("monster")
    fig.titles.append(name_data.title_for(rng, "monster"))
    fig.stats["prowess"] = rng.randint(12, 25)
    # It has to live somewhere. A megabeast used to be a name and a body count
    # and nothing else -- it raided a settlement each year from nowhere in
    # particular -- so the quest to kill one had nowhere to send you and made a
    # cave up, `rng.choice(lairs)`, unrelated to the beast. The lair is now the
    # beast's own, `site_id` being a field every figure has already had.
    lairs = [s for s in world.sites
             if s.kind in ("lair", "cave") and not s.is_ruin
             and not _lair_of(world, s.id, year)]
    if lairs:
        fig.site_id = rng.choice(lairs).id
    record(
        world, year, "beast_attack",
        "The %s %s awoke in the wilds." % (defn.name, fig.display_name),
        [fig.id],
    )
    return fig


def _lair_of(world, site_id: int, year: int):
    """The living monster that lairs at a site, if one does.

    One beast to a cave: two of them sharing would mean the quest naming the
    place could still send you at the wrong one.
    """
    for f in world.figures.values():
        if ("monster" in f.flags and f.site_id == site_id
                and f.alive(year)):
            return f
    return None


def lair_beast(world, site_id: int, year: int):
    """Public form of :func:`_lair_of`, for the map builder and the quests."""
    return _lair_of(world, site_id, year)


def _living_monsters(world, year: int) -> List[HistoricalFigure]:
    return [
        f for f in world.figures.values()
        if "monster" in f.flags and f.alive(year)
    ]


def _living_civs(world) -> List[Any]:
    return [c for c in world.civs if c.destroyed is None]


def _live_sites(world, civ) -> List[Any]:
    out = []
    for sid in civ.sites:
        s = world.site(sid)
        if s is not None and not s.is_ruin:
            out.append(s)
    return out


def _make_artifact(world, rng: RNG, creator, year: int, site) -> Artifact:
    """Forge a named artifact."""
    kinds = [
        "long_sword", "battle_axe", "warhammer", "spear", "crown", "helm",
        "breastplate", "shield", "book", "instrument", "gem",
    ]
    kinds = [k for k in kinds if item_data.exists(k)] or ["long_sword"]
    item_id = rng.choice(kinds)
    defn = item_data.get(item_id)
    # Legends are not forged from lead, ice or ash.
    banned = {"lead", "ice", "water", "ash", "charcoal", "soap", "plant",
              "meat", "bread", "cheese", "alcohol"}
    mats = [
        m for m in mat_data.MATERIALS.values()
        if any(f in m.flags for f in defn.materials)
        and m.id not in banned
        and m.category in ("metal", "gem", "wood", "bone", "glass", "leather",
                           "cloth", "stone")
    ]
    if mats:
        weights = {}
        for m in mats:
            # Adamantine exists, but a legend made of it is itself a legend.
            weights[m.id] = 2.0 if m.id == "adamantine" else float(max(1, m.value))
        material = rng.weighted(weights)
    else:
        material = "steel"
    native, translated = name_data.artifact_name(rng, creator.race)
    art = Artifact(world.next_id("artifact"), translated, native, item_id,
                   material)
    art.creator_hf = creator.id
    art.created = year
    art.site_id = site.id if site else None
    art.holder_hf = creator.id
    mat_adj = mat_data.get(material).adjective
    art.description = "%s %s %s. On it is an image of %s." % (
        indefinite_article(mat_adj).capitalize(), mat_adj, defn.name,
        rng.choice([
            "a dwarf slaying a beast", "the founding of a fortress",
            "a burning tower", "a weeping figure", "a crown of gold",
            "two armies meeting on a field", "a great serpent",
            "the moon over mountains",
        ]),
    )
    world.artifacts.append(art)
    creator.flags.add("legendary")
    record(
        world, year, "artifact_created",
        "%s created %s, a %s %s, in %s." % (
            creator.display_name, art.name, mat_data.get(material).adjective,
            defn.name, site.name if site else "the wilds",
        ),
        [creator.id], [site.id] if site else [],
    )
    return art


def _destroy_site(world, rng: RNG, site, year: int, reason: str,
                  attacker: Optional[HistoricalFigure] = None) -> None:
    """Wipe out a settlement."""
    site.destroyed = year
    site.population = 0
    world.tile(site.wx, site.wy).feature = "ruin"
    figs = [attacker.id] if attacker else []
    record(
        world, year, "site_destroyed",
        "%s was destroyed %s." % (site.name, reason),
        figs, [site.id], [site.civ_id] if site.civ_id else [],
    )


def simulate(world, rng: RNG, years: int, progress=None) -> None:
    """Run the world's history forward by *years*."""
    world.history_years = years
    start_year = 1

    for civ in world.civs:
        _pick_leader(world, rng, civ, start_year)
        for sid in civ.sites:
            site = world.site(sid)
            if site is None:
                continue
            record(
                world, start_year, "founded_site",
                "%s was founded by %s." % (site.name, civ.name),
                [], [site.id], [civ.id],
            )

    for year in range(start_year, years + 1):
        if progress is not None and year % 8 == 0:
            progress("Recording history: year %d" % year, 0.72 + 0.26 * year / years)
        _simulate_year(world, rng, year)

    world.year = max(years + 1, 1)
    _finalize(world, rng)


def _simulate_year(world, rng: RNG, year: int) -> None:
    """One year of world history."""
    civs = _living_civs(world)

    # Leaders die and are replaced.
    for civ in civs:
        leader = world.figures.get(civ.leader_hf) if civ.leader_hf else None
        if leader is None or not leader.alive(year):
            _pick_leader(world, rng, civ, year)
            continue
        age = year - leader.born
        lifespan = creature_data.get(civ.race).lifespan[1]
        if age > lifespan * 0.8 and rng.chance(0.12):
            leader.died = year
            leader.death_cause = "died of old age"
            record(
                world, year, "death",
                "%s died of old age." % leader.display_name,
                [leader.id], [], [civ.id],
            )

    # People marry, and have children who go on to be somebody.
    _marriages(world, rng, year, civs)

    # Civilizations expand.
    for civ in civs:
        live = _live_sites(world, civ)
        if not live:
            continue
        if rng.chance(0.06 + 0.01 * len(live)):
            from .civ import found_site, site_kind_for

            rank = "major" if (len(live) < 3 or rng.chance(0.3)) else "minor"
            site = found_site(world, civ, rng, site_kind_for(civ.race, rank), year)
            if site is not None:
                record(
                    world, year, "founded_site",
                    "%s founded %s." % (civ.name, site.name),
                    [], [site.id], [civ.id],
                )
        for s in live:
            s.population = max(0, int(s.population * rng.uniform(0.99, 1.03)))

    # Notable people are born and make names for themselves.
    for civ in civs:
        live = _live_sites(world, civ)
        if not live or not rng.chance(0.5):
            continue
        site = rng.choice(live)
        prof = rng.weighted({
            "warrior": 3.0, "smith": 2.0, "poet": 1.0, "hunter": 1.5,
            "merchant": 1.5, "scholar": 1.0, "priest": 1.0, "soldier": 2.0,
        })
        fig = new_figure(world, rng, civ.race, civ.id, site.id, year=year,
                         profession=prof, age=rng.randint(18, 40))
        record(
            world, year, "birth",
            "%s the %s %s came of age in %s." % (
                fig.name, creature_data.get(civ.race).adjective, prof, site.name
            ),
            [fig.id], [site.id], [civ.id],
        )
        if prof == "smith" and rng.chance(0.25):
            _make_artifact(world, rng, fig, year, site)
        if prof in ("warrior", "soldier") and rng.chance(0.2):
            fig.flags.add("hero")
            fig.titles.append(name_data.title_for(rng, "hero"))
            fig.stats["prowess"] = fig.stats.get("prowess", 5) + rng.randint(3, 9)
            record(
                world, year, "hero_rose",
                "%s rose to prominence as a warrior of %s." % (
                    fig.display_name, civ.name),
                [fig.id], [site.id], [civ.id],
            )

    # Megabeasts wake and hunt.
    if rng.chance(0.10) and len(_living_monsters(world, year)) < 8:
        _spawn_megabeast(world, rng, year)

    for beast in _living_monsters(world, year):
        if not rng.chance(0.16):
            continue
        targets = [
            s for s in world.sites if s.is_settlement and not s.is_ruin
        ]
        if not targets:
            continue
        site = rng.choice(targets)
        beast_def = creature_data.get(beast.creature_id)
        killed = rng.randint(1, max(2, site.population // 8))
        site.population = max(0, site.population - killed)
        record(
            world, year, "beast_attack",
            "The %s %s attacked %s and killed %d." % (
                beast_def.name, beast.display_name, site.name, killed),
            [beast.id], [site.id], [site.civ_id] if site.civ_id else [],
        )
        beast.stats["renown"] = beast.stats.get("renown", 0) + killed
        if site.population <= 0:
            _destroy_site(world, rng, site, year,
                          "by the %s %s" % (beast_def.name, beast.display_name),
                          beast)
            continue
        # A hero may answer.
        heroes = [
            f for f in world.figures.values()
            if "hero" in f.flags and f.alive(year) and f.civ_id == site.civ_id
        ]
        if heroes and rng.chance(0.5):
            hero = rng.choice(heroes)
            hero_power = hero.stats.get("prowess", 5) + rng.randint(0, 8)
            beast_power = beast.stats.get("prowess", 12) + rng.randint(0, 8)
            if hero_power > beast_power:
                beast.died = year
                beast.death_cause = "slain by %s" % hero.display_name
                hero.kills.append(beast.id)
                hero.flags.add("legendary")
                relate(hero, beast, "slayer")
                record(
                    world, year, "beast_slain",
                    "%s slew the %s %s near %s." % (
                        hero.display_name, beast_def.name, beast.display_name,
                        site.name),
                    [hero.id, beast.id], [site.id],
                )
            else:
                hero.died = year
                hero.death_cause = "slain by the %s %s" % (
                    beast_def.name, beast.display_name)
                beast.kills.append(hero.id)
                relate(beast, hero, "slayer")
                record(
                    world, year, "death",
                    "%s was slain by the %s %s near %s." % (
                        hero.display_name, beast_def.name, beast.display_name,
                        site.name),
                    [hero.id, beast.id], [site.id],
                )

    # Wars.
    if len(civs) >= 2 and rng.chance(0.10):
        a, b = rng.sample(civs, 2)
        if b.id not in a.at_war_with:
            a.at_war_with.add(b.id)
            b.at_war_with.add(a.id)
            record(
                world, year, "war_declared",
                "%s declared war on %s." % (a.name, b.name),
                [], [], [a.id, b.id],
            )

    for civ in civs:
        for enemy_id in list(civ.at_war_with):
            enemy = world.civ(enemy_id)
            if enemy is None or enemy.destroyed is not None:
                civ.at_war_with.discard(enemy_id)
                continue
            if civ.id > enemy.id or not rng.chance(0.30):
                continue
            _fight_battle(world, rng, civ, enemy, year)
        if civ.at_war_with and rng.chance(0.10):
            enemy_id = rng.choice(sorted(civ.at_war_with))
            enemy = world.civ(enemy_id)
            if enemy is not None:
                civ.at_war_with.discard(enemy_id)
                enemy.at_war_with.discard(civ.id)
                record(
                    world, year, "peace",
                    "%s and %s made peace." % (civ.name, enemy.name),
                    [], [], [civ.id, enemy.id],
                )

    # Necromancers, bandits, plagues.
    if rng.chance(0.05) and civs:
        civ = rng.choice(civs)
        live = _live_sites(world, civ)
        if live:
            fig = new_figure(world, rng, civ.race, civ.id, live[0].id, year=year,
                             profession="necromancer", age=rng.randint(30, 60))
            fig.flags.add("necromancer")
            fig.civ_id = None
            record(
                world, year, "became_necromancer",
                "%s learned the secrets of life and death and fled into the "
                "wilderness." % fig.display_name,
                [fig.id], [live[0].id], [civ.id],
            )
            towers = [s for s in world.sites if s.kind == "tower"]
            if towers:
                tower = rng.choice(towers)
                tower.owner_hf = fig.id
                record(
                    world, year, "tower_built",
                    "%s took up residence in %s." % (fig.display_name, tower.name),
                    [fig.id], [tower.id],
                )

    if rng.chance(0.05):
        settlements = [s for s in world.sites if s.is_settlement]
        if settlements:
            site = rng.choice(settlements)
            lost = rng.randint(1, max(2, site.population // 4))
            site.population = max(0, site.population - lost)
            record(
                world, year, "plague",
                "A plague swept through %s, killing %d." % (site.name, lost),
                [], [site.id],
            )

    if rng.chance(0.08):
        camps = [s for s in world.sites if s.kind == "camp"]
        if camps:
            camp = rng.choice(camps)
            leader = new_figure(world, rng, "human", None, camp.id, year=year,
                                profession="bandit leader")
            leader.flags.add("bandit")
            camp.owner_hf = leader.id
            camp.name = name_data.group_name(rng, "bandit")
            record(
                world, year, "banditry",
                "%s gathered a band of outlaws at %s." % (
                    leader.display_name, camp.name),
                [leader.id], [camp.id],
            )

    if rng.chance(0.06) and world.artifacts:
        art = rng.choice(world.artifacts)
        if not art.lost:
            thieves = [
                f for f in world.figures.values()
                if f.alive(year) and ("bandit" in f.flags or "monster" in f.flags)
            ]
            if thieves:
                thief = rng.choice(thieves)
                art.holder_hf = thief.id
                art.site_id = thief.site_id
                record(
                    world, year, "artifact_stolen",
                    "%s stole %s." % (thief.display_name, art.name),
                    [thief.id], [art.site_id] if art.site_id else [],
                )


def _fight_battle(world, rng: RNG, a, b, year: int) -> None:
    """Resolve one battle between two civilizations at war."""
    a_sites = _live_sites(world, a)
    b_sites = _live_sites(world, b)
    if not a_sites or not b_sites:
        return
    target = rng.choice(b_sites)
    a_power = sum(s.population for s in a_sites) + rng.randint(0, 200)
    b_power = sum(s.population for s in b_sites) + rng.randint(0, 200)
    dead_a = rng.randint(1, 60)
    dead_b = rng.randint(1, 60)
    record(
        world, year, "battle",
        "The forces of %s met the forces of %s near %s. %d and %d fell."
        % (a.name, b.name, target.name, dead_a, dead_b),
        [], [target.id], [a.id, b.id],
    )
    for s in a_sites:
        s.population = max(0, s.population - dead_a // max(1, len(a_sites)))
    for s in b_sites:
        s.population = max(0, s.population - dead_b // max(1, len(b_sites)))

    if a_power > b_power * 1.6 and rng.chance(0.4):
        if rng.chance(0.5):
            _destroy_site(world, rng, target, year, "in the war with %s" % a.name)
        else:
            target.civ_id = a.id
            if target.id in b.sites:
                b.sites.remove(target.id)
            a.sites.append(target.id)
            world.tile(target.wx, target.wy).civ_id = a.id
            record(
                world, year, "site_conquered",
                "%s was conquered by %s." % (target.name, a.name),
                [], [target.id], [a.id, b.id],
            )
        if not _live_sites(world, b):
            b.destroyed = year
            record(
                world, year, "site_destroyed",
                "%s was wiped from the world." % b.name, [], [], [b.id],
            )


def _finalize(world, rng: RNG) -> None:
    """Tidy up after the simulation: fill empty sites, place artifacts."""
    year = world.year
    for civ in world.civs:
        if civ.destroyed is None and (
            civ.leader_hf is None
            or not world.figures[civ.leader_hf].alive(year)
        ):
            _pick_leader(world, rng, civ, year)
    for site in world.sites:
        if site.is_settlement and site.population <= 0:
            site.population = rng.randint(4, 30)
    for art in world.artifacts:
        holder = world.figures.get(art.holder_hf) if art.holder_hf else None
        if holder is None or not holder.alive(year):
            art.holder_hf = None
            if art.site_id is None and world.sites:
                art.site_id = rng.choice(world.sites).id


# --------------------------------------------------------------------------- #
# Queries used by quests, rumours and legends
# --------------------------------------------------------------------------- #


def living_figures(world, *, flags: Sequence[str] = ()) -> List[HistoricalFigure]:
    """Every figure still alive, optionally filtered by flag."""
    year = world.year
    out = [f for f in world.figures.values() if f.alive(year)]
    if flags:
        out = [f for f in out if any(fl in f.flags for fl in flags)]
    return out


def events_about(world, hf_id: int) -> List[HistoricalEvent]:
    """Every event mentioning a figure."""
    return [e for e in world.events if hf_id in e.figures]


def events_at(world, site_id: int) -> List[HistoricalEvent]:
    """Every event mentioning a site."""
    return [e for e in world.events if site_id in e.sites]


def recent_events(world, n: int = 20) -> List[HistoricalEvent]:
    """The last *n* events recorded."""
    return world.events[-n:]


def notable_events(world, n: int = 30) -> List[HistoricalEvent]:
    """The most story-worthy events, newest first."""
    interesting = {
        "beast_slain", "beast_attack", "site_destroyed", "site_conquered",
        "artifact_created", "artifact_stolen", "war_declared", "hero_rose",
        "became_necromancer", "banditry", "site_reclaimed",
    }
    out = [e for e in world.events if e.kind in interesting]
    return out[-n:][::-1]
