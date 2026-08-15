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
from ..engine.scheduler import ACTION_COST
from ..engine.screen import Frag
from . import armour
from . import contact as contact_mod
from .contact import spread
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
    #: Set when the defender had not noticed the attacker.
    ambush: bool = False
    #: Energy the strike took, against `ACTION_COST` for a standard action.
    #: A maul is worth nearly two sword-blows of somebody else's time.
    cost: int = ACTION_COST

    def add(self, text: str, color=None) -> None:
        """Append a message fragment."""
        self.messages.append(Frag(text, color or colors.UI["fg"]))


# --------------------------------------------------------------------------- #
# Rolls
# --------------------------------------------------------------------------- #


#: Which skill governs an unarmed attack, by what the attack is called.
#:
#: `striker`, `kicker` and `biter` are in the skill table, the wrestler
#: profession starts with `striker` 4 and `kicker` 3, and nine species carry
#: an authored `biter` -- a dragon has 12 of it. None of them had ever been
#: read: every unarmed attack asked for `wrestling`, which a dragon does not
#: have and a wrestler was given for grappling. Bites and stings are done with
#: the mouth, kicks with the feet, and everything else a body does to somebody
#: is striking.
NATURAL_SKILL: Dict[str, str] = {
    "bite": "biter", "sting": "biter",
    "kick": "kicker",
}
STRIKING = "striker"


def skill_for_attack(attacker, weapon: Optional[Item],
                     attack_def: Optional[AttackDef] = None) -> str:
    """The skill governing one particular blow.

    The weapon decides it when there is one. Without a weapon it is the
    *attack* that decides, which is the part that was missing: a punch, a kick
    and a bite are three different things to be good at.
    """
    if weapon is not None and weapon.defn.weapon is not None:
        return weapon.defn.weapon.skill
    if attack_def is None:
        return "wrestling"
    return NATURAL_SKILL.get(attack_def.name, STRIKING)


def _skill_for_weapon(attacker, weapon: Optional[Item]) -> str:
    """The skill governing an attack with *weapon*, ignoring which attack.

    Kept for the places that ask about a creature's weapon rather than about
    a blow -- parrying, and pricing a swing before one is chosen.
    """
    return skill_for_attack(attacker, weapon)


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
    skill_id = skill_for_attack(attacker, weapon, attack_def)
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


# --------------------------------------------------------------------------- #
# How long a blow takes
# --------------------------------------------------------------------------- #
#
# `prepare` and `recover` -- the wind-up and the follow-through -- have been on
# every attack in the item table and every natural attack in the creature table
# since both were written, and nothing had ever read either of them. A dagger
# flick and a maul swing cost one action each, so the only question a weapon
# ever asked was how hard it hit.

#: The swing the table is calibrated around: a sword, `prepare` 3 and
#: `recover` 3. Everything else is time relative to that.
BASELINE_SWING = 6

#: What a creature swings freely, as a share of what it can carry. Under this
#: the weapon costs nothing extra; over it, the swing starts to drag -- which
#: is how the same maul is a slow weapon for a dwarf and an ordinary one for a
#: strong human.
EASY_SWING = 0.15

#: What each unit of weight over that costs.
HEFT_PENALTY = 0.55

#: What each level of skill shaves off. A legendary weapon-user has cut a
#: third from the time, which is worth about one extra blow in three.
SKILL_RELIEF = 0.022

#: The band an attack can occupy. Both ends are reached, and by the right
#: things: a bare fist is the fastest attack there is and sits on the floor,
#: and a kobold that has picked up a maul sits on the ceiling. What stops the
#: floor from making volume beat weight is not this number, it is armour --
#: a dagger swings half again as often as a sword and still cannot get
#: through a breastplate, because momentum has to clear the tissue's yield
#: before it does anything at all.
FASTEST = 0.55
SLOWEST = 2.20


