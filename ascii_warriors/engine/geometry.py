"""Points, rectangles, lines and grid helpers.

Screen/world coordinates use ``+x`` east and ``+y`` south. Z increases upward, so
``z+1`` is the level above (this matches "look up the stairs", not screen rows).
"""

from __future__ import annotations

import math
from typing import Callable, Iterable, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple


class Point(NamedTuple):
    """An integer 2D grid point."""

    x: int
    y: int

    def __add__(self, other):  # type: ignore[override]
        return Point(self.x + other[0], self.y + other[1])

    def __sub__(self, other):  # type: ignore[override]
        return Point(self.x - other[0], self.y - other[1])


DIRS4: Tuple[Tuple[int, int], ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))
DIRS8: Tuple[Tuple[int, int], ...] = (
    (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1),
)

DIR_NAMES = {
    (0, -1): "north",
    (1, -1): "northeast",
    (1, 0): "east",
    (1, 1): "southeast",
    (0, 1): "south",
    (-1, 1): "southwest",
    (-1, 0): "west",
    (-1, -1): "northwest",
    (0, 0): "here",
}

DIR_ABBREV = {
    "north": "N", "northeast": "NE", "east": "E", "southeast": "SE",
    "south": "S", "southwest": "SW", "west": "W", "northwest": "NW", "here": "-",
}


class Rect:
    """An axis-aligned rectangle with an inclusive-exclusive extent."""

    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x = int(x)
        self.y = int(y)
        self.w = max(0, int(w))
        self.h = max(0, int(h))

    # -- derived ----------------------------------------------------------- #

    @property
    def x2(self) -> int:
        """One past the right edge."""
        return self.x + self.w

    @property
    def y2(self) -> int:
        """One past the bottom edge."""
        return self.y + self.h

    @property
    def center(self) -> Point:
        """The centre cell."""
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    @property
    def area(self) -> int:
        """Cell count."""
        return self.w * self.h

    def as_tuple(self) -> Tuple[int, int, int, int]:
        """``(x, y, w, h)``."""
        return (self.x, self.y, self.w, self.h)

    # -- queries ----------------------------------------------------------- #

    def contains(self, x: int, y: int) -> bool:
        """True if ``(x, y)`` lies inside."""
        return self.x <= x < self.x2 and self.y <= y < self.y2

    def intersects(self, other: "Rect") -> bool:
        """True if the two rectangles overlap in at least one cell."""
        return (
            self.x < other.x2 and other.x < self.x2
            and self.y < other.y2 and other.y < self.y2
        )

    def expand(self, n: int) -> "Rect":
        """A copy grown by *n* cells on every side (may shrink for negative *n*)."""
        return Rect(self.x - n, self.y - n, self.w + 2 * n, self.h + 2 * n)

    def clamp_point(self, x: int, y: int) -> Point:
        """The nearest point inside the rectangle."""
        if self.w <= 0 or self.h <= 0:
            return Point(self.x, self.y)
        return Point(
            max(self.x, min(self.x2 - 1, x)),
            max(self.y, min(self.y2 - 1, y)),
        )

    def cells(self) -> Iterator[Point]:
        """Every cell, row by row."""
        for yy in range(self.y, self.y2):
            for xx in range(self.x, self.x2):
                yield Point(xx, yy)

    def border(self) -> Iterator[Point]:
        """The one-cell-thick outline."""
        if self.w <= 0 or self.h <= 0:
            return
        for xx in range(self.x, self.x2):
            yield Point(xx, self.y)
            if self.h > 1:
                yield Point(xx, self.y2 - 1)
        for yy in range(self.y + 1, self.y2 - 1):
            yield Point(self.x, yy)
            if self.w > 1:
                yield Point(self.x2 - 1, yy)

    def inner(self, pad: int = 1) -> "Rect":
        """The rectangle inset by *pad* on every side."""
        return self.expand(-pad)

    # -- subdivision (BSP helpers) ----------------------------------------- #

    def split_h(self, at: int) -> Tuple["Rect", "Rect"]:
        """Split into top/bottom halves at absolute row *at*."""
        at = max(self.y, min(self.y2, at))
        return (
            Rect(self.x, self.y, self.w, at - self.y),
            Rect(self.x, at, self.w, self.y2 - at),
        )

    def split_v(self, at: int) -> Tuple["Rect", "Rect"]:
        """Split into left/right halves at absolute column *at*."""
        at = max(self.x, min(self.x2, at))
        return (
            Rect(self.x, self.y, at - self.x, self.h),
            Rect(at, self.y, self.x2 - at, self.h),
        )

    def random_sub(self, rng, min_w: int = 3, min_h: int = 3) -> "Rect":
        """A random sub-rectangle at least ``min_w`` x ``min_h`` in size."""
        w = rng.randint(min(min_w, self.w), max(min_w, self.w))
        h = rng.randint(min(min_h, self.h), max(min_h, self.h))
        w = min(w, self.w)
        h = min(h, self.h)
        x = rng.randint(self.x, max(self.x, self.x2 - w))
        y = rng.randint(self.y, max(self.y, self.y2 - h))
        return Rect(x, y, w, h)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rect):
            return NotImplemented
        return self.as_tuple() == other.as_tuple()

    def __hash__(self) -> int:
        return hash(self.as_tuple())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Rect(%d, %d, %d, %d)" % (self.x, self.y, self.w, self.h)


