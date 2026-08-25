"""Temperature: the number the world map has always shown and never meant.

Every world tile has carried a `temperature` since worldgen was written. The
embark screen calls it *freezing* or *scorching*, the travel screen prints it,
and the weather asks it one question -- whether falling water should be snow.
Beyond that a glacier and a desert were the same place to stand in.

Meanwhile every material in the table has a `melting_point` that nothing has
ever read, and the reason it is worth reading is the scale it is written on.
It is Dwarf Fortress's: degrees above absolute zero in Urists, where ice melts
at 10000. Subtract `URIST_OFFSET` and you are in the degrees the world map is
already using. **The bridge between the material table and the climate has
been sitting in both of them the whole time**, which is why `FREEZING` below
is not a constant anybody chose -- it is ice's melting point, converted.

**Temperature is three questions.** What is the air doing (`ambient`: the
world tile, its biome, the season, the hour, the weather, and how far
underground you are). What is nearby doing (`source_heat`: v3.17's fire and
v2.5's magma, because a fire that does not warm you is a light bulb). And what
are you wearing (`insulation`), which is the first thing in this game that has
ever cared, in nine versions of shirts and cloaks and mittens being traded,
stockpiled, tailored and worn for no reason at all.

**Cold takes your fingers; heat takes your water.** That asymmetry is not
decoration. Cold ends in frostbite, through v3.14's `trap_strike` so there is
still one table of things you cannot parry. Heat ends in thirst, which has
been able to kill since v1 and needed nothing new -- the desert just makes the
clock run faster.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..data import materials as mat_data
from ..data.bodies import BODY_PLANS
from . import tiles as tile_data

Cell = Tuple[int, int, int]

# --------------------------------------------------------------------------- #
# The scale
# --------------------------------------------------------------------------- #

#: Degrees between the Urist scale the material table is written on and the one
#: the world map uses. Both were already here; this is the only line joining
#: them.
URIST_OFFSET = 9968


def degrees(urists: float) -> float:
    """A material-table temperature in the units the world map speaks."""
    return float(urists) - URIST_OFFSET


def urists(deg: float) -> float:
    """The reverse, for asking the material table a question."""
    return float(deg) + URIST_OFFSET


def melts_at(material: str) -> Optional[float]:
    """What temperature a named material gives up at, or ``None``."""
    m = mat_data.MATERIALS.get(material)
    return None if m is None else degrees(m.melting_point)


#: Where water stops being water. Not a number anybody picked -- ice's melting
#: point out of the material table, which is 10000 and therefore 32.
FREEZING: float = melts_at("ice") or 32.0

#: How far past freezing it has to get before ice gives way again. Without a
#: margin a river on the line flickers between states every time the hour
#: turns over.
THAW_MARGIN = 4.0


# --------------------------------------------------------------------------- #
# What the air is doing
# --------------------------------------------------------------------------- #

#: How far down before the surface stops mattering. Below this a fortress is
#: the same temperature in Winter as in Summer, which is most of why anyone
#: lives underground -- so it has to be a depth a fortress actually reaches.
#: A local map gives four to nine levels between a column's surface and the
#: magma sea below it; anything larger puts "stable rock" past the bottom of
#: the map, or right on top of the magma, and the mechanic never happens.
CAVE_DEPTH = 6

#: What the rock settles at: near enough the year's average anywhere temperate.
CAVE_TEMP = 52.0

#: How much of a biome's own bias to believe. See `ambient`.
BIOME_WEIGHT = 0.25

#: What each season is worth. Winter is the one with teeth.
SEASON_SWING: Dict[str, float] = {
    "Spring": 0.0, "Summer": 17.0, "Autumn": -2.0, "Winter": -21.0,
}

#: Peak-to-trough over a day, outdoors. Coldest an hour before dawn, warmest
#: mid-afternoon -- `DAY_PEAK` is the hour the sun has finished its work.
DAY_SWING = 12.0
DAY_PEAK = 15.0

#: What the sky is doing to the air under it.
WEATHER_SHIFT: Dict[str, float] = {
    "clear": 2.0, "cloudy": -2.0, "fog": -4.0, "rain": -7.0,
    "storm": -10.0, "snow": -11.0, "blizzard": -19.0,
}


def ambient(
    base: float,
    *,
    biome=None,
    season: str = "Spring",
    hour: float = 12.0,
    weather: str = "clear",
    depth: int = 0,
    outside: bool = True,
) -> float:
    """The air temperature somewhere, in degrees.

    *base* is the world tile's own figure; *depth* is levels below that
    column's surface. Weather and the hour only reach you under open sky, and
    the rock takes over from both as you go down.
    """
    t = float(base)
    if biome is not None:
        # Dead since the biome table was written: a glacier read as merely
        # cold for its latitude, and a volcano read as ordinary rock. Taken
        # at a fraction, because worldgen picked the biome *from* the tile's
        # temperature -- the whole bias is the same climate counted twice,
        # and it puts a glacier at ninety below.
        t += getattr(biome, "temperature_bias", 0) * BIOME_WEIGHT
    t += SEASON_SWING.get(season, 0.0)
    if outside:
        t += WEATHER_SHIFT.get(weather, 0.0)
        t += 0.5 * DAY_SWING * math.cos(
            (float(hour) - DAY_PEAK) * math.pi / 12.0)
    if depth > 0:
        blend = min(1.0, depth / float(CAVE_DEPTH))
        t = t * (1.0 - blend) + CAVE_TEMP * blend
    return t


# --------------------------------------------------------------------------- #
# What is nearby
# --------------------------------------------------------------------------- #

#: Degrees a burning cell adds at its centre, and how far it carries. A camp
#: fire is the difference between a blizzard you walk out of and one you do
#: not, which is the whole reason v3.17 shipped before this did.
FIRE_HEAT = 130.0

#: Magma, which is why the deep fortress is warm whatever the season.
MAGMA_HEAT = 420.0

#: How far either reaches, in cells.
HEAT_RANGE = 6


def _falloff(d: int) -> float:
    """How much of a source's heat survives *d* cells of air."""
    if d > HEAT_RANGE:
        return 0.0
    return (1.0 - d / float(HEAT_RANGE + 1)) ** 2


