"""Field medicine.

Bleeding is what actually kills people, so being able to stop it matters more
than anything else you can carry. Bandages close wounds, splints set broken
bones, and a good diagnostician can tell you which of your problems is the one
about to finish you.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..engine import colors
from ..engine.rng import RNG
from ..engine.screen import Frag
from .body import PartState
from .item import Item

#: Problems a body part can have that treatment can do something about.
TREATMENTS = ("bandage", "splint", "suture")

TREATMENT_NAMES = {
    "bandage": "Bind the wound",
    "splint": "Set the bone",
    "suture": "Stitch the wound",
}

TREATMENT_SKILL = {
    "bandage": "wound_dressing",
    "splint": "bone_setting",
    "suture": "suturing",
}

#: Which item each treatment consumes, if any.
TREATMENT_ITEM = {
    "bandage": "bandage",
    "splint": "splint",
    "suture": "",
}


def part_bleeding(part: PartState) -> int:
    """Total bleeding across a part's wounds."""
    return sum(w.bleeding for w in part.wounds)


def needs_treatment(part: PartState) -> List[str]:
    """Which treatments would help this part right now."""
    if part.gone:
        return []
    out: List[str] = []
    if part_bleeding(part) > 0:
        out.append("bandage")
    if part.broken:
        out.append("splint")
    if part.damage_fraction() > 0.3 and not part_bleeding(part):
        out.append("suture")
    return out


def treatable(creature) -> List[Tuple[PartState, List[str]]]:
    """Every part of a creature that could be treated, worst first."""
    out = []
    for pid in creature.body.order:
        part = creature.body.parts[pid]
        options = needs_treatment(part)
        if options:
            out.append((part, options))
    out.sort(key=lambda pair: -(part_bleeding(pair[0]) * 10
                                + pair[0].damage_fraction()))
    return out


def has_supplies(healer, treatment: str) -> Optional[Item]:
    """The item a treatment needs, if the healer is carrying one."""
    def_id = TREATMENT_ITEM.get(treatment, "")
    if not def_id:
        return None
    matches = healer.inventory.by_def(def_id)
    return matches[0] if matches else None


def can_treat(healer, treatment: str) -> Tuple[bool, str]:
    """Whether the healer can attempt a treatment, and why not if they cannot."""
    def_id = TREATMENT_ITEM.get(treatment, "")
    if def_id and has_supplies(healer, treatment) is None:
        from ..data import items as item_data

        return (False, "You have no %s." % item_data.get(def_id).plural)
    if healer.body.can_grasp() < 1:
        return (False, "You have nothing to work with.")
    return (True, "")


def _consume(healer, treatment: str) -> Optional[Item]:
    """Use up the supplies a treatment needs."""
    item = has_supplies(healer, treatment)
    if item is None:
        return None
    item.count -= 1
    if item.count <= 0:
        healer.inventory.unequip_item(item)
        if item in healer.inventory.items:
            healer.inventory.items.remove(item)
    return item


def _quality(healer, treatment: str, rng: RNG) -> int:
    """Roll how well a treatment went: 0 botched, 1 poor, 2 fine, 3 excellent."""
    skill = healer.skills.level(TREATMENT_SKILL.get(treatment, "wound_dressing"))
    roll = skill + rng.randint(0, 8) + int(healer.attributes.factor("agility") * 2)
    if roll >= 16:
        return 3
    if roll >= 10:
        return 2
    if roll >= 5:
        return 1
    return 0


