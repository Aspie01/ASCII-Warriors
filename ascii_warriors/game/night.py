"""The night: necromancy, curses, and what the moon does to people.

The world already generated necromancers, gave them towers, and stocked those
towers with zombies. It generated vampires and werewolves too. None of it did
anything: the undead stood where the map maker put them, the necromancer was a
tough human in a hat, and a werewolf was a wolf that hit harder.

This is the part that makes them what they are. A necromancer raises the dead
it can see, including the ones you just made, so a tower is not a queue of
zombies to grind through but a fight you lose slowly until you get to the
necromancer. A werebeast's bite is a curse, and the cursed change at the full
moon wherever they happen to be standing -- in an inn, or in your dining hall.
A vampire drinks, quietly, from whoever is asleep and alone, and the sheriff's
book fills up with murders nobody can be tried for.

The three share one idea. Each is a rule about *time and place* rather than a
monster: the corpse on the floor, the phase of the moon, the dwarf who sleeps
in a room of its own.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

Cell = Tuple[int, int, int]

# --------------------------------------------------------------------------- #
# Necromancy
# --------------------------------------------------------------------------- #

#: How far a necromancer's will reaches.
RAISE_RANGE = 7

#: Ticks between raisings. Slow enough that killing the necromancer is the
#: answer and fast enough that ignoring it is not.
RAISE_COOLDOWN = 60

#: A corpse too small to be worth the words.
RAISE_MIN_SIZE = 3000

#: What gets up, by how much of it is left. Anything a butcher has been at,
#: or anything long dead, comes back as bone.
def raised_kind(item) -> str:
    """Whether a corpse rises as a zombie or as a skeleton."""
    if item.def_id == "skull" or item.material == "bone":
        return "skeleton"
    return "zombie" if item.def_id == "corpse" else "skeleton"


def is_necromancer(creature) -> bool:
    """Whether this creature can raise the dead.

    Including whoever has read the slab. The raising machinery was written to
    take any creature and any world, so a player who learns the secret becomes
    a necromancer here and nowhere else needs to know.
    """
    if "necromancy" in (getattr(creature, "secrets", None) or ()):
        return True
    return (creature.profession == "necromancer"
            or creature.def_id == "necromancer"
            or "necromancer" in getattr(creature, "speech", {}))


def raisable(item) -> bool:
    """Whether a thing on the floor could be made to stand up."""
    if item.def_id not in ("corpse", "severed_part"):
        return False
    if item.flags.get("raised"):
        return False
    return int(item.flags.get("size", 0) or 0) >= RAISE_MIN_SIZE


def corpses_near(world, x: int, y: int, z: int, radius: int = RAISE_RANGE):
    """``(item, cell)`` for every corpse within reach, nearest first.

    *world* is anything with ``items_on_ground`` -- a Game or a Fortress. The
    two modes keep their floors in the same shape, so the night layer does not
    need to know which one it is standing in.
    """
    from ..engine import geometry

    out = []
    for cell, pile in world.items_on_ground.items():
        if cell[2] != z:
            continue
        if geometry.chebyshev(x, y, cell[0], cell[1]) > radius:
            continue
        for item in pile:
            if raisable(item):
                out.append((item, cell))
    out.sort(key=lambda pair: geometry.chebyshev(x, y, pair[1][0], pair[1][1]))
    return out


def raise_corpse(world, master, item, cell) -> Optional[Any]:
    """Make one corpse stand up and fight for whoever called it.

    The corpse is consumed. Nothing is raised twice, and nothing rises on a
    square somebody is already standing on, because a zombie wedged inside a
    dwarf is a bug report rather than a horror.
    """
    from .entity import make_creature

    if world.creature_at(*cell) is not None:
        return None
    kind = raised_kind(item)
    risen = make_creature(world.rng, kind, faction=master.faction, level=1)
    risen.x, risen.y, risen.z = cell
    risen.wx, risen.wy = master.wx, master.wy
    risen.name = _risen_name(item, kind)
    risen.raised_by = master.id
    if getattr(master, "hostile_to", None):
        risen.hostile_to = set(master.hostile_to)
    _lift(world, item, cell)
    world.add_creature(risen)
    return risen


def _lift(world, item, cell) -> None:
    """Take an item off the floor in whichever mode we are standing in.

    A Game wants the cell as well; a Fortress goes and finds it. The night
    layer runs in both and would rather not care.
    """
    try:
        world.take_item(item, *cell)
    except TypeError:
        world.take_item(item)


def _risen_name(item, kind: str) -> str:
    """"Urist, risen" reads better than "zombie"."""
    who = str(item.flags.get("name") or "")
    if not who:
        return kind
    # Belt and braces against a name that grows a comma every time round.
    return "%s, risen" % who.split(", risen")[0]


def necromancy_turn(world, creature) -> bool:
    """Spend a necromancer's turn raising something. True if it did.

    Called from both AI loops, before either of them decides to walk anywhere:
    a necromancer with a corpse in front of it does not chase you, it makes
    the corpse chase you.
    """
    if not is_necromancer(creature) or creature.body.dead:
        return False
    now = world.time.ticks
    if now - getattr(creature, "raised_at", 0) < RAISE_COOLDOWN:
        return False
    for item, cell in corpses_near(world, creature.x, creature.y, creature.z):
        risen = raise_corpse(world, creature, item, cell)
        if risen is None:
            continue
        creature.raised_at = now
        world.log.bad("%s raises %s!" % (creature.display_name(), risen.name))
        return True
    return False


# --------------------------------------------------------------------------- #
# Curses
# --------------------------------------------------------------------------- #

#: What a curse turns you into, and how likely a bite is to pass it on.
CURSES: Dict[str, Dict[str, Any]] = {
    "werebeast": {"beast": "werewolf", "odds": 0.30,
                  "carriers": ("werewolf",),
                  "text": "The bite burns. Something has taken hold."},
    "vampire": {"beast": "vampire", "odds": 0.10,
                "carriers": ("vampire",),
                "text": "The world goes thin and red at the edges."},
}

#: Which creature kinds carry which curse, built from the table above.
CARRIERS: Dict[str, str] = {
    kind: name for name, spec in CURSES.items() for kind in spec["carriers"]
}

#: The phase a werebeast cannot hold its shape through. Taken from the
#: calendar's own name for it rather than recomputed here, so the moon the
#: status bar shows you is the moon that turns people.
FULL_MOON = "full moon"


def cursed_with(creature) -> str:
    """The curse on this creature, or ``""``."""
    return getattr(creature, "curse", "")


def afflict(creature, kind: str, log=None, ground=None) -> bool:
    """Lay a curse. False if it was already carrying one.

    *ground* is the fortress or game the curse is being laid in, and is what
    lets the world remember it. `"curse"` has been a declared event kind for
    as long as there have been curses and nothing ever wrote one, so the
    "worship" purpose in `artforms.about` -- which offers a form a choice of
    `artifact_created`, `curse` and `tower_built` to be about -- has never had
    the middle one to pick from.

    The player and figures the world already knows get an entry; a nameless
    bitten guard does not, which is the same rule the rest of history follows.
    The player is in because the player has no `hf_id` until they retire and
    is nonetheless the one person whose story this is.

    The vampire that arrives with the migrants deliberately passes no ground
    and so writes nothing. What makes that one work is that nothing gives it
    away, and a line in the legends screen would give it away.
    """
    if kind not in CURSES or cursed_with(creature):
        return False
    creature.curse = kind
    if log is not None:
        log.bad(CURSES[kind]["text"])
    _remember(ground, creature, kind)
    return True


def _remember(ground, creature, kind: str) -> None:
    """Write a curse into the world's history, if the world knows the victim."""
    world = getattr(ground, "world", None)
    if world is None:
        return
    if getattr(creature, "hf_id", None) is None \
            and not getattr(creature, "is_player", False):
        return
    from ..world import history as history_mod

    time = getattr(ground, "time", None)
    year = int(getattr(time, "year", 0) or getattr(world, "year", 0) or 0)
    hf = getattr(creature, "hf_id", None)
    history_mod.record(
        world, year, "curse",
        "%s was cursed to walk as a %s."
        % (creature.display_name(), CURSES[kind]["beast"]),
        [hf] if hf is not None else (),
    )


