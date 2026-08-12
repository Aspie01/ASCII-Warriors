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
    """Write a game to disk and return the path."""
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
        },
        "game": game.to_dict(),
    }
    path = save_path_for(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    tmp.replace(path)
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
    return Game.from_dict(payload["game"])


def read_meta(path) -> Optional[Dict[str, Any]]:
    """Read just the header of a save file, without rebuilding the game."""
    try:
        with gzip.open(str(path), "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
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
