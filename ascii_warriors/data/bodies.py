"""Body plans: the part trees and tissue layers combat cuts through."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

PART_FLAGS = frozenset({
    "VITAL", "GRASP", "STANCE", "SIGHT", "HEARING", "SMELL", "BREATHE", "THOUGHT",
    "CIRCULATION", "DIGEST", "INTERNAL", "SMALL", "JOINT", "NERVOUS", "HEAD",
    "UPPERBODY", "LOWERBODY", "LIMB", "DIGIT", "TOTEMABLE", "NAIL", "TEETH",
    "FLIER", "EMBEDDED",
})


@dataclass(frozen=True)
class Tissue:
    """One layer of stuff a body part is made of."""

    id: str
    name: str
    material: str
    rel_thickness: int
    heal_rate: int
    pain_receptors: int
    flags: FrozenSet[str]

    def has(self, flag: str) -> bool:
        """True if this tissue carries *flag*."""
        return flag in self.flags


@dataclass(frozen=True)
class BodyPartDef:
    """One node in a creature's body tree."""

    id: str
    name: str
    parent: Optional[str]
    rel_size: int
    flags: FrozenSet[str]
    tissues: Tuple[str, ...]
    side: Optional[str]
    category: str

    def has(self, flag: str) -> bool:
        """True if this part carries *flag*."""
        return flag in self.flags

    @property
    def display_name(self) -> str:
        """Name including the side, e.g. ``"left upper arm"``."""
        if self.side:
            return "%s %s" % (self.side, self.name)
        return self.name


def _t(
    tid: str,
    name: str,
    material: str,
    thickness: int,
    heal: int,
    pain: int,
    *flags: str,
) -> Tissue:
    return Tissue(
        id=tid, name=name, material=material, rel_thickness=thickness,
        heal_rate=heal, pain_receptors=pain, flags=frozenset(flags),
    )


TISSUES: Dict[str, Tissue] = {
    t.id: t
    for t in (
        _t("skin", "skin", "skin", 2, 100, 50, "CONNECTIVE", "STRUCTURAL"),
        _t("fat", "fat", "fat", 3, 100, 15, "CONNECTIVE"),
        _t("muscle", "muscle", "muscle", 6, 90, 50, "CONNECTIVE", "STRUCTURAL",
           "MAJOR_ARTERIES"),
        _t("bone", "bone", "bone", 4, 40, 20, "STRUCTURAL", "CONNECTIVE"),
        _t("cartilage", "cartilage", "cartilage", 2, 50, 20, "STRUCTURAL"),
        _t("nerve", "nervous tissue", "nerve", 1, 5, 100, "FUNCTIONAL"),
        _t("brain", "brain", "brain", 8, 5, 100, "FUNCTIONAL", "MAJOR_ARTERIES"),
        _t("heart", "heart", "heart", 6, 20, 90, "FUNCTIONAL", "MAJOR_ARTERIES"),
        _t("lung", "lung", "lung", 6, 30, 60, "FUNCTIONAL", "MAJOR_ARTERIES"),
        _t("gut", "guts", "gut", 6, 40, 70, "FUNCTIONAL"),
        _t("liver", "liver", "liver", 6, 40, 70, "FUNCTIONAL", "MAJOR_ARTERIES"),
        _t("eye", "eye", "eye", 4, 10, 90, "FUNCTIONAL"),
        _t("nail", "nail", "nail", 1, 60, 5, "STRUCTURAL"),
        _t("hair", "hair", "hair", 1, 80, 1, ()),
        _t("scale", "scale", "scale", 3, 60, 20, "STRUCTURAL", "CONNECTIVE"),
        _t("chitin", "chitin", "chitin", 4, 40, 20, "STRUCTURAL", "CONNECTIVE"),
        _t("feather", "feather", "feather", 1, 70, 5, ()),
        _t("tooth", "tooth", "tooth", 2, 20, 10, "STRUCTURAL"),
    )
}

#: The usual outer stack for flesh-and-blood creatures.
FLESH = ("skin", "fat", "muscle", "bone")
SCALED = ("scale", "fat", "muscle", "bone")
CHITINOUS = ("chitin", "fat", "muscle")
FEATHERED = ("feather", "skin", "fat", "muscle", "bone")


def _p(
    pid: str,
    name: str,
    parent: Optional[str],
    size: int,
    category: str,
    tissues: Tuple[str, ...] = FLESH,
    side: Optional[str] = None,
    *flags: str,
) -> BodyPartDef:
    return BodyPartDef(
        id=pid, name=name, parent=parent, rel_size=size,
        flags=frozenset(flags), tissues=tissues, side=side, category=category,
    )


def _limb_pair(
    base: str,
    name: str,
    parent: str,
    sizes: Tuple[int, int, int, int],
    categories: Tuple[str, str, str, str],
    end_flags: Tuple[str, ...],
    tissues: Tuple[str, ...] = FLESH,
) -> List[BodyPartDef]:
    """Build a mirrored four-segment limb (upper, lower, extremity, digits)."""
    parts: List[BodyPartDef] = []
    upper, lower, ext, digit = name
    for side in ("left", "right"):
        p_up = "%s_%s_upper" % (side, base)
        p_lo = "%s_%s_lower" % (side, base)
        p_ex = "%s_%s" % (side, base + "_end")
        p_di = "%s_%s_digits" % (side, base)
        parts.append(
            _p(p_up, upper, parent, sizes[0], categories[0], tissues, side, "LIMB")
        )
        parts.append(
            _p(p_lo, lower, p_up, sizes[1], categories[1], tissues, side,
               "LIMB", "JOINT")
        )
        parts.append(
            _p(p_ex, ext, p_lo, sizes[2], categories[2], tissues, side, *end_flags)
        )
        parts.append(
            _p(p_di, digit, p_ex, sizes[3], categories[3], tissues, side,
               "DIGIT", "SMALL")
        )
    return parts


# --------------------------------------------------------------------------- #
# Humanoid
# --------------------------------------------------------------------------- #

_HUMANOID: List[BodyPartDef] = [
    _p("upper_body", "upper body", None, 600, "torso", FLESH, None,
       "UPPERBODY", "VITAL"),
    _p("lower_body", "lower body", "upper_body", 500, "torso", FLESH, None,
       "LOWERBODY", "VITAL"),
    _p("neck", "neck", "upper_body", 100, "neck", FLESH, None, "JOINT"),
    _p("head", "head", "neck", 300, "head", FLESH, None, "HEAD", "VITAL", "TOTEMABLE"),
    _p("brain", "brain", "head", 60, "organ", ("brain",), None,
       "VITAL", "THOUGHT", "INTERNAL", "SMALL"),
    _p("skull", "skull", "head", 80, "organ", ("bone",), None, "INTERNAL"),
    _p("left_eye", "eye", "head", 8, "organ", ("eye",), "left", "SIGHT", "SMALL"),
    _p("right_eye", "eye", "head", 8, "organ", ("eye",), "right", "SIGHT", "SMALL"),
    _p("left_ear", "ear", "head", 8, "organ", ("skin", "cartilage"), "left",
       "HEARING", "SMALL"),
    _p("right_ear", "ear", "head", 8, "organ", ("skin", "cartilage"), "right",
       "HEARING", "SMALL"),
    _p("nose", "nose", "head", 10, "organ", ("skin", "cartilage"), None,
       "SMELL", "SMALL"),
    _p("mouth", "mouth", "head", 20, "organ", ("skin", "muscle"), None, "SMALL"),
    _p("teeth", "teeth", "mouth", 10, "organ", ("tooth",), None, "TEETH", "SMALL"),
    _p("throat", "throat", "neck", 30, "organ", ("skin", "muscle", "cartilage"),
       None, "BREATHE", "SMALL", "VITAL"),
    _p("spine", "spine", "upper_body", 80, "organ", ("bone", "nerve"), None,
       "INTERNAL", "NERVOUS"),
    _p("ribs", "ribs", "upper_body", 90, "organ", ("bone",), None, "INTERNAL"),
    _p("heart", "heart", "upper_body", 50, "organ", ("heart",), None,
       "VITAL", "CIRCULATION", "INTERNAL", "SMALL"),
    _p("left_lung", "lung", "upper_body", 60, "organ", ("lung",), "left",
       "VITAL", "BREATHE", "INTERNAL"),
    _p("right_lung", "lung", "upper_body", 60, "organ", ("lung",), "right",
       "VITAL", "BREATHE", "INTERNAL"),
    _p("liver", "liver", "lower_body", 60, "organ", ("liver",), None,
       "VITAL", "INTERNAL"),
    _p("stomach", "stomach", "lower_body", 50, "organ", ("gut",), None,
       "DIGEST", "INTERNAL"),
    _p("guts", "guts", "lower_body", 90, "organ", ("gut",), None,
       "DIGEST", "INTERNAL"),
    _p("spleen", "spleen", "lower_body", 20, "organ", ("gut",), None,
       "INTERNAL", "SMALL"),
    _p("left_kidney", "kidney", "lower_body", 20, "organ", ("gut",), "left",
       "INTERNAL", "SMALL"),
    _p("right_kidney", "kidney", "lower_body", 20, "organ", ("gut",), "right",
       "INTERNAL", "SMALL"),
]
_HUMANOID += _limb_pair(
    "arm", ("upper arm", "lower arm", "hand", "fingers"), "upper_body",
    (200, 180, 100, 40), ("arm", "arm", "hand", "hand"), ("GRASP",),
)
_HUMANOID += _limb_pair(
    "leg", ("upper leg", "lower leg", "foot", "toes"), "lower_body",
    (280, 250, 120, 40), ("leg", "leg", "foot", "foot"), ("STANCE",),
)

