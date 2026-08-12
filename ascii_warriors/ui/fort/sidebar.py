"""The fortress sidebar: date, weather, stocks and what everyone is doing."""

from __future__ import annotations

from typing import List

from ...engine import colors
from ...engine.screen import Frag, Screen, frag_slice
from ...engine.widgets import gauge

SIDEBAR_WIDTH = 32
LOG_HEIGHT = 7


def draw_sidebar(scr: Screen, x: int, y: int, w: int, h: int, fort) -> None:
    """Everything you need to see at a glance while time is running."""
    row = y
    scr.vline(x - 1, y, h, "|", colors.UI["frame"])

    scr.text(x, row, frag_slice([Frag(fort.name, colors.UI["title"])], 0, w))
    row += 1
    scr.text(x, row, fort.time.date_str(), colors.UI["dim"])
    row += 1
    scr.text(x, row, "%s  %s" % (fort.time.time_str(), fort.time.season),
             colors.UI["dim"])
    row += 1
    scr.text(x, row, fort.weather.name, fort.weather.defn.color)
    row += 2

    dwarves = fort.dwarves()
    scr.text(x, row, "Dwarves %d" % len(dwarves), colors.UI["accent"])
    hostiles = fort.hostiles()
    if hostiles:
        scr.text_right(x + w - 1, row, "%d hostile" % len(hostiles),
                       colors.UI["danger"])
    row += 1
    scr.text(x, row, "Wealth  %d" % fort.wealth, colors.UI["dim"])
    row += 1
    scr.text(x, row, "Jobs    %d" % len(fort.jobs), colors.UI["dim"])
    row += 2

    row = _draw_stocks(scr, x, row, w, fort, dwarves)
    row += 1
    row = _draw_happiness(scr, x, row, w, dwarves)
    row += 1
    _draw_roster(scr, x, row, w, y + h - row, dwarves)


def _draw_stocks(scr: Screen, x: int, row: int, w: int, fort, dwarves) -> int:
    """Food and drink, with the days remaining spelled out."""
    heads = max(1, len(dwarves))
    drink = fort.stock_count("dwarven_ale", "wine", "beer", "rum", "mead")
    food = fort.stock_count("meat", "cooked_meat", "prepared_meal", "bread",
                            "cheese", "fish_food", "plump_helmet", "berries",
                            "cave_wheat")
    scr.text(x, row, "Stocks", colors.UI["accent"])
    row += 1
    for label, count in (("Drink", drink), ("Food", food)):
        days = count / float(heads)
        if days < 3:
            colour = colors.UI["danger"]
        elif days < 10:
            colour = colors.UI["warn"]
        else:
            colour = colors.UI["good"]
        scr.text(x, row, "  %-6s %4d" % (label, count), colors.UI["fg"])
        scr.text_right(x + w - 1, row, "%d days" % int(days), colour)
        row += 1
    scr.text(x, row, "  %-6s %4d" % ("Stone", fort.stock_count("boulder")),
             colors.UI["dim"])
    scr.text_right(x + w - 1, row, "%d wood" % fort.stock_count("log"),
                   colors.UI["dim"])
    row += 1
    scr.text(x, row, "  %-6s %4d" % ("Bars", fort.stock_count("bar")),
             colors.UI["dim"])
    scr.text_right(x + w - 1, row, "%d fuel"
                   % fort.stock_count("charcoal", "coal"), colors.UI["dim"])
    return row + 1


def _draw_happiness(scr: Screen, x: int, row: int, w: int, dwarves) -> int:
    """One bar for the mood of the fortress as a whole."""
    if not dwarves:
        return row
    stress = sum(d.needs.stress for d in dwarves) / float(len(dwarves))
    # Stress runs -150 (ecstatic) to 200 (about to snap).
    fill = max(0.0, min(1.0, 1.0 - (stress + 150) / 350.0))
    colour = (colors.UI["good"] if stress < 30 else
              colors.UI["warn"] if stress < 90 else colors.UI["danger"])
    gauge(scr, x, row, w - 1, "Mood", fill, colour)
    return row + 1


def _draw_roster(scr: Screen, x: int, row: int, w: int, h: int, dwarves) -> None:
    """Who is doing what, most interesting first."""
    if h <= 1:
        return
    scr.text(x, row, "Working", colors.UI["accent"])
    row += 1
    ordered = sorted(dwarves, key=lambda d: (d.fort.job is None, d.name))
    for d in ordered[:max(0, h - 1)]:
        state = d.fort
        name = (state.nickname or d.name.split()[0])[:13]
        if state.mood:
            what, colour = "possessed", colors.MAGIC
        elif state.job is not None:
            what, colour = state.job.label, state.job.color
        elif d.body.unconscious > 0:
            what, colour = "unconscious", colors.UI["danger"]
        else:
            what, colour = "idle", colors.UI["dim"]
        scr.text(x, row, "%-13s " % name, colors.UI["fg"])
        scr.text(x + 14, row, what[:max(1, w - 14)], colour)
        row += 1


def draw_log(scr: Screen, x: int, y: int, w: int, h: int, fort) -> None:
    """The scrolling message log."""
    scr.hline(x, y, w, "-", colors.UI["frame"])
    row = y + 1
    for msg in fort.log.recent(h - 1)[-(h - 1):]:
        if row >= y + h:
            break
        scr.text(x, row, frag_slice(msg.display(), 0, w))
        row += 1


def draw_status_line(scr: Screen, x: int, y: int, w: int, fort, mode: str = "") -> None:
    """The top bar: what mode you are in, and whether time is running."""
    scr.fill(x, y, w, 1, " ", colors.UI["fg"], colors.UI["bg"])
    parts: List[Frag] = []
    if fort.paused:
        parts.append(Frag("[PAUSED] ", colors.UI["warn"]))
    else:
        parts.append(Frag("[x%d] " % fort.speed, colors.UI["good"]))
    parts.append(Frag("z%+d " % fort.z, colors.UI["accent"]))
    parts.append(Frag("| ", colors.UI["frame"]))
    if mode:
        parts.append(Frag(mode + " ", colors.UI["title"]))
        parts.append(Frag("| ", colors.UI["frame"]))
    parts.append(Frag(fort.time.full_str() + " ", colors.UI["dim"]))
    if fort.caravan is not None:
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("caravan (t) ", colors.UI["good"]))
    if getattr(fort, "water", None) is not None and fort.water.flooded:
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("FLOODING ", colors.UI["danger"]))
    if getattr(fort, "magma", None) is not None and fort.magma.flooded:
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("MAGMA ", colors.Color(255, 150, 60)))
    if getattr(fort, "breached", False):
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("THE PIT IS OPEN ", colors.UI["danger"]))
    mayor = fort.court.noble("mayor")
    if mayor is not None and mayor.mandate:
        parts.append(Frag("| ", colors.UI["frame"]))
        parts.append(Frag("mandate: %s " % mayor.mandate.get("target", ""),
                          colors.UI["warn"]))
    scr.text(x, y, frag_slice(parts, 0, w))