def swing_time(attack_def: AttackDef) -> int:
    """The wind-up and follow-through of one attack, in the table's units."""
    return (attack_def.prepare + attack_def.recover) or BASELINE_SWING


def heft(attacker, weapon: Optional[Item]) -> float:
    """How heavy a weapon is for whoever is holding it. 1.0 is the easy limit.

    Measured against `carry_capacity`, which already knows the creature's size
    and strength, so a kobold and a dragon get the same question asked in
    their own terms.
    """
    if weapon is None:
        return 0.0
    easy = attacker.carry_capacity() * EASY_SWING
    if easy <= 0:
        return 0.0
    return weapon.unit_weight / easy


def attack_cost(attacker, weapon: Optional[Item], attack_def: AttackDef) -> int:
    """Energy one strike costs, against `ACTION_COST` for a standard action.

    A dagger is most of two blows to a sword's one and a maul is most of two
    sword-blows' worth of time, so a weapon is finally a trade rather than a
    damage figure. Wounds are deliberately not in here: `effective_speed`
    already charges for pain and a mangled arm, and charging twice for the
    same injury is how a hurt creature stops being able to act at all.
    """
    factor = swing_time(attack_def) / float(BASELINE_SWING)
    factor *= 1.0 + HEFT_PENALTY * max(0.0, heft(attacker, weapon) - 1.0)
    skill = attacker.skills.level(skill_for_attack(attacker, weapon, attack_def))
    factor *= max(0.5, 1.0 - SKILL_RELIEF * skill)
    return int(ACTION_COST * max(FASTEST, min(SLOWEST, factor)))


def timed_strike(attacker, defender, *, rng: RNG, log=None,
                 weapon: Optional[Item] = None,
                 ground=None) -> Optional[AttackResult]:
    """One step of a melee in a mode with no energy scheduler.

    A fortress steps every creature once per tick regardless of what it is
    holding, so `attack_cost` has nowhere to be spent there. This banks a
    standard action's worth of time each step and swings only once it has
    saved up enough, carrying the change -- so a hammerer really does land
    fewer blows than a swordsman over the same siege, without the fortress
    needing an energy model of its own.

    Returns ``None`` on the steps spent winding up.
    """
    if weapon is None:
        weapon = attacker.inventory.weapon()
        if weapon is not None and weapon.is_ranged:
            weapon = None
    # Chosen once and handed on: pricing one attack and then swinging
    # whichever the next roll picks would charge for a swing nobody made,
    # and would spend a draw doing it.
    attack_def = choose_attack(attacker, weapon, rng, defender)

    bank = getattr(attacker, "swing_bank", 0.0) + ACTION_COST
    cost = attack_cost(attacker, weapon, attack_def)
    if bank < cost:
        attacker.swing_bank = bank
        return None
    attacker.swing_bank = bank - cost
    return melee_attack(attacker, defender, weapon=weapon,
                        attack_def=attack_def, rng=rng, log=log,
                        ground=ground)


def _drop_severed(defender, rng: RNG, where, result) -> None:
    """Put whatever was just cut off on the floor.

    `severed_items` has built these since limbs could come off and **nothing
    had ever called it**: the body model tracked the severed part, the item
    factory named it ("a goblin left hand"), and the arm itself did not exist.
    """
    if where is None:
        return
    drop = getattr(where, "drop_item", None)
    if drop is None:
        return
    for item in severed_items(defender, rng):
        drop(item, defender.x, defender.y, defender.z)
        result.add("%s falls to the ground." % item.name(article=True).capitalize(),
                   colors.UI["danger"])


def _wear_gear(attacker, weapon, defender, piece, rng: RNG, log) -> None:
    """Charge a weapon and a piece of armour for the work they just did.

    `wear_tick` was already being called on the weapon and its answer thrown
    away, so a weapon could be used past the end of the condition scale and
    nothing was ever destroyed. Armour was never asked at all.
    """
    from . import wear as wear_mod

    if weapon is not None:
        wear_mod.strike(attacker, weapon, rng, log=log)
    if piece is not None:
        wear_mod.absorb(defender, piece, rng, log=log)


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


