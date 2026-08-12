"""Melee, ranged and wrestling combat.

The model follows Dwarf Fortress in spirit: a strike carries momentum derived
from the attacker's strength, the weapon's mass and the attacker's skill; armour
subtracts from that momentum according to its material and thickness; whatever
is left is driven into the defender's tissues by :mod:`ascii_warriors.game.body`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..data import materials as mat_data
from ..data.items import AttackDef, PUNCH
from ..engine import colors
from ..engine.rng import RNG
from ..engine.screen import Frag
from .item import Item, severed_part
from .skills import skill_bonus

# -- tunable constants ------------------------------------------------------ #

#: Base momentum a creature of average strength delivers barehanded.
BASE_MOMENTUM = 12000.0
#: How much a kilogram of weapon adds to momentum.
WEIGHT_MOMENTUM = 9000.0
#: How much attacker size contributes (relative to a 70 l human).
SIZE_REFERENCE = 70000.0
#: Chance floor and ceiling for landing a blow.
MIN_HIT_CHANCE = 0.05
MAX_HIT_CHANCE = 0.97


@dataclass
class AttackResult:
    """What happened when one creature attacked another."""

    hit: bool = False
    messages: List[Frag] = field(default_factory=list)
    killed: bool = False
    damage: float = 0.0
    part: Optional[str] = None
    blocked: bool = False
    dodged: bool = False
    parried: bool = False

    def add(self, text: str, color=None) -> None:
        """Append a message fragment."""
        self.messages.append(Frag(text, color or colors.UI["fg"]))


# --------------------------------------------------------------------------- #
# Rolls
# --------------------------------------------------------------------------- #


def _skill_for_weapon(attacker, weapon: Optional[Item]) -> str:
    """The skill governing an attack with *weapon*."""
    if weapon is not None and weapon.defn.weapon is not None:
        return weapon.defn.weapon.skill
    return "wrestling"


def attack_power(attacker, skill_id: str) -> float:
    """The attacker's overall competence with this attack, roughly 0.5..4."""
    lvl = attacker.skills.level(skill_id)
    general = attacker.skills.level("fighter")
    agility = attacker.attributes.factor("agility")
    kin = attacker.attributes.factor("kinesthetic_sense")
    return skill_bonus(lvl) * (1.0 + general * 0.03) * (agility + kin) * 0.5


def defense_power(defender) -> float:
    """The defender's overall evasiveness."""
    dodge = defender.skills.level("dodging")
    general = defender.skills.level("fighter")
    agility = defender.attributes.factor("agility")
    power = skill_bonus(dodge) * (1.0 + general * 0.02) * agility
    if not defender.body.can_stand():
        power *= 0.4
    if defender.body.unconscious > 0:
        power *= 0.05
    elif defender.body.stunned > 0:
        power *= 0.4
    power *= max(0.35, 1.0 - defender.body.pain_level() * 0.5)
    encumbrance = defender.encumbrance()
    power *= max(0.4, 1.0 - encumbrance * 0.35)
    return power


def to_hit_chance(attacker, defender, skill: str) -> float:
    """Probability that an attack connects at all."""
    atk = attack_power(attacker, skill)
    dfn = defense_power(defender)
    # Big targets are easier to hit.
    size_ratio = (defender.defn.size / max(1.0, float(attacker.defn.size))) ** 0.18
    chance = atk * size_ratio / (atk * size_ratio + dfn)
    return max(MIN_HIT_CHANCE, min(MAX_HIT_CHANCE, chance))


