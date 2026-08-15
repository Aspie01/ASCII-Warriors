"""Contact area: how widely a blow spreads the force it carries.

Every attack in the game already knew its contact area. A dagger's point is 5,
a mace's head is 20, a great axe's edge is 90000. The numbers were written with
the weapon table and then nothing read them -- momentum went into armour and
whatever survived went into tissue, and a thrust and a chop with the same
weight behaved identically.

Contact area is the number that tells them apart. A narrow one concentrates the
whole blow onto a few square millimetres: it finds the gap between the rings of
a mail shirt, it keeps its force through each tissue layer instead of spending
it there, and it arrives deep enough to reach what is behind them. What it does
to the layers it passes is slight, because a puncture is a small hole.

A wide one is the opposite. Armour spreads it, which is what a breastplate is
for; but whatever gets past opens the full width of the edge, and a limb chewed
to the bone comes off with the next blow.

:func:`spread` is that one number, and three places read it: armour absorption
in :mod:`ascii_warriors.game.combat`, and tissue damage and organ reach in
:mod:`ascii_warriors.game.body`.
"""

from __future__ import annotations

from typing import Sequence, Tuple

# -- tunable constants ------------------------------------------------------ #

#: The contact area that spreads its force exactly as much as the model always
#: assumed. Set at a kick, a gore, a claw -- the middle of the natural attacks
#: the bestiary was balanced around -- so that beasts fight as they always did
#: and the deviation is carried by the weapon table, which is what this is for.
REFERENCE = 40.0
#: How sharply spread follows contact area. The table spans four orders of
#: magnitude; this power keeps the whole of it inside a factor of four, which
#: is a difference a fight can survive.
POWER = 0.13
#: Nothing is fine enough that armour stops mattering.
MIN_SPREAD = 0.75
#: Nothing is broad enough that it cannot get through at all.
MAX_SPREAD = 2.60

#: How much faster than its width a point's cost falls away. A narrow blade
#: parts tissue rather than removing it, and the saving compounds layer by
#: layer -- which is the whole of why a thin blade arrives at the far side of
#: the ribs still carrying something and a chopping edge does not.
PIERCE_POWER = 2.0

#: Chance that a wound deep enough to reach an organ actually finds one, before
#: contact area is taken into account. A point beats this, an edge does not.
ORGAN_REACH = 0.45
#: A blow can never be so fine that it always finds an organ, nor so broad that
#: a hole through the ribs never does.
MIN_ORGAN = 0.18
MAX_ORGAN = 0.85

#: What to call a contact area, by the spread it produces. Four words because
#: the weapon table has four clusters: thrusting points and hammer faces,
#: everything a creature is born with, the flats and butts of heavy weapons,
#: and the long edges that chop.
WORDS: Sequence[Tuple[float, str]] = (
    (0.88, "piercing"),
    (1.25, "balanced"),
    (1.80, "spreading"),
    (99.0, "cleaving"),
)


# -- the model -------------------------------------------------------------- #


def spread(contact: int) -> float:
    """How widely an attack of this contact area spreads its force.

    Below 1.0 the blow is concentrated: armour absorbs less of it, it keeps
    more of its force through each tissue layer, and so it reaches deeper.
    Above 1.0 it is spread: armour absorbs more of it, and what lands chews a
    wider wound out of every layer it touches.
    """
    if contact <= 0:
        return MIN_SPREAD
    factor = (float(contact) / REFERENCE) ** POWER
    return max(MIN_SPREAD, min(MAX_SPREAD, factor))


def bite(contact: int) -> float:
    """The share of a tissue layer's resistance this blow has to pay for.

    A broad edge pays all of it, because it removes the whole width of the
    wound and cannot do better than spend what that costs. A point pays much
    less: it parts the tissue instead of taking it away. Never above 1.0 --
    the width an edge buys comes out of the layer it is cutting, not out of
    the depth below it, and charging for it twice was measurably wrong.
    """
    return min(1.0, spread(contact)) ** PIERCE_POWER


def organ_chance(contact: int) -> float:
    """Chance a wound of this contact area finds an organ behind the wall.

    A puncture through the ribs is a hole with something on the other side of
    it. A gash across them is a gash.
    """
    return max(MIN_ORGAN, min(MAX_ORGAN, ORGAN_REACH / spread(contact)))


def word(contact: int) -> str:
    """A word for what this contact area does to armour."""
    factor = spread(contact)
    for edge, name in WORDS:
        if factor <= edge:
            return name
    return WORDS[-1][1]
