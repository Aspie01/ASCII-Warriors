"""Carrying and wearing things.

Armour layers the way Dwarf Fortress does it: an under layer, an over layer, an
armour layer and a cover, each of which can protect the same body part.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from .item import Item

#: Equipment slots. ``weapon``/``offhand`` are held; the rest are worn.
BODY_SLOTS: Tuple[str, ...] = (
    "head", "neck", "torso_under", "torso_over", "torso_armor", "hands",
    "legs", "feet", "back", "weapon", "offhand", "ring1", "ring2", "ammo",
)

SLOT_NAMES: Dict[str, str] = {
    "head": "Head",
    "neck": "Neck",
    "torso_under": "Torso (under)",
    "torso_over": "Torso (over)",
    "torso_armor": "Torso (armor)",
    "hands": "Hands",
    "legs": "Legs",
    "feet": "Feet",
    "back": "Back",
    "weapon": "Weapon",
    "offhand": "Off hand",
    "ring1": "Ring",
    "ring2": "Ring",
    "ammo": "Ammunition",
}

#: Body-part categories -> the slots that cover them.
_COVERAGE_SLOTS: Dict[str, Tuple[str, ...]] = {
    "head": ("head",),
    "neck": ("neck", "head"),
    "torso": ("torso_under", "torso_over", "torso_armor", "back"),
    "arm": ("torso_under", "torso_over", "torso_armor", "back"),
    "hand": ("hands",),
    "leg": ("legs",),
    "foot": ("feet", "legs"),
    "organ": ("torso_under", "torso_over", "torso_armor"),
    "tail": (),
    "wing": ("back",),
    "fin": (),
}


class Inventory:
    """Everything a creature carries, plus what it is wearing and wielding."""

    def __init__(self, owner: Any = None) -> None:
        self.owner = owner
        self.items: List[Item] = []
        self.equipped: Dict[str, Item] = {}

    # -- contents ---------------------------------------------------------- #

    def add(self, item: Item) -> Item:
        """Add an item, merging into an existing stack when possible."""
        if item.count <= 0:
            return item
        if item.defn.stack:
            for existing in self.items:
                if existing.stack_with(item):
                    return existing
        self.items.append(item)
        return item

    def add_all(self, items: Sequence[Item]) -> None:
        """Add several items."""
        for it in items:
            self.add(it)

    def remove(self, item: Item, count: int = 1) -> Optional[Item]:
        """Remove up to *count* units, returning what was taken."""
        if item not in self.items:
            return None
        if item.count > count:
            return item.split(count)
        for slot, worn in list(self.equipped.items()):
            if worn is item:
                del self.equipped[slot]
        self.items.remove(item)
        return item

    def remove_all(self) -> List[Item]:
        """Take everything out, unequipping as needed."""
        out = list(self.items)
        self.items.clear()
        self.equipped.clear()
        return out

    def contains(self, item: Item) -> bool:
        """True if this inventory holds *item*."""
        return item in self.items

    def find(self, pred: Callable[[Item], bool]) -> List[Item]:
        """Every carried item matching a predicate."""
        return [i for i in self.items if pred(i)]

    def by_category(self, cat: str) -> List[Item]:
        """Every carried item in a category."""
        return [i for i in self.items if i.category == cat]

    def by_def(self, def_id: str) -> List[Item]:
        """Every carried item of a definition."""
        return [i for i in self.items if i.def_id == def_id]

    def count_of(self, def_id: str) -> int:
        """Total units of a given item definition."""
        return sum(i.count for i in self.items if i.def_id == def_id)

    def total_weight(self) -> float:
        """Combined weight of everything carried, in kilograms."""
        return sum(i.weight for i in self.items)

    def worn_armor_weight(self) -> float:
        """Weight of the armour actually being worn, in kilograms.

        Worn, not carried: a breastplate in a sack is dead weight to anybody,
        however good they are at wearing one.
        """
        return sum(i.weight for i in self.equipped.values()
                   if i.defn.armor is not None)

    def total_value(self) -> int:
        """Combined trade value of everything carried."""
        return sum(i.value for i in self.items)

    def coins(self) -> int:
        """How much money is carried."""
        return self.count_of("coin")

    def spend_coins(self, amount: int) -> bool:
        """Remove *amount* coins; False if there are not enough."""
        if amount <= 0:
            return True
        have = self.coins()
        if have < amount:
            return False
        left = amount
        for it in list(self.by_def("coin")):
            take = min(left, it.count)
            it.count -= take
            left -= take
            if it.count <= 0:
                self.items.remove(it)
            if left <= 0:
                break
        return True

    # -- equipment --------------------------------------------------------- #

    def is_equipped(self, item: Item) -> bool:
        """True if *item* is currently worn or wielded."""
        return any(v is item for v in self.equipped.values())

    def slot_of(self, item: Item) -> Optional[str]:
        """Which slot *item* occupies, if any."""
        for slot, worn in self.equipped.items():
            if worn is item:
                return slot
        return None

    def slot_for(self, item: Item) -> Optional[str]:
        """The natural slot for an item, or ``None`` if it cannot be worn."""
        defn = item.defn
        if item.is_ammo:
            return "ammo"
        if item.is_shield:
            return "offhand"
        if defn.weapon is not None and defn.category == "weapon":
            return "weapon"
        armor = defn.armor
        if armor is None:
            # Anything else you are carrying, you can pick up and swing. The
            # skill table has had `misc_weapon` -- "Misc. Object User" -- since
            # it was written and **nothing in the game could reach it**: no
            # item mapped to it, because nothing but a weapon could go in the
            # hand. A chair is a poor weapon and a poor weapon is not nothing.
            #
            # Armour is excluded above rather than here: a mail shirt has a
            # slot of its own and wielding it is not the useful reading of
            # "wear this".
            return "weapon" if item.can_be_swung else None
        cover = set(armor.coverage)
        if "head" in cover and armor.layer in ("armor", "over", "under"):
            return "head"
        if "hand" in cover:
            return "hands"
        if "foot" in cover and "leg" not in cover:
            return "feet"
        if "leg" in cover and "torso" not in cover:
            return "legs" if "foot" not in cover else "feet"
        if "torso" in cover:
            if armor.layer == "under":
                return "torso_under"
            if armor.layer == "over":
                return "torso_over"
            if armor.layer == "cover":
                return "back"
            return "torso_armor"
        if "neck" in cover:
            return "neck"
        return None

    def equip(self, item: Item, slot: Optional[str] = None) -> Tuple[bool, str]:
        """Wear or wield an item. Returns ``(ok, message)``."""
        if item not in self.items:
            self.add(item)
        target = slot or self.slot_for(item)
        if target is None:
            return (False, "You cannot wear or wield that.")
        if target not in BODY_SLOTS:
            return (False, "That does not go there.")

        owner = self.owner
        if owner is not None and target in ("weapon", "offhand"):
            grasps = owner.body.can_grasp() if hasattr(owner, "body") else 2
            if grasps <= 0:
                return (False, "You have nothing left to hold it with.")
            wdef = item.defn.weapon
            size = getattr(owner.defn, "size", 60000)
            if wdef and wdef.two_handed_size and size < wdef.two_handed_size:
                if grasps < 2:
                    return (False, "You need both hands for that.")
                other = "offhand" if target == "weapon" else "weapon"
                if other in self.equipped:
                    self.unequip(other)
            if wdef and wdef.min_size and size < wdef.min_size:
                return (False, "That is far too big for you.")

        if target in self.equipped:
            self.unequip(target)
        self.equipped[target] = item
        verb = "wield" if target in ("weapon", "offhand") else "put on"
        return (True, "You %s %s." % (verb, item.name(article=True)))

    def unequip(self, slot: str) -> Optional[Item]:
        """Take something off; returns the item that was removed."""
        return self.equipped.pop(slot, None)

    def unequip_item(self, item: Item) -> bool:
        """Take a specific item off wherever it is worn."""
        slot = self.slot_of(item)
        if slot is None:
            return False
        del self.equipped[slot]
        return True

    def weapon(self) -> Optional[Item]:
        """The wielded weapon, if any."""
        return self.equipped.get("weapon")

    def offhand(self) -> Optional[Item]:
        """Whatever is in the off hand."""
        return self.equipped.get("offhand")

    def shield(self) -> Optional[Item]:
        """The equipped shield, if any."""
        off = self.equipped.get("offhand")
        return off if off is not None and off.is_shield else None

    def ammo(self) -> Optional[Item]:
        """The readied ammunition, if any."""
        return self.equipped.get("ammo")

    def best_weapon(self) -> Optional[Item]:
        """The most damaging carried weapon, by penetration and quality."""
        best: Optional[Item] = None
        best_score = -1.0
        for it in self.items:
            if not it.is_weapon or it.is_ranged or it.category != "weapon":
                continue
            atk = it.attacks()
            if not atk:
                continue
            score = max(a.penetration for a in atk) * it.quality_bonus()
            score *= 1.0 + it.mat.shear_yield / 500000.0
            if score > best_score:
                best, best_score = it, score
        return best

    def ranged_weapon(self) -> Optional[Item]:
        """The best carried bow, crossbow or sling.

        `best_weapon` skips ranged weapons deliberately: it answers *"what do
        I swing"*. Two callers used it to ask *"do I have a bow"*, which it
        can never answer yes to -- so every archer in the world was made
        without ammunition and never drew the bow it was handed. Measured:
        248 of 248 creatures given a ranged weapon stood there empty-handed.
        """
        best: Optional[Item] = None
        best_score = -1.0
        for it in self.items:
            if not it.is_ranged or it.category != "weapon":
                continue
            wdef = it.defn.weapon
            score = (wdef.shoot_force if wdef else 0) * it.quality_bonus()
            if score > best_score:
                best, best_score = it, score
        return best

    def best_armor_set(self) -> List[Item]:
        """One good candidate per armour slot, for AI auto-equipping."""
        by_slot: Dict[str, Item] = {}
        for it in self.items:
            if not it.is_armor:
                continue
            slot = self.slot_for(it)
            if slot is None:
                continue
            cur = by_slot.get(slot)
            lvl = it.defn.armor.armor_level if it.defn.armor else 0
            cur_lvl = cur.defn.armor.armor_level if cur and cur.defn.armor else -1
            if lvl > cur_lvl:
                by_slot[slot] = it
        return list(by_slot.values())

    def armor_on(self, part_category: str) -> List[Item]:
        """Every worn item protecting a body-part category, outermost first."""
        slots = _COVERAGE_SLOTS.get(part_category, ())
        order = {"back": 0, "torso_armor": 1, "torso_over": 2, "torso_under": 3}
        found: List[Item] = []
        for slot in slots:
            it = self.equipped.get(slot)
            if it is None or it.defn.armor is None:
                continue
            cover = it.defn.armor.coverage
            if cover and part_category not in cover:
                continue
            found.append(it)
        found.sort(key=lambda i: order.get(self.slot_of(i) or "", 1))
        return found

    def light_sources(self) -> List[Item]:
        """Carried torches and lanterns."""
        return [i for i in self.items if i.is_light]

    def auto_equip(self) -> List[str]:
        """Wear and wield the best of what is carried; returns messages."""
        msgs: List[str] = []
        w = self.best_weapon()
        if w is not None and self.equipped.get("weapon") is not w:
            ok, msg = self.equip(w, "weapon")
            if ok:
                msgs.append(msg)
        # Somebody whose only weapon is a bow draws the bow. Anybody carrying
        # something to swing keeps holding that: the AI shoots only with what
        # is readied, and a spearman who nocked an arrow because one was in
        # the pack would be a worse spearman.
        if self.equipped.get("weapon") is None:
            bow = self.ranged_weapon()
            if bow is not None:
                ok, msg = self.equip(bow, "weapon")
                if ok:
                    msgs.append(msg)
        for piece in self.best_armor_set():
            slot = self.slot_for(piece)
            if slot and self.equipped.get(slot) is not piece:
                ok, msg = self.equip(piece, slot)
                if ok:
                    msgs.append(msg)
        shield = next((i for i in self.items if i.is_shield), None)
        if shield is not None and "offhand" not in self.equipped:
            ok, msg = self.equip(shield, "offhand")
            if ok:
                msgs.append(msg)
        ammo = next((i for i in self.items if i.is_ammo), None)
        if ammo is not None and "ammo" not in self.equipped:
            self.equipped["ammo"] = ammo
        return msgs

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise items and which slots hold which."""
        index = {id(it): i for i, it in enumerate(self.items)}
        return {
            "items": [it.to_dict() for it in self.items],
            "equipped": {
                slot: index[id(it)]
                for slot, it in self.equipped.items()
                if id(it) in index
            },
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], owner: Any = None) -> "Inventory":
        """Rebuild from :meth:`to_dict`."""
        inv = cls(owner)
        inv.items = [Item.from_dict(x) for x in d.get("items", [])]
        for slot, idx in (d.get("equipped") or {}).items():
            i = int(idx)
            if 0 <= i < len(inv.items) and slot in BODY_SLOTS:
                inv.equipped[slot] = inv.items[i]
        return inv

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Inventory(%d items, %d equipped)" % (
            len(self.items), len(self.equipped)
        )
