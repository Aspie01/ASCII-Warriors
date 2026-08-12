"""Reusable UI pieces: menus, gauges, prompts and modal dialogs."""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple

from . import colors, keys
from .colors import Color
from .screen import Frag, Markup, Screen, frag_len, frag_slice, frag_str, wrap_frags


class MenuItem:
    """One row in a :class:`ListMenu`."""

    __slots__ = ("label", "value", "hotkey", "desc", "enabled", "group")

    def __init__(
        self,
        label: Markup,
        value: Any = None,
        *,
        hotkey: Optional[str] = None,
        desc: Markup = "",
        enabled: bool = True,
        group: Optional[str] = None,
    ) -> None:
        self.label = label
        self.value = value if value is not None else frag_str(label)
        self.hotkey = hotkey
        self.desc = desc
        self.enabled = enabled
        #: When set, this row is a non-selectable group header.
        self.group = group

    @property
    def is_header(self) -> bool:
        """True for non-selectable group headings."""
        return self.group is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "MenuItem(%r)" % frag_str(self.label)


def header(title: str) -> MenuItem:
    """A non-selectable group heading row."""
    return MenuItem(title, None, enabled=False, group=title)


_HOTKEY_POOL = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


class ListMenu:
    """A scrolling, hotkey-driven selection list."""

    def __init__(
        self,
        items: Sequence[MenuItem],
        *,
        per_page: int = 20,
        wrap_around: bool = True,
        auto_hotkeys: bool = True,
    ) -> None:
        self.items: List[MenuItem] = list(items)
        self.per_page = max(1, per_page)
        self.wrap_around = wrap_around
        self.auto_hotkeys = auto_hotkeys
        self.index = 0
        self.offset = 0
        self.filter = ""
        if auto_hotkeys:
            self._assign_hotkeys()
        self._snap_to_selectable(1)

    # -- setup ------------------------------------------------------------- #

    def _assign_hotkeys(self) -> None:
        used = {it.hotkey for it in self.items if it.hotkey}
        pool = [c for c in _HOTKEY_POOL if c not in used]
        pi = 0
        for it in self.items:
            if it.is_header or it.hotkey:
                continue
            if pi < len(pool):
                it.hotkey = pool[pi]
                pi += 1

    def set_items(self, items: Sequence[MenuItem]) -> None:
        """Replace the contents, resetting the cursor."""
        self.items = list(items)
        if self.auto_hotkeys:
            self._assign_hotkeys()
        self.index = 0
        self.offset = 0
        self._snap_to_selectable(1)

    def set_filter(self, text: str) -> None:
        """Only show rows whose label contains *text* (case-insensitive)."""
        self.filter = text.lower()
        self.index = 0
        self.offset = 0
        self._snap_to_selectable(1)

    # -- state ------------------------------------------------------------- #

    def visible_items(self) -> List[MenuItem]:
        """Rows passing the current filter."""
        if not self.filter:
            return self.items
        out: List[MenuItem] = []
        for it in self.items:
            if it.is_header or self.filter in frag_str(it.label).lower():
                out.append(it)
        return out

    @property
    def selected(self) -> Optional[MenuItem]:
        """The highlighted row, or ``None``."""
        vis = self.visible_items()
        if 0 <= self.index < len(vis):
            it = vis[self.index]
            return None if it.is_header else it
        return None

    @property
    def selected_value(self) -> Any:
        """The highlighted row's value, or ``None``."""
        it = self.selected
        return it.value if it else None

    def index_of(self, value: Any) -> int:
        """Index of the row carrying *value*, or ``-1``."""
        for i, it in enumerate(self.visible_items()):
            if not it.is_header and it.value == value:
                return i
        return -1

    def select_value(self, value: Any) -> bool:
        """Move the cursor to the row carrying *value*."""
        i = self.index_of(value)
        if i < 0:
            return False
        self.index = i
        self._scroll_into_view()
        return True

    def _selectable(self, it: MenuItem) -> bool:
        return it.enabled and not it.is_header

    def _snap_to_selectable(self, direction: int) -> None:
        vis = self.visible_items()
        if not vis:
            self.index = 0
            return
        n = len(vis)
        for _ in range(n):
            if 0 <= self.index < n and self._selectable(vis[self.index]):
                return
            self.index += direction
            if self.index < 0:
                self.index = n - 1 if self.wrap_around else 0
            elif self.index >= n:
                self.index = 0 if self.wrap_around else n - 1
        self.index = max(0, min(self.index, n - 1))

    def _scroll_into_view(self) -> None:
        if self.index < self.offset:
            self.offset = self.index
        elif self.index >= self.offset + self.per_page:
            self.offset = self.index - self.per_page + 1
        vis = len(self.visible_items())
        self.offset = max(0, min(self.offset, max(0, vis - self.per_page)))

    # -- input ------------------------------------------------------------- #

    def handle(self, key: str) -> Optional[str]:
        """Process a key; returns ``"select"``, ``"cancel"``, ``"move"`` or ``None``."""
        vis = self.visible_items()
        n = len(vis)
        if key in (keys.ESC, "q", "C-["):
            return "cancel"
        if key in (keys.ENTER, keys.SPACE):
            return "select" if self.selected else None
        if n == 0:
            return None
        if key in (keys.UP, "k", "8"):
            self.index -= 1
            if self.index < 0:
                self.index = n - 1 if self.wrap_around else 0
            self._snap_to_selectable(-1)
            self._scroll_into_view()
            return "move"
        if key in (keys.DOWN, "j", "2"):
            self.index += 1
            if self.index >= n:
                self.index = 0 if self.wrap_around else n - 1
            self._snap_to_selectable(1)
            self._scroll_into_view()
            return "move"
        if key == keys.PGUP:
            self.index = max(0, self.index - self.per_page)
            self._snap_to_selectable(1)
            self._scroll_into_view()
            return "move"
        if key == keys.PGDN:
            self.index = min(n - 1, self.index + self.per_page)
            self._snap_to_selectable(-1)
            self._scroll_into_view()
            return "move"
        if key == keys.HOME:
            self.index = 0
            self._snap_to_selectable(1)
            self._scroll_into_view()
            return "move"
        if key == keys.END:
            self.index = n - 1
            self._snap_to_selectable(-1)
            self._scroll_into_view()
            return "move"
        if len(key) == 1:
            for i, it in enumerate(vis):
                if it.hotkey == key and self._selectable(it):
                    self.index = i
                    self._scroll_into_view()
                    return "select"
        return None

    # -- drawing ----------------------------------------------------------- #

    def draw(
        self,
        scr: Screen,
        x: int,
        y: int,
        w: int,
        h: int,
        *,
        title: Optional[Markup] = None,
        show_scroll: bool = True,
        show_desc: bool = True,
    ) -> None:
        """Render the menu into a rectangle."""
        vis = self.visible_items()
        self.per_page = max(1, h)
        self._scroll_into_view()
        if title is not None:
            scr.text(x, y, title, colors.UI["title"])
            y += 1
            h -= 1
            self.per_page = max(1, h)
        bar_w = 1 if (show_scroll and len(vis) > h) else 0
        text_w = max(1, w - bar_w)

        for row in range(h):
            i = self.offset + row
            yy = y + row
            if i >= len(vis):
                break
            it = vis[i]
            sel = (i == self.index) and self._selectable(it)
            if it.is_header:
                scr.text(x, yy, frag_slice(it.label, 0, text_w), colors.UI["accent"])
                continue
            fg = (
                colors.UI["select_fg"] if sel
                else (colors.UI["fg"] if it.enabled else colors.UI["dim"])
            )
            bg = colors.UI["select_bg"] if sel else None
            if bg is not None:
                scr.fill(x, yy, text_w, 1, " ", fg, bg)
            prefix = "%s) " % it.hotkey if it.hotkey else ("> " if sel else "  ")
            cx = scr.text(x, yy, prefix, colors.UI["accent"] if it.hotkey else fg, bg)
            body = frag_slice(it.label, 0, max(0, text_w - cx))
            if not it.enabled:
                body = [Frag(f.text, colors.UI["dim"]) for f in body]
            elif sel:
                body = [Frag(f.text, f.color) for f in body]
            scr.text(x + cx, yy, body, fg, bg)
            if show_desc and it.desc and frag_len(it.desc):
                dw = text_w - cx - frag_len(it.label) - 2
                if dw > 6:
                    scr.text(
                        x + text_w - min(dw, frag_len(it.desc)),
                        yy,
                        frag_slice(it.desc, 0, dw),
                        colors.UI["dim"],
                        bg,
                    )

        if bar_w:
            _scrollbar(scr, x + w - 1, y, h, self.offset, h, len(vis))


