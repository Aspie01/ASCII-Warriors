"""Key name constants and movement-key tables.

Keys are plain strings so they serialise trivially and read well in ``match``-style
dispatch. Printable keys are themselves (``"a"``, ``"7"``, ``"?"``); everything else
uses one of the named constants below.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

UP = "UP"
DOWN = "DOWN"
LEFT = "LEFT"
RIGHT = "RIGHT"
ENTER = "ENTER"
ESC = "ESC"
TAB = "TAB"
BACKTAB = "BACKTAB"
BACKSPACE = "BACKSPACE"
DELETE = "DELETE"
INSERT = "INSERT"
HOME = "HOME"
END = "END"
PGUP = "PGUP"
PGDN = "PGDN"
SPACE = "SPACE"

F1 = "F1"
F2 = "F2"
F3 = "F3"
F4 = "F4"
F5 = "F5"
F6 = "F6"
F7 = "F7"
F8 = "F8"
F9 = "F9"
F10 = "F10"
F11 = "F11"
F12 = "F12"

FUNCTION_KEYS = (F1, F2, F3, F4, F5, F6, F7, F8, F9, F10, F11, F12)

NAMED_KEYS = (
    UP, DOWN, LEFT, RIGHT, ENTER, ESC, TAB, BACKTAB, BACKSPACE, DELETE,
    INSERT, HOME, END, PGUP, PGDN, SPACE,
) + FUNCTION_KEYS


def ctrl(letter: str) -> str:
    """Return the control-key name for *letter*, e.g. ``ctrl("s") == "C-s"``."""
    return "C-" + letter.lower()


#: Movement keys -> (dx, dy). Screen coordinates: +y is south.
DIR_KEYS: Dict[str, Tuple[int, int]] = {
    # vi keys
    "h": (-1, 0),
    "j": (0, 1),
    "k": (0, -1),
    "l": (1, 0),
    "y": (-1, -1),
    "u": (1, -1),
    "b": (-1, 1),
    "n": (1, 1),
    # arrows
    LEFT: (-1, 0),
    DOWN: (0, 1),
    UP: (0, -1),
    RIGHT: (1, 0),
    # numpad / number row
    "1": (-1, 1),
    "2": (0, 1),
    "3": (1, 1),
    "4": (-1, 0),
    "5": (0, 0),
    "6": (1, 0),
    "7": (-1, -1),
    "8": (0, -1),
    "9": (1, -1),
}

#: Shifted vi keys, used for "run in this direction".
DIR_KEYS_UPPER: Dict[str, Tuple[int, int]] = {
    "H": (-1, 0),
    "J": (0, 1),
    "K": (0, -1),
    "L": (1, 0),
    "Y": (-1, -1),
    "U": (1, -1),
    "B": (-1, 1),
    "N": (1, 1),
}

_LABELS: Dict[str, str] = {
    UP: "Up",
    DOWN: "Down",
    LEFT: "Left",
    RIGHT: "Right",
    ENTER: "Enter",
    ESC: "Esc",
    TAB: "Tab",
    BACKTAB: "Shift-Tab",
    BACKSPACE: "Bksp",
    DELETE: "Del",
    INSERT: "Ins",
    HOME: "Home",
    END: "End",
    PGUP: "PgUp",
    PGDN: "PgDn",
    SPACE: "Space",
}

_SHIFT_MAP = {
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%", "6": "^",
    "7": "&", "8": "*", "9": "(", "0": ")", "-": "_", "=": "+",
    "[": "{", "]": "}", "\\": "|", ";": ":", "'": '"', ",": "<",
    ".": ">", "/": "?", "`": "~",
}


def is_printable(key: str) -> bool:
    """True if *key* is a single printable character."""
    return len(key) == 1 and 32 <= ord(key) < 127


def shifted(key: str) -> str:
    """Return the shifted form of a printable key (``"a" -> "A"``, ``"1" -> "!"``)."""
    if len(key) != 1:
        return key
    if key in _SHIFT_MAP:
        return _SHIFT_MAP[key]
    return key.upper()


def key_label(key: str) -> str:
    """A human-friendly label for help screens and key hints."""
    if key in _LABELS:
        return _LABELS[key]
    if key.startswith("C-") and len(key) == 3:
        return "Ctrl-" + key[2].upper()
    if key in FUNCTION_KEYS:
        return key
    return key


def is_direction(key: str) -> bool:
    """True if *key* is a movement key (including the shifted run variants)."""
    return key in DIR_KEYS or key in DIR_KEYS_UPPER


def direction_of(key: str) -> Optional[Tuple[int, int]]:
    """Return ``(dx, dy)`` for a movement key, or ``None``."""
    if key in DIR_KEYS:
        return DIR_KEYS[key]
    return DIR_KEYS_UPPER.get(key)


def is_run_key(key: str) -> bool:
    """True if *key* is a shifted movement key meaning "run"."""
    return key in DIR_KEYS_UPPER
