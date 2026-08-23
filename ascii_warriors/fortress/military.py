"""Squads, uniforms, training and the alarm.

A fortress with no militia is a fortress that dies the first autumn something
comes over the hill. Soldiers are ordinary dwarves with the military labor and
a squad; the squad tells them what to wear, where to stand and who to kill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

Cell = Tuple[int, int, int]

#: How many dwarves fit in one squad.
SQUAD_SIZE = 10

#: What a squad's orders can be.
ORDERS: Tuple[str, ...] = ("train", "station", "defend", "kill")

ORDER_NAMES: Dict[str, str] = {
    "train": "Train",
    "station": "Station",
    "defend": "Defend the fortress",
    "kill": "Kill",
}


@dataclass(frozen=True)
class Uniform:
    """What a squad is told to wear."""

    id: str
    name: str
    #: Item def ids, best first. A soldier takes the first one it can find.
    weapons: Tuple[str, ...]
    armor: Tuple[str, ...]
    shield: bool
    #: The skill this uniform's weapon trains.
    skill: str
    description: str = ""


UNIFORMS: Dict[str, Uniform] = {
    u.id: u
    for u in (
        Uniform("axe", "Axedwarf",
                ("battle_axe", "great_axe", "axe"),
                ("mail_shirt", "breastplate", "helm", "greaves", "high_boots",
                 "gauntlets", "leather_armor", "cap"),
                True, "axe",
                "An axe takes limbs off. The dwarven favourite."),
        Uniform("hammer", "Hammerdwarf",
                ("warhammer", "maul", "mace", "morningstar"),
                ("mail_shirt", "breastplate", "helm", "greaves", "high_boots",
                 "gauntlets", "leather_armor", "cap"),
                True, "hammer",
                "A hammer does not need to cut through armour."),
        Uniform("sword", "Swordsdwarf",
                ("long_sword", "sword", "short_sword", "scimitar"),
                ("mail_shirt", "breastplate", "helm", "greaves", "high_boots",
                 "gauntlets", "leather_armor", "cap"),
                True, "sword", ""),
        Uniform("spear", "Speardwarf",
                ("pike", "halberd", "spear"),
                ("mail_shirt", "breastplate", "helm", "greaves", "high_boots",
                 "leather_armor", "cap"),
                True, "spear", ""),
        Uniform("marksdwarf", "Marksdwarf",
                ("crossbow", "bow", "sling"),
                ("leather_armor", "mail_shirt", "cap", "helm", "high_boots"),
                False, "crossbow",
                "Shoots through fortifications. Needs bolts."),
    )
}

#: Which skills training at a barracks raises.
TRAINING_SKILLS: Tuple[str, ...] = (
    "fighter", "dodging", "armor_use", "shield_use",
)

#: The alert states a fortress can be in, and the whole of them.
#:
#: This used to be a comment rather than a rule. Four different strings were
#: assigned to :attr:`Military.alert` around the codebase -- ``"danger"`` by
#: every megabeast, werebeast, necromancer, demon wave and siege, and
#: ``"combat"`` by a test -- and the :attr:`Military.alarm` property compares
#: against ``"alarm"`` and so read every one of them as "no alarm".
#: :class:`TestTheAlarmStatesThatExist` holds the set closed now.
ALERTS: Tuple[str, ...] = ("civilian", "alarm")


class Squad:
    """A handful of dwarves told to fight together."""

    _next_id = 1

    def __init__(self, name: str = "", uniform: str = "axe") -> None:
        self.id = Squad._next_id
        Squad._next_id += 1
        self.name = name or "The Militia"
        self.uniform = uniform if uniform in UNIFORMS else "axe"
        #: Creature ids, in the order they were recruited.
        self.members: List[int] = []
        self.order = "train"
        self.station: Optional[Cell] = None
        self.target: Optional[int] = None
        #: Barracks building id this squad trains at.
        self.barracks: Optional[int] = None

    @property
    def defn(self) -> Uniform:
        """The squad's uniform."""
        return UNIFORMS.get(self.uniform) or UNIFORMS["axe"]

    @property
    def order_name(self) -> str:
        """Readable current order."""
        if self.order == "station" and self.station is not None:
            return "Station at %d,%d,%+d" % self.station
        return ORDER_NAMES.get(self.order, self.order.title())

    def has(self, dwarf_id: int) -> bool:
        """True if this dwarf is in the squad."""
        return dwarf_id in self.members

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the squad."""
        return {
            "id": self.id, "name": self.name, "uniform": self.uniform,
            "members": list(self.members), "order": self.order,
            "station": list(self.station) if self.station else None,
            "target": self.target, "barracks": self.barracks,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Squad":
        """Rebuild from :meth:`to_dict`."""
        s = cls(str(d.get("name", "")), str(d.get("uniform", "axe")))
        s.id = int(d.get("id", s.id))
        Squad._next_id = max(Squad._next_id, s.id + 1)
        s.members = [int(m) for m in d.get("members", [])]
        s.order = str(d.get("order", "train"))
        station = d.get("station")
        s.station = tuple(int(v) for v in station) if station else None
        s.target = d.get("target")
        s.barracks = d.get("barracks")
        return s

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Squad(%s, %d members, %s)" % (
            self.name, len(self.members), self.order)


class Military:
    """Every squad, plus the alert state and the safe burrow."""

    def __init__(self) -> None:
        self.squads: List[Squad] = []
        #: ``"civilian"`` is business as usual; ``"alarm"`` sends everyone in.
        #: One of :data:`ALERTS`, always.
        self.alert = "civilian"
        #: Whether there was anything hostile on the map at the last look.
        #: The watch compares this against what it can see now, so it only
        #: touches the alert when the answer *changes*. Between those two
        #: moments the state belongs to whoever set it, which is the only
        #: way the player's alarm key can mean anything.
        self.seen_threat = False
        #: The rectangle civilians retreat into when the alarm sounds.
        self.burrow: Optional[Tuple[int, int, int, int, int]] = None

    # -- squads ------------------------------------------------------------ #

    def squad(self, sid: int) -> Optional[Squad]:
        """Look a squad up by id."""
        for s in self.squads:
            if s.id == sid:
                return s
        return None

    def squad_of(self, dwarf_id: int) -> Optional[Squad]:
        """The squad a dwarf belongs to, if any."""
        for s in self.squads:
            if s.has(dwarf_id):
                return s
        return None

    def add_squad(self, name: str = "", uniform: str = "axe") -> Squad:
        """Raise a new squad."""
        squad = Squad(name, uniform)
        self.squads.append(squad)
        return squad

    def disband(self, squad: Squad) -> None:
        """Send a squad back to work."""
        if squad in self.squads:
            self.squads.remove(squad)

    def enlist(self, squad: Squad, dwarf_id: int) -> bool:
        """Put a dwarf in a squad, taking it out of any other."""
        if len(squad.members) >= SQUAD_SIZE:
            return False
        for other in self.squads:
            if dwarf_id in other.members:
                other.members.remove(dwarf_id)
        squad.members.append(dwarf_id)
        return True

    def discharge(self, dwarf_id: int) -> None:
        """Take a dwarf out of every squad."""
        for s in self.squads:
            if dwarf_id in s.members:
                s.members.remove(dwarf_id)

    def soldiers(self) -> List[int]:
        """Every dwarf id under arms."""
        out: List[int] = []
        for s in self.squads:
            out.extend(s.members)
        return out

    # -- alert -------------------------------------------------------------- #

    def sound_alarm(self, log: Any = None) -> None:
        """Send the civilians inside, and say so the first time.

        The announcement lives here because it used to live in one caller.
        `sim._watch` was the only thing that raised the alarm through this
        method -- every megabeast, siege, werebeast, necromancer and demon
        wave assigned the string directly -- so the watch was also the only
        thing that told the player, one step after the fact. Moving the
        threats onto this method without moving the message would have left
        a necromancer walking in, the fortress downing tools, and nothing on
        screen to connect the two.

        Raising an alarm that is already up says nothing and changes nothing.
        """
        if self.alert == "alarm":
            return
        self.alert = "alarm"
        if log is not None:
            log.warn("The alarm is raised. Civilians, get inside.")

    def all_clear(self, log: Any = None) -> None:
        """Back to work. Silent if the fortress was never under alarm."""
        if self.alert == "civilian":
            return
        self.alert = "civilian"
        if log is not None:
            log.good("All clear.")

    @property
    def alarm(self) -> bool:
        """True while the alarm is sounding."""
        return self.alert == "alarm"

    def in_burrow(self, x: int, y: int, z: int) -> bool:
        """True if a cell is inside the safe burrow."""
        if self.burrow is None:
            return False
        bx, by, bz, w, h = self.burrow
        return z == bz and bx <= x < bx + w and by <= y < by + h

    def burrow_cells(self) -> List[Cell]:
        """Every cell of the safe burrow."""
        if self.burrow is None:
            return []
        bx, by, bz, w, h = self.burrow
        return [(bx + dx, by + dy, bz) for dy in range(h) for dx in range(w)]

    # -- serialisation ------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole military."""
        return {
            "squads": [s.to_dict() for s in self.squads],
            "alert": self.alert,
            "seen_threat": self.seen_threat,
            "burrow": list(self.burrow) if self.burrow else None,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Military":
        """Rebuild from :meth:`to_dict`."""
        m = cls()
        m.squads = [Squad.from_dict(s) for s in d.get("squads", [])]
        alert = str(d.get("alert", "civilian"))
        m.alert = alert if alert in ALERTS else "civilian"
        m.seen_threat = bool(d.get("seen_threat", False))
        burrow = d.get("burrow")
        m.burrow = tuple(int(v) for v in burrow) if burrow else None
        return m

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Military(%d squads, %s)" % (len(self.squads), self.alert)


# --------------------------------------------------------------------------- #
# Equipment
# --------------------------------------------------------------------------- #


def wanted_items(squad: Squad, dwarf) -> List[str]:
    """Item def ids this dwarf still needs for its uniform, best first.

    Only one weapon and one of each armour slot: a soldier already wearing a
    mail shirt is not sent to find a breastplate as well.
    """
    uniform = squad.defn
    carried = {i.def_id for i in dwarf.inventory.items}
    want: List[str] = []
    if not any(w in carried for w in uniform.weapons):
        want.extend(uniform.weapons)
    slots_filled = {
        _slot_of(i.def_id) for i in dwarf.inventory.items if i.is_armor
    }
    for piece in uniform.armor:
        if _slot_of(piece) in slots_filled or piece in carried:
            continue
        want.append(piece)
    if uniform.shield and not any(i.is_shield for i in dwarf.inventory.items):
        want.extend(("shield", "buckler"))
    if uniform.id == "marksdwarf" and not any(
            i.is_ammo for i in dwarf.inventory.items):
        want.extend(("bolt", "arrow", "stone_ammo"))
    return want


#: Which body slot each armour piece covers, for "do I already have one".
_ARMOR_SLOT: Dict[str, str] = {
    "cap": "head", "helm": "head", "great_helm": "head",
    "mail_shirt": "body", "breastplate": "body", "leather_armor": "body",
    "chain_leggings": "legs", "greaves": "legs",
    "gauntlets": "hands", "high_boots": "feet",
}


def _slot_of(def_id: str) -> str:
    """The slot an armour piece occupies."""
    return _ARMOR_SLOT.get(def_id, def_id)


def armed(squad: Squad, dwarf) -> bool:
    """True if a dwarf is carrying a weapon its uniform calls for.

    A soldier missing its gauntlets is a soldier. A soldier missing its axe is
    a casualty, so this is the number the roster reports.
    """
    carried = {i.def_id for i in dwarf.inventory.items}
    return any(w in carried for w in squad.defn.weapons)


def readiness(squad: Squad, fort) -> Tuple[int, int]:
    """``(armed, total)`` members of a squad."""
    ready = 0
    total = 0
    for dwarf_id in squad.members:
        dwarf = fort.creatures.get(dwarf_id)
        if dwarf is None or dwarf.body.dead:
            continue
        total += 1
        if armed(squad, dwarf):
            ready += 1
    return (ready, total)


def combat_level(dwarf) -> int:
    """A rough measure of how dangerous a dwarf is, for the squad list."""
    best_weapon = max(
        (dwarf.skills.level(u.skill) for u in UNIFORMS.values()), default=0)
    return (dwarf.skills.level("fighter") + best_weapon
            + dwarf.skills.level("dodging") // 2
            + dwarf.skills.level("armor_use") // 2)
