"""Default party names and the two places the game keeps them.

The game reads every human party name out of one array of 7 x 17-byte fullwidth
slots at RAM 0x801fbd4c, which lives inside the executable's own data.  Only the
first six slots are (re)initialized from CMDINIT.BIN's identical template when a
new game starts; slot 6 -- アレフ, the hero's true name -- is never written by
that copy, so it keeps whatever the exe ships with.

That matters because the name-reveal event is ``strcpy(name[0], name[6])``
(0x80061fbc, and again at 0x80060d54 when the naming event targets slot 6).
Translating only CMDINIT.BIN therefore left the reveal handing the player back
katakana: v0.2.0 printed "Your name is Aleph..." and then renamed the hero to
アレフ.  Both copies of the table have to be patched.

Slot order matches the game's index: 0 Hawk (the hero's Colosseum name, the one
the naming screen offers first), 1 Hiroko, 2..5 the Center's four fighters, and
6 Aleph.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_en_tree as ET

ENTRY_SIZE = 17                    # fullwidth name + NUL, 8 characters max
COUNT = 7

CMDINIT_BASE = 0x558               # slot 0 inside CMDINIT.BIN
EXE_ARRAY = 0x801FBD4C             # slot 0 of the live array, in exe data

# (English, stock Japanese) per slot; the Japanese side is the build-time assert
# that the tables have not moved.
NAMES = [
    ("Hawk",   "ホーク"),
    ("Hiroko", "ヒロコ"),
    ("Beth",   "ベス"),
    ("Gimel",  "ギメル"),
    ("Daleth", "ダレス"),
    ("Zayin",  "ザイン"),
    ("Aleph",  "アレフ"),
]
assert len(NAMES) == COUNT

ENGLISH = [en for en, _jp in NAMES]


def entry_bytes(english):
    """One 17-byte slot: fullwidth Latin name, NUL-terminated and NUL-padded."""
    data = b"".join(bytes((ET.fullwidth(c) >> 8, ET.fullwidth(c) & 0xFF))
                    for c in english)
    if len(data) > ENTRY_SIZE - 1:
        raise SystemExit(f"party name too long for a {ENTRY_SIZE}-byte slot: {english!r}")
    return data.ljust(ENTRY_SIZE, b"\0")


def stock_bytes(japanese):
    return japanese.encode("shift_jis")

