"""The status sidebar and the message log panel."""

from __future__ import annotations

from typing import List, Tuple

from ..engine import colors
from ..engine.screen import Frag, Screen, frag_slice
from ..engine.widgets import gauge
from ..world import tiles as tile_data

SIDEBAR_WIDTH = 30
LOG_HEIGHT = 7

_SEVERITY_COLORS = {
    "ok": colors.UI["good"],
    "warn": colors.UI["warn"],
    "danger": colors.UI["danger"],
}


def draw_sidebar(scr: Screen, x: int, y: int, w: int, h: int, game) -> None:
    """Draw the right-hand status column."""
    p = game.player
    scr.vline(x - 1, y, h, "|", colors.UI["frame"])
    cy = y

    scr.text(x, cy, p.name[: w - 1], colors.UI["title"])
    cy += 1
    scr.text(x, cy, "%s %s" % (p.defn.name, p.profession or "adventurer"),
             colors.UI["dim"])
    cy += 2

    health = p.body.health_fraction()
    hcol = (colors.UI["good"] if health > 0.6 else
            colors.UI["warn"] if health > 0.3 else colors.UI["danger"])
    gauge(scr, x, cy, w - 1, "Body", health, hcol)
    cy += 1
    blood = p.body.blood_fraction()
    gauge(scr, x, cy, w - 1, "Blood", blood,
          colors.UI["good"] if blood > 0.7 else colors.UI["danger"])
    cy += 1
    for label, frac, severity in p.needs.status():
        gauge(scr, x, cy, w - 1, label, frac, _SEVERITY_COLORS.get(
            severity, colors.UI["good"]))
        cy += 1
    cy += 1

    # Wounds.
    wound_lines = p.body.status_lines()
    if wound_lines and "unhurt" not in wound_lines[0].text:
        scr.text(x, cy, "Wounds", colors.UI["accent"])
        cy += 1
        for frag in wound_lines[:5]:
            scr.text(x, cy, frag_slice([frag], 0, w - 1))
            cy += 1
        if len(wound_lines) > 5:
            scr.text(x, cy, "  ...and %d more" % (len(wound_lines) - 5),
                     colors.UI["dim"])
            cy += 1
        cy += 1

    # Equipment.
    scr.text(x, cy, "Wielding", colors.UI["accent"])
    cy += 1
    weapon = p.inventory.weapon()
    scr.text(x + 1, cy, (weapon.name() if weapon else "bare hands")[: w - 2],
             weapon.color if weapon else colors.UI["dim"])
    cy += 1
    off = p.inventory.offhand()
    if off is not None:
        scr.text(x + 1, cy, off.name()[: w - 2], off.color)
        cy += 1
    ammo = p.inventory.ammo()
    if ammo is not None:
        scr.text(x + 1, cy, "%s x%d" % (ammo.base_name(), ammo.count),
                 colors.UI["dim"])
        cy += 1
    cy += 1

    # Nearby creatures.
    nearby = game.visible_creatures()[:6]
    if nearby:
        scr.text(x, cy, "You see", colors.UI["accent"])
        cy += 1
        for c in nearby:
            if cy >= y + h - 6:
                break
            glyph, colour = c.glyph_and_color()
            hostile = c.is_hostile_to(p) or p.is_hostile_to(c)
            scr.put(x + 1, cy, glyph, colour)
            label = c.display_name()[: w - 8]
            scr.text(x + 3, cy, label,
                     colors.UI["danger"] if hostile else colors.UI["fg"])
            dist = p.distance_to(c)
            scr.text_right(x + w - 2, cy, str(dist), colors.UI["dim"])
            cy += 1
        cy += 1

    # Time and place at the bottom.
    by = y + h - 5
    scr.hline(x, by - 1, w - 1, "-", colors.UI["frame"])
    scr.text(x, by, game.time.date_str()[: w - 1], colors.UI["fg"])
    scr.text(x, by + 1, "%s  %s" % (
        game.time.time_str(), game.time.time_of_day_name()), colors.UI["dim"])
    site = game.current_site()
    region = game.world.region_at(p.wx, p.wy)
    place = site.name if site is not None else (
        region.name if region is not None else "the wilds"
    )
    scr.text(x, by + 2, place[: w - 1], colors.UI["accent2"])
    scr.text(x, by + 3, "z%+d  (%d, %d)" % (p.z, p.wx, p.wy), colors.UI["dim"])


def draw_log(scr: Screen, x: int, y: int, w: int, h: int, game) -> None:
    """Draw the scrolling message log."""
    scr.hline(x, y, w, "-", colors.UI["frame"])
    messages = game.log.recent(h - 1)
    row = y + 1
    for msg in messages[-(h - 1):]:
        if row >= y + h:
            break
        scr.text(x, row, frag_slice(msg.display(), 0, w))
        row += 1


def draw_status_line(scr: Screen, x: int, y: int, w: int, game) -> None:
    """Draw the single-line status bar at the top."""
    p = game.player
    scr.fill(x, y, w, 1, " ", colors.UI["fg"], colors.UI["bg"])
    parts: List[Frag] = [
        Frag("%s " % p.name, colors.UI["title"]),
        Frag("| ", colors.UI["frame"]),
    ]
    here = tile_data.get(game.local.tile(p.x, p.y, p.z)) if game.local else None
    if here is not None:
        parts.append(Frag("%s " % here.name, here.color))
        parts.append(Frag("| ", colors.UI["frame"]))
    enc = p.encumbrance()
    if enc > 1.0:
        parts.append(Frag("overloaded ", colors.UI["danger"]))
    mood = p.needs.mood()
    parts.append(Frag(mood + " ", colors.UI["dim"]))
    parts.append(Frag("| ", colors.UI["frame"]))
    parts.append(Frag("T%d " % game.turn, colors.UI["dim"]))
    if game.quests.active:
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("%d tasks" % len(game.quests.active),
                          colors.UI["accent"]))
    scr.text(x, y, frag_slice(parts, 0, w))
