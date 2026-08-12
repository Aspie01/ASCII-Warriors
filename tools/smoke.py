"""Headless end-to-end driver.

Boots the whole game against a scripted terminal, plays a short adventure and
prints the final frame. Used by CI and while developing to prove the UI, the
world and the simulation all still fit together.

    python -m tools.smoke --seed ci --size pocket --history 20
"""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import List, Optional, Sequence

from ascii_warriors.engine.terminal import HeadlessTerminal, QuitSignal
from ascii_warriors.ui.app import App

#: Walk into the world, poke every screen, then quit.
DEFAULT_SCRIPT: List[str] = (
    # Title -> new adventure (second entry) -> generate with defaults
    ["j", "ENTER", "j", "j", "j", "ENTER"]
    # Character creation: cycle race and profession, then begin
    + ["l", "j", "l", "j", "j", "j", "j", "ENTER"]
    # Walk around a little
    + ["j", "l", "k", "h", "j", "j", "l", "l", "."] * 3
    # Look around, then out
    + ["x", "j", "l", "TAB", "ESC"]
    # Inventory: browse both tabs, then out
    + ["i", "j", "j", "TAB", "j", "ESC"]
    # Character sheet: every tab
    + ["C", "TAB", "j", "j", "TAB", "TAB", "TAB", "ESC"]
    # Legends: every tab, open an entry
    + ["L", "TAB", "j", "ENTER", "j", "j", "ESC", "TAB", "TAB", "TAB", "ESC"]
    # Help
    + ["?", "TAB", "TAB", "ESC"]
    # World map
    + ["M", "l", "l", "j", "ESC"]
    # Search, rest, wait
    + ["s", ".", ".", "R"]
    # Pause menu -> save -> resume
    + ["ESC", "j", "ENTER"]
    # Quit from the pause menu
    + ["ESC", "j", "j", "ENTER"]
)

#: Found a fortress, dig a hole, put up a workshop, look at every screen.
FORTRESS_SCRIPT: List[str] = (
    # Title -> new fortress -> generate with defaults
    ["ENTER", "j", "j", "j", "ENTER"]
    # Embark screen: take the suggestion, commit, confirm a dry site if asked
    + ["s", "ENTER", "y"]
    # Look around: scroll, change level, run some time
    + ["RIGHT", "DOWN", "LEFT", "UP", "SPACE"]
    + ["."] * 6
    + [">", "<", "+", "+", "-"]
    # Designate a block to dig, then a block of stairs
    + ["d", "d", "ENTER", "RIGHT", "RIGHT", "DOWN", "DOWN", "ENTER"]
    + ["i", "ENTER", "RIGHT", "ENTER"]
    + ["t", "ENTER", "DOWN", "ENTER", "ESC"]
    # Let them work
    + ["SPACE"] + ["."] * 12
    # Place a stockpile
    + ["p", "ENTER", "RIGHT", "RIGHT", "DOWN", "ENTER", "ESC"]
    # Build a workshop: the build menu opens a chooser first
    + ["b", "ENTER", "ENTER", "ESC"]
    # The militia: raise a squad, enlist somebody, give it orders
    + ["m", "n", "ENTER", "j", "j", "ENTER", "ENTER", "o", "j", "ENTER", "a", "ESC"]
    # A safe burrow for the civilians
    + ["w", "ENTER", "RIGHT", "RIGHT", "DOWN", "ENTER", "ESC"]
    # Health
    + ["h", "j", "ENTER", "ESC", "ESC"]
    # Levers and gates
    + ["L", "j", "l", "ESC", "ESC"]
    # Every panel
    + ["u", "j", "ENTER", "ESC", "l", "SPACE", "j", "SPACE", "ESC", "ESC"]
    + ["z", "j", "j", "ESC"]
    + ["j", "ENTER"]
    + ["o", "ESC"]
    + ["k", "ENTER"]
    + ["t", "ENTER"]
    + ["?", "ENTER"]
    # Run a while longer, then quit through the menu
    + ["."] * 20
    + ["ESC", "j", "j", "j", "j", "ENTER"]
)


def build_parser() -> argparse.ArgumentParser:
    """Command-line options for the smoke driver."""
    p = argparse.ArgumentParser(description="Headless smoke test for ASCII Warriors")
    p.add_argument("--seed", default="smoke")
    p.add_argument("--size", default="pocket")
    p.add_argument("--history", type=int, default=20)
    p.add_argument("--mode", default="adventure",
                   choices=("adventure", "fortress"),
                   help="which built-in script to run")
    p.add_argument("--keys", default="",
                   help="comma separated key script (default: a full tour)")
    p.add_argument("--width", type=int, default=100)
    p.add_argument("--height", type=int, default=34)
    p.add_argument("--frames", metavar="FILE",
                   help="write every rendered frame to a file")
    p.add_argument("--quiet", action="store_true",
                   help="do not print the final frame")
    return p


def run(argv: Optional[Sequence[str]] = None) -> int:
    """Play a scripted game and report success or failure."""
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    default = (FORTRESS_SCRIPT if args.mode == "fortress" else DEFAULT_SCRIPT)
    script = (
        [k for k in args.keys.split(",") if k] if args.keys else list(default)
    )
    term = HeadlessTerminal(args.width, args.height, script)
    app = App(
        term, seed=args.seed, world_size=args.size, history_years=args.history,
    )
    try:
        term.open()
        app.run()
    except QuitSignal:
        pass
    except Exception:
        sys.stderr.write("SMOKE FAILED\n")
        traceback.print_exc()
        if term.frames:
            sys.stderr.write("\nLast frame:\n" + term.last_text() + "\n")
        return 1
    finally:
        term.close()

    if args.frames:
        with open(args.frames, "w", encoding="utf-8") as fh:
            for i, frame in enumerate(term.frames):
                fh.write("=== frame %d ===\n" % i)
                fh.write("\n".join(frame) + "\n")

    if not args.quiet:
        sys.stdout.write(term.last_text() + "\n")
    sys.stdout.write(
        "\nSMOKE OK: %d keys consumed, %d frames rendered.\n"
        % (term.key_count, len(term.frames))
    )
    if app.game is not None:
        g = app.game
        sys.stdout.write(
            "Character: %s | turn %d | %s | %s\n"
            % (g.player.full_title(), g.turn, g.time.full_str(),
               g.player.body.wound_summary())
        )
    return 0


if __name__ == "__main__":
    sys.exit(run())
