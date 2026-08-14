"""Who knows whom, and what it costs when one of them dies.

Until now a fortress was seven strangers who happened to share a corridor.
Every dwarf got the same thought when anybody died -- "lost a friend to a
violent death" -- whether they had ever stood next to the corpse or not, which
is the kind of detail that quietly tells you the friendship was never modelled.

This models it. Dwarves who spend time near each other form a bond, at a rate
their personalities decide; the bond has a name a player can read; and when
somebody dies, the fortress grieves in proportion to what it actually lost.
Lovers marry, married couples have children, and the children grow up and pick
up a pick.

Nothing here is a separate simulation. Bonds move where dwarves already stand,
which means the tavern you built is the reason your fortress has friends in
it, and the corridor you never widened is the reason it does not.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..data.calendar import TICKS_PER_DAY

#: Bond value thresholds, strongest first, and what to call one.
LEVELS: Tuple[Tuple[int, str], ...] = (
    (80, "close friend"),
    (45, "friend"),
    (15, "friendly with"),
    (-14, "knows"),
    (-44, "annoyed by"),
    (-100, "enemy of"),
)

#: A meeting closes this fraction of the distance to where the pair is
#: heading. Big at first, small near the ceiling: you can like somebody by
#: Tuesday and still be working up to trusting them in the spring.
APPROACH = 14

#: A pair can only affect each other this often. Two dwarves working the same
#: corridor all day are colleagues, not soulmates.
MEET_COOLDOWN = TICKS_PER_DAY

#: The values a pair either share or argue about.
SHARED_VALUES: Tuple[str, ...] = (
    "family", "friendship", "loyalty", "tradition", "harmony",
    "craftsmanship", "martial_prowess", "knowledge",
)

#: Where the average pair of dwarves sits, and how far the tails are pulled
#: out from it. Tuned so roughly a quarter of pairs can become friends, a few
#: per cent can become close friends, and a few per cent cannot stand each
#: other -- a fortress with a handful of real friendships in it, not a commune.
CENTRE = 0.19
SPREAD = 1.6

#: The bond a pair needs before they are lovers. Only a few pairs in a
#: fortress have a ceiling this high, which is the point: love is what
#: happens to the two dwarves who were always going to get on.
LOVE_AT = 70

#: Odds per season that a pair of lovers marry. Lovers marry; there is no
#: second, higher bond to clear, because a threshold that only one pair in
#: two hundred can reach is a wedding the game never shows anybody.
MARRY_ODDS = 0.4

#: Facets that decide whether a pair get on at all. High in both is easy
#: company; high anger and low tolerance is a grudge waiting for a corridor.
WARM = ("friendliness", "gregariousness", "altruism", "humour", "politeness",
        "tolerance", "cheer")
COLD = ("anger", "hate_propensity", "envy", "cruelty", "pride")

#: What one death does to somebody who knew them. Stress, so bigger is worse.
GRIEF: Tuple[Tuple[str, int], ...] = (
    ("spouse", 90),
    ("child", 90),
    ("lover", 60),
    ("close friend", 45),
    ("friend", 28),
    ("friendly with", 16),
    ("knows", 8),
)

#: Nobody grieves an enemy. They are quietly pleased, and ashamed of it.
SPITE = -6

#: Ticks a dwarf can go without company before it starts to mind.
LONELY_AT = TICKS_PER_DAY * 3

#: How much loneliness costs, once a season.
LONELY_STRESS = 8

#: A dwarf under this age is a child: it eats, it plays, it takes no jobs.
CHILD_AGE = 12

#: Odds per season that a married couple in a fortress with food have a child.
BIRTH_ODDS = 0.35

#: Nobody gives birth in a fortress this hungry, or this crowded.
BIRTH_FOOD = 20
BIRTH_POPULATION = 60


class Bond:
    """What two dwarves are to each other.

    Stored once per pair with the lower id first, so there is exactly one
    answer to "what are these two to each other" rather than two that can
    disagree.
    """

    __slots__ = ("a", "b", "value", "kind", "met")

    def __init__(self, a: int, b: int, value: int = 0, kind: str = "",
                 met: int = 0) -> None:
        self.a, self.b = (a, b) if a < b else (b, a)
        self.value = value
        #: ``""``, ``"lover"``, ``"spouse"``, ``"widowed"`` or ``"child"``
        #: (which covers both directions: parent and child). Runs alongside
        #: the value, so a spouse you have fallen out with is still a spouse.
        self.kind = kind
        self.met = met

    @property
    def key(self) -> Tuple[int, int]:
        """The pair, as it is stored."""
        return (self.a, self.b)

    def other(self, dwarf_id: int) -> int:
        """The one of the pair that is not this one."""
        return self.b if dwarf_id == self.a else self.a

    @property
    def level(self) -> str:
        """The word for how well they get on."""
        for threshold, name in LEVELS:
            if self.value >= threshold:
                return name
        return "enemy of"

    @property
    def label(self) -> str:
        """What the units screen calls it.

        Family outranks temper: a spouse you have fallen out with is still a
        spouse, and a parent you cannot stand is still a parent.
        """
        if self.kind in ("spouse", "lover", "child", "widowed"):
            return "widow of" if self.kind == "widowed" else self.kind
        return self.level

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the bond."""
        return {"a": self.a, "b": self.b, "v": self.value,
                "k": self.kind, "m": self.met}

    @classmethod
    def from_dict(cls, d) -> "Bond":
        """Rebuild from :meth:`to_dict`."""
        return cls(int(d["a"]), int(d["b"]), int(d.get("v", 0)),
                   str(d.get("k", "")), int(d.get("m", 0)))


