"""What a people think of you, and why they are entitled to.

`Civilization.ethics` has been generated since civilizations were: six moral
positions per people, on killing, theft, trespassing, slavery, eating the
dead and cutting trees, each one `unthinkable`, `shun`, `misguided`, a
`personal_matter`, `acceptable` or `required`. Elves have always considered
felling a tree unthinkable and eating a sapient acceptable; kobolds have
always considered theft *required*. Until now the only thing in the codebase
that read any of it was the legends screen, which printed it.

So the game had renown -- which only ever goes up, and is the same number to
everybody -- and nothing else. Kill a human merchant in the middle of a human
town and the town's opinion of you was unchanged, because the town had no
opinion.

**Standing is per-people and it is signed.** One number per civilization, from
-100 to 100, moved by things you do where somebody can see you. What a deed
costs depends on whose ethics are being offended: murdering somebody in front
of a people who think killing is unthinkable is ruinous, and doing it in front
of goblins, who do not, costs nothing at all. That asymmetry is the entire
point, and it is why this is a module rather than a counter.

**Being seen is the whole of it.** Witnesses are found through v3.6's
`noticed_by`, so a murder nobody saw is a murder nobody minds, and the stealth
skill that has been able to hide you from a guard's attention since v3.6 now
hides what you did from a nation's memory.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

#: The full range of an opinion.
FLOOR = -100
CEILING = 100

#: Where an opinion stops being one thing and becomes another, worst first.
LEVELS: Tuple[Tuple[int, str], ...] = (
    (-60, "hated"), (-25, "disliked"), (-8, "distrusted"), (8, "unknown"),
    (25, "welcome"), (60, "honoured"), (CEILING + 1, "revered"),
)

#: Standing at or below which a people will set on you where they find you.
HOSTILE_AT = -60

#: How much a people care about a deed, by what their ethics say about it.
#: `required` is not a typo: a people who think theft is required think more
#: of a thief, and kobolds have thought exactly that since worldgen.
ETHIC_WEIGHT: Dict[str, float] = {
    "unthinkable": 1.0,
    "shun": 0.7,
    "misguided": 0.4,
    "personal_matter": 0.15,
    "acceptable": 0.0,
    "required": -0.35,
}

#: What each deed is worth before its people's ethics are consulted, and which
#: ethic decides. Positive numbers are things they will like you for, and
#: those are not weighted by ethics at all: nobody's moral code makes killing
#: their monster for them worse.
DEEDS: Dict[str, Tuple[int, Optional[str]]] = {
    "murder": (-45, "killing"),
    "manslaughter": (-18, "killing"),
    "theft": (-25, "theft"),
    "trespass": (-8, "trespassing"),
    "treefelling": (-10, "treefelling"),
    "cannibalism": (-30, "eating_sapients"),
    "quest": (14, None),
    "beast_slain": (20, None),
    "performance": (3, None),
    "gift": (6, None),
}

#: How far a deed carries. Anybody who can see you and has noticed you.
WITNESS_RANGE = 12

#: What standing does to a price, at the extremes. Being welcome is worth a
#: discount and being hated is worth a surcharge, and neither is worth as much
#: as the Appraiser skill, which is the skill that is supposed to move prices.
PRICE_SWING = 0.22


class Standing:
    """Every people's opinion of one adventurer."""

    __slots__ = ("by_civ",)

    def __init__(self) -> None:
        self.by_civ: Dict[int, int] = {}

    def get(self, civ_id: Optional[int]) -> int:
        """This people's opinion, or indifference if they have none."""
        if civ_id is None:
            return 0
        return self.by_civ.get(int(civ_id), 0)

    def add(self, civ_id: Optional[int], amount: int) -> int:
        """Move an opinion and return where it ended up."""
        if civ_id is None or not amount:
            return self.get(civ_id)
        civ_id = int(civ_id)
        value = max(FLOOR, min(CEILING, self.by_civ.get(civ_id, 0) + amount))
        self.by_civ[civ_id] = value
        return value

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole book of opinions."""
        return {str(k): v for k, v in self.by_civ.items()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Standing":
        """Rebuild from :meth:`to_dict`."""
        s = cls()
        for k, v in (d or {}).items():
            try:
                s.by_civ[int(k)] = int(v)
            except (TypeError, ValueError):      # pragma: no cover - defensive
                continue
        return s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Standing(%d peoples)" % len(self.by_civ)


# --------------------------------------------------------------------------- #
# Access
# --------------------------------------------------------------------------- #


def book(game) -> Standing:
    """The standing book, creating it on a game that predates standing."""
    got = getattr(game, "standing", None)
    if got is None:
        got = game.standing = Standing()
    return got


def of(game, civ_id: Optional[int]) -> int:
    """One people's opinion of the player."""
    return book(game).get(civ_id)