def _scrollbar(
    scr: Screen, x: int, y: int, h: int, offset: int, page: int, total: int
) -> None:
    """Draw a one-column scrollbar."""
    if total <= 0 or h <= 0:
        return
    scr.vline(x, y, h, "|", colors.UI["frame"])
    thumb = max(1, int(h * page / float(total)))
    pos = int(h * offset / float(total))
    pos = max(0, min(h - thumb, pos))
    scr.vline(x, y + pos, thumb, "#", colors.UI["frame_hi"])


# --------------------------------------------------------------------------- #
# Small drawing helpers
# --------------------------------------------------------------------------- #


def progress_bar(
    scr: Screen,
    x: int,
    y: int,
    w: int,
    frac: float,
    *,
    fg: Optional[Color] = None,
    bg: Optional[Color] = None,
    ch: str = "=",
) -> None:
    """A bare filled bar."""
    scr.progress(x, y, w, frac, fg or colors.UI["accent"], bg, ch)


def gauge(
    scr: Screen,
    x: int,
    y: int,
    w: int,
    label: str,
    frac: float,
    color: Color,
    *,
    show_pct: bool = False,
) -> None:
    """A labelled bar: ``Health [=====---]``."""
    frac = max(0.0, min(1.0, frac))
    lw = min(len(label), max(0, w - 4))
    scr.text(x, y, label[:lw], colors.UI["dim"])
    bar_x = x + lw + 1
    bar_w = w - lw - 1
    if show_pct and bar_w > 5:
        bar_w -= 4
        scr.text_right(x + w - 1, y, "%3d%%" % int(frac * 100), colors.UI["dim"])
    if bar_w <= 2:
        return
    scr.put(bar_x, y, "[", colors.UI["frame"])
    scr.put(bar_x + bar_w - 1, y, "]", colors.UI["frame"])
    inner = bar_w - 2
    filled = int(round(frac * inner))
    scr.fill(bar_x + 1, y, filled, 1, "=", color)
    scr.fill(bar_x + 1 + filled, y, inner - filled, 1, "-", colors.UI["frame"])