def on_bite(attacker, defender, rng, log=None, ground=None) -> bool:
    """A bite from something cursed may pass the curse on.

    Called from the combat resolver when a natural attack lands. The odds are
    per bite, not per fight, so a werewolf that gets one lucky mouthful is a
    problem for the rest of the game and one that is put down quickly is not.
    """
    kind = CARRIERS.get(attacker.def_id) or cursed_with(attacker)
    if not kind or defender.body.dead:
        return False
    if defender.defn.has("UNDEAD") or defender.body.bloodless:
        return False
    if cursed_with(defender) or CARRIERS.get(defender.def_id):
        return False
    if not rng.chance(CURSES[kind]["odds"]):
        return False
    return afflict(defender, kind, log if defender.is_player else None,
                   ground=ground)


def moon_is_full(time) -> bool:
    """Whether the moon is full enough to matter."""
    return time.moon_phase() == FULL_MOON


def should_change(creature, time) -> bool:
    """Whether a cursed creature is in its other shape right now."""
    if cursed_with(creature) != "werebeast":
        return False
    return moon_is_full(time) and time.is_night()


def transform(world, creature) -> bool:
    """Turn a cursed creature into the beast. True if it changed."""
    from ..data import creatures as creature_data

    if getattr(creature, "changed", False):
        return False
    beast = CURSES[cursed_with(creature)]["beast"]
    creature.changed = True
    creature.shape_was = creature.def_id
    creature.faction_was = creature.faction
    creature.def_id = beast
    creature._defn = creature_data.get(beast)
    creature.skills.set_level("biter", max(6, creature.skills.level("biter")))
    if not creature.is_player:
        # It does not know you and it does not care. The player keeps its own
        # side, because a game that takes the character away is not a game.
        creature.faction = "hostile"
    world.log.bad("%s twists and swells -- a %s!"
                  % (creature.display_name(), beast))
    return True