def attitude(game, civ_id: Optional[int]) -> str:
    """That opinion as a word."""
    return level_name(of(game, civ_id))


def level_name(value: int) -> str:
    """A standing value as a word."""
    for edge, name in LEVELS:
        if value < edge:
            return name
    return LEVELS[-1][1]


def civ_of(game, creature) -> Optional[int]:
    """Which people a creature belongs to.

    Its own civ id when the site it was generated in had one, and otherwise
    the civilization of its race, which is the honest approximation for a
    wanderer met on the road.
    """
    cid = getattr(creature, "civ_id", None)
    if cid is not None:
        return cid
    race = getattr(creature, "def_id", "")
    for civ in getattr(game.world, "civs", ()):
        if civ.race == race and civ.destroyed is None:
            return civ.id
    return None


def ethic(game, civ_id: Optional[int], name: str) -> str:
    """What a people say about one kind of act."""
    if civ_id is None:
        return "misguided"
    for civ in getattr(game.world, "civs", ()):
        if civ.id == civ_id:
            return str(civ.ethics.get(name, "misguided"))
    return "misguided"


# --------------------------------------------------------------------------- #
# Deeds
# --------------------------------------------------------------------------- #


def witnesses(game, *, actor=None) -> List[Any]:
    """Everybody who can see the actor and has actually noticed them.

    Through v3.6's `noticed_by`, so sneaking hides what you did and not only
    where you are. A murder nobody saw is a murder nobody minds.
    """
    from . import stealth

    actor = actor or game.player
    out = []
    for c in game.visible_creatures():
        if c is actor or not c.defn.intelligent:
            continue
        if actor.distance_to(c) > WITNESS_RANGE:
            continue
        if not stealth.noticed_by(game, actor, c):
            continue
        out.append(c)
    return out


def weight_for(game, civ_id: Optional[int], deed: str) -> float:
    """How much this people care about this deed, given their ethics."""
    base, key = DEEDS.get(deed, (0, None))
    if key is None or base > 0:
        return 1.0
    return ETHIC_WEIGHT.get(ethic(game, civ_id, key), 0.4)


def value_of(game, civ_id: Optional[int], deed: str) -> int:
    """What this deed is worth to this people, ethics included."""
    base, _key = DEEDS.get(deed, (0, None))
    if not base:
        return 0
    return int(round(base * weight_for(game, civ_id, deed)))


def did(game, deed: str, *, civ_id: Optional[int] = None,
        seen_by: Optional[Sequence[Any]] = None, announce: bool = True) -> Dict[int, int]:
    """Record a deed against whoever saw it. Returns the changes by civ.

    When *civ_id* is given the deed is credited to that people whether or not
    anybody watched -- that is for the things a people find out about anyway,
    like a finished job or a beast killed in their name. Everything else needs
    a witness.
    """
    changes: Dict[int, int] = {}
    if civ_id is not None:
        amount = value_of(game, civ_id, deed)
        if amount:
            changes[int(civ_id)] = amount
    else:
        for who in (witnesses(game) if seen_by is None else seen_by):
            cid = civ_of(game, who)
            if cid is None or cid in changes:
                continue
            amount = value_of(game, cid, deed)
            if amount:
                changes[int(cid)] = amount

    marks = book(game)
    for cid, amount in changes.items():
        before = marks.get(cid)
        after = marks.add(cid, amount)
        if announce and level_name(before) != level_name(after):
            _announce(game, cid, after)
    if changes:
        enforce(game)
    return changes