def source_heat(cell: Cell, *, fire=None, magma=None) -> float:
    """Degrees the fires and the magma near a cell add to the air.

    Asked once per creature per chill, so it looks *outward from the cell*
    rather than walking the layers. A mature fortress holds ten thousand
    magma cells and six hundred may be alight at once; scanning either of
    them per query is the mistake v3.17 shipped and this is the same mistake
    declined in advance. Falloff only decreases with distance and the answer
    is a maximum, so the first ring with anything in it is the answer.
    """
    blaze = fire.fuel if (fire is not None and fire.anything_burning) else None
    lava = getattr(magma, "depth", None) if magma is not None else None
    if not blaze and not lava:
        return 0.0

    x, y, z = cell
    best = 0.0
    for d in range(HEAT_RANGE + 1):
        # The nearest source is not always the hottest: a candle at one cell
        # loses to a magma sea at three. Stop only once nothing further out
        # could beat what has been found.
        if best >= MAGMA_HEAT * _falloff(d):
            break
        here = 0.0
        for nx, ny in _ring(x, y, d):
            # Only this level. Heat travels through air, not through the
            # floor: what a magma sea does to the rock above it is already
            # said by the `warm_stone` tile, which is there to be read
            # before you dig into it.
            if lava and (nx, ny, z) in lava:
                here = MAGMA_HEAT
                break
            if blaze and (nx, ny, z) in blaze:
                here = max(here, FIRE_HEAT)
        best = max(best, here * _falloff(d))
    return best


def _ring(x: int, y: int, d: int) -> Iterable[Tuple[int, int]]:
    """The cells exactly *d* away, as a square outline."""
    if d == 0:
        yield (x, y)
        return
    for i in range(-d, d + 1):
        yield (x + i, y - d)
        yield (x + i, y + d)
    for j in range(-d + 1, d):
        yield (x - d, y + j)
        yield (x + d, y + j)


# --------------------------------------------------------------------------- #
# What you are wearing
# --------------------------------------------------------------------------- #

#: How well a material keeps the weather out, per unit thickness. Metal is a
#: bad coat and an excellent oven, which is the trade the plate-armoured
#: soldier makes in a Summer siege.
INSULATION: Dict[str, float] = {
    "cloth": 1.0, "leather": 0.85, "bone": 0.35, "wood": 0.5,
    "metal": 0.12, "stone": 0.2, "glass": 0.08, "gem": 0.08, "misc": 0.3,
}


def _coverage_weights() -> Dict[str, float]:
    """How much of a body each part category is, out of everything outside it.

    Straight out of `rel_size` in the body table, which combat has always used
    to decide where a blow lands and nothing has ever used to decide how much
    of somebody a cloak is actually covering.
    """
    totals: Dict[str, float] = {}
    for part in BODY_PLANS.get("humanoid", ()):
        if part.category == "organ" or part.has("INTERNAL"):
            continue
        totals[part.category] = totals.get(part.category, 0.0) + part.rel_size
    whole = sum(totals.values()) or 1.0
    return {k: v / whole for k, v in totals.items()}