# --------------------------------------------------------------------------- #
# Other plans
# --------------------------------------------------------------------------- #


def _basic_head(parent: str, tissues: Tuple[str, ...] = FLESH) -> List[BodyPartDef]:
    """A simple head cluster used by non-humanoid plans."""
    return [
        _p("head", "head", parent, 250, "head", tissues, None,
           "HEAD", "VITAL", "TOTEMABLE"),
        _p("brain", "brain", "head", 50, "organ", ("brain",), None,
           "VITAL", "THOUGHT", "INTERNAL", "SMALL"),
        _p("skull", "skull", "head", 70, "organ", ("bone",), None, "INTERNAL"),
        _p("left_eye", "eye", "head", 8, "organ", ("eye",), "left", "SIGHT", "SMALL"),
        _p("right_eye", "eye", "head", 8, "organ", ("eye",), "right", "SIGHT", "SMALL"),
        _p("mouth", "mouth", "head", 25, "organ", ("skin", "muscle"), None, "SMALL"),
        _p("teeth", "teeth", "mouth", 15, "organ", ("tooth",), None, "TEETH", "SMALL"),
        _p("throat", "throat", "head", 25, "organ", ("skin", "muscle"), None,
           "BREATHE", "SMALL", "VITAL"),
    ]


def _core_organs(torso: str) -> List[BodyPartDef]:
    """Heart, lungs and guts hung off a torso part."""
    return [
        _p("heart", "heart", torso, 50, "organ", ("heart",), None,
           "VITAL", "CIRCULATION", "INTERNAL", "SMALL"),
        _p("left_lung", "lung", torso, 55, "organ", ("lung",), "left",
           "VITAL", "BREATHE", "INTERNAL"),
        _p("right_lung", "lung", torso, 55, "organ", ("lung",), "right",
           "VITAL", "BREATHE", "INTERNAL"),
        _p("guts", "guts", torso, 80, "organ", ("gut",), None, "DIGEST", "INTERNAL"),
        _p("spine", "spine", torso, 70, "organ", ("bone", "nerve"), None,
           "INTERNAL", "NERVOUS"),
    ]


