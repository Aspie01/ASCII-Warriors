"""Books: what is written in them, and what reading one does to you.

There has been a scholar class since character creation was written --
knowledge 6, reading 5, writing 4, diagnose 3 -- and every one of those skills
did nothing at all. There has been a `book` item with a BOOK flag and a value
of 200 that was pure inventory weight. Towers and towns have generated rooms
called "library" that were four pieces of furniture. A whole way of playing
was described in the data files and never implemented, exactly as stealth was
before v3.6.

A book here is not flavour text. It is *about* something that actually
happened in this world -- a battle, a beast, a nation, a person, an artifact --
and reading it hands you the thing the world already knows: the legends entry.
That makes reading a real alternative to walking three hundred miles to find
out, which is what a library is for.

And a few of them are not books. A slab in a necromancer's tower is the
secret of raising the dead, written down. Reading it makes v3.5's necromancy
yours: the machinery there already takes any creature and any world, so the
player becomes a necromancer with no special case anywhere.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

#: Kinds of book, what each is about, and the skill that gets better for
#: having read it. ``None`` means the book teaches knowledge and nothing else.
SUBJECTS: Tuple[Tuple[str, str, Optional[str]], ...] = (
    ("history", "the history of %s", None),
    ("biography", "the life of %s", None),
    ("beast", "the beast %s", "knowledge"),
    ("battle", "the battle at %s", "fighter"),
    ("craft", "the making of %s", "crafting"),
    ("medicine", "the treatment of wounds", "diagnose"),
    ("surgery", "the cutting of flesh", "surgery"),
    ("smithing", "the working of metal", "smithing"),
    ("swordsmanship", "the sword", "sword"),
    ("herbs", "the plants of the world", "herbalism"),
    ("engineering", "levers, gears and water", "mechanics"),
    ("poetry", "verse", "poetry"),
)

#: What a slab teaches. There is only one secret so far and it is the one the
#: game already has the machinery for.
SECRETS: Dict[str, str] = {
    "necromancy": "the secret of life and death",
}

#: Turns of reading per point of a book's depth, before the reader's skill.
READ_TURNS = 40

#: A book cannot push a skill past this on its own. You can read about the
#: sword all winter; at some point somebody has to swing one at you.
BOOK_SKILL_CAP = 6

#: What a book's depth is worth, as a multiplier on the plain item. A great
#: tome is worth three of a pamphlet, which is what makes a library a target.
DEPTH_VALUE = (1.0, 1.4, 1.9, 2.5, 3.2)


class Book:
    """One written work, and what is in it.

    Stored on the item rather than in a registry, because a book that leaves
    the world with the adventurer carrying it should still say what it says.
    """

    __slots__ = ("kind", "title", "subject", "depth", "skill", "author",
                 "event_ids", "figure_id", "site_id", "civ_id", "artifact_id",
                 "secret", "read_by")

    def __init__(self, kind: str = "history", title: str = "",
                 subject: str = "", depth: int = 1) -> None:
        self.kind = kind
        self.title = title
        #: What the spine says it is about, in words.
        self.subject = subject
        #: How much is in it: reading time, value, and how much it teaches.
        self.depth = depth
        self.skill: Optional[str] = None
        self.author = ""
        #: What in the world's history this book actually covers.
        self.event_ids: List[int] = []
        self.figure_id: Optional[int] = None
        self.site_id: Optional[int] = None
        self.civ_id: Optional[int] = None
        self.artifact_id: Optional[int] = None
        #: Set on a slab rather than a book.
        self.secret = ""
        #: Ids of creatures that have finished it. A second reading of the
        #: same book teaches nothing, which is what makes a library worth
        #: more than one very good book.
        self.read_by: List[int] = []

    @property
    def is_slab(self) -> bool:
        """Whether this is a secret rather than a book."""
        return bool(self.secret)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the work."""
        return {"kind": self.kind, "title": self.title, "subject": self.subject,
                "depth": self.depth, "skill": self.skill, "author": self.author,
                "events": self.event_ids, "figure": self.figure_id,
                "site": self.site_id, "civ": self.civ_id,
                "artifact": self.artifact_id, "secret": self.secret,
                "read": self.read_by}

    @classmethod
    def from_dict(cls, d) -> "Book":
        """Rebuild from :meth:`to_dict`."""
        b = cls(str(d.get("kind", "history")), str(d.get("title", "")),
                str(d.get("subject", "")), int(d.get("depth", 1)))
        b.skill = d.get("skill")
        b.author = str(d.get("author", ""))
        b.event_ids = [int(e) for e in d.get("events", [])]
        b.figure_id = d.get("figure")
        b.site_id = d.get("site")
        b.civ_id = d.get("civ")
        b.artifact_id = d.get("artifact")
        b.secret = str(d.get("secret", ""))
        b.read_by = [int(i) for i in d.get("read", [])]
        return b


