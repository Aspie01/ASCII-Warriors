"""Field of view by recursive shadowcasting."""

from __future__ import annotations

import math
from typing import Callable, List, Set, Tuple

# (xx, xy, yx, yy) transforms for the eight octants.
_OCTANTS: Tuple[Tuple[int, int, int, int], ...] = (
    (1, 0, 0, 1), (0, 1, 1, 0), (0, -1, 1, 0), (-1, 0, 0, 1),
    (-1, 0, 0, -1), (0, -1, -1, 0), (0, 1, -1, 0), (1, 0, 0, -1),
)


def compute_fov(
    ox: int,
    oy: int,
    radius: int,
    blocks: Callable[[int, int], bool],
    visit: Callable[[int, int, float], None],
    *,
    light_walls: bool = True,
) -> None:
    """Visit every cell visible from ``(ox, oy)`` within *radius*.

    *visit* receives ``(x, y, intensity)`` where intensity falls from 1.0 at the
    origin to roughly 0.0 at the edge of the radius.
    """
    visit(ox, oy, 1.0)
    if radius <= 0:
        return
    for xx, xy, yx, yy in _OCTANTS:
        _cast(ox, oy, 1, 1.0, 0.0, radius, xx, xy, yx, yy, blocks, visit, light_walls)


def _cast(
    ox: int,
    oy: int,
    row: int,
    start_slope: float,
    end_slope: float,
    radius: int,
    xx: int,
    xy: int,
    yx: int,
    yy: int,
    blocks: Callable[[int, int], bool],
    visit: Callable[[int, int, float], None],
    light_walls: bool,
) -> None:
    """Recursively scan one octant row by row, narrowing the visible slope span."""
    if start_slope < end_slope:
        return
    radius2 = radius * radius
    blocked = False
    new_start = start_slope
    for distance in range(row, radius + 1):
        if blocked:
            break
        dy = -distance
        for dx in range(-distance, 1):
            l_slope = (dx - 0.5) / (dy + 0.5)
            r_slope = (dx + 0.5) / (dy - 0.5)
            if start_slope < r_slope:
                continue
            if end_slope > l_slope:
                break
            sax = dx * xx + dy * xy
            say = dx * yx + dy * yy
            cx = ox + sax
            cy = oy + say
            d2 = sax * sax + say * say
            wall = blocks(cx, cy)
            if d2 <= radius2:
                if not wall or light_walls:
                    intensity = 1.0 - (math.sqrt(d2) / (radius + 1.0))
                    visit(cx, cy, max(0.0, min(1.0, intensity)))
            if blocked:
                if wall:
                    new_start = r_slope
                    continue
                blocked = False
                start_slope = new_start
            elif wall and distance < radius:
                blocked = True
                _cast(
                    ox, oy, distance + 1, start_slope, l_slope, radius,
                    xx, xy, yx, yy, blocks, visit, light_walls,
                )
                new_start = r_slope


def fov_set(
    ox: int, oy: int, radius: int, blocks: Callable[[int, int], bool]
) -> Set[Tuple[int, int]]:
    """Convenience wrapper returning the set of visible cells."""
    out: Set[Tuple[int, int]] = set()

    def visit(x: int, y: int, _i: float) -> None:
        out.add((x, y))

    compute_fov(ox, oy, radius, blocks, visit)
    return out


def has_los(
    x0: int, y0: int, x1: int, y1: int, blocks: Callable[[int, int], bool]
) -> bool:
    """True if a straight line from the first point to the second is unobstructed.

    Endpoints are never treated as blockers, so you can always see the wall (or
    creature) you are looking at.
    """
    if x0 == x1 and y0 == y1:
        return True
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        if x == x1 and y == y1:
            return True
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
        if x == x1 and y == y1:
            return True
        if blocks(x, y):
            return False


def line_of_fire(
    x0: int, y0: int, x1: int, y1: int, blocks: Callable[[int, int], bool]
) -> List[Tuple[int, int]]:
    """The trajectory from origin to target, stopping at the first blocker.

    The blocking cell itself is included — that is where the projectile lands.
    """
    path: List[Tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        if (x, y) != (x0, y0):
            path.append((x, y))
            if blocks(x, y):
                return path
        if x == x1 and y == y1:
            return path
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy
