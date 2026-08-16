"""Flavour text: turning numbers into the wording the game shows the player."""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

#: Skill titles, index 0..20.
SKILL_LEVELS: Tuple[str, ...] = (
    "Dabbling", "Novice", "Adequate", "Competent", "Skilled", "Proficient",
    "Talented", "Adept", "Expert", "Professional", "Accomplished", "Great",
    "Master", "High Master", "Grand Master", "Legendary",
    "Legendary+1", "Legendary+2", "Legendary+3", "Legendary+4", "Legendary+5",
)

#: Adjectives for item quality levels 0..6.
QUALITY_ADJ: Tuple[str, ...] = (
    "", "well-crafted", "finely-crafted", "superior", "exceptional",
    "masterwork", "artifact",
)

#: Pure-ASCII wrappers matching DF's quality symbols.
QUALITY_WRAP: Tuple[Tuple[str, str], ...] = (
    ("", ""), ("-", "-"), ("+", "+"), ("*", "*"), ("=", "="), ("#", "#"), ("@", "@"),
)

WEAR_NAMES: Tuple[str, ...] = ("", "x", "X", "XX")


def skill_level_name(level: int) -> str:
    """Title for a skill level, clamped to the table."""
    return SKILL_LEVELS[max(0, min(len(SKILL_LEVELS) - 1, int(level)))]


def quality_name(q: int) -> str:
    """Adjective for an item quality level."""
    return QUALITY_ADJ[max(0, min(len(QUALITY_ADJ) - 1, int(q)))]


def quality_wrap(q: int, s: str) -> str:
    """Wrap a name in its quality symbols, e.g. ``"*iron short sword*"``."""
    q = max(0, min(len(QUALITY_WRAP) - 1, int(q)))
    left, right = QUALITY_WRAP[q]
    return "%s%s%s" % (left, s, right)


def wear_name(w: int) -> str:
    """Wear marker for an item, ``""`` when pristine."""
    return WEAR_NAMES[max(0, min(len(WEAR_NAMES) - 1, int(w)))]


# --------------------------------------------------------------------------- #
# Attributes
# --------------------------------------------------------------------------- #

# Each ladder runs from the very highest to the very lowest. The middle entry is
# empty because an average trait is not worth mentioning.
_ATTR_LADDERS: Dict[str, Tuple[str, ...]] = {
    "strength": (
        "unbelievably strong", "mighty", "very strong", "strong", "",
        "weak", "very weak", "unquestionably weak",
    ),
    "agility": (
        "amazingly agile", "extremely agile", "very agile", "agile", "",
        "clumsy", "quite clumsy", "abysmally clumsy",
    ),
    "toughness": (
        "basically unbreakable", "incredibly tough", "very tough", "tough", "",
        "flimsy", "very flimsy", "shockingly fragile",
    ),
    "endurance": (
        "absolutely inexhaustible", "indefatigable", "very tireless", "tireless", "",
        "quick to tire", "very quick to tire", "truly quick to tire",
    ),
    "recuperation": (
        "possessed of amazing recuperative powers", "quick to heal",
        "very quick to heal", "quick to heal", "",
        "slow to heal", "very slow to heal", "really slow to heal",
    ),
    "disease_resistance": (
        "virtually never sick", "almost never sick", "rarely sick",
        "not very susceptible to disease", "",
        "susceptible to disease", "quite susceptible to disease",
        "really susceptible to disease",
    ),
    "analytical_ability": (
        "awesome intellectual powers", "great analytical abilities",
        "a sharp intellect", "a good intellect", "",
        "poor analytical abilities", "very bad analytical abilities",
        "stunningly poor analytical abilities",
    ),
    "focus": (
        "unbreakable focus", "a great ability to focus",
        "a sound ability to focus", "the ability to focus", "",
        "poor focus", "quite poor focus", "really poor focus",
    ),
    "willpower": (
        "an unbreakable will", "an iron will", "a strong will", "a sound will", "",
        "a meager will", "a very meager will", "next to no willpower",
    ),
    "creativity": (
        "a boundless creative imagination", "great creativity",
        "good creativity", "a knack for the creative", "",
        "meager creativity", "poor creativity", "next to no creative talent",
    ),
    "intuition": (
        "uncanny intuition", "great intuition", "good intuition", "intuition", "",
        "bad intuition", "very bad intuition", "horrible intuition",
    ),
    "patience": (
        "absolutely boundless patience", "a deep well of patience",
        "great patience", "a sum of patience", "",
        "little patience", "very little patience", "no patience at all",
    ),
    "memory": (
        "an astonishing memory", "an amazing memory", "a great memory",
        "a good memory", "",
        "a poor memory", "a really bad memory", "little memory to speak of",
    ),
    "linguistic_ability": (
        "an astonishing feel for language", "a great feel for language",
        "a good feel for language", "a feel for language", "",
        "a little difficulty with language", "difficulty with language",
        "a great deal of difficulty with language",
    ),
    "spatial_sense": (
        "a stunning feel for spatial relationships",
        "an amazing spatial sense", "a great spatial sense",
        "a good spatial sense", "",
        "a questionable spatial sense", "a poor spatial sense",
        "an atrocious spatial sense",
    ),
    "musicality": (
        "an astonishing knack for music", "a great feel for music",
        "a good feel for music", "a feel for music", "",
        "an iffy sense for music", "little sense for music",
        "next to no sense for music",
    ),
    "kinesthetic_sense": (
        "a stunning feel for the position of their own body",
        "a great kinesthetic sense", "a good kinesthetic sense",
        "a decent kinesthetic sense", "",
        "a meager kinesthetic sense", "a poor kinesthetic sense",
        "an unfortunate lack of kinesthetic sense",
    ),
    "empathy": (
        "an absolutely remarkable sense of others' emotions",
        "a great sense of empathy", "a good sense of empathy",
        "an ability to read emotions", "",
        "a poor sense of empathy", "a very bad sense of empathy",
        "the utter inability to judge others' emotions",
    ),
    "social_awareness": (
        "a truly remarkable feel for social relationships",
        "a great feel for social relationships",
        "a good feel for social relationships",
        "a sum of social awareness", "",
        "a meager ability with social relationships",
        "a poor ability with social relationships",
        "an unfortunate inability to read social situations",
    ),
}

