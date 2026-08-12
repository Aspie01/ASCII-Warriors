"""Coherent noise and heightmap generation for world building."""

from __future__ import annotations

import math
from typing import List, Sequence

from .rng import RNG

_GRAD2 = (
    (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0),
    (0.7071, 0.7071), (-0.7071, 0.7071), (0.7071, -0.7071), (-0.7071, -0.7071),
)


def _fade(t: float) -> float:
    """Quintic smoothstep, the standard Perlin interpolant."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


class ValueNoise:
    """Gradient (Perlin-style) noise with fBm, ridged and billow variants."""

    __slots__ = ("_perm",)

    def __init__(self, rng: RNG) -> None:
        table = list(range(256))
        rng.shuffle(table)
        self._perm = table + table

    def noise2(self, x: float, y: float) -> float:
        """Gradient noise at ``(x, y)`` in roughly ``[-1, 1]``."""
        xi = int(math.floor(x)) & 255
        yi = int(math.floor(y)) & 255
        xf = x - math.floor(x)
        yf = y - math.floor(y)
        u = _fade(xf)
        v = _fade(yf)
        p = self._perm

        aa = p[p[xi] + yi]
        ab = p[p[xi] + yi + 1]
        ba = p[p[xi + 1] + yi]
        bb = p[p[xi + 1] + yi + 1]

        def dot(h: int, dx: float, dy: float) -> float:
            gx, gy = _GRAD2[h & 7]
            return gx * dx + gy * dy

        x1 = dot(aa, xf, yf) + u * (dot(ba, xf - 1.0, yf) - dot(aa, xf, yf))
        x2 = dot(ab, xf, yf - 1.0) + u * (
            dot(bb, xf - 1.0, yf - 1.0) - dot(ab, xf, yf - 1.0)
        )
        return max(-1.0, min(1.0, (x1 + v * (x2 - x1)) * 1.4))

    def fbm(
        self,
        x: float,
        y: float,
        octaves: int = 5,
        lacunarity: float = 2.0,
        gain: float = 0.5,
    ) -> float:
        """Fractal Brownian motion; result normalised to ``[-1, 1]``."""
        total = 0.0
        amp = 1.0
        freq = 1.0
        norm = 0.0
        for _ in range(max(1, octaves)):
            total += self.noise2(x * freq, y * freq) * amp
            norm += amp
            amp *= gain
            freq *= lacunarity
        return total / norm if norm else 0.0

    def ridged(self, x: float, y: float, octaves: int = 5) -> float:
        """Ridged multifractal noise in ``[0, 1]`` — good for mountain spines."""
        total = 0.0
        amp = 1.0
        freq = 1.0
        norm = 0.0
        for _ in range(max(1, octaves)):
            n = 1.0 - abs(self.noise2(x * freq, y * freq))
            total += n * n * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return max(0.0, min(1.0, total / norm if norm else 0.0))

    def billow(self, x: float, y: float, octaves: int = 5) -> float:
        """Billowy noise in ``[0, 1]`` — good for clouds and rolling hills."""
        total = 0.0
        amp = 1.0
        freq = 1.0
        norm = 0.0
        for _ in range(max(1, octaves)):
            total += abs(self.noise2(x * freq, y * freq)) * amp
            norm += amp
            amp *= 0.5
            freq *= 2.0
        return max(0.0, min(1.0, total / norm if norm else 0.0))

    def domain_warp(self, x: float, y: float, strength: float = 4.0) -> float:
        """fBm sampled through a warped domain, which breaks up grid artefacts."""
        wx = self.fbm(x + 5.2, y + 1.3, 3)
        wy = self.fbm(x + 9.7, y + 4.1, 3)
        return self.fbm(x + strength * wx, y + strength * wy, 5)


class DiamondSquare:
    """Classic diamond-square heightmap generator producing plausible landmasses."""

    __slots__ = ("rng", "size")

    def __init__(self, rng: RNG, size_exp: int) -> None:
        self.rng = rng
        #: Grid edge length, always ``2**size_exp + 1``.
        self.size = (1 << max(1, size_exp)) + 1

    def generate(self, roughness: float = 0.55) -> List[List[float]]:
        """Generate a ``size`` x ``size`` grid normalised to ``[0, 1]``."""
        n = self.size
        grid = [[0.0] * n for _ in range(n)]
        rng = self.rng
        grid[0][0] = rng.uniform(0.0, 1.0)
        grid[0][n - 1] = rng.uniform(0.0, 1.0)
        grid[n - 1][0] = rng.uniform(0.0, 1.0)
        grid[n - 1][n - 1] = rng.uniform(0.0, 1.0)

        step = n - 1
        scale = 1.0
        while step > 1:
            half = step // 2
            for y in range(0, n - 1, step):
                for x in range(0, n - 1, step):
                    avg = (
                        grid[y][x]
                        + grid[y][x + step]
                        + grid[y + step][x]
                        + grid[y + step][x + step]
                    ) * 0.25
                    grid[y + half][x + half] = avg + rng.uniform(-scale, scale)
            for y in range(0, n, half):
                start = half if (y // half) % 2 == 0 else 0
                for x in range(start, n, step):
                    total = 0.0
                    count = 0
                    for dx, dy in ((0, -half), (0, half), (-half, 0), (half, 0)):
                        px, py = x + dx, y + dy
                        if 0 <= px < n and 0 <= py < n:
                            total += grid[py][px]
                            count += 1
                    if count:
                        grid[y][x] = total / count + rng.uniform(-scale, scale)
            step = half
            scale *= roughness
        normalize_grid(grid)
        return grid


def normalize_grid(grid: List[List[float]]) -> None:
    """Rescale a grid in place so its values span ``[0, 1]``."""
    if not grid or not grid[0]:
        return
    lo = min(min(row) for row in grid)
    hi = max(max(row) for row in grid)
    span = hi - lo
    if span <= 1e-12:
        for row in grid:
            for i in range(len(row)):
                row[i] = 0.5
        return
    inv = 1.0 / span
    for row in grid:
        for i in range(len(row)):
            row[i] = (row[i] - lo) * inv


def smooth_grid(grid: List[List[float]], passes: int = 1) -> None:
    """Box-blur a grid in place."""
    if not grid or not grid[0]:
        return
    h = len(grid)
    w = len(grid[0])
    for _ in range(max(0, passes)):
        src = [row[:] for row in grid]
        for y in range(h):
            for x in range(w):
                total = 0.0
                count = 0
                for dy in (-1, 0, 1):
                    yy = y + dy
                    if yy < 0 or yy >= h:
                        continue
                    srow = src[yy]
                    for dx in (-1, 0, 1):
                        xx = x + dx
                        if 0 <= xx < w:
                            total += srow[xx]
                            count += 1
                grid[y][x] = total / count


def erode(grid: List[List[float]], rng: RNG, iterations: int = 40000) -> None:
    """Cheap droplet erosion, in place.

    Each droplet walks downhill, carving a little material and depositing it
    where the slope flattens. It makes coastlines and valleys read as natural.
    """
    if not grid or not grid[0]:
        return
    h = len(grid)
    w = len(grid[0])
    if w < 4 or h < 4:
        return
    neigh = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    for _ in range(max(0, iterations)):
        x = rng.randint(1, w - 2)
        y = rng.randint(1, h - 2)
        sediment = 0.0
        for _step in range(24):
            here = grid[y][x]
            bx, by, best = x, y, here
            for dx, dy in neigh:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and grid[ny][nx] < best:
                    bx, by, best = nx, ny, grid[ny][nx]
            if bx == x and by == y:
                grid[y][x] = min(1.0, here + sediment * 0.5)
                break
            drop = (here - best) * 0.30
            grid[y][x] = here - drop
            sediment += drop
            x, y = bx, by
        else:
            grid[y][x] = min(1.0, grid[y][x] + sediment * 0.25)


def grid_from_noise(
    noise: ValueNoise,
    width: int,
    height: int,
    scale: float = 0.05,
    octaves: int = 6,
) -> List[List[float]]:
    """Sample fBm into a ``height`` x ``width`` grid normalised to ``[0, 1]``."""
    grid = [
        [noise.fbm(x * scale, y * scale, octaves) for x in range(width)]
        for y in range(height)
    ]
    normalize_grid(grid)
    return grid


def blend_grids(
    a: Sequence[Sequence[float]], b: Sequence[Sequence[float]], t: float
) -> List[List[float]]:
    """Element-wise linear blend of two equally shaped grids."""
    return [
        [av + (bv - av) * t for av, bv in zip(arow, brow)] for arow, brow in zip(a, b)
    ]