def compute_momentum(attacker, weapon: Optional[Item], attack_def: AttackDef) -> float:
    """Momentum delivered by one strike, in arbitrary force units."""
    strength = attacker.attributes.factor("strength")
    size_factor = (attacker.defn.size / SIZE_REFERENCE) ** 0.34
    mass = weapon.unit_weight if weapon is not None else 0.0
    skill_id = _skill_for_weapon(attacker, weapon)
    skill = skill_bonus(attacker.skills.level(skill_id))

    momentum = BASE_MOMENTUM * strength * size_factor
    if weapon is None:
        # Natural weapons vary enormously: a punch is not a dragon's bite.
        momentum *= 0.7 + attack_def.penetration / 2000.0
    else:
        momentum += WEIGHT_MOMENTUM * mass * strength
    momentum *= attack_def.velocity
    momentum *= 0.6 + 0.4 * skill
    if weapon is not None:
        momentum *= weapon.quality_bonus() * weapon.wear_factor()
    if attacker.body.winded > 0:
        momentum *= 0.75
    momentum *= max(0.5, 1.0 - attacker.body.pain_level() * 0.4)
    return max(1.0, momentum)


def attack_material(weapon: Optional[Item], attack_def: AttackDef):
    """The material doing the cutting or bashing."""
    if weapon is not None:
        return weapon.mat
    return mat_data.get("bone")


def effective_kind(weapon: Optional[Item], attack_def: AttackDef) -> str:
    """Whether an attack actually cuts, given the weapon's material."""
    if attack_def.kind != "edge":
        return "blunt"
    mat = attack_material(weapon, attack_def)
    if weapon is not None and not mat.can_hold_edge:
        return "blunt"
    return "edge"


# --------------------------------------------------------------------------- #
# Armour
# --------------------------------------------------------------------------- #


def armor_protection(defender, part_id: str, kind: str) -> Tuple[float, Optional[Item]]:
    """How much momentum a part's armour absorbs, and the outermost piece."""
    part = defender.body.part(part_id)
    if part is None:
        return (0.0, None)
    pieces = defender.inventory.armor_on(part.defn.category)
    natural = defender.defn.natural_armor * 3000.0
    total = natural
    outer: Optional[Item] = pieces[0] if pieces else None
    for piece in pieces:
        adef = piece.defn.armor
        if adef is None:
            continue
        mat = piece.mat
        strength = mat.shear_yield if kind == "edge" else mat.impact_yield
        absorb = strength * (adef.thickness / 3.0) * 0.12
        absorb *= 1.0 + adef.armor_level * 0.12
        absorb *= piece.quality_bonus() * piece.wear_factor()
        total += absorb
    return (total, outer)


def try_block(defender, rng: RNG) -> bool:
    """Roll whether the defender's shield stops the blow."""
    shield = defender.inventory.shield()
    if shield is None or not defender.body.can_grasp():
        return False
    if defender.body.is_incapacitated():
        return False
    skill = defender.skills.level("shield_use")
    adef = shield.defn.armor
    base = 0.10 + 0.025 * skill + 0.02 * (adef.armor_level if adef else 0)
    base *= defender.attributes.factor("agility")
    return rng.chance(min(0.65, base))


def try_parry(defender, rng: RNG) -> bool:
    """Roll whether the defender turns the blow aside with a weapon."""
    weapon = defender.inventory.weapon()
    if weapon is None or weapon.is_ranged or defender.body.is_incapacitated():
        return False
    skill = defender.skills.level(_skill_for_weapon(defender, weapon))
    base = 0.05 + 0.02 * skill
    base *= defender.attributes.factor("agility")
    return rng.chance(min(0.55, base))


# --------------------------------------------------------------------------- #
# Melee
# --------------------------------------------------------------------------- #


def _subject(creature) -> str:
    """``"You"`` or ``"The goblin"``."""
    if creature.is_player:
        return "You"
    return "The %s" % creature.short_name()


def _object(creature) -> str:
    """``"you"`` or ``"the goblin"``."""
    if creature.is_player:
        return "you"
    return "the %s" % creature.short_name()


def _be(creature) -> str:
    """``"are"`` for the player, ``"is"`` for anything else."""
    return "are" if creature.is_player else "is"


def _slain_line(creature) -> str:
    """The death announcement for a creature."""
    if creature.is_player:
        return "You have been slain!"
    return "%s is slain!" % _subject(creature)