# Attribute thresholds, highest first. Values run 0..5000 with 1000 average.
_ATTR_CUTOFFS = (2250, 1750, 1500, 1250, 750, 500, 250)


def attribute_desc(attr: str, value: int) -> str:
    """Descriptive phrase for an attribute value; ``""`` when average."""
    ladder = _ATTR_LADDERS.get(attr)
    if not ladder:
        return ""
    for i, cut in enumerate(_ATTR_CUTOFFS):
        if value >= cut:
            return ladder[i]
    return ladder[len(_ATTR_CUTOFFS)]


def attribute_rank(value: int) -> int:
    """Coarse 0..7 rank for an attribute value (0 = highest)."""
    for i, cut in enumerate(_ATTR_CUTOFFS):
        if value >= cut:
            return i
    return len(_ATTR_CUTOFFS)


# --------------------------------------------------------------------------- #
# Bodies, wounds and states
# --------------------------------------------------------------------------- #


def size_desc(volume: int) -> str:
    """A size class label for a creature volume in cm^3."""
    if volume < 10:
        return "minuscule"
    if volume < 500:
        return "tiny"
    if volume < 5000:
        return "small"
    if volume < 30000:
        return "modest"
    if volume < 90000:
        return "average"
    if volume < 300000:
        return "large"
    if volume < 1000000:
        return "huge"
    if volume < 5000000:
        return "gigantic"
    return "colossal"


def body_size_class(volume: int) -> str:
    """Alias of :func:`size_desc`, used where "class" reads better."""
    return size_desc(volume)


def wound_severity(frac: float) -> str:
    """Wording for how badly a body part is damaged."""
    if frac <= 0.0:
        return "unharmed"
    if frac < 0.15:
        return "bruised"
    if frac < 0.35:
        return "cut"
    if frac < 0.55:
        return "badly hurt"
    if frac < 0.75:
        return "severely wounded"
    if frac < 0.95:
        return "mangled"
    return "destroyed"


def stress_desc(stress: int) -> str:
    """Mental state wording for a stress value (higher is worse)."""
    if stress <= -50:
        return "ecstatic"
    if stress <= -20:
        return "elated"
    if stress <= 10:
        return "quite content"
    if stress <= 30:
        return "unhappy"
    if stress <= 60:
        return "very unhappy"
    if stress <= 90:
        return "miserable"
    return "on the verge of breaking down"


def relationship_desc(value: int) -> str:
    """Wording for how one creature feels about another."""
    if value >= 80:
        return "a lifelong friend"
    if value >= 50:
        return "a close friend"
    if value >= 25:
        return "a friend"
    if value >= 10:
        return "a passing acquaintance"
    if value > -10:
        return "a stranger"
    if value > -25:
        return "someone you dislike"
    if value > -50:
        return "an enemy"
    return "a hated enemy"


def age_desc(years: int, race: str = "human") -> str:
    """Life-stage wording, adjusted for long-lived races."""
    scale = {"elf": 5.0, "dwarf": 1.7, "goblin": 1.0, "kobold": 0.7}.get(race, 1.0)
    y = years / scale
    if y < 1:
        return "a baby"
    if y < 12:
        return "a child"
    if y < 18:
        return "an adolescent"
    if y < 30:
        return "a young adult"
    if y < 50:
        return "an adult"
    if y < 70:
        return "middle-aged"
    if y < 85:
        return "elderly"
    return "ancient"


