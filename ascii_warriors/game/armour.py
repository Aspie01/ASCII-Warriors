"""What armour is worth: what it stops, what it merely spreads, and who is
wearing it.

Armour absorbed a blow by comparing the blow to the armour's material -- shear
yield against an edge, impact yield against a hammer. That is the right test
for an edge and the wrong one for a hammer, and the difference is not small:
steel's impact yield is three and a half times its shear yield, so every piece
of armour in the game was three and a half times *better* against a mace than
against an axe. A steel breastplate absorbed 322,000 from a war hammer that
carried 51,000. The hammerman's entire pitch at character creation -- "armour
does not help against a hammer" -- was exactly inverted.

The mistake is treating both blows as the same kind of question. Stopping a cut
is a material question: either the edge shears the plate or it does not, and if
it does not then nothing at all gets through. That part was right, and a
breastplate that cannot be cut by any sword in the game is not a bug.

Stopping an impact is a momentum question. The plate is not cut, it is driven
into the man inside it. Padding and rigidity spread the blow across the ribs
instead of concentrating it on one, and that is worth a great deal -- but a
share of it always arrives, and no thickness of steel makes that share zero.

So blunt absorption is capped at a share of what was swung, and the rest is
transmitted. The cap only ever binds on metal: a wool tunic's absorption is so
far below it that the `min` never fires, which is exactly right.
"""

from __future__ import annotations

from .contact import spread

# -- tunable constants ------------------------------------------------------ #

#: The share of a blunt blow that reaches the body through armour that spreads
#: it perfectly. Calibrated so a war hammer on a steel breastplate lands about
#: as hard as a dagger on a bare chest: a real blow, several of which break
#: something, and not the free kill that removing armour's blunt advantage
#: outright would have made it.
BLUNT_TRANSMIT = 0.30

#: Contact area still decides. A hammer face concentrates what it transmits on
#: one rib; a crossbow butt or a falling floor arrives across the whole chest
#: and the armour has something to spread. Bounded because no blunt blow is so
#: fine that armour is irrelevant, nor so broad that it is harmless.
MIN_TRANSMIT = 0.12
MAX_TRANSMIT = 0.45

#: The spreading power of an iron mail shirt -- `armor_level` 3, thickness 2 --
#: which is the middle of the table and the yardstick the rest is measured
#: against. Rigidity is geometry, not metallurgy: how thick the piece is and
#: how much of a shell it makes. It is deliberately *not* the material's yield,
#: because how hard something is to cut says nothing about how well it spreads
#: a blow that is not cutting it.
REFERENCE_RIGIDITY = (1.0 + 3 * 0.12) * (2 / 3.0)
#: How strongly rigidity buys down what gets through. A square root, so a
#: breastplate is meaningfully better than mail against a hammer without
#: becoming the wall it used to be.
RIGIDITY_POWER = 0.5

#: What each level of `armor_use` takes off the share that gets through. The
#: skill has been in the table with a blank description since the table was
#: written, granted to four professions, three species and the fortress soldier
#: labor, counted in the squad list's danger score, and awarded experience
#: every time a blow was turned -- and read by nothing. Knowing how armour is
#: padded, fitted and angled is exactly the difference between a hammer blow
#: that cracks a rib and one that rings.
#: Set so the floor is reached at level 20 and not before: a skill whose last
#: five levels buy nothing is a skill that lies to whoever is training it.
FIT_RELIEF = 0.0225
#: Nobody wears armour well enough to make a maul harmless.
MIN_FIT = 0.55

#: A middling blunt blow -- a war hammer swung by a trained arm -- used to ask
#: whether a piece of armour is thick enough for the cap to be what limits it
#: at all. Below this it is simply thin, and the cap never fires.
REFERENCE_BLOW = 50000.0

#: What each level of `armor_use` takes off the felt weight of what is worn.
#: The other half of the skill, and the half a wearer notices first: at
#: legendary the same steel is carried as though it were a third lighter.
WEIGHT_RELIEF = 0.017
MAX_WEIGHT_RELIEF = 0.34


# -- the model -------------------------------------------------------------- #


def rigidity(armor_level: int, thickness: int) -> float:
    """How well one piece of armour spreads a blow it is not being cut by."""
    return (1.0 + max(0, armor_level) * 0.12) * (max(1, thickness) / 3.0)


def transmit_share(contact: int, skill: int = 0, rigid: float = 0.0) -> float:
    """The share of a blunt blow that reaches the body whatever is worn.

    Falls with contact area, because a blow spread across the whole chest is
    what armour is best at. Falls with the shell's rigidity, because that is
    the difference between a breastplate and a mail shirt against a hammer --
    mail hangs on you and moves with the blow, and plate does not. And falls
    with the wearer's skill, because a hammer arriving on a well-padded,
    well-fitted plate is a different event from one arriving on a plate that
    is merely present.
    """
    share = BLUNT_TRANSMIT / spread(contact)
    if rigid > 0.0:
        share /= (rigid / REFERENCE_RIGIDITY) ** RIGIDITY_POWER
    share = max(MIN_TRANSMIT, min(MAX_TRANSMIT, share))
    return share * max(MIN_FIT, 1.0 - max(0, skill) * FIT_RELIEF)


def blunt_cap(momentum: float, contact: int, skill: int = 0,
              rigid: float = 0.0) -> float:
    """The most armour can absorb from a blunt blow of this momentum."""
    if momentum <= 0.0:
        return 0.0
    return momentum * (1.0 - transmit_share(contact, skill, rigid))


def caps_blunt(blunt_absorb: float, contact: int, rigid: float) -> bool:
    """True if the cap is what limits this piece, rather than its own thinness.

    Metal answers yes and cloth answers no, which is the difference between
    "lets a fifth of a hammer through" and "lets a hammer through".
    """
    return blunt_absorb >= blunt_cap(REFERENCE_BLOW, contact, 0, rigid)


def weight_relief(skill: int) -> float:
    """The share of worn armour's weight that skill at wearing it removes."""
    return min(MAX_WEIGHT_RELIEF, max(0, skill) * WEIGHT_RELIEF)