# --------------------------------------------------------------------------- #
# Writing them
# --------------------------------------------------------------------------- #


def of(item) -> Optional[Book]:
    """The work bound into an item, or ``None`` if it is not one.

    Kept in the item's own ``flags`` dict rather than as an attribute, because
    Item has ``__slots__`` and because flags already serialise -- which means a
    book keeps what is written in it across a save for free.
    """
    raw = item.flags.get("book")
    if raw is None:
        return None
    if isinstance(raw, Book):
        return raw
    book = Book.from_dict(raw)
    item.flags["book"] = book
    return book


def make_book(world, rng, *, kind: str = "", depth: int = 0,
              author: str = "") -> Book:
    """Write a book about something that actually happened in this world.

    Every book points at real history. A book about nothing is a prop; a book
    about the battle at a place you can walk to is a reason to read.
    """
    choices = [s for s in SUBJECTS if not kind or s[0] == kind]
    entry = rng.choice(choices or list(SUBJECTS))
    book = Book(entry[0], depth=depth or rng.randint(1, 5))
    book.skill = entry[2]
    book.author = author
    _bind_subject(world, rng, book, entry[1])
    book.title = _title(rng, book)
    return book


def _bind_subject(world, rng, book: Book, pattern: str) -> None:
    """Point the book at a real thing, and fall back to a general treatise."""
    if book.kind == "biography":
        figures = [f for f in world.figures.values() if f.titles or f.flags]
        if figures:
            fig = rng.choice(figures)
            book.figure_id = fig.id
            book.subject = pattern % fig.display_name
            book.event_ids = [e.id for e in world.events
                              if fig.id in e.figures][:8]
            return
    elif book.kind == "history":
        civs = [c for c in world.civs]
        if civs:
            civ = rng.choice(civs)
            book.civ_id = civ.id
            book.subject = pattern % civ.name
            book.event_ids = [e.id for e in world.events
                              if civ.id in e.civs][:8]
            return
    elif book.kind == "battle":
        sites = [s for s in world.sites]
        battles = [e for e in world.events if e.kind == "battle"]
        if battles:
            ev = rng.choice(battles)
            book.event_ids = [ev.id]
            if ev.sites:
                book.site_id = ev.sites[0]
            site = world.site(book.site_id) if book.site_id else None
            book.subject = pattern % (site.name if site is not None
                                      else "a forgotten place")
            return
        if sites:
            site = rng.choice(sites)
            book.site_id = site.id
            book.subject = pattern % site.name
            return
    elif book.kind == "beast":
        beasts = [f for f in world.figures.values() if "monster" in f.flags]
        if beasts:
            beast = rng.choice(beasts)
            book.figure_id = beast.id
            book.subject = pattern % beast.display_name
            book.event_ids = [e.id for e in world.events
                              if beast.id in e.figures][:8]
            return
    elif book.kind == "craft":
        if world.artifacts:
            art = rng.choice(list(world.artifacts))
            book.artifact_id = art.id
            book.subject = pattern % art.name
            return
    # A general treatise: no subject in the world, just the subject itself.
    book.subject = pattern if "%s" not in pattern else pattern % "many things"


def _title(rng, book: Book) -> str:
    """A title in the shape a dwarf would give one."""
    if book.is_slab:
        return _title_case(SECRETS.get(book.secret, "a secret"))
    forms = (
        "On %s", "A Treatise Concerning %s", "The Book of %s",
        "Notes Upon %s", "Of %s",
    )
    return rng.choice(forms) % _title_case(book.subject)


