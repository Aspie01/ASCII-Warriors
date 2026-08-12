"""Cross-platform raw terminal I/O.

The only module that touches stdin/stdout directly. It provides raw-mode key
reading and a diffing ANSI renderer on both POSIX (``termios``) and Windows
(``ctypes`` + ``msvcrt``), with no third-party dependencies and no ``curses``.
"""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from . import colors, keys
from .colors import Color

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .screen import Screen

WINDOWS = sys.platform == "win32"

CSI = "\x1b["
ALT_SCREEN_ON = "\x1b[?1049h"
ALT_SCREEN_OFF = "\x1b[?1049l"
CURSOR_HIDE = "\x1b[?25l"
CURSOR_SHOW = "\x1b[?25h"
WRAP_OFF = "\x1b[?7l"
WRAP_ON = "\x1b[?7h"
SGR_RESET = "\x1b[0m"

COLOR_MODES = ("auto", "truecolor", "256", "16", "mono")


class QuitSignal(Exception):
    """Raised by :class:`HeadlessTerminal` when its scripted input is exhausted."""


# --------------------------------------------------------------------------- #
# Glyph fallback
# --------------------------------------------------------------------------- #

#: Non-ASCII glyphs mapped to safe ASCII for terminals we cannot trust.
ASCII_FALLBACK: Dict[str, str] = {
    "─": "-", "│": "|", "┌": "+", "┐": "+", "└": "+", "┘": "+",
    "═": "=", "║": "|", "╔": "+", "╗": "+", "╚": "+", "╝": "+",
    "━": "-", "┃": "|", "┏": "+", "┓": "+", "┗": "+", "┛": "+",
    "├": "+", "┤": "+", "┬": "+", "┴": "+", "┼": "+",
    "░": ".", "▒": ":", "▓": "#", "█": "#", "▄": "_", "▀": "\"",
    "•": "*", "·": ".", "°": "o", "±": "+", "«": "<", "»": ">",
    "↑": "^", "↓": "v", "←": "<", "→": ">", "≡": "=", "≈": "~",
    "☼": "*", "♦": "*", "♠": "*", "♣": "*", "♥": "*", "†": "+",
    "Ω": "O", "α": "a", "β": "B", "π": "n", "σ": "s", "µ": "u",
    "√": "v", "∞": "8", "∩": "n", "⌂": "^", "£": "L", "¢": "c",
}


def to_ascii(ch: str) -> str:
    """Map one character to a safe ASCII equivalent."""
    if not ch:
        return " "
    if ord(ch[0]) < 128:
        return ch[0]
    return ASCII_FALLBACK.get(ch[0], "?")


# --------------------------------------------------------------------------- #
# Environment probing
# --------------------------------------------------------------------------- #