#: Part category -> fraction of a body's outside.
COVERAGE: Dict[str, float] = _coverage_weights()

#: What a creature's own hide is worth. `natural_armor` is a scaly hide or a
#: thick pelt depending on the animal, and either keeps some weather off.
HIDE_INSULATION = 0.09


def insulation(creature) -> float:
    """How wrapped up somebody is, 0.0 naked to about 1.0 in wool and furs."""
    total = 0.0
    defn = getattr(creature, "defn", None)
    if defn is not None:
        total += HIDE_INSULATION * getattr(defn, "natural_armor", 0)
    inv = getattr(creature, "inventory", None)
    if inv is not None:
        for item in inv.equipped.values():
            if item is None:
                continue
            adef = getattr(item.defn, "armor", None)
            if adef is None or not adef.coverage:
                continue
            mat = getattr(item, "mat", None)
            per = INSULATION.get(getattr(mat, "category", ""), 0.3)
            area = sum(COVERAGE.get(c, 0.0) for c in adef.coverage)
            total += per * area * min(2.0, adef.thickness / 2.0)
    return max(0.0, min(1.2, total))


# --------------------------------------------------------------------------- #
# What it does to you
# --------------------------------------------------------------------------- #

#: The band a body is happy in, naked and still.
COMFORT_LOW = 46.0
COMFORT_HIGH = 86.0

#: What being fully dressed is worth against the cold, in degrees.
INSULATION_DEGREES = 58.0

#: And what it costs you in the heat, in degrees. Clothes cut both ways.
SWELTER_PENALTY = 16.0

#: How far past the edge is as bad as it gets.
LETHAL_SPAN = 62.0

#: Ticks to go from comfortable to as-bad-as-it-gets, and to come back. Coming
#: in out of the cold is faster than going into it -- shelter is meant to be
#: worth reaching.
ADJUST_TICKS = 1600
RECOVER_TICKS = 650

#: What exposure looks like, worst first: (threshold, cold, heat).
STAGES: Tuple[Tuple[float, str, str], ...] = (
    (0.85, "freezing to death", "collapsing in the heat"),
    (0.60, "numb with cold", "badly overheated"),
    (0.35, "shivering", "sweltering"),
    (0.15, "cold", "hot"),
)

#: Where the damage starts, and its odds per hour at the worst.
HARM_AT = 0.60
FROSTBITE_ODDS = 0.30

#: What the heat does to thirst and hunger, as a multiple of the ordinary
#: clock at full exposure.
SWELTER_THIRST = 2.4
CHILL_HUNGER = 1.6

#: The worst it can slow you.
SLOW_FLOOR = 0.55


def strain(temp: float, ins: float = 0.0) -> float:
    """How hard the air is pushing, -1.0 frozen through 0.0 to +1.0 baked."""
    cold_edge = COMFORT_LOW - INSULATION_DEGREES * ins
    if temp < cold_edge:
        return -min(1.0, (cold_edge - temp) / LETHAL_SPAN)
    hot_edge = COMFORT_HIGH - SWELTER_PENALTY * ins
    if temp > hot_edge:
        return min(1.0, (temp - hot_edge) / LETHAL_SPAN)
    return 0.0


def unaffected(creature) -> bool:
    """Whether temperature is somebody else's problem."""
    defn = getattr(creature, "defn", None)
    if defn is None:
        return True
    return bool(defn.has("FIREIMMUNE") or defn.has("UNDEAD"))


def stage(exposure: float) -> Tuple[int, str]:
    """The worst stage an exposure has reached, and the word for it."""
    mag = abs(exposure)
    for i, (edge, cold, hot) in enumerate(STAGES):
        if mag >= edge:
            return (len(STAGES) - i, cold if exposure < 0 else hot)
    return (0, "")


def describe(creature) -> str:
    """A word for how somebody is coping, or ``""``."""
    return stage(getattr(creature, "exposure", 0.0))[1]


def speed_factor(creature) -> float:
    """What the weather is costing somebody's movement."""
    mag = abs(getattr(creature, "exposure", 0.0))
    if mag < STAGES[2][0]:
        return 1.0
    return max(SLOW_FLOOR, 1.0 - (mag - STAGES[2][0]) * 0.7)


#: Where the cold bites first. `trap_strike` already knows how to aim -- it
#: has taken a `prefer` hint since the body model was written -- so frostbite
#: does not need its own idea of what an extremity is.
FROST_TARGET = "DIGIT"


