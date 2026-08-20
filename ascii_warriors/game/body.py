"""Bodies, tissues and wounds.

There is no hit-point pool. A creature dies because something vital was
destroyed, because its head came off, or because it bled out. Every blow lands
on a specific part and works through its tissue layers in order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..data import bodies as body_data
from ..data import materials as mat_data
from ..data.bodies import BodyPartDef
from ..data.descriptors import list_join, wound_severity
from ..engine import colors
from ..engine.rng import RNG
from ..engine.screen import Frag
from .contact import bite, organ_chance, spread

#: Blood volume as a fraction of body volume, in litres per cm^3.
BLOOD_PER_VOLUME = 0.00007
#: What the material doing the cutting is worth, against iron. A blade much
#: harder than what it meets shears more of what it meets, and a soft one
#: folds -- which is the whole of "real material science" as far as a weapon
#: is concerned, and the model did not have it: a weapon's material reached
#: the calculation through its *mass* and through whether it could hold an
#: edge at all, and through nothing else. So a copper sword killed a goblin
#: faster than a steel one, because copper is denser, and adamantine -- the
#: hardest thing in the game, shearing at five million against steel's four
#: hundred and thirty thousand -- was the worst weapon material there is,
#: taking twice as many blows as anything else, because it weighs nothing.
#:
#: Square-rooted, because the raw ratio spans a factor of forty across the
#: metals; clamped, because the game is balanced around iron and a fight
#: should still be a fight; and anchored on iron for the same reason.
#: The yield above which what a blade is made of starts to matter. Skin
#: shears at 20,000 and muscle at 30,000; bone at 115,000. Everything in this
#: game dies of a cut to something soft, and no metal is better than any other
#: at cutting something soft.
KEEN_MATTERS_ABOVE = 50000

KEEN_REFERENCE = "iron"
KEEN_FLOOR = 0.6
#: High enough not to clip adamantine, whose square-rooted ratio against iron
#: is 5.7. Clamping it to 3 left the hardest thing in the game *still* worse
#: than steel, because it is thirty-nine times lighter and momentum is most
#: of a blow: the ceiling has to let the data say what the data says.
KEEN_CEILING = 6.0


def keenness(edge: Optional[Any], edged: bool) -> float:
    """How much better than iron *edge* is at getting through things."""
    if edge is None:
        return 1.0
    iron = mat_data.get(KEEN_REFERENCE)
    mine = edge.shear_yield if edged else edge.impact_yield
    theirs = iron.shear_yield if edged else iron.impact_yield
    if mine <= 0 or theirs <= 0:
        return 1.0
    return max(KEEN_FLOOR, min(KEEN_CEILING, (mine / float(theirs)) ** 0.5))


#: What is left of a bloodless body when it stops. See `structure_fraction`.
STRUCTURE_DEATH = 0.70

#: What a part with a broken bone in it is still worth structurally.
BROKEN_WORTH = 0.35

#: Below this fraction of blood a creature falls unconscious.
BLOOD_FAINT = 0.45
#: Below this fraction of blood a creature dies.
BLOOD_DEATH = 0.20
#: Litres lost per tick per point of wound bleeding.
#:
#: Left where it was, and the reason is worth writing down. Cutting it to
#: 0.001 alongside `CLOT_TICKS` bought an adventurer half again as long to
#: live -- and made every fight in the game two to three times longer, because
#: what kills things here is bleeding: an iron sword went from putting a
#: goblin down in eight blows to eighteen. §126 anchored that number
#: deliberately ("a wolf has to cost what a wolf cost"), and how long a fight
#: lasts is its own question with its own measurement, not a side effect of
#: fixing the clock on clotting.
BLEED_PER_POINT = 0.004

#: Ticks that close one point of bleeding on every open wound, on your feet.
#:
#: A rate, because clotting did not have one. It was a coin flip per call to
#: `Body.tick` -- `rng.chance(0.0018 * ticks)` -- and the same wound over the
#: same four thousand ticks of game time came out at 13.2 points still open if
#: time arrived one tick at a time and 19.1 if it arrived in one lump, because
#: the chance is clamped at 0.9 and a single long call can only ever close one
#: point. Sleeping through the night healed less than walking through it.
#:
#: Fifteen ticks -- a minute and a half -- because that is what makes the two
#: ends of the model say different things. A scratch of two or three points
#: closes in a few minutes and costs a twentieth of your blood; the
#: twenty-eight points a troll leaves in a thigh take seven hundred ticks to
#: close on their own and twenty-four litres of blood to get there, which is
#: five times what a human has. Small wounds close. Big ones need a bandage.
CLOT_TICKS = 15.0

#: The fastest a body can lose blood, as a fraction of its own volume per tick.
#:
#: Bleeding was the sum of every open wound and nothing else, so it had no
#: ceiling: a troll fight left an adventurer with two hundred and sixty-three
#: points of bleeding, which at `BLEED_PER_POINT` is 1.05 litres a tick out of
#: a body that holds 4.9 and dies at 0.98. It was dead in the next six seconds
#: of game time. Wounds do not add up like that -- a heart can only pump so
#: fast, and past a certain point more holes do not empty you any quicker.
#: Three percent a tick is thirty percent a minute: a severed artery, and four
#: minutes from whole to dead.
BLEED_CAP = 0.03

#: Every wound the game can actually give you. `edge` and `blunt` are the only
#: two kinds the tissue model knows, so the first three come out of the physics
#: and the last two are named by whatever did the hurting. This used to list a
#: puncture and a tear as well, neither of which anything could produce -- a
#: spear's `stab` attack has kind `edge`, so a thrust cuts.
#:
#: Named in backticks rather than quoted on purpose: the test that keeps this
#: honest counts string literals, and a comment quoting a dead kind is a second
#: occurrence that hides it.
WOUND_KINDS = ("cut", "bruise", "fracture", "burn", "frostbite")


@dataclass
class Wound:
    """A single injury to one tissue of one part."""

    part: str
    tissue: str
    severity: float
    kind: str
    bleeding: int = 0
    pain: int = 0
    age: int = 0
    severed: bool = False

    def describe(self) -> str:
        """Short wording such as ``"a badly hurt left upper arm"``."""
        if self.severed:
            return "severed"
        return "%s %s" % (wound_severity(self.severity), self.tissue)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the wound."""
        return {
            "p": self.part, "t": self.tissue, "s": self.severity, "k": self.kind,
            "b": self.bleeding, "pa": self.pain, "a": self.age, "sv": self.severed,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Wound":
        """Rebuild from :meth:`to_dict`."""
        return cls(
            part=str(d.get("p", "")), tissue=str(d.get("t", "")),
            severity=float(d.get("s", 0.0)), kind=str(d.get("k", "cut")),
            bleeding=int(d.get("b", 0)), pain=int(d.get("pa", 0)),
            age=int(d.get("a", 0)), severed=bool(d.get("sv", False)),
        )


class PartState:
    """The live condition of one body part."""

    __slots__ = (
        "id", "defn", "size", "tissues", "wounds", "severed", "destroyed",
        "broken", "missing_from",
    )

    def __init__(self, defn: BodyPartDef, size: int) -> None:
        self.id = defn.id
        self.defn = defn
        self.size = max(1, size)
        #: tissue id -> remaining fraction, 1.0 = intact.
        self.tissues: Dict[str, float] = {t: 1.0 for t in defn.tissues}
        self.wounds: List[Wound] = []
        self.severed = False
        self.destroyed = False
        self.broken = False
        #: Set when this part is gone because a parent was severed.
        self.missing_from: Optional[str] = None

    @property
    def name(self) -> str:
        """Display name including the side."""
        return self.defn.display_name

    @property
    def gone(self) -> bool:
        """True if the part is severed or lost with a parent."""
        return self.severed or self.missing_from is not None

    def functional(self) -> bool:
        """True if the part can still do its job."""
        if self.gone or self.destroyed:
            return False
        # A part stops working once its functional tissue is mostly gone.
        for tid, frac in self.tissues.items():
            t = body_data.tissue(tid)
            if t.has("FUNCTIONAL") and frac <= 0.35:
                return False
        if self.broken and self.defn.has("STANCE"):
            return False
        if self.broken and self.defn.has("GRASP"):
            return False
        return True

    def damage_fraction(self) -> float:
        """How damaged the part is overall, 0..1."""
        if self.gone or self.destroyed:
            return 1.0
        if not self.tissues:
            return 0.0
        total = 0.0
        weight = 0.0
        for tid, frac in self.tissues.items():
            t = body_data.tissue(tid)
            w = float(max(1, t.rel_thickness))
            total += (1.0 - frac) * w
            weight += w
        return total / weight if weight else 0.0

    def status(self) -> str:
        """Wording for the part's condition."""
        if self.severed:
            return "severed"
        if self.missing_from:
            return "missing"
        if self.destroyed:
            return "destroyed"
        if self.broken:
            return "broken"
        return wound_severity(self.damage_fraction())

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the part state."""
        return {
            "id": self.id,
            "size": self.size,
            "tissues": dict(self.tissues),
            "wounds": [w.to_dict() for w in self.wounds],
            "severed": self.severed,
            "destroyed": self.destroyed,
            "broken": self.broken,
            "missing_from": self.missing_from,
        }

    def load(self, d: Mapping[str, Any]) -> None:
        """Restore state from :meth:`to_dict`."""
        self.size = int(d.get("size", self.size))
        self.tissues = {k: float(v) for k, v in (d.get("tissues") or {}).items()}
        self.wounds = [Wound.from_dict(w) for w in d.get("wounds", [])]
        self.severed = bool(d.get("severed", False))
        self.destroyed = bool(d.get("destroyed", False))
        self.broken = bool(d.get("broken", False))
        self.missing_from = d.get("missing_from")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "PartState(%s, %s)" % (self.id, self.status())


class Body:
    """A creature's physical condition."""

    def __init__(
        self,
        plan_id: str,
        size: int,
        materials: Optional[Mapping[str, str]] = None,
        missing: Sequence[str] = (),
    ) -> None:
        self.plan_id = plan_id
        self.size = max(1, size)
        self.materials: Dict[str, str] = dict(materials or {})
        #: Tissue layers this creature simply does not have. A skeleton is
        #: bones with nothing on them; giving it skin, fat and muscle made of
        #: bone made it four layers of the toughest tissue in the game, and a
        #: dwarf with a steel warhammer lost to one forty times in forty.
        self.missing: Tuple[str, ...] = tuple(missing)
        parts_def = body_data.build_plan(plan_id)
        total_rel = sum(p.rel_size for p in parts_def) or 1
        self.parts: Dict[str, PartState] = {}
        self.order: List[str] = []
        for pdef in parts_def:
            part_size = max(1, int(self.size * pdef.rel_size / total_rel))
            part = PartState(pdef, part_size)
            for tid in self.missing:
                part.tissues.pop(tid, None)
            self.parts[pdef.id] = part
            self.order.append(pdef.id)

        self.max_blood = max(0.5, self.size * BLOOD_PER_VOLUME)
        self.blood = self.max_blood
        self.pain = 0
        self.stunned = 0
        self.unconscious = 0
        self.winded = 0
        self.dead = False
        self.death_cause = ""
        self.bloodless = False
        #: Lowest blood-warning threshold already announced.
        self._blood_warned = 1.0
        #: Whether the wounds are currently outrunning the clotting. See the
        #: warning in `tick`.
        self._flooding = False
        #: Ticks of rest banked toward closing the next point of bleeding.
        self._rest_ticks = 0.0
        #: The same, banked while upright. Time, not a coin flip per call.
        self._clot_ticks = 0.0

    # -- queries ----------------------------------------------------------- #

    def part(self, pid: str) -> Optional[PartState]:
        """Look up a part by id."""
        return self.parts.get(pid)

    def parts_by_flag(self, flag: str) -> List[PartState]:
        """Every present part carrying *flag*."""
        return [
            p for p in self.parts.values() if p.defn.has(flag) and not p.gone
        ]

    def external_parts(self) -> List[PartState]:
        """Every part a weapon could reach."""
        return [
            self.parts[pid] for pid in self.order
            if not self.parts[pid].defn.has("INTERNAL") and not self.parts[pid].gone
        ]

    def children_of(self, pid: str) -> List[PartState]:
        """Every part hanging off *pid*, recursively."""
        out: List[PartState] = []
        stack = [pid]
        while stack:
            cur = stack.pop()
            for p in self.parts.values():
                if p.defn.parent == cur:
                    out.append(p)
                    stack.append(p.id)
        return out

    def random_part(
        self, rng: RNG, *, weighted: bool = True, prefer: Optional[str] = None
    ) -> PartState:
        """Choose a part to strike, biased toward large exposed ones."""
        candidates = self.external_parts()
        if not candidates:
            candidates = [p for p in self.parts.values() if not p.gone]
        if not candidates:
            return next(iter(self.parts.values()))
        if prefer:
            preferred = [
                p for p in candidates
                if p.id == prefer or p.defn.category == prefer
                or p.defn.has(prefer)
            ]
            if preferred:
                candidates = preferred
        if not weighted:
            return rng.choice(candidates)
        weights = [float(max(1, p.size)) for p in candidates]
        idx = rng.pick_index(weights)
        return candidates[idx if idx >= 0 else 0]

    def can_stand(self) -> bool:
        """True if enough stance parts still work."""
        stance = [p for p in self.parts.values() if p.defn.has("STANCE")]
        if not stance:
            return True
        working = sum(1 for p in stance if p.functional())
        return working >= max(1, len(stance) // 2)

    def can_grasp(self) -> int:
        """How many working grasping parts remain."""
        return sum(
            1 for p in self.parts.values() if p.defn.has("GRASP") and p.functional()
        )

    def can_see(self) -> bool:
        """True if at least one eye still works."""
        eyes = [p for p in self.parts.values() if p.defn.has("SIGHT")]
        if not eyes:
            return True
        return any(p.functional() for p in eyes)

    def can_breathe(self) -> bool:
        """True if at least one breathing part still works."""
        lungs = [p for p in self.parts.values() if p.defn.has("BREATHE")]
        if not lungs:
            return True
        return any(p.functional() for p in lungs)

    def bleeding_rate(self) -> float:
        """Litres of blood lost per tick, and no faster than a body can."""
        total = 0
        for p in self.parts.values():
            for w in p.wounds:
                total += w.bleeding
        rate = total * BLEED_PER_POINT
        if self.max_blood > 0:
            return min(rate, self.max_blood * BLEED_CAP)
        return rate

    def pain_tolerance(self) -> float:
        """How much pain this body can take before shutting down."""
        return 100.0

    def pain_level(self) -> float:
        """Current pain relative to tolerance, 0..1+."""
        return self.pain / self.pain_tolerance()

    def structure_fraction(self) -> float:
        """How much of this body still holds together, 0..1.

        Averaged over each part's tissue layers and weighted by part size, so
        a torso opened up counts for more than a finger, and a broken bone
        counts for most of what the part was worth: a thing held together by
        its skeleton is not held together by a snapped one.

        Only bloodless bodies are judged on this. Everything else in the game
        dies of blood loss long before it comes apart, which is exactly why
        this had to be written.
        """
        total = left = 0.0
        for part in self.parts.values():
            total += part.size
            if part.gone or part.destroyed:
                continue
            share = 1.0
            if part.tissues:
                share = sum(part.tissues.values()) / len(part.tissues)
            if part.broken:
                share *= BROKEN_WORTH
            left += part.size * share
        return left / total if total > 0 else 1.0

    def blood_fraction(self) -> float:
        """Remaining blood as a fraction of full."""
        if self.max_blood <= 0:
            return 1.0
        return max(0.0, self.blood / self.max_blood)

    def health_fraction(self) -> float:
        """A single 0..1 summary used for gauges and AI decisions."""
        if self.dead:
            return 0.0
        vitals = [p for p in self.parts.values() if p.defn.has("VITAL")]
        vital_health = 1.0
        if vitals:
            vital_health = 1.0 - max(p.damage_fraction() for p in vitals)
        blood = self.blood_fraction()
        pain = max(0.0, 1.0 - self.pain_level())
        return max(0.0, min(1.0, min(vital_health, blood) * 0.75 + pain * 0.25))

    def is_incapacitated(self) -> bool:
        """True if the creature cannot act this turn."""
        return self.dead or self.unconscious > 0 or self.stunned > 0

    # -- damage ------------------------------------------------------------ #

    def apply_damage(
        self,
        part_id: str,
        kind: str,
        force: float,
        contact: int,
        penetration: int,
        rng: RNG,
        wound: str = "",
        edge: Optional[Any] = None,
    ) -> List[str]:
        """Drive *force* into a part and return the resulting effect clauses.

        *force* is in kilopascals delivered to the contact area; each tissue
        layer resists with its material's shear (edged) or impact (blunt) yield.

        *contact* decides how that force is spent. A broad edge chews away more
        of every layer it meets and burns itself out doing so; a point takes
        little from each layer and keeps what it came in with, which is how it
        arrives at the far side of the ribs still carrying something.

        *wound* names the injury when the physics cannot. Fire and frostbite
        are both blunt to the tissue model -- neither shears anything -- so
        without this a creature that stood in a fire came out bruised, and
        `WOUND_KINDS` listed a "burn" that nothing in the game could produce.
        """
        part = self.parts.get(part_id)
        if part is None or part.gone:
            return []
        clauses: List[str] = []
        remaining = force
        depth = 0
        edged = kind == "edge"
        width = spread(contact)
        cost = bite(contact)
        # What the blow is made of. See `keenness`.
        keen = keenness(edge, edged)
        layers = list(part.defn.tissues)

        for tid in layers:
            frac = part.tissues.get(tid, 0.0)
            if frac <= 0.0:
                continue
            tissue = body_data.tissue(tid)
            mat = mat_data.get(self.materials.get(tid, tissue.material))
            yield_str = mat.shear_yield if edged else mat.impact_yield
            fracture = mat.shear_fracture if edged else mat.impact_fracture
            # Thicker layers resist more; damaged layers resist less.
            resist = yield_str * (0.35 + 0.65 * frac)
            resist *= 0.6 + 0.4 * (tissue.rel_thickness / 6.0)

            # The metal only counts against something hard. Flesh yields to
            # anything -- skin shears at 20,000 against bone's 115,000 -- so a
            # better edge buys nothing there, and scaling it anyway flattened
            # the weapon triangle: a spear's narrow bite is not at the cap, so
            # lifting it pushed a spear over the threshold where an axe
            # belongs, and §69's "the edge is for the man with no armour"
            # stopped being true. Against bone it is the whole question.
            edge_worth = keen if yield_str >= KEEN_MATTERS_ABOVE else 1.0
            resist /= edge_worth

            if remaining < resist * 0.35:
                if depth == 0:
                    clauses.append("but the attack glances away")
                break

            ratio = remaining / max(1.0, float(resist))
            hurt = max(0.05, min(1.0, ratio * 0.25 * width))
            new_frac = max(0.0, frac - hurt)
            part.tissues[tid] = new_frac
            depth += 1

            severity = 1.0 - new_frac
            wound_kind = wound or _wound_kind(kind, mat.id)
            bleed = 0
            if tissue.has("MAJOR_ARTERIES") and edged:
                bleed = int(6 + 22 * hurt)
            elif tissue.has("MAJOR_ARTERIES"):
                bleed = int(2 + 8 * hurt)
            elif edged:
                bleed = int(1 + 6 * hurt)
            pain = int(tissue.pain_receptors * hurt * 0.5)

            injury = Wound(part.id, tissue.name, severity, wound_kind, bleed, pain)
            part.wounds.append(injury)
            self.pain += pain

            clauses.append(_tissue_clause(tissue.name, wound_kind, hurt, new_frac))

            if mat.id == "bone" and hurt > 0.4:
                part.broken = True
            if new_frac <= 0.0 and tissue.has("FUNCTIONAL"):
                part.destroyed = True

            # Force bleeds off as it passes through each layer, by as much of
            # that layer as the blow actually had to pay for.
            remaining -= resist * (0.55 + 0.45 * frac) * cost
            if remaining <= 0:
                break
            if remaining > fracture * 1.4 and depth >= len(layers):
                break

        # A blow that chews through every layer takes the part off.
        if layers and not part.defn.has("INTERNAL"):
            structural_gone = all(
                part.tissues.get(t, 0.0) <= 0.08 for t in layers
            )
            severable = part.defn.has("LIMB") or part.defn.has("DIGIT") \
                or part.defn.has("HEAD") or part.defn.category in (
                    "arm", "leg", "hand", "foot", "head", "neck", "tail", "wing")
            if structural_gone and edged and severable:
                clauses.extend(self.sever(part.id))
            elif structural_gone:
                part.destroyed = True
                clauses.append("tearing it apart")

        if part.destroyed and part.defn.has("VITAL") and not self.dead:
            self._die("%s destroyed" % part.name)

        if penetration > 3000 and depth >= 2 and not part.defn.has("INTERNAL"):
            self._maybe_hit_organ(part, kind, remaining, contact, rng, clauses,
                                  edge)

        self._check_state()
        return clauses

    def _maybe_hit_organ(
        self,
        part: PartState,
        kind: str,
        force: float,
        contact: int,
        rng: RNG,
        clauses: List[str],
        edge: Optional[Any] = None,
    ) -> None:
        """A deep wound to a torso can reach the organs behind it."""
        if force <= 0:
            return
        organs = [
            p for p in self.parts.values()
            if p.defn.parent == part.id and p.defn.has("INTERNAL") and not p.gone
        ]
        if not organs or not rng.chance(organ_chance(contact)):
            return
        organ = rng.choice(organs)
        before = organ.damage_fraction()
        self.apply_damage(organ.id, kind, force * 0.7, contact, 0, rng,
                          edge=edge)
        if organ.damage_fraction() > before + 0.01:
            clauses.append(
                "and the %s is %s" % (organ.name, wound_severity(
                    organ.damage_fraction()))
            )

    def sever(self, part_id: str) -> List[str]:
        """Take a part off, along with everything attached to it."""
        part = self.parts.get(part_id)
        if part is None or part.gone:
            return []
        part.severed = True
        part.wounds.append(
            Wound(part.id, "everything", 1.0, "cut", bleeding=30, pain=60, severed=True)
        )
        self.pain += 60
        clauses = ["severing it"]
        for child in self.children_of(part_id):
            if not child.gone:
                child.missing_from = part_id
        if part.defn.has("VITAL") or part.defn.has("HEAD"):
            if not self.dead:
                self._die("%s severed" % part.name)
        return clauses

    def _die(self, cause: str) -> None:
        """Mark the body dead."""
        self.dead = True
        self.death_cause = cause
        self.unconscious = 0

    def _check_state(self) -> None:
        """Apply the standing death and unconsciousness rules."""
        if self.dead:
            return
        frac = self.blood_fraction()
        if frac <= BLOOD_DEATH:
            self._die("bled to death")
            return
        # A thing with no blood cannot bleed out and does not faint, so the
        # two rules that end nearly every fight in this game never applied to
        # it. Ten of the eighty-one creatures in the table are bloodless --
        # the four undead, three of the things that live in the caverns, the
        # demon, the bronze colossus and the forgotten beast -- and in
        # practice none of them could be killed at all. Measured: a starting
        # warrior beats a wolf forty times in forty in seven exchanges and
        # loses to a zombie thirty-eight times in forty, having cut the skin,
        # fat and muscle off its torso, neck, both arms and both legs on the
        # way. What stops one is being taken apart.
        if self.bloodless and self.structure_fraction() <= STRUCTURE_DEATH:
            self._die("hacked apart")
            return
        if not self.can_breathe():
            self._die("suffocated")
            return
        for p in self.parts.values():
            if (p.destroyed or p.gone) and (
                p.defn.has("THOUGHT") or p.defn.has("VITAL")
            ):
                self._die("%s destroyed" % p.name)
                return
        if frac <= BLOOD_FAINT and self.unconscious <= 0:
            self.unconscious = 200
        if self.pain_level() >= 1.0 and self.unconscious <= 0:
            self.unconscious = 100

    def apply_blood_loss(self, litres: float) -> None:
        """Remove blood directly (bleeding, thirst, magic)."""
        self.blood = max(0.0, self.blood - litres)
        self._check_state()

    # -- healing and upkeep ------------------------------------------------ #

    def tick(
        self, rng: RNG, ticks: int, toughness: float, recuperation: float
    ) -> List[str]:
        """Advance bleeding, pain, clotting and healing; returns messages."""
        msgs: List[str] = []
        if self.dead or ticks <= 0:
            return msgs

        rate = self.bleeding_rate()
        if rate > 0 and not self.bloodless:
            self.blood = max(0.0, self.blood - rate * ticks)
        elif not self.bloodless and self.blood < self.max_blood:
            # Blood is replaced steadily once the wounds have closed.
            self.blood = min(
                self.max_blood, self.blood + 0.00012 * ticks * recuperation
            )

        # Warn once each time the player crosses a blood threshold downward,
        # so nobody bleeds out without being told it is happening.
        frac = self.blood_fraction()
        if not self.bloodless:
            for level, text in (
                (0.75, "You are bleeding."),
                (0.55, "You are bleeding badly!"),
                (0.35, "You are losing consciousness from blood loss!"),
            ):
                if frac < level and level < self._blood_warned:
                    msgs.append(text)
                    self._blood_warned = level
            if frac > self._blood_warned + 0.1:
                self._blood_warned = min(1.0, frac)

            # The three above are about how much blood is left, which is a
            # number that keeps moving. This one is about the rate, which
            # stops moving at `BLEED_CAP` and stays there -- and while it is
            # stuck there, binding a wound changes nothing you can see.
            #
            # Measured on a doomed run: seventeen consecutive turns of
            # bandaging in a four-way melee. Each bandage really did close
            # fourteen points; twelve more arrived every turn, the total went
            # from forty to a hundred and twenty-four against a ceiling of
            # thirty-seven, and the rate read 0.147 from the first turn to the
            # last. Nothing on the screen said the arithmetic had stopped
            # working. This does.
            at_cap = rate >= self.max_blood * BLEED_CAP - 1e-9
            if at_cap and not self._flooding:
                msgs.append("You are bleeding faster than you can bind it.")
            self._flooding = at_cap

        # Clotting: tougher creatures stop bleeding sooner. Banked as time
        # rather than rolled per call, so an hour of it closes the same wound
        # whether the hour arrives in one piece or in three hundred.
        self._clot_ticks += ticks * max(0.2, toughness)
        closed = int(self._clot_ticks // CLOT_TICKS)
        if closed:
            self._clot_ticks -= closed * CLOT_TICKS
        for p in self.parts.values():
            for w in list(p.wounds):
                w.age += ticks
                if closed and w.bleeding > 0:
                    w.bleeding = max(0, w.bleeding - closed)
                if w.pain > 0:
                    w.pain = max(0, w.pain - max(1, int(ticks * 0.02)))

        # Pain fades toward the sum of current wound pain.
        target = sum(w.pain for p in self.parts.values() for w in p.wounds)
        if self.pain > target:
            self.pain = max(target, self.pain - max(1, int(ticks * 0.05)))

        if self.stunned > 0:
            self.stunned = max(0, self.stunned - ticks)
        if self.winded > 0:
            self.winded = max(0, self.winded - ticks)
        if self.unconscious > 0:
            self.unconscious = max(0, self.unconscious - ticks)
            if self.unconscious == 0:
                msgs.append("You come to.")

        # Slow tissue regeneration.
        heal_chance = min(0.5, 0.00025 * ticks * recuperation)
        if heal_chance > 0 and rng.chance(heal_chance):
            for p in self.parts.values():
                if p.gone:
                    continue
                for tid, frac in list(p.tissues.items()):
                    if frac < 1.0:
                        t = body_data.tissue(tid)
                        p.tissues[tid] = min(
                            1.0, frac + 0.01 * (t.heal_rate / 100.0) * recuperation
                        )
                p.wounds = [w for w in p.wounds if w.severed or w.severity > 0.05
                            or w.bleeding > 0]
                if p.broken and all(
                    p.tissues.get(t, 1.0) > 0.85 for t in p.defn.tissues
                ):
                    p.broken = False
            if not self.bloodless:
                self.blood = min(
                    self.max_blood, self.blood + 0.002 * ticks * recuperation
                )

        self._check_state()
        return msgs

    def rest_heal(self, ticks: int, recuperation: float) -> None:
        """Accelerated healing while sleeping or resting.

        Rest closes wounds faster than standing about does, but it does not
        close them instantly. Lying down used to zero every wound in the body
        on the first call, which made a bandage worthless and a severed artery
        a minor inconvenience.
        """
        # The same clock as standing up, and the caller's multiplier is what
        # makes lying down worth doing: `_handle_wounds` banks three ticks of
        # rest per tick and `_go_sleep` four. A second constant for it only
        # ever meant the two could drift, and they did -- rest at five ticks a
        # point closed six points a step, which out-healed a mortal wound and
        # made the bandage decorative.
        self._rest_ticks += ticks * max(0.2, recuperation)
        closed = int(self._rest_ticks // CLOT_TICKS)
        if closed:
            self._rest_ticks -= closed * CLOT_TICKS

        for p in self.parts.values():
            if p.gone:
                continue
            for tid, frac in list(p.tissues.items()):
                if frac < 1.0:
                    t = body_data.tissue(tid)
                    p.tissues[tid] = min(
                        1.0, frac + (ticks / 3000.0) * (t.heal_rate / 100.0)
                        * recuperation
                    )
            if closed:
                for w in p.wounds:
                    if w.bleeding > 0:
                        w.bleeding = max(0, w.bleeding - closed)
            # A wound only stops being a wound once the flesh under it has
            # knitted back together.
            p.wounds = [
                w for w in p.wounds
                if w.severed or w.bleeding > 0 or p.damage_fraction() > 0.02
            ]
            if p.broken and all(p.tissues.get(t, 1.0) > 0.8 for t in p.defn.tissues):
                p.broken = False
        if not self.bloodless:
            self.blood = min(
                self.max_blood, self.blood + (ticks / 2000.0) * recuperation
            )
        self.pain = max(0, self.pain - ticks // 20)

    # -- presentation ------------------------------------------------------ #

    def wound_summary(self) -> str:
        """One-line summary of the worst injuries."""
        hurt = [
            p for p in self.parts.values()
            if p.gone or p.broken or p.damage_fraction() > 0.08
        ]
        if not hurt:
            return "unhurt"
        hurt.sort(key=lambda p: -p.damage_fraction())
        return list_join(["%s %s" % (p.status(), p.name) for p in hurt[:3]])

    def status_lines(self) -> List[Frag]:
        """Coloured lines for the status panel."""
        out: List[Frag] = []
        for pid in self.order:
            p = self.parts[pid]
            if p.defn.has("INTERNAL") and not (p.gone or p.destroyed or p.wounds):
                continue
            frac = p.damage_fraction()
            if not p.gone and not p.broken and frac < 0.05:
                continue
            if p.gone:
                col = colors.UI["danger"]
            elif p.destroyed or frac > 0.7:
                col = colors.UI["danger"]
            elif p.broken or frac > 0.35:
                col = colors.UI["warn"]
            else:
                col = colors.UI["fg"]
            out.append(Frag("%s: %s" % (p.name, p.status()), col))
        if not out:
            out.append(Frag("You are unhurt.", colors.UI["good"]))
        return out

    def describe_state(self) -> List[str]:
        """Plain sentences about the body's overall condition."""
        lines: List[str] = []
        bf = self.blood_fraction()
        if bf < 0.35:
            lines.append("You have lost a dangerous amount of blood.")
        elif bf < 0.7:
            lines.append("You have lost blood.")
        if self.pain_level() > 0.6:
            lines.append("You are in terrible pain.")
        elif self.pain_level() > 0.3:
            lines.append("You are in pain.")
        if not self.can_stand():
            lines.append("You cannot stand.")
        if not self.can_see():
            lines.append("You cannot see.")
        if self.can_grasp() == 0:
            lines.append("You cannot grasp anything.")
        return lines

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the whole body."""
        return {
            "plan": self.plan_id,
            "size": self.size,
            "materials": dict(self.materials),
            "parts": [p.to_dict() for p in self.parts.values()],
            "blood": self.blood,
            "max_blood": self.max_blood,
            "pain": self.pain,
            "stunned": self.stunned,
            "unconscious": self.unconscious,
            "winded": self.winded,
            "dead": self.dead,
            "cause": self.death_cause,
            "bloodless": self.bloodless,
            "missing": list(self.missing),
            "warned": self._blood_warned,
            "flooding": self._flooding,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Body":
        """Rebuild from :meth:`to_dict`."""
        b = cls(str(d.get("plan", "humanoid")), int(d.get("size", 60000)),
                d.get("materials") or {})
        for pd in d.get("parts", []):
            p = b.parts.get(str(pd.get("id", "")))
            if p is not None:
                p.load(pd)
        b.blood = float(d.get("blood", b.max_blood))
        b.max_blood = float(d.get("max_blood", b.max_blood))
        b.pain = int(d.get("pain", 0))
        b.stunned = int(d.get("stunned", 0))
        b.unconscious = int(d.get("unconscious", 0))
        b.winded = int(d.get("winded", 0))
        b.dead = bool(d.get("dead", False))
        b.death_cause = str(d.get("cause", ""))
        b.bloodless = bool(d.get("bloodless", False))
        b.missing = tuple(str(t) for t in d.get("missing", ()))
        b._blood_warned = float(d.get("warned", 1.0))
        b._flooding = bool(d.get("flooding", False))
        return b

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Body(%s, %d parts, %s)" % (
            self.plan_id, len(self.parts), "dead" if self.dead else "alive"
        )


def _wound_kind(attack_kind: str, material: str) -> str:
    """Map an attack type and tissue material to a wound description."""
    if attack_kind == "edge":
        return "fracture" if material == "bone" else "cut"
    if material == "bone":
        return "fracture"
    return "bruise"


#: How a wound reads at each depth: gone, deep, middling, shallow. Fire and
#: cold are blunt to the tissue model and had been describing themselves as
#: bruises, which is what standing in a fire used to say.
_CLAUSES = {
    "fracture": ("shattering", "shattering", "fracturing", "chipping"),
    "cut": ("tearing apart", "tearing", "tearing", "cutting"),
    "burn": ("burning away", "charring", "burning", "scorching"),
    "frostbite": ("killing", "freezing", "numbing", "chilling"),
}
_BRUISE = ("tearing apart", "denting", "bruising", "bruising")


def _tissue_clause(tissue_name: str, kind: str, hurt: float, remaining: float) -> str:
    """Build the phrase describing what happened to one tissue layer."""
    words = _CLAUSES.get(kind, _BRUISE)
    if remaining <= 0.0:
        depth = 0
    elif hurt > 0.6:
        depth = 1
    elif hurt > 0.3:
        depth = 2
    else:
        depth = 3
    return "%s the %s" % (words[depth], tissue_name)
