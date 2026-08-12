"""The local map: one world tile blown up into a walkable, multi-level place.

Z-levels run from ``zmin`` (deep caverns) to ``zmax`` (treetops and towers).
Level 0 is the nominal surface; each column has its own surface height, so hills
and valleys are real terrain you climb rather than paint.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..data import biomes as biome_data
from ..data import materials as mat_data
from ..engine.noise import ValueNoise
from ..engine.rng import RNG
from . import tiles as tile_data

LOCAL_W = 64
LOCAL_H = 48
Z_BELOW = 6
Z_ABOVE = 4


class LocalMap:
    """A three-dimensional grid of terrain tiles."""

    def __init__(
        self,
        width: int,
        height: int,
        zmin: int,
        zmax: int,
        *,
        wx: int = 0,
        wy: int = 0,
        biome: str = "grassland",
    ) -> None:
        self.width = width
        self.height = height
        self.zmin = zmin
        self.zmax = zmax
        self.wx = wx
        self.wy = wy
        self.biome = biome
        self.site_id: Optional[int] = None
        #: z -> flat list of tile ids.
        self.levels: Dict[int, List[str]] = {
            z: ["air"] * (width * height) for z in range(zmin, zmax + 1)
        }
        #: Column surface heights, indexed like a level.
        self.surface: List[int] = [0] * (width * height)
        self.stone = "granite"
        self.soil = "dirt"
        self.entry_points: Dict[str, Tuple[int, int, int]] = {}

    # -- access ------------------------------------------------------------ #

    def in_bounds(self, x: int, y: int, z: int) -> bool:
        """True if a coordinate exists on this map."""
        return (
            0 <= x < self.width and 0 <= y < self.height
            and self.zmin <= z <= self.zmax
        )

    def tile(self, x: int, y: int, z: int) -> str:
        """The tile id at a coordinate; out-of-bounds reads return rock."""
        if not self.in_bounds(x, y, z):
            return "rock_wall"
        return self.levels[z][y * self.width + x]

    def set_tile(self, x: int, y: int, z: int, tid: str) -> None:
        """Write a tile, ignoring out-of-bounds writes."""
        if self.in_bounds(x, y, z):
            self.levels[z][y * self.width + x] = tid

    def surface_z(self, x: int, y: int) -> int:
        """The ground level of a column."""
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.surface[y * self.width + x]
        return 0

    def walkable(self, x: int, y: int, z: int) -> bool:
        """True if a creature can stand here."""
        if not self.in_bounds(x, y, z):
            return False
        t = tile_data.get(self.tile(x, y, z))
        if t.walk:
            return True
        return False

    def blocks_sight(self, x: int, y: int, z: int) -> bool:
        """True if this cell stops line of sight."""
        if not self.in_bounds(x, y, z):
            return True
        return not tile_data.get(self.tile(x, y, z)).sight

    def is_open(self, x: int, y: int, z: int) -> bool:
        """True if this cell is empty air a creature would fall through."""
        return tile_data.get(self.tile(x, y, z)).has("OPEN")

    def is_outside(self, x: int, y: int, z: int) -> bool:
        """True if the sky is visible from this cell."""
        if not self.in_bounds(x, y, z):
            return False
        if z < self.surface_z(x, y):
            return False
        for zz in range(z + 1, self.zmax + 1):
            if not tile_data.get(self.tile(x, y, zz)).has("OPEN"):
                return False
        return True

    def has_floor(self, x: int, y: int, z: int) -> bool:
        """True if something solid supports a creature at this cell."""
        if not self.in_bounds(x, y, z):
            return False
        if tile_data.get(self.tile(x, y, z)).walk:
            return True
        below = self.tile(x, y, z - 1)
        return not tile_data.get(below).has("OPEN")

    def neighbours(self, x: int, y: int, z: int) -> Iterator[Tuple[int, int, int]]:
        """Every walkable cell reachable in one step, including stairs and ramps.

        These edges are deliberately symmetric: if you can get from A to B you
        can get back. An asymmetric graph gives you one-way drops that A* will
        cheerfully route through, stranding whoever took them.
        """
        for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1),
                       (-1, 0), (-1, -1)):
            nx, ny = x + dx, y + dy
            if self.walkable(nx, ny, z):
                yield (nx, ny, z)

        here = tile_data.get(self.tile(x, y, z))
        above = tile_data.get(self.tile(x, y, z + 1))
        below = tile_data.get(self.tile(x, y, z - 1))

        # Up a staircase, or up into the foot of one coming down.
        if (here.has("STAIR_UP") or above.has("STAIR_DOWN")) \
                and self.walkable(x, y, z + 1):
            yield (x, y, z + 1)
        # Down a staircase, or down onto the head of one going up.
        if (here.has("STAIR_DOWN") or below.has("STAIR_UP")) \
                and self.walkable(x, y, z - 1):
            yield (x, y, z - 1)

        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            # Up the slope of a ramp you are standing on.
            if here.has("RAMP") and self.walkable(x + dx, y + dy, z + 1):
                yield (x + dx, y + dy, z + 1)
            # Down onto a ramp on the level below.
            n = (x + dx, y + dy, z - 1)
            if tile_data.get(self.tile(*n)).has("RAMP") and self.walkable(*n):
                yield n

    def path_neighbours(self, node: Tuple[int, int, int]):
        """Neighbour generator in the ``(node, cost)`` form A* expects."""
        x, y, z = node
        for n in self.neighbours(x, y, z):
            diagonal = n[0] != x and n[1] != y
            cost = 1.41 if diagonal else 1.0
            if n[2] != z:
                cost = 2.0
            t = tile_data.get(self.tile(*n))
            if t.has("WATER"):
                cost *= 2.5
            yield (n, cost)

    def random_open(
        self, rng: RNG, z: Optional[int] = None, *, tries: int = 400
    ) -> Tuple[int, int, int]:
        """A random walkable cell, preferring the surface."""
        for _ in range(tries):
            x = rng.randint(0, self.width - 1)
            y = rng.randint(0, self.height - 1)
            zz = self.surface_z(x, y) if z is None else z
            if self.walkable(x, y, zz) and not tile_data.get(
                self.tile(x, y, zz)
            ).has("WATER"):
                return (x, y, zz)
        # Fall back to an exhaustive scan.
        for yy in range(self.height):
            for xx in range(self.width):
                zz = self.surface_z(xx, yy) if z is None else z
                if self.walkable(xx, yy, zz):
                    return (xx, yy, zz)
        return (self.width // 2, self.height // 2, 0)

    def central_open(self, rng: RNG) -> Tuple[int, int, int]:
        """The walkable cell closest to the middle of the map.

        Arriving at a settlement should put you in it, not in a corner.
        """
        cx, cy = self.width // 2, self.height // 2
        best: Optional[Tuple[int, int, int]] = None
        best_score = None
        for y in range(self.height):
            for x in range(self.width):
                z = self.surface_z(x, y)
                if not self.walkable(x, y, z):
                    continue
                t = tile_data.get(self.tile(x, y, z))
                if t.has("WATER") or t.has("FURNITURE") or t.has("DOOR"):
                    continue
                # Arrive in the open, ideally on a road, not inside someone's
                # bedroom with a wall in your face.
                open_sides = sum(
                    1 for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
                    if self.walkable(x + dx, y + dy, z)
                    and not tile_data.get(self.tile(x + dx, y + dy, z)).has("WALL")
                )
                score = (
                    (x - cx) ** 2 + (y - cy) ** 2
                    - (400 if t.id == "road" else 0)
                    - open_sides * 40
                )
                if best_score is None or score < best_score:
                    best, best_score = (x, y, z), score
        return best if best is not None else self.random_open(rng)

    def edge_entry(self, rng: RNG, side: str) -> Tuple[int, int, int]:
        """A walkable cell on one edge of the map, for arriving on foot."""
        candidates: List[Tuple[int, int, int]] = []
        if side in ("west", "east"):
            x = 1 if side == "west" else self.width - 2
            for y in range(1, self.height - 1):
                z = self.surface_z(x, y)
                if self.walkable(x, y, z):
                    candidates.append((x, y, z))
        else:
            y = 1 if side == "north" else self.height - 2
            for x in range(1, self.width - 1):
                z = self.surface_z(x, y)
                if self.walkable(x, y, z):
                    candidates.append((x, y, z))
        if candidates:
            return rng.choice(candidates)
        return self.random_open(rng)

    def count_tiles(self, tid: str) -> int:
        """How many cells hold a given tile id."""
        return sum(level.count(tid) for level in self.levels.values())

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the map with simple run-length encoding."""
        return {
            "w": self.width, "h": self.height,
            "zmin": self.zmin, "zmax": self.zmax,
            "wx": self.wx, "wy": self.wy, "biome": self.biome,
            "site": self.site_id, "stone": self.stone, "soil": self.soil,
            "surface": self.surface,
            "entries": {k: list(v) for k, v in self.entry_points.items()},
            "levels": {
                str(z): _rle_encode(level) for z, level in self.levels.items()
            },
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "LocalMap":
        """Rebuild from :meth:`to_dict`."""
        lm = cls(int(d["w"]), int(d["h"]), int(d["zmin"]), int(d["zmax"]),
                 wx=int(d.get("wx", 0)), wy=int(d.get("wy", 0)),
                 biome=str(d.get("biome", "grassland")))
        lm.site_id = d.get("site")
        lm.stone = str(d.get("stone", "granite"))
        lm.soil = str(d.get("soil", "dirt"))
        lm.surface = [int(v) for v in d.get("surface", lm.surface)]
        lm.entry_points = {
            k: (int(v[0]), int(v[1]), int(v[2]))
            for k, v in (d.get("entries") or {}).items()
        }
        for zs, encoded in (d.get("levels") or {}).items():
            lm.levels[int(zs)] = _rle_decode(encoded, lm.width * lm.height)
        return lm

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "LocalMap(%dx%d, z %d..%d, %s)" % (
            self.width, self.height, self.zmin, self.zmax, self.biome
        )


def _rle_encode(level: Sequence[str]) -> List[Any]:
    """Run-length encode a level, which is mostly long runs of rock and air."""
    out: List[Any] = []
    prev: Optional[str] = None
    count = 0
    for tid in level:
        if tid == prev:
            count += 1
        else:
            if prev is not None:
                out.append([prev, count])
            prev, count = tid, 1
    if prev is not None:
        out.append([prev, count])
    return out


def _rle_decode(encoded: Sequence[Any], length: int) -> List[str]:
    """Reverse :func:`_rle_encode`."""
    out: List[str] = []
    for tid, count in encoded:
        out.extend([tid] * int(count))
    if len(out) < length:
        out.extend(["air"] * (length - len(out)))
    return out[:length]


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def _pick_stone(rng: RNG, biome: str) -> str:
    """Choose the local rock layer."""
    b = biome_data.get(biome)
    if b.stone and mat_data.exists(b.stone):
        return b.stone
    layer = rng.choice(list(mat_data.STONE_LAYERS))
    return rng.choice(mat_data.STONE_LAYERS[layer])


def _build_heightmap(
    world, wx: int, wy: int, rng: RNG, w: int, h: int, zmin: int, zmax: int,
    *, flatten: float = 1.0,
) -> List[int]:
    """Interpolate a local heightmap from the world tile and its neighbours."""
    noise = ValueNoise(rng.sub("height"))
    here = world.tile(wx, wy)
    base = here.elevation

    # Sample the four corners from neighbouring world tiles so adjacent local
    # maps line up at their edges.
    def elev(dx: int, dy: int) -> float:
        return world.tile(wx + dx, wy + dy).elevation

    corners = {
        (0, 0): (base + elev(-1, 0) + elev(0, -1) + elev(-1, -1)) / 4.0,
        (1, 0): (base + elev(1, 0) + elev(0, -1) + elev(1, -1)) / 4.0,
        (0, 1): (base + elev(-1, 0) + elev(0, 1) + elev(-1, 1)) / 4.0,
        (1, 1): (base + elev(1, 0) + elev(0, 1) + elev(1, 1)) / 4.0,
    }

    relief = (1.0 + max(0.0, here.elevation - 0.42) * 14.0) * flatten
    heights: List[int] = [0] * (w * h)
    for y in range(h):
        fy = y / max(1.0, h - 1.0)
        for x in range(w):
            fx = x / max(1.0, w - 1.0)
            top = corners[(0, 0)] * (1 - fx) + corners[(1, 0)] * fx
            bot = corners[(0, 1)] * (1 - fx) + corners[(1, 1)] * fx
            e = top * (1 - fy) + bot * fy
            detail = noise.fbm(x * 0.12, y * 0.12, 4) * 0.5 + 0.5
            local = ((e - base) * 40.0) * flatten + (detail - 0.5) * relief * 1.8
            heights[y * w + x] = max(zmin + 2, min(zmax - 2, int(round(local))))
    return heights


def _fill_columns(lm: LocalMap, world, rng: RNG) -> None:
    """Lay down rock, soil and surface terrain for every column."""
    here = world.tile(lm.wx, lm.wy)
    b = biome_data.get(lm.biome)
    surface_tile = {
        "sand": "sand", "mud": "mud", "ice": "ice", "dirt": "dirt",
    }.get(b.soil, "dirt")
    if b.grass and here.temperature > 5:
        surface_tile = "grass"
    if b.has("FROZEN") and here.temperature < 10:
        surface_tile = "snow"

    water_level = None
    if here.is_ocean or here.is_lake:
        water_level = max(lm.zmin + 1, min(lm.zmax - 1, 0))

    for y in range(lm.height):
        for x in range(lm.width):
            sz = lm.surface[y * lm.width + x]
            for z in range(lm.zmin, lm.zmax + 1):
                if z < sz - 3:
                    lm.set_tile(x, y, z, "rock_wall")
                elif z < sz:
                    lm.set_tile(x, y, z, "soil_wall")
                elif z == sz:
                    lm.set_tile(x, y, z, surface_tile)
                else:
                    lm.set_tile(x, y, z, "air")
            if water_level is not None and sz <= water_level:
                for z in range(sz, water_level + 1):
                    depth = water_level - z
                    lm.set_tile(
                        x, y, z,
                        "deep_water" if depth > 1 else
                        ("water" if depth > 0 else "shallow_water"),
                    )


def _add_ramps(lm: LocalMap) -> None:
    """Put ramps wherever the surface steps up, so slopes are climbable."""
    for y in range(lm.height):
        for x in range(lm.width):
            sz = lm.surface_z(x, y)
            higher = False
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < lm.width and 0 <= ny < lm.height:
                    if lm.surface_z(nx, ny) > sz:
                        higher = True
                        break
            if higher:
                current = tile_data.get(lm.tile(x, y, sz))
                if not current.has("WATER") and not current.has("CONSTRUCTED") \
                        and not current.has("FURNITURE") and current.walk:
                    lm.set_tile(x, y, sz, "ramp_up")


def _scatter_plants(lm: LocalMap, rng: RNG) -> None:
    """Plant trees and shrubs according to the biome."""
    b = biome_data.get(lm.biome)
    for y in range(lm.height):
        for x in range(lm.width):
            sz = lm.surface_z(x, y)
            t = tile_data.get(lm.tile(x, y, sz))
            if not t.walk or t.has("WATER") or t.has("RAMP"):
                continue
            if rng.chance(b.tree_density * 0.55):
                lm.set_tile(x, y, sz, "tree")
                # A tree's canopy occupies the level above.
                if lm.in_bounds(x, y, sz + 1):
                    lm.set_tile(x, y, sz + 1, "tree")
            elif rng.chance(b.shrub_density * 0.35):
                lm.set_tile(x, y, sz, "shrub")


def _carve_river(lm: LocalMap, world, rng: RNG) -> None:
    """Cut a river across the map if the world tile has one."""
    here = world.tile(lm.wx, lm.wy)
    if not here.river:
        return
    horizontal = rng.chance(0.5)
    span = lm.height if horizontal else lm.width
    pos = (lm.width if horizontal else lm.height) // 2
    width = 2 + min(4, here.river // 3)
    noise = ValueNoise(rng.sub("river"))
    for i in range(span):
        pos += int(round(noise.noise2(i * 0.15, 3.7) * 1.6))
        pos = max(width + 1, min((lm.width if horizontal else lm.height)
                                 - width - 2, pos))
        for o in range(-width, width + 1):
            x, y = (pos + o, i) if horizontal else (i, pos + o)
            if not (0 <= x < lm.width and 0 <= y < lm.height):
                continue
            sz = lm.surface_z(x, y)
            depth = 1 if abs(o) >= width - 1 else 2
            for d in range(depth):
                lm.set_tile(x, y, sz - d, "shallow_water" if depth == 1 else "water")
            lm.surface[y * lm.width + x] = sz - depth + 1
            if lm.in_bounds(x, y, sz + 1):
                lm.set_tile(x, y, sz + 1, "air")


def _carve_caves(lm: LocalMap, rng: RNG) -> None:
    """Grow cave systems below the surface with cellular automata."""
    for z in range(lm.zmin, min(0, lm.zmax)):
        depth_from_top = -z
        fill = 0.44 + 0.02 * depth_from_top
        grid = [
            [rng.chance(fill) for _ in range(lm.width)] for _ in range(lm.height)
        ]
        for _ in range(4):
            new = [row[:] for row in grid]
            for y in range(lm.height):
                for x in range(lm.width):
                    n = 0
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nx, ny = x + dx, y + dy
                            if 0 <= nx < lm.width and 0 <= ny < lm.height:
                                if grid[ny][nx]:
                                    n += 1
                            else:
                                n += 1
                    new[y][x] = n >= 5 if grid[y][x] else n >= 6
            grid = new
        for y in range(lm.height):
            for x in range(lm.width):
                if grid[y][x]:
                    continue
                if y in (0, lm.height - 1) or x in (0, lm.width - 1):
                    continue
                if z < lm.surface_z(x, y):
                    lm.set_tile(x, y, z, "stone_floor")


def _connect_levels(lm: LocalMap, rng: RNG) -> None:
    """Punch staircases so every level below the surface is reachable."""
    for z in range(lm.zmax, lm.zmin, -1):
        below = z - 1
        if below < lm.zmin:
            break
        spots: List[Tuple[int, int]] = []
        for y in range(1, lm.height - 1):
            for x in range(1, lm.width - 1):
                if lm.walkable(x, y, below) and not tile_data.get(
                    lm.tile(x, y, below)
                ).has("WATER"):
                    spots.append((x, y))
        if not spots:
            continue
        rng.shuffle(spots)
        made = 0
        for x, y in spots:
            if made >= 3:
                break
            # A staircase needs a solid column to cut through.
            sz = lm.surface_z(x, y)
            if z > sz:
                continue
            here = lm.tile(x, y, z)
            if tile_data.get(here).has("WATER"):
                continue
            lm.set_tile(x, y, z, "stair_down")
            lm.set_tile(x, y, below, "stair_up")
            made += 1


def _add_ore(lm: LocalMap, rng: RNG) -> None:
    """Seed ore and gem veins in the rock."""
    for _ in range(rng.randint(4, 14)):
        z = rng.randint(lm.zmin, min(-1, lm.zmax))
        x = rng.randint(2, lm.width - 3)
        y = rng.randint(2, lm.height - 3)
        kind = "gem_vein" if rng.one_in(5) else "ore_vein"
        for _ in range(rng.randint(3, 12)):
            if lm.tile(x, y, z) == "rock_wall":
                lm.set_tile(x, y, z, kind)
            dx, dy = rng.dir8()
            x = max(1, min(lm.width - 2, x + dx))
            y = max(1, min(lm.height - 2, y + dy))


def _add_cave_entrance(lm: LocalMap, rng: RNG) -> None:
    """Open a way down from the surface into the caves."""
    for _ in range(60):
        x = rng.randint(2, lm.width - 3)
        y = rng.randint(2, lm.height - 3)
        sz = lm.surface_z(x, y)
        if not lm.walkable(x, y, sz):
            continue
        if tile_data.get(lm.tile(x, y, sz)).has("WATER"):
            continue
        # Dig straight down until we break into open space.
        for z in range(sz - 1, lm.zmin - 1, -1):
            if lm.walkable(x, y, z):
                for zz in range(z, sz):
                    lm.set_tile(x, y, zz, "stair_updown")
                lm.set_tile(x, y, sz, "stair_down")
                lm.entry_points["cave"] = (x, y, sz)
                return


def generate_local(
    world, wx: int, wy: int, rng: RNG, *, site=None
) -> Tuple[LocalMap, List[Dict[str, Any]]]:
    """Build the local map for one world tile."""
    from . import sitegen

    here = world.tile(wx, wy)
    zmin, zmax = -Z_BELOW, Z_ABOVE
    lm = LocalMap(LOCAL_W, LOCAL_H, zmin, zmax, wx=wx, wy=wy, biome=here.biome)
    lm.stone = _pick_stone(rng, here.biome)
    lm.soil = biome_data.get(here.biome).soil
    lm.site_id = site.id if site is not None else None

    # People build on level ground. Sites get a perfectly flat surface at z=0
    # so streets, halls, gates and the people in them all share one level.
    flatten = 0.0 if site is not None else 1.0
    lm.surface = _build_heightmap(
        world, wx, wy, rng, LOCAL_W, LOCAL_H, zmin, zmax, flatten=flatten
    )
    _fill_columns(lm, world, rng)
    _carve_river(lm, world, rng)
    if not (here.is_ocean or here.is_lake):
        _carve_caves(lm, rng)
        _add_ore(lm, rng)
        _connect_levels(lm, rng)
        _add_cave_entrance(lm, rng)
    _add_ramps(lm)
    _scatter_plants(lm, rng)

    population: List[Dict[str, Any]] = []
    if site is not None:
        population = sitegen.build_site(lm, world, site, rng)
        # Building carves cliffs; re-cut ramps so the site stays walkable.
        _add_ramps(lm)
    lm.entry_points.setdefault("center", lm.central_open(rng))
    return lm, population
