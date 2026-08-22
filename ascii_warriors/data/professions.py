"""What each profession knows when it starts.

This table lived in `ui/charcreate.py`, which is where it was first needed and
the wrong place for it to live. `Game.new_game` takes a profession, stores it
on the character and then applies whatever skills the caller happened to pass
alongside -- so the profession name meant nothing on its own, and every caller
that wanted a real character had to reach into the UI layer and apply the
table by hand. The character-creation screen did. `tests/test_systems.py`
does, in three places. `tools/play.py` did not, and so spent its whole
existence measuring a warrior with `fighter 0` and `sword 0`: an iron sword, a
mail shirt, and no idea what to do with either.

Down here the game can see it, and `new_game` applies it.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: Profession -> (description, starting skills).
PROFESSIONS: Dict[str, Tuple[str, Dict[str, int]]] = {
    "warrior": ("Sword and shield. Trained to stand and fight.",
                {"fighter": 4, "sword": 4, "shield_use": 3, "armor_use": 3,
                 "dodging": 2}),
    "axeman": ("An axe takes limbs off. That is the whole argument.",
               {"fighter": 4, "axe": 5, "shield_use": 2, "armor_use": 3,
                "woodcutting": 2}),
    "hammerman": ("Armour does not help against a hammer.",
                  {"fighter": 4, "hammer": 5, "shield_use": 3, "armor_use": 4}),
    "spearman": ("Reach, and the discipline to use it.",
                 {"fighter": 4, "spear": 5, "dodging": 3, "armor_use": 2}),
    "archer": ("Kill it before it reaches you.",
               {"bow": 5, "dodging": 3, "observer": 3, "ambusher": 2}),
    "hunter": ("At home in the wilds, and never hungry.",
               {"bow": 4, "tracker": 4, "ambusher": 3, "butchery": 3,
                "herbalism": 3, "sneak": 3}),
    "thief": ("Quick hands, quiet feet and no scruples.",
              {"dagger": 4, "sneak": 5, "dodging": 4, "observer": 3,
               "lying": 3, "appraisal": 3}),
    "scholar": ("You know things. Whether that helps is another matter.",
                {"knowledge": 6, "reading": 5, "writing": 4, "diagnose": 3,
                 "persuasion": 3, "dagger": 1}),
    "bard": ("A song, a poem, and the sense to leave before the fighting.",
             {"music": 5, "poetry": 4, "dancing": 3, "conversation": 4,
              "persuasion": 3, "lying": 2, "dagger": 2}),
    "wrestler": ("No weapon. No armour. No mercy.",
                 {"wrestling": 6, "striker": 4, "kicker": 3, "dodging": 4,
                  "fighter": 3}),
    "peasant": ("You were nobody. That is where every legend starts.",
                {"dodging": 1}),
}

PROFESSION_ORDER = list(PROFESSIONS)


def skills_for(profession: str) -> Dict[str, int]:
    """What this profession starts knowing. Empty for one nobody has heard of."""
    found = PROFESSIONS.get(profession)
    return dict(found[1]) if found else {}