def treat(
    healer, patient, part_id: str, treatment: str, *, rng: RNG
) -> List[Frag]:
    """Apply one treatment to one body part. Returns messages."""
    part = patient.body.part(part_id)
    if part is None or part.gone:
        return [Frag("There is nothing there to treat.", colors.UI["dim"])]
    ok, why = can_treat(healer, treatment)
    if not ok:
        return [Frag(why, colors.UI["warn"])]

    who = "your" if patient is healer else "%s's" % patient.display_name()
    skill_id = TREATMENT_SKILL.get(treatment, "wound_dressing")
    quality = _quality(healer, treatment, rng)
    out: List[Frag] = []

    if treatment == "bandage":
        bleeding = part_bleeding(part)
        if bleeding <= 0:
            return [Frag("That wound is not bleeding.", colors.UI["dim"])]
        _consume(healer, treatment)
        if quality == 0:
            out.append(Frag(
                "You fumble the dressing on %s %s and waste the bandage."
                % (who, part.name), colors.UI["warn"]))
            healer.add_exp(skill_id, 15)
            return out
        stopped = {1: 0.5, 2: 0.85, 3: 1.0}[quality]
        for w in part.wounds:
            w.bleeding = int(w.bleeding * (1.0 - stopped))
        left = part_bleeding(part)
        wording = {1: "roughly", 2: "cleanly", 3: "expertly"}[quality]
        out.append(Frag(
            "You bind %s %s %s." % (who, part.name, wording), colors.UI["good"]))
        if left > 0:
            out.append(Frag("It is still bleeding.", colors.UI["warn"]))
        else:
            out.append(Frag("The bleeding stops.", colors.UI["good"]))
        healer.add_exp(skill_id, 45)

    elif treatment == "splint":
        if not part.broken:
            return [Frag("Nothing there is broken.", colors.UI["dim"])]
        _consume(healer, treatment)
        if quality == 0:
            out.append(Frag(
                "You set the bone badly and %s cries out." % (
                    "you" if patient is healer else patient.display_name()),
                colors.UI["warn"]))
            patient.body.pain += 20
            healer.add_exp(skill_id, 15)
            return out
        part.broken = False
        # A splint holds the bone while it knits; restore some of it now.
        for tid, frac in list(part.tissues.items()):
            from ..data import bodies as body_data

            if body_data.tissue(tid).material == "bone":
                part.tissues[tid] = min(1.0, frac + 0.15 * quality)
        out.append(Frag(
            "You splint %s %s. The bone is set." % (who, part.name),
            colors.UI["good"]))
        healer.add_exp(skill_id, 55)

    else:  # suture
        if part.damage_fraction() <= 0.05:
            return [Frag("That wound does not need stitching.", colors.UI["dim"])]
        if quality == 0:
            out.append(Frag("Your stitches tear open again.", colors.UI["warn"]))
            healer.add_exp(skill_id, 15)
            return out
        healed = 0.06 * quality
        for tid, frac in list(part.tissues.items()):
            if frac < 1.0:
                part.tissues[tid] = min(1.0, frac + healed)
        part.wounds = [w for w in part.wounds if w.severed or w.bleeding > 0]
        out.append(Frag(
            "You stitch %s %s closed." % (who, part.name), colors.UI["good"]))
        healer.add_exp(skill_id, 50)

    healer.add_exp("diagnose", 10)
    return out


def diagnose(healer, patient) -> List[Frag]:
    """Describe a patient's injuries, in detail proportional to skill."""
    skill = healer.skills.level("diagnose")
    body = patient.body
    who = "You are" if patient is healer else "%s is" % patient.display_name()
    out: List[Frag] = []

    hurt = treatable(patient)
    if not hurt and body.blood_fraction() > 0.95:
        out.append(Frag("%s in good health." % who, colors.UI["good"]))
        healer.add_exp("diagnose", 5)
        return out

    bleed_rate = body.bleeding_rate()
    if bleed_rate > 0:
        if skill >= 3:
            ticks = int(
                max(0.0, body.blood - body.max_blood * 0.2) / max(1e-6, bleed_rate)
            )
            out.append(Frag(
                "Blood loss will kill %s in about %d turns."
                % ("you" if patient is healer else "them", ticks),
                colors.UI["danger"]))
        else:
            out.append(Frag("%s bleeding." % who, colors.UI["danger"]))

    for part, options in hurt:
        bits = []
        if "bandage" in options:
            bits.append("bleeding")
        if "splint" in options:
            bits.append("broken")
        if "suture" in options:
            bits.append("open")
        detail = ", ".join(bits)
        if skill >= 2:
            detail += " (%d%% damaged)" % int(part.damage_fraction() * 100)
        out.append(Frag("  %s: %s" % (part.name, detail), colors.UI["warn"]))

    if skill < 2 and len(out) > 4:
        del out[4:]
        out.append(Frag("  ...you cannot tell what else is wrong.",
                        colors.UI["dim"]))

    healer.add_exp("diagnose", 20)
    return out


def auto_treat(healer, *, rng: RNG) -> List[Frag]:
    """Treat the healer's own worst problem with whatever they are carrying."""
    hurt = treatable(healer)
    for part, options in hurt:
        for treatment in options:
            ok, _why = can_treat(healer, treatment)
            if ok:
                return treat(healer, healer, part.id, treatment, rng=rng)
    return [Frag("There is nothing you can do for yourself right now.",
                 colors.UI["dim"])]