def _announce(game, civ_id: int, value: int) -> None:
    """Say something when a people change their mind about you."""
    name = _civ_name(game, civ_id)
    word = level_name(value)
    if value <= HOSTILE_AT:
        game.log.bad("%s will kill you on sight." % name)
    elif value < 0:
        game.log.warn("%s consider you %s." % (name, word))
    else:
        game.log.good("%s consider you %s." % (name, word))


def _civ_name(game, civ_id: Optional[int]) -> str:
    """A people's name."""
    for civ in getattr(game.world, "civs", ()):
        if civ.id == civ_id:
            return civ.name
    return "They"


def on_kill(game, victim) -> Dict[int, int]:
    """The player has killed something. Whose problem is that?

    Killing something already trying to kill you is not murder, and killing a
    wolf is not a crime against anybody. Everything else is judged by the
    ethics of whoever was watching, which is how the same act is ruinous in a
    dwarven town and free in a goblin one.
    """
    if not getattr(victim, "defn", None) or not victim.defn.intelligent:
        return {}
    if victim.faction in ("hostile", "wild_hostile"):
        return {}
    seen = witnesses(game)
    if not seen:
        return {}
    deed = "murder" if victim.faction in ("town", "player") else "manslaughter"
    return did(game, deed, seen_by=seen)


# --------------------------------------------------------------------------- #
# Consequences
# --------------------------------------------------------------------------- #


def enforce(game) -> int:
    """Turn a people hostile once they hate you enough. Returns how many.

    Written against the `hostile_to` set that `Creature.is_hostile_to` already
    consults, rather than by teaching that method about civilizations: it is
    called on every pair of creatures in every combat check and has no game to
    ask.
    """
    turned = 0
    for c in game.creatures.values():
        if c.is_player or not c.alive or c.faction in ("hostile", "wild_hostile"):
            continue
        cid = civ_of(game, c)
        if cid is None or of(game, cid) > HOSTILE_AT:
            continue
        if game.player.id not in c.hostile_to:
            c.hostile_to.add(game.player.id)
            turned += 1
    return turned


def price_factor(game, merchant) -> float:
    """What a merchant's people's opinion does to their prices."""
    value = of(game, civ_of(game, merchant))
    return 1.0 - PRICE_SWING * (value / float(CEILING))


def greeting_tone(game, npc) -> str:
    """How somebody of this people opens with you."""
    return attitude(game, civ_of(game, npc))


def summary(game) -> List[str]:
    """Every people who has an opinion, for the character screen."""
    marks = book(game)
    if not marks.by_civ:
        return ["No people has an opinion of you yet."]
    rows = []
    for civ in getattr(game.world, "civs", ()):
        value = marks.by_civ.get(civ.id)
        if value is None:
            continue
        rows.append((value, "%-30s %-11s %+d"
                     % (civ.name[:30], level_name(value), value)))
    rows.sort()
    return [text for _v, text in rows] or ["No people has an opinion of you yet."]


# --------------------------------------------------------------------------- #
# Peoples disliking each other
# --------------------------------------------------------------------------- #


def ethical_distance(a, b) -> float:
    """How far apart two peoples' moral codes are, from 0 to 1.

    Nothing in the world simulation has ever asked why two civilizations went
    to war; `_wars` picked a pair. Two peoples who agree about killing, theft
    and slavery have less to fight about than an elf nation and a goblin one,
    and this is the number that says so.
    """
    keys = set(a.ethics) | set(b.ethics)
    if not keys:
        return 0.0
    order = ("required", "acceptable", "personal_matter", "misguided",
             "shun", "unthinkable")
    total = 0.0
    for key in keys:
        try:
            ia = order.index(a.ethics.get(key, "misguided"))
            ib = order.index(b.ethics.get(key, "misguided"))
        except ValueError:                       # pragma: no cover - defensive
            continue
        total += abs(ia - ib) / float(len(order) - 1)
    return total / len(keys)
