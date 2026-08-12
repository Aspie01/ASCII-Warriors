"""Item instances: a definition plus a material, a quality and some history."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..data import items as item_data
from ..data import materials as mat_data
from ..data.descriptors import (
    indefinite_article, quality_name, quality_wrap, wear_name,
)
from ..data.items import AttackDef, ItemDef
from ..data.materials import Material
from ..engine import colors
from ..engine.rng import RNG
from ..engine.screen import Frag

QUALITY_NAMES = (
    "", "well-crafted", "finely-crafted", "superior", "exceptional",
    "masterwork", "artifact",
)

#: Quality level -> value multiplier.
QUALITY_VALUE = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 10.0)
#: Quality level -> combat effectiveness multiplier.
QUALITY_BONUS = (1.0, 1.05, 1.10, 1.15, 1.20, 1.30, 1.50)


class Item:
    """One concrete object in the world."""

    _next_id = 1

    __slots__ = (
        "id", "def_id", "material", "quality", "wear", "count", "maker",
        "name_override", "artifact_id", "flags", "charges",
    )

    def __init__(
        self,
        def_id: str,
        material: str,
        *,
        quality: int = 0,
        wear: int = 0,
        count: int = 1,
        maker: str = "",
        name_override: str = "",
    ) -> None:
        self.id = Item._next_id
        Item._next_id += 1
        self.def_id = def_id
        self.material = material if mat_data.exists(material) else "iron"
        self.quality = max(0, min(6, int(quality)))
        self.wear = max(0, min(3, int(wear)))
        self.count = max(1, int(count))
        self.maker = maker
        self.name_override = name_override
        #: Set when this item is a named artifact from world history.
        self.artifact_id: Optional[int] = None
        self.flags: Dict[str, Any] = {}
        #: Torches and lanterns burn down; ammunition tracks nothing here.
        self.charges = 0

    # -- definitions ------------------------------------------------------- #

    @property
    def defn(self) -> ItemDef:
        """The underlying item definition."""
        return item_data.get(self.def_id)

    @property
    def mat(self) -> Material:
        """The material this item is made of."""
        return mat_data.get(self.material)

    @property
    def category(self) -> str:
        """Item category, e.g. ``"weapon"``."""
        return self.defn.category

    @property
    def glyph(self) -> str:
        """Map glyph."""
        return self.defn.glyph

    @property
    def color(self):
        """Display colour, taken from the material."""
        return self.mat.color

    # -- physical ---------------------------------------------------------- #

    @property
    def unit_weight(self) -> float:
        """Weight of a single unit in kilograms."""
        return self.mat.weight_of(self.defn.volume)

    @property
    def weight(self) -> float:
        """Total weight of the stack in kilograms."""
        return self.unit_weight * self.count

    @property
    def volume(self) -> int:
        """Total volume of the stack in cm^3."""
        return self.defn.volume * self.count

    @property
    def value(self) -> int:
        """Trade value of the whole stack.

        The material matters, but not linearly: a steel sword should be worth
        several times an iron one, not thirty times.
        """
        base = max(1, self.defn.value * (2 + max(1, self.mat.value)) // 8)
        v = base * QUALITY_VALUE[min(self.quality, 6)]
        v *= (1.0 - 0.15 * self.wear)
        return max(1, int(v * self.count))

    def quality_bonus(self) -> float:
        """Combat/armour effectiveness multiplier from quality."""
        return QUALITY_BONUS[min(self.quality, 6)]

    def wear_factor(self) -> float:
        """Effectiveness multiplier lost to wear, 1.0 down to 0.55."""
        return 1.0 - 0.15 * self.wear

    # -- naming ------------------------------------------------------------ #

    def base_name(self, plural: bool = False) -> str:
        """Material plus item name, without quality markers."""
        if self.name_override:
            return self.name_override
        d = self.defn
        noun = d.plural if plural else d.name
        if d.category in ("food", "drink") and self.material in (
            "meat", "plant", "cheese", "bread", "alcohol", "water"
        ):
            return noun
        if d.category == "corpse":
            return noun
        adjective = self.mat.adjective
        if noun.lower().startswith(adjective.lower()):
            return noun
        return "%s %s" % (adjective, noun)

    def name(
        self, *, article: bool = False, plural: bool = False, full: bool = True
    ) -> str:
        """The display name, e.g. ``"a masterwork steel long sword"``."""
        show_plural = plural or (self.count > 1)
        base = self.base_name(show_plural)
        if not full:
            return base
        name = quality_wrap(self.quality, base)
        w = wear_name(self.wear)
        if w:
            name = "%s (%s)" % (name, w)
        if self.count > 1:
            return "%d %s" % (self.count, name)
        if article:
            return "%s %s" % (indefinite_article(base), name)
        return name

    def colored_name(self, *, article: bool = False) -> List[Frag]:
        """The display name as coloured fragments."""
        text = self.name(article=article)
        col = self.color
        if self.quality >= 5:
            col = colors.UI["accent"]
        if self.artifact_id is not None:
            col = colors.MAGIC
        return [Frag(text, col)]

    def full_description(self) -> List[str]:
        """Multi-line description for the examine screen."""
        d = self.defn
        lines: List[str] = [self.name(article=True)]
        if d.description:
            lines.append(d.description)
        lines.append(
            "Material: %s (density %d kg/m3)" % (self.mat.name, self.mat.density)
        )
        lines.append("Weight: %.2f kg   Value: %d" % (self.weight, self.value))
        if self.quality:
            lines.append("Quality: %s" % quality_name(self.quality))
        if self.wear:
            lines.append("Condition: %s" % ("worn", "tattered", "falling apart")[
                min(2, self.wear - 1)
            ])
        if self.maker:
            lines.append("Crafted by %s." % self.maker)
        if d.weapon:
            lines.append("Weapon skill: %s" % d.weapon.skill)
            for a in d.weapon.attacks:
                lines.append(
                    "  %s (%s), contact %d, penetration %d"
                    % (a.name, a.kind, a.contact, a.penetration)
                )
            if d.weapon.two_handed_size:
                lines.append(
                    "Needs two hands for creatures under %d cm3."
                    % d.weapon.two_handed_size
                )
        if d.armor:
            lines.append(
                "Armor: layer %s, level %d, thickness %d"
                % (d.armor.layer, d.armor.armor_level, d.armor.thickness)
            )
            if d.armor.coverage:
                lines.append("Covers: %s" % ", ".join(d.armor.coverage))
        if d.nutrition:
            lines.append("Nutrition: %d" % d.nutrition)
        if d.hydration:
            lines.append("Hydration: %d" % d.hydration)
        return lines

    # -- predicates -------------------------------------------------------- #

    @property
    def is_weapon(self) -> bool:
        """True for anything with a weapon definition."""
        return self.defn.weapon is not None

    @property
    def is_ranged(self) -> bool:
        """True for bows, crossbows and slings."""
        w = self.defn.weapon
        return bool(w and w.ranged)

    @property
    def is_armor(self) -> bool:
        """True for anything worn for protection."""
        return self.defn.armor is not None

    @property
    def is_shield(self) -> bool:
        """True for shields and bucklers."""
        return self.defn.has("SHIELD")

    @property
    def is_edible(self) -> bool:
        """True for food."""
        return self.defn.has("EDIBLE") or self.defn.nutrition > 0

    @property
    def is_drink(self) -> bool:
        """True for drinks."""
        return self.defn.has("DRINK") or self.defn.hydration > 0

    @property
    def is_ammo(self) -> bool:
        """True for arrows, bolts and sling stones."""
        return self.defn.has("AMMO")

    @property
    def is_light(self) -> bool:
        """True for torches and lanterns."""
        return self.defn.has("LIGHT")

    @property
    def is_corpse(self) -> bool:
        """True for corpses and severed parts."""
        return self.defn.has("CORPSE")

    @property
    def is_container(self) -> bool:
        """True for packs, quivers and flasks."""
        return self.defn.has("CONTAINER")

    def attacks(self) -> List[AttackDef]:
        """Every attack this item can make."""
        w = self.defn.weapon
        return list(w.attacks) if w else []

    def damage_class(self) -> str:
        """``"edge"`` or ``"blunt"`` for the item's best attack."""
        atk = self.attacks()
        if not atk:
            return "blunt"
        if any(a.kind == "edge" for a in atk) and self.mat.can_hold_edge:
            return "edge"
        return "blunt"

    # -- stacking and wear ------------------------------------------------- #

    def stack_with(self, other: "Item") -> bool:
        """Merge *other* into this stack if they are identical; True on success."""
        if other is self or not self.defn.stack:
            return False
        if (
            other.def_id != self.def_id
            or other.material != self.material
            or other.quality != self.quality
            or other.wear != self.wear
            or other.artifact_id is not None
            or self.artifact_id is not None
        ):
            return False
        self.count += other.count
        other.count = 0
        return True

    def split(self, n: int) -> "Item":
        """Split *n* units off this stack into a new item."""
        n = max(1, min(n, self.count))
        clone = Item(
            self.def_id, self.material, quality=self.quality, wear=self.wear,
            count=n, maker=self.maker, name_override=self.name_override,
        )
        clone.artifact_id = self.artifact_id
        self.count -= n
        return clone

    def wear_tick(self, rng: RNG) -> bool:
        """Advance wear with a small chance; True if the item is destroyed."""
        if self.artifact_id is not None:
            return False
        chance = 0.004 if self.mat.is_metal else 0.012
        if not rng.chance(chance):
            return False
        self.wear += 1
        if self.wear > 3:
            return True
        return False

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the item."""
        return {
            "id": self.id,
            "def": self.def_id,
            "mat": self.material,
            "q": self.quality,
            "w": self.wear,
            "n": self.count,
            "maker": self.maker,
            "name": self.name_override,
            "art": self.artifact_id,
            "flags": self.flags,
            "charges": self.charges,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Item":
        """Rebuild an item, preserving its id."""
        it = cls(
            str(d.get("def", "boulder")), str(d.get("mat", "iron")),
            quality=int(d.get("q", 0)), wear=int(d.get("w", 0)),
            count=int(d.get("n", 1)), maker=str(d.get("maker", "")),
            name_override=str(d.get("name", "")),
        )
        it.id = int(d.get("id", it.id))
        Item._next_id = max(Item._next_id, it.id + 1)
        it.artifact_id = d.get("art")
        it.flags = dict(d.get("flags") or {})
        it.charges = int(d.get("charges", 0))
        return it

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Item(%s)" % self.name()


# --------------------------------------------------------------------------- #
# Construction helpers
# --------------------------------------------------------------------------- #


def _materials_for(defn: ItemDef, tier: int) -> List[str]:
    """Candidate material ids for an item definition at a wealth tier."""
    out: List[str] = []
    for flag in defn.materials:
        if flag == "EDIBLE":
            out.extend(["meat", "plant", "bread", "cheese"])
        elif flag == "LIQUID":
            out.extend(["water", "alcohol"])
        elif flag == "ORGANIC":
            out.extend(["leather", "bone", "plant"])
        else:
            out.extend(m.id for m in mat_data.by_flag(flag))
    if not out:
        out = ["iron"]
    # Bias metals by tier so early enemies carry copper, not steel.
    if "METAL" in defn.materials:
        allowed = set(mat_data.WEAPON_METALS[: max(1, min(6, tier + 2))])
        allowed.update({"copper", "bronze", "iron"})
        filtered = [m for m in out if m not in mat_data.WEAPON_METALS or m in allowed]
        if filtered:
            out = filtered
    return sorted(set(out))


def make_item(
    rng: RNG,
    def_id: str,
    *,
    material: Optional[str] = None,
    quality: Optional[int] = None,
    tier: int = 1,
    count: int = 1,
) -> Item:
    """Create an item, rolling material and quality when not specified."""
    defn = item_data.get(def_id)
    if material is None:
        material = rng.choice(_materials_for(defn, tier))
    if quality is None:
        roll = rng.random() + tier * 0.05
        if roll > 0.985:
            quality = 5
        elif roll > 0.95:
            quality = 4
        elif roll > 0.88:
            quality = 3
        elif roll > 0.76:
            quality = 2
        elif roll > 0.58:
            quality = 1
        else:
            quality = 0
    it = Item(def_id, material, quality=quality, count=count)
    if defn.has("LIGHT"):
        it.charges = rng.randint(1800, 4800)
    return it


_LOOT_TABLE: Dict[str, Sequence[str]] = {
    "weapon": ("dagger", "short_sword", "sword", "axe", "mace", "spear",
               "warhammer", "battle_axe", "long_sword", "scimitar", "flail",
               "morningstar", "pick", "halberd"),
    "armor": ("cap", "helm", "mail_shirt", "breastplate", "leather_armor",
              "greaves", "gauntlets", "high_boots", "chain_leggings",
              "shield", "buckler"),
    "clothing": ("cloak", "robe", "tunic", "trousers", "shoes", "hood"),
    "food": ("meat", "bread", "cheese", "plump_helmet", "berries"),
    "drink": ("dwarven_ale", "wine", "rum", "beer", "mead"),
    "tool": ("rope", "torch", "waterskin", "backpack", "whetstone", "bandage",
             "flint_and_steel", "lockpick"),
    "treasure": ("gem", "coin", "coin", "rough_gem"),
}


def random_loot(rng: RNG, tier: int, kinds: Sequence[str] = ()) -> List[Item]:
    """Roll a small pile of plausible loot for a creature or chest."""
    kinds = tuple(kinds) or ("weapon", "armor", "food", "tool", "treasure")
    out: List[Item] = []
    n = max(1, rng.gauss_int(1 + tier * 0.7, 1.0, 1, 5))
    for _ in range(n):
        kind = rng.choice(kinds)
        table = _LOOT_TABLE.get(kind, _LOOT_TABLE["tool"])
        def_id = rng.choice(table)
        count = 1
        if def_id == "coin":
            count = rng.randint(5, 40 + tier * 40)
        elif item_data.get(def_id).stack:
            count = rng.randint(1, 3)
        out.append(make_item(rng, def_id, tier=tier, count=count))
    return out


def starting_kit(rng: RNG, race: str, profession: str) -> List[Item]:
    """The equipment a newly created adventurer sets out with."""
    kit: List[Item] = []
    metal = "iron" if race != "kobold" else "copper"

    weapons = {
        "warrior": ("sword", "shield"),
        "axeman": ("axe", "shield"),
        "hammerman": ("warhammer", "shield"),
        "spearman": ("spear", "buckler"),
        "archer": ("bow", "dagger"),
        "hunter": ("bow", "dagger"),
        "thief": ("dagger", "dagger"),
        "scholar": ("dagger", "book"),
        "peasant": ("dagger",),
        "wrestler": (),
    }.get(profession, ("sword",))
    for w in weapons:
        mat = metal
        if w == "bow":
            mat = "oak"
        elif w == "shield" or w == "buckler":
            mat = "oak" if rng.chance(0.5) else metal
        elif w == "book":
            mat = "leather"
        kit.append(Item(w, mat, quality=rng.randint(0, 1)))

    armour = {
        "warrior": ("mail_shirt", "helm", "high_boots"),
        "axeman": ("mail_shirt", "cap", "high_boots"),
        "hammerman": ("mail_shirt", "helm", "high_boots"),
        "spearman": ("leather_armor", "cap", "high_boots"),
        "archer": ("leather_armor", "cap", "shoes"),
        "hunter": ("leather_armor", "hood", "shoes"),
        "thief": ("leather_armor", "hood", "shoes"),
        "scholar": ("robe", "shoes"),
        "peasant": ("tunic", "trousers", "shoes"),
        "wrestler": ("tunic", "trousers", "shoes"),
    }.get(profession, ("leather_armor", "shoes"))
    for a in armour:
        defn = item_data.get(a)
        mat = metal if "METAL" in defn.materials else (
            "leather" if "LEATHER" in defn.materials else "pig_tail_cloth"
        )
        kit.append(Item(a, mat))

    kit.append(Item("waterskin", "leather"))
    kit.append(Item("water_drink", "water", count=3))
    kit.append(Item("backpack", "leather"))
    kit.append(Item("meat", "meat", count=rng.randint(3, 6)))
    kit.append(Item("bread", "bread", count=rng.randint(2, 4)))
    kit.append(Item("dwarven_ale", "alcohol", count=rng.randint(2, 4)))
    torch = Item("torch", "oak", count=2)
    torch.charges = 2400
    kit.append(torch)
    kit.append(Item("rope", "pig_tail_cloth"))
    kit.append(Item("coin", "silver", count=rng.randint(20, 80)))
    if profession in ("archer", "hunter"):
        kit.append(Item("arrow", metal, count=rng.randint(15, 30)))
    if profession == "thief":
        kit.append(Item("lockpick", metal))
    return kit


def corpse_of(creature) -> Item:
    """Build the corpse item left behind by a dead creature."""
    it = Item("corpse", "meat", count=1)
    it.name_override = "%s corpse" % creature.defn.adjective
    it.flags["creature"] = creature.def_id
    it.flags["size"] = creature.defn.size
    it.flags["name"] = creature.name
    return it


def severed_part(creature, part_name: str) -> Item:
    """Build the item left behind when a limb is hacked off."""
    it = Item("severed_part", "meat", count=1)
    it.name_override = "%s %s" % (creature.defn.adjective, part_name)
    it.flags["creature"] = creature.def_id
    return it