_QUADRUPED: List[BodyPartDef] = (
    [
        _p("body", "body", None, 900, "torso", FLESH, None, "UPPERBODY", "VITAL"),
        _p("neck", "neck", "body", 90, "neck", FLESH, None, "JOINT"),
    ]
    + _basic_head("neck")
    + _core_organs("body")
    + [_p("tail", "tail", "body", 90, "tail", FLESH, None, "LIMB")]
    + _limb_pair(
        "front_leg", ("upper front leg", "lower front leg", "front foot", "claws"),
        "body", (200, 180, 90, 30), ("leg", "leg", "foot", "foot"), ("STANCE",),
    )
    + _limb_pair(
        "rear_leg", ("upper rear leg", "lower rear leg", "rear foot", "claws"),
        "body", (220, 200, 90, 30), ("leg", "leg", "foot", "foot"), ("STANCE",),
    )
)

_BIRD: List[BodyPartDef] = (
    [
        _p("body", "body", None, 500, "torso", FEATHERED, None, "UPPERBODY", "VITAL"),
        _p("neck", "neck", "body", 60, "neck", FEATHERED, None, "JOINT"),
        _p("left_wing", "wing", "body", 200, "wing", FEATHERED, "left",
           "LIMB", "FLIER"),
        _p("right_wing", "wing", "body", 200, "wing", FEATHERED, "right",
           "LIMB", "FLIER"),
        _p("tail", "tail feathers", "body", 60, "tail", ("feather",), None, "SMALL"),
        _p("beak", "beak", "body", 30, "head", ("nail",), None, "SMALL", "TEETH"),
    ]
    + _basic_head("neck", FEATHERED)
    + _core_organs("body")
    + _limb_pair(
        "leg", ("upper leg", "lower leg", "foot", "talons"), "body",
        (90, 80, 50, 20), ("leg", "leg", "foot", "foot"), ("STANCE", "GRASP"),
        FEATHERED,
    )
)

_SERPENT: List[BodyPartDef] = (
    [
        _p("body", "body", None, 1000, "torso", SCALED, None, "UPPERBODY", "VITAL"),
        _p("tail", "tail", "body", 400, "tail", SCALED, None, "LIMB", "STANCE"),
    ]
    + _basic_head("body", SCALED)
    + _core_organs("body")
)

_FISH: List[BodyPartDef] = (
    [
        _p("body", "body", None, 800, "torso", SCALED, None, "UPPERBODY", "VITAL"),
        _p("tail", "tail fin", "body", 150, "tail", SCALED, None, "LIMB", "STANCE"),
        _p("left_fin", "fin", "body", 60, "fin", SCALED, "left", "LIMB"),
        _p("right_fin", "fin", "body", 60, "fin", SCALED, "right", "LIMB"),
        _p("gills", "gills", "body", 50, "organ", ("skin", "muscle"), None,
           "BREATHE", "VITAL", "SMALL"),
    ]
    + _basic_head("body", SCALED)
    + [
        _p("heart", "heart", "body", 40, "organ", ("heart",), None,
           "VITAL", "CIRCULATION", "INTERNAL", "SMALL"),
        _p("guts", "guts", "body", 70, "organ", ("gut",), None, "DIGEST", "INTERNAL"),
        _p("spine", "spine", "body", 60, "organ", ("bone", "nerve"), None,
           "INTERNAL", "NERVOUS"),
    ]
)

_INSECT: List[BodyPartDef] = [
    _p("thorax", "thorax", None, 400, "torso", CHITINOUS, None, "UPPERBODY", "VITAL"),
    _p("abdomen", "abdomen", "thorax", 400, "torso", CHITINOUS, None,
       "LOWERBODY", "VITAL"),
    _p("head", "head", "thorax", 180, "head", CHITINOUS, None, "HEAD", "VITAL"),
    _p("brain", "brain", "head", 30, "organ", ("brain",), None,
       "VITAL", "THOUGHT", "INTERNAL", "SMALL"),
    _p("left_eye", "compound eye", "head", 20, "organ", ("eye",), "left",
       "SIGHT", "SMALL"),
    _p("right_eye", "compound eye", "head", 20, "organ", ("eye",), "right",
       "SIGHT", "SMALL"),
    _p("mandibles", "mandibles", "head", 40, "organ", ("chitin",), None,
       "TEETH", "SMALL"),
    _p("guts", "guts", "abdomen", 80, "organ", ("gut",), None, "DIGEST", "INTERNAL"),
]
for _i, _side in enumerate(("left", "right")):
    for _n in (1, 2, 3):
        _INSECT.append(
            _p("%s_leg_%d" % (_side, _n), "leg", "thorax", 60, "leg",
               CHITINOUS, _side, "LIMB", "STANCE")
        )

