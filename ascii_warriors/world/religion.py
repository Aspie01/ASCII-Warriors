"""Gods, and what a temple is for.

The game has been building temples since sitegen was written. It furnishes them
with an altar and a statue, stations a priest in them, sells you a book at the
door, and calls a room with an altar in it a "temple" -- and there was nothing
to worship. `"altar": "temple"` in `rooms.ROOM_KINDS` was the *only* mention of
a temple in the whole of fortress mode: a named room with a quality score that
no dwarf ever had a reason to walk into.

So this is the thing the scaffolding was waiting for. Every civilization gets a
pantheon at worldgen: a handful of gods with names in the people's own tongue
and spheres they are held to govern. Who worships whom is not stored anywhere.
A person's god is *derived* from their own id against their civilization's
pantheon, which costs nothing to save, survives a reload without being written
down, and gives the same answer in both modes -- a dwarf in your fortress and
the same figure met later in the ruins pray to the same god.

The spheres are not decoration. A god of war is who a soldier thanks, a god of
the forge is who a smith swears by, and `sphere_for` is what makes a dwarf's
prayer sound like it came from that dwarf.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..engine.rng import RNG

#: What a god can be god *of*, and the epithet that comes with it. Ordered so
#: that the first few -- the ones every people cares about -- are the likeliest
#: to be picked for a small pantheon.
SPHERES: Tuple[Tuple[str, str], ...] = (
    ("war", "the Bloodied"),
    ("death", "the Silent"),
    ("craft", "the Maker"),
    ("earth", "the Deep"),
    ("water", "the Drowning"),
    ("fortune", "the Turning Wheel"),
    ("wisdom", "the Long Memory"),
    ("fire", "the Kindler"),
    ("the hunt", "the Patient"),
    ("storms", "the Unquiet"),
    ("love", "the Warm Hand"),
    ("silence", "the Listener"),
    ("gold", "the Bright Hoard"),
    ("the sun", "the Watcher"),
    ("night", "the Long Dark"),
)

#: Which sphere a trade looks to. A smith swears by the forge and a soldier by
#: the god of war, and a dwarf whose own god governs their own work says so.
SPHERE_FOR_PROFESSION: Dict[str, str] = {
    "warrior": "war", "soldier": "war", "guard": "war", "hammerdwarf": "war",
    "smith": "craft", "mason": "craft", "carpenter": "craft",
    "craftsdwarf": "craft", "weaver": "craft", "engraver": "craft",
    "miner": "earth", "hunter": "the hunt", "fisherdwarf": "water",
    "merchant": "fortune", "scholar": "wisdom", "poet": "wisdom",
    "priest": "wisdom", "necromancer": "death", "farmer": "earth",
    "brewer": "fortune", "doctor": "the warm hand",
}

#: How many gods a people keeps. Few enough that each one means something.
MIN_GODS = 3
MAX_GODS = 6


class Deity:
    """A god somebody prays to."""

    def __init__(self, did: int, name: str, native_name: str,
                 spheres: Sequence[str], epithet: str = "") -> None:
        self.id = did
        self.name = name
        self.native_name = native_name
        self.spheres: List[str] = list(spheres)
        self.epithet = epithet
        #: Which civilizations hold this god. Gods are per-people, but two
        #: peoples can come to worship the same one.
        self.civ_ids: List[int] = []

    @property
    def display_name(self) -> str:
        """Name with the epithet, the way a priest would say it."""
        return "%s %s" % (self.name, self.epithet) if self.epithet else self.name

    def sphere_text(self) -> str:
        """"war and the hunt", for a line of prose."""
        from ..data.descriptors import list_join

        return list_join(self.spheres) if self.spheres else "nothing at all"

    def summary(self) -> str:
        """A one-line description for the legends screen."""
        return "%s, god of %s" % (self.display_name, self.sphere_text())

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the god."""
        return {
            "id": self.id, "name": self.name, "native": self.native_name,
            "spheres": self.spheres, "epithet": self.epithet,
            "civs": self.civ_ids,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Deity":
        """Rebuild from :meth:`to_dict`."""
        g = cls(int(d["id"]), str(d["name"]), str(d.get("native", "")),
                list(d.get("spheres", [])), str(d.get("epithet", "")))
        g.civ_ids = [int(c) for c in d.get("civs", [])]
        return g

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Deity(%s)" % self.summary()


def generate(world, rng: RNG) -> None:
    """Give every people a pantheon. Called once, at worldgen."""
    from ..data import names as name_data

    # One naming stream for the whole pantheon, advanced as it goes. A fresh
    # `rng.sub("god")` per god is the same sub-RNG every time, which named
    # every god of a people the same thing.
    names = rng.sub("god-names")
    for civ in world.civs:
        count = rng.randint(MIN_GODS, MAX_GODS)
        spheres = list(SPHERES)
        rng.shuffle(spheres)
        for sphere, epithet in spheres[:count]:
            native = name_data._native_word(names, civ.race, 3)
            god = Deity(world.next_id("deity"), native.capitalize(),
                        native, [sphere], epithet)
            god.civ_ids.append(civ.id)
            world.gods.append(god)


def gods_of(world, civ_id: Optional[int]) -> List[Deity]:
    """Every god a people holds."""
    if civ_id is None:
        return []
    return [g for g in getattr(world, "gods", ()) if civ_id in g.civ_ids]


def god(world, deity_id: Optional[int]) -> Optional[Deity]:
    """One god by id."""
    if deity_id is None:
        return None
    for g in getattr(world, "gods", ()):
        if g.id == deity_id:
            return g
    return None


def _worshipper_key(worshipper) -> int:
    """A stable number for somebody, for choosing their god.

    Their creature id in play, their historical id otherwise. Both are stable
    across a save, which is the whole reason this is derived rather than
    stored: nothing has to remember it and nothing can lose it.
    """
    for attr in ("hf_id", "id"):
        value = getattr(worshipper, attr, None)
        if isinstance(value, int):
            return value
    return 0


def deity_of(world, worshipper) -> Optional[Deity]:
    """Who this person prays to.

    Their own trade first, when their people keep a god of it -- a smith looks
    to the forge and a soldier to the god of war -- and otherwise one of their
    people's gods, the same one every time.
    """
    civ_id = getattr(worshipper, "civ_id", None)
    pantheon = gods_of(world, civ_id)
    if not pantheon:
        # A fortress expedition carries no civ id -- `Fortress.civ_id` is
        # optional and embark never sets one -- so without this nobody in
        # fortress mode has a god, which is the one place the temple was
        # built for. Fall back to their own people's gods.
        race = str(getattr(worshipper, "def_id", "")
                   or getattr(worshipper, "race", "") or "")
        for civ in world.civs:
            if civ.race == race:
                pantheon = gods_of(world, civ.id)
                if pantheon:
                    break
    if not pantheon:
        return None
    want = SPHERE_FOR_PROFESSION.get(
        str(getattr(worshipper, "profession", "") or ""))
    if want:
        for g in pantheon:
            if want in g.spheres:
                return g
    return pantheon[_worshipper_key(worshipper) % len(pantheon)]


def prayer_line(world, worshipper) -> str:
    """What somebody says they were doing in the temple."""
    g = deity_of(world, worshipper)
    if g is None:
        return "You sit a while in the quiet."
    return "You give thanks to %s, god of %s." % (g.display_name,
                                                  g.sphere_text())