def rect_of_points(points: Iterable[Tuple[int, int]]) -> Rect:
    """The smallest :class:`Rect` covering every point (empty rect if none)."""
    pts = list(points)
    if not pts:
        return Rect(0, 0, 0, 0)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


# --------------------------------------------------------------------------- #
# Lines and shapes
# --------------------------------------------------------------------------- #


def line(x0: int, y0: int, x1: int, y1: int) -> List[Point]:
    """Bresenham line from ``(x0, y0)`` to ``(x1, y1)``, both endpoints included."""
    points: List[Point] = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        points.append(Point(x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
    return points


def bresenham_3d(
    x0: int, y0: int, z0: int, x1: int, y1: int, z1: int
) -> List[Tuple[int, int, int]]:
    """A 3D Bresenham line, both endpoints included."""
    points: List[Tuple[int, int, int]] = []
    dx, dy, dz = abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)
    sx = 1 if x1 > x0 else -1
    sy = 1 if y1 > y0 else -1
    sz = 1 if z1 > z0 else -1
    x, y, z = x0, y0, z0

    if dx >= dy and dx >= dz:
        p1 = 2 * dy - dx
        p2 = 2 * dz - dx
        for _ in range(dx + 1):
            points.append((x, y, z))
            if p1 >= 0:
                y += sy
                p1 -= 2 * dx
            if p2 >= 0:
                z += sz
                p2 -= 2 * dx
            p1 += 2 * dy
            p2 += 2 * dz
            x += sx
    elif dy >= dx and dy >= dz:
        p1 = 2 * dx - dy
        p2 = 2 * dz - dy
        for _ in range(dy + 1):
            points.append((x, y, z))
            if p1 >= 0:
                x += sx
                p1 -= 2 * dy
            if p2 >= 0:
                z += sz
                p2 -= 2 * dy
            p1 += 2 * dx
            p2 += 2 * dz
            y += sy
    else:
        p1 = 2 * dy - dz
        p2 = 2 * dx - dz
        for _ in range(dz + 1):
            points.append((x, y, z))
            if p1 >= 0:
                y += sy
                p1 -= 2 * dz
            if p2 >= 0:
                x += sx
                p2 -= 2 * dz
            p1 += 2 * dy
            p2 += 2 * dx
            z += sz
    if points[-1] != (x1, y1, z1):
        points.append((x1, y1, z1))
    return points


def circle(cx: int, cy: int, r: int) -> List[Point]:
    """Every cell within Euclidean radius *r* of the centre."""
    out: List[Point] = []
    r2 = r * r
    for yy in range(cy - r, cy + r + 1):
        for xx in range(cx - r, cx + r + 1):
            dx, dy = xx - cx, yy - cy
            if dx * dx + dy * dy <= r2:
                out.append(Point(xx, yy))
    return out


def ring(cx: int, cy: int, r: int) -> List[Point]:
    """The outline of a circle of radius *r*."""
    if r <= 0:
        return [Point(cx, cy)]
    out: Set[Point] = set()
    r2_out = (r + 0.5) ** 2
    r2_in = (r - 0.5) ** 2
    for yy in range(cy - r, cy + r + 1):
        for xx in range(cx - r, cx + r + 1):
            dx, dy = xx - cx, yy - cy
            d2 = dx * dx + dy * dy
            if r2_in <= d2 <= r2_out:
                out.add(Point(xx, yy))
    return sorted(out, key=lambda p: math.atan2(p.y - cy, p.x - cx))


def spiral(cx: int, cy: int, max_r: int) -> Iterator[Point]:
    """Cells in expanding rings around a centre, nearest first."""
    yield Point(cx, cy)
    for r in range(1, max_r + 1):
        for p in ring(cx, cy, r):
            yield p


def flood_fill(
    start: Tuple[int, int],
    passable: Callable[[int, int], bool],
    max_cells: int = 100000,
    dirs: Sequence[Tuple[int, int]] = DIRS4,
) -> Set[Point]:
    """Every cell reachable from *start* through cells where *passable* is true."""
    sx, sy = start
    if not passable(sx, sy):
        return set()
    seen: Set[Point] = {Point(sx, sy)}
    stack = [Point(sx, sy)]
    while stack and len(seen) < max_cells:
        p = stack.pop()
        for dx, dy in dirs:
            q = Point(p.x + dx, p.y + dy)
            if q in seen:
                continue
            if passable(q.x, q.y):
                seen.add(q)
                stack.append(q)
    return seen


# --------------------------------------------------------------------------- #
# Distances and directions
# --------------------------------------------------------------------------- #


def chebyshev(x0: int, y0: int, x1: int, y1: int) -> int:
    """King-move distance."""
    return max(abs(x1 - x0), abs(y1 - y0))


def manhattan(x0: int, y0: int, x1: int, y1: int) -> int:
    """Taxicab distance."""
    return abs(x1 - x0) + abs(y1 - y0)


def euclid(x0: int, y0: int, x1: int, y1: int) -> float:
    """Straight-line distance."""
    dx, dy = x1 - x0, y1 - y0
    return math.sqrt(dx * dx + dy * dy)


def octile(x0: int, y0: int, x1: int, y1: int) -> float:
    """Diagonal-aware distance, the natural A* heuristic on an 8-way grid."""
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    return (dx + dy) + (math.sqrt(2.0) - 2.0) * min(dx, dy)


def normalize_dir(dx: int, dy: int) -> Tuple[int, int]:
    """Reduce an offset to one of the nine unit directions."""
    return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))


