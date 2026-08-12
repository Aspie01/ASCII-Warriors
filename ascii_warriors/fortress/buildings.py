"""Workshops, furniture, constructions, stockpiles and farm plots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ..engine import colors
from ..engine.colors import Color
from ..world import tiles as tile_data

Cell = Tuple[int, int, int]


@dataclass(frozen=True)
class BuildingKind:
    """One thing you can put up."""

    id: str
    name: str
    glyph: str
    color: Color
    width: int
    height: int
    #: Item categories or flags acceptable as building material.
    materials: Tuple[str, ...]
    material_count: int
    work: int
    labor: str
    skill: str
    tile: str
    category: str
    walkable: bool = True
    description: str = ""


def _b(
    bid: str, name: str, glyph: str, color: Color, w: int, h: int,
    mats: Tuple[str, ...], count: int, work: int, labor: str, skill: str,
    tile: str, category: str, walkable: bool = True, desc: str = "",
) -> BuildingKind:
    return BuildingKind(bid, name, glyph, color, w, h, mats, count, work,
                        labor, skill, tile, category, walkable, desc)


KINDS: Dict[str, BuildingKind] = {
    k.id: k
    for k in (
        # -- workshops ---------------------------------------------------- #
        _b("carpenter", "Carpenter's workshop", "C", colors.Color(170, 130, 80),
           3, 3, ("WOOD",), 1, 200, "building", "carpentry",
           "floor_constructed", "Workshops", True,
           "Turns logs into beds, doors, barrels and bins."),
        _b("mason", "Mason's workshop", "M", colors.Color(170, 168, 160),
           3, 3, ("STONE",), 1, 200, "building", "masonry",
           "floor_constructed", "Workshops", True,
           "Turns stone into furniture, doors and blocks."),
        _b("craftsdwarf", "Craftsdwarf's workshop", "R",
           colors.Color(190, 160, 200), 3, 3, ("STONE", "WOOD"), 1, 200,
           "building", "crafting", "floor_constructed", "Workshops", True,
           "Makes trinkets, mugs and totems out of anything."),
        _b("smith", "Metalsmith's forge", "F", colors.Color(210, 130, 80),
           3, 3, ("STONE",), 1, 260, "building", "smithing",
           "floor_constructed", "Workshops", True,
           "Forges weapons and armour. Needs fuel."),
        _b("smelter", "Smelter", "&", colors.Color(220, 150, 70),
           3, 3, ("STONE",), 1, 260, "building", "smelting",
           "floor_constructed", "Workshops", True,
           "Ore and fuel in, metal bars out. Also where alloys are made."),
        _b("wood_furnace", "Wood furnace", "&", colors.Color(160, 110, 70),
           3, 3, ("STONE",), 1, 220, "building", "smelting",
           "floor_constructed", "Workshops", True,
           "Burns logs into charcoal, which is what everything else burns."),
        _b("magma_smelter", "Magma smelter", "&", colors.Color(240, 110, 50),
           3, 3, ("STONE",), 1, 300, "building", "smelting",
           "floor_constructed", "Workshops", True,
           "Smelts without fuel. Must be built over magma."),
        _b("magma_forge", "Magma forge", "F", colors.Color(240, 90, 40),
           3, 3, ("STONE",), 1, 320, "building", "smithing",
           "floor_constructed", "Workshops", True,
           "Forges without fuel. Must be built over magma."),
        _b("still", "Still", "S", colors.Color(180, 140, 90), 3, 3,
           ("WOOD", "STONE"), 1, 180, "building", "brewing",
           "floor_constructed", "Workshops", True,
           "Brews plants into drink. A fortress without drink is a doomed one."),
        _b("kitchen", "Kitchen", "K", colors.Color(200, 170, 120), 3, 3,
           ("WOOD", "STONE"), 1, 180, "building", "cooking",
           "floor_constructed", "Workshops", True,
           "Cooks raw food into meals worth eating."),
        _b("butcher", "Butcher's shop", "B", colors.Color(190, 110, 110),
           3, 3, ("WOOD", "STONE"), 1, 180, "building", "butchery",
           "floor_constructed", "Workshops", True, ""),
        _b("hospital", "Hospital bed", "H", colors.Color(210, 180, 180),
           1, 1, ("WOOD",), 1, 100, "building", "carpentry", "bed",
           "Workshops", True, "Where the wounded are treated."),
        _b("farm", "Farm plot", "=", colors.Color(120, 92, 58), 3, 3,
           (), 0, 60, "farming", "herbalism", "farm", "Workshops", True,
           "Plump helmets grow underground on nothing but mud and patience."),
        _b("barracks", "Barracks", "!", colors.Color(190, 180, 210), 3, 3,
           ("WOOD", "STONE"), 1, 200, "building", "carpentry",
           "barracks", "Workshops", True,
           "Where a squad spars. An untrained militia is a pile of corpses "
           "that has not happened yet."),

        # -- furniture ----------------------------------------------------- #
        _b("bed", "Bed", "=", colors.Color(180, 140, 90), 1, 1, ("WOOD",), 1,
           80, "building", "carpentry", "bed", "Furniture", True,
           "A dwarf who sleeps in a bed wakes up happier."),
        _b("table", "Table", "=", colors.Color(170, 130, 85), 1, 1,
           ("WOOD", "STONE"), 1, 80, "building", "carpentry", "table",
           "Furniture", True, ""),
        _b("chair", "Chair", "=", colors.Color(165, 125, 80), 1, 1,
           ("WOOD", "STONE"), 1, 70, "building", "carpentry", "chair",
           "Furniture", True, ""),
        _b("door", "Door", "+", colors.Color(170, 125, 70), 1, 1,
           ("WOOD", "STONE"), 1, 90, "building", "carpentry", "door_closed",
           "Furniture", True, "Keeps the weather and the goblins out."),
        _b("cabinet", "Cabinet", "=", colors.Color(150, 115, 70), 1, 1,
           ("WOOD", "STONE"), 1, 90, "building", "carpentry", "cabinet",
           "Furniture", False, ""),
        _b("coffer", "Coffer", "=", colors.Color(190, 160, 100), 1, 1,
           ("WOOD", "STONE", "METAL"), 1, 100, "building", "carpentry",
           "coffer", "Furniture", False, ""),
        _b("statue", "Statue", "&", colors.Color(200, 195, 185), 1, 1,
           ("STONE", "METAL"), 1, 160, "building", "masonry", "statue",
           "Furniture", False,
           "Dwarves like looking at these more than you would expect."),
        _b("well", "Well", "o", colors.Color(160, 180, 200), 1, 1,
           ("STONE", "WOOD"), 1, 200, "building", "mechanics", "well",
           "Furniture", True, "Clean water without leaving the fortress."),

        # -- constructions -------------------------------------------------- #
        _b("wall", "Wall", "#", colors.Color(175, 170, 158), 1, 1,
           ("STONE", "WOOD", "METAL"), 1, 120, "building", "masonry",
           "wall_constructed", "Construction", False, ""),
        _b("floor", "Floor", ".", colors.Color(160, 155, 145), 1, 1,
           ("STONE", "WOOD", "METAL"), 1, 100, "building", "masonry",
           "floor_constructed", "Construction", True, ""),
        _b("bridge", "Bridge", "=", colors.Color(160, 120, 75), 1, 1,
           ("STONE", "WOOD"), 1, 110, "building", "carpentry", "bridge",
           "Construction", True, ""),
        _b("fortification", "Fortification", "#", colors.Color(185, 180, 168),
           1, 1, ("STONE",), 1, 130, "building", "masonry", "fortification",
           "Construction", False,
           "Your crossbows can shoot through it. Theirs cannot get in."),
        _b("up_stair", "Up staircase", "<", colors.Color(200, 195, 175), 1, 1,
           ("STONE", "WOOD"), 1, 130, "building", "masonry", "stair_up",
           "Construction", True, ""),
        _b("down_stair", "Down staircase", ">", colors.Color(200, 195, 175),
           1, 1, ("STONE", "WOOD"), 1, 130, "building", "masonry",
           "stair_down", "Construction", True, ""),

        # -- defence -------------------------------------------------------- #
        _b("weapon_trap", "Weapon trap", "^", colors.Color(200, 120, 110),
           1, 1, ("WEAPON",), 1, 160, "mechanics", "mechanics", "trap",
           "Defence", True,
           "A weapon on a trigger. It does not care how brave the goblin is."),
        _b("spike_trap", "Spike trap", "^", colors.Color(180, 140, 140),
           1, 1, ("STONE", "METAL"), 1, 140, "mechanics", "mechanics", "trap",
           "Defence", True, "Cheaper, and almost as unpleasant."),
        _b("hatch", "Hatch cover", "+", colors.Color(150, 140, 130), 1, 1,
           ("WOOD", "STONE", "METAL"), 1, 100, "building", "carpentry",
           "hatch", "Defence", True,
           "Closes a stairway behind you."),
        _b("lever", "Lever", "\\", colors.Color(200, 180, 120), 1, 1,
           ("mechanism",), 1, 120, "mechanics", "mechanics", "lever",
           "Defence", True,
           "Pull it and everything linked to it opens or shuts."),
        _b("floodgate", "Floodgate", "#", colors.Color(120, 150, 180), 1, 1,
           ("STONE", "METAL", "WOOD"), 1, 160, "building", "mechanics",
           "floodgate_shut", "Defence", False,
           "Holds water back, or lets it through. Link it to a lever."),
        _b("drawbridge", "Drawbridge", "=", colors.Color(150, 112, 66), 3, 1,
           ("WOOD", "STONE", "METAL"), 1, 220, "building", "mechanics",
           "bridge_down", "Defence", True,
           "Raise it and the corridor becomes a wall. The classic answer to "
           "a siege."),
    )
}

#: Buildings that hurt whatever walks onto them.
TRAP_KINDS: Tuple[str, ...] = ("weapon_trap", "spike_trap")

#: Buildings a lever can be linked to, and the tiles for their two states.
#: ``(open tile, shut tile)`` — open lets things through, shut does not.
GATE_TILES: Dict[str, Tuple[str, str]] = {
    "floodgate": ("floodgate_open", "floodgate_shut"),
    "drawbridge": ("bridge_down", "bridge_up"),
    "door": ("door_open", "door_closed"),
    # An open hatch is the hole it was covering: things climb down it, and
    # water pours down it.
    "hatch": ("stair_down", "hatch"),
}

WORKSHOP_KINDS: Tuple[str, ...] = (
    "carpenter", "mason", "craftsdwarf", "smith", "smelter", "wood_furnace",
    "magma_smelter", "magma_forge", "still", "kitchen", "butcher",
)

#: Workshops that burn magma instead of fuel, and so have to sit on top of it.
MAGMA_KINDS: Tuple[str, ...] = ("magma_smelter", "magma_forge")

BUILD_CATEGORIES: Tuple[str, ...] = (
    "Workshops", "Furniture", "Construction", "Defence",
)


class Building:
    """A workshop, piece of furniture or construction, built or planned."""

    _next_id = 1

    def __init__(self, kind: str, x: int, y: int, z: int) -> None:
        self.id = Building._next_id
        Building._next_id += 1
        self.kind = kind
        self.x = x
        self.y = y
        self.z = z
        self.built = False
        #: Item ids used to build it, recorded so the material shows in its name.
        self.materials: List[int] = []
        self.material_name = ""
        #: Production orders queued at this workshop.
        self.orders: List[Dict[str, Any]] = []
        self.worker: Optional[int] = None
        self.owner: Optional[int] = None
        #: Levers remember what they are linked to; gates remember their state.
        self.links: List[int] = []
        self.shut = True
        #: Set when somebody has asked for this lever to be pulled.
        self.pending = False
        #: Farm plots track what is growing.
        self.crop = ""
        self.growth = 0
        self.planted = False

    @property
    def defn(self) -> BuildingKind:
        """The building's definition."""
        return KINDS.get(self.kind) or KINDS["wall"]

    @property
    def name(self) -> str:
        """Display name, including the material once it is built."""
        if self.material_name:
            return "%s %s" % (self.material_name, self.defn.name.lower())
        return self.defn.name

    @property
    def is_gate(self) -> bool:
        """True for things a lever can open and shut."""
        return self.kind in GATE_TILES

    def gate_tile(self) -> str:
        """The tile this gate should be showing right now."""
        openp, shutp = GATE_TILES.get(self.kind, ("floor", "floor"))
        return shutp if self.shut else openp

    @property
    def is_workshop(self) -> bool:
        """True for buildings that take production orders."""
        return self.kind in WORKSHOP_KINDS

    def cells(self) -> List[Cell]:
        """Every tile this building occupies."""
        d = self.defn
        return [
            (self.x + dx, self.y + dy, self.z)
            for dy in range(d.height) for dx in range(d.width)
        ]

    @property
    def center(self) -> Cell:
        """The middle of the building, where a worker stands."""
        d = self.defn
        return (self.x + d.width // 2, self.y + d.height // 2, self.z)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the building."""
        return {
            "id": self.id, "kind": self.kind, "x": self.x, "y": self.y,
            "z": self.z, "built": self.built, "materials": self.materials,
            "material_name": self.material_name, "orders": self.orders,
            "worker": self.worker, "owner": self.owner, "crop": self.crop,
            "growth": self.growth, "planted": self.planted,
            "links": self.links, "shut": self.shut, "pending": self.pending,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Building":
        """Rebuild from :meth:`to_dict`."""
        b = cls(str(d["kind"]), int(d["x"]), int(d["y"]), int(d["z"]))
        b.id = int(d.get("id", b.id))
        Building._next_id = max(Building._next_id, b.id + 1)
        b.built = bool(d.get("built", False))
        b.materials = [int(i) for i in d.get("materials", [])]
        b.material_name = str(d.get("material_name", ""))
        b.orders = list(d.get("orders", []))
        b.worker = d.get("worker")
        b.owner = d.get("owner")
        b.crop = str(d.get("crop", ""))
        b.growth = int(d.get("growth", 0))
        b.planted = bool(d.get("planted", False))
        b.links = [int(i) for i in d.get("links", [])]
        b.shut = bool(d.get("shut", True))
        b.pending = bool(d.get("pending", False))
        return b

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Building(%s at %d,%d,%d, %s)" % (
            self.kind, self.x, self.y, self.z,
            "built" if self.built else "planned")


# --------------------------------------------------------------------------- #
# Farm plots and stockpiles are zones rather than single buildings
# --------------------------------------------------------------------------- #

#: Which item categories each stockpile type accepts.
STOCKPILE_TYPES: Dict[str, Tuple[str, ...]] = {
    "stone": ("misc",),
    "wood": ("misc",),
    "food": ("food", "drink"),
    "furniture": ("furniture",),
    "weapons": ("weapon", "ammo"),
    "armor": ("armor", "clothing", "shield"),
    "goods": ("gem", "coin", "tool", "container", "book", "remains"),
    "metal": ("misc",),
    "refuse": ("corpse", "remains"),
    "all": ("weapon", "armor", "clothing", "shield", "ammo", "food", "drink",
            "tool", "container", "gem", "coin", "book", "furniture", "misc",
            "remains"),
}

STOCKPILE_COLORS: Dict[str, Color] = {
    "stone": colors.Color(150, 148, 142),
    "wood": colors.Color(160, 120, 75),
    "food": colors.Color(190, 175, 110),
    "furniture": colors.Color(170, 140, 100),
    "weapons": colors.Color(180, 180, 195),
    "armor": colors.Color(160, 170, 195),
    "goods": colors.Color(190, 160, 200),
    "metal": colors.Color(210, 150, 90),
    "refuse": colors.Color(140, 130, 120),
    "all": colors.Color(170, 170, 170),
}


class Stockpile:
    """A rectangle dwarves haul matching goods into."""

    _next_id = 1

    def __init__(self, kind: str, x: int, y: int, z: int, w: int, h: int) -> None:
        self.id = Stockpile._next_id
        Stockpile._next_id += 1
        self.kind = kind
        self.x = x
        self.y = y
        self.z = z
        self.w = max(1, w)
        self.h = max(1, h)

    @property
    def categories(self) -> Tuple[str, ...]:
        """Item categories this pile accepts."""
        return STOCKPILE_TYPES.get(self.kind, STOCKPILE_TYPES["all"])

    @property
    def color(self) -> Color:
        """Overlay colour."""
        return STOCKPILE_COLORS.get(self.kind, colors.UI["dim"])

    def accepts(self, item) -> bool:
        """True if this pile wants that item."""
        if self.kind == "stone":
            return item.def_id == "boulder"
        if self.kind == "wood":
            return item.def_id == "log"
        if self.kind == "refuse":
            return item.is_corpse or item.def_id in ("bone_item", "skull")
        if self.kind == "metal":
            return item.def_id in ("ore", "bar", "coal", "charcoal")
        if item.def_id in ("ore", "bar", "coal", "charcoal"):
            # Ore beside the smelter, not scattered through the bedrooms.
            return self.kind == "all"
        if item.def_id in ("boulder", "log"):
            return self.kind == "all"
        return item.category in self.categories

    def contains(self, x: int, y: int, z: int) -> bool:
        """True if a cell lies in this pile."""
        return (z == self.z and self.x <= x < self.x + self.w
                and self.y <= y < self.y + self.h)

    def cells(self) -> List[Cell]:
        """Every cell in the pile."""
        return [
            (self.x + dx, self.y + dy, self.z)
            for dy in range(self.h) for dx in range(self.w)
        ]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the stockpile."""
        return {"id": self.id, "kind": self.kind, "x": self.x, "y": self.y,
                "z": self.z, "w": self.w, "h": self.h}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Stockpile":
        """Rebuild from :meth:`to_dict`."""
        s = cls(str(d["kind"]), int(d["x"]), int(d["y"]), int(d["z"]),
                int(d["w"]), int(d["h"]))
        s.id = int(d.get("id", s.id))
        Stockpile._next_id = max(Stockpile._next_id, s.id + 1)
        return s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Stockpile(%s %dx%d at %d,%d,%d)" % (
            self.kind, self.w, self.h, self.x, self.y, self.z)


def can_place(lm, kind: str, x: int, y: int, z: int, buildings,
              magma=None) -> Tuple[bool, str]:
    """Whether a building fits here. Returns ``(ok, why not)``."""
    k = KINDS.get(kind)
    if k is None:
        return (False, "There is no such building.")
    for dy in range(k.height):
        for dx in range(k.width):
            cx, cy = x + dx, y + dy
            if not lm.in_bounds(cx, cy, z):
                return (False, "That is off the edge of the map.")
            if kind in MAGMA_KINDS and magma is not None \
                    and magma.at(cx, cy, z - 1) <= 0:
                # The whole point of it: you have to bring the magma to the
                # workshop, which is an afternoon's engineering and a very
                # bad afternoon if you get it wrong.
                return (False, "It needs magma directly underneath it.")
            tile = tile_data.get(lm.tile(cx, cy, z))
            if kind in ("wall", "floor", "up_stair", "down_stair",
                        "fortification", "bridge"):
                if tile.has("WALL") and kind != "floor":
                    return (False, "There is already a wall there.")
            elif not tile.walk or tile.has("WATER"):
                return (False, "The ground there will not take it.")
            if tile.has("FURNITURE"):
                return (False, "Something is already built there.")
            for b in buildings:
                if (cx, cy, z) in b.cells():
                    return (False, "Something is already built there.")
    return (True, "")


def material_matches(item, kind: str) -> bool:
    """True if an item can be used to build this kind of building."""
    k = KINDS.get(kind)
    if k is None:
        return False
    if "WEAPON" in k.materials:
        return item.is_weapon and not item.is_ranged
    if item.def_id in k.materials:
        return True
    if item.def_id == "boulder":
        return "STONE" in k.materials
    if item.def_id == "log":
        return "WOOD" in k.materials
    if item.def_id == "bar":
        return "METAL" in k.materials
    if item.def_id in ("ore", "coal", "charcoal"):
        # Raw ore and fuel are the smelter's business. Nobody builds a wall
        # out of the coal they were going to burn.
        return False
    if item.category in ("weapon", "armor", "food", "drink", "corpse"):
        return False
    flags = item.mat.flags
    return any(f in flags for f in k.materials)
