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

Strategy (same reliability principle as sys_strings): rewrite the fragments as FULLWIDTH
SJIS Latin so the STOCK printer draws them (the 12x12 font 0x800d4188 has Latin glyphs).
We REPOINT to a clean single-column 3-line layout: put 3 English lines in the (now free)
fragment region and point the left slots (0,2,4) at them; point the right slots (1,3,5)
at an empty string so they draw nothing. No code changes -> no risk of the garble the
old ASCII-printer hook caused here.

Render buffer is ~200px wide => ~16 fullwidth chars/line.
"""

import struct
import build_en_tree as ET

BASE = 0x801e40f8      # RDLOGO load address (fixed)
PTR_TABLE = 0x684      # file offset of the 6-entry string pointer table

# 3-line English disclaimer (each <=16 fullwidth chars to fit the ~200px buffer).
LINES = [
    "This is fiction.",   # row1 (y=4)
    "Any resemblance",    # row2 (y=16)
    "is coincidental.",   # row3 (y=28)
]


def _fw(s):
    out = bytearray()
    for ch in s:
        out += struct.pack(">H", ET.fullwidth(ch))
    return bytes(out)


def patch_rdlogo(rd):
    """rd: bytearray of RDLOGO.BIN. Rewrites fragments (file 0x00-0x63) as English and
    repoints the pointer table (file 0x684) to a single-column 3-line layout."""
    rd = bytearray(rd)
    # Lay the 3 lines + one empty string into the fragment region starting at file 0x00.
    # Each entry: fullwidth bytes + NUL, 2-byte aligned. Region must end before code @0x6c.
    offs = []
    pos = 0x00
    for s in LINES:
        data = _fw(s)
        offs.append(pos)
        rd[pos:pos + len(data)] = data
        pos += len(data)
        rd[pos] = 0; rd[pos + 1] = 0   # NUL (2 bytes, keep even alignment)
        pos += 2
    empty_off = pos
    rd[pos] = 0; rd[pos + 1] = 0
    pos += 2
    if pos > 0x6c:
        raise SystemExit(f"RDLOGO strings overflow into code: end 0x{pos:x} > 0x6c")
    # Repoint: left column (slots 0,2,4) -> lines; right column (1,3,5) -> empty.
    ptrs = [BASE + offs[0], BASE + empty_off,   # row1: line1, (empty)
            BASE + offs[1], BASE + empty_off,   # row2: line2, (empty)
            BASE + offs[2], BASE + empty_off]   # row3: line3, (empty)
    for j, p in enumerate(ptrs):
        struct.pack_into("<I", rd, PTR_TABLE + j * 4, p)
    return bytes(rd)
