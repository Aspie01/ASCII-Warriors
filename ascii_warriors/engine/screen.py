"""The off-screen character buffer everything draws into.

A :class:`Screen` holds three parallel flat lists (chars, foregrounds,
backgrounds). Every draw call clips silently, so callers never have to bounds
check. :mod:`ascii_warriors.engine.terminal` diffs two buffers to produce the
minimal escape-sequence stream.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple, Union

from . import colors
from .colors import Color

_DEFAULT_FG = colors.UI["fg"]
_DEFAULT_BG = colors.UI["bg"]


class Frag(NamedTuple):
    """A run of text in a single colour."""

    text: str
    color: Color = _DEFAULT_FG


#: Anything the text drawing helpers accept.
Markup = Union[str, Frag, Sequence[Frag]]

#: ``style -> (horizontal, vertical, tl, tr, bl, br)``
BOX_STYLES: Dict[str, Tuple[str, str, str, str, str, str]] = {
    "single": ("─", "│", "┌", "┐", "└", "┘"),
    "double": ("═", "║", "╔", "╗", "╚", "╝"),
    "heavy": ("━", "┃", "┏", "┓", "┗", "┛"),
    "ascii": ("-", "|", "+", "+", "+", "+"),
    "none": (" ", " ", " ", " ", " ", " "),
}


def _to_frags(s: Markup, default: Color) -> List[Frag]:
    """Normalise any Markup value into a list of :class:`Frag`."""
    if isinstance(s, str):
        return [Frag(s, default)] if s else []
    if isinstance(s, Frag):
        return [s] if s.text else []
    out: List[Frag] = []
    for part in s:
        if isinstance(part, Frag):
            if part.text:
                out.append(part)
        elif isinstance(part, str):
            if part:
                out.append(Frag(part, default))
        elif isinstance(part, (tuple, list)) and len(part) == 2:
            text, col = part
            if text:
                out.append(Frag(str(text), col))
    return out


def frags(*parts) -> List[Frag]:
    """Build a Frag list from strings and ``(text, colour)`` pairs.

    ``frags("hp ", ("12", colors.RED), "/20")``
    """
    out: List[Frag] = []
    for p in parts:
        if isinstance(p, Frag):
            out.append(p)
        elif isinstance(p, str):
            out.append(Frag(p, _DEFAULT_FG))
        elif isinstance(p, (tuple, list)) and len(p) == 2:
            out.append(Frag(str(p[0]), p[1]))
        elif p is None:
            continue
        else:
            out.append(Frag(str(p), _DEFAULT_FG))
    return [f for f in out if f.text]


def frag_len(s: Markup) -> int:
    """Total printable length of a Markup value."""
    if isinstance(s, str):
        return len(s)
    if isinstance(s, Frag):
        return len(s.text)
    return sum(len(f.text) if isinstance(f, Frag) else len(str(f)) for f in s)


def frag_str(s: Markup) -> str:
    """The plain text of a Markup value, colours discarded."""
    if isinstance(s, str):
        return s
    if isinstance(s, Frag):
        return s.text
    return "".join(f.text if isinstance(f, Frag) else str(f) for f in s)


def frag_slice(s: Markup, start: int, end: int) -> List[Frag]:
    """Slice a Markup value by printable column, preserving colours."""
    out: List[Frag] = []
    pos = 0
    for f in _to_frags(s, _DEFAULT_FG):
        n = len(f.text)
        seg_start = max(start, pos)
        seg_end = min(end, pos + n)
        if seg_end > seg_start:
            out.append(Frag(f.text[seg_start - pos:seg_end - pos], f.color))
        pos += n
        if pos >= end:
            break
    return out


def wrap(s: str, width: int) -> List[str]:
    """Word-wrap plain text, breaking over-long words."""
    if width <= 0:
        return []
    lines: List[str] = []
    for para in s.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for word in para.split(" "):
            if not word:
                continue
            while len(word) > width:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:width])
                word = word[width:]
            if not cur:
                cur = word
            elif len(cur) + 1 + len(word) <= width:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
    return lines


_NEWLINE = object()


def _tokenize(parts: Sequence[Frag]) -> List[object]:
    """Split fragments into word tokens and explicit newline markers."""
    tokens: List[object] = []
    for frag in parts:
        chunks = frag.text.split("\n")
        for ci, chunk in enumerate(chunks):
            if ci:
                tokens.append(_NEWLINE)
            for word in chunk.split(" "):
                if word:
                    tokens.append(Frag(word, frag.color))
    return tokens


def wrap_frags(s: Markup, width: int) -> List[List[Frag]]:
    """Word-wrap Markup, keeping each word's colour intact."""
    if width <= 0:
        return []
    tokens = _tokenize(_to_frags(s, _DEFAULT_FG))
    lines: List[List[Frag]] = []
    cur: List[Frag] = []
    cur_len = 0

    def flush() -> None:
        nonlocal cur, cur_len
        lines.append(cur)
        cur = []
        cur_len = 0

    for token in tokens:
        if token is _NEWLINE:
            flush()
            continue
        assert isinstance(token, Frag)
        word, col = token.text, token.color
        while len(word) > width:
            if cur_len:
                flush()
            cur.append(Frag(word[:width], col))
            cur_len = width
            flush()
            word = word[width:]
        if not word:
            continue
        if cur_len and cur_len + 1 + len(word) > width:
            flush()
        if cur_len:
            cur.append(Frag(" ", col))
            cur_len += 1
        cur.append(Frag(word, col))
        cur_len += len(word)
    if cur or not lines:
        lines.append(cur)
    return lines