def armor_protection(
    defender, part_id: str, kind: str, contact: int = int(contact_mod.REFERENCE),
    momentum: float = 0.0,
) -> Tuple[float, Optional[Item]]:
    """How much momentum a part's armour absorbs, and the outermost piece.

    Armour works by spreading a blow over more of itself than the blow arrived
    on, so how much it absorbs depends on how much it was given to spread. A
    great axe hands a breastplate the whole length of its edge and the plate
    takes almost all of it; a spear point hands it a few square millimetres and
    goes through. *contact* is that area, and defaults to the middle of the
    table so a caller that has no attack in hand gets the old behaviour.

    *momentum* is what was swung, and it is only needed for blunt blows.
    Stopping a cut is a material question -- either the edge shears the plate
    or nothing at all gets through -- but stopping an impact is a question of
    where the momentum goes, and a share of it always arrives inside. Pass 0
    and no cap is applied, which is the old behaviour and wrong for anything
    blunt; see :mod:`ascii_warriors.game.armour`.
    """
    part = defender.body.part(part_id)
    if part is None:
        return (0.0, None)
    pieces = defender.inventory.armor_on(part.defn.category)
    natural = defender.defn.natural_armor * 3000.0
    total = natural
    # How much of a shell all of it makes, which is a separate question from
    # how hard it is to cut and the one that matters to a hammer.
    rigid = defender.defn.natural_armor * armour.REFERENCE_RIGIDITY * 0.25
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
        rigid += armour.rigidity(adef.armor_level, adef.thickness) \
            * piece.wear_factor()
    # Natural armour spreads a blow for the same reason plate does: a hide is
    # thick, and a point goes between the scales of it either way.
    total *= spread(contact)
    if kind != "edge" and momentum > 0.0:
        # An impact is not stopped by not being cut. However good the plate,
        # it is driven into the man wearing it, and how well he wears it is
        # what decides how much of that he feels.
        total = min(total, armour.blunt_cap(
            momentum, contact, defender.skills.level("armor_use"), rigid))
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


#: How sharply each level of the `fighter` skill inclines a creature towards
#: the attack that will actually get through. At zero it is a coin toss -- a
#: farmhand with a sword swings the sword -- and a trained soldier thrusts at
#: the plate and cuts at the man without one.
ATTACK_JUDGEMENT = 0.42
#: Nobody is so good that the wrong choice never happens.
MAX_JUDGEMENT = 5.0


#: Body plan -> the part a fighter judges it by. A property of the plan, not
#: of the individual, so it is worked out once per species rather than walked
#: out of forty parts on every swing in the game.
_JUDGED_PART: Dict[str, str] = {}


def _judged_part(defender):
    """The part a fighter sizes up before deciding how to strike.

    The chest, when there is one. It is the single likeliest thing a blow
    lands on, and the piece everybody armours first, so it is what tells him
    whether his edge is any use today. Judging by the least armoured part
    instead was tried and is worse: a blow lands where it lands, and a fighter
    who reasons about a bare thigh he cannot aim at is not reasoning.
    """
    known = _JUDGED_PART.get(defender.body.plan_id)
    if known is not None:
        part = defender.body.part(known)
        if part is not None and not part.gone:
            return part
    best = None
    for part in defender.body.parts.values():
        if part.gone or part.defn.has("INTERNAL"):
            continue
        if part.defn.category == "torso":
            if best is None or best.defn.category != "torso" \
                    or part.defn.rel_size > best.defn.rel_size:
                best = part
        elif best is None or (best.defn.category != "torso"
                              and part.defn.rel_size > best.defn.rel_size):
            best = part
    if best is not None:
        _JUDGED_PART[defender.body.plan_id] = best.id
    return best