def _title_case(text: str) -> str:
    """Title Case, leaving the small words alone."""
    small = {"of", "the", "at", "a", "and", "in", "upon", "concerning"}
    words = text.split()
    return " ".join(w if w in small and i else w.capitalize()
                    for i, w in enumerate(words))


def make_slab(rng, secret: str = "necromancy") -> Book:
    """A slab: one secret, cut into stone by somebody who should not have."""
    book = Book("slab", depth=5)
    book.secret = secret
    book.subject = SECRETS.get(secret, "something better left alone")
    book.title = _title(rng, book)
    return book


def bind(world, rng, item, *, kind: str = "", depth: int = 0,
         author: str = "") -> Book:
    """Attach a freshly written work to a book item, and price it."""
    book = make_book(world, rng, kind=kind, depth=depth, author=author)
    return attach(item, book)


def attach(item, book: Book) -> Book:
    """Put an existing work into an item and give it the title as its name."""
    item.flags["book"] = book
    item.name_override = book.title
    return book


# --------------------------------------------------------------------------- #
# Writing them
# --------------------------------------------------------------------------- #
#
# `writing` is in the skill table and the scholar profession starts with 4 of
# it. Nothing had ever read it: books existed only because worldgen had made
# them, and an adventurer who had killed a hydra and learned the secret of
# life and death could not write any of it down.

#: A book cannot be deeper than the writer is skilled, whatever they know.
#: A brilliant surgeon who cannot write produces a pamphlet.
MAX_DEPTH = 5

#: How much of a subject you have to know before you can write about it.
KNOWS_ENOUGH = 3

#: Turns per point of depth. Writing is much slower than reading, which is
#: why nobody does it in a corridor with goblins in it.
WRITE_TURNS = 260


def writable(item) -> bool:
    """A blank book, waiting for somebody to fill it."""
    return item is not None and item.defn.has("BOOK") and of(item) is None


def can_write(writer) -> bool:
    """Whether this creature could write a book at all."""
    return can_read(writer) and writer.skills.level("writing") > 0


def subjects_for(writer) -> List[Tuple[str, str]]:
    """What this writer is qualified to write about, best first.

    A book has to be about something you know. `history` and `biography`
    teach no skill and are open to anybody literate -- you were there, or you
    heard it from somebody who was.
    """
    out: List[Tuple[str, str]] = []
    for kind, phrase, skill in SUBJECTS:
        if skill is None:
            out.append((kind, phrase))
            continue
        if writer.skills.level(skill) >= KNOWS_ENOUGH:
            out.append((kind, phrase))
    return out