# --------------------------------------------------------------------------- #
# Looking bonds up
# --------------------------------------------------------------------------- #


def _key(a, b) -> Tuple[int, int]:
    """The storage key for a pair of dwarves."""
    x, y = a.id, b.id
    return (x, y) if x < y else (y, x)


def bond(fort, a, b) -> Optional[Bond]:
    """What these two are to each other, if they are anything."""
    return fort.bonds.get(_key(a, b))


def bonds_of(fort, dwarf) -> List[Bond]:
    """Every bond this dwarf has, strongest feeling first."""
    out = [bd for bd in fort.bonds.values()
           if dwarf.id in (bd.a, bd.b)]
    out.sort(key=lambda bd: (bd.kind == "spouse", bd.kind == "lover",
                             abs(bd.value)), reverse=True)
    return out


def spouse_of(fort, dwarf):
    """The dwarf this one is married to, if it is married and they are here."""
    for bd in fort.bonds.values():
        if bd.kind == "spouse" and dwarf.id in (bd.a, bd.b):
            return fort.creatures.get(bd.other(dwarf.id))
    return None


def describe(fort, dwarf, other) -> str:
    """``"close friend"``, or ``""`` if they have never met."""
    bd = bond(fort, dwarf, other)
    return bd.label if bd is not None else ""


def forget(fort, dwarf_id: int) -> None:
    """Drop every bond involving a dwarf who is no longer in the fortress.

    Only for dwarves that leave. The dead keep their bonds, because who the
    dead were close to is exactly what the survivors are grieving.
    """
    for key in [k for k in fort.bonds if dwarf_id in k]:
        del fort.bonds[key]


# --------------------------------------------------------------------------- #
# Forming them
# --------------------------------------------------------------------------- #


def compatibility(a, b) -> float:
    """How well these two could ever get on, -1..1.

    Centred on the average dwarf, so fifty in everything scores zero: a warm
    pair comes out positive and an angry one negative, rather than everybody
    being mildly fond of everybody. Warmth is the pair's average, because it
    only takes one sociable dwarf to start a conversation and two cold ones
    will not. Shared values pull them together, because agreeing about what
    matters is most of what friendship is, and a dwarf who values family and
    one who does not will have that argument eventually.
    """
    pa, pb = a.personality, b.personality
    warm = sum(pa.facet(f) + pb.facet(f) for f in WARM) / (2.0 * len(WARM))
    cold = sum(pa.facet(f) + pb.facet(f) for f in COLD) / (2.0 * len(COLD))
    temper = ((warm - 50) - (cold - 50)) / 30.0

    shared = 0.0
    for value in SHARED_VALUES:
        gap = abs(pa.value(value) - pb.value(value))
        shared += 1.0 - gap / 35.0
    shared /= len(SHARED_VALUES)

    # Spread and re-centre. Raw, almost every pair of dwarves lands in a
    # narrow band of mild fondness -- nobody ever dislikes anybody and nobody
    # is ever close enough to marry -- because they are all the same race with
    # the same leanings. The band is real; what it needs is a tail at each end.
    raw = temper * 0.55 + shared * 0.75
    return max(-1.0, min(1.0, (raw - CENTRE) * SPREAD))


def ceiling(a, b) -> int:
    """The best -- or worst -- these two will ever be to each other.

    This is what makes personality matter. Compatibility used to set only the
    rate, so every pair in a fortress ended up inseparable given enough
    months in the same tavern; as a ceiling it means a merely agreeable pair
    plateaus as friendly acquaintances and never becomes more, and only a
    genuinely well-matched one gets as far as marrying.
    """
    return int(round(100 * compatibility(a, b)))