def _verb(attacker, attack_def: AttackDef) -> str:
    """Conjugate an attack verb for the attacker."""
    return attack_def.verb2 if attacker.is_player else attack_def.verb3


def _weapon_phrase(weapon: Optional[Item]) -> str:
    """``" with your iron sword"`` or an empty string."""
    if weapon is None:
        return ""
    return " with %s" % weapon.name(article=True)


def choose_attack(attacker, weapon: Optional[Item], rng: RNG) -> AttackDef:
    """Pick which attack to use this swing."""
    if weapon is not None:
        attacks = weapon.attacks()
        if attacks:
            return rng.choice(attacks)
    natural = attacker.defn.attacks
    usable = []
    for na in natural:
        if not na.part:
            usable.append(na.attack)
            continue
        part = attacker.body.part(na.part)
        if part is not None and part.functional():
            usable.append(na.attack)
    if usable:
        return rng.choice(usable)
    return PUNCH


def melee_attack(
    attacker,
    defender,
    *,
    weapon: Optional[Item] = None,
    attack_def: Optional[AttackDef] = None,
    target_part: Optional[str] = None,
    rng: RNG,
    log=None,
) -> AttackResult:
    """Resolve one melee strike."""
    result = AttackResult()
    if attacker.body.dead or defender.body.dead:
        return result

    if weapon is None:
        weapon = attacker.inventory.weapon()
        if weapon is not None and weapon.is_ranged:
            weapon = None
    if attack_def is None:
        attack_def = choose_attack(attacker, weapon, rng)

    skill_id = _skill_for_weapon(attacker, weapon)
    chance = to_hit_chance(attacker, defender, skill_id)
    if target_part:
        chance *= 0.7  # aimed strikes are harder

    subject = _subject(attacker)
    obj = _object(defender)
    verb = _verb(attacker, attack_def)

    if not rng.chance(chance):
        result.dodged = True
        text = "%s %s at %s, but %s" % (
            subject, verb, obj,
            "you dodge" if defender.is_player else "%s dodges" % _object(defender),
        )
        result.add(text + ".", colors.UI["dim"])
        defender.add_exp("dodging", 12)
        attacker.add_exp(skill_id, 4)
        _emit(log, result)
        return result

    if try_block(defender, rng):
        result.blocked = True
        shield = defender.inventory.shield()
        result.add(
            "%s %s at %s, but the blow is blocked by %s." % (
                subject, verb, obj,
                shield.name(article=True) if shield else "a shield",
            ),
            colors.UI["dim"],
        )
        defender.add_exp("shield_use", 15)
        attacker.add_exp(skill_id, 4)
        _emit(log, result)
        return result

    if try_parry(defender, rng):
        result.parried = True
        result.add(
            "%s %s at %s, but the blow is parried." % (subject, verb, obj),
            colors.UI["dim"],
        )
        defender.add_exp(
            _skill_for_weapon(defender, defender.inventory.weapon()), 12
        )
        _emit(log, result)
        return result

    part = (
        defender.body.part(target_part)
        if target_part else defender.body.random_part(rng)
    )
    if part is None or part.gone:
        part = defender.body.random_part(rng)
    result.part = part.id

    kind = effective_kind(weapon, attack_def)
    momentum = compute_momentum(attacker, weapon, attack_def)
    absorbed, outer = armor_protection(defender, part.id, kind)
    delivered = momentum - absorbed
    result.damage = max(0.0, delivered)

    head = "%s %s %s in the %s%s" % (
        subject, verb, obj, part.name, _weapon_phrase(weapon)
    )

    if delivered <= 0:
        if outer is not None:
            result.add(
                "%s, but the attack is blunted by %s." % (head, outer.name(article=True)),
                colors.UI["dim"],
            )
        else:
            result.add("%s, but the attack glances away." % head, colors.UI["dim"])
        attacker.add_exp(skill_id, 6)
        defender.add_exp("armor_use", 10)
        _emit(log, result)
        return result

    clauses = defender.body.apply_damage(
        part.id, kind, delivered, attack_def.contact, attack_def.penetration, rng
    )
    result.hit = True

    if clauses:
        body_text = ", ".join(clauses)
        punct = "!" if delivered > momentum * 0.6 else "."
        result.add("%s, %s%s" % (head, body_text, punct), colors.UI["fg"])
    else:
        result.add("%s, but it is barely a scratch." % head, colors.UI["dim"])

    # A solid blunt hit can stun or knock the wind out.
    if kind == "blunt" and delivered > 12000 and rng.chance(0.35):
        defender.body.stunned += rng.randint(50, 150)
        result.add("%s %s stunned!" % (_subject(defender), _be(defender)),
                   colors.UI["warn"])
    if delivered > 30000 and rng.chance(0.25):
        defender.body.winded += rng.randint(60, 180)

    attacker.add_exp(skill_id, 20)
    attacker.add_exp("fighter", 10)
    if weapon is not None:
        weapon.wear_tick(rng)

    if defender.body.dead:
        result.killed = True
        result.add(_slain_line(defender), colors.UI["danger"])
    _emit(log, result)
    return result