def tick(creature, temp: float, ticks: int, rng, log=None) -> List[str]:
    """Let the weather work on somebody for *ticks*.

    Returns anything worth telling the player. The exposure is a number that
    moves rather than a threshold that trips, because the interesting decision
    is when to turn back, and a threshold gives you no warning to act on.
    """
    msgs: List[str] = []
    if creature.body.dead or unaffected(creature):
        creature.exposure = 0.0
        return msgs

    want = strain(temp, insulation(creature))
    have = getattr(creature, "exposure", 0.0)
    toward_zero = abs(want) < abs(have) or (want * have) < 0
    rate = ticks / float(RECOVER_TICKS if toward_zero else ADJUST_TICKS)
    if want > have:
        have = min(want, have + rate)
    elif want < have:
        have = max(want, have - rate)
    before = stage(getattr(creature, "exposure", 0.0))[0]
    creature.exposure = have
    now, word = stage(have)

    if now > before and word:
        msgs.append("You are %s." % word if creature.is_player
                    else "%s is %s." % (creature.name, word))
        if now >= 2:
            creature.needs.add_thought("caught out in the weather", 4 * now)

    mag = abs(have)
    # Charged through a fractional carry: a shivering local turn is one
    # tick, its surcharge is 0.29 of a point, and `int()` ate it whole --
    # measured, an adventurer could stand in a -30 winter for eighty combat
    # turns and pay nothing, while a dwarf on the fortress's ten-tick step
    # paid honestly. The carry is transient by design: losing it in a save
    # costs under a point.
    debt = getattr(creature, "_exposure_debt", 0.0)
    if have < 0:
        # Keeping warm is expensive. This is the one cold effect that was
        # already here in v1, kept because it was right.
        debt += ticks * (CHILL_HUNGER - 1.0) * mag
        whole = int(debt)
        debt -= whole
        creature.needs.hunger += whole
        if mag >= HARM_AT:
            odds = FROSTBITE_ODDS * (ticks / 600.0) * (mag - HARM_AT) / 0.4
            if rng.chance(min(0.9, odds)):
                from ..game import combat
                combat.trap_strike(
                    creature, "frostbite", "", rng=rng, log=log,
                    prefer=FROST_TARGET)
    elif have > 0:
        debt += ticks * (SWELTER_THIRST - 1.0) * mag
        whole = int(debt)
        debt -= whole
        creature.needs.thirst += whole
        if mag >= HARM_AT:
            creature.needs.exert(int(ticks * mag / 40.0))
    creature._exposure_debt = debt
    return msgs


def to_value(creature) -> Optional[float]:
    """The exposure, for a save, or ``None`` when there is nothing to keep."""
    v = getattr(creature, "exposure", 0.0)
    return round(v, 4) if v else None


# --------------------------------------------------------------------------- #
# Frost: what the cold does to water
# --------------------------------------------------------------------------- #

#: How often the cold gets to look at the water, and how much of it at a time.
#: Learned from v3.17: the mistake is not the work, it is doing the work every
#: step. Freezing is a thing that happens over a season.
CHECK_TICKS = 300
SAMPLE = 40

#: The tile a frozen surface becomes -- already in the table, already flagged
#: `ICE`, and already read by v3.14 as something you slip on.
ICE_TILE = "ice"


def liquid_freezes_at(lm, cell: Cell) -> Optional[float]:
    """What temperature the liquid on a cell gives up at, or ``None``.

    Straight through the tile's own `material` to the material table's
    `melting_point`. Nothing here knows what water is; it knows how to ask.
    """
    t = tile_data.get(lm.tile(*cell))
    if not t.has("WATER") or t.has("DEEP"):
        # Deep water freezes on top and stays liquid underneath, which is a
        # thing this map has no way to represent, so it is left alone.
        return None
    return melts_at(getattr(t, "material", ""))