_BLOB: List[BodyPartDef] = [
    _p("body", "body", None, 1000, "torso", ("skin", "fat"), None,
       "UPPERBODY", "VITAL", "THOUGHT"),
]

_DRAGON: List[BodyPartDef] = (
    [
        _p("body", "body", None, 1400, "torso", SCALED, None, "UPPERBODY", "VITAL"),
        _p("neck", "neck", "body", 200, "neck", SCALED, None, "JOINT"),
        _p("tail", "tail", "body", 400, "tail", SCALED, None, "LIMB"),
        _p("left_wing", "wing", "body", 400, "wing", SCALED, "left", "LIMB", "FLIER"),
        _p("right_wing", "wing", "body", 400, "wing", SCALED, "right", "LIMB", "FLIER"),
    ]
    + _basic_head("neck", SCALED)
    + _core_organs("body")
    + _limb_pair(
        "front_leg", ("upper front leg", "lower front leg", "front claw", "talons"),
        "body", (260, 230, 120, 50), ("leg", "leg", "foot", "foot"),
        ("STANCE", "GRASP"), SCALED,
    )
    + _limb_pair(
        "rear_leg", ("upper rear leg", "lower rear leg", "rear claw", "talons"),
        "body", (280, 250, 120, 50), ("leg", "leg", "foot", "foot"),
        ("STANCE",), SCALED,
    )
)

# A giant humanoid is the humanoid plan without the fiddly small parts.
_GIANT_HUMANOID: List[BodyPartDef] = [
    p for p in _HUMANOID if p.id not in ("spleen", "left_kidney", "right_kidney")
]


BODY_PLANS: Dict[str, Tuple[BodyPartDef, ...]] = {
    "humanoid": tuple(_HUMANOID),
    "giant_humanoid": tuple(_GIANT_HUMANOID),
    "quadruped": tuple(_QUADRUPED),
    "bird": tuple(_BIRD),
    "serpent": tuple(_SERPENT),
    "fish": tuple(_FISH),
    "insect": tuple(_INSECT),
    "blob": tuple(_BLOB),
    "dragon": tuple(_DRAGON),
}


def build_plan(plan_id: str) -> Tuple[BodyPartDef, ...]:
    """Return a body plan's parts, defaulting to the humanoid plan."""
    return BODY_PLANS.get(plan_id, BODY_PLANS["humanoid"])


def plan_ids() -> List[str]:
    """Every known plan id."""
    return sorted(BODY_PLANS)


def tissue(tid: str) -> Tissue:
    """Look up a tissue, defaulting to muscle."""
    return TISSUES.get(tid) or TISSUES["muscle"]


def validate() -> List[str]:
    """Check every plan for dangling parents and unknown tissues.

    Returns a list of problem descriptions; an empty list means the data is sound.
    """
    problems: List[str] = []
    for plan, parts in BODY_PLANS.items():
        ids = {p.id for p in parts}
        roots = [p for p in parts if p.parent is None]
        if len(roots) != 1:
            problems.append("%s: expected exactly one root, found %d" % (plan, len(roots)))
        for p in parts:
            if p.parent is not None and p.parent not in ids:
                problems.append("%s: %s has unknown parent %s" % (plan, p.id, p.parent))
            for t in p.tissues:
                if t not in TISSUES:
                    problems.append("%s: %s has unknown tissue %s" % (plan, p.id, t))
            for f in p.flags:
                if f not in PART_FLAGS:
                    problems.append("%s: %s has unknown flag %s" % (plan, p.id, f))
        if not any(p.has("VITAL") for p in parts):
            problems.append("%s: no vital parts" % plan)
    return problems
