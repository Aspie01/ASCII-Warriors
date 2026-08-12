"""Item definitions: weapons, armour, tools, food and everything else you carry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Tuple

CATEGORIES: Tuple[str, ...] = (
    "weapon", "armor", "clothing", "shield", "ammo", "food", "drink", "tool",
    "container", "gem", "coin", "furniture", "corpse", "remains", "misc", "book",
)


@dataclass(frozen=True)
class AttackDef:
    """One way of striking with a weapon or body part."""

    name: str
    verb2: str
    verb3: str
    kind: str
    contact: int
    penetration: int
    velocity: float = 1.0
    prepare: int = 3
    recover: int = 3

    @property
    def is_edged(self) -> bool:
        """True for cutting and piercing attacks."""
        return self.kind == "edge"


@dataclass(frozen=True)
class WeaponDef:
    """How an item behaves when swung or fired."""

    skill: str
    two_handed_size: int
    min_size: int
    attacks: Tuple[AttackDef, ...]
    ranged: Optional[str] = None
    shoot_force: int = 0

    @property
    def is_ranged(self) -> bool:
        """True for bows, crossbows and slings."""
        return self.ranged is not None


@dataclass(frozen=True)
class ArmorDef:
    """How an item protects the body."""

    layer: str
    coverage: Tuple[str, ...]
    thickness: int
    armor_level: int
    permit_size: int = 0


@dataclass(frozen=True)
class ItemDef:
    """A kind of item, before a material and quality are chosen."""

    id: str
    name: str
    plural: str
    category: str
    glyph: str
    volume: int
    value: int
    materials: Tuple[str, ...]
    weapon: Optional[WeaponDef] = None
    armor: Optional[ArmorDef] = None
    nutrition: int = 0
    hydration: int = 0
    stack: bool = False
    flags: FrozenSet[str] = field(default_factory=frozenset)
    description: str = ""

    def has(self, flag: str) -> bool:
        """True if this item carries *flag*."""
        return flag in self.flags


# --------------------------------------------------------------------------- #
# Attack shorthands
# --------------------------------------------------------------------------- #

def _slash(contact: int, pen: int, vel: float = 1.0) -> AttackDef:
    return AttackDef("slash", "slash", "slashes", "edge", contact, pen, vel)


def _stab(contact: int, pen: int, vel: float = 1.0) -> AttackDef:
    return AttackDef("stab", "stab", "stabs", "edge", contact, pen, vel, 2, 2)


def _bash(contact: int, pen: int, vel: float = 1.0) -> AttackDef:
    return AttackDef("bash", "bash", "bashes", "blunt", contact, pen, vel, 4, 4)


def _hack(contact: int, pen: int, vel: float = 1.0) -> AttackDef:
    return AttackDef("hack", "hack", "hacks", "edge", contact, pen, vel, 4, 4)


PUNCH = AttackDef("punch", "punch", "punches", "blunt", 20, 500, 1.0, 1, 1)
KICK = AttackDef("kick", "kick", "kicks", "blunt", 40, 800, 1.0, 2, 2)
BITE = AttackDef("bite", "bite", "bites", "edge", 20, 2000, 1.0, 2, 2)
SCRATCH = AttackDef("scratch", "scratch", "scratches", "edge", 10, 1000, 1.0, 1, 1)
CLAW = AttackDef("claw", "claw", "claws", "edge", 30, 4000, 1.0, 2, 2)
GORE = AttackDef("gore", "gore", "gores", "edge", 40, 6000, 1.2, 3, 3)
SLAM = AttackDef("slam", "slam", "slams", "blunt", 200, 4000, 1.0, 4, 4)
STING = AttackDef("sting", "sting", "stings", "edge", 5, 3000, 1.0, 2, 2)
LASH = AttackDef("lash", "lash", "lashes", "blunt", 5, 200, 1.4, 2, 2)
PECK = AttackDef("peck", "peck", "pecks", "edge", 10, 1500, 1.0, 1, 1)
BUTT = AttackDef("butt", "butt", "butts", "blunt", 60, 1500, 1.0, 3, 3)
CRUSH = AttackDef("crush", "crush", "crushes", "blunt", 400, 8000, 1.0, 5, 5)

ITEMS: Dict[str, ItemDef] = {}


def _add(item: ItemDef) -> ItemDef:
    ITEMS[item.id] = item
    return item


def _weapon(
    iid: str,
    name: str,
    skill: str,
    volume: int,
    value: int,
    attacks: Tuple[AttackDef, ...],
    *,
    two_handed_size: int = 0,
    min_size: int = 0,
    plural: str = "",
    glyph: str = "/",
    mats: Tuple[str, ...] = ("METAL",),
    flags: Tuple[str, ...] = (),
    ranged: Optional[str] = None,
    shoot_force: int = 0,
    desc: str = "",
) -> ItemDef:
    return _add(ItemDef(
        id=iid, name=name, plural=plural or (name + "s"), category="weapon",
        glyph=glyph, volume=volume, value=value, materials=mats,
        weapon=WeaponDef(skill, two_handed_size, min_size, attacks, ranged, shoot_force),
        flags=frozenset(flags), description=desc,
    ))


def _armor(
    iid: str,
    name: str,
    layer: str,
    coverage: Tuple[str, ...],
    volume: int,
    value: int,
    thickness: int,
    level: int,
    *,
    category: str = "armor",
    glyph: str = "[",
    plural: str = "",
    mats: Tuple[str, ...] = ("METAL",),
    flags: Tuple[str, ...] = (),
    permit_size: int = 0,
    desc: str = "",
) -> ItemDef:
    return _add(ItemDef(
        id=iid, name=name, plural=plural or (name + "s"), category=category,
        glyph=glyph, volume=volume, value=value, materials=mats,
        armor=ArmorDef(layer, coverage, thickness, level, permit_size),
        flags=frozenset(flags), description=desc,
    ))


# --------------------------------------------------------------------------- #
# Weapons
# --------------------------------------------------------------------------- #

_weapon("dagger", "dagger", "dagger", 100, 20,
        (_stab(5, 4000, 1.1), _slash(20, 2000)), min_size=15000,
        desc="A short blade, easy to conceal and quick to draw.")
_weapon("short_sword", "short sword", "sword", 150, 35,
        (_slash(20000, 4000), _stab(50, 4000, 1.1)), min_size=17500)
_weapon("sword", "sword", "sword", 200, 45,
        (_slash(25000, 4500), _stab(60, 4500, 1.1)), min_size=21000)
_weapon("long_sword", "long sword", "sword", 300, 60,
        (_slash(40000, 5000), _stab(80, 5000, 1.05)), min_size=27500,
        two_handed_size=45000)
_weapon("two_handed_sword", "two-handed sword", "sword", 500, 90,
        (_slash(60000, 6000, 1.1), _stab(120, 6000)), min_size=45000,
        two_handed_size=75000, plural="two-handed swords")
_weapon("scimitar", "scimitar", "sword", 250, 55,
        (_slash(35000, 5000, 1.1),), min_size=25000)
_weapon("axe", "axe", "axe", 250, 40,
        (_hack(40000, 4000), _bash(200, 800)), min_size=22500)
_weapon("battle_axe", "battle axe", "axe", 400, 70,
        (_hack(60000, 5000, 1.05), _bash(400, 1000)), min_size=32500,
        two_handed_size=55000)
_weapon("great_axe", "great axe", "axe", 600, 100,
        (_hack(90000, 6000, 1.1),), min_size=50000, two_handed_size=80000)
_weapon("mace", "mace", "mace", 300, 40,
        (_bash(20, 1500, 1.05),), min_size=27500)
_weapon("morningstar", "morningstar", "mace", 350, 55,
        (_bash(10, 2500, 1.05), _stab(20, 2000)), min_size=30000)
_weapon("warhammer", "war hammer", "hammer", 300, 50,
        (_bash(10, 2000, 1.1),), min_size=25000)
_weapon("maul", "maul", "hammer", 600, 80,
        (_bash(20, 3000, 1.1),), min_size=50000, two_handed_size=80000)
_weapon("spear", "spear", "spear", 250, 30,
        (_stab(20, 8000, 1.1), _bash(400, 500)), min_size=22500,
        glyph="/", desc="A long shaft with a leaf-shaped head. Reach is life.")
_weapon("pike", "pike", "spear", 450, 50,
        (_stab(25, 12000, 1.05),), min_size=42500, two_handed_size=60000)
_weapon("halberd", "halberd", "axe", 500, 75,
        (_hack(50000, 5000), _stab(30, 9000)), min_size=45000,
        two_handed_size=65000)
_weapon("flail", "flail", "mace", 350, 55,
        (_bash(15, 2200, 1.15),), min_size=30000)
_weapon("whip", "whip", "whip", 100, 25,
        (LASH,), min_size=15000, mats=("LEATHER",))
_weapon("pick", "pick", "pick", 300, 35,
        (_stab(10, 6000), _bash(200, 800)), min_size=27500,
        desc="A miner's tool that punches through stone, and skulls.")
_weapon("crossbow", "crossbow", "crossbow", 400, 60,
        (_bash(400, 500),), min_size=27500, mats=("WOOD", "METAL", "BONE"),
        ranged="bolt", shoot_force=1000, glyph="}")
_weapon("bow", "bow", "bow", 200, 45,
        (_bash(200, 400),), min_size=22500, mats=("WOOD",),
        ranged="arrow", shoot_force=800, glyph="}")
_weapon("sling", "sling", "sling", 50, 10,
        (_bash(50, 200),), min_size=10000, mats=("LEATHER", "CLOTH"),
        ranged="stone", shoot_force=500, glyph="}")

_add(ItemDef("bolt", "bolt", "bolts", "ammo", "|", 20, 2, ("METAL", "WOOD", "BONE"),
             weapon=WeaponDef("crossbow", 0, 0, (_stab(5, 6000),)),
             stack=True, flags=frozenset({"AMMO"})))
_add(ItemDef("arrow", "arrow", "arrows", "ammo", "|", 20, 2, ("METAL", "WOOD", "BONE"),
             weapon=WeaponDef("bow", 0, 0, (_stab(5, 5000),)),
             stack=True, flags=frozenset({"AMMO"})))
_add(ItemDef("stone_ammo", "sling stone", "sling stones", "ammo", "*", 30, 1,
             ("STONE",), weapon=WeaponDef("sling", 0, 0, (_bash(20, 1000),)),
             stack=True, flags=frozenset({"AMMO"})))

# --------------------------------------------------------------------------- #
# Armour and clothing
# --------------------------------------------------------------------------- #

HEAD = ("head",)
TORSO = ("torso",)
ARMS = ("arm",)
HANDS = ("hand",)
LEGS = ("leg",)
FEET = ("foot",)
NECK = ("neck",)

_armor("cap", "cap", "armor", HEAD, 100, 15, 1, 1, mats=("LEATHER",), glyph="^")
_armor("helm", "helm", "armor", HEAD, 200, 40, 3, 3, glyph="^")
_armor("great_helm", "great helm", "armor", HEAD + NECK, 280, 60, 4, 4, glyph="^")
_armor("mail_shirt", "mail shirt", "armor", TORSO + ARMS, 600, 90, 2, 3, glyph="[")
_armor("breastplate", "breastplate", "armor", TORSO, 700, 120, 4, 5, glyph="[")
_armor("leather_armor", "cuirass", "armor", TORSO + ARMS, 400, 40, 2, 2,
       mats=("LEATHER",), plural="cuirasses", glyph="[")
_armor("chain_leggings", "chain leggings", "armor", LEGS, 400, 60, 2, 3,
       plural="pairs of chain leggings", glyph="[")
_armor("greaves", "greaves", "armor", LEGS, 500, 80, 4, 4,
       plural="pairs of greaves", glyph="[")
_armor("gauntlets", "gauntlets", "armor", HANDS, 150, 35, 2, 3,
       plural="pairs of gauntlets", glyph="]")
_armor("high_boots", "high boots", "armor", FEET + LEGS, 300, 45, 2, 2,
       mats=("LEATHER", "METAL"), plural="pairs of high boots", glyph="]")
_armor("shield", "shield", "cover", (), 500, 50, 3, 4, category="shield",
       mats=("WOOD", "METAL"), flags=("SHIELD",), glyph=")")
_armor("buckler", "buckler", "cover", (), 250, 30, 2, 2, category="shield",
       mats=("WOOD", "METAL"), flags=("SHIELD",), glyph=")")

_armor("cloak", "cloak", "cover", TORSO + ARMS + LEGS, 300, 15, 1, 0,
       category="clothing", mats=("CLOTH", "LEATHER"), glyph="(")
_armor("robe", "robe", "over", TORSO + ARMS + LEGS, 250, 12, 1, 0,
       category="clothing", mats=("CLOTH",), glyph="(")
_armor("tunic", "tunic", "under", TORSO + ARMS, 150, 8, 1, 0,
       category="clothing", mats=("CLOTH", "LEATHER"), glyph="(")
_armor("trousers", "trousers", "under", LEGS, 150, 8, 1, 0,
       category="clothing", mats=("CLOTH", "LEATHER"),
       plural="pairs of trousers", glyph="(")
_armor("shoes", "shoes", "under", FEET, 120, 6, 1, 0,
       category="clothing", mats=("LEATHER", "CLOTH"),
       plural="pairs of shoes", glyph="]")
_armor("socks", "socks", "under", FEET, 40, 3, 1, 0,
       category="clothing", mats=("CLOTH",), plural="pairs of socks", glyph="]")
_armor("mittens", "mittens", "under", HANDS, 60, 4, 1, 0,
       category="clothing", mats=("CLOTH", "LEATHER"),
       plural="pairs of mittens", glyph="]")
_armor("hood", "hood", "over", HEAD + NECK, 80, 5, 1, 0,
       category="clothing", mats=("CLOTH", "LEATHER"), glyph="^")

# --------------------------------------------------------------------------- #
# Food, drink and tools
# --------------------------------------------------------------------------- #


def _food(
    iid: str, name: str, volume: int, value: int, nutrition: int,
    *, plural: str = "", mats: Tuple[str, ...] = ("EDIBLE",), glyph: str = "%",
    hydration: int = 0, desc: str = "",
) -> ItemDef:
    return _add(ItemDef(
        id=iid, name=name, plural=plural or (name + "s"), category="food",
        glyph=glyph, volume=volume, value=value, materials=mats,
        nutrition=nutrition, hydration=hydration, stack=True,
        flags=frozenset({"EDIBLE"}), description=desc,
    ))


_food("meat", "meat", 100, 3, 700, plural="pieces of meat")
_food("cooked_meat", "roast", 100, 8, 1100, desc="Charred over a campfire.")
_food("fish_food", "fish", 80, 3, 500, plural="fish")
_food("bread", "biscuit", 60, 4, 600)
_food("cheese", "cheese", 60, 6, 650, plural="wedges of cheese")
_food("plump_helmet", "plump helmet", 50, 2, 450, mats=("EDIBLE",),
      desc="A fat purple mushroom. The staple of dwarven life.")
_food("cave_wheat", "cave wheat", 40, 2, 300)
_food("berries", "berries", 30, 1, 200, plural="handfuls of berries")
_food("prepared_meal", "fine meal", 120, 20, 1600, plural="fine meals")

for _did, _dname, _dval, _hyd, _nut in (
    ("water_drink", "water", 1, 900, 0),
    ("dwarven_ale", "dwarven ale", 6, 800, 120),
    ("wine", "wine", 8, 800, 100),
    ("rum", "rum", 8, 700, 100),
    ("beer", "beer", 5, 850, 110),
    ("mead", "mead", 9, 800, 140),
):
    _add(ItemDef(_did, _dname, _dname, "drink", "!", 100, _dval, ("LIQUID",),
                 nutrition=_nut, hydration=_hyd, stack=True,
                 flags=frozenset({"DRINK"})))


def _tool(
    iid: str, name: str, volume: int, value: int,
    *, glyph: str = "(", mats: Tuple[str, ...] = ("METAL", "WOOD"),
    plural: str = "", flags: Tuple[str, ...] = ("TOOL",), category: str = "tool",
    desc: str = "",
) -> ItemDef:
    return _add(ItemDef(
        id=iid, name=name, plural=plural or (name + "s"), category=category,
        glyph=glyph, volume=volume, value=value, materials=mats,
        flags=frozenset(flags), description=desc,
    ))


_tool("backpack", "backpack", 300, 20, mats=("LEATHER", "CLOTH"),
      flags=("TOOL", "CONTAINER", "BAG"), desc="Doubles what you can carry.")
_tool("waterskin", "waterskin", 150, 10, mats=("LEATHER",),
      flags=("TOOL", "CONTAINER"), glyph="!")
_tool("flask", "flask", 120, 12, mats=("METAL", "GLASS"),
      flags=("TOOL", "CONTAINER"), glyph="!")
_tool("quiver", "quiver", 200, 15, mats=("LEATHER",),
      flags=("TOOL", "CONTAINER", "QUIVER"))
_tool("rope", "rope", 200, 12, mats=("CLOTH", "ORGANIC"), desc="For climbing down.")
_tool("torch", "torch", 100, 5, mats=("WOOD",), flags=("TOOL", "LIGHT", "FLAMMABLE"),
      glyph="~", desc="Burns for a while and keeps the dark at arm's length.")
_tool("lantern", "lantern", 200, 40, mats=("METAL",), flags=("TOOL", "LIGHT"),
      glyph="~")
_tool("lockpick", "lockpick", 30, 15)
_tool("whetstone", "whetstone", 100, 8, mats=("STONE",))
_tool("bandage", "bandage", 30, 14, mats=("CLOTH",), flags=("TOOL", "MEDICAL"),
      desc="Clean cloth. Worth more than a sword when you are bleeding.")
_tool("splint", "splint", 80, 18, mats=("WOOD", "METAL"),
      flags=("TOOL", "MEDICAL"))
_tool("crutch", "crutch", 200, 8, mats=("WOOD",), flags=("TOOL", "MEDICAL"))
_tool("flint_and_steel", "flint and steel", 40, 10, mats=("METAL",),
      plural="flint and steel sets", flags=("TOOL", "FIRE"))
_tool("shovel", "shovel", 300, 18)
_tool("fishing_rod", "fishing rod", 200, 12, mats=("WOOD",))
_tool("instrument", "lute", 300, 40, mats=("WOOD",), flags=("TOOL", "INSTRUMENT"))
_tool("book", "book", 200, 60, mats=("ORGANIC",), flags=("BOOK",), category="book",
      glyph="?", desc="Somebody's collected knowledge, bound in leather.")

_add(ItemDef("coin", "coin", "coins", "coin", "$", 1, 1, ("METAL",),
             stack=True, flags=frozenset({"COIN"})))
_add(ItemDef("gem", "gem", "gems", "gem", "*", 10, 100, ("GEM",),
             stack=False, flags=frozenset({"GEM"})))
_add(ItemDef("rough_gem", "rough gem", "rough gems", "gem", "*", 20, 30, ("GEM",),
             stack=False, flags=frozenset({"GEM"})))
_add(ItemDef("boulder", "boulder", "boulders", "misc", "*", 3000, 3, ("STONE",)))
_add(ItemDef("log", "log", "logs", "misc", "/", 4000, 4, ("WOOD",),
             flags=frozenset({"FLAMMABLE"})))
_add(ItemDef("bone_item", "bone", "bones", "remains", "%", 60, 2, ("BONE",),
             stack=True))
_add(ItemDef("skull", "skull", "skulls", "remains", "%", 200, 5, ("BONE",)))
_add(ItemDef("hide", "hide", "hides", "remains", "%", 300, 10, ("LEATHER",),
             stack=True))
_add(ItemDef("corpse", "corpse", "corpses", "corpse", "%", 60000, 0, ("ORGANIC",),
             flags=frozenset({"CORPSE", "EDIBLE"}), nutrition=2500))
_add(ItemDef("severed_part", "severed part", "severed parts", "remains", "%",
             500, 0, ("ORGANIC",), flags=frozenset({"CORPSE", "EDIBLE"}),
             nutrition=300))

# Furniture found in generated sites.
for _fid, _fname, _fglyph, _fvol, _fval in (
    ("bed", "bed", "=", 4000, 30),
    ("table", "table", "=", 4000, 25),
    ("chair", "chair", "=", 2000, 20),
    ("chest", "chest", "=", 5000, 35),
    ("cabinet", "cabinet", "=", 5000, 35),
    ("barrel", "barrel", "=", 6000, 20),
    ("bin", "bin", "=", 5000, 18),
    ("coffer", "coffer", "=", 5000, 40),
    ("statue", "statue", "&", 30000, 200),
    ("altar", "altar", "_", 20000, 300),
):
    _add(ItemDef(_fid, _fname, _fname + "s", "furniture", _fglyph, _fvol, _fval,
                 ("WOOD", "STONE", "METAL"), flags=frozenset({"FURNITURE"})))

_add(ItemDef("mechanism", "mechanism", "mechanisms", "tool", "*", 200, 30,
             ("STONE", "METAL", "WOOD"), stack=False,
             description="Levers, gears and a length of chain. Everything "
                         "clever a fortress does runs on these."))

# Jewellery. Worth many times the stone it is cut from, which is the point.
for _jid, _jname, _jplural, _jvol, _jval in (
    ("crown", "crown", "crowns", 400, 300),
    ("amulet", "amulet", "amulets", 120, 120),
    ("ring", "ring", "rings", 40, 90),
    ("earring", "earring", "earrings", 30, 70),
    ("bracelet", "bracelet", "bracelets", 90, 100),
):
    _add(ItemDef(_jid, _jname, _jplural, "gem", '"', _jvol, _jval,
                 ("METAL", "STONE", "GEM"), stack=False))


def get(iid: str) -> ItemDef:
    """Look up an item definition, defaulting to a rock."""
    return ITEMS.get(iid) or ITEMS["boulder"]


def exists(iid: str) -> bool:
    """True if *iid* names a known item."""
    return iid in ITEMS


def by_category(cat: str) -> List[ItemDef]:
    """Every item in a category."""
    return [i for i in ITEMS.values() if i.category == cat]


def weapons_for_skill(skill: str) -> List[ItemDef]:
    """Every weapon that trains *skill*."""
    return [i for i in ITEMS.values() if i.weapon and i.weapon.skill == skill]


def melee_weapons() -> List[ItemDef]:
    """Every non-ranged weapon."""
    return [
        i for i in ITEMS.values()
        if i.weapon and not i.weapon.is_ranged and i.category == "weapon"
    ]


def ranged_weapons() -> List[ItemDef]:
    """Every ranged weapon."""
    return [i for i in ITEMS.values() if i.weapon and i.weapon.is_ranged]


def armor_pieces() -> List[ItemDef]:
    """Every armour or clothing item."""
    return [i for i in ITEMS.values() if i.armor is not None]


def ammo_for(weapon_def: ItemDef) -> Optional[str]:
    """The ammunition item id a ranged weapon needs."""
    if weapon_def.weapon and weapon_def.weapon.ranged:
        return weapon_def.weapon.ranged if weapon_def.weapon.ranged != "stone" \
            else "stone_ammo"
    return None


def validate() -> List[str]:
    """Check item data for internal consistency."""
    problems: List[str] = []
    for iid, it in ITEMS.items():
        if it.category not in CATEGORIES:
            problems.append("%s: unknown category %s" % (iid, it.category))
        if it.volume <= 0:
            problems.append("%s: non-positive volume" % iid)
        if it.weapon and not it.weapon.attacks:
            problems.append("%s: weapon with no attacks" % iid)
        if it.weapon and it.weapon.ranged:
            ammo = it.weapon.ranged if it.weapon.ranged != "stone" else "stone_ammo"
            if ammo not in ITEMS:
                problems.append("%s: unknown ammo %s" % (iid, it.weapon.ranged))
        if not it.materials:
            problems.append("%s: no material classes" % iid)
    return problems