#: What each kind of trap does when something walks onto it.
TRAP_STRIKES: Dict[str, Tuple[str, float, int, int, str]] = {
    # kind -> (damage kind, momentum, contact, penetration, verb)
    "weapon_trap": ("edged", 30000.0, 60, 4000, "slashes"),
    "spike_trap": ("piercing", 24000.0, 10, 8000, "impales"),
}


def trap_strike(
    victim, trap_kind: str, material: str = "", *, rng: RNG, log=None
) -> AttackResult:
    """A trap goes off under somebody.

    Traps do not miss and cannot be parried — that is the point of them — but
    armour still counts, so a well-equipped goblin may walk over one and live.
    """
    result = AttackResult()
    if victim.body.dead:
        return result
    spec = TRAP_STRIKES.get(trap_kind)
    if spec is None:
        return result
    kind, momentum, contact, penetration, verb = spec

    part = victim.body.random_part(rng)
    if part is None:
        return result
    result.part = part.id
    momentum *= rng.uniform(0.7, 1.25)
    absorbed, outer = armor_protection(victim, part.id, kind)
    delivered = max(0.0, momentum - absorbed)
    result.damage = delivered

    name = ("%s %s" % (material, trap_kind.replace("_", " "))).strip()
    head = "A %s %s %s in the %s" % (name, verb, _object(victim), part.name)
    if delivered <= 0:
        result.add("%s, but the armour holds." % head, colors.UI["dim"])
        _emit(log, result)
        return result

    clauses = victim.body.apply_damage(
        part.id, kind, delivered, contact, penetration, rng)
    result.hit = True
    if clauses:
        result.add("%s, %s!" % (head, ", ".join(clauses)), colors.UI["fg"])
    else:
        result.add("%s." % head, colors.UI["dim"])
    if victim.body.dead:
        result.killed = True
        result.add(_slain_line(victim), colors.UI["danger"])
    _emit(log, result)
    return result


