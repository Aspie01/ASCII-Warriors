"""What happens in the tavern once somebody is standing in it.

v3.4 built the tavern and gave it the one job of putting dwarves next to each
other so they would become friends. That is a real job, but it left the
building itself doing nothing a corridor could not do. This is the other half:
somebody stands up and performs, and the room gets something out of it.

The whole thing runs off :mod:`ascii_warriors.game.performance`, which is the
same code the adventurer performs with. A fortress performance and a tavern
performance in a human town on the far side of the world differ only in who is
in the room.

Two design points worth stating because they are the difference between a
system and free happiness:

* **Anyone in the tavern may perform, not only the good.** The performer is
  drawn from whoever is there, weighted towards skill but never restricted to
  it. A fortress with no musicians in it will hear some genuinely bad music,
  and a bad performance costs the room stress rather than saving it. That is
  what makes a legendary bard worth having migrate in.
* **Instruments are a real constraint.** A musical form asks for an instrument
  by name. The right one is worth `INSTRUMENT_BONUS`; the wrong one is still
  worth `WRONG_INSTRUMENT`, because a drum song on a harp is a real
  performance of the wrong thing; and none at all is `NO_INSTRUMENT`, a
  fourteen-point penalty. This used to read "a dwarf without one is playing it
  wrong for a fourteen-point penalty", which folded two of those three into
  each other -- playing it wrong is a small *bonus*. A fortress that never
  builds a carpenter's shop hears poetry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..data.calendar import TICKS_PER_DAY
from ..game import performance
from ..world import artforms

#: Ticks between one dwarf finishing and another starting. A tavern is not a
#: concert hall: a few performances a day, so the stress relief is a reason to
#: build one rather than a reason to never build anything else.
INTERVAL = TICKS_PER_DAY // 6

#: How many have to be there before anybody bothers. Performing to nobody is
#: practice, and practice is not a tavern.
MIN_AUDIENCE = 2

#: How much a dwarf's skill weights its chance of being the one who performs.
#: Not a filter -- a weight -- because the bad performances are the point.
SKILL_WEIGHT = 1.6

#: What a performance in a tavern is worth over one anywhere else, as a
#: multiplier on what the audience feels. Handed to `performance.perform`
#: rather than applied afterwards, because everything that moves stress has to
#: go through one funnel to stay inside the window that keeps a tavern from
#: becoming the only system in the game that matters.
TAVERN_BONUS = 1.35


def tick(fort, ticks: int) -> Optional[performance.Result]:
    """Maybe hold a performance in the fortress tavern.

    Returns the result when one happened, for the tests and for nothing else:
    everything it does, it does to the dwarves.
    """
    tavern = fort.tavern()
    if tavern is None:
        return None
    nxt = getattr(fort, "_next_performance", 0)
    if fort.ticks < nxt:
        return None
    fort._next_performance = fort.ticks + INTERVAL

    crowd = in_tavern(fort, tavern)
    if len(crowd) < MIN_AUDIENCE:
        return None
    performer = _who(fort, crowd)
    form = _what(fort, performer)
    if form is None:
        return None

    audience = [d for d in crowd if d is not performer]
    result = performance.perform(fort, fort.rng, performer, form, audience,
                                 available=instruments(fort, tavern),
                                 mood=TAVERN_BONUS)
    _announce(fort, result)
    return result


def in_tavern(fort, tavern=None) -> List[Any]:
    """Every dwarf currently in the tavern.

    The whole room rather than the furniture, matching the radius the walk
    towards it uses -- otherwise the audience is three dwarves and the other
    seventeen standing a tile away hear nothing.
    """
    from .dwarf import TAVERN_RADIUS, tavern_spot

    spot = tavern_spot(fort, tavern)
    if spot is None:
        return []
    cx, cy, cz = spot
    return [d for d in fort.dwarves()
            if d.z == cz
            and max(abs(d.x - cx), abs(d.y - cy)) <= TAVERN_RADIUS
            and not d.fort.sleeping]


def instruments(fort, tavern=None) -> List[Any]:
    """Every instrument lying in the tavern.

    Instruments are furniture, not luggage: a dwarf does not carry a harp
    around the fortress, it is kept where the music happens. So the tavern's
    floor is the pool a performer plays from, and hauling a lute into the
    tavern is a real decision with a measurable result.
    """
    from .dwarf import TAVERN_RADIUS, tavern_spot

    spot = tavern_spot(fort, tavern)
    if spot is None:
        return []
    cx, cy, cz = spot
    out = []
    for (x, y, z), pile in fort.items_on_ground.items():
        if z != cz or max(abs(x - cx), abs(y - cy)) > TAVERN_RADIUS:
            continue
        out.extend(i for i in pile if i.defn.has("INSTRUMENT"))
    return out


def _who(fort, crowd: Sequence[Any]):
    """Pick who performs. Skill helps; it does not decide."""
    weights = []
    for d in crowd:
        best = max((d.skills.level(s) for s in ("music", "poetry", "dancing")),
                   default=0)
        weights.append(1.0 + max(0, best) * SKILL_WEIGHT)
    return crowd[fort.rng.pick_index(weights)]


def _what(fort, performer):
    """What this dwarf performs.

    Its own repertoire first, because a dwarf performing the song it grew up
    with is the ordinary case. Failing that, anything the world has, which is
    a dwarf trying something it half remembers hearing.
    """
    world = fort.world
    mine = performance.repertoire(world, performer)
    if mine:
        return fort.rng.choice(mine)
    everything = artforms.forms(world)
    if not everything:
        return None
    return fort.rng.choice(everything)


def _announce(fort, result: performance.Result) -> None:
    """Say something when it was worth saying something about.

    Six performances a day for two hundred days is twelve hundred lines of
    log nobody will read, so the ordinary ones pass in silence and the room
    simply feels better.
    """
    form = result.form
    verb = artforms.VERB.get(form.kind, "performs")
    if result.band >= performance.LEGENDARY_AT:
        fort.log.good("%s %s %s. It will be remembered."
                      % (result.performer.name, verb, form.name))
    elif result.band >= 4:
        fort.log.good("%s %s %s in the tavern. It is %s."
                      % (result.performer.name, verb, form.name, result.name))
    elif result.band == 0:
        fort.log.info("%s %s %s. It is not good."
                      % (result.performer.name, verb, form.name))
    for who in result.learners:
        if fort.rng.chance(0.34):
            fort.log.info("%s has learned %s." % (who.name, form.name))


# --------------------------------------------------------------------------- #
# Setting up
# --------------------------------------------------------------------------- #


def teach_embark(fort) -> None:
    """Give the founding seven the songs they grew up with.

    Called once at embark. Without it the tavern is silent until a migrant
    who happens to know something walks in, which is not how leaving home
    works.
    """
    world = getattr(fort, "world", None)
    if world is None or not artforms.forms(world):
        return
    for dwarf in fort.dwarves():
        teach(fort, dwarf)


def teach(fort, dwarf) -> None:
    """Give one dwarf its people's repertoire."""
    world = getattr(fort, "world", None)
    if world is None:
        return
    performance.teach_civ(world, fort.rng, dwarf, _home_civ(fort))


def _home_civ(fort) -> Optional[int]:
    """The civilization that sent this expedition, or any dwarven one."""
    cid = getattr(fort, "civ_id", None)
    if cid is not None:
        return cid
    for civ in getattr(fort.world, "civs", ()):
        if civ.race == "dwarf":
            return civ.id
    return None


def summary(fort) -> str:
    """One line about what the fortress can perform, for the status screens."""
    world = getattr(fort, "world", None)
    if world is None:
        return "No forms are known here."
    known = set()
    for d in fort.dwarves():
        known.update(getattr(d, "forms", None) or ())
    if not known:
        return "Nobody here knows a song."
    kinds: Dict[str, int] = {}
    for fid in known:
        form = artforms.by_id(world, fid)
        if form is not None:
            kinds[form.kind] = kinds.get(form.kind, 0) + 1
    parts = ["%d %s" % (n, k) for k, n in sorted(kinds.items())]
    return "%d forms known: %s." % (len(known), ", ".join(parts))
