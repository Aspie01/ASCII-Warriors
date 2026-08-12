"""World generation.

Elevation from fractal noise, oceans by threshold, temperature by latitude and
altitude, orographic rainfall, drainage, rivers by downhill flow, then biomes,
regions and civilizations. History is simulated afterwards by
:mod:`ascii_warriors.world.history`.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..data import biomes as biome_data
from ..data import names as name_data
from ..engine.noise import ValueNoise, erode, normalize_grid, smooth_grid
from ..engine.rng import RNG

WORLD_SIZES: Dict[str, int] = {
    "pocket": 33, "small": 65, "medium": 97, "large": 129, "huge": 161,
}

#: Elevation below which a tile is ocean.
SEA_LEVEL = 0.42
#: Elevation above which a tile is mountain.
MOUNTAIN_LEVEL = 0.86

Progress = Optional[Callable[[str, float], None]]


class WorldTile:
    """One world-map square: roughly a day's walk across."""

    __slots__ = (
        "elevation", "rainfall", "temperature", "drainage", "volcanism",
        "savagery", "evil", "biome", "river", "river_dir", "is_ocean",
        "is_lake", "region_id", "site_id", "civ_id", "explored", "feature",
    )

    def __init__(self) -> None:
        self.elevation = 0.5
        self.rainfall = 0.5
        self.temperature = 50.0
        self.drainage = 0.5
        self.volcanism = 0.0
        self.savagery = 30
        self.evil = 50
        self.biome = "grassland"
        self.river = 0
        self.river_dir = -1
        self.is_ocean = False
        self.is_lake = False
        self.region_id = 0
        self.site_id: Optional[int] = None
        self.civ_id: Optional[int] = None
        self.explored = False
        #: Optional non-site landmark such as a cave mouth.
        self.feature = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the tile compactly."""
        return {
            "e": round(self.elevation, 4), "r": round(self.rainfall, 4),
            "t": round(self.temperature, 2), "d": round(self.drainage, 4),
            "v": round(self.volcanism, 3), "s": self.savagery, "ev": self.evil,
            "b": self.biome, "rv": self.river, "rd": self.river_dir,
            "o": self.is_ocean, "l": self.is_lake, "rg": self.region_id,
            "si": self.site_id, "ci": self.civ_id, "x": self.explored,
            "f": self.feature,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "WorldTile":
        """Rebuild from :meth:`to_dict`."""
        t = cls()
        t.elevation = float(d.get("e", 0.5))
        t.rainfall = float(d.get("r", 0.5))
        t.temperature = float(d.get("t", 50.0))
        t.drainage = float(d.get("d", 0.5))
        t.volcanism = float(d.get("v", 0.0))
        t.savagery = int(d.get("s", 30))
        t.evil = int(d.get("ev", 50))
        t.biome = str(d.get("b", "grassland"))
        t.river = int(d.get("rv", 0))
        t.river_dir = int(d.get("rd", -1))
        t.is_ocean = bool(d.get("o", False))
        t.is_lake = bool(d.get("l", False))
        t.region_id = int(d.get("rg", 0))
        t.site_id = d.get("si")
        t.civ_id = d.get("ci")
        t.explored = bool(d.get("x", False))
        t.feature = str(d.get("f", ""))
        return t


class Region:
    """A named contiguous area of one biome."""

    __slots__ = ("id", "name", "biome", "tiles", "savagery", "evil")

    def __init__(self, rid: int, name: str, biome: str) -> None:
        self.id = rid
        self.name = name
        self.biome = biome
        self.tiles: List[Tuple[int, int]] = []
        self.savagery = "Wilderness"
        self.evil = "Neutral"

    @property
    def full_name(self) -> str:
        """Name plus alignment, e.g. ``"The Sunken Wilds (Sinister Forest)"``."""
        return "%s (%s %s)" % (
            self.name, self.evil if self.evil != "Neutral" else self.savagery,
            biome_data.get(self.biome).name,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the region."""
        return {
            "id": self.id, "name": self.name, "biome": self.biome,
            "tiles": [list(t) for t in self.tiles],
            "savagery": self.savagery, "evil": self.evil,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Region":
        """Rebuild from :meth:`to_dict`."""
        r = cls(int(d["id"]), str(d["name"]), str(d["biome"]))
        r.tiles = [(int(a), int(b)) for a, b in d.get("tiles", [])]
        r.savagery = str(d.get("savagery", "Wilderness"))
        r.evil = str(d.get("evil", "Neutral"))
        return r


class World:
    """A generated world with its geography, peoples and history."""

    def __init__(self, name: str, seed: int, width: int, height: int) -> None:
        self.name = name
        self.seed = seed
        self.width = width
        self.height = height
        self.tiles: List[List[WorldTile]] = [
            [WorldTile() for _ in range(width)] for _ in range(height)
        ]
        self.regions: List[Region] = []
        self.civs: List[Any] = []
        self.sites: List[Any] = []
        self.figures: Dict[int, Any] = {}
        self.events: List[Any] = []
        self.artifacts: List[Any] = []
        self.year = 125
        self.history_years = 0
        self._next_hf = 1
        self._next_event = 1
        self._next_site = 1
        self._next_artifact = 1

    # -- access ------------------------------------------------------------ #

    def tile(self, x: int, y: int) -> WorldTile:
        """The tile at ``(x, y)``, clamped to the map."""
        x = max(0, min(self.width - 1, x))
        y = max(0, min(self.height - 1, y))
        return self.tiles[y][x]

    def in_bounds(self, x: int, y: int) -> bool:
        """True if ``(x, y)`` lies on the map."""
        return 0 <= x < self.width and 0 <= y < self.height

    def biome_at(self, x: int, y: int) -> str:
        """Biome id at a location."""
        return self.tile(x, y).biome

    def site_at(self, x: int, y: int) -> Optional[Any]:
        """The site at a location, if any."""
        sid = self.tile(x, y).site_id
        if sid is None:
            return None
        return self.site(sid)

    def site(self, sid: int) -> Optional[Any]:
        """Look up a site by id."""
        for s in self.sites:
            if s.id == sid:
                return s
        return None

    def civ(self, cid: int) -> Optional[Any]:
        """Look up a civilization by id."""
        for c in self.civs:
            if c.id == cid:
                return c
        return None

    def figure(self, hf_id: int) -> Optional[Any]:
        """Look up a historical figure by id."""
        return self.figures.get(hf_id)

    def artifact(self, aid: int) -> Optional[Any]:
        """Look up an artifact by id."""
        for a in self.artifacts:
            if a.id == aid:
                return a
        return None

    def region_at(self, x: int, y: int) -> Optional[Region]:
        """The region containing a location."""
        rid = self.tile(x, y).region_id
        for r in self.regions:
            if r.id == rid:
                return r
        return self.regions[0] if self.regions else None

    def neighbours(self, x: int, y: int) -> List[Tuple[int, int]]:
        """The eight surrounding world tiles that exist."""
        out = []
        for dx, dy in ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1),
                       (-1, 0), (-1, -1)):
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny):
                out.append((nx, ny))
        return out

    def travel_cost(self, x: int, y: int) -> float:
        """How long crossing a tile takes, relative to open grassland."""
        t = self.tile(x, y)
        b = biome_data.get(t.biome)
        cost = b.travel_cost
        if t.river:
            cost += 0.6
        if t.site_id is not None:
            cost *= 0.7
        cost *= 1.0 + max(0.0, t.elevation - SEA_LEVEL) * 0.8
        return max(0.4, cost)

    def land_tiles(self) -> List[Tuple[int, int]]:
        """Every non-ocean coordinate."""
        return [
            (x, y)
            for y in range(self.height)
            for x in range(self.width)
            if not self.tiles[y][x].is_ocean
        ]

    def next_id(self, kind: str) -> int:
        """Allocate the next id for figures, events, sites or artifacts."""
        if kind == "hf":
            self._next_hf += 1
            return self._next_hf - 1
        if kind == "event":
            self._next_event += 1
            return self._next_event - 1
        if kind == "site":
            self._next_site += 1
            return self._next_site - 1
        self._next_artifact += 1
        return self._next_artifact - 1

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the entire world."""
        from .civ import Civilization, Site
        from .history import Artifact, HistoricalEvent, HistoricalFigure

        return {
            "name": self.name,
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "year": self.year,
            "history_years": self.history_years,
            "tiles": [[t.to_dict() for t in row] for row in self.tiles],
            "regions": [r.to_dict() for r in self.regions],
            "civs": [c.to_dict() for c in self.civs],
            "sites": [s.to_dict() for s in self.sites],
            "figures": {str(k): v.to_dict() for k, v in self.figures.items()},
            "events": [e.to_dict() for e in self.events],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "counters": [
                self._next_hf, self._next_event, self._next_site,
                self._next_artifact,
            ],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "World":
        """Rebuild a world from :meth:`to_dict`."""
        from .civ import Civilization, Site
        from .history import Artifact, HistoricalEvent, HistoricalFigure

        w = cls(str(d["name"]), int(d["seed"]), int(d["width"]), int(d["height"]))
        w.year = int(d.get("year", 125))
        w.history_years = int(d.get("history_years", 0))
        w.tiles = [
            [WorldTile.from_dict(t) for t in row] for row in d.get("tiles", [])
        ]
        w.regions = [Region.from_dict(r) for r in d.get("regions", [])]
        w.civs = [Civilization.from_dict(c) for c in d.get("civs", [])]
        w.sites = [Site.from_dict(s) for s in d.get("sites", [])]
        w.figures = {
            int(k): HistoricalFigure.from_dict(v)
            for k, v in (d.get("figures") or {}).items()
        }
        w.events = [HistoricalEvent.from_dict(e) for e in d.get("events", [])]
        w.artifacts = [Artifact.from_dict(a) for a in d.get("artifacts", [])]
        counters = d.get("counters") or [1, 1, 1, 1]
        (w._next_hf, w._next_event, w._next_site, w._next_artifact) = (
            int(counters[0]), int(counters[1]), int(counters[2]), int(counters[3])
        )
        return w

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "World(%r, %dx%d, seed=%d)" % (
            self.name, self.width, self.height, self.seed
        )


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #


def _report(progress: Progress, label: str, frac: float) -> None:
    if progress is not None:
        progress(label, max(0.0, min(1.0, frac)))


def _make_elevation(rng: RNG, w: int, h: int) -> List[List[float]]:
    """Continental heightmap: fbm plus a radial falloff so land is centred."""
    noise = ValueNoise(rng.sub("elevation"))
    detail = ValueNoise(rng.sub("elevation-detail"))
    grid = [[0.0] * w for _ in range(h)]
    scale = 3.4 / max(w, h)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    max_r = math.hypot(cx, cy)
    for y in range(h):
        for x in range(w):
            base = noise.fbm(x * scale, y * scale, 6, 2.0, 0.52)
            ridge = detail.ridged(x * scale * 2.1, y * scale * 2.1, 4)
            value = 0.5 + base * 0.42 + (ridge - 0.5) * 0.24
            # Push the edges of the map underwater so continents have coasts.
            r = math.hypot(x - cx, y - cy) / max_r
            value -= max(0.0, (r - 0.55)) ** 1.7 * 1.5
            grid[y][x] = value
    normalize_grid(grid)
    smooth_grid(grid, 1)
    erode(grid, rng.sub("erosion"), w * h * 6)
    normalize_grid(grid)
    return grid


def _make_climate(
    rng: RNG, world: World, elevation: List[List[float]]
) -> None:
    """Temperature, rainfall, drainage and volcanism."""
    w, h = world.width, world.height
    rain_noise = ValueNoise(rng.sub("rain"))
    drain_noise = ValueNoise(rng.sub("drainage"))
    volc_noise = ValueNoise(rng.sub("volcanism"))
    scale = 4.0 / max(w, h)

    for y in range(h):
        # Latitude: 0 at the poles, 1 at the equator.
        lat = 1.0 - abs((y / max(1.0, h - 1.0)) * 2.0 - 1.0)
        for x in range(w):
            t = world.tiles[y][x]
            e = elevation[y][x]
            t.elevation = e
            t.is_ocean = e < SEA_LEVEL

            altitude = max(0.0, e - SEA_LEVEL) / (1.0 - SEA_LEVEL)
            temp = 8.0 + lat * 92.0 - altitude * 55.0
            temp += rain_noise.noise2(x * scale * 0.7, y * scale * 0.7) * 8.0
            t.temperature = max(-30.0, min(110.0, temp))

            # Orographic rainfall: wet near the sea, dry in rain shadows.
            base_rain = 0.5 + rain_noise.fbm(x * scale, y * scale, 5) * 0.42
            base_rain += (1.0 - abs(lat - 0.5) * 2.0) * 0.10
            base_rain -= altitude * 0.20
            t.rainfall = max(0.0, min(1.0, base_rain))

            t.drainage = max(0.0, min(1.0, 0.5 + drain_noise.fbm(
                x * scale * 1.6, y * scale * 1.6, 4) * 0.5))
            v = volc_noise.ridged(x * scale * 1.3, y * scale * 1.3, 3)
            t.volcanism = max(0.0, (v - 0.55) / 0.45) if v > 0.55 else 0.0

    # Coastal tiles get more rain; deep inland gets less.
    for y in range(h):
        for x in range(w):
            t = world.tiles[y][x]
            if t.is_ocean:
                t.rainfall = 1.0
                continue
            sea_near = any(
                world.tiles[ny][nx].is_ocean for nx, ny in world.neighbours(x, y)
            )
            if sea_near:
                t.rainfall = min(1.0, t.rainfall + 0.12)


def _carve_rivers(rng: RNG, world: World) -> None:
    """Trace rivers downhill from wet highlands to the sea."""
    w, h = world.width, world.height
    candidates: List[Tuple[float, int, int]] = []
    for y in range(h):
        for x in range(w):
            t = world.tiles[y][x]
            if t.is_ocean or t.elevation < 0.62:
                continue
            score = t.elevation * 0.6 + t.rainfall * 0.4
            candidates.append((score, x, y))
    candidates.sort(reverse=True)
    sources = candidates[: max(3, (w * h) // 220)]
    rng.shuffle(sources)

    for _score, sx, sy in sources[: max(2, len(sources) // 2)]:
        x, y = sx, sy
        flow = 1
        seen: Set[Tuple[int, int]] = set()
        for _step in range(w + h):
            if (x, y) in seen:
                break
            seen.add((x, y))
            tile = world.tiles[y][x]
            if tile.is_ocean:
                break
            tile.river = max(tile.river, flow)
            flow += 1
            # Flow to the lowest neighbour.
            best = None
            best_e = tile.elevation
            for nx, ny in world.neighbours(x, y):
                nt = world.tiles[ny][nx]
                if nt.elevation < best_e:
                    best, best_e = (nx, ny), nt.elevation
            if best is None:
                # A basin: make a lake and stop.
                if not tile.is_ocean and tile.elevation > SEA_LEVEL:
                    tile.is_lake = True
                break
            dx, dy = best[0] - x, best[1] - y
            tile.river_dir = _dir_index(dx, dy)
            x, y = best

    # River tiles are wetter and better drained.
    for y in range(h):
        for x in range(w):
            t = world.tiles[y][x]
            if t.river:
                t.rainfall = min(1.0, t.rainfall + 0.10)


def _dir_index(dx: int, dy: int) -> int:
    """Pack a unit direction into 0..7, or -1."""
    dirs = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
    try:
        return dirs.index((dx, dy))
    except ValueError:
        return -1


def _assign_biomes(world: World) -> None:
    """Classify every tile and mark beaches and volcanoes."""
    for y in range(world.height):
        for x in range(world.width):
            t = world.tiles[y][x]
            if t.is_lake:
                t.biome = "lake"
                continue
            t.biome = biome_data.classify(
                t.elevation, t.rainfall, t.temperature, t.drainage,
                is_water=t.is_ocean,
            )
            if not t.is_ocean:
                if t.river and t.biome not in ("mountain", "glacier"):
                    if t.rainfall > 0.55 and t.drainage < 0.4:
                        t.biome = "marsh"
                if t.volcanism > 0.72 and t.elevation > 0.7:
                    t.biome = "volcano"
                elif t.elevation < SEA_LEVEL + 0.035 and t.temperature > 15:
                    near_sea = any(
                        world.tiles[ny][nx].is_ocean
                        for nx, ny in world.neighbours(x, y)
                    )
                    if near_sea:
                        t.biome = "beach"


def _build_regions(rng: RNG, world: World) -> None:
    """Flood-fill contiguous same-biome areas into named regions."""
    w, h = world.width, world.height
    seen = [[False] * w for _ in range(h)]
    rid = 0
    for y in range(h):
        for x in range(w):
            if seen[y][x]:
                continue
            biome = world.tiles[y][x].biome
            stack = [(x, y)]
            cells: List[Tuple[int, int]] = []
            seen[y][x] = True
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for nx, ny in world.neighbours(cx, cy):
                    if not seen[ny][nx] and world.tiles[ny][nx].biome == biome:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if len(cells) < 6 and rid > 0:
                # Fold slivers into the region next door so the map is not
                # a confetti of one-tile "regions".
                merged = False
                for cx, cy in cells:
                    for nx, ny in world.neighbours(cx, cy):
                        other = world.tiles[ny][nx].region_id
                        if other and other != 0:
                            target = next(
                                (r for r in world.regions if r.id == other), None
                            )
                            if target is not None:
                                target.tiles.extend(cells)
                                for ax, ay in cells:
                                    world.tiles[ay][ax].region_id = other
                                merged = True
                                break
                    if merged:
                        break
                if merged:
                    continue
            rid += 1
            region = Region(rid, name_data.region_name(rng, biome), biome)
            region.tiles = cells
            savagery = sum(world.tiles[cy][cx].savagery for cx, cy in cells)
            savagery //= max(1, len(cells))
            evil = sum(world.tiles[cy][cx].evil for cx, cy in cells)
            evil //= max(1, len(cells))
            region.savagery = biome_data.savagery_name(savagery)
            region.evil = biome_data.alignment_name(evil)
            for cx, cy in cells:
                world.tiles[cy][cx].region_id = rid
            world.regions.append(region)


def _assign_alignment(rng: RNG, world: World) -> None:
    """Scatter savagery and good/evil across the map."""
    noise_s = ValueNoise(rng.sub("savagery"))
    noise_e = ValueNoise(rng.sub("evil"))
    scale = 5.0 / max(world.width, world.height)
    for y in range(world.height):
        for x in range(world.width):
            t = world.tiles[y][x]
            b = biome_data.get(t.biome)
            s = 50 + noise_s.fbm(x * scale, y * scale, 4) * 60 + b.savagery_bias
            e = 50 + noise_e.fbm(x * scale + 40, y * scale + 40, 3) * 70
            if b.has("EVIL"):
                e += 25
            if b.has("GOOD"):
                e -= 25
            t.savagery = max(0, min(100, int(s)))
            t.evil = max(0, min(100, int(e)))


def generate_world(
    rng: RNG,
    *,
    size: str = "medium",
    name: str = "",
    history_years: int = 120,
    progress: Progress = None,
) -> World:
    """Generate a complete world with geography, peoples and history."""
    from . import civ as civ_mod
    from . import history as history_mod

    dim = WORLD_SIZES.get(size, WORLD_SIZES["medium"])
    if not name:
        name = name_data.civ_name(rng.sub("worldname"), "dwarf")[1]
    world = World(name, rng.seed, dim, dim)

    _report(progress, "Shaping the land", 0.02)
    elevation = _make_elevation(rng, dim, dim)

    _report(progress, "Setting the seasons", 0.20)
    _make_climate(rng, world, elevation)

    _report(progress, "Running the rivers", 0.32)
    _carve_rivers(rng, world)

    _report(progress, "Growing the forests", 0.42)
    _assign_biomes(world)
    _assign_alignment(rng, world)
    _assign_biomes(world)

    _report(progress, "Naming the regions", 0.52)
    _build_regions(rng, world)

    _report(progress, "Raising civilizations", 0.60)
    civ_mod.place_civilizations(world, rng, progress)

    _report(progress, "Recording history", 0.72)
    history_mod.simulate(world, rng, history_years, progress)

    _report(progress, "The world is ready", 1.0)
    return world


def world_hash(world: World) -> str:
    """A short stable digest of a world's geography, used by tests."""
    import hashlib

    h = hashlib.blake2b(digest_size=8)
    for row in world.tiles:
        for t in row:
            h.update(("%s%d%d" % (t.biome, int(t.elevation * 1000), t.river)).encode())
    return h.hexdigest()


def summarize(world: World) -> List[str]:
    """Human-readable statistics about a generated world."""
    counts: Dict[str, int] = {}
    ocean = 0
    for row in world.tiles:
        for t in row:
            counts[t.biome] = counts.get(t.biome, 0) + 1
            if t.is_ocean:
                ocean += 1
    total = world.width * world.height
    lines = [
        "%s - %dx%d, seed %d" % (world.name, world.width, world.height, world.seed),
        "Year %d, %d years of history" % (world.year, world.history_years),
        "%d%% ocean, %d regions, %d civilizations, %d sites"
        % (ocean * 100 // total, len(world.regions), len(world.civs),
           len(world.sites)),
        "%d historical figures, %d events, %d artifacts"
        % (len(world.figures), len(world.events), len(world.artifacts)),
    ]
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:8]
    lines.append(
        "Terrain: " + ", ".join(
            "%s %d%%" % (biome_data.get(b).name, n * 100 // total) for b, n in top
        )
    )
    return lines
