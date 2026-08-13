"""Footprints: what walked here, which way it went, and how long ago.

The hunter class has had `tracker` 4 since character creation was written and
the fortress hunter labor has had `tracker` 3 since labors existed, and no
line of code has ever read either. This is the fourth hole the same audit has
turned up -- which skills does the data hand out that nothing reads? -- after
stealth in v3.6, books in v3.7 and the artistic skills in v3.8.

Tracks are cheap on purpose. Every creature that moves stamps one cell, and
one cell only holds the last thing that crossed it, so the whole layer is a
dict of at most a few hundred entries that ages out on its own. There is no
simulation here and nothing steps it: a track knows when it was made and
answers questions about itself relative to now.

**Reading one is the skill, not finding it.** Anybody can see that something
passed. Which way it went, what it was, how long ago, how many, and whether
it was bleeding are five separate things the tracker skill hands over one at
a time, so the difference between an untrained adventurer and a hunter is not
whether they see the trail but how much of the story it tells them.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

Cell = Tuple[int, int, int]

#: Ground that takes a print. Rock does not, which is why a trail stops at the
#: cave mouth and why the tracker skill is an outdoor skill.
SOFT: Tuple[str, ...] = ("dirt", "grass", "grass_dead", "sand", "mud", "snow",
                         "farm", "ash")

#: Ticks before a track is too old to read at all, by ground. Snow and mud
#: hold a print; sand loses it to the first wind.
FADE: Dict[str, int] = {
    "snow": 43200, "mud": 28800, "dirt": 21600, "farm": 21600,
    "grass": 14400, "grass_dead": 14400, "ash": 14400, "sand": 7200,
}
DEFAULT_FADE = 14400

#: Blood outlasts a footprint and does not care what it fell on.
BLOOD_FADE = 36000

#: The most tracks kept at once. A trail three hundred cells long is longer
#: than anything worth following, and the cap is what stops a long game
#: turning the layer into a memory leak.
MAX_TRACKS = 400

#: How much of the layer is dropped when it overflows: the oldest quarter,
#: rather than one entry per move, so pruning is rare instead of constant.
PRUNE_FRACTION = 4

#: What the tracker skill tells you, by level. Each tier is a thing the trail
#: says, not a better roll on the same thing.
DIRECTION_AT = 1
SPECIES_AT = 4
AGE_AT = 7
COUNT_AT = 10
CONDITION_AT = 13

#: How far a search sweeps for trails.
SEARCH_RADIUS = 6

#: Heading by step, looked up exactly rather than scored. `dx` and `dy` are
#: already signs, so there are only nine cases and a dot product over them
#: only manages to let the diagonals win ties -- which is how due east first
#: came out of this as "north-east".
_COMPASS: Dict[Tuple[int, int], str] = {
    (0, -1): "north", (1, -1): "north-east", (1, 0): "east",
    (1, 1): "south-east", (0, 1): "south", (-1, 1): "south-west",
    (-1, 0): "west", (-1, -1): "north-west",
}


class Track:
    """The last thing to cross one cell."""

    __slots__ = ("def_id", "name", "size", "dx", "dy", "tick", "blood",
                 "count", "player")

    def __init__(self, def_id: str = "", name: str = "", size: int = 0,
                 dx: int = 0, dy: int = 0, tick: int = 0) -> None:
        self.def_id = def_id
        self.name = name
        self.size = size
        #: Which way it was heading when it stood here.
        self.dx = dx
        self.dy = dy
        self.tick = tick
        #: Whether it was losing blood at the time.
        self.blood = False
        #: How many of the same thing have crossed this cell.
        self.count = 1
        #: Whether this is the player's own trail, which matters because
        #: finding your own footprints and thinking you found a wolf is a
        #: worse experience than the system is worth.
        self.player = False

    @property
    def heading(self) -> str:
        """Which way it went, in words."""
        return _COMPASS.get((_sign(self.dx), _sign(self.dy)), "nowhere")

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the track."""
        return {"d": self.def_id, "n": self.name, "s": self.size,
                "dx": self.dx, "dy": self.dy, "t": self.tick,
                "b": self.blood, "c": self.count, "p": self.player}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Track":
        """Rebuild from :meth:`to_dict`."""
        t = cls(str(d.get("d", "")), str(d.get("n", "")), int(d.get("s", 0)),
                int(d.get("dx", 0)), int(d.get("dy", 0)), int(d.get("t", 0)))
        t.blood = bool(d.get("b", False))
        t.count = int(d.get("c", 1))
        t.player = bool(d.get("p", False))
        return t

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Track(%s, %s, %d)" % (self.def_id, self.heading, self.tick)