def direction_name(dx: int, dy: int) -> str:
    """Compass name for an offset, e.g. ``"southeast"``."""
    return DIR_NAMES.get(normalize_dir(dx, dy), "here")


def direction_abbrev(dx: int, dy: int) -> str:
    """Two-letter compass abbreviation for an offset."""
    return DIR_ABBREV.get(direction_name(dx, dy), "-")


def bearing_name(x0: int, y0: int, x1: int, y1: int) -> str:
    """The compass direction you would travel to get from one point to another."""
    return direction_name(x1 - x0, y1 - y0)


def neighbours8(x: int, y: int) -> Iterator[Point]:
    """The eight surrounding cells."""
    for dx, dy in DIRS8:
        yield Point(x + dx, y + dy)


def neighbours4(x: int, y: int) -> Iterator[Point]:
    """The four orthogonally adjacent cells."""
    for dx, dy in DIRS4:
        yield Point(x + dx, y + dy)


def clamp(v: int, lo: int, hi: int) -> int:
    """Clamp *v* to ``[lo, hi]``."""
    return lo if v < lo else (hi if v > hi else v)


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between two floats."""
    return a + (b - a) * t


def nearest_point(
    x: int, y: int, points: Iterable[Tuple[int, int]]
) -> Optional[Point]:
    """The closest point to ``(x, y)`` by Chebyshev distance, or ``None``."""
    best: Optional[Point] = None
    best_d = 1 << 30
    for px, py in points:
        d = chebyshev(x, y, px, py)
        if d < best_d:
            best, best_d = Point(px, py), d
    return best