def supports_color() -> bool:
    """True if the current stdout looks like a colour-capable tty."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        if not sys.stdout.isatty():
            return False
    except Exception:
        return False
    return os.environ.get("TERM", "") not in ("", "dumb")


def detect_color_mode() -> str:
    """Guess the best colour mode for this terminal."""
    if os.environ.get("NO_COLOR") is not None:
        return "mono"
    forced = os.environ.get("ASCII_WARRIORS_COLORS")
    if forced in COLOR_MODES and forced != "auto":
        return forced
    if os.environ.get("FORCE_COLOR"):
        return "truecolor"
    try:
        istty = sys.stdout.isatty()
    except Exception:
        istty = False
    if not istty:
        return "mono"
    if WINDOWS:
        # Any Windows console that accepts VT sequences handles 24-bit colour.
        return "truecolor"
    if os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return "truecolor"
    term = os.environ.get("TERM", "")
    if term in ("", "dumb"):
        return "mono"
    if "256" in term or "direct" in term:
        return "256"
    if "color" in term or term.startswith(("xterm", "screen", "tmux", "rxvt", "linux")):
        return "16"
    return "16"


def terminal_size(default: Tuple[int, int] = (100, 34)) -> Tuple[int, int]:
    """Current terminal size, falling back to *default*."""
    try:
        size = os.get_terminal_size()
        if size.columns > 0 and size.lines > 0:
            return (size.columns, size.lines)
    except Exception:
        pass
    try:
        cols = int(os.environ.get("COLUMNS", "0"))
        rows = int(os.environ.get("LINES", "0"))
        if cols > 0 and rows > 0:
            return (cols, rows)
    except ValueError:
        pass
    return default


# --------------------------------------------------------------------------- #
# POSIX escape-sequence decoding (a pure function, so it is unit testable)
# --------------------------------------------------------------------------- #

_CSI_FINAL: Dict[str, str] = {
    "A": keys.UP, "B": keys.DOWN, "C": keys.RIGHT, "D": keys.LEFT,
    "H": keys.HOME, "F": keys.END,
    "P": keys.F1, "Q": keys.F2, "R": keys.F3, "S": keys.F4,
    "Z": keys.BACKTAB,
}

_CSI_TILDE: Dict[int, str] = {
    1: keys.HOME, 2: keys.INSERT, 3: keys.DELETE, 4: keys.END,
    5: keys.PGUP, 6: keys.PGDN, 7: keys.HOME, 8: keys.END,
    11: keys.F1, 12: keys.F2, 13: keys.F3, 14: keys.F4, 15: keys.F5,
    17: keys.F6, 18: keys.F7, 19: keys.F8, 20: keys.F9, 21: keys.F10,
    23: keys.F11, 24: keys.F12,
}

_CTRL_NAMES = {
    "\r": keys.ENTER, "\n": keys.ENTER, "\t": keys.TAB,
    "\x7f": keys.BACKSPACE, "\x08": keys.BACKSPACE, "\x1b": keys.ESC,
    " ": keys.SPACE,
}


def decode_key(buf: str) -> Tuple[Optional[str], int]:
    """Decode the first key in *buf*.

    Returns ``(key_name, consumed)``. ``(None, 0)`` means the buffer holds an
    incomplete escape sequence and more input is needed.
    """
    if not buf:
        return (None, 0)
    ch = buf[0]

    if ch != "\x1b":
        if ch in _CTRL_NAMES:
            return (_CTRL_NAMES[ch], 1)
        code = ord(ch)
        if 1 <= code <= 26:
            return (keys.ctrl(chr(code + 96)), 1)
        if code < 32:
            return (keys.ctrl(chr(code + 64).lower()), 1)
        return (ch, 1)

    if len(buf) == 1:
        return (None, 0)  # bare ESC or an incomplete sequence

    second = buf[1]

    if second == "[":
        i = 2
        params = ""
        while i < len(buf) and (buf[i].isdigit() or buf[i] == ";"):
            params += buf[i]
            i += 1
        if i >= len(buf):
            return (None, 0)
        final = buf[i]
        consumed = i + 1
        if final == "~":
            head = params.split(";")[0]
            try:
                num = int(head) if head else 0
            except ValueError:
                num = 0
            return (_CSI_TILDE.get(num, keys.ESC), consumed)
        if final in _CSI_FINAL:
            return (_CSI_FINAL[final], consumed)
        return (keys.ESC, consumed)

    if second == "O":
        if len(buf) < 3:
            return (None, 0)
        final = buf[2]
        return (_CSI_FINAL.get(final, keys.ESC), 3)

    if second == "\x1b":
        return (keys.ESC, 1)

    # ESC followed by a printable char: treat as Alt-<key>; the game does not
    # use Alt bindings, so surface the plain key.
    return (second, 2)


# --------------------------------------------------------------------------- #
# Windows virtual-key mapping
# --------------------------------------------------------------------------- #

_WIN_SPECIAL: Dict[str, str] = {
    "H": keys.UP, "P": keys.DOWN, "K": keys.LEFT, "M": keys.RIGHT,
    "G": keys.HOME, "O": keys.END, "I": keys.PGUP, "Q": keys.PGDN,
    "R": keys.INSERT, "S": keys.DELETE,
    ";": keys.F1, "<": keys.F2, "=": keys.F3, ">": keys.F4, "?": keys.F5,
    "@": keys.F6, "A": keys.F7, "B": keys.F8, "C": keys.F9, "D": keys.F10,
    "\x85": keys.F11, "\x86": keys.F12,
}


def decode_windows_key(ch: str, special: bool) -> str:
    """Map a ``msvcrt`` character to a key name."""
    if special:
        return _WIN_SPECIAL.get(ch, keys.ESC)
    if ch in _CTRL_NAMES:
        return _CTRL_NAMES[ch]
    code = ord(ch) if ch else 0
    if 1 <= code <= 26:
        return keys.ctrl(chr(code + 96))
    if code < 32:
        return keys.ctrl(chr(code + 64).lower())
    return ch


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #


class Terminal:
    """Raw-mode terminal with a diffing ANSI renderer."""

    def __init__(self, color_mode: str = "auto", unicode_glyphs: bool = False) -> None:
        self.color_mode = color_mode if color_mode in COLOR_MODES else "auto"
        self._resolved_mode = self.color_mode
        self.unicode_glyphs = bool(unicode_glyphs)
        self._open = False
        self._prev_chars: List[str] = []
        self._prev_fgs: List[Color] = []
        self._prev_bgs: List[Color] = []
        self._prev_w = 0
        self._prev_h = 0
        self._size = terminal_size()
        self._force_redraw = True
        self._inbuf = ""
        self._saved_attrs = None
        self._win_saved_out = None
        self._win_saved_in = None
        self._win_saved_cp = None
        self._resized = False

    # -- lifecycle --------------------------------------------------------- #

    def open(self) -> None:
        """Enter raw mode and the alternate screen buffer."""
        if self._open:
            return
        self._resolved_mode = (
            detect_color_mode() if self.color_mode == "auto" else self.color_mode
        )
        if WINDOWS:
            self._open_windows()
        else:
            self._open_posix()
        self._open = True
        self._size = terminal_size()
        self._force_redraw = True
        self._write(ALT_SCREEN_ON + CURSOR_HIDE + WRAP_OFF + SGR_RESET + "\x1b[2J")
        self._flush()

    def close(self) -> None:
        """Restore the terminal. Safe to call twice, and never raises."""
        if not self._open:
            return
        self._open = False
        try:
            self._write(SGR_RESET + WRAP_ON + CURSOR_SHOW + ALT_SCREEN_OFF)
            self._flush()
        except Exception:
            pass
        try:
            if WINDOWS:
                self._close_windows()
            else:
                self._close_posix()
        except Exception:
            pass

    def __enter__(self) -> "Terminal":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- POSIX ------------------------------------------------------------- #

    def _open_posix(self) -> None:
        try:
            import signal
            import termios
            import tty
        except ImportError:  # pragma: no cover - non-POSIX
            return
        try:
            fd = sys.stdin.fileno()
            self._saved_attrs = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except Exception:
            self._saved_attrs = None
        try:
            signal.signal(signal.SIGWINCH, self._on_sigwinch)
        except (ValueError, AttributeError, OSError):
            pass

    def _close_posix(self) -> None:
        if self._saved_attrs is None:
            return
        try:
            import termios

            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self._saved_attrs)
        except Exception:
            pass
        self._saved_attrs = None

    def _on_sigwinch(self, signum, frame) -> None:  # pragma: no cover - signal path
        self._resized = True

    # -- Windows ----------------------------------------------------------- #

    def _open_windows(self) -> None:  # pragma: no cover - Windows only
        if not WINDOWS:
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h_out = kernel32.GetStdHandle(-11)
        h_in = kernel32.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(h_out, ctypes.byref(mode)):
            self._win_saved_out = mode.value
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING | ENABLE_PROCESSED_OUTPUT
            kernel32.SetConsoleMode(h_out, mode.value | 0x0004 | 0x0001)
        if kernel32.GetConsoleMode(h_in, ctypes.byref(mode)):
            self._win_saved_in = mode.value
            # Clear ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT
            kernel32.SetConsoleMode(h_in, mode.value & ~0x0002 & ~0x0004 & ~0x0001)
        try:
            self._win_saved_cp = kernel32.GetConsoleOutputCP()
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            self._win_saved_cp = None

    def _close_windows(self) -> None:  # pragma: no cover - Windows only
        if not WINDOWS:
            return
        import ctypes

        kernel32 = ctypes.windll.kernel32
        if self._win_saved_out is not None:
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), self._win_saved_out)
            self._win_saved_out = None
        if self._win_saved_in is not None:
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-10), self._win_saved_in)
            self._win_saved_in = None
        if self._win_saved_cp:
            kernel32.SetConsoleOutputCP(self._win_saved_cp)
            self._win_saved_cp = None

    # -- size -------------------------------------------------------------- #

    @property
    def size(self) -> Tuple[int, int]:
        """Current ``(width, height)``, never below ``(1, 1)``."""
        w, h = self._size
        return (max(1, w), max(1, h))

    def poll_resize(self) -> bool:
        """True if the terminal has been resized since the last call."""
        new = terminal_size(self._size)
        if new != self._size or self._resized:
            self._size = new
            self._resized = False
            self._force_redraw = True
            return True
        return False

    # -- input ------------------------------------------------------------- #

    def read_key(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read one key. Blocks forever when *timeout* is ``None``."""
        if WINDOWS:
            return self._read_key_windows(timeout)
        return self._read_key_posix(timeout)

    def _read_key_posix(self, timeout: Optional[float]) -> Optional[str]:
        import select

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            key, consumed = decode_key(self._inbuf)
            if key is not None:
                self._inbuf = self._inbuf[consumed:]
                return key
            # An unresolved lone ESC: wait briefly for the rest of the sequence.
            wait: Optional[float]
            if self._inbuf:
                wait = 0.05
            elif deadline is None:
                wait = None
            else:
                wait = max(0.0, deadline - time.monotonic())
            try:
                ready, _, _ = select.select([sys.stdin], [], [], wait)
            except (OSError, ValueError):
                return None
            if not ready:
                if self._inbuf:
                    # Nothing followed the ESC, so it really was Escape.
                    self._inbuf = self._inbuf[1:]
                    return keys.ESC
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                continue
            chunk = self._read_available()
            if not chunk:
                return None
            self._inbuf += chunk

    def _read_available(self) -> str:
        """Read whatever bytes are waiting on stdin and decode them as UTF-8."""
        try:
            data = os.read(sys.stdin.fileno(), 1024)
        except (OSError, ValueError):
            return ""
        if not data:
            return ""
        # Tolerate a split multi-byte character by dropping trailing partials.
        for trim in range(0, 4):
            try:
                return data[: len(data) - trim].decode("utf-8") if trim else data.decode("utf-8")
            except UnicodeDecodeError:
                continue
        return data.decode("latin-1", "replace")

    def _read_key_windows(  # pragma: no cover - Windows only
        self, timeout: Optional[float]
    ) -> Optional[str]:
        import msvcrt

        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    ch2 = msvcrt.getwch()
                    return decode_windows_key(ch2, True)
                return decode_windows_key(ch, False)
            if deadline is not None and time.monotonic() >= deadline:
                return None
            time.sleep(0.005)

    # -- rendering --------------------------------------------------------- #

    def full_redraw(self) -> None:
        """Force the next :meth:`render` to repaint every cell."""
        self._force_redraw = True

    def _sgr(self, fg: Color, bg: Color) -> str:
        mode = self._resolved_mode
        if mode == "mono":
            return ""
        if mode == "truecolor":
            return "\x1b[38;2;%d;%d;%d;48;2;%d;%d;%dm" % (
                fg.r, fg.g, fg.b, bg.r, bg.g, bg.b,
            )
        if mode == "256":
            return "\x1b[38;5;%d;48;5;%dm" % (colors.to_256(fg), colors.to_256(bg))
        f = colors.to_16(fg)
        b = colors.to_16(bg)
        fcode = (30 + f) if f < 8 else (90 + f - 8)
        bcode = (40 + b) if b < 8 else (100 + b - 8)
        return "\x1b[%d;%dm" % (fcode, bcode)

    def render(self, screen: "Screen") -> None:
        """Diff *screen* against the last frame and emit the minimal update."""
        w, h = screen.width, screen.height
        full = (
            self._force_redraw
            or w != self._prev_w
            or h != self._prev_h
            or not self._prev_chars
        )
        if full:
            self._prev_chars = [""] * (w * h)
            self._prev_fgs = [None] * (w * h)  # type: ignore[list-item]
            self._prev_bgs = [None] * (w * h)  # type: ignore[list-item]
            self._prev_w, self._prev_h = w, h

        out: List[str] = []
        if full:
            out.append(SGR_RESET)
            out.append("\x1b[2J")
        chars, fgs, bgs = screen.chars, screen.fgs, screen.bgs
        pchars, pfgs, pbgs = self._prev_chars, self._prev_fgs, self._prev_bgs
        ascii_only = not self.unicode_glyphs
        cur_fg: Optional[Color] = None
        cur_bg: Optional[Color] = None
        # A cursor-position escape costs ~6 bytes, so absorb short unchanged gaps
        # into a run rather than repositioning.
        gap_tolerance = 4

        for y in range(h):
            row = y * w
            for start, end in self._row_segments(
                row, w, chars, fgs, bgs, pchars, pfgs, pbgs, full, gap_tolerance
            ):
                out.append("\x1b[%d;%dH" % (y + 1, start + 1))
                for x in range(start, end):
                    i = row + x
                    fg, bg, ch = fgs[i], bgs[i], chars[i]
                    if fg != cur_fg or bg != cur_bg:
                        sgr = self._sgr(fg, bg)
                        if sgr:
                            out.append(sgr)
                        cur_fg, cur_bg = fg, bg
                    out.append(to_ascii(ch) if ascii_only else ch)
                    pchars[i] = ch
                    pfgs[i] = fg
                    pbgs[i] = bg
        if out:
            self._write("".join(out))
            self._flush()
        self._force_redraw = False

    @staticmethod
    def _row_segments(
        row: int,
        w: int,
        chars,
        fgs,
        bgs,
        pchars,
        pfgs,
        pbgs,
        full: bool,
        gap_tolerance: int,
    ) -> List[Tuple[int, int]]:
        """Half-open column spans in one row that need repainting."""
        if full:
            return [(0, w)] if w else []
        segments: List[Tuple[int, int]] = []
        start = -1
        gap = 0
        for x in range(w):
            i = row + x
            changed = not (
                pchars[i] == chars[i] and pfgs[i] == fgs[i] and pbgs[i] == bgs[i]
            )
            if changed:
                if start < 0:
                    start = x
                gap = 0
            elif start >= 0:
                gap += 1
                if gap > gap_tolerance:
                    segments.append((start, x - gap + 1))
                    start = -1
                    gap = 0
        if start >= 0:
            segments.append((start, w - gap))
        return segments

    def bell(self) -> None:
        """Ring the terminal bell."""
        self._write("\a")
        self._flush()

    def set_title(self, title: str) -> None:
        """Set the window/tab title."""
        self._write("\x1b]0;%s\a" % title.replace("\a", " "))
        self._flush()

    # -- low level --------------------------------------------------------- #

    def _write(self, s: str) -> None:
        try:
            sys.stdout.write(s)
        except (OSError, ValueError):
            pass

    def _flush(self) -> None:
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            pass


