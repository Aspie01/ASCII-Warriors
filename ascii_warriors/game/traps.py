"""Traps, and the ground that is trying to drop you.

The tile table has had a `trap` tile with a `TRAP` flag since the tile table
existed, and an `ice` tile with an `ICE` flag that glacier biomes have been
laying down all along. The fortress reads neither -- its traps are buildings
with their own machinery -- and adventure mode read neither either, so a tomb
sealed four hundred years ago to keep people out was a room with a skeleton in
it, and a glacier was a white floor.

**A trap you can see is a puzzle; a trap you cannot is a tax.** Every trap
here starts hidden and every one of them can be found before it goes off, by
looking (`s`, which v3.9 already made the verb for reading the ground) or by
walking past with a good enough Observer. Once found it is drawn, named, and
can be disarmed with `mechanics`, walked around, or -- if you are feeling
confident and it is a snare rather than a pit -- simply triggered from a safe
tile. What a trap must never be is an unavoidable die roll on entering a room.

**They spring what the game already has.** A dart carries v3.11's venom, a
snare lays v3.11's web, a pit drops you a level and hurts you the way falling
already hurts, and an alarm wakes the site -- which is the one that turns a
tomb from a fight into a running fight.

Ice is the other half: `ICE` ground is a roll against agility and `climbing`
every time you cross it, and failing means you go down, lose the turn, and
possibly slide a tile further than you meant to.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

Cell = Tuple[int, int, int]

#: The tile a sprung or discovered trap is drawn as. Already in the table,
#: already a red `^`.
TRAP_TILE = "trap"

#: What each kind of trap does, how hard it is to spot, and what it says.
KINDS: Dict[str, Dict[str, Any]] = {
    "dart": {
        "name": "dart trap", "hide": 12, "disarm": 6,
        "text": "A dart hisses out of the wall.",
        "venom": "scorpion", "damage": (1, 1),
    },
    "pit": {
        "name": "pit", "hide": 8, "disarm": 4,
        "text": "The floor gives way.",
        "fall": True, "damage": (1, 1),
    },
    "collapse": {
        "name": "falling rock", "hide": 14, "disarm": 8,
        "text": "The ceiling comes down on you.",
        "damage": (1, 1),
    },
    "snare": {
        "name": "snare", "hide": 10, "disarm": 5,
        "text": "Strands whip up around your legs.",
        "web": True, "damage": (1, 1),
    },
    "alarm": {
        "name": "alarm", "hide": 16, "disarm": 7,
        "text": "Somewhere below, a bell begins to ring.",
        "alarm": True, "damage": (0, 0),
    },
}

#: How many traps a site of each kind gets. A tomb was sealed to keep people
#: out; a ruin was somebody's home and only fell down afterwards.
PER_SITE: Dict[str, Tuple[int, int]] = {
    "tomb": (3, 6), "ruin": (1, 3), "lair": (0, 2),
}

#: How far an alarm reaches.
ALARM_RANGE = 40

#: What a point of Observer is worth against a trap's concealment, when you
#: are looking for it on purpose.
SEARCH_WEIGHT = 4.0

#: And when you are merely walking past. Much less: noticing a tripwire you
#: were not looking for is luck with a little skill in it.
PASSIVE_WEIGHT = 1.2

#: How close you have to be for either to happen at all.
SEARCH_RANGE = 4
PASSIVE_RANGE = 2

#: How wide the spotting curve is, and where it sits. The first cut divided by
#: 20 with a 0.45 base, which made every observer level worth a fifth of the
#: whole range: an untrained searcher found a pit 1% of the time and a
#: level-5 one found it 95%. That is a cliff, not a skill -- the same mistake
#: v3.6's stealth and v3.8's performance each made once.
SPREAD = 70.0
SEARCH_BASE = 0.25
PASSIVE_BASE = 0.12

#: Slipping on ice: the roll, and what it costs.
ICE_BASE = 0.28
ICE_PER_LEVEL = 0.05
SLIP_FATIGUE = 25


class Trap:
    """One trap, on one cell."""

    __slots__ = ("kind", "found", "sprung", "armed")

    def __init__(self, kind: str = "dart") -> None:
        self.kind = kind
        #: Whether the player knows it is there.
        self.found = False
        #: Whether it has already gone off.
        self.sprung = False
        #: Whether it still would.
        self.armed = True

    @property
    def defn(self) -> Dict[str, Any]:
        """This kind's entry."""
        return KINDS.get(self.kind, KINDS["dart"])

    @property
    def name(self) -> str:
        """What it is called."""
        return str(self.defn["name"])

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the trap."""
        return {"k": self.kind, "f": self.found, "s": self.sprung,
                "a": self.armed}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Trap":
        """Rebuild from :meth:`to_dict`."""
        t = cls(str(d.get("k", "dart")))
        t.found = bool(d.get("f", False))
        t.sprung = bool(d.get("s", False))
        t.armed = bool(d.get("a", True))
        return t

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Trap(%s, %s)" % (self.kind, "found" if self.found else "hidden")


# --------------------------------------------------------------------------- #
# Where they are
# --------------------------------------------------------------------------- #


def layer(game) -> Dict[Cell, Trap]:
    """Every trap on this map, creating the layer."""
    got = getattr(game, "traps", None)
    if got is None:
        got = game.traps = {}
    return got


def at(game, cell: Cell) -> Optional[Trap]:
    """The trap on a cell, if any."""
    return layer(game).get(cell)


def place(game, cell: Cell, kind: str) -> Optional[Trap]:
    """Put a trap on a cell. None if it could not go there."""
    lm = getattr(game, "local", None)
    if lm is None or not lm.walkable(*cell) or cell in layer(game):
        return None
    trap = Trap(kind)
    layer(game)[cell] = trap
    return trap


def populate(game, site, rng) -> int:
    """Seed a site with traps. Returns how many went in.

    Called when a local map is generated rather than at worldgen, because a
    trap belongs to a floor plan and floor plans are made on arrival.
    """
    kind = getattr(site, "kind", "") if site is not None else ""
    lo, hi = PER_SITE.get(kind, (0, 0))
    if hi <= 0:
        return 0
    lm = game.local
    want = rng.randint(lo, hi)
    made = 0
    for _ in range(want * 12):
        if made >= want:
            break
        cell = lm.random_open(rng)
        if place(game, cell, rng.choice(list(KINDS))) is not None:
            made += 1
    return made


# --------------------------------------------------------------------------- #
# Finding them
# --------------------------------------------------------------------------- #


def spot_chance(finder, trap: Trap, *, searching: bool) -> float:
    """How likely this person is to notice this trap."""
    weight = SEARCH_WEIGHT if searching else PASSIVE_WEIGHT
    score = finder.skills.level("observer") * weight
    score += finder.attributes.factor("intuition") * 4.0 - 4.0
    base = SEARCH_BASE if searching else PASSIVE_BASE
    odds = (score - trap.defn["hide"]) / SPREAD + base
    return max(0.0, min(0.95, odds))


def look_around(game, *, searching: bool) -> List[Tuple[Cell, Trap]]:
    """Roll to notice nearby traps. Returns the ones newly found.

    Folded into `search` and into moving, so there is no separate "detect
    traps" verb: looking hard at the ground is what searching already is.
    """
    p = game.player
    reach = SEARCH_RANGE if searching else PASSIVE_RANGE
    found = []
    for cell, trap in list(layer(game).items()):
        if trap.found or trap.sprung or cell[2] != p.z:
            continue
        if max(abs(cell[0] - p.x), abs(cell[1] - p.y)) > reach:
            continue
        if not game.rng.chance(spot_chance(p, trap, searching=searching)):
            continue
        reveal(game, cell, trap)
        found.append((cell, trap))
    return found


def reveal(game, cell: Cell, trap: Trap) -> None:
    """Mark a trap as known and draw it."""
    trap.found = True
    lm = getattr(game, "local", None)
    if lm is not None and lm.walkable(*cell):
        lm.set_tile(cell[0], cell[1], cell[2], TRAP_TILE)


def disarm(game, cell: Cell) -> Tuple[bool, str]:
    """Take a found trap apart with `mechanics`. Failing can set it off."""
    trap = at(game, cell)
    if trap is None or not trap.armed or trap.sprung:
        return (False, "There is nothing to disarm there.")
    if not trap.found:
        return (False, "You do not know of anything there.")
    p = game.player
    level = max(0, p.skills.level("mechanics"))
    p.add_exp("mechanics", 30)
    odds = 0.25 + level * 0.07 - trap.defn["disarm"] * 0.03
    if game.rng.chance(max(0.05, min(0.95, odds))):
        trap.armed = False
        p.add_exp("mechanics", 40)
        return (True, "You take the %s apart." % trap.name)
    if game.rng.chance(0.35):
        spring(game, cell, p)
        return (False, "You set it off.")
    return (False, "You cannot see how it comes apart.")


# --------------------------------------------------------------------------- #
# Setting them off
# --------------------------------------------------------------------------- #


def step_on(game, creature, cell: Cell) -> Optional[Trap]:
    """Something has walked onto a cell. Spring whatever is under it."""
    trap = at(game, cell)
    if trap is None or not trap.armed or trap.sprung:
        return None
    spring(game, cell, creature)
    return trap


def spring(game, cell: Cell, victim) -> None:
    """Set a trap off on whoever is standing there."""
    trap = at(game, cell)
    if trap is None or trap.sprung:
        return
    defn = trap.defn
    trap.sprung = True
    trap.armed = False
    reveal(game, cell, trap)

    said = str(defn["text"])
    if victim.is_player:
        game.log.bad(said)
    elif game.can_see_creature(victim):
        game.log.warn("%s sets off a %s." % (victim.short_name().capitalize(),
                                             trap.name))

    landed = True
    if defn.get("damage", (0, 0))[1]:
        landed = _hurt(game, victim, trap.kind)
    if defn.get("venom") and landed:
        # A dart that failed to get through the armour has not envenomed
        # anybody. Gating on the strike is the difference between armour
        # mattering and armour mattering for half the trap.
        from . import venom

        venom.inject(victim, str(defn["venom"]), game.rng)
    if defn.get("web"):
        from . import webs

        webs.spin(game, victim, (victim.x, victim.y, victim.z))
    if defn.get("fall"):
        _drop(game, victim)
    if defn.get("alarm"):
        _rouse(game, victim)


def _hurt(game, victim, kind: str) -> bool:
    """Do the damage through `combat.trap_strike`.

    The fortress has had a trap-damage path since traps were buildings, and it
    already handles armour, body parts and the wound model. A second one for
    the same idea is how two systems quietly stop agreeing about what a spike
    does. Returns whether anything actually got through.
    """
    from . import combat

    result = combat.trap_strike(victim, kind, "", rng=game.rng,
                                log=game.log if (victim.is_player
                                                 or game.can_see_creature(victim))
                                else None)
    if victim.body.dead and not victim.is_player:
        game.kill_creature(victim)
    return result.damage > 0


def _drop(game, victim) -> None:
    """A pit: down one level, if there is one to go down to."""
    lm = getattr(game, "local", None)
    if lm is None:
        return
    below = (victim.x, victim.y, victim.z - 1)
    if victim.z - 1 < lm.zmin or not lm.walkable(*below):
        return
    game.move_creature(victim, *below)
    if victim.is_player:
        game.log.warn("You land hard, a level below.")


def _rouse(game, victim) -> None:
    """An alarm: everything nearby now knows where you are."""
    woken = 0
    for c in game.creatures.values():
        if c is victim or not c.alive or c.is_player:
            continue
        if victim.distance_to(c) > ALARM_RANGE:
            continue
        if c.ai is None:
            continue
        c.ai.alertness = 40
        c.ai.last_seen = (victim.x, victim.y, victim.z)
        woken += 1
    if woken and victim.is_player:
        game.log.bad("Something is coming.")


# --------------------------------------------------------------------------- #
# Ice
# --------------------------------------------------------------------------- #


def is_ice(game, cell: Cell) -> bool:
    """Whether this ground is ice."""
    from ..world import tiles as tile_data

    lm = getattr(game, "local", None)
    if lm is None or not lm.in_bounds(*cell):
        return False
    return tile_data.get(lm.tile(*cell)).has("ICE")


def footing(creature) -> float:
    """How likely this creature is to keep its feet on ice."""
    skill = max(0, creature.skills.level("climbing"))
    keep = 1.0 - ICE_BASE + skill * ICE_PER_LEVEL
    keep += creature.attributes.factor("agility") * 0.12 - 0.12
    return max(0.05, min(0.99, keep))


def cross(game, creature, cell: Cell) -> bool:
    """Walk onto ice. Returns True if they went down.

    Called from the move, so it costs the turn rather than costing health:
    the danger of ice is not that it hurts, it is that you are on the floor
    for a moment while something else is not.
    """
    if not is_ice(game, cell):
        return False
    if game.rng.chance(footing(creature)):
        creature.add_exp("climbing", 4)
        return False
    creature.needs.exert(SLIP_FATIGUE)
    creature.body.stunned = max(getattr(creature.body, "stunned", 0), 1)
    if creature.is_player:
        game.log.warn("Your feet go out from under you.")
    elif game.can_see_creature(creature):
        game.log.info("%s slips." % creature.short_name().capitalize())
    return True


# --------------------------------------------------------------------------- #
# Serialising them
# --------------------------------------------------------------------------- #


def to_list(game) -> List[Any]:
    """The trap layer, for a save."""
    return [[c[0], c[1], c[2], t.to_dict()] for c, t in layer(game).items()]


def from_list(game, raw: Sequence[Any]) -> None:
    """Rebuild it from :func:`to_list`."""
    out: Dict[Cell, Trap] = {}
    for row in raw or ():
        try:
            x, y, z, d = row
        except (TypeError, ValueError):      # pragma: no cover - defensive
            continue
        out[(int(x), int(y), int(z))] = Trap.from_dict(d)
    game.traps = out
