"""Engravings: the fortress telling the world's story back to itself.

An engraver smooths a wall and then carves something into it. What it carves
is a real event out of the world's history — the beast your militia killed
last spring, the war your civilization is losing, the artifact somebody made
two hundred years before you were born — phrased the way Dwarf Fortress
phrases it, because that phrasing is the joke and the point at once.

Everything here reads from `world.events` and writes nothing back. An
engraving is a description, a quality and a subject: no simulation, no cost
beyond the job that carved it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..data import creatures as creature_data
from ..engine.rng import RNG

Cell = Tuple[int, int, int]

#: Quality names, matching the ones on a crafted item.
QUALITY_NAMES: Tuple[str, ...] = (
    "rough", "simple", "well-designed", "finely-crafted", "superior",
    "exceptional", "masterful",
)

#: What a wall is worth to the room around it, by quality.
QUALITY_VALUE: Tuple[int, ...] = (0, 1, 2, 3, 5, 8, 14)

#: A dwarf that walks past something this good is cheered up by it.
ADMIRE_AT = 4

#: How events are worded when they become pictures. The first form that fits
#: an event is used, so the specific ones come first.
SUBJECTS: Tuple[Tuple[str, str], ...] = (
    ("beast_slain", "%(figures)s. %(a)s is striking down %(b)s."),
    ("battle", "%(figures)s. They are fighting."),
    ("site_destroyed", "%(figures)s and a burning tower. The tower is burning."),
    ("beast_attack", "%(figures)s. %(a)s is screaming."),
    ("artifact_created", "%(figures)s and an artifact. "
                         "The artifact is surrounded by %(a)s."),
    ("became_leader", "%(figures)s. %(a)s is on a throne."),
    ("hero_rose", "%(figures)s. %(a)s is in a triumphant pose."),
    ("war_declared", "%(figures)s. They are in a fortification."),
    ("founded_site", "%(figures)s and a fortress. "
                     "The fortress is well-crafted."),
    ("death", "%(figures)s. %(a)s is laid out."),
)

#: Fallbacks for when the world has not done anything worth carving.
IMAGES: Tuple[str, ...] = (
    "dwarves and a mountain. The mountain is well-crafted.",
    "a dwarf and an anvil. The dwarf is striking the anvil.",
    "cheese and a dwarf. The dwarf is smiling.",
    "an image of dwarves in a triumphant pose.",
    "a stack of ale barrels and a dwarf. The dwarf is content.",
)


class Engraving:
    """One carved wall."""

    __slots__ = ("quality", "text", "event_id", "maker")

    def __init__(self, quality: int, text: str, event_id: Optional[int] = None,
                 maker: str = "") -> None:
        self.quality = quality
        self.text = text
        self.event_id = event_id
        self.maker = maker

    @property
    def quality_name(self) -> str:
        """``"masterful"`` and friends."""
        return QUALITY_NAMES[min(self.quality, len(QUALITY_NAMES) - 1)]

    @property
    def value(self) -> int:
        """What it adds to the room it is in."""
        return QUALITY_VALUE[min(self.quality, len(QUALITY_VALUE) - 1)]

    def describe(self) -> str:
        """The whole thing, the way the game says it."""
        from ..data.descriptors import indefinite_article

        return "On the wall is %s %s engraving of %s" % (
            indefinite_article(self.quality_name), self.quality_name,
            self.text)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the engraving."""
        return {"q": self.quality, "text": self.text, "event": self.event_id,
                "maker": self.maker}

    @classmethod
    def from_dict(cls, d) -> "Engraving":
        """Rebuild from :meth:`to_dict`."""
        return cls(int(d.get("q", 0)), str(d.get("text", "")),
                   d.get("event"), str(d.get("maker", "")))


# --------------------------------------------------------------------------- #
# Choosing a subject
# --------------------------------------------------------------------------- #


def _figures(world, event) -> Tuple[str, str, str]:
    """Name the figures in an event as an engraver would see them.

    Returns ``(the whole phrase, the first one, the second one)``.
    """
    names = []
    for hf_id in event.figures[:2]:
        fig = world.figures.get(hf_id)
        if fig is None:
            continue
        defn = creature_data.get(fig.creature_id or fig.race)
        # The plain name: an engraving says "Urist the dwarf", not "Urist
        # Ironhand the Brave the dwarf".
        names.append("%s the %s" % (fig.name, defn.name))
    if not names:
        for site_id in event.sites[:1]:
            site = world.site(site_id)
            if site is not None:
                names.append(site.name)
    if not names:
        return ("dwarves", "a dwarf", "a dwarf")
    if len(names) == 1:
        return (names[0], names[0], names[0])
    return ("%s and %s" % (names[0], names[1]), names[0], names[1])


