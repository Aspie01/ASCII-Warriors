"""The message log.

Messages are lists of coloured fragments so combat can highlight the bits that
matter. Repeats collapse into a single line with a counter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..engine import colors
from ..engine.screen import Frag, Markup, frag_str

#: Message kind -> default colour.
KIND_COLORS: Dict[str, Any] = {
    "info": colors.UI["fg"],
    "combat": colors.Color(214, 152, 120),
    "warn": colors.UI["warn"],
    "good": colors.UI["good"],
    "bad": colors.UI["danger"],
    "social": colors.UI["accent2"],
    "system": colors.UI["dim"],
}


def _normalise(text: Markup, default_color) -> List[Frag]:
    """Coerce any Markup into a fragment list."""
    if isinstance(text, str):
        return [Frag(text, default_color)]
    if isinstance(text, Frag):
        return [text]
    out: List[Frag] = []
    for part in text:
        if isinstance(part, Frag):
            out.append(part)
        elif isinstance(part, str):
            out.append(Frag(part, default_color))
        elif isinstance(part, (tuple, list)) and len(part) == 2:
            out.append(Frag(str(part[0]), part[1]))
    return out


class Message:
    """A single log entry."""

    __slots__ = ("frags", "turn", "count", "kind")

    def __init__(self, frags: List[Frag], turn: int, kind: str = "info") -> None:
        self.frags = frags
        self.turn = turn
        self.count = 1
        self.kind = kind

    @property
    def text(self) -> str:
        """The plain text of the message, with any repeat counter."""
        base = frag_str(self.frags)
        return base if self.count <= 1 else "%s (x%d)" % (base, self.count)

    def display(self) -> List[Frag]:
        """Fragments to draw, including the repeat counter."""
        if self.count <= 1:
            return self.frags
        return list(self.frags) + [Frag(" (x%d)" % self.count, colors.UI["dim"])]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise text, colours, turn and kind."""
        return {
            "frags": [[f.text, list(f.color)] for f in self.frags],
            "turn": self.turn,
            "count": self.count,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "Message":
        """Rebuild from :meth:`to_dict`."""
        frags = [
            Frag(t, colors.Color(*c)) for t, c in d.get("frags", [])
        ]
        m = cls(frags, int(d.get("turn", 0)), str(d.get("kind", "info")))
        m.count = int(d.get("count", 1))
        return m

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Message(%r)" % self.text


class MessageLog:
    """A capped, de-duplicating scrollback of game messages."""

    def __init__(self, capacity: int = 2000) -> None:
        self.capacity = max(50, capacity)
        self.messages: List[Message] = []
        #: How many messages have arrived since the player last looked.
        self.new_count = 0
        self.turn = 0

    # -- writing ----------------------------------------------------------- #

    def add(self, text: Markup, kind: str = "info") -> None:
        """Append a message, collapsing an immediate repeat."""
        frags = _normalise(text, KIND_COLORS.get(kind, colors.UI["fg"]))
        if not frags or not frag_str(frags).strip():
            return
        if self.messages:
            last = self.messages[-1]
            if last.kind == kind and frag_str(last.frags) == frag_str(frags):
                last.count += 1
                last.turn = self.turn
                self.new_count += 1
                return
        self.messages.append(Message(frags, self.turn, kind))
        self.new_count += 1
        if len(self.messages) > self.capacity:
            del self.messages[: len(self.messages) - self.capacity]

    def info(self, text: Markup) -> None:
        """Ordinary message."""
        self.add(text, "info")

    def combat(self, text: Markup) -> None:
        """Combat message."""
        self.add(text, "combat")

    def warn(self, text: Markup) -> None:
        """Something to pay attention to."""
        self.add(text, "warn")

    def good(self, text: Markup) -> None:
        """Something went well."""
        self.add(text, "good")

    def bad(self, text: Markup) -> None:
        """Something went badly."""
        self.add(text, "bad")

    def social(self, text: Markup) -> None:
        """Speech and social interaction."""
        self.add(text, "social")

    def system(self, text: Markup) -> None:
        """Out-of-world notice (saving, settings)."""
        self.add(text, "system")

    def extend(self, texts: Sequence[Markup], kind: str = "info") -> None:
        """Append several messages of the same kind."""
        for t in texts:
            self.add(t, kind)

    # -- reading ----------------------------------------------------------- #

    def recent(self, n: int) -> List[Message]:
        """The last *n* messages, oldest first."""
        return self.messages[-n:] if n > 0 else []

    def all(self) -> List[Message]:
        """Every retained message."""
        return list(self.messages)

    def since_turn(self, turn: int) -> List[Message]:
        """Every message logged on or after *turn*."""
        return [m for m in self.messages if m.turn >= turn]

    def clear_new(self) -> None:
        """Mark everything as read."""
        self.new_count = 0

    def clear(self) -> None:
        """Discard the whole log."""
        self.messages.clear()
        self.new_count = 0

    # -- serialisation ----------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the last 400 messages."""
        return {
            "capacity": self.capacity,
            "turn": self.turn,
            "messages": [m.to_dict() for m in self.messages[-400:]],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "MessageLog":
        """Rebuild from :meth:`to_dict`."""
        log = cls(int(d.get("capacity", 2000)))
        log.turn = int(d.get("turn", 0))
        log.messages = [Message.from_dict(m) for m in d.get("messages", [])]
        return log

    def __len__(self) -> int:
        return len(self.messages)
