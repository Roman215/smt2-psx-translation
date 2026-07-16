"""SMT2 boot disclaimer (RDLOGO.BIN) English patch.

RDLOGO.BIN is a self-contained overlay loaded to fixed RAM base 0x801e40f8 and executed
at boot (the "This game is fiction..." disclaimer). Verified from PCSX-Redux boot save
state (sstate8):
- file 0x00-0x6b : 6 SJIS text fragments (F0..F5) drawn as 3 rows x 2 columns.
- file 0x6c-0x683: MIPS code. Draw routine @file 0x204 reads 6 string POINTERS from a
  pre-baked table and prints each via the STOCK system printer 0x800482a4 at a fixed
  (x,y). Print order -> (x,y):
    ptr[0]->(0,4)  ptr[1]->(78,4)   [row1: left, right]
    ptr[2]->(0,16) ptr[3]->(126,16) [row2]
    ptr[4]->(0,28) ptr[5]->(90,28)  [row3]
- file 0x684-0x69b: the 6-entry absolute pointer table (base+offset).
- file 0x69c+: function-pointer table (state machine) -- DO NOT TOUCH.

The three English lines use the same marker-prefixed one-byte format as sys_strings.py.
The main executable's system-printer wrapper expands those bytes to the existing SJIS
glyphs, so the overlay gains storage capacity without changing its code or pointers.
"""

import struct

BASE = 0x801e40f8      # RDLOGO load address (fixed)
PTR_TABLE = 0x684      # file offset of the 6-entry string pointer table

# Direct translation of:
# このゲームはフィクションであり
# 登場する人物や団体は実在の個人および団体とは一切関係ありません
#
LINES = [
    "This game is a work of fiction.",
    "Any relation to real people or groups",
    "is purely coincidental.",
]


def _ascii(s):
    return bytes([0x1f]) + s.encode("ascii") + b"\0"


def patch_rdlogo(rd):
    """rd: bytearray of RDLOGO.BIN. Rewrites fragments (file 0x00-0x63) as English and
    repoints the pointer table (file 0x684) to a single-column 3-line layout."""
    rd = bytearray(rd)
    # Lay the three marker-prefixed lines plus one empty string into file 0x00-0x6b.
    rd[0:0x6c] = bytes(0x6c)
    offs = []
    pos = 0x00
    for s in LINES:
        data = _ascii(s)
        offs.append(pos)
        rd[pos:pos + len(data)] = data
        pos += len(data)
    empty_off = pos
    rd[pos] = 0
    pos += 1
    if pos > 0x6c:
        raise SystemExit(f"RDLOGO strings overflow into code: end 0x{pos:x} > 0x6c")
    # Repoint: left column (slots 0,2,4) -> lines; right column (1,3,5) -> empty.
    ptrs = [BASE + offs[0], BASE + empty_off,   # row1: line1, (empty)
            BASE + offs[1], BASE + empty_off,   # row2: line2, (empty)
            BASE + offs[2], BASE + empty_off]   # row3: line3, (empty)
    for j, p in enumerate(ptrs):
        struct.pack_into("<I", rd, PTR_TABLE + j * 4, p)
    return bytes(rd)
