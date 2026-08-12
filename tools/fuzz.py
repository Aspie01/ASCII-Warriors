"""Random-key fuzzer.

Boots the game against a scripted terminal and hammers it with random keys,
looking for a screen that crashes when you press something unexpected. Every
run is seeded, so a failure can be replayed exactly.

    python -m tools.fuzz --mode fortress --keys 4000 --seed 7
"""

from __future__ import annotations

import argparse
import random
import sys
import traceback
from typing import List, Optional, Sequence

from ascii_warriors.engine.terminal import HeadlessTerminal, QuitSignal
from ascii_warriors.ui.app import App

#: The keys a confused player might actually press.
POOL: List[str] = (
    list("abcdefghijklmnopqrstuvwxyz")
    + list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    + list("0123456789")
    + list("<>+-=?/.,;:'\"[]{}()!@#$%^&*_|\\~`")
    + ["UP", "DOWN", "LEFT", "RIGHT", "ENTER", "TAB", "BACKTAB", "SPACE",
       "HOME", "END", "PGUP", "PGDN", "BACKSPACE", "DELETE", "INSERT"]
    + ["ESC"] * 4
    + ["F1", "F2", "F3", "F10"]
)

#: Enough to get into each mode before the random keys start.
PREFIX = {
    "adventure": ["j", "ENTER", "j", "j", "j", "ENTER",
                  "l", "j", "l", "j", "j", "j", "j", "ENTER"],
    "fortress": ["ENTER", "j", "j", "j", "ENTER", "s", "ENTER", "y"],
}


def build_parser() -> argparse.ArgumentParser:
    """Command-line options."""
    p = argparse.ArgumentParser(description="Random-key fuzzer")
    p.add_argument("--mode", default="fortress",
                   choices=("adventure", "fortress"))
    p.add_argument("--seed", default="fuzz")
    p.add_argument("--keys", type=int, default=3000)
    p.add_argument("--size", default="pocket")
    p.add_argument("--history", type=int, default=20)
    p.add_argument("--width", type=int, default=100)
    p.add_argument("--height", type=int, default=34)
    return p


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Fuzz one session; returns a process exit code."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    rng = random.Random(args.seed)
    script = list(PREFIX[args.mode])
    script += [rng.choice(POOL) for _ in range(args.keys)]

    term = HeadlessTerminal(args.width, args.height, script)
    app = App(term, seed=args.seed, world_size=args.size,
              history_years=args.history)
    try:
        term.open()
        app.run()
    except QuitSignal:
        pass
    except Exception:
        sys.stderr.write("FUZZ FAILED (mode=%s seed=%s) after %d keys\n"
                         % (args.mode, args.seed, term.key_count))
        traceback.print_exc()
        if term.frames:
            sys.stderr.write("\nLast frame:\n" + term.last_text() + "\n")
        return 1
    finally:
        term.close()

    sys.stdout.write("FUZZ OK: mode=%s seed=%s, %d keys, %d frames.\n"
                     % (args.mode, args.seed, term.key_count, len(term.frames)))
    return 0


if __name__ == "__main__":
    sys.exit(run())