# --------------------------------------------------------------------------- #
# Leaving them
# --------------------------------------------------------------------------- #


def layer(game) -> Dict[Cell, Track]:
    """The track layer, creating it on a game that predates tracks."""
    got = getattr(game, "tracks", None)
    if got is None:
        got = game.tracks = {}
    return got


def takes_print(game, cell: Cell) -> bool:
    """Whether this ground holds a footprint."""
    if game.local is None or not game.local.in_bounds(*cell):
        return False
    return game.local.tile(*cell) in SOFT


def leave(game, creature, frm: Optional[Cell] = None) -> Optional[Track]:
    """Stamp the cell a creature has just walked onto.

    Called from `Game.move_creature`, which is the one funnel every move in
    adventure mode goes through -- the same reason v2.5 put every tile change
    through `dig_out`. A track recorded anywhere else is a track some other
    kind of movement does not leave.
    """
    cell = (creature.x, creature.y, creature.z)
    if not takes_print(game, cell):
        return None
    dx, dy = 0, 0
    if frm is not None:
        dx, dy = _sign(cell[0] - frm[0]), _sign(cell[1] - frm[1])

    marks = layer(game)
    old = marks.get(cell)
    track = Track(creature.def_id, creature.short_name(),
                  int(getattr(creature.defn, "size", 0) or 0),
                  dx, dy, game.scheduler.ticks)
    track.player = bool(creature.is_player)
    track.blood = _is_bleeding(creature)
    if old is not None and old.def_id == track.def_id:
        # The same kind again: a herd reads as a herd rather than as one deer
        # that keeps coming back.
        track.count = min(99, old.count + 1)
    marks[cell] = track
    if len(marks) > MAX_TRACKS:
        prune(game)
    return track


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def _is_bleeding(creature) -> bool:
    """Whether this creature is losing blood as it walks."""
    body = getattr(creature, "body", None)
    if body is None:
        return False
    try:
        return body.bleeding_rate() > 0.0
    except Exception:                       # pragma: no cover - defensive
        return False