def parse_markup(
    s: str,
    default_color: Color = _DEFAULT_FG,
    palette: Optional[Dict[str, Color]] = None,
) -> List[Frag]:
    """Parse inline tags like ``"{red}danger{/}"`` into coloured fragments."""
    out: List[Frag] = []
    stack: List[Color] = [default_color]
    buf: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "{":
            close = s.find("}", i + 1)
            if close == -1:
                buf.append(ch)
                i += 1
                continue
            tag = s[i + 1:close]
            if buf:
                out.append(Frag("".join(buf), stack[-1]))
                buf = []
            if tag == "/":
                if len(stack) > 1:
                    stack.pop()
            else:
                col = None
                if palette and tag in palette:
                    col = palette[tag]
                else:
                    col = colors.ansi_name_to_color(tag)
                stack.append(col)
            i = close + 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        out.append(Frag("".join(buf), stack[-1]))
    return out


class Screen:
    """A width x height grid of coloured characters."""

    __slots__ = ("width", "height", "chars", "fgs", "bgs", "ascii_only", "dirty")

    def __init__(self, width: int, height: int) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        n = self.width * self.height
        self.chars: List[str] = [" "] * n
        self.fgs: List[Color] = [_DEFAULT_FG] * n
        self.bgs: List[Color] = [_DEFAULT_BG] * n
        #: When true every box style degrades to ``+ - |``.
        self.ascii_only = True
        self.dirty = False

    # -- lifecycle --------------------------------------------------------- #

    def resize(self, width: int, height: int) -> None:
        """Resize and clear the buffer."""
        self.width = max(1, int(width))
        self.height = max(1, int(height))
        n = self.width * self.height
        self.chars = [" "] * n
        self.fgs = [_DEFAULT_FG] * n
        self.bgs = [_DEFAULT_BG] * n
        self.dirty = True

    def clear(self, bg: Color = _DEFAULT_BG, ch: str = " ") -> None:
        """Reset every cell to *ch* on *bg*."""
        n = self.width * self.height
        self.chars = [ch] * n
        self.fgs = [_DEFAULT_FG] * n
        self.bgs = [bg] * n
        self.dirty = False

    # -- cell access ------------------------------------------------------- #

    def put(
        self,
        x: int,
        y: int,
        ch: str,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
    ) -> None:
        """Write a single character, clipping silently."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height or not ch:
            return
        i = y * self.width + x
        self.chars[i] = ch[0]
        self.fgs[i] = fg
        if bg is not None:
            self.bgs[i] = bg
        self.dirty = True

    def get(self, x: int, y: int) -> Tuple[str, Color, Color]:
        """Read a cell as ``(char, fg, bg)``; out-of-range reads return a blank."""
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return (" ", _DEFAULT_FG, _DEFAULT_BG)
        i = y * self.width + x
        return (self.chars[i], self.fgs[i], self.bgs[i])

    # -- text -------------------------------------------------------------- #

    def text(
        self,
        x: int,
        y: int,
        s: Markup,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
        max_width: Optional[int] = None,
    ) -> int:
        """Draw one line of Markup; returns the number of columns written."""
        if y < 0 or y >= self.height:
            return 0
        parts = _to_frags(s, fg)
        if not parts:
            return 0
        limit = self.width - x if max_width is None else min(max_width, self.width - x)
        if limit <= 0:
            return 0
        written = 0
        cx = x
        w, chars, fgs, bgs = self.width, self.chars, self.fgs, self.bgs
        row = y * w
        for frag in parts:
            col = frag.color
            for ch in frag.text:
                if written >= limit:
                    self.dirty = True
                    return written
                if 0 <= cx < w:
                    i = row + cx
                    chars[i] = ch
                    fgs[i] = col
                    if bg is not None:
                        bgs[i] = bg
                cx += 1
                written += 1
        self.dirty = True
        return written

    def text_center(
        self,
        y: int,
        s: Markup,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
        x0: int = 0,
        w: Optional[int] = None,
    ) -> None:
        """Draw text horizontally centred inside ``[x0, x0+w)``."""
        width = self.width if w is None else w
        x = x0 + max(0, (width - frag_len(s)) // 2)
        self.text(x, y, s, fg, bg, max_width=width)

    def text_right(
        self,
        x: int,
        y: int,
        s: Markup,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
    ) -> None:
        """Draw text ending at column *x* (inclusive)."""
        self.text(x - frag_len(s) + 1, y, s, fg, bg)

    def wrapped(
        self,
        x: int,
        y: int,
        w: int,
        s: Markup,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
        max_lines: Optional[int] = None,
    ) -> int:
        """Word-wrap Markup into a column; returns the number of rows used."""
        if w <= 0:
            return 0
        lines = wrap_frags(_to_frags(s, fg), w)
        if max_lines is not None:
            lines = lines[:max_lines]
        for i, ln in enumerate(lines):
            self.text(x, y + i, ln, fg, bg, max_width=w)
        return len(lines)

    # -- shapes ------------------------------------------------------------ #

    def fill(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        ch: str = " ",
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
    ) -> None:
        """Fill a rectangle, clipping to the buffer."""
        if w <= 0 or h <= 0:
            return
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        c = ch[0] if ch else " "
        for yy in range(y0, y1):
            row = yy * self.width
            for xx in range(x0, x1):
                i = row + xx
                self.chars[i] = c
                self.fgs[i] = fg
                if bg is not None:
                    self.bgs[i] = bg
        self.dirty = True

    def hline(
        self, x: int, y: int, w: int, ch: str = "-",
        fg: Color = _DEFAULT_FG, bg: Optional[Color] = None,
    ) -> None:
        """A horizontal rule."""
        self.fill(x, y, w, 1, ch, fg, bg)

    def vline(
        self, x: int, y: int, h: int, ch: str = "|",
        fg: Color = _DEFAULT_FG, bg: Optional[Color] = None,
    ) -> None:
        """A vertical rule."""
        self.fill(x, y, 1, h, ch, fg, bg)

    def frame(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        title: Optional[Markup] = None,
        fg: Color = None,  # type: ignore[assignment]
        bg: Optional[Color] = None,
        style: str = "single",
        title_fg: Optional[Color] = None,
    ) -> None:
        """Draw a box, optionally with a centred title in the top edge."""
        if w < 2 or h < 2:
            return
        if fg is None:
            fg = colors.UI["frame"]
        chars = BOX_STYLES.get(style, BOX_STYLES["single"])
        if self.ascii_only or style == "ascii":
            chars = BOX_STYLES["ascii"] if style != "none" else BOX_STYLES["none"]
        hor, ver, tl, tr, bl, br = chars

        self.hline(x + 1, y, w - 2, hor, fg, bg)
        self.hline(x + 1, y + h - 1, w - 2, hor, fg, bg)
        self.vline(x, y + 1, h - 2, ver, fg, bg)
        self.vline(x + w - 1, y + 1, h - 2, ver, fg, bg)
        self.put(x, y, tl, fg, bg)
        self.put(x + w - 1, y, tr, fg, bg)
        self.put(x, y + h - 1, bl, fg, bg)
        self.put(x + w - 1, y + h - 1, br, fg, bg)

        if title is not None and frag_len(title) and w > 6:
            tl_len = min(frag_len(title), w - 6)
            tx = x + (w - tl_len - 2) // 2
            tcol = title_fg if title_fg is not None else colors.UI["title"]
            self.text(tx, y, " ", tcol, bg)
            self.text(tx + 1, y, frag_slice(title, 0, tl_len), tcol, bg)
            self.text(tx + 1 + tl_len, y, " ", tcol, bg)

    def shade(self, x: int, y: int, w: int, h: int, factor: float) -> None:
        """Darken existing cells in a rectangle toward black."""
        if w <= 0 or h <= 0:
            return
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        for yy in range(y0, y1):
            row = yy * self.width
            for xx in range(x0, x1):
                i = row + xx
                self.fgs[i] = colors.darken(self.fgs[i], factor)
                self.bgs[i] = colors.darken(self.bgs[i], factor)
        self.dirty = True

    def box_shadow(self, x: int, y: int, w: int, h: int) -> None:
        """Dim a one-cell border to the right of and below a box."""
        for yy in range(y + 1, y + h + 1):
            self._dim_cell(x + w, yy)
        for xx in range(x + 1, x + w + 1):
            self._dim_cell(xx, y + h)

    def _dim_cell(self, x: int, y: int) -> None:
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        i = y * self.width + x
        self.fgs[i] = colors.darken(self.fgs[i], 0.35)
        self.bgs[i] = colors.darken(self.bgs[i], 0.35)
        self.dirty = True

    def progress(
        self,
        x: int,
        y: int,
        w: int,
        frac: float,
        fg: Color = _DEFAULT_FG,
        bg: Optional[Color] = None,
        ch: str = "=",
    ) -> None:
        """A simple filled bar primitive."""
        if w <= 0:
            return
        frac = max(0.0, min(1.0, frac))
        filled = int(round(frac * w))
        self.fill(x, y, filled, 1, ch, fg, bg)
        self.fill(x + filled, y, w - filled, 1, " ", colors.UI["dim"], bg)

    # -- composition ------------------------------------------------------- #

    def blit(self, other: "Screen", x: int, y: int) -> None:
        """Copy another screen into this one at ``(x, y)``, clipping."""
        for sy in range(other.height):
            ty = y + sy
            if ty < 0 or ty >= self.height:
                continue
            src = sy * other.width
            dst = ty * self.width
            for sx in range(other.width):
                tx = x + sx
                if tx < 0 or tx >= self.width:
                    continue
                self.chars[dst + tx] = other.chars[src + sx]
                self.fgs[dst + tx] = other.fgs[src + sx]
                self.bgs[dst + tx] = other.bgs[src + sx]
        self.dirty = True

    def sub(self, x: int, y: int, w: int, h: int) -> "Screen":
        """Extract a rectangular region as a new screen."""
        out = Screen(max(1, w), max(1, h))
        out.ascii_only = self.ascii_only
        for yy in range(out.height):
            for xx in range(out.width):
                ch, fg, bg = self.get(x + xx, y + yy)
                out.put(xx, yy, ch, fg, bg)
        return out

    def snapshot(self) -> "Screen":
        """A deep copy of this screen."""
        out = Screen(self.width, self.height)
        out.chars = list(self.chars)
        out.fgs = list(self.fgs)
        out.bgs = list(self.bgs)
        out.ascii_only = self.ascii_only
        return out

    def to_text(self) -> List[str]:
        """Plain-text rows, for tests and headless rendering."""
        w = self.width
        return [
            "".join(self.chars[row * w:(row + 1) * w]) for row in range(self.height)
        ]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Screen(%dx%d)" % (self.width, self.height)