def _judge_attack(attacker, weapon: Optional[Item], attacks, defender,
                  rng: RNG) -> AttackDef:
    """Choose among *attacks* by what each would deliver to *defender*.

    Weapons in this game carry two attacks apiece and they stopped being
    interchangeable the moment contact area was read: against an iron mail
    shirt a sword's point gets through and its edge does not. The choice was a
    flat coin toss, which threw the whole of that away as variance. Skill at
    arms is what buys the judgement -- the roll is still a roll, it is only
    weighted.
    """
    part = _judged_part(defender)
    judgement = min(MAX_JUDGEMENT,
                    attacker.skills.level("fighter") * ATTACK_JUDGEMENT)
    if part is None or judgement <= 0.0:
        return rng.choice(attacks)
    # Nothing to judge against a man in a shirt: with no armour to spread the
    # blow, every attack lands with the momentum it was swung with and the
    # ranking collapses to which one is quickest. Scoring it anyway cost a
    # third of the time every strike in the game takes, for a preference of
    # three blows in five.
    if defender.defn.natural_armor <= 0 \
            and not defender.inventory.armor_on(part.defn.category):
        return rng.choice(attacks)
    delivered = []
    for attack in attacks:
        kind = effective_kind(weapon, attack)
        momentum = compute_momentum(attacker, weapon, attack)
        absorbed, _outer = armor_protection(
            defender, part.id, kind, attack.contact, momentum)
        delivered.append(max(0.0, momentum - absorbed))
    best = max(delivered)
    if best <= 0.0:
        # Nothing he does reaches the man's chest. There is no judgement to
        # make against a target like that; swing, and hope for a limb.
        return rng.choice(attacks)
    weights = [(d / best) ** judgement for d in delivered]
    index = rng.pick_index(weights)
    return attacks[index] if index >= 0 else rng.choice(attacks)


def choose_attack(attacker, weapon: Optional[Item], rng: RNG,
                  defender=None) -> AttackDef:
    """Pick which attack to use this swing.

    With a defender in view the choice is judged rather than rolled flat; see
    :func:`_judge_attack`. Without one -- pricing a swing, or a test asking
    what a weapon does -- it stays the coin toss it always was.
    """
    if weapon is not None:
        attacks = weapon.attacks()
        if attacks:
            if defender is None or len(attacks) < 2:
                return rng.choice(attacks)
            return _judge_attack(attacker, weapon, attacks, defender, rng)
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
        if defender is None or len(usable) < 2:
            return rng.choice(usable)
        return _judge_attack(attacker, None, usable, defender, rng)
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
    world=None,
    ground=None,
) -> AttackResult:
    """Resolve one melee strike.

    Pass *world* to let the strike know whether the defender had noticed the
    attacker. Without it every attack is a fair fight, which is what the two
    fortress loops want and is why it is optional.

    *ground* is where anything cut off lands, and is separate for exactly that
    reason: the fortress wants the limbs without wanting the ambush rules.
    """
    result = AttackResult()
    if attacker.body.dead or defender.body.dead:
        return result

    from . import stealth

    ambush = world is not None and stealth.unnoticed(world, attacker, defender)
    if ambush:
        result.ambush = True
        target_part = target_part or stealth.ambush_part(defender, rng)

    if weapon is None:
        weapon = attacker.inventory.weapon()
        if weapon is not None and weapon.is_ranged:
            weapon = None
    if attack_def is None:
        attack_def = choose_attack(attacker, weapon, rng, defender)
    result.cost = attack_cost(attacker, weapon, attack_def)

    skill_id = skill_for_attack(attacker, weapon, attack_def)
    chance = to_hit_chance(attacker, defender, skill_id)
    if target_part and not ambush:
        chance *= 0.7  # aimed strikes are harder
    if ambush:
        # It is not defending. Aiming is the easy part.
        chance = max(chance, AMBUSH_HIT)

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

    if not ambush and try_block(defender, rng):
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

    if not ambush and try_parry(defender, rng):
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
    if ambush:
        momentum *= stealth.AMBUSH_MOMENTUM
    absorbed, outer = armor_protection(
        defender, part.id, kind, attack_def.contact, momentum)
    delivered = momentum - absorbed
    result.damage = max(0.0, delivered)

    head = "%s %s %s in the %s%s" % (
        subject, verb, obj, part.name, _weapon_phrase(weapon)
    )
    if ambush:
        head = "%s, unseen, %s %s in the %s%s" % (
            subject, verb, obj, part.name, _weapon_phrase(weapon))

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
        _wear_gear(attacker, weapon, defender, outer, rng, log)
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
    _wear_gear(attacker, weapon, defender, outer if absorbed > 0 else None,
               rng, log)
    _drop_severed(defender, rng, ground if ground is not None else world,
                  result)
    if ambush:
        stealth.on_ambush(world, attacker, defender)

    # A bite from something cursed is how the curse travels. What matters is
    # the attack that landed, not whether the thing also owns a sword.
    if attack_def.name in BITES:
        from . import night, venom

        dose = venom.on_bite(attacker, defender, rng)
        if dose is not None:
            result.add("%s been envenomed."
                       % ("You have" if defender.is_player
                          else "%s has" % _subject(defender)),
                       colors.UI["danger"])
        if night.on_bite(attacker, defender, rng, log):
            result.add("%s been bitten by something unclean."
                       % ("You have" if defender.is_player
                          else "%s has" % _subject(defender)),
                       colors.UI["danger"])

    if defender.is_player and world is not None and not defender.body.dead:
        from . import mounts

        thrown = mounts.on_hit(world, int(delivered), rng)
        if thrown:
            result.add(thrown, colors.UI["danger"])

    if defender.body.dead:
        result.killed = True
        result.add(_slain_line(defender), colors.UI["danger"])
    _emit(log, result)
    return result