def meet(fort, a, b) -> Optional[Bond]:
    """Two dwarves spend a moment together. Returns the bond if it moved.

    Bounded by a cooldown, so standing beside somebody all day is worth one
    conversation, not four hundred. The bond moves a fraction of the distance
    still to run, so acquaintance is quick and friendship takes a season --
    the shape a friendship actually has.
    """
    if a is b:
        return None
    key = _key(a, b)
    bd = fort.bonds.get(key)
    if bd is None:
        bd = Bond(a.id, b.id, met=fort.ticks)
        fort.bonds[key] = bd
    elif fort.ticks - bd.met < MEET_COOLDOWN:
        return None
    bd.met = fort.ticks
    a.fort.lonely = 0
    b.fort.lonely = 0

    cap = ceiling(a, b)
    gap = cap - bd.value
    if gap == 0:
        return bd
    step = max(1, abs(gap) // APPROACH)
    before = bd.value
    bd.value += step if gap > 0 else -step
    if (gap > 0) != (cap - bd.value > 0):
        bd.value = cap        # do not overshoot on the last step
    _announce(fort, a, b, bd, before)
    return bd


def _announce(fort, a, b, bd: Bond, before: int) -> None:
    """Say something only when the relationship actually changes name."""
    if bd.kind or _level_of(before) == _level_of(bd.value):
        return
    if bd.value >= 80:
        fort.log.good("%s and %s have become close friends." % (a.name, b.name))
    elif bd.value >= 45:
        fort.log.info("%s and %s have become friends." % (a.name, b.name))
    elif bd.value <= -45:
        fort.log.warn("%s and %s cannot stand each other." % (a.name, b.name))


def _level_of(value: int) -> str:
    """The level name a raw value falls in."""
    for threshold, name in LEVELS:
        if value >= threshold:
            return name
    return "enemy of"


# --------------------------------------------------------------------------- #
# Grief
# --------------------------------------------------------------------------- #


def grieve(fort, dead) -> None:
    """Everybody who knew the dead feels it, in proportion to knowing them.

    A stranger notices a funeral. A spouse loses the fortress along with the
    dwarf, which is where the classic death spiral starts, and it should:
    a fortress that has never let anybody make a friend has nothing to lose
    and no reason to keep going either.
    """
    weights = dict(GRIEF)
    for bd in bonds_of(fort, dead):
        other = fort.creatures.get(bd.other(dead.id))
        if other is None or other.body.dead \
                or getattr(other, "fort", None) is None:
            continue
        stress = weights.get(bd.label, weights.get(bd.level, 0))
        if bd.value <= -45 and not bd.kind:
            other.needs.add_thought("outlived an enemy", SPITE)
            continue
        if not stress:
            continue
        other.needs.add_thought("lost %s" % _grief_words(bd.label), stress)
        if bd.kind == "spouse":
            bd.kind = "widowed"
            fort.log.bad("%s is widowed." % other.name)


def _grief_words(label: str) -> str:
    """How a dwarf would put it."""
    return {
        "spouse": "a spouse",
        "close friend": "a close friend",
        "friend": "a friend",
        "friendly with": "somebody they liked",
        "knows": "somebody they knew",
    }.get(label, "somebody they knew")


# --------------------------------------------------------------------------- #
# Marriage
# --------------------------------------------------------------------------- #


def eligible(fort, dwarf) -> bool:
    """Whether this dwarf could fall in love with anybody at all."""
    if dwarf.body.dead or getattr(dwarf, "fort", None) is None:
        return False
    if dwarf.age < CHILD_AGE:
        return False
    return not any(bd.kind in ("lover", "spouse")
                   for bd in bonds_of(fort, dwarf))


def court(fort) -> None:
    """Bonds strong enough to be something else become something else.

    Love needs the propensity for it as well as the bond: a dwarf with none
    has close friends and stays that way, which is a perfectly good life and
    one the fortress should be able to contain.
    """
    for bd in list(fort.bonds.values()):
        if bd.kind not in ("", "lover"):
            continue
        a = fort.creatures.get(bd.a)
        b = fort.creatures.get(bd.b)
        if a is None or b is None or a.body.dead or b.body.dead:
            continue
        if bd.kind == "lover":
            if fort.rng.chance(MARRY_ODDS):
                _wed(fort, bd, a, b)
            continue
        if not eligible(fort, a) or not eligible(fort, b):
            continue
        if bd.value >= LOVE_AT and _romantic(fort, a, b):
            bd.kind = "lover"
            fort.log.good("%s and %s have become lovers." % (a.name, b.name))


def _romantic(fort, a, b) -> bool:
    """Whether these two would take it further, this season."""
    drive = (a.personality.facet("love_propensity")
             + b.personality.facet("love_propensity")) / 200.0
    return fort.rng.chance(max(0.05, min(0.9, drive)))


def _wed(fort, bd: Bond, a, b) -> None:
    """Marry a pair, and write it into the world that will outlive them."""
    from ..world import history as history_mod

    bd.kind = "spouse"
    fort.log.good("%s and %s are married!" % (a.name, b.name))
    for d in (a, b):
        d.needs.add_thought("was married", -25)
        d.value_thought("romance", -20, "married for love")
    for other in fort.dwarves():
        if other is not a and other is not b:
            other.needs.add_thought("attended a wedding", -4)
    figs = [d.hf_id for d in (a, b) if d.hf_id is not None]
    history_mod.record(
        fort.world, fort.time.year, "marriage",
        "%s and %s were married at %s." % (a.name, b.name, fort.name),
        figs, [fort.site_id] if fort.site_id else [],
        [fort.civ_id] if fort.civ_id else [])


# --------------------------------------------------------------------------- #
# Children
# --------------------------------------------------------------------------- #


def couples(fort) -> List[Tuple[Any, Any]]:
    """Every married pair both of whom are alive and here."""
    out = []
    for bd in fort.bonds.values():
        if bd.kind != "spouse":
            continue
        a = fort.creatures.get(bd.a)
        b = fort.creatures.get(bd.b)
        if a is None or b is None or a.body.dead or b.body.dead:
            continue
        if getattr(a, "fort", None) is None or getattr(b, "fort", None) is None:
            continue
        out.append((a, b))
    return out


def is_child(dwarf) -> bool:
    """Too young to work."""
    return dwarf.age < CHILD_AGE


def children(fort) -> List:
    """Everybody in the fortress who is still a child."""
    return [d for d in fort.dwarves() if is_child(d)]


def maybe_born(fort) -> Optional[Any]:
    """A married couple may have a child, if the fortress can feed one."""
    if len(fort.dwarves()) >= BIRTH_POPULATION:
        return None
    if fort.food_stock() < BIRTH_FOOD:
        return None
    pairs = [(a, b) for a, b in couples(fort)
             if a.female != b.female and min(a.age, b.age) < 90]
    if not pairs:
        return None
    a, b = fort.rng.choice(pairs)
    if not fort.rng.chance(BIRTH_ODDS):
        return None
    return born(fort, a, b)


def born(fort, a, b):
    """A child is born to a couple, and the world hears about it."""
    from ..world import history as history_mod
    from . import dwarf as dwarf_mod

    mother = a if a.female else b
    child = dwarf_mod.make_dwarf(fort.rng, "child", age=0)
    child.x, child.y, child.z = fort._free_spot(
        (mother.x, mother.y, mother.z), 0)
    child.wx, child.wy = fort.wx, fort.wy
    fort.add_creature(child)
    # A child is born knowing exactly two people, and very well.
    for parent in (a, b):
        fort.bonds[_key(child, parent)] = Bond(
            child.id, parent.id, 60, "child", fort.ticks)
        parent.needs.add_thought("had a child", -20)
        parent.value_thought("family", -18, "has a child of its own")
    fort.log.good("%s has given birth to %s!" % (mother.name, child.name))
    history_mod.record(
        fort.world, fort.time.year, "birth",
        "%s was born at %s." % (child.name, fort.name),
        [f for f in (a.hf_id, b.hf_id) if f is not None],
        [fort.site_id] if fort.site_id else [],
        [fort.civ_id] if fort.civ_id else [])
    return child


def birthdays(fort) -> List:
    """A year passes for everybody. Returns whoever grew up in it."""
    from .labors import PROFESSION_LABORS

    grown = []
    for d in fort.dwarves():
        was_child = is_child(d)
        d.age += 1
        if was_child and not is_child(d):
            profession = fort.rng.choice(list(PROFESSION_LABORS.keys()))
            d.profession = profession
            for labor in PROFESSION_LABORS[profession]:
                d.fort.labors.enable(labor)
            d.needs.add_thought("grew up", -10)
            fort.log.good("%s has grown up, and can work." % d.name)
            grown.append(d)
    return grown


# --------------------------------------------------------------------------- #
# Loneliness
# --------------------------------------------------------------------------- #


def lonely(fort, dwarf) -> bool:
    """Whether this dwarf has gone too long without anybody."""
    return dwarf.fort.lonely > LONELY_AT


def season(fort) -> None:
    """What the fortress thinks of its own company, once a season.

    Knowing a name is not company. The cheerful thought needs a real friend,
    or every dwarf in a crowded corridor collects it for nothing and the
    tavern stops being worth building.
    """
    for d in fort.dwarves():
        if lonely(fort, d):
            d.needs.add_thought("has nobody to talk to", LONELY_STRESS)
            continue
        friends = sum(1 for bd in bonds_of(fort, d)
                      if bd.kind or bd.value >= 45)
        if friends:
            d.needs.add_thought("has friends here", -min(10, 4 + friends))


def summary(fort) -> str:
    """One line for the status bar."""
    kids = len(children(fort))
    if not kids:
        return ""
    return "1 child" if kids == 1 else "%d children" % kids