class HeadlessTerminal(Terminal):
    """A tty-free terminal for tests, CI and scripted smoke runs."""

    def __init__(
        self,
        width: int = 100,
        height: int = 34,
        keys_script: Sequence[str] = (),
        loop_keys: bool = False,
    ) -> None:
        super().__init__(color_mode="mono", unicode_glyphs=False)
        self._size = (max(1, width), max(1, height))
        self._queue: List[str] = list(keys_script)
        self._loop = bool(loop_keys)
        self._loop_source: List[str] = list(keys_script)
        #: Every rendered frame as plain-text rows (last 200 kept).
        self.frames: List[List[str]] = []
        self.key_count = 0

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def poll_resize(self) -> bool:
        return False

    def feed(self, more: Sequence[str]) -> None:
        """Append keys to the scripted queue."""
        self._queue.extend(more)
        if self._loop:
            self._loop_source.extend(more)

    def read_key(self, timeout: Optional[float] = None) -> Optional[str]:
        """Pop the next scripted key, raising :class:`QuitSignal` when exhausted."""
        if not self._queue:
            if self._loop and self._loop_source:
                self._queue = list(self._loop_source)
            else:
                raise QuitSignal("scripted input exhausted")
        self.key_count += 1
        return self._queue.pop(0)

    def render(self, screen: "Screen") -> None:
        """Record the frame as plain text instead of writing to a tty."""
        self.frames.append(screen.to_text())
        if len(self.frames) > 200:
            del self.frames[:-200]

    def last_text(self) -> str:
        """The most recent frame as a single newline-joined string."""
        if not self.frames:
            return ""
        return "\n".join(self.frames[-1])

    def bell(self) -> None:
        pass

    def set_title(self, title: str) -> None:
        pass