#: An ambusher barely has to aim. Not certainty -- you can still fumble a
#: knife in the dark -- but it is not a fight the defender is having yet.
AMBUSH_HIT = 0.92


#: Natural attacks that put teeth into a wound. Only these carry a curse:
#: being clawed by a werewolf is a bad afternoon, being bitten is a life.
BITES = frozenset({"bite", "gore", "sting"})


#: What each kind of trap does when something walks onto it.
TRAP_STRIKES: Dict[str, Tuple[str, float, int, int, str]] = {
    # kind -> (damage kind, momentum, contact, penetration, verb)
    # "edge" and "blunt" are the only two kinds the model knows. This table
    # was written with "edged" and "piercing", which are neither, so a weapon
    # trap that slashes you has never once cut anybody: both the armour test
    # and the tissue test fall through to their blunt branch, and the blunt
    # branch does not bleed and does not sever.
    "weapon_trap": ("edge", 30000.0, 60, 4000, "slashes"),
    "spike_trap": ("edge", 24000.0, 10, 8000, "impales"),
    # The ones a tomb was sealed with. Same table so armour counts against
    # them exactly as it does against a fortress trap -- a second damage path
    # for the same idea is how the two quietly stop agreeing.
    "dart": ("edge", 9000.0, 5, 9000, "strikes"),
    "pit": ("blunt", 26000.0, 400, 500, "slams"),
    "collapse": ("blunt", 42000.0, 600, 800, "crushes"),
    "snare": ("blunt", 3000.0, 200, 200, "catches"),
    "alarm": ("blunt", 0.0, 0, 0, "startles"),
    # Standing in a fire. Armour helps against a dart and helps a great deal
    # less against burning, which is what the low contact area buys.
    "fire": ("blunt", 5200.0, 2, 300, "burns"),
    # The other end of the same scale. Frostbite is slow and small and takes
    # fingers rather than limbs, and a mitten is worth more against it than a
    # breastplate — which is what the armour model already says, given the
    # chance to say it.
    "frostbite": ("blunt", 2600.0, 4, 150, "numbs"),
    # The ground. A fall is the whole body arriving at once: an enormous
    # contact area, so armour spreads it rather than stopping it, and very
    # little penetration -- nothing is being driven through anything, it is
    # all blunt trauma. A `pit` trap's numbers are a trap's, and a
    # breastplate simply ate a six-storey drop.
    "fall": ("blunt", 260000.0, 2000, 100, "slams"),
}


