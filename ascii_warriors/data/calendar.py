"""The dwarven calendar.

Twelve months named for stone and metal, 28 days each, four seasons of three
months. One tick is six seconds — the time a standard action takes for a
creature of baseline speed.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Tuple

MONTHS: Tuple[str, ...] = (
    "Granite", "Slate", "Felsite",
    "Hematite", "Malachite", "Galena",
    "Limestone", "Sandstone", "Timber",
    "Moonstone", "Opal", "Obsidian",
)

SEASONS: Tuple[str, ...] = ("Spring", "Summer", "Autumn", "Winter")

DAYS_PER_MONTH = 28
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR  # 336

#: Six seconds per tick.
SECONDS_PER_TICK = 6
TICKS_PER_MINUTE = 10
TICKS_PER_HOUR = TICKS_PER_MINUTE * 60          # 600
TICKS_PER_DAY = TICKS_PER_HOUR * 24             # 14400
TICKS_PER_MONTH = TICKS_PER_DAY * DAYS_PER_MONTH
TICKS_PER_YEAR = TICKS_PER_DAY * DAYS_PER_YEAR

#: Default campaign start: the 1st of Granite, year 125, at eight in the morning.
DEFAULT_YEAR = 125
DEFAULT_HOUR = 8

MOON_PHASES: Tuple[str, ...] = (
    "new moon", "waxing crescent", "first quarter", "waxing gibbous",
    "full moon", "waning gibbous", "last quarter", "waning crescent",
)


def ordinal(n: int) -> str:
    """Format an integer with its English ordinal suffix (``1 -> "1st"``)."""
    if 10 <= abs(n) % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(abs(n) % 10, "th")
    return "%d%s" % (n, suffix)


def season_of_month(month: int) -> str:
    """Season name for a 1-based month number."""
    return SEASONS[((month - 1) // 3) % 4]


class GameTime:
    """A point in world time, stored as a single tick count."""

    __slots__ = ("ticks",)

    def __init__(self, ticks: int = 0) -> None:
        self.ticks = int(ticks)

    @classmethod
    def at(
        cls,
        year: int = DEFAULT_YEAR,
        month: int = 1,
        day: int = 1,
        hour: int = DEFAULT_HOUR,
        minute: int = 0,
    ) -> "GameTime":
        """Build a time from calendar components (all 1-based except the clock)."""
        ticks = (
            year * TICKS_PER_YEAR
            + (month - 1) * TICKS_PER_MONTH
            + (day - 1) * TICKS_PER_DAY
            + hour * TICKS_PER_HOUR
            + minute * TICKS_PER_MINUTE
        )
        return cls(ticks)

    # -- components -------------------------------------------------------- #

    @property
    def year(self) -> int:
        """Year number."""
        return self.ticks // TICKS_PER_YEAR

    @property
    def month(self) -> int:
        """Month of the year, 1..12."""
        return (self.ticks % TICKS_PER_YEAR) // TICKS_PER_MONTH + 1

    @property
    def day(self) -> int:
        """Day of the month, 1..28."""
        return (self.ticks % TICKS_PER_MONTH) // TICKS_PER_DAY + 1

    @property
    def hour(self) -> int:
        """Hour of the day, 0..23."""
        return (self.ticks % TICKS_PER_DAY) // TICKS_PER_HOUR

    @property
    def minute(self) -> int:
        """Minute of the hour, 0..59."""
        return (self.ticks % TICKS_PER_HOUR) // TICKS_PER_MINUTE

    @property
    def month_name(self) -> str:
        """Name of the current month."""
        return MONTHS[self.month - 1]

    @property
    def season(self) -> str:
        """Current season name."""
        return season_of_month(self.month)

    @property
    def day_of_year(self) -> int:
        """Day within the year, 1..336."""
        return (self.ticks % TICKS_PER_YEAR) // TICKS_PER_DAY + 1

    # -- movement ---------------------------------------------------------- #

    def advance(self, ticks: int) -> None:
        """Move forward by *ticks* (negative values are ignored)."""
        if ticks > 0:
            self.ticks += int(ticks)

    def copy(self) -> "GameTime":
        """An independent copy."""
        return GameTime(self.ticks)

    def ticks_until(self, hour: int, minute: int = 0) -> int:
        """Ticks until the next occurrence of a wall-clock time."""
        target = hour * TICKS_PER_HOUR + minute * TICKS_PER_MINUTE
        now = self.ticks % TICKS_PER_DAY
        delta = target - now
        if delta <= 0:
            delta += TICKS_PER_DAY
        return delta

    # -- daylight ---------------------------------------------------------- #

    def is_night(self) -> bool:
        """True between 20:00 and 05:00."""
        h = self.hour
        return h >= 20 or h < 5

    def light_level(self) -> float:
        """Outdoor daylight from 0.0 (deep night) to 1.0 (noon).

        Ramps smoothly through civil twilight so dawn and dusk read differently
        from midnight.
        """
        frac = (self.ticks % TICKS_PER_DAY) / float(TICKS_PER_DAY)
        # Peak at noon, trough at midnight.
        raw = 0.5 - 0.5 * math.cos(2.0 * math.pi * frac)
        # Sharpen: full dark for a few hours either side of midnight.
        value = (raw - 0.12) / 0.78
        seasonal = 1.0 + 0.08 * math.cos(
            2.0 * math.pi * (self.day_of_year - 190) / DAYS_PER_YEAR
        )
        return max(0.0, min(1.0, value * seasonal))

    def moon_phase(self) -> str:
        """A flavour moon phase on a 28-day cycle."""
        idx = int(((self.ticks // TICKS_PER_DAY) % 28) / 3.5) % 8
        return MOON_PHASES[idx]

    # -- formatting -------------------------------------------------------- #

    def date_str(self) -> str:
        """``"12th of Granite, 125"``."""
        return "%s of %s, %d" % (ordinal(self.day), self.month_name, self.year)

    def time_str(self) -> str:
        """``"14:32"``."""
        return "%02d:%02d" % (self.hour, self.minute)

    def short_date(self) -> str:
        """``"12 Granite 125"``."""
        return "%d %s %d" % (self.day, self.month_name, self.year)

    def full_str(self) -> str:
        """Date, clock and season together."""
        return "%s, %s (%s)" % (self.date_str(), self.time_str(), self.season)

    def time_of_day_name(self) -> str:
        """A coarse label such as ``"dusk"`` or ``"midday"``."""
        h = self.hour
        if h < 4:
            return "the dead of night"
        if h < 6:
            return "before dawn"
        if h < 8:
            return "dawn"
        if h < 11:
            return "morning"
        if h < 14:
            return "midday"
        if h < 17:
            return "afternoon"
        if h < 19:
            return "evening"
        if h < 21:
            return "dusk"
        return "night"

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {"ticks": self.ticks}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "GameTime":
        """Rebuild from :meth:`to_dict`."""
        return cls(int(d.get("ticks", 0)))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "GameTime(%s)" % self.full_str()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, GameTime) and other.ticks == self.ticks

    def __lt__(self, other: "GameTime") -> bool:
        return self.ticks < other.ticks

    def __hash__(self) -> int:
        return hash(self.ticks)


def duration_str(ticks: int) -> str:
    """Human-readable length of time, e.g. ``"3 hours"`` or ``"2 days"``."""
    if ticks < TICKS_PER_MINUTE:
        return "a moment"
    if ticks < TICKS_PER_HOUR:
        n = max(1, ticks // TICKS_PER_MINUTE)
        return "%d minute%s" % (n, "" if n == 1 else "s")
    if ticks < TICKS_PER_DAY:
        n = max(1, ticks // TICKS_PER_HOUR)
        return "%d hour%s" % (n, "" if n == 1 else "s")
    if ticks < TICKS_PER_MONTH:
        n = max(1, ticks // TICKS_PER_DAY)
        return "%d day%s" % (n, "" if n == 1 else "s")
    if ticks < TICKS_PER_YEAR:
        n = max(1, ticks // TICKS_PER_MONTH)
        return "%d month%s" % (n, "" if n == 1 else "s")
    n = max(1, ticks // TICKS_PER_YEAR)
    return "%d year%s" % (n, "" if n == 1 else "s")
