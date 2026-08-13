"""Performing a form: the roll, who hears it, and what hearing it does.

:mod:`ascii_warriors.world.artforms` makes the forms and never touches them
again. This is where somebody stands up in a tavern and does one.

Three things happen at once and they are the reason the module exists:

* **The performer is judged.** Quality is a roll against the skill the form
  wants, and the skill table has had `music`, `dancing` and `poetry` in it
  since the beginning with nothing to spend them on. A musician without the
  instrument the form calls for is playing it wrong, and it shows.
* **The audience feels something.** A good performance is worth real stress
  relief to everybody in the room, which is the first thing a tavern has ever
  done for a fortress besides be a place people stand in. A bad one is worth
  the opposite, because a tavern where anybody may perform is a tavern where
  somebody will be terrible.
* **The form travels.** A listener who hears something good has a chance of
  learning it, and a form is about real history, so hearing it can teach the
  listener the event the same way v3.7's books do. That is how a dwarven song
  ends up being sung in a human town, and how you find out what happened at a
  battle you were nowhere near.

Both game modes call the same two functions. A fortress performance and a
tavern performance three hundred miles away differ only in who the audience
is.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..world import artforms

#: Quality bands, worst to best. Deliberately the same shape as an
#: engraving's, because a fortress that grades its walls should grade its
#: songs the same way.
QUALITY_NAMES: Tuple[str, ...] = (
    "halting", "plain", "competent", "fine", "moving", "masterful",
    "legendary",
)

#: How each band lands on somebody listening, as a stress delta. Negative is
#: good. A bad performance costing a little is what makes a tavern full of
#: untrained dwarves an actual gamble rather than free happiness.
AUDIENCE_STRESS: Tuple[int, ...] = (3, 1, -2, -5, -9, -14, -20)

#: The window a performance can move somebody's stress inside. Outside it, a
#: song is still a song and the thought is still recorded, but it stops
#: moving the number.
#:
#: Without this the whole mood system collapses into the tavern. Measured over
#: three hundred performances: a fortress with one good musician sat pinned at
#: the -150 floor for ever -- nothing else that happened to it could matter --
#: and a fortress with only bad ones climbed to +198, which is a tantrum
#: spiral caused entirely by amateur poetry. Music is worth a lot and it is
#: not worth everything, in either direction.
RELIEF_FLOOR = -45
ANNOYANCE_CEILING = 45

#: What the performer gets out of it, per band, as experience in the form's
#: own skill. Performing badly still teaches you something.
PERFORM_EXP: Tuple[int, ...] = (20, 28, 38, 52, 70, 92, 120)

#: Odds a listener picks the form up, per band. Nobody learns a song off
#: somebody butchering it.
LEARN_ODDS: Tuple[float, ...] = (0.0, 0.0, 0.05, 0.12, 0.22, 0.35, 0.5)

#: The band from which the world remembers that it happened.
LEGENDARY_AT = 6

#: And how many people have to have been there. A legendary performance to
#: two listeners is a good night, not a thing the world writes down.
LEGENDARY_AUDIENCE = 4

#: And even then, mostly it is not written down. A fortress with a good
#: bard in it produced two hundred history events over fifty measured days
#: without this, which is not a history, it is a diary.
REMEMBER_ODDS = 0.04

#: What the right instrument in your hands is worth, and what having none at
#: all costs, in raw skill points before the roll.
INSTRUMENT_BONUS = 8
WRONG_INSTRUMENT = 3
NO_INSTRUMENT = -14

#: Knowing the form, rather than sight-reading somebody else's culture.
KNOWN_BONUS = 10

#: Performing your own people's work, where the audience is that people.
NATIVE_BONUS = 4

#: What each point of the performing skill is worth.
PER_LEVEL = 4.0

#: How much luck there is in one performance. Wide enough that a competent
#: performer has good nights and bad ones, narrow enough that skill decides.
SPREAD = 7.0

#: The score each band starts at, worst to best. Written as thresholds rather
#: than as an offset and a divisor because the first cut did it the other way
#: and quietly handed an untrained dwarf who happened to know the song a
#: `moving` performance -- the same mistake stealth made in v3.6 by centring
#: its curve on zero. The numbers below read directly: somebody who has never
#: performed knows one form and scores 6, which is `halting`; a skill of 5
#: with the right instrument scores 34, which is `fine`; and `legendary`
#: wants a skill in the high teens and an audience of its own people.
THRESHOLDS: Tuple[float, ...] = (-999.0, 12.0, 24.0, 34.0, 46.0, 62.0, 82.0)

#: How tiring it is to perform, in fatigue points.
FATIGUE = {"music": 6, "poetry": 4, "dance": 18}

#: Turns a performance takes in adventure mode.
PERFORM_TURNS = 60


class Result:
    """What one performance came to."""

    __slots__ = ("form", "performer", "band", "audience", "learners",
                 "revealed", "coins")

    def __init__(self, form, performer, band: int) -> None:
        self.form = form
        self.performer = performer
        self.band = band
        #: Everybody who heard it.
        self.audience: List[Any] = []
        #: Everybody who took the form away with them.
        self.learners: List[Any] = []
        #: Lines of history the audience learned from it.
        self.revealed: List[str] = []
        #: Coins thrown, in adventure mode.
        self.coins = 0

    @property
    def name(self) -> str:
        """The band as a word."""
        return QUALITY_NAMES[max(0, min(len(QUALITY_NAMES) - 1, self.band))]

    @property
    def good(self) -> bool:
        """Whether this was worth hearing."""
        return self.band >= 3

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Result(%s, %s, %d heard)" % (
            getattr(self.form, "name", "?"), self.name, len(self.audience))


# --------------------------------------------------------------------------- #
# Knowing forms
# --------------------------------------------------------------------------- #


def known(creature) -> List[int]:
    """The ids of forms this creature can perform, creating the list."""
    got = getattr(creature, "forms", None)
    if got is None:
        got = creature.forms = []
    return got


def knows(creature, form) -> bool:
    """Whether this creature knows a particular form."""
    fid = form if isinstance(form, int) else form.id
    return fid in (getattr(creature, "forms", None) or ())


def learn(creature, form) -> bool:
    """Teach a creature a form. False if it already knew it."""
    fid = form if isinstance(form, int) else form.id
    got = known(creature)
    if fid in got:
        return False
    got.append(fid)
    return True


def repertoire(world, creature) -> List[Any]:
    """Every form this creature knows, as forms rather than ids."""
    out = []
    for fid in (getattr(creature, "forms", None) or ()):
        form = artforms.by_id(world, fid)
        if form is not None:
            out.append(form)
    return out


def teach_civ(world, rng, creature, civ_id: Optional[int], n: int = 0) -> None:
    """Give somebody the forms they grew up with.

    Everybody knows some of their own people's work. This is what makes a
    fortress able to perform at all on the day it embarks, and what makes an
    elf in a human tavern worth listening to.
    """
    pool = artforms.of_civ(world, civ_id)
    if not pool:
        pool = artforms.forms(world)
    if not pool:
        return
    want = n or rng.randint(1, min(4, len(pool)))
    for form in rng.pick_n(pool, min(want, len(pool))):
        learn(creature, form)


# --------------------------------------------------------------------------- #
# Doing one
# --------------------------------------------------------------------------- #


def instrument_for(performer, form,
                   available: Sequence[Any] = ()) -> Tuple[Optional[Any], int]:
    """The instrument to hand for this form, and what it is worth.

    Carried first, then whatever is lying in the room. A fortress dwarf never
    carries a lute around -- it is furniture, kept where the music happens --
    so without the second half a fortress could craft every instrument in the
    game and its musicians would still be playing nothing. That was true of
    the first cut of this, and the measured result was a tavern that performed
    identically with and without a single instrument in it.

    A form that calls for a drum played on a harp is a real performance of the
    wrong thing, so it is worth something, but not what the drum was worth.
    """
    if form.kind != "music":
        return (None, 0)
    pool = []
    inv = getattr(performer, "inventory", None)
    if inv is not None:
        pool.extend(inv.find(lambda i: i.defn.has("INSTRUMENT")))
    pool.extend(i for i in available if i.defn.has("INSTRUMENT"))
    if not pool:
        return (None, NO_INSTRUMENT)
    for item in pool:
        if item.def_id == form.instrument:
            return (item, INSTRUMENT_BONUS)
    return (pool[0], WRONG_INSTRUMENT)


def score(world, performer, form, *, audience: Sequence[Any] = (),
          available: Sequence[Any] = ()) -> float:
    """The raw number a performance rolls around, before the dice.

    Split out from :func:`band` so a test can read the curve without a
    thousand rolls, and so the look panel could show it if it ever wants to.
    """
    level = max(0, performer.skills.level(form.skill))
    value = level * PER_LEVEL
    if knows(performer, form):
        value += KNOWN_BONUS
    _item, bonus = instrument_for(performer, form, available)
    value += bonus
    if audience and form.civ_id is not None:
        same = sum(1 for c in audience if _civ_of(world, c) == form.civ_id)
        if same * 2 >= len(audience):
            value += NATIVE_BONUS
    return value


def band(world, rng, performer, form, *, audience: Sequence[Any] = (),
         available: Sequence[Any] = ()) -> int:
    """Roll a performance and return its quality band."""
    value = score(world, performer, form, audience=audience,
                  available=available) + rng.gauss(0.0, SPREAD)
    got = 0
    for i, floor in enumerate(THRESHOLDS):
        if value >= floor:
            got = i
    return got


def perform(where, rng, performer, form, audience: Sequence[Any],
            available: Sequence[Any] = (), mood: float = 1.0) -> Result:
    """Perform a form to whoever is there. Applies everything it does.

    *where* may be a Game, a Fortress or a World: the only thing wanted from
    it is the world, because a form is a thing the world owns.

    *mood* scales what the audience feels -- a room built for listening in is
    worth more than a corridor. It is a parameter rather than something the
    caller applies afterwards because every stress change has to go through
    :func:`felt` to stay inside the window; the first cut let the fortress top
    the number up itself and the window silently did nothing, which is how a
    tavern of amateurs still drove a fortress to +198 stress.
    """
    world = _world_of(where)
    listeners = [c for c in audience if c is not performer and _can_hear(c)]
    result = Result(form, performer, band(world, rng, performer, form,
                                          audience=listeners,
                                          available=available))
    result.audience = listeners

    performer.add_exp(form.skill, PERFORM_EXP[result.band])
    performer.add_exp("concentration", PERFORM_EXP[result.band] // 5)
    needs = getattr(performer, "needs", None)
    if needs is not None:
        needs.exert(FATIGUE.get(form.kind, 6))
        # Performing well is its own reward, and badly its own punishment --
        # through the same window as everybody else's, because the performer
        # is in the room too and this is the third path that tried to move
        # stress without asking whether it was allowed to.
        needs.add_thought("performed %s" % result.name,
                          felt(needs.stress, result.band, mood * 0.5))

    text = "heard %s %s of %s" % (result.name,
                                  artforms.WORK_NOUN.get(form.kind, "piece"),
                                  form.name)
    for listener in listeners:
        lneeds = getattr(listener, "needs", None)
        if lneeds is not None:
            lneeds.add_thought(text,
                               felt(lneeds.stress, result.band, mood))
        if not knows(listener, form) and rng.chance(LEARN_ODDS[result.band]):
            learn(listener, form)
            result.learners.append(listener)

    if result.good:
        result.revealed = reveal(world, form)
    if (result.band >= LEGENDARY_AT and len(listeners) >= LEGENDARY_AUDIENCE
            and rng.chance(REMEMBER_ODDS)):
        remember(world, performer, form, result)
    return result


def felt(stress: int, band: int, mood: float = 1.0) -> int:
    """What a performance of this band actually does to somebody at *stress*.

    Clamped into the window above, so a song can carry you to contentment but
    not past it, and a bad one can annoy you without ever being the reason a
    fortress falls apart.
    """
    delta = int(round(
        AUDIENCE_STRESS[max(0, min(len(AUDIENCE_STRESS) - 1, band))] * mood))
    if delta < 0:
        return min(0, max(delta, RELIEF_FLOOR - stress))
    if delta > 0:
        return max(0, min(delta, ANNOYANCE_CEILING - stress))
    return 0


def reveal(where, form) -> List[str]:
    """Open the history a form is about, and return what was new.

    The same trick as reading a book, and deliberately so: the world keeps a
    history that nothing can reach without walking to it, and a song about the
    battle is one of the two ways it travels.
    """
    world = _world_of(where)
    if form.event_id is None:
        return []
    seen = getattr(world, "known_events", None)
    if seen is None:
        seen = world.known_events = set()
    if form.event_id in seen:
        return []
    for ev in getattr(world, "events", ()):
        if ev.id == form.event_id:
            seen.add(ev.id)
            return ["%d: %s" % (ev.year, ev.text)]
    return []


def remember(where, performer, form, result: Result) -> None:
    """Write a legendary performance into the world's history.

    The point of a world that keeps a history is that things you do go into
    it. A performance nobody could ever read about afterwards is a number.
    """
    from ..world import history

    world = _world_of(where)
    if not hasattr(world, "events"):
        return
    history.record(
        world, int(getattr(world, "year", 0) or 0), "performance",
        "%s gave a legendary performance of %s before %d listeners."
        % (performer.name, form.name, len(result.audience)),
        civs=[form.civ_id] if form.civ_id is not None else (),
    )


def describe(result: Result) -> List[str]:
    """The performance as lines for a log or a message pane."""
    form = result.form
    verb = artforms.VERB.get(form.kind, "performs")
    lines = ["%s %s %s. It is %s."
             % (result.performer.name, verb, form.name, result.name)]
    if result.revealed:
        lines.append("You learn what it is about:")
        lines.extend("  " + t for t in result.revealed)
    for who in result.learners:
        lines.append("%s has learned %s." % (who.name, form.name))
    return lines


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _world_of(thing):
    """The World, given a World, a Game or a Fortress."""
    return getattr(thing, "world", None) or thing


def _can_hear(creature) -> bool:
    """Whether somebody is in a state to be an audience."""
    if not getattr(creature, "alive", True):
        return False
    return bool(getattr(creature.defn, "intelligent", True))


def _civ_of(world, creature) -> Optional[int]:
    """Which civilization a creature belongs to, by race, as a fallback.

    Creatures do not carry a civ id, so a race match against the civilizations
    that exist is the honest approximation: a dwarf in the audience counts as
    one of the people who made a dwarven song.
    """
    cid = getattr(creature, "civ_id", None)
    if cid is not None:
        return cid
    race = getattr(creature, "def_id", "")
    for civ in getattr(world, "civs", ()):
        if civ.race == race:
            return civ.id
    return None