def revert(world, creature) -> bool:
    """Turn it back at dawn. True if it changed back."""
    from ..data import creatures as creature_data

    if not getattr(creature, "changed", False):
        return False
    creature.def_id = getattr(creature, "shape_was", "") or creature.def_id
    creature._defn = creature_data.get(creature.def_id)
    creature.changed = False
    if not creature.is_player:
        creature.faction = getattr(creature, "faction_was", "") or "wild"
    world.log.info("%s is itself again, and remembers none of it."
                   % creature.display_name())
    return True


# --------------------------------------------------------------------------- #
# Vampires
# --------------------------------------------------------------------------- #

#: The share of a body's blood one feeding takes. Three or four nights on the
#: same dwarf kills it, which is slow enough that the fortress notices
#: somebody looking peaky before it finds a corpse.
FEED_SHARE = 0.28


def is_vampire(creature) -> bool:
    """Whether this creature drinks."""
    return (cursed_with(creature) == "vampire"
            or CARRIERS.get(creature.def_id) == "vampire")


def can_feed_on(victim) -> bool:
    """Whether a sleeping body is worth a vampire's night."""
    if victim.body.dead or victim.defn.has("UNDEAD"):
        return False
    return not victim.body.bloodless


def feed(world, vampire, victim) -> bool:
    """Drink. True if the victim died of it.

    The bite itself is quiet. What is loud is the body in the morning, and
    whether anybody was awake to see who was standing over it.
    """
    victim.body.blood = max(0.0, victim.body.blood
                            - victim.body.max_blood * FEED_SHARE)
    victim.needs.add_thought("woke up weak and cold", 12)
    if victim.body.blood <= 0:
        victim.body.dead = True
        victim.body.death_cause = "drained of blood"
        return True
    return False
