"""Saving and loading, as gzipped JSON in the platform's user data directory."""

from __future__ import annotations

import gzip
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SAVE_VERSION = 1
SAVE_SUFFIX = ".aws"
#: Fortresses save alongside adventurers but are a different sort of thing.
FORTRESS_SUFFIX = ".awf"
#: And the world is a third thing again: it outlives both of them.
WORLD_SUFFIX = ".awd"
APP_NAME = "ASCIIWarriors"


def save_dir() -> Path:
    """Where saves live on this platform."""
    override = os.environ.get("ASCII_WARRIORS_SAVE_DIR")
    if override:
        path = Path(override)
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME / "saves"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_NAME / "saves"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(name: str) -> str:
    """Turn a character name into a filesystem-safe stem."""
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", name).strip().replace(" ", "_")
    return cleaned or "adventurer"


def save_path_for(name: str) -> Path:
    """The file a save with this name would use."""
    return save_dir() / (_safe_name(name) + SAVE_SUFFIX)


def save_game(game, name: str) -> Path:
    """Write a game to disk and return the path.

    The world is written back too, so whatever this character has done to it
    is there for the next one. The character's own file goes first: if the
    world write fails, the story is still on disk.
    """
    ensure_uid(game.world)
    payload = {
        "version": SAVE_VERSION,
        "saved_at": int(time.time()),
        "meta": {
            "name": game.player.name,
            "race": game.player.defn.name,
            "profession": game.player.profession,
            "world": game.world.name,
            "year": game.time.year,
            "date": game.time.date_str(),
            "turn": game.turn,
            "kills": len(game.player.kills),
            "dead": game.game_over,
            "world_uid": game.world.uid,
        },
        "game": game.to_dict(),
    }
    path = save_path_for(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    tmp.replace(path)
    save_world(game.world)
    return path


def load_game(path):
    """Read a game back from disk."""
    from .state import Game

    with gzip.open(str(path), "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    version = int(payload.get("version", 0))
    if version > SAVE_VERSION:
        raise ValueError(
            "This save was made by a newer version of ASCII Warriors "
            "(save format %d, this build understands %d)."
            % (version, SAVE_VERSION)
        )
    game = Game.from_dict(payload["game"])
    adopt_world(game.world)
    return game


def fortress_path_for(name: str) -> Path:
    """The file a fortress save with this name would use."""
    return save_dir() / (_safe_name(name) + FORTRESS_SUFFIX)


def save_fortress(fort, name: str = "") -> Path:
    """Write a fortress to disk and return the path.

    The world goes with it, for the reason `save_game` writes one: what you
    have built here is a place the next character should be able to find.
    """
    ensure_uid(fort.world)
    payload = {
        "version": SAVE_VERSION,
        "saved_at": int(time.time()),
        "mode": "fortress",
        "meta": {
            "name": fort.name,
            "world": fort.world.name,
            "year": fort.time.year,
            "date": fort.time.date_str(),
            "dwarves": len(fort.dwarves()),
            "wealth": fort.wealth,
            "dead": fort.lost,
            "world_uid": fort.world.uid,
        },
        "fortress": fort.to_dict(),
    }
    path = fortress_path_for(name or fort.name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    tmp.replace(path)
    save_world(fort.world)
    return path


def load_fortress(path):
    """Read a fortress back from disk."""
    from ..fortress.fortress import Fortress

    with gzip.open(str(path), "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    version = int(payload.get("version", 0))
    if version > SAVE_VERSION:
        raise ValueError(
            "This save was made by a newer version of ASCII Warriors "
            "(save format %d, this build understands %d)."
            % (version, SAVE_VERSION)
        )
    fort = Fortress.from_dict(payload["fortress"])
    adopt_world(fort.world)
    return fort


# --------------------------------------------------------------------------- #
# Worlds
#
# A world is not a save. A save is one character's story; the world is the
# place all of them happen in, and it has to outlive any of them for the
# promise in `renown.retire` to mean anything: retire an adventurer, and the
# next adventurer -- or the next fortress -- walks into a world that has them
# in it. So the world is written to a file of its own, and every save writes
# it back as that character left it.
# --------------------------------------------------------------------------- #


def world_path_for(uid: str) -> Path:
    """The file a world with this handle uses."""
    return save_dir() / (_safe_name(uid) + WORLD_SUFFIX)


def _claim_uid(world) -> str:
    """A filename of its own for a world that has not been written yet.

    Named after the world, because that is what the player will look for in
    the list, and numbered on collision, because two worlds generated from
    different seeds can be called the same thing and neither should overwrite
    the other.
    """
    stem = _safe_name(world.name)
    if not world_path_for(stem).exists():
        return stem
    n = 2
    while world_path_for("%s_%d" % (stem, n)).exists():
        n += 1
    return "%s_%d" % (stem, n)


def ensure_uid(world) -> str:
    """Give a world its filename, before anything records which file that is.

    A save writes the world *into* its own payload as well as beside it, and
    a world serialised before it was named carried `uid = ""`. Loading that
    save then adopted a world that could not find its own file and wrote a
    second one, so a fresh save reopened once turned one world into two.
    """
    if not world.uid:
        world.uid = _claim_uid(world)
    return world.uid


def world_meta(world) -> Dict[str, Any]:
    """The header of a world file: enough to choose one without loading it.

    What a returning player is looking for is not the seed. It is who they
    left there -- the adventurers they retired and the fortresses they built.
    """
    retired = sorted(
        f.name for f in world.figures.values()
        if "retired" in f.flags and f.died is None
    )
    built = sorted(
        str(p.get("name", "?")) for p in world.preserved.values()
        if isinstance(p, dict)
    )
    return {
        "name": world.name,
        "uid": world.uid,
        "seed": world.seed,
        "year": world.year,
        "width": world.width,
        "height": world.height,
        "sites": len(world.sites),
        "civs": len(world.civs),
        "figures": sum(1 for f in world.figures.values() if f.died is None),
        "retired": retired,
        "built": built,
    }


def save_world(world) -> Path:
    """Write a world to its own file and return the path.

    Stamps `world.uid` the first time, so every later save of any character
    who plays here lands on the same file.
    """
    ensure_uid(world)
    payload = {
        "version": SAVE_VERSION,
        "saved_at": int(time.time()),
        "mode": "world",
        "meta": world_meta(world),
        "world": world.to_dict(),
    }
    path = world_path_for(world.uid)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    tmp.replace(path)
    return path


def load_world(path):
    """Read a world back from its own file."""
    from ..world.worldgen import World

    with gzip.open(str(path), "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    version = int(payload.get("version", 0))
    if version > SAVE_VERSION:
        raise ValueError(
            "This world was made by a newer version of ASCII Warriors "
            "(save format %d, this build understands %d)."
            % (version, SAVE_VERSION)
        )
    world = World.from_dict(payload["world"])
    if not world.uid:
        world.uid = Path(path).stem
    return world


def list_worlds() -> List[Dict[str, Any]]:
    """Every world on disk, newest first."""
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(save_dir().glob("*" + WORLD_SUFFIX))
    except OSError:
        return out
    for path in entries:
        meta = read_meta(path)
        if meta is None:
            continue
        meta["path"] = path
        if not meta.get("uid"):
            meta["uid"] = path.stem
        out.append(meta)
    out.sort(key=lambda m: m.get("saved_at", 0), reverse=True)
    return out


def describe_world(meta: Dict[str, Any]) -> str:
    """One-line summary of a world for the world list."""
    left = meta.get("retired") or []
    built = meta.get("built") or []
    if left and built:
        note = "%s, and %s" % (left[0], built[0])
    elif left:
        note = "%s settled here" % left[0]
    elif built:
        note = built[0]
    else:
        note = "-"
    return "%-28s %-6s %-7s %-7s %s" % (
        str(meta.get("name", "?"))[:28],
        str(meta.get("year", "?"))[:6],
        str(meta.get("sites", "?"))[:7],
        str(meta.get("figures", "?"))[:7],
        note[:34],
    )


def adopt_world(world) -> Optional[Path]:
    """Put a save's own world onto the world list if it is not there already.

    Every save carries a whole world -- three quarters of an adventurer's file
    is one -- and saves made before worlds had files of their own carry the
    only copy of theirs. Opening one adopts it, so it can be played again.

    Never overwrites: a world already on the list is the world as the last
    character *left* it, and loading an older save of somebody who lived there
    is not a reason to roll it back.
    """
    try:
        if world.uid and world_path_for(world.uid).exists():
            return None
        return save_world(world)
    except OSError:  # pragma: no cover - disk failure
        return None


def continue_seed(world) -> str:
    """A seed for the next character to play in a world.

    Derived from the world rather than the clock, so the same world in the
    same state always rolls the same next character -- and a world somebody
    has lived in is not in the same state as one nobody has.
    """
    return "%d:%d:%d" % (world.seed, len(world.events), len(world.figures))


def list_fortresses() -> List[Dict[str, Any]]:
    """Every fortress save on disk, newest first."""
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(save_dir().glob("*" + FORTRESS_SUFFIX))
    except OSError:
        return out
    for path in entries:
        meta = read_meta(path)
        if meta is None:
            continue
        meta["path"] = path
        out.append(meta)
    out.sort(key=lambda m: m.get("saved_at", 0), reverse=True)
    return out


#: Enough decompressed characters to hold any header. Every payload here is
#: written with its version, timestamp and `meta` before the game, the
#: fortress or the world, so the header is at the front of the file.
HEADER_CHARS = 65536


def _header_of(text: str) -> Optional[Dict[str, Any]]:
    """Pull version, timestamp and `meta` out of the front of a payload.

    Scans for each key and decodes only the value that follows it, so a list
    of worlds does not have to parse a megabyte of tiles to print a name.
    """
    decoder = json.JSONDecoder()
    out: Dict[str, Any] = {}
    for key in ("version", "saved_at", "meta"):
        at = text.find('"%s":' % key)
        if at < 0:
            return None
        try:
            out[key], _end = decoder.raw_decode(text, at + len(key) + 3)
        except ValueError:
            return None
    return out


def read_meta(path) -> Optional[Dict[str, Any]]:
    """Read just the header of a save file, without rebuilding the game.

    The title screen lists adventurers, fortresses and worlds, and a world is
    about a megabyte of JSON; parsing all three lists in full to print their
    names cost a quarter of a second per file. Falls back to a whole-file
    parse if the header is not where it should be.
    """
    try:
        with gzip.open(str(path), "rt", encoding="utf-8") as fh:
            head = fh.read(HEADER_CHARS)
            payload = _header_of(head)
            if payload is None:
                payload = json.loads(head + fh.read())
    except Exception:
        return None
    meta = dict(payload.get("meta") or {})
    meta["version"] = payload.get("version", 0)
    meta["saved_at"] = payload.get("saved_at", 0)
    return meta


def list_saves() -> List[Dict[str, Any]]:
    """Every save on disk, newest first."""
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(save_dir().glob("*" + SAVE_SUFFIX))
    except OSError:
        return out
    for path in entries:
        meta = read_meta(path)
        if meta is None:
            continue
        meta["path"] = path
        meta["file"] = path.name
        try:
            meta["mtime"] = path.stat().st_mtime
        except OSError:
            meta["mtime"] = 0
        out.append(meta)
    out.sort(key=lambda m: -m.get("mtime", 0))
    return out


def delete_save(path) -> None:
    """Remove a save file."""
    try:
        Path(path).unlink()
    except OSError:
        pass


def autosave(game) -> Optional[Path]:
    """Save under the character's name, swallowing any I/O error."""
    try:
        return save_game(game, game.player.name)
    except Exception:
        return None


def describe_fortress(meta: Dict[str, Any]) -> str:
    """One-line summary of a fortress save."""
    when = meta.get("saved_at", 0)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "?"
    status = "FALLEN" if meta.get("dead") else str(meta.get("dwarves", "?"))
    return "%-22s %-16s %-8s %-8s %s" % (
        str(meta.get("name", "?"))[:22],
        str(meta.get("date", "?"))[:16],
        status,
        str(meta.get("wealth", 0))[:8],
        stamp,
    )


def describe(meta: Dict[str, Any]) -> str:
    """One-line summary of a save for the load menu."""
    when = meta.get("saved_at", 0)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if when else "?"
    status = "DEAD" if meta.get("dead") else "alive"
    return "%-20s %-10s %-14s %s  %s" % (
        str(meta.get("name", "?"))[:20],
        str(meta.get("race", "?"))[:10],
        str(meta.get("date", "?"))[:14],
        status,
        stamp,
    )