def subject(fort, rng: RNG) -> Tuple[str, Optional[int]]:
    """Pick something to carve. Returns ``(text, event id)``.

    Recent history first: a fortress carves what happened to it, and what
    happened to it is at the end of the world's event list.
    """
    world = fort.world
    kinds = {kind for kind, _phrase in SUBJECTS}
    pool = [e for e in world.events[-120:] if e.kind in kinds]
    # What just happened, first. A fortress carves the siege it survived last
    # spring, not the fourteenth village its civilization founded.
    recent = [e for e in world.events[-25:] if e.kind in kinds]
    if recent and rng.chance(0.6):
        pool = recent
    # Anything that happened here is worth carving twice over.
    ours = [e for e in pool if fort.site_id is not None
            and fort.site_id in e.sites]
    if ours and rng.chance(0.5):
        pool = ours
    if not pool or rng.chance(0.15):
        return (rng.choice(list(IMAGES)), None)
    event = rng.choice(pool)
    phrase = next(p for kind, p in SUBJECTS if kind == event.kind)
    whole, first, second = _figures(world, event)
    text = phrase % {"figures": whole, "a": first, "b": second}
    return ("%s The artwork relates to %s in the year %d."
            % (text, _relates(world, event, first, second), event.year),
            event.id)


#: How each kind of event is named in the caption. A caption is a noun phrase
#: -- "the slaying of the dragon" -- not the sentence the historian wrote.
RELATES: Dict[str, str] = {
    "beast_slain": "the slaying of %(b)s by %(a)s",
    "beast_attack": "the attack on %(site)s",
    "battle": "the battle at %(site)s",
    "site_destroyed": "the destruction of %(site)s",
    "artifact_created": "the making of an artifact by %(a)s",
    "became_leader": "the ascension of %(a)s",
    "hero_rose": "the rise of %(a)s",
    "war_declared": "a war",
    "founded_site": "the founding of %(site)s",
    "death": "the death of %(a)s",
}


def _relates(world, event, first: str, second: str) -> str:
    """The historian's half of the caption, as a noun phrase."""
    site = None
    for site_id in event.sites[:1]:
        found = world.site(site_id)
        if found is not None:
            site = found.name
    phrase = RELATES.get(event.kind)
    if phrase is None or ("%(site)s" in phrase and site is None):
        # One sentence of it: the caption is a label, not the chronicle.
        text = event.text.rstrip(".").split(". ")[0]
        head = text.split(" ", 1)[0] if text else ""
        if head in ("The", "A", "An"):
            text = text[0].lower() + text[1:]
        return text
    return phrase % {"a": first, "b": second, "site": site or "this place"}


def quality_for(dwarf, rng: RNG) -> int:
    """How good the engraver's day was."""
    level = dwarf.skills.level("engraving")
    roll = rng.random() + level * 0.04
    for threshold, quality in ((1.18, 6), (1.05, 5), (0.92, 4), (0.75, 3),
                               (0.55, 2), (0.3, 1)):
        if roll > threshold:
            return quality
    return 0


# --------------------------------------------------------------------------- #
# The fortress's collection
# --------------------------------------------------------------------------- #


def engrave(fort, dwarf, cell: Cell) -> Engraving:
    """Carve one wall and remember what is on it."""
    text, event_id = subject(fort, fort.rng)
    art = Engraving(quality_for(dwarf, fort.rng), text, event_id, dwarf.name)
    fort.engravings[cell] = art
    dwarf.add_exp("engraving", 25)
    if art.quality >= ADMIRE_AT + 1:
        fort.log.good("%s has created a masterful engraving." % dwarf.name)
        dwarf.needs.add_thought("made a masterpiece", -12)
    return art


def at(fort, cell: Cell) -> Optional[Engraving]:
    """The engraving on a cell, if there is one."""
    return fort.engravings.get(cell)


def room_value(fort, cells) -> int:
    """What the engravings in a room add to it."""
    total = 0
    for cell in cells:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            art = fort.engravings.get((cell[0] + dx, cell[1] + dy, cell[2]))
            if art is not None:
                total += art.value
    return total


def admire(fort, dwarf) -> None:
    """A dwarf notices what is on the wall beside it.

    Only good work gets noticed, and only occasionally: a fortress full of
    masterpieces should be a happy one, not a stream of log messages.
    """
    x, y, z = dwarf.x, dwarf.y, dwarf.z
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        art = fort.engravings.get((x + dx, y + dy, z))
        if art is None or art.quality < ADMIRE_AT:
            continue
        dwarf.needs.add_thought("admired a fine engraving", -2 - art.value // 4)
        # And more, or nothing at all, depending on whether this particular
        # dwarf cares about art. Half a fortress should walk past a masterwork.
        dwarf.value_thought("artwork", -art.value // 2,
                            "admired the work on the wall")
        return


def summary(fort) -> str:
    """One line about the fortress's collection."""
    if not fort.engravings:
        return ""
    best = max(fort.engravings.values(), key=lambda a: a.quality)
    return "%d engravings, the best %s" % (len(fort.engravings),
                                           best.quality_name)