def write_depth(writer, kind: str) -> int:
    """How deep a work this writer can produce on this subject."""
    craft = writer.skills.level("writing")
    entry = next((s for s in SUBJECTS if s[0] == kind), None)
    known = writer.skills.level(entry[2]) if entry and entry[2] else craft
    return max(1, min(MAX_DEPTH, (craft + known) // 3))


def write_turns(writer, kind: str) -> int:
    """How long it takes. Deeper work is longer work."""
    return WRITE_TURNS * write_depth(writer, kind)


def write(world, rng, writer, item, kind: str) -> Tuple[Optional[Book], str]:
    """Fill a blank book. Returns the work and what to tell the writer."""
    if not writable(item):
        return (None, "There is already something written in that.")
    if not can_write(writer):
        return (None, "You do not know how to set words down.")
    if kind not in {k for k, _p in subjects_for(writer)}:
        return (None, "You do not know enough about that to fill a book.")
    book = bind(world, rng, item, kind=kind,
                depth=write_depth(writer, kind),
                author=writer.display_name())
    # You have read your own book. It would be strange to learn from it.
    book.read_by.append(writer.id)
    writer.add_exp("writing", 40 * book.depth)
    return (book, "You finish %s." % book.title)


# --------------------------------------------------------------------------- #
# Reading them
# --------------------------------------------------------------------------- #


def read_turns(reader, book: Book) -> int:
    """How long this reader takes to get through this book.

    A slow reader with a deep book loses most of a day to it, which is the
    cost that makes a library somewhere safe worth having.
    """
    skill = max(0, reader.skills.level("reading"))
    speed = 1.0 + skill * 0.18
    return max(10, int(READ_TURNS * book.depth / speed))


def can_read(reader) -> bool:
    """Whether this creature can read at all."""
    return reader.body.can_see() and reader.defn.intelligent


def already_read(reader, book: Book) -> bool:
    """Whether this reader has finished this work before."""
    return reader.id in book.read_by


def read(world, reader, book: Book) -> List[str]:
    """Read a work through. Returns the lines to show the reader.

    Everything a book does happens here: the legends it opens, the skill it
    nudges, and the secret it may carry. Re-reading teaches nothing, which is
    why a library beats one very good book.
    """
    lines: List[str] = []
    if already_read(reader, book):
        return ["You have read this before. There is nothing new in it."]
    book.read_by.append(reader.id)

    reader.add_exp("reading", 30 * book.depth)
    reader.add_exp("knowledge", 20 * book.depth)
    reader.add_exp("concentration", 10 * book.depth)

    if book.is_slab:
        lines.extend(_learn_secret(world, reader, book))
        return lines

    learned = discover(world, book)
    if learned:
        lines.append("You learn of %s." % book.subject)
        lines.extend("  " + t for t in learned[:6])
    else:
        lines.append("You read about %s. You knew most of it." % book.subject)

    if book.skill:
        gained = _teach(reader, book)
        if gained:
            lines.append(gained)
    return lines


def _teach(reader, book: Book) -> str:
    """Nudge the skill a book covers, up to the cap a book can reach."""
    skill = book.skill
    level = reader.skills.level(skill)
    if level >= BOOK_SKILL_CAP:
        return "You already know more of this than the author did."
    reader.add_exp(skill, 120 * book.depth)
    if reader.skills.level(skill) > level:
        from .skills import SKILLS

        return "Your %s has improved." % SKILLS[skill].name.lower()
    return ""


def _learn_secret(world, reader, book: Book) -> List[str]:
    """Take a secret off a slab, if the reader can stand to.

    Necromancy is not a skill, it is a fact about you afterwards. The
    machinery in `night` already asks whether a creature is a necromancer
    rather than whether it is *the* necromancer, so the player becomes one
    with no special case anywhere.
    """
    secrets = getattr(reader, "secrets", None)
    if secrets is None:
        secrets = reader.secrets = []
    if book.secret in secrets:
        return ["You already know what is written here."]
    secrets.append(book.secret)
    if book.secret == "necromancy":
        reader.profession = reader.profession or "necromancer"
        return [
            "The letters move as you read them.",
            "You understand. Death is a door and you have the key.",
            "You can raise the dead.",
        ]
    return ["You have learned %s." % SECRETS.get(book.secret, "something")]


def knows_secret(creature, secret: str = "necromancy") -> bool:
    """Whether this creature has read that particular slab."""
    return secret in (getattr(creature, "secrets", None) or ())


def _world_of(thing):
    """The World, given a World, a Game or a Fortress.

    Reading happens in both modes and the caller should not have to know which
    kind of thing it is holding.
    """
    return getattr(thing, "world", None) or thing


def discover(where, book: Book) -> List[str]:
    """Reveal what a book covers, and return the newly learned lines.

    The world already keeps a history nobody has any way to read without
    walking to it. A book is that way.
    """
    world = _world_of(where)
    known = getattr(world, "known_events", None)
    if known is None:
        known = world.known_events = set()
    out = []
    for eid in book.event_ids:
        if eid in known:
            continue
        ev = _event(world, eid)
        if ev is None:
            continue
        known.add(eid)
        out.append("%d: %s" % (ev.year, ev.text))
    return out


def _event(world, eid: int):
    """One historical event by id."""
    for ev in world.events:
        if ev.id == eid:
            return ev
    return None


def value_of(item) -> int:
    """What a written work is worth, over and above the leather it is bound in."""
    book = of(item)
    if book is None:
        return item.value
    scale = DEPTH_VALUE[max(0, min(len(DEPTH_VALUE) - 1, book.depth - 1))]
    return max(1, int(item.value * scale))


def summary(book: Book) -> str:
    """One line for an inventory or a shelf."""
    depth = ("a pamphlet", "a slim volume", "a book", "a thick volume",
             "a great tome")[max(0, min(4, book.depth - 1))]
    if book.is_slab:
        return "A stone slab. Something is cut into it."
    who = " by %s" % book.author if book.author else ""
    return "%s on %s%s." % (depth.capitalize(), book.subject, who)
