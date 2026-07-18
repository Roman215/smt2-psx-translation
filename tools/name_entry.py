"""Name-entry (naming) screen character grid -> English.

Two independent pieces must agree:

1. SELECTION TABLE -- a 16-row x 13-column table of fullwidth SJIS characters
   at exe RAM 0x800eaf64 (file 0xdb764): 13 big-endian SJIS chars (26 bytes)
   per row plus a u16 null terminator (28-byte stride, 448 bytes total).
   Rows display as three fixed groups of 5 / 5 / 3 columns (cursor X
   placement code at 0x8003ee60: X = 0x18/0x82/0xed + col*20).  The select
   handler at 0x8003effc reads char = table[(row+scroll) % 16][col] and
   appends it to the name buffer (8 chars max); (row 15, col 11) is the END
   button position (0x8003f19c) and must stay a space.  A scan over the exe
   finds no other reference into the table, so this part is a pure data edit.

2. GRID TEXTURE -- the characters the player SEES are not drawn from the
   table at runtime.  The whole grid is a pre-rendered 4bpp 156px-wide atlas
   in PACKA.BIN (top-left at 0x3237FF1, 78 bytes per image row), uploaded to
   VRAM; the per-frame draw 0x8003e7f8 blits 12x12 sprites with U=col*12,
   V=absrow*12.  Cell glyphs sit at image (2+col*12, 1+row*12), rendered from
   the game's own 12x12 fullwidth font (0x800d4188) with palette index 1 as
   foreground over an index-2 shadow at (+1,+1) -- verified pixel-identical
   for both kana and the stock fullwidth A-Z cells.  Image row 0 is a border
   line and rows 192+ hold the cursor frame / key icons / "-END-" label
   (sampled at V>=192); both are preserved untouched.
"""
import hashlib
import struct
import build_en_tree as ET

TABLE_FILE_OFF = 0xDB764          # RAM 0x800eaf64
ROWS, COLS = 16, 13
ROW_STRIDE = COLS * 2 + 2

# Stock layout: cols 0-4 hiragana, 5-9 katakana, 10-12 digits/A-Z/specials.
# English layout keeps the same groups: hiragana block -> uppercase,
# katakana block -> lowercase, right block -> digits plus the stock grid's
# non-Japanese specials (? ! ' -) and a period.  Every unused cell is a
# selectable fullwidth space, exactly like the stock table's padding rows.
LAYOUT = [
    "ABCDE" + "abcde" + "012",
    "FGHIJ" + "fghij" + "345",
    "KLMNO" + "klmno" + "678",
    "PQRST" + "pqrst" + "9?!",
    "UVWXY" + "uvwxy" + "'-.",
    "Z    " + "z    " + "   ",
] + [" " * COLS] * 10

# First stock row (a-i-u-e-o hira/kata + 0 1 2), anchor check before overwriting.
_STOCK_ROW0 = bytes.fromhex("82a082a282a482a682a883418343834583478349824f82508251")


def build_table():
    assert len(LAYOUT) == ROWS
    out = bytearray()
    for row in LAYOUT:
        assert len(row) == COLS, row
        for ch in row:
            out += struct.pack(">H", ET.fullwidth(ch))
        out += b"\x00\x00"
    assert len(out) == ROWS * ROW_STRIDE
    return bytes(out)


def apply_name_entry(exe):
    """Overwrite the kana grid in the exe image with the English layout."""
    off = TABLE_FILE_OFF
    if exe[off:off + len(_STOCK_ROW0)] != _STOCK_ROW0:
        raise ValueError("name-entry table anchor mismatch at 0x%x" % off)
    table = build_table()
    exe[off:off + len(table)] = table
    return len(table)


# ---------------- grid texture (PACKA atlas) ----------------

ATLAS_PACKA_OFF = 0x3237FF1
ATLAS_STRIDE = 78                 # bytes per image row = 156 px at 4bpp
ATLAS_WIDTH = 156
ATLAS_GRID_HEIGHT = 192           # rows 0..191 = 16 cell-rows of 12 px
ATLAS_SHA256 = "c768aa803d54787c67bf932cf2bb083f963011160351daab86857dafac9aa519"
GLYPH_X_OFF, GLYPH_Y_OFF = 2, 1   # glyph origin inside the 12x12 cell grid
FG_INDEX, SHADOW_INDEX = 1, 2

FONT12_ADDR = 0x800D4188
PSX_EXE_LOAD = 0x80010000
PSX_EXE_HEADER = 0x800


def _glyph12(slpm, sjis):
    """12x12 1bpp glyph rows for a fullwidth SJIS code, from the stock font."""
    hi, lo = sjis >> 8, sjis & 0xFF
    index = (hi - 0x81) * 189 + (lo - 0x40)
    base = FONT12_ADDR - PSX_EXE_LOAD + PSX_EXE_HEADER
    bit_origin = index * 144
    rows = []
    for gy in range(12):
        row = []
        for gx in range(12):
            bit = bit_origin + gy * 12 + gx
            row.append((slpm[base + bit // 8] >> (7 - bit % 8)) & 1)
        rows.append(row)
    return rows


def _atlas_pixel(packa, x, y, value):
    off = ATLAS_PACKA_OFF + y * ATLAS_STRIDE + x // 2
    if x & 1:
        packa[off] = (packa[off] & 0x0F) | ((value & 0x0F) << 4)
    else:
        packa[off] = (packa[off] & 0xF0) | (value & 0x0F)


def patch_atlas(packa, slpm):
    """Redraw the naming-grid atlas cells in PACKA with the LAYOUT characters.

    slpm must be the PRISTINE exe: the build kerns the shipped 12x12 font
    left for the VWF, but the atlas kana are centered stock glyphs, so the
    replacements must come from the unkerned bitmaps.
    """
    region = bytes(
        packa[ATLAS_PACKA_OFF:ATLAS_PACKA_OFF + ATLAS_GRID_HEIGHT * ATLAS_STRIDE]
    )
    actual = hashlib.sha256(region).hexdigest()
    if actual != ATLAS_SHA256:
        raise SystemExit(
            f"name-entry atlas at PACKA 0x{ATLAS_PACKA_OFF:x}: unexpected SHA-256 {actual}"
        )
    # Clear every grid pixel below the row-0 border line.
    for y in range(1, ATLAS_GRID_HEIGHT):
        for x in range(ATLAS_WIDTH):
            _atlas_pixel(packa, x, y, 0)
    # Shadow pass first so foreground ink always wins, as in the stock cells.
    for pass_index, value in ((1, SHADOW_INDEX), (0, FG_INDEX)):
        for row_index, row in enumerate(LAYOUT):
            for col_index, ch in enumerate(row):
                if ch == " ":
                    continue
                glyph = _glyph12(slpm, ET.fullwidth(ch))
                ox = GLYPH_X_OFF + col_index * 12 + pass_index
                oy = GLYPH_Y_OFF + row_index * 12 + pass_index
                for gy in range(12):
                    for gx in range(12):
                        if not glyph[gy][gx]:
                            continue
                        x, y = ox + gx, oy + gy
                        if x < ATLAS_WIDTH and 1 <= y < ATLAS_GRID_HEIGHT:
                            _atlas_pixel(packa, x, y, value)
