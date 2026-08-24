"""Butchery, cooking and field crafting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from ..data import creatures as creature_data
from ..data import items as item_data
from .item import Item
from .skills import ability


@dataclass(frozen=True)
class Recipe:
    """One thing you can make."""

    id: str
    name: str
    skill: str
    difficulty: int
    inputs: Tuple[Tuple[str, int], ...]
    output: str
    out_count: int = 1
    needs: Tuple[str, ...] = ()
    description: str = ""


RECIPES: Dict[str, Recipe] = {}


def _r(
    rid: str, name: str, skill: str, difficulty: int,
    inputs: Tuple[Tuple[str, int], ...], output: str, out_count: int = 1,
    needs: Tuple[str, ...] = (), desc: str = "",
) -> Recipe:
    rec = Recipe(rid, name, skill, difficulty, inputs, output, out_count, needs, desc)
    RECIPES[rid] = rec
    return rec


_r("cook_meat", "Roast meat", "cooking", 0, (("meat", 1),), "cooked_meat", 1,
   ("fire",), "Raw meat over a fire keeps you alive a good deal longer.")
_r("cook_fish", "Roast fish", "cooking", 0, (("fish_food", 1),), "cooked_meat", 1,
   ("fire",))
_r("fine_meal", "Prepare a fine meal", "cooking", 3,
   (("cooked_meat", 1), ("plump_helmet", 1)), "prepared_meal", 1, ("fire",))
_r("make_torch", "Make a torch", "crafting", 0, (("log", 1),), "torch", 3, ())
_r("make_bandage", "Tear a bandage", "crafting", 0, (("CLOTH", 1),),
   "bandage", 4, (),
   "Any cloth garment will do, and a shirt is worth four bandages. "
   "Leather does not tear into dressings.")
_r("make_arrows", "Fletch arrows", "bowyer", 2, (("log", 1),), "arrow", 12, ())
_r("make_bolts", "Carve bolts", "bowyer", 2, (("log", 1),), "bolt", 12, ())
_r("make_rope", "Braid a rope", "crafting", 1, (("hide", 2),), "rope", 1, ())
# Somewhere to put the writing. Every book in the world arrived already
# written, so an adventurer had nothing blank to fill.
_r("bind_book", "Bind a blank book", "leatherwork", 2, (("hide", 2),),
   "book", 1, (), "Pages, and a cover to hold them.")
_r("tan_leather", "Tan a hide", "leatherwork", 1, (("hide", 1),), "tunic", 1, ())
_r("carve_bone_dagger", "Carve a bone dagger", "crafting", 2,
   (("bone_item", 3),), "dagger", 1, ())
_r("make_sling_stones", "Knap sling stones", "crafting", 0,
   (("boulder", 1),), "stone_ammo", 10, ())
_r("brew_ale", "Brew ale", "brewing", 2, (("plump_helmet", 3),), "dwarven_ale", 4,
   ("fire",))
_r("sharpen_weapon", "Sharpen a blade", "weaponsmithing", 1,
   (("whetstone", 1),), "whetstone", 1, ())
_r("forge_dagger", "Forge a dagger", "weaponsmithing", 3,
   (("boulder", 1),), "dagger", 1, ("fire", "anvil"))
_r("forge_spear", "Forge a spear", "weaponsmithing", 4,
   (("boulder", 2),), "spear", 1, ("fire", "anvil"))


def available(creature, game) -> List[Recipe]:
    """Every recipe the creature has the materials and facilities for."""
    out: List[Recipe] = []
    facilities = _facilities(creature, game)
    for rec in RECIPES.values():
        if any(n not in facilities for n in rec.needs):
            continue
        if not _has_inputs(creature, rec):
            continue
        out.append(rec)
    out.sort(key=lambda r: (r.skill, r.name))
    return out


def _facilities(creature, game) -> set:
    """What workshops and fires are within reach."""
    found = set()
    if game.local is None:
        return found
    from ..world import tiles as tile_data

    for dx in range(-1, 2):
        for dy in range(-1, 2):
            tid = game.local.tile(creature.x + dx, creature.y + dy, creature.z)
            t = tile_data.get(tid)
            if t.has("FIRE"):
                found.add("fire")
            if tid in ("table", "cabinet"):
                found.add("workshop")
    site = game.current_site()
    if site is not None and "forge" in site.buildings:
        found.add("anvil")
        found.add("fire")
    return found


#: What a recipe input in capitals means. An input is normally the id of one
#: item; these are kinds of thing.
#:
#: "Tear a bandage" asked for a cloak, and no adventurer has ever carried one.
#: The starting kit is armour, and `_dress` gives the rest of the world
#: outerwear a third of the time -- so the one recipe in the game that answers
#: the thing that kills adventurers could not be made by the person bleeding.
#: Eight driver runs, eight deaths, seven of them counting "bleeding, and
#: nothing to bind it with" after the third and last bandage in the kit.
#: Recipe inputs that name a *kind* of thing rather than one item id, as
#: ``need -> (item category, any one of these material flags)``.
#:
#: The flags are alternatives. `CLOTH` was the only entry and it was also the
#: only flag it would accept, which read as "a cloth garment" and was written
#: into `make_bandage` -- whose own description says **"Any garment will
#: do."** Half of what an adventurer sets out wearing is leather: the tunic
#: and the shoes carry `LEATHER`, the trousers and the cloak carry `CLOTH`.
#: So the help promised a shirt off your back and the code took two garments
#: of the four, and 75% of measured adventurers bled to death, 10.9 turns of
#: each fatal life spent with nothing left to bind a wound with.
#: Recipe inputs that name a *kind* of thing rather than one item id, as
#: ``need -> (item category, any one of these material flags)``.
#:
#: The flags are alternatives, which is a shape the table did not have when it
#: was one entry mapping to one implied flag. Nothing uses the alternation
#: today; it is here because the single-flag form read as though `CLOTH` meant
#: "a garment" and it means "a cloth garment", and that reading is what
#: `make_bandage` was documented against for four hundred versions.
CLASSES: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "CLOTH": ("clothing", ("CLOTH",)),
}


def _satisfies(item, need: str) -> bool:
    """Whether a carried item counts as one unit of a recipe input."""
    if item.def_id == need:
        return True
    found = CLASSES.get(need)
    if found is None:
        return False
    category, flags = found
    return (item.category == category
            and any(flag in item.mat.flags for flag in flags))


def _carried(creature, need: str) -> List:
    """Everything the creature has that would do for one input."""
    return [i for i in creature.inventory.items if _satisfies(i, need)]


def _has_inputs(creature, rec: Recipe) -> bool:
    """True if the creature carries everything a recipe needs."""
    for need, count in rec.inputs:
        if sum(i.count for i in _carried(creature, need)) < count:
            return False
    return True


def craft(creature, recipe: Recipe, game) -> Tuple[bool, str]:
    """Attempt a recipe. Returns ``(success, message)``."""
    if not _has_inputs(creature, recipe):
        return (False, "You lack the materials.")
    facilities = _facilities(creature, game)
    missing = [n for n in recipe.needs if n not in facilities]
    if missing:
        return (False, "You need %s." % ", ".join(missing))

    material = "iron"
    for need, count in recipe.inputs:
        left = count
        for it in _carried(creature, need):
            material = it.material
            take = min(left, it.count)
            it.count -= take
            left -= take
            if it.count <= 0:
                creature.inventory.remove(it, it.count if it.count > 0 else 1)
                if it in creature.inventory.items:
                    creature.inventory.items.remove(it)
            if left <= 0:
                break

    # Effective level, not trained level: `SkillDef.attrs` says what governs
    # each craft -- creativity, focus and a steady hand for most of them -- and
    # until now a dull smith and a brilliant one turned out the same work.
    skill_level = ability(creature, recipe.skill)
    roll = skill_level + game.rng.randint(0, 6) - recipe.difficulty
    quality = 0
    if roll >= 12:
        quality = 4
    elif roll >= 9:
        quality = 3
    elif roll >= 6:
        quality = 2
    elif roll >= 3:
        quality = 1
    elif roll < 0 and game.rng.chance(0.35):
        creature.add_exp(recipe.skill, 15)
        return (False, "You botch the work and ruin the materials.")

    out_def = item_data.get(recipe.output)
    if "EDIBLE" in out_def.materials or out_def.category in ("food", "drink"):
        material = {"cooked_meat": "meat", "prepared_meal": "meat",
                    "dwarven_ale": "alcohol"}.get(recipe.output, material)
    elif "METAL" in out_def.materials and material not in ("iron", "steel",
                                                           "copper", "bronze"):
        material = "iron"
    elif "WOOD" in out_def.materials and material in ("iron", "steel"):
        material = "oak"

    item = Item(recipe.output, material, quality=quality,
                count=recipe.out_count, maker=creature.name)
    creature.inventory.add(item)
    creature.add_exp(recipe.skill, 40)
    creature.needs.exert(15)
    return (True, "You make %s." % item.name(article=True))


def butcher_corpse(creature, corpse: Item, game) -> List[Item]:
    """Cut a corpse into meat, bone and hide."""
    if not corpse.is_corpse:
        return []
    size = int(corpse.flags.get("size", 60000))
    cid = corpse.flags.get("creature", "")
    defn = creature_data.get(cid) if cid else None
    skill = creature.skills.level("butchery")
    yield_factor = 1.0 + skill * 0.08

    meat_count = max(1, int(size / 12000.0 * yield_factor))
    bone_count = max(1, int(size / 30000.0))
    hide_count = 1 if size > 20000 else 0

    out: List[Item] = []
    if defn is not None and defn.has("UNDEAD"):
        out.append(Item("bone_item", "bone", count=bone_count))
    else:
        out.append(Item("meat", "meat", count=meat_count))
        out.append(Item("bone_item", "bone", count=bone_count))
        if hide_count:
            out.append(Item("hide", "leather", count=hide_count))
    if size > 40000 and game.rng.chance(0.5):
        out.append(Item("skull", "bone"))

    creature.inventory.remove(corpse, corpse.count)
    if corpse in creature.inventory.items:
        creature.inventory.items.remove(corpse)
    for it in out:
        creature.inventory.add(it)
    creature.add_exp("butchery", 35)
    creature.needs.exert(25)
    return out


def cook(creature, items: Sequence[Item], game) -> Optional[Item]:
    """Cook whatever raw food is supplied over a nearby fire."""
    if "fire" not in _facilities(creature, game):
        return None
    raw = [i for i in items if i.is_edible and i.def_id in ("meat", "fish_food")]
    if not raw:
        return None
    total = sum(i.count for i in raw)
    for it in raw:
        creature.inventory.remove(it, it.count)
        if it in creature.inventory.items:
            creature.inventory.items.remove(it)
    quality = min(5, int(ability(creature, "cooking")) // 3)
    out = Item("cooked_meat", "meat", quality=quality, count=total,
               maker=creature.name)
    creature.inventory.add(out)
    creature.add_exp("cooking", 30)
    return out


def can_butcher(creature) -> List[Item]:
    """Every corpse the creature is carrying."""
    return [i for i in creature.inventory.items if i.is_corpse]
