"""Weather.

Weather changes with the season and the biome, and it matters: fog and storms
cut how far you can see, rain and cloud darken the day, and cold weather makes
you burn through food faster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from ..data import biomes as biome_data
from ..data.calendar import TICKS_PER_HOUR
from ..engine import colors
from ..engine.colors import Color
from ..engine.rng import RNG


@dataclass(frozen=True)
class WeatherKind:
    """One kind of weather and what it does."""

    id: str
    name: str
    description: str
    light: float
    sight: float
    color: Color
    glyph: str = ""


KINDS: Dict[str, WeatherKind] = {
    k.id: k
    for k in (
        WeatherKind("clear", "clear", "The sky is clear.", 1.0, 1.0,
                    colors.Color(150, 180, 210)),
        WeatherKind("cloudy", "cloudy", "Grey cloud covers the sky.", 0.80, 0.95,
                    colors.Color(150, 152, 158)),
        WeatherKind("rain", "rain", "Rain is falling.", 0.62, 0.80,
                    colors.Color(120, 150, 190), "'"),
        WeatherKind("storm", "storm", "A storm is breaking overhead.", 0.40, 0.60,
                    colors.Color(96, 110, 140), "/"),
        WeatherKind("snow", "snow", "Snow is falling.", 0.70, 0.70,
                    colors.Color(226, 234, 244), "*"),
        WeatherKind("blizzard", "blizzard", "A blizzard howls around you.",
                    0.45, 0.40, colors.Color(214, 226, 240), "*"),
        WeatherKind("fog", "fog", "A thick fog hangs over everything.",
                    0.75, 0.42, colors.Color(178, 182, 186)),
    )
}

#: How likely each kind is to follow the current one, before climate weighting.
_TRANSITIONS: Dict[str, Dict[str, float]] = {
    "clear": {"clear": 6.0, "cloudy": 3.0, "fog": 0.6},
    "cloudy": {"cloudy": 4.0, "clear": 3.0, "rain": 2.5, "snow": 1.5, "fog": 1.0},
    "rain": {"rain": 3.0, "cloudy": 3.5, "storm": 1.2, "clear": 1.0},
    "storm": {"storm": 1.5, "rain": 3.0, "cloudy": 2.0},
    "snow": {"snow": 3.0, "cloudy": 3.0, "blizzard": 1.0, "clear": 1.0},
    "blizzard": {"blizzard": 1.2, "snow": 3.0, "cloudy": 1.5},
    "fog": {"fog": 2.0, "clear": 2.5, "cloudy": 2.0},
}


class Weather:
    """The current weather, and when it will next change."""

    __slots__ = ("kind", "ticks_left")

    def __init__(self, kind: str = "clear", ticks_left: int = 0) -> None:
        self.kind = kind if kind in KINDS else "clear"
        self.ticks_left = ticks_left

    @property
    def defn(self) -> WeatherKind:
        """The definition of the current weather."""
        return KINDS[self.kind]

    @property
    def name(self) -> str:
        """One-word name, e.g. ``"rain"``."""
        return self.defn.name

    def describe(self) -> str:
        """A sentence about the weather."""
        return self.defn.description

    def light_modifier(self) -> float:
        """How much daylight gets through, 0..1."""
        return self.defn.light

    def sight_modifier(self) -> float:
        """How far you can see, as a fraction of normal."""
        return self.defn.sight

    def is_severe(self) -> bool:
        """True for weather worth complaining about."""
        return self.kind in ("storm", "blizzard", "fog")

    def is_cold(self) -> bool:
        """True for freezing weather."""
        return self.kind in ("snow", "blizzard")

    def is_wet(self) -> bool:
        """True when water is falling out of the sky."""
        return self.kind in ("rain", "storm", "snow", "blizzard")

    def tick(self, ticks: int, rng: RNG, biome: str, temperature: float,
             season: str) -> str:
        """Advance the weather clock; returns a message when it changes."""
        self.ticks_left -= ticks
        if self.ticks_left > 0:
            return ""
        old = self.kind
        self.kind = _next_kind(rng, self.kind, biome, temperature, season)
        self.ticks_left = rng.randint(2, 14) * TICKS_PER_HOUR
        if self.kind == old:
            return ""
        return self.describe()

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the weather."""
        return {"kind": self.kind, "left": self.ticks_left}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Weather":
        """Rebuild from :meth:`to_dict`."""
        return cls(str(d.get("kind", "clear")), int(d.get("left", 0)))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Weather(%s)" % self.kind


def _next_kind(
    rng: RNG, current: str, biome: str, temperature: float, season: str
) -> str:
    """Pick the next weather, weighted by climate."""
    table = dict(_TRANSITIONS.get(current, _TRANSITIONS["clear"]))
    b = biome_data.get(biome)

    freezing = temperature < 20
    for kind in list(table):
        if kind in ("snow", "blizzard") and not freezing:
            table[kind] = 0.0
        if kind in ("rain", "storm") and freezing:
            table[kind] = 0.0

    if b.has("DESERT"):
        for kind in ("rain", "storm", "snow", "blizzard", "fog"):
            table[kind] = table.get(kind, 0.0) * 0.15
        table["clear"] = table.get("clear", 1.0) * 2.0
    if b.has("WETLAND") or b.has("FOREST"):
        table["fog"] = table.get("fog", 0.5) * 2.5
        table["rain"] = table.get("rain", 1.0) * 1.6
    if b.has("MOUNTAIN"):
        table["storm"] = table.get("storm", 1.0) * 1.8
        table["fog"] = table.get("fog", 0.5) * 1.5
    if season == "Winter":
        table["snow"] = table.get("snow", 0.0) * 1.8
        table["clear"] = table.get("clear", 1.0) * 0.7
    elif season == "Summer":
        table["clear"] = table.get("clear", 1.0) * 1.4

    table = {k: v for k, v in table.items() if v > 0}
    if not table:
        return "clear"
    return rng.weighted(table)


def starting_weather(rng: RNG, biome: str, temperature: float, season: str) -> Weather:
    """Roll the weather a new game begins with."""
    w = Weather("clear", 0)
    w.kind = _next_kind(rng, "cloudy", biome, temperature, season)
    w.ticks_left = rng.randint(2, 10) * TICKS_PER_HOUR
    return w


def exposure_message(weather: Weather, indoors: bool) -> str:
    """A line to log when the player is out in bad weather."""
    if indoors:
        return ""
    if weather.kind == "blizzard":
        return "The blizzard cuts through you."
    if weather.kind == "storm":
        return "The storm lashes at you."
    if weather.kind == "snow":
        return "The cold bites."
    return ""