class Frost:
    """The cells the cold has taken, and what was under them.

    Freezing remembers the tile it covered and the water it swallowed, so a
    thaw puts both back exactly. A glacier's own ice is terrain and none of
    this layer's business: it did not freeze it and it will not melt it.

    Both modes use it, and they hold their water differently -- the fortress
    in v2.5's fluid layer, the adventure map as terrain -- so *water* is
    optional and the fluid layer is simply another place to look.
    """

    __slots__ = ("frozen", "_next_check", "_pool")

    def __init__(self) -> None:
        #: Cell -> (tile before, water depth swallowed).
        self.frozen: Dict[Cell, Tuple[str, int]] = {}
        self._next_check = 0
        #: Cached surface water cells for a map with no fluid layer. Not
        #: saved: it is rebuilt from the map, which is saved.
        self._pool: Optional[List[Cell]] = None

    # -- asking -------------------------------------------------------------- #

    def is_frozen(self, x: int, y: int, z: int) -> bool:
        """Whether this cell is ice we made."""
        return (x, y, z) in self.frozen

    @property
    def any_ice(self) -> bool:
        """Whether the cold is holding anything."""
        return bool(self.frozen)

    def forget_map(self) -> None:
        """Drop everything, for a map we are leaving."""
        self.frozen.clear()
        self._pool = None
        self._next_check = 0

    # -- changing state ------------------------------------------------------ #

    def freeze(self, lm, cell: Cell, water=None) -> bool:
        """Take one cell. False if there was nothing to take."""
        if cell in self.frozen or not lm.in_bounds(*cell):
            return False
        x, y, z = cell
        depth = 0
        if water is not None and water.at(x, y, z) > 0:
            if water.at(x, y, z + 1) > 0:
                # Only the surface freezes. What is under it stays liquid,
                # which is why you can still drown under a frozen river.
                return False
            depth = water.at(x, y, z)
        elif liquid_freezes_at(lm, cell) is None:
            return False
        self.frozen[cell] = (lm.tile(x, y, z), depth)
        if depth:
            water.set(cell, 0)
        lm.set_tile(x, y, z, ICE_TILE)
        return True

    def thaw(self, lm, cell: Cell, water=None) -> bool:
        """Give one cell back. False if we were not holding it."""
        was = self.frozen.pop(cell, None)
        if was is None:
            return False
        tile, depth = was
        if lm.in_bounds(*cell) and lm.tile(*cell) == ICE_TILE:
            lm.set_tile(cell[0], cell[1], cell[2], tile)
        if depth and water is not None:
            water.add(cell, depth)
        return True

    def _surface_water(self, lm) -> List[Cell]:
        """Every open-air cell of standing water on a map with no fluid layer.

        Scanned once per map: the only thing that changes it is this class,
        and this class knows when it has.
        """
        if self._pool is None:
            found: List[Cell] = []
            for y in range(lm.height):
                for x in range(lm.width):
                    cell = (x, y, lm.surface_z(x, y))
                    if liquid_freezes_at(lm, cell) is not None:
                        found.append(cell)
            self._pool = found
        return self._pool

    def step(self, lm, rng, temp_at, now: int, water=None) -> Tuple[int, int]:
        """Freeze and thaw a sample of the map. Returns ``(froze, thawed)``.

        *temp_at* is a callable giving the temperature at a cell, so this
        works for a Fortress and a Game without knowing what either one is.
        Sampled on a cadence: the mistake v3.17 made was not the work but
        doing it every step, and a river freezes over a season either way.
        """
        if now < self._next_check:
            return (0, 0)
        self._next_check = now + CHECK_TICKS

        thawed = 0
        for cell in list(self.frozen)[:SAMPLE * 2]:
            edge = FREEZING if self.frozen[cell][1] else (
                liquid_freezes_at(lm, cell) or FREEZING)
            if temp_at(cell) > edge + THAW_MARGIN and self.thaw(lm, cell, water):
                thawed += 1
                if self._pool is not None:
                    self._pool.append(cell)

        cells: Sequence[Cell]
        if water is not None and water.depth:
            cells = list(water.depth)
        else:
            cells = self._surface_water(lm)
        froze = 0
        if cells:
            for _ in range(min(SAMPLE, len(cells))):
                cell = cells[rng.randint(0, len(cells) - 1)]
                if cell in self.frozen or not lm.is_outside(*cell):
                    continue
                edge = FREEZING if water is not None else liquid_freezes_at(lm, cell)
                if edge is None or temp_at(cell) > edge:
                    continue
                if self.freeze(lm, cell, water):
                    froze += 1
        if froze and self._pool is not None:
            self._pool = [c for c in self._pool if c not in self.frozen]
        return (froze, thawed)

    # -- serialising --------------------------------------------------------- #

    def to_list(self) -> List[Any]:
        """The whole layer, for a save."""
        return [[c[0], c[1], c[2], t, d] for c, (t, d) in self.frozen.items()]

    @classmethod
    def from_list(cls, raw: Sequence[Any]) -> "Frost":
        """Rebuild from :meth:`to_list`."""
        f = cls()
        for row in raw or ():
            try:
                x, y, z, tile, depth = row
            except (TypeError, ValueError):    # pragma: no cover - defensive
                continue
            f.frozen[(int(x), int(y), int(z))] = (str(tile), int(depth))
        return f

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Frost(%d frozen)" % len(self.frozen)