def prune(game) -> int:
    """Drop the oldest tracks. Returns how many went."""
    marks = layer(game)
    if len(marks) <= MAX_TRACKS:
        return 0
    drop = max(1, len(marks) // PRUNE_FRACTION)
    oldest = sorted(marks, key=lambda c: marks[c].tick)[:drop]
    for cell in oldest:
        del marks[cell]
    return len(oldest)


def wipe(game, fraction: float = 1.0) -> int:
    """Rain and snow take the trail. Returns how many tracks went.

    Weather has been in the game since v1 and this is the first thing that
    has ever cared whether it was raining, which is the point: the reason to
    set out after the storm rather than during it.
    """
    marks = layer(game)
    if fraction >= 1.0:
        gone = len(marks)
        marks.clear()
        return gone
    doomed = sorted(marks, key=lambda c: marks[c].tick)
    doomed = doomed[:int(len(doomed) * max(0.0, fraction))]
    for cell in doomed:
        del marks[cell]
    return len(doomed)


# --------------------------------------------------------------------------- #
# Reading them
# --------------------------------------------------------------------------- #


def age_of(game, track: Track) -> int:
    """Ticks since this track was made."""
    return max(0, game.scheduler.ticks - track.tick)


def fade_ticks(game, cell: Cell, track: Track) -> int:
    """How long this particular track lasts on this particular ground."""
    if track.blood:
        return BLOOD_FADE
    if game.local is None:
        return DEFAULT_FADE
    return FADE.get(game.local.tile(*cell), DEFAULT_FADE)


def readable(game, cell: Cell) -> Optional[Track]:
    """The track on a cell, if there is one still fresh enough to read."""
    track = layer(game).get(cell)
    if track is None:
        return None
    if age_of(game, track) > fade_ticks(game, cell, track):
        del layer(game)[cell]
        return None
    return track


def nearby(game, radius: int = SEARCH_RADIUS,
           *, include_own: bool = False) -> List[Tuple[Cell, Track]]:
    """Every readable track within *radius* of the player, nearest first."""
    p = game.player
    out = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            cell = (p.x + dx, p.y + dy, p.z)
            track = readable(game, cell)
            if track is None:
                continue
            if track.player and not include_own:
                continue
            out.append((cell, track))
    out.sort(key=lambda ct: max(abs(ct[0][0] - p.x), abs(ct[0][1] - p.y)))
    return out


def read(game, reader, cell: Cell, track: Track) -> List[str]:
    """What this reader can tell from this track.

    Five separate facts handed over one at a time rather than one roll made
    better, because a hunter and a clerk looking at the same print should
    disagree about what it says, not about whether it is there.
    """
    level = max(0, reader.skills.level("tracker"))
    age = age_of(game, track)
    fade = fade_ticks(game, cell, track)
    faint = age > fade // 2

    what = track.name if level >= SPECIES_AT else "something"
    lead = "%s tracks%s." % (
        ("Faint" if faint else "Fresh") if level >= 1 else "Some",
        "" if level < SPECIES_AT else " of %s" % _an(what))
    if level < DIRECTION_AT:
        return ["Something has passed this way."]
    lines = [lead[0].upper() + lead[1:]]
    lines.append("They head %s." % track.heading)
    if level >= AGE_AT:
        lines.append("Made %s." % _ago(age))
    if level >= COUNT_AT and track.count > 1:
        lines.append("Several passed here -- %d at least." % track.count)
    if level >= CONDITION_AT:
        if track.blood:
            lines.append("There is blood. It is hurt.")
        elif track.size:
            lines.append("A %s one, by the depth." % _bulk(track.size))
    elif track.blood and level >= SPECIES_AT:
        lines.append("There is blood here.")
    return lines


def _an(word: str) -> str:
    """``a wolf``, ``an elk``."""
    from ..data.descriptors import indefinite_article

    return "%s %s" % (indefinite_article(word), word)


def _ago(ticks: int) -> str:
    """How long ago, in words a person would use."""
    from ..data.calendar import TICKS_PER_DAY, TICKS_PER_HOUR

    if ticks < TICKS_PER_HOUR // 2:
        return "moments ago"
    if ticks < TICKS_PER_HOUR * 2:
        return "within the hour"
    if ticks < TICKS_PER_DAY:
        return "about %d hours ago" % max(1, ticks // TICKS_PER_HOUR)
    return "more than a day ago"


def _bulk(size: int) -> str:
    """How big it was, from the print."""
    if size >= 200000:
        return "huge"
    if size >= 60000:
        return "big"
    if size >= 15000:
        return "middling"
    return "small"


def can_track(reader) -> bool:
    """Whether this creature reads tracks at all."""
    return reader.body.can_see()


# --------------------------------------------------------------------------- #
# Serialising them
# --------------------------------------------------------------------------- #


def to_list(game) -> List[Any]:
    """The whole layer, for a save."""
    return [[c[0], c[1], c[2], t.to_dict()] for c, t in layer(game).items()]


def from_list(game, raw: Sequence[Any]) -> None:
    """Rebuild the layer from :func:`to_list`."""
    marks: Dict[Cell, Track] = {}
    for row in raw or ():
        try:
            x, y, z, d = row
        except (TypeError, ValueError):     # pragma: no cover - defensive
            continue
        marks[(int(x), int(y), int(z))] = Track.from_dict(d)
    game.tracks = marks
