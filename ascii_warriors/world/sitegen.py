"""Building settlements, fortresses, caves and towers into a local map."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..data import creatures as creature_data
from ..engine.geometry import Rect, line
from ..engine.rng import RNG
from . import tiles as tile_data

#: A population entry describes one inhabitant for :mod:`game.state` to spawn.
PopSpec = Dict[str, Any]


def _pop(
    def_id: str,
    x: int,
    y: int,
    z: int,
    *,
    faction: str = "town",
    profession: str = "",
    name: str = "",
    hf_id: Optional[int] = None,
    level: int = 0,
    role: str = "",
) -> PopSpec:
    """Build one population entry."""
    return {
        "def_id": def_id, "x": x, "y": y, "z": z, "faction": faction,
        "profession": profession, "name": name, "hf_id": hf_id,
        "level": level, "role": role,
    }


def _flatten(lm, rect: Rect, z: int) -> None:
    """Level the ground inside a rectangle so a building can stand on it."""
    for y in range(rect.y, rect.y2):
        for x in range(rect.x, rect.x2):
            if not (0 <= x < lm.width and 0 <= y < lm.height):
                continue
            sz = lm.surface_z(x, y)
            for zz in range(min(sz, z), max(sz, z) + 1):
                if zz < z:
                    lm.set_tile(x, y, zz, "soil_wall")
                elif zz > z:
                    lm.set_tile(x, y, zz, "air")
            lm.set_tile(x, y, z, "floor_constructed")
            lm.surface[y * lm.width + x] = z


def _building(
    lm, rect: Rect, z: int, rng: RNG, *, door_sides: Sequence[str] = ("south",)
) -> None:
    """Raise a walled building with a door and a roofless interior."""
    _flatten(lm, rect, z)
    for p in rect.border():
        if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
            lm.set_tile(p.x, p.y, z, "wall_constructed")
            if lm.in_bounds(p.x, p.y, z + 1):
                lm.set_tile(p.x, p.y, z + 1, "wall_constructed")
    doors: List[Tuple[int, int]] = []
    for side in door_sides:
        if side == "south":
            doors.append((rect.x + rect.w // 2, rect.y2 - 1))
        elif side == "north":
            doors.append((rect.x + rect.w // 2, rect.y))
        elif side == "west":
            doors.append((rect.x, rect.y + rect.h // 2))
        else:
            doors.append((rect.x2 - 1, rect.y + rect.h // 2))
    for dx, dy in doors:
        if 0 <= dx < lm.width and 0 <= dy < lm.height:
            lm.set_tile(dx, dy, z, "door_closed")
            if lm.in_bounds(dx, dy, z + 1):
                lm.set_tile(dx, dy, z + 1, "air")


def _furnish(lm, rect: Rect, z: int, rng: RNG, kind: str) -> None:
    """Drop furniture inside a finished building."""
    inner = rect.inner(1)
    if inner.w <= 0 or inner.h <= 0:
        return
    cells = list(inner.cells())
    rng.shuffle(cells)
    plan = {
        "house": ["bed", "table", "chair", "cabinet"],
        "tavern": ["table", "chair", "table", "chair", "barrel", "bed", "bed"],
        "temple": ["altar", "statue"],
        "market": ["table", "table", "coffer"],
        "keep": ["table", "chair", "coffer", "statue"],
        "barracks": ["bed", "bed", "bed", "cabinet"],
        "forge": ["table", "coffer"],
        "library": ["table", "chair", "cabinet", "cabinet"],
        "shop": ["table", "coffer", "cabinet"],
    }.get(kind, ["table", "chair"])
    for i, item in enumerate(plan):
        if i >= len(cells):
            break
        x, y = cells[i]
        lm.set_tile(x, y, z, "table" if item == "barrel" else item)


def _road(lm, x0: int, y0: int, x1: int, y1: int, z: int) -> None:
    """Lay a road between two points."""
    for p in line(x0, y0, x1, y1):
        if not (0 <= p.x < lm.width and 0 <= p.y < lm.height):
            continue
        sz = lm.surface_z(p.x, p.y)
        t = tile_data.get(lm.tile(p.x, p.y, sz))
        if t.has("WATER") or t.has("CONSTRUCTED"):
            continue
        lm.set_tile(p.x, p.y, sz, "road")


def _place_rects(
    lm, rng: RNG, count: int, min_size: int, max_size: int, area: Rect
) -> List[Rect]:
    """Pack non-overlapping building footprints into an area."""
    out: List[Rect] = []
    for _ in range(count * 12):
        if len(out) >= count:
            break
        w = rng.randint(min_size, max_size)
        h = rng.randint(min_size, max_size)
        x = rng.randint(area.x, max(area.x, area.x2 - w - 1))
        y = rng.randint(area.y, max(area.y, area.y2 - h - 1))
        r = Rect(x, y, w, h)
        if any(r.expand(1).intersects(o) for o in out):
            continue
        out.append(r)
    return out


def _residents_for(site) -> Tuple[str, str]:
    """The creature id and faction for a site's ordinary inhabitants."""
    race = site.race or "human"
    faction = "hostile" if site.hostile else "town"
    return (race, faction)


