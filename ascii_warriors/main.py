"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
import traceback
from typing import List, Optional, Sequence

from . import __version__
from .engine.terminal import COLOR_MODES, HeadlessTerminal, Terminal
from .world.worldgen import WORLD_SIZES


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="ascii-warriors",
        description="A Dwarf-Fortress-inspired ASCII adventure RPG.",
    )
    parser.add_argument("--version", action="version",
                        version="ASCII Warriors %s" % __version__)
    parser.add_argument("--seed", metavar="TEXT",
                        help="world seed (any text); omit for a random world")
    parser.add_argument("--size", choices=sorted(WORLD_SIZES), default="medium",
                        help="world size (default: medium)")
    parser.add_argument("--history", type=int, default=120, metavar="YEARS",
                        help="years of history to simulate (default: 120)")
    parser.add_argument("--colors", choices=COLOR_MODES, default="auto",
                        dest="color_mode",
                        help="colour mode (default: auto-detect)")
    parser.add_argument("--unicode", action="store_true",
                        help="use Unicode box-drawing glyphs instead of ASCII")
    parser.add_argument("--load", metavar="PATH",
                        help="load a save file directly")
    parser.add_argument("--debug", action="store_true",
                        help="show tracebacks instead of a friendly message")
    parser.add_argument("--headless", metavar="KEYS",
                        help="run without a terminal, feeding a comma-separated "
                             "key script (for testing)")
    parser.add_argument("--headless-size", metavar="WxH", default="100x34",
                        help="screen size for --headless (default: 100x34)")
    parser.add_argument("--dump-world", metavar="FILE",
                        help="generate a world, write a text summary and exit")
    parser.add_argument("--list-saves", action="store_true",
                        help="list saved games and exit")
    return parser


def _dump_world(args: argparse.Namespace) -> int:
    """Generate a world and write a plain-text report."""
    from .engine.rng import RNG
    from .world import legends
    from .world.worldgen import generate_world, summarize

    rng = RNG(args.seed or "ascii-warriors")
    world = generate_world(rng, size=args.size, history_years=args.history)
    lines: List[str] = []
    lines.extend(summarize(world))
    lines.append("")
    for frag in legends.world_summary(world):
        lines.append(frag.text)
    lines.append("")
    lines.append("=== Full timeline ===")
    for ev in world.events:
        lines.append(ev.describe(world))
    text = "\n".join(lines) + "\n"
    if args.dump_world == "-":
        sys.stdout.write(text)
    else:
        with open(args.dump_world, "w", encoding="utf-8") as fh:
            fh.write(text)
        sys.stdout.write("Wrote %s (%d events)\n"
                         % (args.dump_world, len(world.events)))
    return 0


def _list_saves() -> int:
    """Print the saves on disk."""
    from .game import save as save_mod

    saves = save_mod.list_saves()
    if not saves:
        sys.stdout.write("No saved games in %s\n" % save_mod.save_dir())
        return 0
    sys.stdout.write("Saves in %s:\n" % save_mod.save_dir())
    for meta in saves:
        sys.stdout.write("  " + save_mod.describe(meta) + "\n")
    return 0


def _parse_size(text: str) -> tuple:
    """Parse a ``WxH`` size string."""
    try:
        w, h = text.lower().split("x")
        return (max(40, int(w)), max(14, int(h)))
    except (ValueError, AttributeError):
        return (100, 34)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the game."""
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.list_saves:
        return _list_saves()
    if args.dump_world:
        return _dump_world(args)

    from .ui.app import App

    if args.headless is not None:
        width, height = _parse_size(args.headless_size)
        script = [k for k in args.headless.split(",") if k != ""]
        term: Terminal = HeadlessTerminal(width, height, script)
    else:
        term = Terminal(color_mode=args.color_mode, unicode_glyphs=args.unicode)

    app = App(
        term, seed=args.seed, debug=args.debug,
        world_size=args.size, history_years=args.history,
    )

    code = 0
    try:
        term.open()
        term.set_title("ASCII Warriors")
        if args.load:
            from .game import save as save_mod
            from .ui.play_screen import PlayScene

            app.game = save_mod.load_game(args.load)
            app.push(PlayScene(app))
        code = app.run()
    except Exception:
        term.close()
        if args.debug:
            traceback.print_exc()
        else:
            sys.stderr.write(
                "ASCII Warriors hit an unexpected problem and had to stop.\n"
                "Run again with --debug to see the details.\n\n"
            )
            traceback.print_exc()
        return 1
    finally:
        term.close()

    if args.headless is not None and isinstance(term, HeadlessTerminal):
        sys.stdout.write(term.last_text() + "\n")
    return code


if __name__ == "__main__":  # pragma: no cover - module entry
    sys.exit(main())
