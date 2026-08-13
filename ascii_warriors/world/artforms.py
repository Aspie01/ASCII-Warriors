"""Musical, poetic and dance forms: what a civilization made that is not a wall.

There have been three artistic skills since the skill table was written --
`music`, `dancing`, `poetry` -- and until now not one line of code read any of
them. `music` and `dancing` did not appear anywhere in the codebase outside the
table that defines them. There has been a `lute` in the item data with an
INSTRUMENT flag and a value of 300, and nothing has ever asked whether an item
was an instrument. Every town generates a tavern and the fortress can build
one, and the only thing that ever happened in either was that people stood
near each other.

A form here is a real cultural object with a real owner. The Bronze Hills
invented it in a particular year, it has a name in their own language, it has
rules -- what it is played on, how fast, what it is for -- and very often it is
*about* something that actually happened. That last part is what makes
performing it worth anything to a listener: hearing the song about the battle
tells you about the battle, the same way v3.7's books do, except that a song
walks to you.

Nothing in this module simulates. Forms are generated once at worldgen and
read forever after; :mod:`ascii_warriors.game.performance` is where performing
one does something.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..data import names as name_data
from ..engine.rng import RNG

#: The three kinds of form, and the skill each is performed with.
KINDS: Tuple[str, ...] = ("music", "poetry", "dance")

#: Which skill performs which kind. `dance` and `dancing` differ because the
#: skill table already named the skill and the kind reads better short.
SKILL_FOR: Dict[str, str] = {
    "music": "music", "poetry": "poetry", "dance": "dancing",
}

#: What each kind is called when it is one particular work.
WORK_NOUN: Dict[str, str] = {
    "music": "song", "poetry": "poem", "dance": "dance",
}

#: What performing it is called.
VERB: Dict[str, str] = {
    "music": "plays", "poetry": "recites", "dance": "dances",
}

#: Instruments a musical form can call for. These are item def ids, so a form
#: that wants a drum wants the drum that is actually in the item data.
INSTRUMENTS: Tuple[str, ...] = ("lute", "drum", "flute", "horn", "harp")

#: How a form of each kind is put together. Picked once and then true forever,
#: which is what separates a form from a mood.
STRUCTURE: Dict[str, Tuple[str, ...]] = {
    "music": (
        "a slow melody over a held drone",
        "three voices that answer each other",
        "a single line repeated with a change each time",
        "a fast figure that doubles in speed at the end",
        "a call from one player and a reply from the rest",
        "long silences between short phrases",
    ),
    "poetry": (
        "rhymed couplets",
        "unrhymed lines of even length",
        "a fixed refrain returned to after every verse",
        "a single unbroken sentence",
        "paired lines where the second reverses the first",
        "a list, ended by one line that is not a list",
    ),
    "dance": (
        "a ring that turns against itself",
        "two lines that pass through each other",
        "pairs that separate and find each other again",
        "a single dancer circled by the rest",
        "stamping in a line, arms linked",
        "a slow procession that breaks into a run",
    ),
}

#: What a form is for. A civilization's forms cluster on its own concerns, but
#: not so tightly that every dwarf song is about mining.
PURPOSE: Tuple[Tuple[str, str], ...] = (
    ("mourning", "the dead"),
    ("war", "battle"),
    ("labour", "work"),
    ("celebration", "victory"),
    ("courtship", "love"),
    ("worship", "the gods"),
    ("history", "the past"),
    ("drink", "ale"),
)

#: How the audience is meant to feel. Read out loud in the description, and
#: read again by the performance code, which pays a mourning song less for
#: cheering somebody up and more for being the right thing at a funeral.
MOOD: Dict[str, str] = {
    "mourning": "grave", "war": "fierce", "labour": "steady",
    "celebration": "joyful", "courtship": "tender", "worship": "solemn",
    "history": "measured", "drink": "raucous",
}

#: How many forms a civilization invents. A people with three songs, two poems
#: and two dances has a culture you can hear the edges of; twenty would be
#: noise in the legends screen.
FORMS_PER_CIV = (2, 3)

#: The odds that a form is about a particular thing that happened rather than
#: about its subject in general. Most art is not documentary.
ABOUT_ODDS = 0.45


class ArtForm:
    """One musical, poetic or dance form, invented by somebody, about something."""

    __slots__ = ("id", "kind", "name", "native_name", "civ_id", "year",
                 "structure", "purpose", "instrument", "figure_id",
                 "event_id", "author_hf")

    def __init__(self, fid: int = 0, kind: str = "music", name: str = "",
                 native_name: str = "") -> None:
        self.id = fid
        self.kind = kind
        self.name = name
        self.native_name = native_name
        self.civ_id: Optional[int] = None
        self.year = 0
        self.structure = ""
        self.purpose = ""
        #: Def id of the instrument a musical form wants, if it wants one.
        self.instrument: Optional[str] = None
        #: What it is about, when it is about anything in particular.
        self.figure_id: Optional[int] = None
        self.event_id: Optional[int] = None
        #: Who invented it, when that is somebody the world remembers.
        self.author_hf: Optional[int] = None

    @property
    def full_name(self) -> str:
        """Translated name with the native form, as civilizations are shown."""
        if self.native_name and self.native_name != self.name:
            return "%s (%s)" % (self.name, self.native_name)
        return self.name

    @property
    def skill(self) -> str:
        """The skill this form is performed with."""
        return SKILL_FOR.get(self.kind, "music")

    @property
    def mood(self) -> str:
        """One word for how it is meant to land."""
        return MOOD.get(self.purpose, "measured")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the form."""
        return {
            "id": self.id, "kind": self.kind, "name": self.name,
            "native": self.native_name, "civ": self.civ_id, "year": self.year,
            "structure": self.structure, "purpose": self.purpose,
            "instrument": self.instrument, "figure": self.figure_id,
            "event": self.event_id, "author": self.author_hf,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ArtForm":
        """Rebuild from :meth:`to_dict`."""
        f = cls(int(d.get("id", 0)), str(d.get("kind", "music")),
                str(d.get("name", "")), str(d.get("native", "")))
        f.civ_id = d.get("civ")
        f.year = int(d.get("year", 0))
        f.structure = str(d.get("structure", ""))
        f.purpose = str(d.get("purpose", ""))
        f.instrument = d.get("instrument")
        f.figure_id = d.get("figure")
        f.event_id = d.get("event")
        f.author_hf = d.get("author")
        return f

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ArtForm(%r, %s)" % (self.name, self.kind)


# --------------------------------------------------------------------------- #
# Inventing them
# --------------------------------------------------------------------------- #


def _next_id(world) -> int:
    """The next free form id, creating the counter on an older world."""
    n = getattr(world, "_next_form", None)
    if not n:
        n = max([f.id for f in forms(world)] or [0]) + 1
    world._next_form = n + 1
    return n


def forms(world) -> List[ArtForm]:
    """Every form in the world, on a world that predates them too."""
    got = getattr(world, "forms", None)
    if got is None:
        got = world.forms = []
    return got


def by_id(world, fid: Optional[int]) -> Optional[ArtForm]:
    """One form by id."""
    if fid is None:
        return None
    for f in forms(world):
        if f.id == fid:
            return f
    return None


def of_civ(world, civ_id: Optional[int], kind: str = "") -> List[ArtForm]:
    """Everything a particular people made."""
    return [f for f in forms(world)
            if f.civ_id == civ_id and (not kind or f.kind == kind)]


def invent(world, rng: RNG, civ, kind: str = "", year: int = 0) -> ArtForm:
    """Make one form, owned by *civ*, and file it in the world.

    A form belongs to a people. That is the whole reason the fortress cares
    that an elf is performing in it, and the reason a song can travel.
    """
    kind = kind or rng.choice(KINDS)
    race = getattr(civ, "race", "human")
    native = name_data._native_word(rng, race, rng.randint(2, 3))
    form = ArtForm(_next_id(world), kind, _name_for(rng, kind), native)
    form.civ_id = getattr(civ, "id", None)
    form.year = year or _founding_year(world, civ)
    form.structure = rng.choice(STRUCTURE[kind])
    form.purpose = rng.choice(PURPOSE)[0]
    if kind == "music":
        form.instrument = rng.choice(INSTRUMENTS)
    _bind_history(world, rng, form, civ)
    # Nobody wrote the song about the battle before the battle. Binding
    # happens after the year is picked because the year is only a guess until
    # there is an event to date it against.
    ev = _event(world, form.event_id)
    if ev is not None and ev.year > form.year:
        form.year = ev.year
    forms(world).append(form)
    return form


def _founding_year(world, civ) -> int:
    """A year inside this civilization's lifetime to have invented it in."""
    start = int(getattr(civ, "year_founded", 0) or 0)
    end = int(getattr(world, "year", start) or start)
    if end <= start:
        return start
    return start + (end - start) // 2


def _name_for(rng: RNG, kind: str) -> str:
    """A translated title in the shape a people would give one."""
    forms_by_kind = {
        "music": ("The {adj} {noun}", "{noun} of {noun2}", "The {verb} {noun}",
                  "{adj} {noun2}s"),
        "poetry": ("The {noun} of the {noun2}", "On the {adj} {noun}",
                   "The {verb} {noun}", "{adj} {noun}"),
        "dance": ("The {noun} Dance", "The {adj} {noun}", "{noun} and {noun2}",
                  "The {verb} {noun}"),
    }
    pattern = rng.choice(forms_by_kind.get(kind, forms_by_kind["music"]))
    return name_data._titleize(name_data._expand(rng, pattern))


def _bind_history(world, rng: RNG, form: ArtForm, civ) -> None:
    """Point the form at a real event or a real person, most of the time.

    A song about the battle at a place you can walk to is worth hearing. A
    song about nothing is a prop, so most forms are about something and the
    rest are about their purpose in general, which is honest.
    """
    events = getattr(world, "events", None) or []
    if not events or not rng.chance(ABOUT_ODDS):
        return
    want = {"mourning": ("death", "battle", "site_destroyed"),
            "war": ("battle", "war_declared", "site_conquered"),
            "celebration": ("beast_slain", "peace", "hero_rose"),
            "history": ("founded_civ", "founded_site", "became_leader"),
            "worship": ("artifact_created", "curse", "tower_built"),
            }.get(form.purpose, ())
    cid = getattr(civ, "id", None)
    pool = [e for e in events if (not want or e.kind in want)]
    mine = [e for e in pool if cid is not None and cid in e.civs]
    chosen = rng.choice(mine or pool) if (mine or pool) else None
    if chosen is None:
        return
    form.event_id = chosen.id
    if chosen.figures:
        form.figure_id = chosen.figures[0]


def populate(world, rng: RNG) -> None:
    """Give every civilization its forms. Called once, after history is run.

    After history rather than before, because a form that is about the war
    needs the war to have happened first.
    """
    if forms(world):
        return
    for civ in world.civs:
        sub = rng.sub("forms%d" % getattr(civ, "id", 0))
        for kind in KINDS:
            for _ in range(sub.randint(*FORMS_PER_CIV)):
                invent(world, sub, civ, kind=kind)


# --------------------------------------------------------------------------- #
# Reading them
# --------------------------------------------------------------------------- #


def describe(world, form: ArtForm) -> List[str]:
    """The form written out, the way the legends screen wants it."""
    civ = _civ(world, form.civ_id)
    lines = ["%s, a form of %s%s." % (
        form.full_name, form.kind,
        " of %s" % civ.name if civ is not None else "")]
    if form.year:
        lines.append("It was first performed in the year %d." % form.year)
    lines.append("It is %s, and it is %s." % (form.structure, _for(form)))
    if form.kind == "music" and form.instrument:
        lines.append("It is played on %s." % _an(_instrument_name(form)))
    ev = _event(world, form.event_id)
    if ev is not None:
        lines.append("It concerns what happened in %d: %s" % (ev.year, ev.text))
    return lines


def _for(form: ArtForm) -> str:
    """What the form is for, in words."""
    for key, words in PURPOSE:
        if key == form.purpose:
            return "meant for %s" % words
    return "meant for whatever it is wanted for"


def _instrument_name(form: ArtForm) -> str:
    """The instrument's proper name out of the item data."""
    from ..data import items as item_data

    defn = item_data.get(form.instrument) if form.instrument else None
    return defn.name if defn is not None else (form.instrument or "nothing")


def _an(word: str) -> str:
    """``a lute``, ``an anvil``."""
    from ..data.descriptors import indefinite_article

    return "%s %s" % (indefinite_article(word), word)


def _civ(world, cid: Optional[int]):
    """A civilization by id."""
    if cid is None:
        return None
    for c in getattr(world, "civs", ()):
        if c.id == cid:
            return c
    return None


def _event(world, eid: Optional[int]):
    """A historical event by id."""
    if eid is None:
        return None
    for e in getattr(world, "events", ()):
        if e.id == eid:
            return e
    return None


def summary(world, form: ArtForm) -> str:
    """One line, for a menu."""
    civ = _civ(world, form.civ_id)
    return "%s - %s%s, %s" % (
        form.name, form.kind,
        " of %s" % civ.name if civ is not None else "", form.mood)