# --------------------------------------------------------------------------- #
# Site builders
# --------------------------------------------------------------------------- #


def build_town(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A human town: houses, a tavern, a temple, a market and a keep."""
    pop: List[PopSpec] = []
    z = 0
    area = Rect(4, 4, lm.width - 8, lm.height - 8)
    n_buildings = max(4, min(14, site.population // 12 + 4))
    rects = _place_rects(lm, rng, n_buildings, 5, 9, area)
    if not rects:
        return pop

    kinds = ["tavern", "temple", "market", "keep"] + ["house"] * 20
    rng.shuffle(kinds[4:])
    race, faction = _residents_for(site)
    center = rects[0].center

    for i, r in enumerate(rects):
        kind = kinds[i] if i < len(kinds) else "house"
        sides = ["south", "north", "west", "east"]
        _building(lm, r, z, rng, door_sides=(rng.choice(sides),))
        _furnish(lm, r, z, rng, kind)
        _road(lm, r.center.x, r.center.y, center.x, center.y, z)

        inner = r.inner(1)
        spots = [p for p in inner.cells() if lm.walkable(p.x, p.y, z)]
        rng.shuffle(spots)
        if kind == "tavern":
            if spots:
                p = spots.pop()
                pop.append(_pop(race, p.x, p.y, z, faction=faction,
                                profession="tavern keeper", role="tavern_keeper"))
            for _ in range(min(3, len(spots))):
                p = spots.pop()
                pop.append(_pop(
                    rng.choice([race, "human", "merchant", "bandit"]),
                    p.x, p.y, z, faction=faction, profession="patron",
                    role="patron",
                ))
        elif kind == "keep":
            if spots:
                p = spots.pop()
                pop.append(_pop(race, p.x, p.y, z, faction=faction,
                                profession="lord", role="lord",
                                hf_id=site.ruler_hf, level=3))
            for _ in range(min(2, len(spots))):
                p = spots.pop()
                pop.append(_pop("guard", p.x, p.y, z, faction=faction,
                                profession="guard", role="guard", level=2))
        elif kind == "market":
            for _ in range(min(2, len(spots))):
                p = spots.pop()
                pop.append(_pop("merchant", p.x, p.y, z, faction=faction,
                                profession="merchant", role="merchant"))
        elif kind == "temple":
            if spots:
                p = spots.pop()
                pop.append(_pop(race, p.x, p.y, z, faction=faction,
                                profession="priest", role="priest"))
        else:
            for _ in range(min(rng.randint(1, 2), len(spots))):
                p = spots.pop()
                pop.append(_pop(race, p.x, p.y, z, faction=faction,
                                profession="peasant", role="citizen"))

    # A few people out in the streets, where the player will actually meet them.
    streets = [
        (x, y) for y in range(lm.height) for x in range(lm.width)
        if lm.tile(x, y, z) == "road"
    ]
    if not streets:
        streets = [
            (x, y) for y in range(lm.height) for x in range(lm.width)
            if lm.walkable(x, y, z)
            and abs(x - center.x) < 16 and abs(y - center.y) < 12
        ]
    rng.shuffle(streets)
    for x, y in streets[: rng.randint(3, 7)]:
        pop.append(_pop(race, x, y, z, faction=faction, profession="peasant",
                        role="citizen"))
    for x, y in streets[7: 7 + rng.randint(1, 3)]:
        pop.append(_pop("guard", x, y, z, faction=faction, profession="guard",
                        role="guard", level=1))
    return pop


def build_fortress(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A dwarven fortress: a gated surface hall over carved underground rooms."""
    pop: List[PopSpec] = []
    z = 0
    hall = Rect(lm.width // 2 - 8, lm.height // 2 - 6, 17, 13)
    _building(lm, hall, z, rng, door_sides=("south",))
    _furnish(lm, hall, z, rng, "keep")

    # Cut a stairwell down into the mountain.
    sx, sy = hall.center.x, hall.center.y
    for zz in range(z, lm.zmin, -1):
        lm.set_tile(sx, sy, zz, "stair_updown")
    lm.set_tile(sx, sy, z, "stair_down")

    race, faction = _residents_for(site)
    # Underground halls.
    for depth in range(1, 4):
        zz = z - depth
        if zz < lm.zmin:
            break
        room = Rect(sx - 9 + rng.randint(-2, 2), sy - 6 + rng.randint(-2, 2), 19, 13)
        for y in range(room.y, room.y2):
            for x in range(room.x, room.x2):
                if 0 <= x < lm.width and 0 <= y < lm.height:
                    lm.set_tile(x, y, zz, "floor_constructed")
        for p in room.border():
            if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
                lm.set_tile(p.x, p.y, zz, "wall_constructed")
        lm.set_tile(sx, sy, zz, "stair_updown")
        for _ in range(rng.randint(2, 5)):
            x = rng.randint(room.x + 1, room.x2 - 2)
            y = rng.randint(room.y + 1, room.y2 - 2)
            lm.set_tile(x, y, zz, rng.choice(["bed", "table", "chair", "cabinet"]))
        for _ in range(rng.randint(2, 5)):
            x = rng.randint(room.x + 1, room.x2 - 2)
            y = rng.randint(room.y + 1, room.y2 - 2)
            if lm.walkable(x, y, zz):
                pop.append(_pop(race, x, y, zz, faction=faction,
                                profession=rng.choice(
                                    ["miner", "smith", "brewer", "mason"]),
                                role="citizen"))

    inner = hall.inner(1)
    spots = [p for p in inner.cells() if lm.walkable(p.x, p.y, z)]
    rng.shuffle(spots)
    if spots:
        p = spots.pop()
        pop.append(_pop(race, p.x, p.y, z, faction=faction, profession="lord",
                        role="lord", hf_id=site.ruler_hf, level=4))
    for _ in range(min(3, len(spots))):
        p = spots.pop()
        pop.append(_pop("hammerdwarf" if race == "dwarf" else "guard",
                        p.x, p.y, z, faction=faction, profession="guard",
                        role="guard", level=3))
    if spots:
        p = spots.pop()
        pop.append(_pop(race, p.x, p.y, z, faction=faction,
                        profession="tavern keeper", role="tavern_keeper"))
    return pop


def build_cave(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A kobold warren: twisting tunnels under a hidden entrance."""
    pop: List[PopSpec] = []
    z = -2 if lm.zmin <= -2 else lm.zmin
    x, y = lm.width // 2, lm.height // 2
    cells: List[Tuple[int, int]] = []
    for _ in range(rng.randint(160, 320)):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 1 <= nx < lm.width - 1 and 1 <= ny < lm.height - 1:
                    lm.set_tile(nx, ny, z, "stone_floor")
                    cells.append((nx, ny))
        dx, dy = rng.dir8()
        x = max(2, min(lm.width - 3, x + dx))
        y = max(2, min(lm.height - 3, y + dy))

    # Surface entrance.
    ex, ey = lm.width // 2, lm.height // 2
    sz = lm.surface_z(ex, ey)
    for zz in range(z, sz + 1):
        lm.set_tile(ex, ey, zz, "stair_updown")
    lm.set_tile(ex, ey, sz, "stair_down")
    lm.entry_points["cave"] = (ex, ey, sz)

    race, faction = _residents_for(site)
    rng.shuffle(cells)
    n = max(3, min(18, site.population // 2 + 3))
    for i in range(min(n, len(cells))):
        cx, cy = cells[i]
        pop.append(_pop(race, cx, cy, z, faction="hostile",
                        profession="thief", role="denizen", level=1))
    return pop


def build_dark_fortress(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A goblin dark fortress: a black spire ringed by pits."""
    pop: List[PopSpec] = []
    z = 0
    tower = Rect(lm.width // 2 - 4, lm.height // 2 - 4, 9, 9)
    for level in range(0, min(5, lm.zmax + 1)):
        zz = z + level
        _flatten(lm, tower, zz) if level == 0 else None
        for y in range(tower.y, tower.y2):
            for x in range(tower.x, tower.x2):
                if not (0 <= x < lm.width and 0 <= y < lm.height):
                    continue
                lm.set_tile(x, y, zz, "floor_constructed")
        for p in tower.border():
            if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
                lm.set_tile(p.x, p.y, zz, "wall_constructed")
        lm.set_tile(tower.center.x, tower.center.y, zz, "stair_updown")
    lm.set_tile(tower.center.x, tower.center.y, z, "stair_up")
    door = (tower.x + tower.w // 2, tower.y2 - 1)
    lm.set_tile(door[0], door[1], z, "door_closed")

    area = Rect(3, 3, lm.width - 6, lm.height - 6)
    for r in _place_rects(lm, rng, rng.randint(4, 9), 4, 7, area):
        if r.intersects(tower.expand(2)):
            continue
        _building(lm, r, z, rng, door_sides=(rng.choice(
            ["south", "north", "west", "east"]),))
        _furnish(lm, r, z, rng, "barracks")
        inner = r.inner(1)
        spots = [p for p in inner.cells() if lm.walkable(p.x, p.y, z)]
        for p in spots[: rng.randint(1, 3)]:
            pop.append(_pop("goblin", p.x, p.y, z, faction="hostile",
                            profession="soldier", role="denizen", level=2))

    inner = tower.inner(1)
    spots = [p for p in inner.cells() if lm.walkable(p.x, p.y, z)]
    rng.shuffle(spots)
    if spots:
        p = spots.pop()
        pop.append(_pop("goblin", p.x, p.y, z, faction="hostile",
                        profession="warlord", role="lord",
                        hf_id=site.ruler_hf, level=5))
    for p in spots[:3]:
        pop.append(_pop("goblin", p.x, p.y, z, faction="hostile",
                        profession="guard", role="guard", level=3))
    for _ in range(rng.randint(2, 5)):
        x, y, zz = lm.random_open(rng)
        pop.append(_pop(rng.choice(["goblin", "goblin", "troll"]), x, y, zz,
                        faction="hostile", profession="soldier",
                        role="denizen", level=2))
    return pop


def build_tower(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A necromancer's tower, with undead on every floor."""
    pop: List[PopSpec] = []
    z = 0
    tower = Rect(lm.width // 2 - 3, lm.height // 2 - 3, 7, 7)
    floors = min(5, lm.zmax + 1)
    for level in range(floors):
        zz = z + level
        if level == 0:
            _flatten(lm, tower, zz)
        for y in range(tower.y, tower.y2):
            for x in range(tower.x, tower.x2):
                if 0 <= x < lm.width and 0 <= y < lm.height:
                    lm.set_tile(x, y, zz, "floor_constructed")
        for p in tower.border():
            if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
                lm.set_tile(p.x, p.y, zz, "wall_constructed")
        lm.set_tile(tower.center.x, tower.center.y, zz, "stair_updown")
        inner = tower.inner(1)
        spots = [p for p in inner.cells()
                 if lm.walkable(p.x, p.y, zz) and (p.x, p.y) != (
                     tower.center.x, tower.center.y)]
        rng.shuffle(spots)
        for p in spots[: rng.randint(1, 3)]:
            pop.append(_pop(rng.choice(["zombie", "skeleton", "ghoul"]),
                            p.x, p.y, zz, faction="hostile",
                            profession="undead", role="denizen", level=1))
    lm.set_tile(tower.x + 3, tower.y2 - 1, z, "door_closed")
    # Unless the histories already record this one's death. A tower whose
    # necromancer was killed three hundred years ago is an empty tower with
    # its dead still walking in it, not a second chance to kill somebody the
    # legends have already buried. A tower nobody claimed still gets one --
    # that is what a tower is -- it just has no name to put to it.
    owner = world.figures.get(site.owner_hf) if site.owner_hf else None
    if site.owner_hf is None or (owner is not None and owner.alive(world.year)):
        top = z + floors - 1
        pop.append(_pop("necromancer", tower.center.x + 1, tower.center.y, top,
                        faction="hostile", profession="necromancer",
                        role="lord", hf_id=site.owner_hf, level=5))
    return pop


def build_ruin(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A broken settlement with something living in it."""
    pop: List[PopSpec] = []
    z = 0
    area = Rect(4, 4, lm.width - 8, lm.height - 8)
    for r in _place_rects(lm, rng, rng.randint(3, 7), 4, 8, area):
        _flatten(lm, r, z)
        for p in r.border():
            if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
                if rng.chance(0.55):
                    lm.set_tile(p.x, p.y, z, "wall_constructed")
                else:
                    lm.set_tile(p.x, p.y, z, "rubble")
        for p in r.inner(1).cells():
            if rng.chance(0.25):
                lm.set_tile(p.x, p.y, z, "rubble")
    for _ in range(rng.randint(2, 6)):
        x, y, zz = lm.random_open(rng)
        pop.append(_pop(
            rng.choice(["zombie", "skeleton", "giant_rat", "bandit", "goblin"]),
            x, y, zz, faction="hostile", profession="", role="denizen", level=1,
        ))
    # Sometimes what ruined the place is still written on a wall of it. Towers
    # only generate in larger worlds; ruins generate in nearly all of them.
    undead = [spec for spec in pop
              if spec["def_id"] in ("zombie", "skeleton")]
    if undead and rng.chance(0.4):
        undead[0]["profession"] = "tomb_lord"
    return pop


def build_camp(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A bandit camp around a fire."""
    pop: List[PopSpec] = []
    cx, cy, z = lm.random_open(rng)
    lm.set_tile(cx, cy, z, "campfire")
    for _ in range(rng.randint(3, 8)):
        x = max(1, min(lm.width - 2, cx + rng.randint(-6, 6)))
        y = max(1, min(lm.height - 2, cy + rng.randint(-6, 6)))
        zz = lm.surface_z(x, y)
        if lm.walkable(x, y, zz):
            pop.append(_pop("bandit", x, y, zz, faction="hostile",
                            profession="bandit", role="denizen", level=1))
    if pop:
        pop[0]["level"] = 3
        pop[0]["role"] = "lord"
        pop[0]["profession"] = "bandit leader"
        pop[0]["hf_id"] = site.owner_hf
    return pop


def build_lair(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A beast's lair, littered with bones and treasure."""
    pop: List[PopSpec] = []
    cx, cy = lm.width // 2, lm.height // 2
    z = -1 if lm.zmin <= -1 else lm.zmin
    for _ in range(rng.randint(120, 220)):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nx, ny = cx + dx, cy + dy
                if 1 <= nx < lm.width - 1 and 1 <= ny < lm.height - 1:
                    lm.set_tile(nx, ny, z, "stone_floor")
        dx, dy = rng.dir8()
        cx = max(2, min(lm.width - 3, cx + dx))
        cy = max(2, min(lm.height - 3, cy + dy))
    ex, ey = lm.width // 2, lm.height // 2
    sz = lm.surface_z(ex, ey)
    for zz in range(z, sz + 1):
        lm.set_tile(ex, ey, zz, "stair_updown")
    lm.entry_points["cave"] = (ex, ey, sz)

    # Whoever actually lairs here, if the world remembers somebody doing so.
    # This used to be `rng.choice(megabeasts)`: an anonymous beast of a random
    # species with no `hf_id`, in a cave the histories had never heard of --
    # while the quest to kill a named beast pointed at a cave picked the same
    # way. The two halves existed for versions and were never joined, so a
    # slay-the-beast quest could not be finished by anybody.
    beasts = [c for c in creature_data.megabeasts() if c.frequency > 0]
    beast = rng.choice(beasts) if beasts else creature_data.get("troll")
    x, y, _zz = lm.random_open(rng, z)
    pop.append(_pop(beast.id, x, y, z, faction="hostile",
                    profession=beast.name, role="beast", level=2))
    return pop


def build_forest_retreat(lm, world, site, rng: RNG) -> List[PopSpec]:
    """An elven retreat built in the treetops."""
    pop: List[PopSpec] = []
    z = 1 if lm.zmax >= 1 else 0
    area = Rect(6, 6, lm.width - 12, lm.height - 12)
    for r in _place_rects(lm, rng, rng.randint(4, 8), 4, 6, area):
        for y in range(r.y, r.y2):
            for x in range(r.x, r.x2):
                if 0 <= x < lm.width and 0 <= y < lm.height:
                    lm.set_tile(x, y, z, "floor_constructed")
                    sz = lm.surface_z(x, y)
                    if lm.walkable(x, y, sz):
                        lm.set_tile(x, y, sz, "tree")
        for p in r.border():
            if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
                lm.set_tile(p.x, p.y, z, "wall_constructed")
        ladder = r.center
        lm.set_tile(ladder.x, ladder.y, z, "stair_down")
        below = lm.surface_z(ladder.x, ladder.y)
        for zz in range(below, z):
            lm.set_tile(ladder.x, ladder.y, zz, "stair_updown")
        inner = r.inner(1)
        spots = [p for p in inner.cells() if lm.walkable(p.x, p.y, z)]
        for p in spots[: rng.randint(1, 3)]:
            pop.append(_pop("elf", p.x, p.y, z, faction="town",
                            profession=rng.choice(["archer", "peasant", "poet"]),
                            role="citizen"))
    for _ in range(rng.randint(2, 5)):
        x, y, zz = lm.random_open(rng)
        pop.append(_pop("elf_archer", x, y, zz, faction="town",
                        profession="archer", role="guard", level=2))
    if pop:
        pop[0]["role"] = "lord"
        pop[0]["profession"] = "lord"
        pop[0]["hf_id"] = site.ruler_hf
        pop[0]["level"] = 3
    return pop


def build_shrine(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A lonely roadside shrine."""
    x, y, z = lm.random_open(rng)
    r = Rect(max(1, x - 2), max(1, y - 2), 5, 5)
    _flatten(lm, r, z)
    for p in r.border():
        if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
            lm.set_tile(p.x, p.y, z, "wall_constructed")
    lm.set_tile(r.center.x, r.center.y, z, "altar")
    lm.set_tile(r.x + 2, r.y2 - 1, z, "door_open")
    return []


def build_tomb(lm, world, site, rng: RNG) -> List[PopSpec]:
    """A buried crypt full of the restless dead."""
    pop: List[PopSpec] = []
    z = -1 if lm.zmin <= -1 else lm.zmin
    room = Rect(lm.width // 2 - 7, lm.height // 2 - 5, 15, 11)
    for y in range(room.y, room.y2):
        for x in range(room.x, room.x2):
            if 0 <= x < lm.width and 0 <= y < lm.height:
                lm.set_tile(x, y, z, "floor_constructed")
    for p in room.border():
        if 0 <= p.x < lm.width and 0 <= p.y < lm.height:
            lm.set_tile(p.x, p.y, z, "wall_constructed")
    ex, ey = room.center.x, room.center.y
    sz = lm.surface_z(ex, ey)
    for zz in range(z, sz + 1):
        lm.set_tile(ex, ey, zz, "stair_updown")
    lm.entry_points["cave"] = (ex, ey, sz)
    for _ in range(rng.randint(4, 10)):
        x = rng.randint(room.x + 1, room.x2 - 2)
        y = rng.randint(room.y + 1, room.y2 - 2)
        lm.set_tile(x, y, z, "grave")
    for _ in range(rng.randint(2, 6)):
        x = rng.randint(room.x + 1, room.x2 - 2)
        y = rng.randint(room.y + 1, room.y2 - 2)
        if lm.walkable(x, y, z):
            pop.append(_pop(rng.choice(["skeleton", "zombie", "mummy"]),
                            x, y, z, faction="hostile", role="denizen", level=1))
    # Whoever cut a tomb full of walking dead knew how it was done, and wrote
    # it on the wall. Towers only generate in larger worlds; tombs and ruins
    # generate in all of them, and a secret nobody can reach is not a secret.
    if pop:
        pop[0]["profession"] = "tomb_lord"
    return pop


_BUILDERS = {
    "town": build_town,
    "city": build_town,
    "hamlet": build_town,
    "castle": build_town,
    "hillocks": build_town,
    "fortress": build_fortress,
    "cave": build_cave,
    "dark_fortress": build_dark_fortress,
    "dark_pits": build_dark_fortress,
    "tower": build_tower,
    "ruin": build_ruin,
    "camp": build_camp,
    "lair": build_lair,
    "forest_retreat": build_forest_retreat,
    "shrine": build_shrine,
    "tomb": build_tomb,
}


def build_site(lm, world, site, rng: RNG) -> List[PopSpec]:
    """Build a site into a local map and return who lives there."""
    from . import residents as resident_mod

    if site is None:
        return []
    if site.is_ruin and site.kind not in ("ruin", "tomb"):
        # Falls through to the shared tail rather than returning here: a cave
        # that fell in since the beast moved into it is still where the beast
        # lives, and the early return was why the one ruined lair in a world
        # came out empty.
        pop = build_ruin(lm, world, site, rng)
    else:
        builder = _BUILDERS.get(site.kind)
        if builder is None:
            return []
        pop = builder(lm, world, site, rng)
    # Every builder above invents anonymous townsfolk, and the world has
    # already decided who lives here by name. One funnel, so no builder has to
    # remember to ask.
    resident_mod.name_the_locals(world, site, pop)
    _add_lair_beast(lm, world, site, rng, pop)
    return pop


def _add_lair_beast(lm, world, site, rng: RNG, pop: List[PopSpec]) -> None:
    """Put the beast the histories say lairs here into its own lair.

    Here rather than in a builder, for the same reason the residents are named
    here: three builders make somewhere a beast can live -- `build_lair`,
    `build_cave`, and `build_ruin` for the cave that fell in since -- and the
    one that was missed is the one that mattered. `build_lair` used to put a
    beast of a random species with no `hf_id` in every lair, while the quest to
    kill a *named* beast pointed at a cave chosen the same random way and the
    beast itself lived nowhere at all. Every half existed and none were joined,
    so a slay-the-beast quest could not be finished by anybody.
    """
    from . import history as history_mod

    fig = history_mod.lair_beast(world, site.id, world.year)
    if fig is None:
        return
    if any(spec.get("hf_id") == fig.id for spec in pop):
        return
    defn = creature_data.get(fig.creature_id)
    # Underground if this place has an underground; a beast in a hole in the
    # ground is the point of it.
    z = -1 if lm.zmin <= -1 else lm.zmin
    spot = lm.random_open(rng, z) or lm.random_open(rng)
    if spot is None:
        return
    x, y, zz = spot
    pop.append(_pop(defn.id, x, y, zz, faction="hostile",
                    profession=defn.name, role="beast", level=2,
                    name=fig.display_name, hf_id=fig.id))