def key_hint(
    scr: Screen,
    x: int,
    y: int,
    pairs: Sequence[Tuple[str, str]],
    fg: Optional[Color] = None,
) -> None:
    """Render ``[k] label`` hint runs along a row."""
    cx = x
    for k, label in pairs:
        if cx >= scr.width - 2:
            break
        cx += scr.text(cx, y, "[", colors.UI["frame"])
        cx += scr.text(cx, y, keys.key_label(k), colors.UI["accent"])
        cx += scr.text(cx, y, "] ", colors.UI["frame"])
        cx += scr.text(cx, y, label, fg or colors.UI["dim"])
        cx += scr.text(cx, y, "  ", colors.UI["dim"])


def scroll_view(
    scr: Screen,
    x: int,
    y: int,
    w: int,
    h: int,
    lines: Sequence[Markup],
    offset: int,
) -> int:
    """Draw a scrolled block of lines; returns the clamped offset used."""
    total = len(lines)
    offset = max(0, min(offset, max(0, total - h)))
    for i in range(h):
        li = offset + i
        if li >= total:
            break
        scr.text(x, y + i, frag_slice(lines[li], 0, w), colors.UI["fg"])
    if total > h:
        _scrollbar(scr, x + w - 1, y, h, offset, h, total)
    return offset


