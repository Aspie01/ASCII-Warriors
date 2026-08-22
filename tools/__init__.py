"""The command-line drivers, and the one thing all of them must do first.

Every driver in here boots the real `App` against a headless terminal, and
the real `App` saves: a world is written the moment it is generated, and a
fortress or a character whenever the game decides to. Left alone, that is the
player's own save folder -- so a driver run both litters it and reads back
whatever is already in it.
"""

from __future__ import annotations

import os
import tempfile


def scratch_saves() -> str:
    """Point this process's saves somewhere harmless. Returns the directory.

    `tools/fuzz.py` promised that "every run is seeded, so a failure can be
    replayed exactly" while quietly depending on a directory it was itself
    filling up, one world per run. Measured on the same seed and the same
    source:

        save folder held at 144 files -> 447 keys, four runs out of four
        save folder empty             -> 459 keys, four runs out of four
        save folder as the ritual left it -> 447 and 835, alternating

    Nothing in the game was random. The run simply was not a function of its
    seed, which is the one thing a fuzzer has to be.

    `setdefault` rather than an assignment, so that a caller which has already
    chosen a directory -- the tests do, and so does anybody replaying a
    failure against a saved world -- keeps the one it chose.
    """
    os.environ.setdefault("ASCII_WARRIORS_SAVE_DIR", tempfile.mkdtemp())
    return os.environ["ASCII_WARRIORS_SAVE_DIR"]