def trap_strike(
    victim, trap_kind: str, material: str = "", *, rng: RNG, log=None,
    prefer: str = "",
) -> AttackResult:
    """A trap goes off under somebody.

    Traps do not miss and cannot be parried — that is the point of them — but
    armour still counts, so a well-equipped goblin may walk over one and live.

    *prefer* aims at a part, a category or a flag, for the hazards that have
    somewhere in particular to bite.
    """
    result = AttackResult()
    if victim.body.dead:
        return result
    spec = TRAP_STRIKES.get(trap_kind)
    if spec is None:
        return result
    kind, momentum, contact, penetration, verb = spec

    part = victim.body.random_part(rng, prefer=prefer or None)
    if part is None:
        return result
    result.part = part.id
    momentum *= rng.uniform(0.7, 1.25)
    absorbed, outer = armor_protection(victim, part.id, kind, contact, momentum)
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
    attacker, defender, weapon: Item, ammo: Optional[Item], *, rng: RNG,
    log=None, ground=None
) -> AttackResult:
    """Resolve a shot from a bow, crossbow or sling.

    *ground* is where the spent round lands, and is the same parameter and the
    same reason as the one v3.25 added for severed limbs: combat is called
    from two modes and from tests that have no world at all, so the caller
    says where the floor is or there is no floor.
    """
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

    from . import ammo as ammo_mod

    spent = ammo_mod.spend(attacker, ammo)

    if not rng.chance(chance):
        result.add("%s fire%s at %s and miss%s." % (
            subject, "" if attacker.is_player else "s", obj,
            "" if attacker.is_player else "es"), colors.UI["dim"])
        attacker.add_exp(skill_id, 6)
        ammo_mod.land(ground, spent,
                      (defender.x, defender.y, defender.z), rng, hit=False)
        _emit(log, result)
        return result

    if try_block(defender, rng):
        result.blocked = True
        result.add("%s fire%s at %s, but the %s is blocked." % (
            subject, "" if attacker.is_player else "s", obj, ammo_name),
            colors.UI["dim"])
        defender.add_exp("shield_use", 12)
        ammo_mod.land(ground, spent,
                      (defender.x, defender.y, defender.z), rng, hit=True)
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

    absorbed, outer = armor_protection(
        defender, part.id, kind, attack.contact, momentum)
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
        ammo_mod.land(ground, spent,
                      (defender.x, defender.y, defender.z), rng, hit=True)
        _emit(log, result)
        return result

    clauses = defender.body.apply_damage(
        part.id, kind, delivered, attack.contact, attack.penetration, rng
    )
    result.hit = True
    result.add("%s, %s!" % (head, ", ".join(clauses) if clauses else "drawing blood"),
               colors.UI["fg"])
    attacker.add_exp(skill_id, 22)
    ammo_mod.land(ground, spent,
                  (defender.x, defender.y, defender.z), rng, hit=True)
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
    absorbed, _outer = armor_protection(
        defender, part.id, kind, attack.contact, momentum)
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


def opportunity_to_flee(creature, world=None) -> bool:
    """True if a creature is hurt or frightened enough to break off.

    Kept as the name the AI has always called, and handed to `morale`, which
    knows what this one never could: who is standing beside it, and how many
    of them have already gone down.
    """
    if world is not None:
        from . import morale

        return morale.broke(creature, world)
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