# --------------------------------------------------------------------------- #
# Personality
# --------------------------------------------------------------------------- #

#: Written to follow a plural or first-person subject -- "they are a coward",
#: "I am a coward" -- because those two share every verb form and the singular
#: does not. These used to be third-person singular ("is a coward", "prefers
#: solitude") and the one thing that reads them prefixes "They ", so every
#: personality line in the game came out as "They has no vanity." or, where
#: the code stripped a leading "is", "They a coward."
_FACET_PHRASES: Dict[str, Tuple[str, str]] = {
    "bravery": ("are incredibly brave", "are a coward"),
    "cheer": ("are always in good spirits", "are given to dark moods"),
    "anxiety": ("are a nervous wreck", "are never anxious"),
    "anger": ("have a quick temper", "are slow to anger"),
    "greed": ("are very greedy", "have no interest in wealth"),
    "curiosity": ("have a boundless curiosity", "are incurious"),
    "friendliness": ("are warm and friendly", "are cold to others"),
    "pride": ("are immensely proud", "have no vanity"),
    "envy": ("are prone to envy", "never envy others"),
    "stubbornness": ("are incredibly stubborn", "are easily swayed"),
    "discipline": ("are highly disciplined", "lack all discipline"),
    "vengefulness": ("nurse grudges forever", "forgive readily"),
    "confidence": ("are supremely self-confident", "doubt everything"),
    "gregariousness": ("love a crowd", "prefer solitude"),
    "ambition": ("burn with ambition", "have no ambition"),
    "trust": ("trust others easily", "trust nobody"),
    "humour": ("find humour everywhere", "have no sense of humour"),
    "altruism": ("give freely to others", "look out only for themselves"),
    "hate_propensity": ("take an easy dislike to others", "rarely hate anyone"),
    "love_propensity": ("form deep attachments", "do not form attachments"),
    "cruelty": ("have a cruel streak", "cannot bear cruelty"),
    "perseverance": ("never give up", "abandon things easily"),
    "excitement_seeking": ("crave excitement", "avoid all excitement"),
    "imagination": ("have a vivid imagination", "are entirely literal-minded"),
    "swayed_by_emotions": ("are ruled by emotion", "are unmoved by emotion"),
    "activity_level": ("are always in motion", "are deeply sedentary"),
    "orderliness": ("keep everything in order", "live in disarray"),
    "politeness": ("are unfailingly polite", "are blunt to the point of rudeness"),
    "assertiveness": ("speak their mind forcefully", "avoid confrontation"),
    "tolerance": ("tolerate anything", "are deeply intolerant"),
}


def personality_desc(trait: str, value: int) -> str:
    """A sentence fragment for a personality facet, ``""`` when unremarkable."""
    phrases = _FACET_PHRASES.get(trait)
    if not phrases:
        return ""
    high, low = phrases
    if value >= 85:
        return high
    if value >= 70:
        return high.replace("incredibly ", "").replace("immensely ", "")
    if value <= 15:
        return low
    if value <= 30:
        return low
    return ""


# --------------------------------------------------------------------------- #
# General text helpers
# --------------------------------------------------------------------------- #

_NUMBER_WORDS = (
    "no", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve",
)


def number_word(n: int) -> str:
    """Small numbers as words, larger ones as digits."""
    if 0 <= n < len(_NUMBER_WORDS):
        return _NUMBER_WORDS[n]
    return str(n)


def indefinite_article(word: str) -> str:
    """``"a"`` or ``"an"`` for *word*."""
    if not word:
        return "a"
    first = word.lstrip("-+*=#@").lower()
    if not first:
        return "a"
    return "an" if first[0] in "aeiou" else "a"


def with_article(word: str) -> str:
    """Prefix a noun phrase with the right indefinite article."""
    return "%s %s" % (indefinite_article(word), word)


def capitalize_first(s: str) -> str:
    """Capitalise only the first character, leaving the rest alone."""
    if not s:
        return s
    return s[0].upper() + s[1:]


def list_join(items: Sequence[str], conjunction: str = "and") -> str:
    """``["a", "b", "c"] -> "a, b and c"``."""
    parts: List[str] = [p for p in items if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return "%s %s %s" % (parts[0], conjunction, parts[1])
    return "%s %s %s" % (", ".join(parts[:-1]), conjunction, parts[-1])


def pluralize(word: str, n: int) -> str:
    """Naive English pluralisation, good enough for item names."""
    if n == 1:
        return word
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith("f"):
        return word[:-1] + "ves"
    return word + "s"


def percent_desc(frac: float) -> str:
    """Coarse wording for a 0..1 fraction."""
    if frac >= 0.99:
        return "complete"
    if frac >= 0.75:
        return "nearly complete"
    if frac >= 0.5:
        return "well along"
    if frac >= 0.25:
        return "under way"
    if frac > 0.0:
        return "barely started"
    return "not started"