def wrestle(attacker, defender, move: str, *, rng: RNG, log=None) -> AttackResult:
    """Resolve a grappling move: ``"grab"``, ``"throw"``, ``"choke"``, ``"break"``."""
    result = AttackResult()
    atk = attack_power(attacker, "wrestling") * attacker.attributes.factor("strength")
    dfn = defense_power(defender) * defender.attributes.factor("strength")
    chance = max(0.05, min(0.95, atk / (atk + dfn)))
    subject = _subject(attacker)
    obj = _object(defender)

    if not rng.chance(chance):
        result.add("%s %s to grapple %s, but fail%s." % (
            subject, "try" if attacker.is_player else "tries", obj,
            "" if attacker.is_player else "s"), colors.UI["dim"])
        defender.add_exp("wrestling", 8)
        _emit(log, result)
        return result

    attacker.add_exp("wrestling", 25)
    result.hit = True
    if move == "throw":
        defender.body.stunned += rng.randint(60, 160)
        result.add("%s throw%s %s to the ground!" % (
            subject, "" if attacker.is_player else "s", obj), colors.UI["fg"])
    elif move == "choke":
        throat = defender.body.part("throat")
        if throat is not None and not throat.gone:
            clauses = defender.body.apply_damage(
                "throat", "blunt", 8000 * attacker.attributes.factor("strength"),
                20, 0, rng
            )
            result.add("%s choke%s %s, %s!" % (
                subject, "" if attacker.is_player else "s", obj,
                ", ".join(clauses) if clauses else "cutting off the air"),
                colors.UI["fg"])
        else:
            result.add("%s find%s nothing to choke." % (
                subject, "" if attacker.is_player else "s"), colors.UI["dim"])
    elif move == "break":
        part = defender.body.random_part(rng, prefer="LIMB")
        clauses = defender.body.apply_damage(
            part.id, "blunt", 14000 * attacker.attributes.factor("strength"),
            60, 0, rng
        )
        result.part = part.id
        result.add("%s wrench%s %s's %s, %s!" % (
            subject, "" if attacker.is_player else "es", obj, part.name,
            ", ".join(clauses) if clauses else "straining it"), colors.UI["fg"])
    else:
        defender.body.stunned += rng.randint(20, 60)
        result.add("%s grab%s hold of %s." % (
            subject, "" if attacker.is_player else "s", obj), colors.UI["fg"])

    if defender.body.dead:
        result.killed = True
        result.add(_slain_line(defender), colors.UI["danger"])
    _emit(log, result)
    return result


# --------------------------------------------------------------------------- #
# Ranged
# --------------------------------------------------------------------------- #


def ranged_attack(
    attacker, defender, weapon: Item, ammo: Optional[Item], *, rng: RNG, log=None
) -> AttackResult:
    """Resolve a shot from a bow, crossbow or sling."""
    result = AttackResult()
    wdef = weapon.defn.weapon
    if wdef is None or not wdef.ranged:
        result.add("That is not something you can shoot.", colors.UI["warn"])
        _emit(log, result)
        return result
    if ammo is None or ammo.count <= 0:
        result.add("You have nothing to shoot.", colors.UI["warn"])
        _emit(log, result)
        return result

    skill_id = wdef.skill
    dist = max(1, attacker.distance_to(defender))
    chance = to_hit_chance(attacker, defender, skill_id)
    chance *= max(0.25, 1.0 - dist * 0.025)

    subject = _subject(attacker)
    obj = _object(defender)
    ammo_name = ammo.base_name(False)

    ammo.count -= 1
    if ammo.count <= 0:
        attacker.inventory.remove(ammo, 1)

    if not rng.chance(chance):
        result.add("%s fire%s at %s and miss%s." % (
            subject, "" if attacker.is_player else "s", obj,
            "" if attacker.is_player else "es"), colors.UI["dim"])
        attacker.add_exp(skill_id, 6)
        _emit(log, result)
        return result

    if try_block(defender, rng):
        result.blocked = True
        result.add("%s fire%s at %s, but the %s is blocked." % (
            subject, "" if attacker.is_player else "s", obj, ammo_name),
            colors.UI["dim"])
        defender.add_exp("shield_use", 12)
        _emit(log, result)
        return result

    attack = (ammo.attacks() or weapon.attacks() or [PUNCH])[0]
    part = defender.body.random_part(rng)
    result.part = part.id
    kind = effective_kind(ammo, attack)

    momentum = wdef.shoot_force * 6.0
    momentum *= 1.0 + attacker.skills.level(skill_id) * 0.08
    momentum *= weapon.quality_bonus() * ammo.quality_bonus()
    momentum *= 1.0 + ammo.mat.shear_yield / 400000.0
    momentum *= max(0.4, 1.0 - dist * 0.012)

    absorbed, outer = armor_protection(defender, part.id, kind)
    delivered = momentum - absorbed
    result.damage = max(0.0, delivered)

    head = "%s fire%s %s into %s's %s" % (
        subject, "" if attacker.is_player else "s",
        "a %s" % ammo_name, obj, part.name,
    )
    if delivered <= 0:
        result.add("%s, but it fails to penetrate%s." % (
            head, " %s" % outer.name(article=True) if outer else ""),
            colors.UI["dim"])
        attacker.add_exp(skill_id, 8)
        _emit(log, result)
        return result

    clauses = defender.body.apply_damage(
        part.id, kind, delivered, attack.contact, attack.penetration, rng
    )
    result.hit = True
    result.add("%s, %s!" % (head, ", ".join(clauses) if clauses else "drawing blood"),
               colors.UI["fg"])
    attacker.add_exp(skill_id, 22)
    if defender.body.dead:
        result.killed = True
        result.add(_slain_line(defender), colors.UI["danger"])
    _emit(log, result)
    return result


