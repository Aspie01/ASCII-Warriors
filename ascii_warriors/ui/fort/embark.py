"""Choosing where to dig in.

The site you pick decides most of what happens next: whether there is water to
drink, wood to burn, and how much of the mountain is worth having.
"""

from __future__ import annotations

from typing import List, Tuple

from ...data import biomes as biome_data
from ...engine import colors, keys
from ...engine.screen import Screen
from ...engine.widgets import key_hint
from ..app import Scene


def site_score(world, x: int, y: int) -> float:
    """How promising a square looks. Higher is better.

    Running water outweighs everything else. A fortress with a river survives
    running out of ale; a fortress without one simply dies of it.
    """
    t = world.tile(x, y)
    if t.is_ocean or t.is_lake or t.site_id is not None:
        return -1e9
    score = t.elevation * 4.0
    score += t.rainfall * 1.5
    if t.river:
        score += 20.0
    if t.biome in ("forest", "taiga", "temperate_forest", "tropical_forest"):
        score += 2.0
    score -= abs(t.temperature - 50.0) / 40.0
    score -= t.savagery / 120.0
    return score


def suggest_site(world) -> Tuple[int, int]:
    """The best embark the map has to offer."""
    best = (world.width // 2, world.height // 2)
    best_score = -1e18
    for y in range(1, world.height - 1):
        for x in range(1, world.width - 1):
            s = site_score(world, x, y)
            if s > best_score:
                best, best_score = (x, y), s
    # The very edge of the world is scanned too: a river there is worth more
    # than dry hills in the middle.
    for y in range(world.height):
        for x in (0, world.width - 1):
            s = site_score(world, x, y)
            if s > best_score:
                best, best_score = (x, y), s
    for x in range(world.width):
        for y in (0, world.height - 1):
            s = site_score(world, x, y)
            if s > best_score:
                best, best_score = (x, y), s
    return best


class EmbarkScene(Scene):
    """Pick a square of the world and found a fortress on it."""

    def __init__(self, app, world, rng) -> None:
        super().__init__(app)
        self.world = world
        self.rng = rng
        self.cx, self.cy = suggest_site(world)
        self.cam_x = 0
        self.cam_y = 0

    # -- drawing ----------------------------------------------------------- #

    def draw(self, scr: Screen) -> None:
        """The world map with a cursor, and a report on the square under it."""
        scr.clear(colors.UI["bg"])
        panel = 34
        mw = max(20, scr.width - panel - 3)
        mh = max(10, scr.height - 4)
        self.cam_x = max(0, min(max(0, self.world.width - mw),
                                self.cx - mw // 2))
        self.cam_y = max(0, min(max(0, self.world.height - mh),
                                self.cy - mh // 2))
        scr.text(2, 0, "Where will you dig?", colors.UI["title"])
        self._draw_world(scr, 1, 1, mw, mh)
        self._draw_report(scr, scr.width - panel, 1, panel - 2)
        key_hint(scr, 2, scr.height - 1, [
            ("arrows", "move"), ("Enter", "embark here"),
            ("s", "suggest"), (keys.ESC, "back"),
        ])

    def _tile_glyph(self, x: int, y: int):
        """Glyph and colour for one world square."""
        t = self.world.tile(x, y)
        site = self.world.site_at(x, y)
        if site is not None:
            return site.glyph()
        if t.river and not t.is_ocean:
            return ("~", colors.Color(96, 150, 210))
        b = biome_data.get(t.biome)
        return (b.glyph, b.map_color)

    def _draw_world(self, scr: Screen, ox: int, oy: int, w: int, h: int) -> None:
        """The world map, coloured by biome."""
        world = self.world
        for sy in range(h):
            wy = self.cam_y + sy
            if wy >= world.height:
                break
            for sx in range(w):
                wx = self.cam_x + sx
                if wx >= world.width:
                    break
                glyph, fg = self._tile_glyph(wx, wy)
                scr.put(ox + sx, oy + sy, glyph, fg)
        sx, sy = self.cx - self.cam_x, self.cy - self.cam_y
        if 0 <= sx < w and 0 <= sy < h:
            ch, _fg, _bg = scr.get(ox + sx, oy + sy)
            scr.put(ox + sx, oy + sy, ch, colors.UI["bg"], colors.UI["accent"])

    def _draw_report(self, scr: Screen, x: int, y: int, w: int) -> None:
        """What we know about the square under the cursor."""
        world = self.world
        t = world.tile(self.cx, self.cy)
        row = y
        scr.text(x, row, "Site report", colors.UI["title"])
        row += 2
        region = world.region_at(self.cx, self.cy)
        if region is not None:
            scr.text(x, row, region.full_name[:w], colors.UI["accent"])
            row += 1
        scr.text(x, row, biome_data.get(t.biome).name[:w], colors.UI["fg"])
        row += 2

        rows: List[Tuple[str, str, object]] = [
            ("Elevation", _band(t.elevation, ("low", "rolling", "hilly",
                                              "mountainous")), None),
            ("Rainfall", _band(t.rainfall, ("arid", "dry", "damp", "wet")),
             None),
            ("Temperature", _temperature(t.temperature), None),
            ("Savagery", _band(t.savagery / 100.0,
                               ("calm", "settled", "wild", "savage")), None),
        ]
        for label, value, _ in rows:
            scr.text(x, row, "%-12s %s" % (label, value), colors.UI["fg"])
            row += 1
        row += 1

        water = "a river runs through it" if t.river else "no running water"
        scr.text(x, row, water[:w],
                 colors.UI["good"] if t.river else colors.UI["warn"])
        row += 1
        if t.is_ocean or t.is_lake:
            scr.text(x, row, "underwater", colors.UI["danger"])
            row += 1
        if t.site_id is not None:
            site = world.site(t.site_id)
            scr.text(x, row, "occupied: %s" % (
                site.name if site else "a settlement"), colors.UI["danger"])
            row += 1
        row += 1
        scr.wrapped(x, row, w, ADVICE, colors.UI["dim"])

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> None:
        """Move the cursor, or commit."""
        from .fort_screen import scroll_delta

        delta = scroll_delta(key)
        if delta is not None:
            self.cx = max(0, min(self.world.width - 1, self.cx + delta[0]))
            self.cy = max(0, min(self.world.height - 1, self.cy + delta[1]))
            return
        if key == keys.ESC:
            self.done = True
            return
        if key == "s":
            self.cx, self.cy = suggest_site(self.world)
            return
        if key == keys.ENTER:
            self._embark()

    def _embark(self) -> None:
        """Found the fortress."""
        t = self.world.tile(self.cx, self.cy)
        if t.is_ocean or t.is_lake:
            self.app.message("Embark", "You cannot found a fortress "
                                       "underwater.")
            return
        if t.site_id is not None:
            self.app.message("Embark", "Somebody already lives there.")
            return
        if not t.river and not self.app.confirm(
                "No water here. Your dwarves will have only what they carry. "
                "Embark anyway?"):
            return
        from ...fortress.fortress import Fortress
        from .fort_screen import FortScene

        fort = Fortress.embark(self.world, self.cx, self.cy,
                               self.rng.sub("fortress"))
        fort.site_id = t.site_id
        self.app.reset_to(FortScene(self.app, fort))


ADVICE = ("Dig into a hill with trees nearby and water you can reach. "
          "A river is worth more than gold: dwarves who have run out of "
          "ale will drink from it rather than die.")


def _band(value: float, words: Tuple[str, ...]) -> str:
    """Turn a 0..1 number into one of a few words."""
    idx = min(len(words) - 1, max(0, int(value * len(words))))
    return words[idx]


def _temperature(t: float) -> str:
    """A word for a temperature."""
    if t < 20:
        return "freezing"
    if t < 40:
        return "cold"
    if t < 65:
        return "temperate"
    if t < 85:
        return "warm"
    return "scorching"