def draw_titled_panel(
    scr: Screen,
    x: int,
    y: int,
    w: int,
    h: int,
    title: Markup,
    *,
    style: str = "single",
) -> Tuple[int, int, int, int]:
    """Draw a framed panel and return its inner ``(x, y, w, h)``."""
    scr.frame(x, y, w, h, title=title, style=style)
    return (x + 1, y + 1, max(0, w - 2), max(0, h - 2))


class Tabs:
    """A horizontal tab strip."""

    def __init__(self, labels: Sequence[str], index: int = 0) -> None:
        self.labels = list(labels)
        self.index = max(0, min(index, len(self.labels) - 1)) if self.labels else 0

    def draw(self, scr: Screen, x: int, y: int, w: int) -> None:
        """Render the strip clipped to *w* columns."""
        cx = x
        for i, label in enumerate(self.labels):
            if cx >= x + w:
                break
            sel = i == self.index
            fg = colors.UI["select_fg"] if sel else colors.UI["dim"]
            bg = colors.UI["select_bg"] if sel else None
            txt = " %s " % label
            if bg is not None:
                scr.fill(cx, y, min(len(txt), x + w - cx), 1, " ", fg, bg)
            cx += scr.text(cx, y, txt, fg, bg, max_width=x + w - cx)
            cx += scr.text(cx, y, " ", colors.UI["frame"])

    def handle(self, key: str) -> bool:
        """Advance the selection on Tab/left/right; returns True if consumed."""
        if not self.labels:
            return False
        if key in (keys.TAB, keys.RIGHT, "L"):
            self.index = (self.index + 1) % len(self.labels)
            return True
        if key in (keys.BACKTAB, keys.LEFT, "H"):
            self.index = (self.index - 1) % len(self.labels)
            return True
        return False


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #


def _center_box(scr: Screen, w: int, h: int) -> Tuple[int, int]:
    return (max(0, (scr.width - w) // 2), max(0, (scr.height - h) // 2))


def popup(
    scr: Screen,
    term,
    lines: Sequence[Markup],
    *,
    title: Markup = "",
    buttons: Sequence[str] = ("OK",),
    width: Optional[int] = None,
) -> int:
    """Show a modal message box; returns the index of the chosen button."""
    body = list(lines)
    w = width or min(
        scr.width - 4, max(28, max((frag_len(l) for l in body), default=20) + 4)
    )
    wrapped: List[List[Frag]] = []
    for ln in body:
        wrapped.extend(wrap_frags(ln, w - 4))
    h = min(scr.height - 2, len(wrapped) + 4 + (1 if buttons else 0))
    x, y = _center_box(scr, w, h)
    sel = 0
    base = scr.snapshot()

    while True:
        scr.blit(base, 0, 0)
        scr.fill(x, y, w, h, " ", colors.UI["fg"], colors.UI["bg"])
        scr.frame(x, y, w, h, title=title, style="single")
        scr.box_shadow(x, y, w, h)
        for i, ln in enumerate(wrapped[: h - 4]):
            scr.text(x + 2, y + 1 + i, ln)
        if buttons:
            by = y + h - 2
            bx = x + 2
            for i, b in enumerate(buttons):
                label = "[ %s ]" % b
                fg = colors.UI["select_fg"] if i == sel else colors.UI["dim"]
                bg = colors.UI["select_bg"] if i == sel else None
                if bg is not None:
                    scr.fill(bx, by, len(label), 1, " ", fg, bg)
                scr.text(bx, by, label, fg, bg)
                bx += len(label) + 2
        term.render(scr)
        key = term.read_key()
        if key is None:
            continue
        if key in (keys.LEFT, "h") and buttons:
            sel = (sel - 1) % len(buttons)
        elif key in (keys.RIGHT, "l") and buttons:
            sel = (sel + 1) % len(buttons)
        elif key in (keys.ENTER, keys.SPACE):
            return sel
        elif key == keys.ESC:
            return -1
        elif len(key) == 1:
            for i, b in enumerate(buttons):
                if b and b[0].lower() == key.lower():
                    return i


def message_box(scr: Screen, term, title: Markup, text: Markup) -> None:
    """Show a message and wait for acknowledgement."""
    popup(scr, term, [text], title=title, buttons=("OK",))


def confirm(scr: Screen, term, question: str) -> bool:
    """Ask a yes/no question."""
    return popup(scr, term, [question], title="Confirm", buttons=("Yes", "No")) == 0


def text_input(
    scr: Screen,
    term,
    x: int,
    y: int,
    w: int,
    *,
    prompt: str = "",
    initial: str = "",
    max_len: int = 32,
    redraw: Optional[Callable[[], None]] = None,
) -> Optional[str]:
    """A single-line editor. Returns the text, or ``None`` if cancelled."""
    buf = list(initial[:max_len])
    cur = len(buf)
    pw = len(prompt)
    while True:
        if redraw:
            redraw()
        scr.fill(x, y, w, 1, " ", colors.UI["fg"], colors.UI["bg"])
        scr.text(x, y, prompt, colors.UI["accent"])
        field_w = max(1, w - pw - 1)
        view_start = max(0, cur - field_w + 1)
        shown = "".join(buf)[view_start:view_start + field_w]
        scr.text(x + pw, y, shown, colors.UI["select_fg"], colors.UI["select_bg"])
        scr.fill(
            x + pw + len(shown), y, field_w - len(shown), 1, " ",
            colors.UI["fg"], colors.UI["select_bg"],
        )
        cx = x + pw + (cur - view_start)
        ch, fg, _bg = scr.get(cx, y)
        scr.put(cx, y, ch if ch != " " else "_", colors.UI["bg"], colors.UI["accent"])
        term.render(scr)

        key = term.read_key()
        if key is None:
            continue
        if key == keys.ESC:
            return None
        if key == keys.ENTER:
            return "".join(buf).strip()
        if key == keys.BACKSPACE:
            if cur > 0:
                del buf[cur - 1]
                cur -= 1
        elif key == keys.DELETE:
            if cur < len(buf):
                del buf[cur]
        elif key == keys.LEFT:
            cur = max(0, cur - 1)
        elif key == keys.RIGHT:
            cur = min(len(buf), cur + 1)
        elif key == keys.HOME:
            cur = 0
        elif key == keys.END:
            cur = len(buf)
        elif key == keys.SPACE:
            if len(buf) < max_len:
                buf.insert(cur, " ")
                cur += 1
        elif keys.is_printable(key):
            if len(buf) < max_len:
                buf.insert(cur, key)
                cur += 1


def prompt_string(
    scr: Screen, term, prompt: str, initial: str = "", max_len: int = 32
) -> Optional[str]:
    """Modal single-line text prompt."""
    w = min(scr.width - 6, max(36, len(prompt) + max_len + 6))
    h = 5
    x, y = _center_box(scr, w, h)
    base = scr.snapshot()

    def redraw() -> None:
        scr.blit(base, 0, 0)
        scr.fill(x, y, w, h, " ", colors.UI["fg"], colors.UI["bg"])
        scr.frame(x, y, w, h, title="Input")
        scr.box_shadow(x, y, w, h)

    return text_input(
        scr, term, x + 2, y + 2, w - 4,
        prompt=prompt + " ", initial=initial, max_len=max_len, redraw=redraw,
    )


def prompt_direction(scr: Screen, term, prompt: str) -> Optional[Tuple[int, int]]:
    """Ask for a direction key; returns ``(dx, dy)`` or ``None``."""
    y = scr.height - 1
    scr.fill(0, y, scr.width, 1, " ", colors.UI["fg"], colors.UI["bg"])
    scr.text(0, y, prompt + " (direction, Esc to cancel)", colors.UI["accent"])
    term.render(scr)
    while True:
        key = term.read_key()
        if key is None:
            continue
        if key == keys.ESC:
            return None
        d = keys.direction_of(key)
        if d is not None:
            return d


def choose(
    scr: Screen,
    term,
    title: Markup,
    items: Sequence[MenuItem],
    *,
    per_page: int = 18,
    allow_cancel: bool = True,
    width: Optional[int] = None,
) -> Any:
    """A one-shot modal list chooser. Returns the chosen value, or ``None``."""
    if not items:
        message_box(scr, term, title, "Nothing to choose from.")
        return None
    longest = max(frag_len(it.label) for it in items)
    w = width or min(scr.width - 4, max(30, longest + 12))
    h = min(scr.height - 4, min(per_page, len(items)) + 4)
    x, y = _center_box(scr, w, h)
    menu = ListMenu(items, per_page=h - 4)
    base = scr.snapshot()

    while True:
        scr.blit(base, 0, 0)
        scr.fill(x, y, w, h, " ", colors.UI["fg"], colors.UI["bg"])
        scr.frame(x, y, w, h, title=title)
        scr.box_shadow(x, y, w, h)
        menu.draw(scr, x + 2, y + 1, w - 4, h - 3)
        key_hint(
            scr, x + 2, y + h - 2,
            [(keys.ENTER, "choose"), (keys.ESC, "cancel")],
        )
        term.render(scr)
        key = term.read_key()
        if key is None:
            continue
        result = menu.handle(key)
        if result == "select" and menu.selected:
            return menu.selected.value
        if result == "cancel" and allow_cancel:
            return None


def multi_choose(
    scr: Screen,
    term,
    title: Markup,
    items: Sequence[MenuItem],
    *,
    per_page: int = 18,
) -> List[Any]:
    """Choose several values; Space toggles, Enter accepts."""
    if not items:
        return []
    chosen: List[Any] = []
    w = min(scr.width - 4, max(34, max(frag_len(it.label) for it in items) + 14))
    h = min(scr.height - 4, min(per_page, len(items)) + 4)
    x, y = _center_box(scr, w, h)
    menu = ListMenu(items, per_page=h - 4, auto_hotkeys=False)
    base = scr.snapshot()

    while True:
        scr.blit(base, 0, 0)
        scr.fill(x, y, w, h, " ", colors.UI["fg"], colors.UI["bg"])
        scr.frame(x, y, w, h, title=title)
        scr.box_shadow(x, y, w, h)
        for i, it in enumerate(menu.visible_items()[menu.offset:menu.offset + h - 3]):
            mark = "[x]" if it.value in chosen else "[ ]"
            scr.text(x + 2, y + 1 + i, mark, colors.UI["accent"])
        menu.draw(scr, x + 6, y + 1, w - 8, h - 3)
        key_hint(
            scr, x + 2, y + h - 2,
            [(keys.SPACE, "toggle"), (keys.ENTER, "done"), (keys.ESC, "cancel")],
        )
        term.render(scr)
        key = term.read_key()
        if key is None:
            continue
        if key == keys.SPACE:
            it = menu.selected
            if it:
                if it.value in chosen:
                    chosen.remove(it.value)
                else:
                    chosen.append(it.value)
            continue
        if key == keys.ENTER:
            return chosen
        if key == keys.ESC:
            return []
        menu.handle(key)