def throw_item(attacker, defender, item: Item, *, rng: RNG, log=None) -> AttackResult:
    """Resolve a thrown object striking a creature."""
    result = AttackResult()
    chance = to_hit_chance(attacker, defender, "throwing")
    subject = _subject(attacker)
    obj = _object(defender)

    if not rng.chance(chance):
        result.add("%s throw%s %s at %s and miss%s." % (
            subject, "" if attacker.is_player else "s", item.name(article=True),
            obj, "" if attacker.is_player else "es"), colors.UI["dim"])
        attacker.add_exp("throwing", 6)
        _emit(log, result)
        return result

    attack = (item.attacks() or [PUNCH])[0]
    part = defender.body.random_part(rng)
    result.part = part.id
    kind = effective_kind(item, attack)
    momentum = (
        2200.0 * attacker.attributes.factor("strength")
        * (1.0 + attacker.skills.level("throwing") * 0.08)
        * (0.5 + min(3.0, item.unit_weight))
    )
    absorbed, _outer = armor_protection(defender, part.id, kind)
    delivered = momentum - absorbed
    result.damage = max(0.0, delivered)

    head = "%s throw%s %s, striking %s in the %s" % (
        subject, "" if attacker.is_player else "s", item.name(article=True),
        obj, part.name,
    )
    if delivered <= 0:
        result.add("%s, but it bounces off." % head, colors.UI["dim"])
    else:
        clauses = defender.body.apply_damage(
            part.id, kind, delivered, attack.contact, attack.penetration, rng
        )
        result.hit = True
        result.add("%s, %s!" % (head, ", ".join(clauses) if clauses else "bruising it"),
                   colors.UI["fg"])
    attacker.add_exp("throwing", 20)
    if defender.body.dead:
        result.killed = True
        result.add(_slain_line(defender), colors.UI["danger"])
    _emit(log, result)
    return result


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _emit(log, result: AttackResult) -> None:
    """Push a result's messages into a message log."""
    if log is None:
        return
    for frag in result.messages:
        log.combat([frag])


def opportunity_to_flee(creature) -> bool:
    """True if a creature is hurt or frightened enough to break off."""
    if creature.defn.has("NO_FEAR"):
        return False
    health = creature.body.health_fraction()
    bravery = creature.personality.bravery_factor()
    threshold = 0.45 / max(0.25, bravery)
    return health < min(0.75, threshold)


def severed_items(defender, rng: RNG) -> List[Item]:
    """Build items for any parts that were just cut off."""
    out: List[Item] = []
    for p in defender.body.parts.values():
        if p.severed and not p.defn.has("INTERNAL"):
            if any(w.severed and w.age == 0 for w in p.wounds):
                out.append(severed_part(defender, p.name))
                for w in p.wounds:
                    if w.severed:
                        w.age = 1
    return out
