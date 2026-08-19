"""Creatures: the player and everything that moves."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..data import creatures as creature_data
from ..data import items as item_data
from ..data import names as name_data
from ..data.creatures import CreatureDef
from ..data.descriptors import age_desc, list_join
from ..engine import colors, geometry
from ..engine.colors import Color
from ..engine.rng import RNG
from ..engine.screen import Frag
from .attributes import Attributes, roll_attributes
from .body import Body
from .inventory import Inventory
from .needs import Needs
from .personality import Personality, roll_personality
from .skills import SkillSet


#: Creatures whose flesh is not flesh: every tissue is replaced wholesale.
TISSUE_OVERRIDES: Dict[str, Dict[str, str]] = {
    "bronze_colossus": {
        "skin": "bronze", "fat": "bronze", "muscle": "bronze", "bone": "bronze",
        "cartilage": "bronze", "nerve": "bronze", "brain": "bronze",
        "heart": "bronze", "lung": "bronze", "gut": "bronze", "liver": "bronze",
        "eye": "bronze", "tooth": "bronze", "nail": "bronze", "hair": "bronze",
    },
    "skeleton": {
        "nerve": "bone", "brain": "bone", "heart": "bone", "lung": "bone",
        "gut": "bone", "liver": "bone", "eye": "bone", "cartilage": "bone",
    },
}

#: Tissue layers a creature simply does not have. A skeleton is bones with
#: nothing on them, and saying so with the material map instead -- skin made
#: of bone, fat made of bone, muscle made of bone -- gave it four layers of
#: the toughest tissue in the game to chew through. It was tougher than a
#: living man: a dwarf with a steel warhammer lost to one forty times in
#: forty, over a hundred and thirty exchanges.
TISSUE_MISSING: Dict[str, Tuple[str, ...]] = {
    "skeleton": ("skin", "fat", "muscle", "hair", "nail"),
}


class Creature:
    """One living (or undead) thing on the map."""

    _next_id = 1

    def __init__(
        self,
        def_id: str,
        *,
        rng: RNG,
        name: str = "",
        female: Optional[bool] = None,
        age: Optional[int] = None,
        player: bool = False,
        faction: str = "wild",
        level: int = 0,
    ) -> None:
        self.id = Creature._next_id
        Creature._next_id += 1
        self.def_id = def_id
        defn = creature_data.get(def_id)
        self._defn: CreatureDef = defn

        self.female = rng.chance(0.5) if female is None else bool(female)
        self.name = name or name_data.name_for_race(
            defn.civ or def_id, rng, self.female
        )
        lo, hi = defn.lifespan
        self.age = age if age is not None else rng.randint(
            max(14, int(lo * 0.25)), max(16, int(hi * 0.7))
        )

        self.x = 0
        self.y = 0
        self.z = 0
        self.wx = 0
        self.wy = 0

        self.body = Body(defn.body_plan, defn.size,
                         TISSUE_OVERRIDES.get(def_id),
                         TISSUE_MISSING.get(def_id, ()))
        if not defn.blood:
            self.body.bloodless = True
        self.attributes = roll_attributes(rng, defn.attributes)
        self.skills = SkillSet(defn.skills)
        self.personality = roll_personality(rng, defn.civ or "human")
        self.inventory = Inventory(self)
        self.needs = Needs()
        self.needs.owner = self

        if level > 0:
            self._apply_level(rng, level)

        self.faction = faction
        self.hostile_to: set = set()
        self.is_player = player
        self.alive = True
        self.profession = ""
        self.title = ""
        self.hf_id: Optional[int] = None
        self.site_id: Optional[int] = None
        self.civ_id: Optional[int] = None
        self.ai: Any = None
        self.speech: Dict[str, Any] = {}
        self.kills: List[str] = []
        self.gold_reward = 0
        #: Set for uniquely generated creatures (forgotten beasts, titans).
        self.unique_def: Optional[CreatureDef] = None
        #: Secrets this creature has read off a slab. Necromancy is not a
        #: skill, it is a fact about you afterwards.
        self.secrets: List[str] = []
        #: Ids of the artistic forms this creature can perform. Learned
        #: growing up, or off somebody who performed one well.
        self.forms: List[int] = []
        #: Venom currently working in this creature.
        self.venom: List[Any] = []
        #: How badly this creature has been shaken by what it has seen.
        #: Wears off; see `morale`.
        self.shaken = 0.0
        #: When this creature's clothes are next looked at. Staggered by
        #: whoever sets it, so a fortress does not check everyone at once.
        self.next_wear_check = 0
        #: Time saved up toward the next swing, for the fortress, which
        #: steps everybody once regardless of what they are holding.
        self.swing_bank = 0.0
        #: How the weather is going, -1.0 freezing to death through 0.0
        #: comfortable to +1.0 collapsing in the heat. A number that moves
        #: rather than a threshold that trips, so there is time to turn back.
        self.exposure = 0.0
        #: The mount this creature is riding, held off the map while ridden.
        self.mount: Optional["Creature"] = None
        #: Whether this animal has been won over, and how often somebody has
        #: tried. A refusal is one attempt that did not work, not a verdict.
        self.tame = False
        self.tame_tries = 0
        #: Set while this creature is deliberately trying not to be seen,
        #: and what it last did loudly enough for anybody to hear.
        self.sneaking = False
        self.noise = "move"
        #: What the night has done to this creature: "werebeast", "vampire"
        #: or nothing. ``changed`` is set while it is wearing the other shape.
        self.curse = ""
        self.changed = False
        self.shape_was = ""
        self.faction_was = ""
        #: Set on the risen, and on whoever raised them.
        self.raised_by: Optional[int] = None
        self.raised_at = 0
        #: A thief came to steal, not to fight. It is not part of a siege, it
        #: raises no alarm, and it leaves the moment its hands are full.
        self.thief = False
        self.thief_since = 0
        self.loot: Optional[int] = None
        self.loot_name = ""

    # -- definition -------------------------------------------------------- #

    @property
    def defn(self) -> CreatureDef:
        """The species definition, or the unique one for named beasts."""
        return self.unique_def or self._defn

    @property
    def race(self) -> str:
        """The civilised race id, or the creature id for animals."""
        return self.defn.civ or self.def_id

    def _apply_level(self, rng: RNG, level: int) -> None:
        """Toughen up a creature for its role in the world."""
        for _ in range(level):
            for attr in ("strength", "agility", "toughness", "endurance"):
                self.attributes.modify(attr, rng.randint(20, 90))
        for sid, _lv in list(self.skills.known()):
            self.skills.set_level(sid, self.skills.level(sid) + level // 2)
        if not self.skills.known():
            self.skills.set_level("fighter", max(1, level))

    # -- naming and display ------------------------------------------------ #

    def short_name(self) -> str:
        """The species name, used when the creature is not known by name."""
        return self.defn.name

    def display_name(self, *, with_title: bool = True) -> str:
        """How this creature is referred to in messages."""
        if self.is_player:
            return self.name
        if self.defn.intelligent and self.name:
            if with_title and self.title:
                return "%s %s" % (self.name, self.title)
            return self.name
        return self.defn.name

    def full_title(self) -> str:
        """Name, profession and race for the character sheet."""
        bits = [self.name]
        if self.title:
            bits.append(self.title)
        if self.profession:
            bits.append("the %s %s" % (self.defn.adjective, self.profession))
        else:
            bits.append("the %s" % self.defn.name)
        return " ".join(bits)

    def glyph_and_color(self) -> Tuple[str, Color]:
        """The map glyph and colour, dimmed when dead or unconscious."""
        defn = self.defn
        glyph = defn.glyph
        color = defn.color
        if self.is_player:
            return ("@", colors.WHITE)
        if self.body.dead:
            return ("%", colors.darken(color, 0.5))
        if self.body.unconscious > 0:
            return (glyph, colors.darken(color, 0.6))
        if self.body.health_fraction() < 0.4:
            return (glyph, colors.blend(color, colors.BLOOD, 0.4))
        return (glyph, color)

    def describe(self) -> List[Frag]:
        """Lines for the look/examine panel."""
        out: List[Frag] = []
        out.append(Frag(self.full_title(), colors.UI["title"]))
        if self.defn.description:
            out.append(Frag(self.defn.description, colors.UI["dim"]))
        out.append(Frag("A %s %s." % (
            age_desc(self.age, self.race), self.defn.name), colors.UI["fg"]))
        health = self.body.health_fraction()
        if self.body.dead:
            out.append(Frag("It is dead. (%s)" % self.body.death_cause,
                            colors.UI["danger"]))
        else:
            word = ("in perfect health" if health > 0.9 else
                    "lightly wounded" if health > 0.7 else
                    "wounded" if health > 0.45 else
                    "badly wounded" if health > 0.2 else "near death")
            out.append(Frag("It is %s." % word,
                            colors.UI["good"] if health > 0.6
                            else colors.UI["warn"] if health > 0.3
                            else colors.UI["danger"]))
            summary = self.body.wound_summary()
            if summary != "unhurt":
                out.append(Frag("Wounds: %s." % summary, colors.UI["warn"]))
        weapon = self.inventory.weapon()
        if weapon is not None:
            out.append(Frag("It wields %s." % weapon.name(article=True),
                            colors.UI["fg"]))
        worn = [
            i.name() for s, i in self.inventory.equipped.items()
            if s not in ("weapon", "offhand", "ammo")
        ]
        if worn:
            out.append(Frag("It wears %s." % list_join(worn), colors.UI["dim"]))
        best = self.skills.known()[:3]
        if best:
            from .skills import SKILLS, level_name

            out.append(Frag("Skills: %s." % list_join(
                ["%s %s" % (level_name(lv), SKILLS[sid].name) for sid, lv in best]
            ), colors.UI["dim"]))
        if self.curse:
            out.append(Frag(
                "It is wearing another shape." if self.changed
                else "Something is wrong with it.", colors.MAGIC))
        if self.raised_by is not None:
            out.append(Frag("It was not walking a week ago.", colors.MAGIC))
        return out

    # -- capabilities ------------------------------------------------------ #

    def carry_capacity(self) -> float:
        """How much this creature can carry before slowing down, in kilograms."""
        base = self.defn.size / 1000.0
        cap = base * 0.5 * self.attributes.factor("strength")
        if self.inventory.by_def("backpack"):
            cap *= 1.6
        return max(3.0, cap)

    def encumbrance(self) -> float:
        """How overloaded the creature is, 0 = free, 1 = at capacity.

        Worn armour weighs less to somebody who knows how to wear it. It is the
        same steel either way -- the difference is where it sits, how it is
        slung and how much of it the shoulders are taking, and that is what
        `armor_use` is. The relief applies here and nowhere else, so it reaches
        dodging and walking pace together and by the one route.
        """
        cap = self.carry_capacity()
        if self.mount is not None:
            from . import mounts

            cap *= mounts.CARRY_SHARE
        if cap <= 0:
            return 0.0
        from . import armour

        load = self.inventory.total_weight()
        relief = armour.weight_relief(self.skills.level("armor_use"))
        if relief > 0.0:
            load -= self.inventory.worn_armor_weight() * relief
        return max(0.0, load / cap)

    def effective_speed(self) -> int:
        """Movement speed after wounds, load and exhaustion.

        A mounted rider moves at the animal's pace, not their own: the whole
        point of a horse is that your legs stop being the limit.
        """
        if self.mount is not None:
            from . import mounts

            speed = float(self.mount.defn.speed) * mounts.SPEED_SHARE
        else:
            speed = float(self.defn.speed)
        if not self.body.can_stand():
            speed *= 0.35
        stance = [p for p in self.body.parts.values() if p.defn.has("STANCE")]
        if stance:
            broken = sum(1 for p in stance if not p.functional())
            if broken:
                speed *= max(0.3, 1.0 - 0.35 * broken / len(stance))
        enc = self.encumbrance()
        if enc > 1.0:
            speed *= max(0.3, 1.0 - (enc - 1.0) * 0.5)
        speed *= max(0.4, 1.0 - self.body.pain_level() * 0.4)
        speed *= 0.7 + 0.3 * self.attributes.factor("agility")
        if self.needs.fatigue > 1200:
            speed *= 0.8
        if self.venom:
            from . import venom as venom_mod

            speed *= venom_mod.slow_factor(self)
        if self.exposure:
            from ..world import heat

            speed *= heat.speed_factor(self)
        return max(10, int(speed))

    def sight_radius(self, light: float = 1.0) -> int:
        """How far this creature can see given ambient light 0..1."""
        if not self.body.can_see():
            return 1
        base = 12
        if self.defn.has("SUBTERRANEAN") or self.defn.has("NOCTURNAL"):
            base = 10
            light = max(light, 0.7)
        observer = self.skills.level("observer")
        base += observer // 3
        base = int(base * (0.35 + 0.65 * max(0.0, min(1.0, light))))
        if self.inventory.equipped.get("weapon") is not None:
            pass
        for it in self.inventory.items:
            if it.is_light and it.charges > 0:
                base = max(base, 8)
                break
        return max(1, base)

    def value_thought(self, topic: str, base: int, text: str) -> int:
        """Feel something about an event, but only if you hold the value.

        Twenty cultural values have been rolled for every creature since
        personalities existed and nothing but the character sheet ever read
        one. This is how they get read: a dwarf who prizes craftsmanship is
        lifted by a masterwork and a dwarf who does not walks past it.
        Returns the stress delta applied, which is zero for the indifferent.
        """
        from . import personality as personality_mod

        delta = personality_mod.feels_about(self.personality, topic, base)
        if delta:
            self.needs.add_thought(text, delta)
        return delta

    def can_act(self) -> bool:
        """True if the creature may take a turn."""
        return not self.body.dead and self.body.unconscious <= 0 \
            and self.body.stunned <= 0

    def is_hostile_to(self, other: "Creature") -> bool:
        """True if this creature would attack *other* on sight."""
        if other is self or other.body.dead:
            return False
        if other.id in self.hostile_to or self.id in other.hostile_to:
            return True
        if self.faction == other.faction:
            return False
        if self.defn.has("OPPOSED_TO_LIFE"):
            return not other.defn.has("OPPOSED_TO_LIFE")
        if self.faction == "player":
            return other.faction in ("hostile", "wild_hostile")
        if other.faction == "player":
            if self.faction == "hostile":
                return True
            if self.faction in ("wild", "wild_hostile"):
                # `wild_hostile` fell through to False here, which made the
                # one faction with "hostile" in its name the one that never
                # attacked anybody. Nothing spawns with it today, so this was
                # a trap rather than a bug; it is neither now.
                return (self.faction == "wild_hostile"
                        or self.defn.has("SAVAGE") or self.defn.has("EVIL"))
            return False
        if self.faction == "hostile" and other.faction in ("town", "player"):
            return True
        return False

    def distance_to(self, other: "Creature") -> int:
        """Chebyshev distance to another creature on the same level."""
        return geometry.chebyshev(self.x, self.y, other.x, other.y)

    # -- progression ------------------------------------------------------- #

    def add_exp(self, skill: str, amount: int) -> Optional[str]:
        """Train a skill; returns a level-up message when one happens."""
        if amount <= 0 or self.body.dead:
            return None
        scaled = int(amount * (0.6 + 0.4 * self.attributes.factor("focus")))
        new_level = self.skills.add_exp(skill, max(1, scaled))
        if new_level is None:
            return None
        from .skills import SKILLS, level_name

        sd = SKILLS.get(skill)
        if sd is None:
            return None
        return "You are now %s %s." % (level_name(new_level), sd.name)

    def on_death(self, game, cause: str) -> None:
        """Handle everything that follows dying."""
        if not self.alive:
            return
        self.alive = False
        self.body.dead = True
        if not self.body.death_cause:
            self.body.death_cause = cause
        if self.hf_id is not None and game is not None:
            world = getattr(game, "world", None)
            if world is not None:
                fig = world.figures.get(self.hf_id)
                if fig is not None:
                    fig.died = game.time.year
                    fig.death_cause = self.body.death_cause

    def take_turn(self, game) -> int:
        """Run this creature's AI for one action; returns the energy spent."""
        from . import ai

        return ai.take_turn(self, game)

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the creature."""
        d: Dict[str, Any] = {
            "id": self.id,
            "def": self.def_id,
            "name": self.name,
            "female": self.female,
            "age": self.age,
            "x": self.x, "y": self.y, "z": self.z,
            "wx": self.wx, "wy": self.wy,
            "body": self.body.to_dict(),
            "attributes": self.attributes.to_dict(),
            "skills": self.skills.to_dict(),
            "personality": self.personality.to_dict(),
            "inventory": self.inventory.to_dict(),
            "needs": self.needs.to_dict(),
            "faction": self.faction,
            "hostile_to": sorted(self.hostile_to),
            "player": self.is_player,
            "alive": self.alive,
            "profession": self.profession,
            "title": self.title,
            "hf_id": self.hf_id,
            "site_id": self.site_id,
            "civ_id": self.civ_id,
            "ai": self.ai.to_dict() if self.ai is not None else None,
            "kills": self.kills,
            "gold_reward": self.gold_reward,
            "speech": self.speech,
        }
        if self.thief:
            d["thief"] = {"since": self.thief_since, "loot": self.loot,
                          "name": self.loot_name}
        if self.sneaking:
            d["sneaking"] = True
        if self.secrets:
            d["secrets"] = list(self.secrets)
        if self.forms:
            d["forms"] = list(self.forms)
        if self.venom:
            from . import venom as venom_mod

            d["venom"] = venom_mod.to_list(self)
        if self.exposure:
            d["exposure"] = round(self.exposure, 4)
        if self.swing_bank:
            d["swing_bank"] = round(self.swing_bank, 2)
        if self.next_wear_check:
            d["wear_check"] = self.next_wear_check
        if self.shaken:
            d["shaken"] = round(self.shaken, 3)
        if self.tame or self.tame_tries:
            d["tame"] = [self.tame, self.tame_tries]
        if self.mount is not None:
            d["mount"] = self.mount.to_dict()
        if self.curse or self.changed or self.raised_by is not None:
            d["night"] = {"curse": self.curse, "changed": self.changed,
                          "was": self.shape_was, "faction_was": self.faction_was,
                          "by": self.raised_by, "at": self.raised_at}
        if self.unique_def is not None:
            u = self.unique_def
            d["unique"] = {
                "id": u.id, "name": u.name, "plural": u.plural,
                "adjective": u.adjective, "glyph": u.glyph,
                "color": list(u.color), "body_plan": u.body_plan, "size": u.size,
                "tier": u.tier, "attributes": dict(u.attributes),
                "skills": dict(u.skills), "biomes": sorted(u.biomes),
                "flags": sorted(u.flags), "speed": u.speed, "blood": u.blood,
                "description": u.description, "natural_armor": u.natural_armor,
                "attacks": [na.part for na in u.attacks],
            }
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Creature":
        """Rebuild a creature exactly, preserving ids."""
        rng = RNG(1)
        c = cls(str(d.get("def", "rat")), rng=rng, name=str(d.get("name", "")),
                female=bool(d.get("female", False)), age=int(d.get("age", 20)),
                player=bool(d.get("player", False)),
                faction=str(d.get("faction", "wild")))
        c.id = int(d.get("id", c.id))
        Creature._next_id = max(Creature._next_id, c.id + 1)
        c.x, c.y, c.z = int(d.get("x", 0)), int(d.get("y", 0)), int(d.get("z", 0))
        c.wx, c.wy = int(d.get("wx", 0)), int(d.get("wy", 0))
        c.body = Body.from_dict(d.get("body") or {})
        c.attributes = Attributes.from_dict(d.get("attributes") or {})
        c.skills = SkillSet.from_dict(d.get("skills") or {})
        c.personality = Personality.from_dict(d.get("personality") or {})
        c.inventory = Inventory.from_dict(d.get("inventory") or {}, c)
        c.needs = Needs.from_dict(d.get("needs") or {})
        # Deserialising replaces the Needs the constructor made, and with it
        # the back-reference personality is read through. Without this line a
        # loaded game quietly ignores every personality in it.
        c.needs.owner = c
        c.hostile_to = set(int(i) for i in d.get("hostile_to", []))
        c.alive = bool(d.get("alive", True))
        c.profession = str(d.get("profession", ""))
        c.title = str(d.get("title", ""))
        c.hf_id = d.get("hf_id")
        c.site_id = d.get("site_id")
        c.civ_id = d.get("civ_id")
        c.kills = list(d.get("kills", []))
        c.gold_reward = int(d.get("gold_reward", 0))
        c.speech = dict(d.get("speech") or {})

        c.sneaking = bool(d.get("sneaking", False))
        c.secrets = [str(x) for x in d.get("secrets", [])]
        c.forms = [int(x) for x in d.get("forms", [])]
        if d.get("venom"):
            from . import venom as venom_mod

            venom_mod.from_list(c, d["venom"])
        c.exposure = float(d.get("exposure", 0.0))
        c.swing_bank = float(d.get("swing_bank", 0.0))
        c.next_wear_check = int(d.get("wear_check", 0))
        c.shaken = float(d.get("shaken", 0.0))
        tame = d.get("tame")
        if tame:
            c.tame, c.tame_tries = bool(tame[0]), int(tame[1])
        if d.get("mount"):
            c.mount = Creature.from_dict(d["mount"])

        night = d.get("night")
        if night:
            c.curse = str(night.get("curse", ""))
            c.changed = bool(night.get("changed", False))
            c.shape_was = str(night.get("was", ""))
            c.faction_was = str(night.get("faction_was", ""))
            c.raised_by = night.get("by")
            c.raised_at = int(night.get("at", 0))
            if c.changed and c.shape_was:
                # It went into the save mid-change; keep it that way.
                from ..data import creatures as _cd

                c._defn = _cd.get(c.def_id)

        thief = d.get("thief")
        if thief:
            c.thief = True
            c.thief_since = int(thief.get("since", 0))
            c.loot = thief.get("loot")
            c.loot_name = str(thief.get("name", ""))

        unique = d.get("unique")
        if unique:
            c.unique_def = _rebuild_unique(unique)

        ai_data = d.get("ai")
        if ai_data:
            from .ai import AIState

            c.ai = AIState.from_dict(ai_data)
        return c

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Creature(%s #%d at %d,%d,%d)" % (
            self.display_name(), self.id, self.x, self.y, self.z
        )


def _rebuild_unique(d: Mapping[str, Any]) -> CreatureDef:
    """Rebuild a uniquely generated creature definition from a save."""
    from ..data.creatures import NaturalAttack
    from ..data.items import BITE

    base = creature_data.get("forgotten_beast")
    attacks = tuple(
        NaturalAttack(part, BITE) for part in d.get("attacks", []) if part
    ) or base.attacks
    return CreatureDef(
        id=str(d.get("id", "unique")),
        name=str(d.get("name", "beast")),
        plural=str(d.get("plural", "beasts")),
        adjective=str(d.get("adjective", "beast")),
        glyph=str(d.get("glyph", "F")),
        color=Color(*d.get("color", [180, 90, 180])),
        body_plan=str(d.get("body_plan", "quadruped")),
        size=int(d.get("size", 400000)),
        tier=int(d.get("tier", 5)),
        attributes=dict(d.get("attributes") or {}),
        skills=dict(d.get("skills") or {}),
        attacks=attacks,
        biomes=frozenset(d.get("biomes") or []),
        flags=frozenset(d.get("flags") or []),
        speed=int(d.get("speed", 110)),
        frequency=0,
        blood=str(d.get("blood", "")),
        lifespan=(100000, 100000),
        description=str(d.get("description", "")),
        natural_armor=int(d.get("natural_armor", 3)),
    )


#: Every weapon skill the item table actually trains, read from the table so
#: a weapon added with a new skill is one its students can be handed. Ammunition
#: carries a `WeaponDef` too -- an arrow trains `bow` -- hence the category.
WEAPON_SKILLS = frozenset(
    i.weapon.skill for i in item_data.ITEMS.values()
    if i.weapon is not None and i.category == "weapon"
)

#: The rank at which a weapon skill is what somebody fights with rather than
#: something they once tried.
TRAINED = 3

#: What a people arms itself with when the table does not say this person was
#: trained in anything in particular. Kept from before `trained_weapons`,
#: because a goblin raider with `fighter` 1 is still a raider.
RACE_WEAPONS: Dict[str, Tuple[str, ...]] = {
    "goblin": ("short_sword", "spear", "whip", "dagger", "mace"),
    "kobold": ("dagger", "short_sword", "sling"),
    "elf": ("bow", "spear", "short_sword"),
    "dwarf": ("axe", "warhammer", "short_sword", "mace"),
}
DEFAULT_WEAPONS: Tuple[str, ...] = ("sword", "spear", "axe", "mace", "dagger")

#: What somebody who was never a fighter has on them. A knife is a tool as
#: much as a weapon, which is why a merchant has one and not a halberd.
UNTRAINED_WEAPONS: Tuple[str, ...] = ("dagger",)

#: Everybody wears something. The player set out in a tunic, trousers and
#: shoes, and then met four hundred people wearing nothing at all.
CLOTHING: Tuple[str, ...] = ("tunic", "trousers", "shoes")

#: A layer over that, some of the time.
OUTERWEAR: Tuple[str, ...] = ("cloak", "hood", "robe")

#: Armour for somebody who was not trained to wear it.
LIGHT_ARMOUR: Tuple[str, ...] = ("leather_armor", "cap", "high_boots")

#: And for somebody who was. `armor_use` is in the creature table already: a
#: guard has 3 and a hammerdwarf 5, and both used to get the same coat off the
#: same five-item list.
HEAVY_ARMOUR: Tuple[str, ...] = (
    "mail_shirt", "breastplate", "helm", "great_helm", "greaves",
    "gauntlets", "chain_leggings",
)

#: What a kind of person carries besides their gear, as `random_loot`
#: categories. Six of that function's seven categories -- weapon, armor,
#: clothing, food, drink and tool, about sixty item definitions -- had never
#: been drawn from by anything: its one caller asked only for treasure.
MERCHANT_GOODS: Tuple[str, ...] = ("treasure", "treasure", "food", "drink", "tool")
SOLDIER_KIT: Tuple[str, ...] = ("food", "drink", "tool")
CIVILIAN_KIT: Tuple[str, ...] = ("food", "tool")
ROBBER_KIT: Tuple[str, ...] = ("treasure", "drink", "tool")


def usable_weapons(defn: CreatureDef, ids: Sequence[str]) -> List[str]:
    """Those of *ids* this creature is big enough to hold.

    A gremlin is fifteen thousand and a battle axe wants twenty-seven and a
    half: `Inventory.equip` refuses it, so a gremlin handed one off a race
    list carried it around and fought with its hands.
    """
    out: List[str] = []
    for wid in ids:
        w = item_data.ITEMS.get(wid)
        if w is None or w.category != "weapon" or w.weapon is None:
            continue
        if w.weapon.min_size and defn.size < w.weapon.min_size:
            continue
        if w.weapon.two_handed_size and defn.size < w.weapon.two_handed_size:
            # Wieldable, but only with both hands, and a shield is better.
            if defn.skills.get("shield_use", 0) >= TRAINED:
                continue
        out.append(wid)
    return out


def trained_weapons(defn: CreatureDef) -> List[str]:
    """What this kind of person fights with, from what they are trained in.

    The creature table says it already: an `elf_archer` has `bow` 7 and an
    `axedwarf` has `axe` 6. Both used to draw a weapon from a list keyed on
    their *race*, which handed the archer a spear two times in three and the
    axedwarf a warhammer -- and the archer's bow, when it came, was never
    drawn and never loaded.

    Returns the ids of every weapon in their best trained skill that they are
    big enough to use, so a goblin trained in swords gets a short sword and a
    giant gets a two-hander from the same line.
    """
    best = 0
    for skill, rank in defn.skills.items():
        if skill in WEAPON_SKILLS and rank >= TRAINED:
            best = max(best, rank)
    if not best:
        return []
    ids: List[str] = []
    for skill, rank in sorted(defn.skills.items()):
        if rank == best and skill in WEAPON_SKILLS:
            ids.extend(w.id for w in item_data.weapons_for_skill(skill))
    return usable_weapons(defn, ids)


def _fights(defn: CreatureDef, faction: str) -> bool:
    """Whether this is somebody who would be carrying a weapon at all.

    A town's baker is not, and used to be handed a battle axe off the same
    list as its guard.
    """
    return (faction in ("hostile", "wild") or defn.has("EVIL")
            or defn.skills.get("fighter", 0) > 0)


def _kit_for(defn: CreatureDef, faction: str) -> Tuple[str, ...]:
    """The categories of oddments this kind of person has about them."""
    if defn.skills.get("appraisal", 0) or defn.skills.get("negotiation", 0):
        return MERCHANT_GOODS
    if faction == "hostile" or defn.has("EVIL"):
        return ROBBER_KIT
    if any(s in WEAPON_SKILLS and r >= TRAINED for s, r in defn.skills.items()):
        return SOLDIER_KIT
    return CIVILIAN_KIT


def _dress(c: Creature, rng: RNG, tier: int) -> None:
    """Put clothes on somebody."""
    from .item import make_item

    for piece in CLOTHING:
        c.inventory.add(make_item(rng, piece, tier=max(0, tier - 1)))
    if rng.chance(0.35):
        c.inventory.add(make_item(rng, rng.choice(OUTERWEAR), tier=tier))


def _arm(c: Creature, rng: RNG, tier: int, faction: str) -> None:
    """Give somebody a weapon, armour and a shield, by what they were taught."""
    from .item import Item, make_item

    defn = c.defn
    choices = trained_weapons(defn)
    if not choices and _fights(defn, faction):
        choices = usable_weapons(
            defn, RACE_WEAPONS.get(c.race, DEFAULT_WEAPONS))
    if choices:
        c.inventory.add(make_item(rng, rng.choice(choices), tier=tier))
    elif rng.chance(0.6):
        knives = usable_weapons(defn, UNTRAINED_WEAPONS)
        if knives:
            c.inventory.add(make_item(rng, rng.choice(knives), tier=tier))

    heavy = defn.skills.get("armor_use", 0) >= TRAINED
    table = HEAVY_ARMOUR if heavy else LIGHT_ARMOUR
    for _ in range(rng.randint(2, 3) if heavy else 1):
        if heavy or rng.chance(0.55):
            c.inventory.add(make_item(rng, rng.choice(table), tier=tier))
    if defn.skills.get("shield_use", 0) >= TRAINED or rng.chance(0.3):
        c.inventory.add(make_item(rng, rng.choice(("shield", "buckler")), tier=tier))

    bow = c.inventory.ranged_weapon()
    if bow is not None:
        ammo_id = item_data.ammo_for(bow.defn)
        if ammo_id:
            c.inventory.add(make_item(rng, ammo_id, tier=tier,
                                      count=rng.randint(10, 25)))
    if rng.chance(0.5):
        c.inventory.add(Item("coin", "silver", count=rng.randint(3, 60)))


def make_creature(
    rng: RNG,
    def_id: str,
    *,
    faction: str = "wild",
    level: int = 0,
    equip: bool = True,
    tier: Optional[int] = None,
) -> Creature:
    """Create a creature and give it plausible equipment."""
    from .item import random_loot

    c = Creature(def_id, rng=rng, faction=faction, level=level)
    defn = c.defn
    # A werebeast fights with what it is. Arming one hands it a sword and it
    # never bites again, which quietly removes the only thing that makes it a
    # werebeast rather than a strong man. It still wears clothes: it is a
    # person most of the month, and so is the vampire in the tavern.
    armed = not defn.has("NIGHT_CREATURE")
    # `CIVILIZED` is the line for clothing, and it is the line already used to
    # decide who can have a name (`residents.could_be`). Nothing in the item
    # table is cut for a giant, and a cyclops in shoes is a worse world than a
    # cyclops without.
    dressed = defn.has("CIVILIZED")
    if equip and defn.intelligent and defn.body_plan in (
        "humanoid", "giant_humanoid"
    ):
        t = tier if tier is not None else max(0, min(5, defn.tier + level // 2))
        if dressed:
            _dress(c, rng, t)
        if armed:
            _arm(c, rng, t, faction)
        # A troll with a backpack is a worse world too. Oddments belong to
        # people who keep house; a beast that walks upright keeps what it took.
        kit = _kit_for(defn, faction) if dressed else ("treasure",)
        c.inventory.add_all(random_loot(rng, t, kit))
        c.inventory.auto_equip()
    elif equip and defn.tier >= 3 and rng.chance(0.3):
        c.inventory.add_all(random_loot(rng, defn.tier, ("treasure",)))
    c.gold_reward = defn.tier * rng.randint(10, 60)
    return c
