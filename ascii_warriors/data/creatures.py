"""The bestiary: every creature that walks, swims, flies or shambles."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from ..engine import colors
from ..engine.colors import Color
from ..engine.rng import RNG
from .items import (
    BITE, BUTT, CLAW, CRUSH, GORE, KICK, PECK, PUNCH, SCRATCH, SLAM, STING,
    AttackDef,
)


@dataclass(frozen=True)
class NaturalAttack:
    """An attack a creature makes with part of its own body."""

    part: str
    attack: AttackDef


@dataclass(frozen=True)
class CreatureDef:
    """A species."""

    id: str
    name: str
    plural: str
    adjective: str
    glyph: str
    color: Color
    body_plan: str
    size: int
    tier: int
    attributes: Mapping[str, int]
    skills: Mapping[str, int]
    attacks: Tuple[NaturalAttack, ...]
    biomes: FrozenSet[str]
    flags: FrozenSet[str]
    group: Tuple[int, int] = (1, 1)
    speed: int = 100
    frequency: int = 50
    diet: str = "omnivore"
    blood: str = "blood"
    lifespan: Tuple[int, int] = (60, 100)
    civ: Optional[str] = None
    child_name: str = ""
    description: str = ""
    natural_armor: int = 0

    def has(self, flag: str) -> bool:
        """True if this creature carries *flag*."""
        return flag in self.flags

    @property
    def intelligent(self) -> bool:
        """True for creatures that talk, trade and hold grudges."""
        return "INTELLIGENT" in self.flags


CREATURES: Dict[str, CreatureDef] = {}

#: Biome sets used repeatedly below.
ANY_LAND = frozenset({
    "tundra", "taiga", "temperate_forest", "temperate_broadleaf",
    "tropical_forest", "jungle", "savanna", "shrubland", "grassland",
    "desert", "badlands", "mountain", "hills", "marsh", "swamp", "beach",
})
FOREST = frozenset({
    "taiga", "temperate_forest", "temperate_broadleaf", "tropical_forest",
    "jungle", "swamp",
})
OPEN = frozenset({"grassland", "savanna", "shrubland", "hills", "tundra"})
COLD = frozenset({"tundra", "taiga", "glacier", "mountain"})
HOT = frozenset({"desert", "badlands", "savanna", "jungle", "tropical_forest"})
WATER = frozenset({"ocean", "deep_ocean", "lake", "river"})
UNDERGROUND = frozenset({"cave"})


def _c(
    cid: str,
    name: str,
    glyph: str,
    color: Color,
    plan: str,
    size: int,
    tier: int,
    biomes: FrozenSet[str],
    flags: Tuple[str, ...],
    attacks: Tuple[NaturalAttack, ...] = (),
    *,
    plural: str = "",
    adjective: str = "",
    attributes: Optional[Mapping[str, int]] = None,
    skills: Optional[Mapping[str, int]] = None,
    group: Tuple[int, int] = (1, 1),
    speed: int = 100,
    frequency: int = 50,
    diet: str = "omnivore",
    blood: str = "blood",
    lifespan: Tuple[int, int] = (10, 20),
    civ: Optional[str] = None,
    child_name: str = "",
    desc: str = "",
    armor: int = 0,
) -> CreatureDef:
    cd = CreatureDef(
        id=cid, name=name, plural=plural or (name + "s"),
        adjective=adjective or name, glyph=glyph, color=color,
        body_plan=plan, size=size, tier=tier,
        attributes=dict(attributes or {}), skills=dict(skills or {}),
        attacks=attacks, biomes=biomes, flags=frozenset(flags),
        group=group, speed=speed, frequency=frequency, diet=diet, blood=blood,
        lifespan=lifespan, civ=civ, child_name=child_name, description=desc,
        natural_armor=armor,
    )
    CREATURES[cid] = cd
    return cd


def _na(part: str, attack: AttackDef) -> NaturalAttack:
    return NaturalAttack(part, attack)


HUMANOID_ATTACKS = (
    _na("left_arm_end", PUNCH),
    _na("right_arm_end", PUNCH),
    _na("left_leg_end", KICK),
    _na("teeth", BITE),
)

# --------------------------------------------------------------------------- #
# Civilised races
# --------------------------------------------------------------------------- #

_c("dwarf", "dwarf", "@", colors.Color(196, 150, 96), "humanoid", 60000, 2,
   frozenset({"mountain", "hills"}),
   ("INTELLIGENT", "CIVILIZED", "CAN_SPEAK", "TRAINABLE"),
   HUMANOID_ATTACKS, plural="dwarves", adjective="dwarven",
   attributes={"strength": 1250, "toughness": 1250, "endurance": 1150,
               "willpower": 1150, "analytical_ability": 1050},
   skills={}, lifespan=(150, 170), civ="dwarf", child_name="dwarven child",
   desc="Short, broad and stubborn. Fond of stone, metal and strong drink.")

_c("human", "human", "@", colors.Color(214, 176, 140), "humanoid", 70000, 2,
   OPEN | FOREST,
   ("INTELLIGENT", "CIVILIZED", "CAN_SPEAK", "TRAINABLE"),
   HUMANOID_ATTACKS, adjective="human",
   attributes={}, lifespan=(70, 90), civ="human", child_name="human child",
   desc="Adaptable, short-lived and everywhere.")

_c("elf", "elf", "@", colors.Color(150, 206, 140), "humanoid", 60000, 2,
   FOREST, ("INTELLIGENT", "CIVILIZED", "CAN_SPEAK", "GOOD"),
   HUMANOID_ATTACKS, plural="elves", adjective="elven",
   attributes={"agility": 1250, "spatial_sense": 1200, "strength": 900},
   skills={"bow": 3, "dodging": 2, "ambusher": 2},
   lifespan=(700, 900), civ="elf", child_name="elven child",
   desc="Long-lived forest dwellers who will not suffer an axe near a tree.")

_c("goblin", "goblin", "g", colors.Color(122, 158, 96), "humanoid", 50000, 2,
   ANY_LAND, ("INTELLIGENT", "CIVILIZED", "CAN_SPEAK", "EVIL", "NO_FEAR"),
   HUMANOID_ATTACKS, adjective="goblin",
   attributes={"agility": 1150, "strength": 950, "empathy": 600},
   skills={"fighter": 1, "dodging": 1},
   group=(1, 4), lifespan=(1000, 1200), civ="goblin", child_name="goblin child",
   desc="Cruel, tireless and unaging. They do not fear death.")

_c("kobold", "kobold", "k", colors.Color(158, 132, 88), "humanoid", 25000, 1,
   ANY_LAND, ("INTELLIGENT", "CIVILIZED", "EVIL", "AMBUSHER"),
   HUMANOID_ATTACKS, adjective="kobold",
   attributes={"agility": 1200, "strength": 700, "toughness": 800},
   skills={"sneak": 4, "ambusher": 3, "dodging": 2},
   group=(2, 5), speed=110, lifespan=(40, 60), civ="kobold",
   desc="Small, sly and light-fingered. They cannot speak, but they can steal.")

PLAYABLE_RACES: Tuple[str, ...] = ("dwarf", "human", "elf", "goblin", "kobold")

# Civilised professions reuse the base races but read differently in play.
for _pid, _pname, _prace, _pcol, _pskills in (
    ("bandit", "bandit", "human", colors.Color(168, 96, 78),
     {"fighter": 3, "sword": 3, "dodging": 2, "ambusher": 3}),
    ("guard", "guard", "human", colors.Color(150, 160, 190),
     {"fighter": 4, "spear": 4, "shield_use": 3, "armor_use": 3}),
    ("merchant", "merchant", "human", colors.Color(206, 186, 112),
     {"appraisal": 5, "negotiation": 5, "conversation": 4}),
    ("peasant", "peasant", "human", colors.Color(178, 158, 128), {}),
    ("hammerdwarf", "hammerdwarf", "dwarf", colors.Color(190, 170, 150),
     {"fighter": 6, "hammer": 6, "shield_use": 4, "armor_use": 5}),
    ("axedwarf", "axedwarf", "dwarf", colors.Color(190, 160, 120),
     {"fighter": 6, "axe": 6, "shield_use": 4, "armor_use": 5}),
    ("elf_archer", "elven archer", "elf", colors.Color(126, 196, 126),
     {"bow": 7, "dodging": 4, "ambusher": 4}),
    ("goblin_snatcher", "goblin snatcher", "goblin", colors.Color(96, 138, 78),
     {"sneak": 6, "ambusher": 5, "dodging": 3}),
    ("necromancer", "necromancer", "human", colors.Color(160, 120, 200),
     {"knowledge": 8, "willpower": 5, "dodging": 2}),
    ("vampire", "vampire", "human", colors.Color(180, 70, 90),
     {"fighter": 6, "dodging": 5, "sneak": 6, "lying": 8}),
    ("werewolf", "werewolf", "human", colors.Color(140, 128, 116),
     {"fighter": 7, "biter": 6, "dodging": 4}),
):
    _base = CREATURES[_prace]
    _extra_flags = ["INTELLIGENT", "CIVILIZED", "CAN_SPEAK"]
    if _pid in ("bandit", "goblin_snatcher"):
        _extra_flags.append("EVIL")
    if _pid in ("necromancer",):
        _extra_flags += ["EVIL", "NIGHT_CREATURE"]
    if _pid in ("vampire", "werewolf"):
        _extra_flags += ["EVIL", "NIGHT_CREATURE", "NO_FEAR"]
    _c(_pid, _pname, "@", _pcol, _base.body_plan, _base.size,
       3 if _pid in ("vampire", "werewolf", "necromancer") else 2,
       _base.biomes, tuple(_extra_flags), HUMANOID_ATTACKS,
       attributes=dict(_base.attributes), skills=_pskills,
       lifespan=_base.lifespan, civ=None,
       frequency=30, desc="")

# --------------------------------------------------------------------------- #
# Domestic and wild animals
# --------------------------------------------------------------------------- #

_QUAD_BITE = (_na("teeth", BITE),)
_CLAW_BITE = (_na("left_front_leg_digits", CLAW),
              _na("right_front_leg_digits", CLAW), _na("teeth", BITE))

_c("dog", "dog", "d", colors.Color(180, 150, 110), "quadruped", 30000, 1,
   ANY_LAND, ("PET", "TRAINABLE", "PACK"), _QUAD_BITE,
   skills={"biter": 2}, group=(1, 3), speed=130, diet="carnivore",
   lifespan=(10, 16), desc="Loyal, loud and useful in a fight.")
_c("cat", "cat", "c", colors.Color(160, 150, 140), "quadruped", 5000, 0,
   ANY_LAND, ("PET", "TRAINABLE"), (_na("teeth", BITE), _na("left_front_leg_digits", SCRATCH)),
   speed=140, diet="carnivore", lifespan=(12, 18))
_c("horse", "horse", "h", colors.Color(150, 110, 76), "quadruped", 500000, 1,
   OPEN, ("MOUNT", "TRAINABLE", "GRAZER", "PACK"),
   (_na("left_rear_leg_end", KICK), _na("teeth", BITE)),
   group=(1, 6), speed=180, diet="herbivore", lifespan=(25, 30))
_c("donkey", "donkey", "h", colors.Color(140, 130, 120), "quadruped", 200000, 1,
   OPEN, ("MOUNT", "TRAINABLE", "GRAZER"), (_na("left_rear_leg_end", KICK),),
   speed=130, diet="herbivore", lifespan=(25, 35))
_c("mule", "mule", "h", colors.Color(128, 116, 104), "quadruped", 300000, 1,
   OPEN, ("MOUNT", "TRAINABLE", "GRAZER"), (_na("left_rear_leg_end", KICK),),
   speed=130, diet="herbivore", lifespan=(30, 40))
_c("cow", "cow", "c", colors.Color(196, 180, 160), "quadruped", 700000, 1,
   OPEN, ("GRAZER", "TRAINABLE", "BENIGN"), (_na("head", BUTT),),
   plural="cows", group=(2, 8), speed=80, diet="herbivore", lifespan=(15, 22))
_c("bull", "bull", "c", colors.Color(120, 96, 78), "quadruped", 800000, 2,
   OPEN, ("GRAZER",), (_na("head", GORE), _na("head", BUTT)),
   speed=110, diet="herbivore", lifespan=(15, 22))
_c("pig", "pig", "p", colors.Color(214, 168, 168), "quadruped", 100000, 1,
   ANY_LAND, ("GRAZER", "TRAINABLE", "BENIGN"), _QUAD_BITE,
   group=(2, 6), speed=90, lifespan=(10, 15))
_c("sheep", "sheep", "s", colors.Color(226, 220, 206), "quadruped", 80000, 0,
   OPEN, ("GRAZER", "TRAINABLE", "BENIGN"), (_na("head", BUTT),),
   plural="sheep", group=(3, 10), speed=90, diet="herbivore", lifespan=(10, 14))
_c("goat", "goat", "s", colors.Color(190, 178, 150), "quadruped", 70000, 0,
   frozenset({"mountain", "hills", "shrubland"}),
   ("GRAZER", "TRAINABLE"), (_na("head", GORE),),
   group=(2, 8), speed=110, diet="herbivore", lifespan=(12, 16))
_c("chicken", "chicken", "b", colors.Color(214, 190, 140), "bird", 3000, 0,
   ANY_LAND, ("BENIGN", "TRAINABLE"), (_na("beak", PECK),),
   group=(3, 10), speed=90, lifespan=(5, 10))
_c("duck", "duck", "b", colors.Color(150, 160, 120), "bird", 3000, 0,
   frozenset({"marsh", "swamp", "lake", "river"}), ("BENIGN", "SWIMMER", "FLIER"),
   (_na("beak", PECK),), group=(3, 12), speed=100, lifespan=(5, 10))

_c("deer", "deer", "d", colors.Color(170, 132, 90), "quadruped", 100000, 1,
   FOREST | OPEN, ("GRAZER", "BENIGN"), (_na("head", GORE),),
   plural="deer", group=(2, 8), speed=170, diet="herbivore", lifespan=(10, 18),
   desc="Skittish, quick and worth eating.")
_c("elk", "elk", "d", colors.Color(146, 110, 74), "quadruped", 300000, 2,
   COLD | FOREST, ("GRAZER",), (_na("head", GORE), _na("left_front_leg_end", KICK)),
   plural="elk", group=(1, 5), speed=150, diet="herbivore", lifespan=(12, 20))
_c("boar", "boar", "p", colors.Color(120, 100, 84), "quadruped", 120000, 2,
   FOREST, ("SAVAGE",), (_na("teeth", GORE), _na("teeth", BITE)),
   group=(1, 4), speed=130, lifespan=(10, 16),
   desc="Bad tempered, thick skinned and armed with tusks.")
_c("grizzly_bear", "grizzly bear", "B", colors.Color(132, 100, 66), "quadruped",
   500000, 3, FOREST | COLD, ("SAVAGE",), _CLAW_BITE,
   attributes={"strength": 2200, "toughness": 1800},
   skills={"fighter": 4, "biter": 4}, speed=120, lifespan=(20, 30), armor=1,
   desc="Six hundred pounds of muscle and bad intentions.")
_c("black_bear", "black bear", "B", colors.Color(70, 66, 62), "quadruped",
   300000, 2, FOREST, ("SAVAGE",), _CLAW_BITE,
   attributes={"strength": 1700}, skills={"fighter": 3}, speed=120,
   lifespan=(18, 25))
_c("wolf", "wolf", "w", colors.Color(140, 140, 148), "quadruped", 40000, 2,
   FOREST | COLD | OPEN, ("SAVAGE", "PACK"), _QUAD_BITE,
   plural="wolves", attributes={"agility": 1400},
   skills={"biter": 4, "dodging": 3}, group=(3, 7), speed=160,
   diet="carnivore", lifespan=(10, 16),
   desc="They do not hunt alone.")
_c("fox", "fox", "f", colors.Color(198, 122, 60), "quadruped", 8000, 1,
   FOREST | OPEN, ("AMBUSHER",), _QUAD_BITE,
   plural="foxes", speed=150, diet="carnivore", lifespan=(6, 12))
_c("lion", "lion", "L", colors.Color(198, 164, 92), "quadruped", 250000, 3,
   frozenset({"savanna", "shrubland", "desert"}), ("SAVAGE", "PACK"), _CLAW_BITE,
   attributes={"strength": 1800, "agility": 1500}, skills={"fighter": 5},
   group=(2, 5), speed=150, diet="carnivore", lifespan=(12, 18))
_c("tiger", "tiger", "L", colors.Color(214, 140, 56), "quadruped", 300000, 3,
   frozenset({"jungle", "tropical_forest"}), ("SAVAGE", "AMBUSHER"), _CLAW_BITE,
   attributes={"strength": 1900, "agility": 1600}, skills={"fighter": 5, "sneak": 5},
   speed=150, diet="carnivore", lifespan=(12, 20))
_c("leopard", "leopard", "L", colors.Color(196, 172, 96), "quadruped", 100000, 2,
   FOREST, ("SAVAGE", "AMBUSHER"), _CLAW_BITE,
   skills={"fighter": 4, "sneak": 6}, speed=170, diet="carnivore",
   lifespan=(10, 17))
_c("wolverine", "wolverine", "w", colors.Color(110, 86, 62), "quadruped",
   20000, 2, COLD, ("SAVAGE", "NO_FEAR"), _CLAW_BITE,
   skills={"fighter": 4}, speed=130, diet="carnivore", lifespan=(8, 15))
_c("badger", "badger", "b", colors.Color(150, 146, 140), "quadruped", 15000, 1,
   FOREST | OPEN, ("SAVAGE",), _CLAW_BITE, speed=110, lifespan=(6, 12))
_c("rabbit", "rabbit", "r", colors.Color(180, 160, 138), "quadruped", 2000, 0,
   OPEN | FOREST, ("BENIGN", "GRAZER"), (_na("teeth", BITE),),
   group=(1, 5), speed=170, diet="herbivore", lifespan=(4, 9))
_c("rat", "rat", "r", colors.Color(128, 120, 112), "quadruped", 300, 0,
   ANY_LAND, ("VERMIN",), (_na("teeth", BITE),),
   group=(1, 6), speed=140, lifespan=(2, 4))
_c("giant_rat", "giant rat", "r", colors.Color(146, 124, 96), "quadruped",
   8000, 1, ANY_LAND | UNDERGROUND, ("SAVAGE", "PACK", "SUBTERRANEAN"),
   (_na("teeth", BITE),), group=(2, 6), speed=120, lifespan=(4, 8))
_c("elephant", "elephant", "E", colors.Color(150, 148, 148), "quadruped",
   3000000, 4, frozenset({"savanna", "jungle", "tropical_forest"}),
   ("GRAZER", "PACK"), (_na("head", SLAM), _na("left_front_leg_end", CRUSH)),
   attributes={"strength": 3500, "toughness": 2500}, group=(2, 6), speed=100,
   diet="herbivore", lifespan=(60, 80), armor=2,
   desc="Three tonnes that will not be argued with.")
_c("rhinoceros", "rhinoceros", "E", colors.Color(140, 136, 132), "quadruped",
   1500000, 4, frozenset({"savanna", "grassland"}), ("SAVAGE", "GRAZER"),
   (_na("head", GORE), _na("head", SLAM)),
   plural="rhinoceroses", attributes={"strength": 2800, "toughness": 2400},
   speed=140, diet="herbivore", lifespan=(35, 50), armor=3)
_c("hippopotamus", "hippopotamus", "E", colors.Color(146, 116, 116), "quadruped",
   1500000, 4, frozenset({"river", "lake", "marsh", "swamp"}),
   ("SAVAGE", "SWIMMER"), (_na("teeth", BITE), _na("head", SLAM)),
   plural="hippopotamuses", attributes={"strength": 2600, "toughness": 2200},
   speed=110, diet="herbivore", lifespan=(35, 50), armor=2)
_c("camel", "camel", "h", colors.Color(198, 168, 118), "quadruped", 500000, 1,
   frozenset({"desert", "badlands"}), ("MOUNT", "GRAZER", "TRAINABLE"),
   (_na("teeth", BITE), _na("left_rear_leg_end", KICK)),
   group=(1, 5), speed=120, diet="herbivore", lifespan=(30, 45))
_c("gorilla", "gorilla", "G", colors.Color(70, 68, 66), "humanoid", 200000, 3,
   frozenset({"jungle", "tropical_forest"}), ("SAVAGE", "PACK"),
   HUMANOID_ATTACKS, attributes={"strength": 2400}, skills={"wrestling": 5},
   group=(2, 6), speed=110, lifespan=(30, 45))

# -- birds, fish, vermin ---------------------------------------------------- #

_c("raven", "raven", "b", colors.Color(60, 58, 66), "bird", 1500, 0,
   ANY_LAND, ("FLIER",), (_na("beak", PECK),), group=(1, 8), speed=170,
   lifespan=(10, 20))
_c("eagle", "eagle", "B", colors.Color(150, 126, 88), "bird", 6000, 2,
   frozenset({"mountain", "hills"}), ("FLIER", "SAVAGE"),
   (_na("beak", PECK), _na("left_leg_digits", CLAW)),
   skills={"fighter": 3}, speed=200, diet="carnivore", lifespan=(15, 25))
_c("buzzard", "buzzard", "b", colors.Color(120, 106, 88), "bird", 3000, 1,
   frozenset({"desert", "badlands", "savanna"}), ("FLIER",),
   (_na("beak", PECK),), group=(1, 5), speed=170, diet="carnivore",
   lifespan=(10, 20))
_c("bat", "bat", "b", colors.Color(96, 88, 96), "bird", 200, 0,
   ANY_LAND | UNDERGROUND, ("FLIER", "NOCTURNAL", "SUBTERRANEAN", "VERMIN"),
   (_na("teeth", BITE),), group=(2, 12), speed=190, lifespan=(5, 15))
_c("giant_bat", "giant bat", "B", colors.Color(112, 96, 104), "bird", 20000, 2,
   UNDERGROUND | ANY_LAND, ("FLIER", "NOCTURNAL", "SAVAGE", "SUBTERRANEAN"),
   (_na("teeth", BITE),), group=(1, 4), speed=180, diet="carnivore",
   lifespan=(10, 20))
_c("giant_cave_swallow", "giant cave swallow", "B", colors.Color(96, 116, 140),
   "bird", 30000, 2, UNDERGROUND, ("FLIER", "SAVAGE", "SUBTERRANEAN"),
   (_na("beak", PECK),), group=(1, 5), speed=210, diet="carnivore",
   lifespan=(10, 20))
_c("carp", "carp", "f", colors.Color(150, 148, 96), "fish", 20000, 2,
   frozenset({"river", "lake"}), ("AQUATIC", "SWIMMER", "SAVAGE"),
   (_na("teeth", BITE),), plural="carp", group=(1, 4), speed=130,
   diet="carnivore", blood="blood", lifespan=(10, 30),
   desc="Do not turn your back on the water.")
_c("pike", "pike", "f", colors.Color(120, 140, 110), "fish", 8000, 1,
   frozenset({"river", "lake"}), ("AQUATIC", "SWIMMER"), (_na("teeth", BITE),),
   plural="pike", speed=140, diet="carnivore", lifespan=(8, 20))
_c("alligator", "alligator", "A", colors.Color(96, 116, 84), "quadruped",
   200000, 3, frozenset({"swamp", "marsh", "river"}),
   ("SAVAGE", "SWIMMER", "AMBUSHER"), (_na("teeth", BITE), _na("tail", SLAM)),
   attributes={"strength": 2000, "toughness": 1900}, skills={"biter": 5, "sneak": 4},
   speed=110, diet="carnivore", lifespan=(30, 50), armor=3)
_c("snake", "snake", "S", colors.Color(110, 148, 80), "serpent", 3000, 1,
   ANY_LAND, ("AMBUSHER", "POISON_BITE"), (_na("teeth", BITE),),
   speed=110, diet="carnivore", lifespan=(8, 20))
_c("giant_desert_scorpion", "giant desert scorpion", "S",
   colors.Color(160, 130, 70), "insect", 60000, 3,
   frozenset({"desert", "badlands"}), ("SAVAGE", "POISON_BITE"),
   (_na("mandibles", BITE), _na("abdomen", STING)),
   skills={"fighter": 4}, speed=120, diet="carnivore", blood="",
   lifespan=(5, 10), armor=3)
_c("cave_spider", "cave spider", "s", colors.Color(80, 74, 88), "insect", 100, 0,
   UNDERGROUND, ("VERMIN", "SUBTERRANEAN", "WEBBER", "POISON_BITE"),
   (_na("mandibles", BITE),), group=(1, 6), speed=130, diet="carnivore",
   blood="", lifespan=(2, 5))
_c("giant_cave_spider", "giant cave spider", "S", colors.Color(96, 88, 104),
   "insect", 80000, 4, UNDERGROUND, ("SAVAGE", "SUBTERRANEAN", "WEBBER",
                                     "POISON_BITE", "AMBUSHER"),
   (_na("mandibles", BITE),),
   attributes={"agility": 2000, "strength": 1600}, skills={"fighter": 6, "sneak": 6},
   speed=140, diet="carnivore", blood="", lifespan=(15, 40), armor=2,
   desc="It waits in the dark above the tunnel, and it is patient.")

# --------------------------------------------------------------------------- #
# Monsters and megabeasts
# --------------------------------------------------------------------------- #

_c("troll", "troll", "T", colors.Color(120, 140, 110), "giant_humanoid",
   300000, 3, ANY_LAND | UNDERGROUND, ("SAVAGE", "EVIL", "SUBTERRANEAN"),
   HUMANOID_ATTACKS, attributes={"strength": 2400, "toughness": 2200,
                                 "analytical_ability": 400},
   skills={"fighter": 4, "wrestling": 4}, group=(1, 3), speed=90,
   lifespan=(80, 120), armor=2,
   desc="Lumbering, ugly and hard to put down.")
_c("ogre", "ogre", "O", colors.Color(150, 130, 96), "giant_humanoid", 400000, 4,
   ANY_LAND, ("SAVAGE", "EVIL", "SEMIMEGABEAST"), HUMANOID_ATTACKS,
   attributes={"strength": 2800, "toughness": 2300},
   skills={"fighter": 6, "wrestling": 5}, speed=100, lifespan=(100, 150), armor=2)
_c("minotaur", "minotaur", "M", colors.Color(150, 106, 74), "giant_humanoid",
   350000, 4, frozenset({"mountain", "hills"}),
   ("SAVAGE", "EVIL", "SEMIMEGABEAST", "INTELLIGENT"),
   HUMANOID_ATTACKS + (_na("head", GORE),),
   attributes={"strength": 2600, "toughness": 2200, "agility": 1400},
   skills={"fighter": 7, "axe": 6}, speed=120, lifespan=(150, 200), armor=2,
   desc="It remembers the shape of every tunnel it has ever walked.")
_c("cyclops", "cyclops", "C", colors.Color(180, 150, 120), "giant_humanoid",
   1000000, 5, frozenset({"mountain", "hills", "shrubland"}),
   ("SAVAGE", "EVIL", "SEMIMEGABEAST", "INTELLIGENT"), HUMANOID_ATTACKS,
   plural="cyclopes", attributes={"strength": 3400, "toughness": 2800},
   skills={"fighter": 8, "wrestling": 7}, speed=100, lifespan=(400, 600), armor=3)
_c("ettin", "ettin", "E", colors.Color(140, 128, 108), "giant_humanoid",
   900000, 5, ANY_LAND, ("SAVAGE", "EVIL", "SEMIMEGABEAST", "INTELLIGENT"),
   HUMANOID_ATTACKS, attributes={"strength": 3200, "toughness": 2700},
   skills={"fighter": 8}, speed=100, lifespan=(400, 600), armor=3)
_c("hydra", "hydra", "H", colors.Color(96, 160, 130), "dragon", 1200000, 5,
   frozenset({"swamp", "marsh", "lake"}), ("SAVAGE", "EVIL", "MEGABEAST"),
   (_na("teeth", BITE), _na("tail", SLAM)),
   plural="hydras", attributes={"strength": 3000, "toughness": 3200},
   skills={"fighter": 9, "biter": 9}, speed=110, diet="carnivore",
   lifespan=(1000, 2000), armor=4,
   desc="Seven heads, and it has never been counted twice the same.")
_c("dragon", "dragon", "D", colors.Color(196, 62, 48), "dragon", 2000000, 5,
   ANY_LAND | UNDERGROUND, ("SAVAGE", "EVIL", "MEGABEAST", "FLIER",
                            "FIREIMMUNE", "INTELLIGENT", "NO_FEAR"),
   (_na("teeth", BITE), _na("left_front_leg_digits", CLAW), _na("tail", SLAM)),
   attributes={"strength": 4000, "toughness": 3800, "agility": 1800},
   skills={"fighter": 12, "biter": 12, "dodging": 6}, speed=140,
   diet="carnivore", lifespan=(5000, 10000), armor=6,
   desc="Older than every kingdom whose names it has forgotten.")
_c("roc", "roc", "R", colors.Color(146, 122, 88), "bird", 1500000, 5,
   frozenset({"mountain", "hills"}), ("SAVAGE", "MEGABEAST", "FLIER"),
   (_na("beak", PECK), _na("left_leg_digits", CLAW)),
   attributes={"strength": 3200, "toughness": 2600}, skills={"fighter": 9},
   speed=200, diet="carnivore", lifespan=(1000, 3000), armor=2)
_c("bronze_colossus", "bronze colossus", "C", colors.BRONZE, "giant_humanoid",
   5000000, 5, ANY_LAND, ("MEGABEAST", "NO_EAT", "NO_DRINK", "NO_SLEEP",
                          "NO_FEAR", "FIREIMMUNE", "OPPOSED_TO_LIFE"),
   HUMANOID_ATTACKS, plural="bronze colossuses",
   attributes={"strength": 5000, "toughness": 5000},
   skills={"fighter": 10, "wrestling": 10}, speed=80, blood="",
   lifespan=(100000, 100000), armor=10,
   desc="A statue that walks. Bronze does not bleed.")
_c("giant", "giant", "G", colors.Color(190, 170, 150), "giant_humanoid",
   1500000, 5, COLD | frozenset({"mountain", "hills"}),
   ("SAVAGE", "SEMIMEGABEAST", "INTELLIGENT"), HUMANOID_ATTACKS,
   attributes={"strength": 3600, "toughness": 3000}, skills={"fighter": 8},
   speed=110, lifespan=(200, 300), armor=2)
_c("blind_cave_ogre", "blind cave ogre", "O", colors.Color(160, 150, 140),
   "giant_humanoid", 600000, 4, UNDERGROUND,
   ("SAVAGE", "SUBTERRANEAN", "SEMIMEGABEAST"), HUMANOID_ATTACKS,
   attributes={"strength": 3000, "toughness": 2500}, skills={"fighter": 6},
   speed=90, lifespan=(100, 150), armor=2)
_c("gremlin", "gremlin", "g", colors.Color(120, 110, 138), "humanoid", 15000, 1,
   UNDERGROUND, ("INTELLIGENT", "EVIL", "SUBTERRANEAN", "AMBUSHER", "NOCTURNAL"),
   HUMANOID_ATTACKS, skills={"sneak": 7, "ambusher": 6}, speed=140,
   lifespan=(30, 60), desc="It pulls levers it does not understand.")
_c("night_troll", "night troll", "T", colors.Color(80, 70, 90), "giant_humanoid",
   250000, 4, ANY_LAND, ("SAVAGE", "EVIL", "NIGHT_CREATURE", "NOCTURNAL",
                         "NO_FEAR", "INTELLIGENT"),
   HUMANOID_ATTACKS, attributes={"strength": 2600, "toughness": 2400},
   skills={"fighter": 6, "wrestling": 6}, speed=120, lifespan=(500, 900), armor=2)

# -- undead ----------------------------------------------------------------- #

_c("zombie", "zombie", "z", colors.Color(126, 140, 110), "humanoid", 70000, 2,
   ANY_LAND, ("UNDEAD", "EVIL", "NO_EAT", "NO_DRINK", "NO_SLEEP", "NO_FEAR",
              "OPPOSED_TO_LIFE"),
   HUMANOID_ATTACKS, attributes={"strength": 1400, "toughness": 1600,
                                 "agility": 700},
   skills={"wrestling": 2}, group=(2, 6), speed=70, blood="",
   lifespan=(100000, 100000), desc="It does not tire, and it does not stop.")
_c("skeleton", "skeleton", "z", colors.BONE, "humanoid", 40000, 2,
   ANY_LAND, ("UNDEAD", "EVIL", "NO_EAT", "NO_DRINK", "NO_SLEEP", "NO_FEAR",
              "OPPOSED_TO_LIFE"),
   HUMANOID_ATTACKS, attributes={"strength": 1200, "toughness": 1400},
   skills={"fighter": 3, "sword": 3}, group=(2, 6), speed=100, blood="",
   lifespan=(100000, 100000))
_c("ghoul", "ghoul", "z", colors.Color(150, 148, 120), "humanoid", 60000, 3,
   ANY_LAND, ("UNDEAD", "EVIL", "NO_SLEEP", "NO_FEAR", "OPPOSED_TO_LIFE",
              "NOCTURNAL"),
   HUMANOID_ATTACKS, attributes={"strength": 1600, "agility": 1500},
   skills={"fighter": 4, "biter": 5}, group=(1, 4), speed=130, blood="",
   lifespan=(100000, 100000))
_c("mummy", "mummy", "M", colors.Color(180, 160, 120), "humanoid", 65000, 4,
   frozenset({"desert", "badlands"}),
   ("UNDEAD", "EVIL", "NO_EAT", "NO_DRINK", "NO_SLEEP", "NO_FEAR",
    "OPPOSED_TO_LIFE", "INTELLIGENT"),
   HUMANOID_ATTACKS, plural="mummies",
   attributes={"strength": 2000, "toughness": 2200, "willpower": 2500},
   skills={"fighter": 6}, speed=90, blood="", lifespan=(100000, 100000), armor=1)

# -- procedural template ---------------------------------------------------- #

_c("forgotten_beast", "forgotten beast", "F", colors.Color(180, 90, 180),
   "quadruped", 400000, 5, UNDERGROUND,
   ("SAVAGE", "EVIL", "MEGABEAST", "SUBTERRANEAN", "NO_FEAR"),
   (_na("teeth", BITE), _na("left_front_leg_digits", CLAW)),
   attributes={"strength": 2800, "toughness": 2800}, skills={"fighter": 8},
   speed=110, blood="", lifespan=(100000, 100000), armor=3,
   desc="It has waited in the deep places since before the first fortress.")


_FB_PLANS = ("quadruped", "serpent", "insect", "blob", "dragon", "giant_humanoid")
_FB_MATERIALS = (
    ("of iron", colors.IRON, 5), ("of stone", colors.STONE, 4),
    ("of salt", colors.Color(230, 230, 236), 2),
    ("of ash", colors.ASH, 2), ("of fire", colors.EMBER, 5),
    ("of ice", colors.ICE, 4), ("made of amber", colors.Color(214, 148, 52), 3),
)
_FB_SHAPES = (
    "a great %s", "a towering %s", "a twisted %s", "an emaciated %s",
    "a gigantic %s", "a bloated %s", "a spindly %s",
)
_FB_NOUNS = (
    "eyeless serpent", "many-legged horror", "winged beast", "crawling mass",
    "humanoid thing", "shelled monstrosity", "quadruped", "worm",
)
_FB_TRAITS = (
    "It has a gaunt appearance.", "Its eyes glow in the dark.",
    "It has enormous mandibles.", "Beware its poisonous bite!",
    "Beware its deadly dust!", "It undulates rhythmically.",
    "It is crazed with hunger.", "Its hair is stringy and matted.",
    "It has a pair of curling horns.",
)


def random_forgotten_beast(rng: RNG, name: str) -> CreatureDef:
    """Generate a unique deep-earth horror, DF style."""
    plan = rng.choice(_FB_PLANS)
    material, color, armor = rng.choice(_FB_MATERIALS)
    shape = rng.choice(_FB_SHAPES) % rng.choice(_FB_NOUNS)
    traits = rng.sample(_FB_TRAITS, rng.randint(1, 3))
    size = rng.randint(200000, 3000000)
    strength = rng.randint(2000, 4200)
    toughness = rng.randint(2000, 4200)
    attacks: List[NaturalAttack] = [_na("teeth", BITE)]
    if plan in ("quadruped", "dragon"):
        attacks.append(_na("left_front_leg_digits", CLAW))
    if plan == "giant_humanoid":
        attacks = list(HUMANOID_ATTACKS)
    if plan == "blob":
        attacks = [_na("body", SLAM)]
    if plan == "insect":
        attacks = [_na("mandibles", BITE), _na("abdomen", STING)]
    if plan == "serpent":
        attacks = [_na("teeth", BITE), _na("tail", SLAM)]
    return CreatureDef(
        id="forgotten_beast_%d" % rng.randint(1, 10 ** 9),
        name=name, plural=name + "s", adjective=name,
        glyph="F", color=color, body_plan=plan, size=size, tier=5,
        attributes={"strength": strength, "toughness": toughness,
                    "agility": rng.randint(900, 2200)},
        skills={"fighter": rng.randint(6, 11), "biter": rng.randint(5, 10),
                "dodging": rng.randint(2, 6)},
        attacks=tuple(attacks), biomes=UNDERGROUND,
        flags=frozenset({"SAVAGE", "EVIL", "MEGABEAST", "SUBTERRANEAN",
                         "NO_FEAR", "NO_SLEEP", "UNIQUE"}),
        group=(1, 1), speed=rng.randint(90, 140), frequency=0,
        diet="carnivore", blood="blood" if rng.chance(0.6) else "",
        lifespan=(100000, 100000), civ=None,
        description="%s %s. %s" % (shape, material, " ".join(traits)),
        natural_armor=armor,
    )


# --------------------------------------------------------------------------- #
# Queries
# --------------------------------------------------------------------------- #


def get(cid: str) -> CreatureDef:
    """Look up a creature definition, defaulting to a rat."""
    return CREATURES.get(cid) or CREATURES["rat"]


def exists(cid: str) -> bool:
    """True if *cid* names a known creature."""
    return cid in CREATURES


def spawnable(
    biome: str,
    *,
    underground: bool = False,
    max_tier: int = 5,
    flags_any: Sequence[str] = (),
    flags_none: Sequence[str] = (),
) -> List[CreatureDef]:
    """Every creature that can appear in a biome, filtered by tier and flags."""
    out: List[CreatureDef] = []
    for c in CREATURES.values():
        if c.frequency <= 0 or c.tier > max_tier:
            continue
        if "UNIQUE" in c.flags:
            continue
        if underground:
            if "SUBTERRANEAN" not in c.flags:
                continue
        else:
            if biome not in c.biomes:
                continue
        if flags_any and not any(f in c.flags for f in flags_any):
            continue
        if flags_none and any(f in c.flags for f in flags_none):
            continue
        out.append(c)
    return out


def megabeasts() -> List[CreatureDef]:
    """Every megabeast and semi-megabeast."""
    return [
        c for c in CREATURES.values()
        if "MEGABEAST" in c.flags or "SEMIMEGABEAST" in c.flags
    ]


def night_creatures() -> List[CreatureDef]:
    """Every creature of the night."""
    return [c for c in CREATURES.values() if "NIGHT_CREATURE" in c.flags]


def civilized_races() -> List[CreatureDef]:
    """Every race that founds civilizations."""
    return [c for c in CREATURES.values() if c.civ]


def validate() -> List[str]:
    """Check the bestiary against the body-plan and item tables."""
    from . import bodies

    problems: List[str] = []
    for cid, c in CREATURES.items():
        if c.body_plan not in bodies.BODY_PLANS:
            problems.append("%s: unknown body plan %s" % (cid, c.body_plan))
            continue
        part_ids = {p.id for p in bodies.BODY_PLANS[c.body_plan]}
        for na in c.attacks:
            if na.part and na.part not in part_ids:
                problems.append(
                    "%s: attack references missing part %s" % (cid, na.part)
                )
        if c.size <= 0:
            problems.append("%s: non-positive size" % cid)
        if c.speed <= 0:
            problems.append("%s: non-positive speed" % cid)
    return problems
