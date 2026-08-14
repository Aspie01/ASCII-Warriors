"""What workshops make, and what they need to make it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..data import items as item_data
from ..data import materials as mat_data


@dataclass(frozen=True)
class Recipe:
    """One thing a workshop can produce."""

    id: str
    name: str
    workshop: str
    skill: str
    #: ``(requirement, count)``. A requirement is an item def id, a class
    #: (``STONE``/``WOOD``/``METAL``/``BAR``/``FUEL``/``FLUX``/``FOOD``/
    #: ``PLANT``), or ``bar:iron`` for one particular metal.
    inputs: Tuple[Tuple[str, int], ...]
    output: str
    out_count: int
    work: int
    description: str = ""
    #: Forced output material, for alloys: bronze is not made of copper.
    out_material: str = ""


RECIPES: Dict[str, Recipe] = {}


def _r(rid, name, shop, skill, inputs, output, out_count=1, work=200, desc="",
       out_material=""):
    rec = Recipe(rid, name, shop, skill, inputs, output, out_count, work, desc,
                 out_material)
    RECIPES[rid] = rec
    return rec


# -- carpenter --------------------------------------------------------------- #
_r("wood_bed", "Wooden bed", "carpenter", "carpentry", (("WOOD", 1),), "bed")
_r("wood_table", "Wooden table", "carpenter", "carpentry", (("WOOD", 1),), "table")
_r("wood_chair", "Wooden chair", "carpenter", "carpentry", (("WOOD", 1),), "chair")
_r("wood_barrel", "Barrel", "carpenter", "carpentry", (("WOOD", 1),), "barrel")
_r("wood_cabinet", "Cabinet", "carpenter", "carpentry", (("WOOD", 1),), "cabinet")
_r("wood_shield", "Wooden shield", "carpenter", "carpentry", (("WOOD", 1),),
   "shield", 1, 240)
_r("wood_bolts", "Wooden bolts", "carpenter", "bowyer", (("WOOD", 1),),
   "bolt", 15, 200)
_r("wood_bow", "Bow", "carpenter", "bowyer", (("WOOD", 1),), "bow", 1, 280)
_r("wood_crutch", "Crutch", "carpenter", "carpentry", (("WOOD", 1),), "crutch")
# Instruments. A tavern with nothing to play in it is a room with barrels,
# and a musical form asks for a particular instrument by name.
_r("wood_lute", "Lute", "carpenter", "carpentry", (("WOOD", 1),), "lute",
   1, 320, "A musician without one is a musician nobody listens to.")
_r("wood_flute", "Flute", "carpenter", "carpentry", (("WOOD", 1),), "flute",
   1, 200)
_r("wood_harp", "Harp", "carpenter", "carpentry", (("WOOD", 2),), "harp",
   1, 460)
_r("wood_splint", "Splint", "carpenter", "carpentry", (("WOOD", 1),), "splint", 3)

# -- mason ------------------------------------------------------------------- #
_r("stone_table", "Stone table", "mason", "masonry", (("STONE", 1),), "table")
_r("stone_chair", "Stone chair", "mason", "masonry", (("STONE", 1),), "chair")
_r("stone_door", "Stone door", "mason", "masonry", (("STONE", 1),), "chest")
_r("stone_coffer", "Stone coffer", "mason", "masonry", (("STONE", 1),), "coffer")
_r("stone_statue", "Statue", "mason", "masonry", (("STONE", 1),), "statue", 1, 320,
   "Dwarves are unreasonably cheered by a good statue.")
_r("stone_altar", "Altar", "mason", "masonry", (("STONE", 1),), "altar", 1, 300)

# -- craftsdwarf ------------------------------------------------------------- #
_r("stone_crafts", "Stone crafts", "craftsdwarf", "crafting", (("STONE", 1),),
   "gem", 2, 220, "Trinkets. Worth more to a caravan than to you.")
_r("bone_crafts", "Bone crafts", "craftsdwarf", "crafting",
   (("bone_item", 2),), "gem", 1, 200)
_r("stone_ammo", "Sling stones", "craftsdwarf", "crafting", (("STONE", 1),),
   "stone_ammo", 12, 160)
_r("leather_armor", "Leather cuirass", "craftsdwarf", "leatherwork",
   (("hide", 2),), "leather_armor", 1, 260)
_r("leather_bag", "Backpack", "craftsdwarf", "leatherwork", (("hide", 1),),
   "backpack", 1, 200)
_r("cloth_bandage", "Bandages", "craftsdwarf", "leatherwork", (("CLOTH", 1),),
   "bandage", 4, 160,
   "Out of a hide or a bolt of cloth, whichever the fortress has.")
_r("spin_wool", "Spin wool", "craftsdwarf", "leatherwork", (("wool", 2),),
   "cloth", 1, 180, "Two fleeces make a bolt.", out_material="wool_cloth")
_r("rope", "Rope", "craftsdwarf", "crafting", (("hide", 2),), "rope", 1, 180)

# -- the clothier ------------------------------------------------------------ #
# v3.18 dressed every dwarf and v3.20 wears those clothes out, so a fortress
# needs to be able to make more. Without these a long game ends with dwarves
# in rags, and since v3.18 rags are how a dwarf freezes.
_r("sew_tunic", "Tunic", "craftsdwarf", "leatherwork", (("CLOTH", 1),),
   "tunic", 1, 160, "Somebody has to keep making these.",
   out_material="wool_cloth")
_r("sew_trousers", "Trousers", "craftsdwarf", "leatherwork", (("CLOTH", 1),),
   "trousers", 1, 160, out_material="wool_cloth")
_r("sew_cloak", "Cloak", "craftsdwarf", "leatherwork", (("CLOTH", 2),),
   "cloak", 1, 220, "For whoever works above ground.",
   out_material="wool_cloth")
_r("sew_hood", "Hood", "craftsdwarf", "leatherwork", (("CLOTH", 1),),
   "hood", 1, 140, out_material="wool_cloth")
_r("make_shoes", "Shoes", "craftsdwarf", "leatherwork", (("hide", 1),),
   "shoes", 1, 180)
_r("hide_drum", "Drum", "craftsdwarf", "leatherwork", (("hide", 1), ("WOOD", 1)),
   "drum", 1, 240)
_r("bone_flute", "Bone flute", "craftsdwarf", "crafting",
   (("bone_item", 1),), "flute", 1, 220)
_r("torches", "Torches", "craftsdwarf", "crafting", (("WOOD", 1),), "torch", 4, 150)
_r("mechanisms", "Mechanisms", "craftsdwarf", "mechanics", (("STONE", 1),),
   "mechanism", 2, 240,
   "Everything a fortress does cleverly needs one of these.")

# -- wood furnace ------------------------------------------------------------ #
_r("burn_charcoal", "Burn charcoal", "wood_furnace", "smelting",
   (("WOOD", 1),), "charcoal", 2, 240,
   "One log, slowly, into the fuel everything else needs.",
   out_material="charcoal")

# -- smelter ----------------------------------------------------------------- #
_r("smelt_ore", "Smelt ore", "smelter", "smelting",
   (("ore", 1), ("FUEL", 1)), "bar", 1, 300,
   "Whatever metal the ore was, the bar is.")
_r("make_bronze", "Alloy bronze", "smelter", "smelting",
   (("bar:copper", 1), ("bar:tin", 1), ("FUEL", 1)), "bar", 2, 360,
   "Copper and tin. Twice the metal and better than either.",
   out_material="bronze")
_r("make_steel", "Make steel", "smelter", "smelting",
   (("bar:iron", 1), ("FLUX", 1), ("FUEL", 2)), "bar", 1, 480,
   "Iron, flux stone and a great deal of fuel. The best a fortress makes.",
   out_material="steel")

# -- forge ------------------------------------------------------------------- #
# Everything here takes bars and fuel. A forge with no smelter behind it is an
# expensive floor.
_r("iron_dagger", "Forge dagger", "smith", "weaponsmithing",
   (("BAR", 1), ("FUEL", 1)), "dagger", 1, 340)
_r("iron_sword", "Forge short sword", "smith", "weaponsmithing",
   (("BAR", 2), ("FUEL", 1)), "short_sword", 1, 420)
_r("iron_axe", "Forge axe", "smith", "weaponsmithing",
   (("BAR", 2), ("FUEL", 1)), "axe", 1, 420)
_r("iron_spear", "Forge spear", "smith", "weaponsmithing",
   (("BAR", 1), ("FUEL", 1)), "spear", 1, 380)
_r("iron_hammer", "Forge war hammer", "smith", "weaponsmithing",
   (("BAR", 2), ("FUEL", 1)), "warhammer", 1, 420)
_r("iron_helm", "Forge helm", "smith", "armorsmithing",
   (("BAR", 1), ("FUEL", 1)), "helm", 1, 380)
_r("iron_mail", "Forge mail shirt", "smith", "armorsmithing",
   (("BAR", 3), ("FUEL", 1)), "mail_shirt", 1, 520)
_r("iron_greaves", "Forge greaves", "smith", "armorsmithing",
   (("BAR", 2), ("FUEL", 1)), "greaves", 1, 440)
_r("iron_shield", "Forge shield", "smith", "armorsmithing",
   (("BAR", 1), ("FUEL", 1)), "shield", 1, 360)
_r("iron_bolts", "Forge bolts", "smith", "weaponsmithing",
   (("BAR", 1), ("FUEL", 1)), "bolt", 20, 300)
_r("metal_mechanisms", "Forge mechanisms", "smith", "mechanics",
   (("BAR", 1), ("FUEL", 1)), "mechanism", 4, 320,
   "Metal ones, for when the stone ones keep jamming.")

# -- still ------------------------------------------------------------------- #
_r("brew_ale", "Brew dwarven ale", "still", "brewing", (("PLANT", 2),),
   "dwarven_ale", 5, 200,
   "A dwarf without drink works slowly and complains constantly.")
_r("brew_wine", "Brew wine", "still", "brewing", (("PLANT", 2),), "wine", 5, 200)

# -- kitchen ----------------------------------------------------------------- #
_r("cook_roast", "Cook a roast", "kitchen", "cooking", (("FOOD", 2),),
   "prepared_meal", 2, 220, "Worth far more nourishment than the parts.")
_r("cook_biscuits", "Bake biscuits", "kitchen", "cooking", (("PLANT", 2),),
   "bread", 4, 180)
_r("make_cheese", "Make cheese", "kitchen", "cooking", (("milk", 2),),
   "cheese", 3, 200, "Milk keeps badly. Cheese does not.")

# -- butcher ----------------------------------------------------------------- #
_r("butcher_corpse", "Butcher a corpse", "butcher", "butchery",
   (("corpse", 1),), "meat", 6, 200)

# -- magma workshops --------------------------------------------------------- #
# The same work with the fuel line struck out. That is the whole reward for
# bringing magma to where you wanted it.
for _rid, _rec in list(RECIPES.items()):
    if _rec.workshop not in ("smelter", "smith"):
        continue
    _shop = "magma_smelter" if _rec.workshop == "smelter" else "magma_forge"
    _inputs = tuple((req, n) for req, n in _rec.inputs if req != "FUEL")
    _r("magma_" + _rid, _rec.name, _shop, _rec.skill, _inputs, _rec.output,
       _rec.out_count, _rec.work, _rec.description, _rec.out_material)

#: Material class -> the item definitions that satisfy it.
CLASS_ITEMS: Dict[str, Tuple[str, ...]] = {
    "STONE": ("boulder",),
    "WOOD": ("log",),
    "METAL": ("bar",),
    "BAR": ("bar",),
    "ORE": ("ore",),
    "FUEL": ("charcoal", "coal"),
    "FLUX": ("boulder",),
    "CLOTH": ("cloth", "hide"),
    "PLANT": ("plump_helmet", "cave_wheat", "berries"),
    "FOOD": ("meat", "cooked_meat", "fish_food", "plump_helmet", "cheese",
             "bread", "berries", "cave_wheat"),
}


def recipes_for(workshop: str) -> List[Recipe]:
    """Everything a given workshop can make."""
    return [r for r in RECIPES.values() if r.workshop == workshop]


def satisfies(item, requirement: str) -> bool:
    """True if an item can serve as one unit of a recipe input."""
    if ":" in requirement:
        # ``bar:copper``: this item, and this material. Alloys care.
        def_id, _, material = requirement.partition(":")
        return item.def_id == def_id and item.material == material
    allowed = CLASS_ITEMS.get(requirement)
    if allowed is not None:
        if requirement == "FLUX":
            return (item.def_id == "boulder"
                    and item.material in mat_data.FLUX_STONES)
        return item.def_id in allowed
    return item.def_id == requirement


def find_inputs(recipe: Recipe, pool: Sequence) -> Optional[List]:
    """Pick items from *pool* satisfying a recipe, or ``None`` if short."""
    chosen: List = []
    used = set()
    for requirement, count in recipe.inputs:
        found = 0
        for item in pool:
            if id(item) in used:
                continue
            if not satisfies(item, requirement):
                continue
            take = min(count - found, item.count)
            if take <= 0:
                continue
            chosen.append((item, take))
            used.add(id(item))
            found += take
            if found >= count:
                break
        if found < count:
            return None
    return chosen


def output_material(recipe: Recipe, inputs: Sequence) -> str:
    """What material the product comes out as."""
    if recipe.out_material:
        return recipe.out_material
    defn = item_data.get(recipe.output)
    if recipe.output in ("dwarven_ale", "wine"):
        return "alcohol"
    if defn.category in ("food",):
        return "meat" if recipe.output in ("prepared_meal", "meat") else "plant"
    for item, _count in inputs:
        mat = item.mat
        if "METAL" in defn.materials and mat.is_metal:
            return mat.id
        if "WOOD" in defn.materials and mat.category == "wood":
            return mat.id
        if "STONE" in defn.materials and mat.category == "stone":
            return mat.id
        if "LEATHER" in defn.materials and mat.category == "leather":
            return mat.id
    # Metal goods forged from ore come out as the metal the ore implies.
    if "METAL" in defn.materials:
        return "iron"
    if "WOOD" in defn.materials:
        return "oak"
    if "STONE" in defn.materials:
        return "granite"
    for item, _count in inputs:
        return item.material
    return "granite"
