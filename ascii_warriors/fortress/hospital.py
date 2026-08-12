"""The hospital.

A dwarf that has been cut open will bleed to death in a few minutes while
standing next to a full barrel of ale, because nothing in the fortress notices.
This module notices. Wounded dwarves stop working, go to a bed, and a dwarf
with the medicine labor comes and binds them up.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from ..game import medical

Cell = Tuple[int, int, int]

#: How badly hurt a dwarf must be before it stops working and lies down.
REST_BLOOD = 0.85
REST_PAIN = 0.35

#: Blood fraction below which a dwarf is in real trouble.
CRITICAL_BLOOD = 0.6

#: Work a treatment job takes. Binding a wound is quick — skill decides how
#: well it is done, not how long it takes, and a bleeding dwarf has minutes.
TREAT_WORK = 30

#: Bandages the hospital tries to keep in stock, per dwarf.
BANDAGE_PER_DWARF = 2


def is_hurt(dwarf) -> bool:
    """True if a dwarf should stop what it is doing and be seen to."""
    body = dwarf.body
    if body.dead:
        return False
    if body.bleeding_rate() > 0:
        return True
    if body.blood_fraction() < REST_BLOOD:
        return True
    if body.pain_level() > REST_PAIN:
        return True
    return any(p.broken for p in body.parts.values())


def is_critical(dwarf) -> bool:
    """True if a dwarf will die shortly without help."""
    return (dwarf.body.bleeding_rate() > 0
            and dwarf.body.blood_fraction() < CRITICAL_BLOOD)


def needs_care(dwarf) -> List[Tuple[str, str]]:
    """``(part id, treatment)`` pairs a dwarf needs, worst first."""
    out: List[Tuple[str, str]] = []
    for part, options in medical.treatable(dwarf):
        for treatment in options:
            out.append((part.id, treatment))
    return out


def patients(fort) -> List:
    """Every dwarf that ought to be in a hospital bed, worst first."""
    hurt = [d for d in fort.dwarves() if is_hurt(d)]
    hurt.sort(key=lambda d: (d.body.blood_fraction(),
                             -d.body.pain_level()))
    return hurt


def hospital_beds(fort) -> List:
    """Every built hospital bed."""
    return [b for b in fort.buildings if b.kind == "hospital" and b.built]


def free_bed(fort, dwarf) -> Optional[object]:
    """A hospital bed for a patient, keeping the one it already has."""
    beds = hospital_beds(fort)
    if not beds:
        return None
    for b in beds:
        if b.owner == dwarf.id:
            return b
    for b in beds:
        if b.owner is None or b.owner not in _living_ids(fort):
            b.owner = dwarf.id
            return b
    return None


def _living_ids(fort) -> set:
    """Ids of dwarves still alive, for freeing beds of the dead."""
    return {d.id for d in fort.dwarves()}


def release_bed(fort, dwarf) -> None:
    """Give a hospital bed back once its patient is well."""
    for b in hospital_beds(fort):
        if b.owner == dwarf.id:
            b.owner = None


def doctors(fort) -> List:
    """Every dwarf willing and able to treat somebody."""
    return [d for d in fort.dwarves()
            if d.fort.labors.has("medicine") and not is_critical(d)]


def supplies(fort, treatment: str) -> Optional[object]:
    """An unreserved item the treatment needs, or ``None`` if none is needed."""
    def_id = medical.TREATMENT_ITEM.get(treatment, "")
    if not def_id:
        return None
    for pile in fort.items_on_ground.values():
        for item in pile:
            if item.def_id == def_id and not fort.jobs.is_reserved(item.id):
                return item
    return None


def can_supply(fort, treatment: str) -> bool:
    """True if the treatment needs nothing, or the fortress has it."""
    def_id = medical.TREATMENT_ITEM.get(treatment, "")
    if not def_id:
        return True
    return fort.stock_count(def_id) > 0


#: Second-person verbs :mod:`medical` writes, and their third-person forms.
_VERBS = {
    "bind": "binds", "set": "sets", "stitch": "stitches", "fumble": "fumbles",
    "clean": "cleans", "splint": "splints", "have": "has",
}


def _third_person(text: str, healer, patient) -> str:
    """Rewrite first-aid messages written for an adventurer's own body."""
    words = text.split(" ", 2)
    if words and words[0] == "You" and len(words) > 1:
        verb = _VERBS.get(words[1], words[1] + "s")
        text = " ".join([healer.name, verb] + words[2:])
    else:
        text = text.replace("You ", "%s " % healer.name)
    return text.replace("your ", "%s's " % patient.name)


def treat(fort, healer, patient, part_id: str, treatment: str) -> None:
    """Carry out one treatment and log what happened."""
    frags = medical.treat(healer, patient, part_id, treatment, rng=fort.rng)
    lines = [_third_person(f.text.strip(), healer, patient)
             for f in frags if f.text.strip()]
    if not lines:
        return
    text = " ".join(lines)
    good = "bleeding stops" in text or "binds" in text or "sets" in text
    fort.log.add(text, "good" if good else "info")


def summary(fort) -> List[Tuple[str, str, str]]:
    """``(name, condition, treatment wanted)`` rows for the health screen."""
    rows: List[Tuple[str, str, str]] = []
    for d in patients(fort):
        care = needs_care(d)
        wanted = ", ".join(sorted({t for _p, t in care})) or "rest"
        blood = d.body.blood_fraction()
        if is_critical(d):
            condition = "bleeding out"
        elif blood < 0.75:
            condition = "weak from blood loss"
        elif any(p.broken for p in d.body.parts.values()):
            condition = "broken bones"
        else:
            condition = d.body.wound_summary() or "hurt"
        rows.append((d.name, condition, wanted))
    return rows
