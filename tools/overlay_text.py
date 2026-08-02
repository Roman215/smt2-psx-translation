"""English text for executable overlays that carry private string tables.

Most UI text is resident in SLPM_869.24 or PACKA.BIN, but several overlays keep
their own raw Shift-JIS copies.  These strings use the same stock printer as the
main executable, so the global 0x1f ASCII wrapper installed by build.py works here
too (the boot disclaimer already relies on the same behavior).

The casino and bonus-viewer name lists deliberately reuse name_tables.py.  Keeping
one canonical spelling list prevents these rarely visited screens from drifting
away from the names shown in battle and the main menus.
"""

import hashlib
import struct

import build_en_tree as ET
import name_tables as NT


ASCII_MARKER = 0x1F

# Set by build.py before the overlays are patched.  WIDTHS10 is kern_font's
# 10x10 proportional width table (keyed by SJIS glyph index); ENHANCEMENTS
# mirrors the build's --no-enhancements switch.
WIDTHS10 = None
ENHANCEMENTS = True


def configure(widths10=None, enhancements=True):
    global WIDTHS10, ENHANCEMENTS
    WIDTHS10 = widths10
    ENHANCEMENTS = enhancements


# ---- Minimal MIPS I encoder for the in-overlay patches ---------------------------
ZERO, V0, V1, A0, A1, A2, A3 = 0, 2, 3, 4, 5, 6, 7
S0, S1, S2, S3, S4, S5 = 16, 17, 18, 19, 20, 21


def _i(op, rs, rt, imm):
    return ((op & 0x3F) << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (imm & 0xFFFF)


def _r(rs, rt, rd, sa, fn):
    return ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | ((rd & 0x1F) << 11) | \
           ((sa & 0x1F) << 6) | (fn & 0x3F)


NOP = 0
ADDIU = lambda rt, rs, imm: _i(0x09, rs, rt, imm)
ANDI = lambda rt, rs, imm: _i(0x0C, rs, rt, imm)
ORI = lambda rt, rs, imm: _i(0x0D, rs, rt, imm)
LUI = lambda rt, imm: _i(0x0F, 0, rt, imm)
SLTIU = lambda rt, rs, imm: _i(0x0B, rs, rt, imm)
LW = lambda rt, off, rs: _i(0x23, rs, rt, off)
LBU = lambda rt, off, rs: _i(0x24, rs, rt, off)
LHU = lambda rt, off, rs: _i(0x25, rs, rt, off)
SH = lambda rt, off, rs: _i(0x29, rs, rt, off)
BNEZ = lambda rs, off: _i(0x05, rs, 0, off)
JAL = lambda target: (0x03 << 26) | ((target >> 2) & 0x03FFFFFF)
ADDU = lambda rd, rs, rt: _r(rs, rt, rd, 0, 0x21)
SUBU = lambda rd, rs, rt: _r(rs, rt, rd, 0, 0x23)
SLL = lambda rd, rt, sa: _r(0, rt, rd, sa, 0x00)
SRL = lambda rd, rt, sa: _r(0, rt, rd, sa, 0x02)
MULTU = lambda rs, rt: _r(rs, rt, 0, 0, 0x19)
MFHI = lambda rd: _r(0, 0, rd, 0, 0x10)
MOVE = lambda rd, rs: ADDU(rd, rs, ZERO)


def _write_code(buf, off, words, expected_sha256, *, label):
    """Replace a verified run of instructions with an equally long new one."""
    stock = bytes(buf[off:off + len(words) * 4])
    actual = hashlib.sha256(stock).hexdigest()
    if actual != expected_sha256:
        raise SystemExit(
            f"{label}: unexpected stock code at 0x{off:x} "
            f"({actual[:16]} != {expected_sha256[:16]})"
        )
    struct.pack_into(f"<{len(words)}I", buf, off, *words)


def _ascii(text):
    try:
        encoded = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise SystemExit(f"overlay text is not ASCII: {text!r}") from exc
    return bytes((ASCII_MARKER,)) + encoded + b"\0"


def _patch_slot(buf, off, gap, expected, english, *, label):
    """Replace one NUL-terminated SJIS slot without disturbing adjacent data."""
    original = expected.encode("shift_jis")
    if bytes(buf[off:off + len(original)]) != original:
        raise SystemExit(f"{label} 0x{off:x}: unexpected Japanese source")
    if off + len(original) >= off + gap or buf[off + len(original)] != 0:
        raise SystemExit(f"{label} 0x{off:x}: source is not NUL-terminated in its slot")
    if any(buf[off + len(original) + 1:off + gap]):
        raise SystemExit(f"{label} 0x{off:x}: nonzero slot padding")
    data = _ascii(english)
    if len(data) > gap:
        raise SystemExit(
            f"{label} 0x{off:x} OVERFLOW {len(data)}>{gap}: {english!r}"
        )
    buf[off:off + gap] = data + bytes(gap - len(data))


def _aligned_slots(buf, start, count, expected_end, *, label):
    """Read a four-byte-aligned raw-SJIS table and return its fixed slots."""
    slots = []
    pos = start
    for index in range(count):
        try:
            end = buf.index(0, pos)
        except ValueError as exc:
            raise SystemExit(f"{label}: unterminated entry {index}") from exc
        next_pos = (end + 4) & ~3
        if any(buf[end + 1:next_pos]):
            raise SystemExit(f"{label}: nonzero padding after entry {index}")
        try:
            japanese = bytes(buf[pos:end]).decode("shift_jis")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"{label}: invalid Shift-JIS entry {index}") from exc
        slots.append((pos, next_pos - pos, japanese))
        pos = next_pos
    if pos != expected_end:
        raise SystemExit(f"{label}: unexpected table end 0x{pos:x} != 0x{expected_end:x}")
    return slots


# Disc overlays are loaded to a fixed RAM address, and it is *not* the round
# number the file offsets suggest: the boot disclaimer, the casino demon list
# and the bonus viewer all run from 0x801e40f8, so file offset 0 is that
# address.  Getting this wrong is silent -- the strings are still translated in
# place, but _repack_table then rewrites the wrong pointers, so a row shows a
# different demon's name and the race pointer lands mid-string and prints
# symbol glyphs.  _verify_pointer_coverage below turns that back into a build
# failure.
OVERLAY_BASE = 0x801E40F8


def _verify_pointer_coverage(buf, start, expected_end, entry_offsets, *, label):
    """Prove every stored pointer into a repacked bank hit a real string start.

    Run against the untouched source, before anything is rewritten.  A wrong
    OVERLAY_BASE (or a table that is not really a list of absolute pointers)
    shows up here as pointers that land in the middle of an entry.
    """
    entries = set(entry_offsets)
    referenced = set()
    strays = []
    for off in range(0, len(buf) - 3, 4):
        if start <= off < expected_end:
            continue
        pointer = struct.unpack_from("<I", buf, off)[0]
        if not (OVERLAY_BASE + start <= pointer < OVERLAY_BASE + expected_end):
            continue
        target = pointer - OVERLAY_BASE
        if target in entries:
            referenced.add(target)
        else:
            strays.append((off, pointer))
    if strays:
        detail = ", ".join(f"0x{o:x}->0x{p:08x}" for o, p in strays[:6])
        raise SystemExit(
            f"{label}: {len(strays)} pointer(s) do not address an entry start "
            f"with overlay base 0x{OVERLAY_BASE:08x}: {detail}"
        )
    if not referenced:
        raise SystemExit(
            f"{label}: no pointer references this bank with overlay base "
            f"0x{OVERLAY_BASE:08x}"
        )
    return referenced


def _repack_table(buf, start, count, expected_end, english, *, label):
    """Repack an aligned raw-name table and retarget its absolute pointers.

    English is smaller overall, but a few individual names are longer than their
    Japanese slots.  Repacking the complete private bank avoids abbreviations while
    keeping its start/end addresses and every following overlay structure fixed.
    """
    slots = _aligned_slots(buf, start, count, expected_end, label=label)
    if len(english) != count:
        raise SystemExit(f"{label}: {len(english)} translations for {count} entries")
    _verify_pointer_coverage(
        buf, start, expected_end, [pos for pos, _gap, _jp in slots], label=label
    )

    blob = bytearray()
    new_offsets = []
    for text in english:
        new_offsets.append(start + len(blob))
        data = _ascii(text)
        blob += data
        blob += bytes((-len(blob)) & 3)
    allocation = expected_end - start
    if len(blob) > allocation:
        raise SystemExit(f"{label} OVERFLOW {len(blob)}>{allocation}")

    pointer_map = {
        OVERLAY_BASE + old_off: OVERLAY_BASE + new_off
        for (old_off, _gap, _japanese), new_off in zip(slots, new_offsets)
    }
    buf[start:expected_end] = blob + bytes(allocation - len(blob))

    # The overlays store selected names in ordinary absolute-pointer lists.  No
    # table address is synthesized by an instruction pair; update every aligned
    # pointer word outside the string allocation.
    for off in range(0, len(buf) - 3, 4):
        if start <= off < expected_end:
            continue
        old_pointer = struct.unpack_from("<I", buf, off)[0]
        new_pointer = pointer_map.get(old_pointer)
        if new_pointer is not None:
            struct.pack_into("<I", buf, off, new_pointer)
    return slots, new_offsets


def _patch_demon_table(buf, start, expected_end, *, label):
    # These private tables contain the 255 ordinary demons in reverse game order:
    # Moebius through Satan.  The later boss/special entries are not present.
    english = list(reversed(NT.DEMONS[:255]))
    slots = _aligned_slots(buf, start, len(english), expected_end, label=label)
    if slots[0][2] != "メビウス" or slots[-1][2] != "サタン":
        raise SystemExit(f"{label}: unexpected demon-table order")
    _repack_table(buf, start, len(english), expected_end, english, label=label)


def patch_3dmap(source):
    """Translate the Automap/COMP text bank at the start of 3DMAP.BIN."""
    buf = bytearray(source)
    entries = {
        0x024: (0x24, "ここではＣＯＭＰを使用できません", "The COMP can't be used here."),
        # This one is followed immediately by a one-byte data value at 0x6b;
        # unlike the later bank entries it has no four-byte alignment padding.
        0x048: (0x23, "ＣＯＭＰを使える状態ではありません", "You can't use the COMP now."),
        # Marker help is displayed as a category line followed by one of the
        # two action lines.  Complete English phrases keep every pairing natural.
        0x20C: (0x18, "その他の状況に応じて", "Other purposes:"),
        0x224: (0x10, "ボス部屋などに", "Boss areas:"),
        0x234: (0x14, "宝箱の設置ポイント", "Treasure spots:"),
        0x248: (0x18, "イベント発生ポイント", "Event locations:"),
        0x260: (0x10, "通常の用途に", "General use:"),
        0x270: (0x14, "などに使用します", "Mark this spot."),
        0x284: (0x0C, "使用します", "Mark here."),
        0x290: (0x18, "このマーカーを消します", "Delete this marker."),
        0x2A8: (0x24, "マーカーの種類を選択してください", "Select a marker type."),
        0x2CC: (0x28, "その場所にはマーカーをセットできません", "You can't place a marker there."),
        0x2F4: (0x18, "マーカーをセットします", "Place a marker."),
    }
    for off, (gap, japanese, english) in entries.items():
        _patch_slot(buf, off, gap, japanese, english, label="3DMAP.BIN")
    return bytes(buf)


def patch_casino3(source):
    """Translate the demon-selection table private to CASINO3.BIN."""
    buf = bytearray(source)
    _patch_demon_table(buf, 0x000, 0xC98, label="CASINO3.BIN demons")
    ui = {
        0xC98: (0x0C, "ハズサナイ", "Keep"),
        0xCA4: (0x0C, "センコウ", "First"),
        0xCB0: (0x0C, "コウコウ", "Second"),
        0xCBC: (0x10, "あくま　ＭＡＸ", "DEMON MAX"),
        0xCCC: (0x10, "どうしますか？", "What now?"),
        0xCDC: (0x10, "ドレカハズス", "Remove which?"),
    }
    for off, (gap, japanese, english) in ui.items():
        _patch_slot(buf, off, gap, japanese, english, label="CASINO3.BIN UI")
    return bytes(buf)


# ---- Bonus viewer (post-ending Devil Analysis roll) ------------------------------
# The viewer walks a fixed 186-row list of demons.  Each row draws a name plate --
# race in green then the demon name -- above the portrait, and an ENCOUNT/DEFEAT
# tally below it.  Three parallel per-row tables drive that layout, and all three
# are counts of *Japanese* fullwidth cells, so none of them survive translation:
#
#   0x2270  plate size: race + 1 + name cells; the plate spans x = 158-6n .. 162+6n
#           and the text surface is blitted at x = 158-6n
#   0x232C  demon id, which indexes the name pointer table at 0x2848
#   0x23E8  race cell count, used as pen X = 12*cells + 15 for the demon name
#
# Rather than keep a cell count that means nothing for proportional English, the
# patches below switch the plate to the compact 10x10 font used by the Cathedral
# and party lists, make the name follow the race by reading back the pen, and
# rescale the plate table to *pixels* so it can be recomputed from real widths.
OMAKE_ROWS = 186
OMAKE_PLATE_TABLE = 0x2270
OMAKE_ROW_DEMON = 0x232C
OMAKE_RACE_PTRS = 0x2560

# Stock plate geometry: left edge = OMAKE_PLATE_LEFT - n, right edge =
# OMAKE_PLATE_RIGHT + n, and the race pen starts OMAKE_PLATE_PAD past the left
# edge.  Only the scale of n changes (six pixels per unit -> one).
OMAKE_PLATE_LEFT = 158
OMAKE_PLATE_RIGHT = 162
OMAKE_PLATE_PAD = 3
# Surface the plate text is drawn into, from the sprite primitive at 0x801e6d70.
OMAKE_SURFACE_WIDTH = 168
# Gap between the race and the demon name.  The stock screen used a full 12px
# cell; 8 keeps the two fields clearly separate at 10x10 without wasting plate.
OMAKE_NAME_GAP = 8

# addiu a1, zero, 8 -> font 4.  Font ids here index the 0x800f8268 pointer array,
# where 8 is the 12x12 fullwidth face and 4 is the 10x10 one.
OMAKE_FONT_SELECT = 0x0EA4
OMAKE_FONT_SELECT_SHA256 = \
    "4c1eecc19b1c1edff9e300f395ec05653f5a4737404768e27c67e85269fda589"
OMAKE_NAME_X = 0x0EF4
OMAKE_NAME_X_SHA256 = \
    "d4f226a77f9fb4d9a5ec74a15d555912acb4ed69effe49b5201c9ae3cfd61635"
OMAKE_DEFEAT = 0x11A0
OMAKE_DEFEAT_SHA256 = \
    "c2a6ecc45e898cc48f12302b945e8bb69eb14794f08b0995e2e8185353f53e62"
# The five inlined "n * 6" expansions in the plate-geometry setup.
OMAKE_PLATE_SCALES = (
    (0x1B08, V0, V1), (0x1B24, V0, V1), (0x1B38, V1, A1),
    (0x1B58, V0, A1), (0x1B68, V0, V1),
)

OMAKE_CTX = S0                    # plate text context, 0x801e6da8
OMAKE_SET_PEN = 0x80048448        # set pen x/y
OMAKE_PRINT = 0x800482A4          # stock string printer (ASCII-aware in this build)
OMAKE_PEN_X = 0x20                # context field written by OMAKE_SET_PEN
OMAKE_ROW_INDEX = 0x7098          # current row, relative to s2 = 0x801e0000
OMAKE_DIGITS = S4                 # 0x801e7064, pointer table of digit glyphs
OMAKE_DIV10 = S5                  # 0xcccccccd
OMAKE_DEFEAT_TABLE = 0x801FC128   # per-demon analysis counter
OMAKE_DEFEAT_Y = 0x0C
OMAKE_DEFEAT_DIGIT_X = (0x40, 0x48, 0x50)


def _text_width(text, *, label):
    """Width of one proportional 10x10 string, in pixels."""
    if WIDTHS10 is None:
        raise SystemExit(f"{label}: 10x10 width table was not configured")
    total = 0
    for char in text:
        code = ET.fullwidth(char)
        row = (code >> 8) - (0x81 if (code >> 8) < 0xA0 else 0xC1)
        total += WIDTHS10.get((code & 0xFF) - 0x40 + row * 189, 10)
    return total


def _patch_omake_plate(buf, races, race_offsets):
    """Draw the name plate in 10x10 English and size it to the real text."""
    _write_code(
        buf, OMAKE_FONT_SELECT, [ADDIU(A1, ZERO, 4)],
        OMAKE_FONT_SELECT_SHA256, label="OMAKE.BIN plate font",
    )

    # The demon name used a precomputed Japanese pen X.  Read back the pen the
    # race just left instead -- the same idiom the Cathedral rows use.
    _write_code(
        buf, OMAKE_NAME_X,
        [
            LHU(A1, OMAKE_PEN_X, OMAKE_CTX),
            NOP,                                    # R3000 load-delay slot
            ADDIU(A1, A1, OMAKE_NAME_GAP),
            SH(A1, OMAKE_PEN_X, OMAKE_CTX),
        ] + [NOP] * 8,
        OMAKE_NAME_X_SHA256, label="OMAKE.BIN plate name pen",
    )

    # Rescale the plate half-width from 12-pixel cells to single pixels.
    stock_scale = {
        (V0, V1): (0x00031040, 0x00431021, 0x00021040),
        (V1, A1): (0x00051840, 0x00651821, 0x00031840),
        (V0, A1): (0x00051040, 0x00451021, 0x00021040),
    }
    for offset, dst, src in OMAKE_PLATE_SCALES:
        expected = stock_scale[(dst, src)]
        actual = struct.unpack_from("<3I", buf, offset)
        if actual != expected:
            raise SystemExit(
                f"OMAKE.BIN plate scale at 0x{offset:x}: "
                + ", ".join(f"0x{word:08x}" for word in actual)
            )
        struct.pack_into("<3I", buf, offset, MOVE(dst, src), NOP, NOP)

    # ...and rebuild the table it reads, from measured English widths.
    race_by_offset = dict(zip(race_offsets, races))
    demons = NT.DEMONS
    widest = (0, "")
    plate = bytearray()
    for row in range(OMAKE_ROWS):
        race_pointer = struct.unpack_from("<I", buf, OMAKE_RACE_PTRS + row * 4)[0]
        race = race_by_offset[race_pointer - OVERLAY_BASE]
        demon = demons[buf[OMAKE_ROW_DEMON + row]]
        text = _text_width(race, label="OMAKE.BIN races") + OMAKE_NAME_GAP + \
               _text_width(demon, label="OMAKE.BIN demons")
        half = -(-(text + 2) // 2)          # 3px of slack on each side
        if half > 0xFF:
            raise SystemExit(
                f"OMAKE.BIN plate: {race} {demon} needs half-width {half}"
            )
        widest = max(widest, (text, f"{race} {demon}"))
        plate.append(half)
    surface = OMAKE_PLATE_PAD + widest[0]
    if surface > OMAKE_SURFACE_WIDTH:
        raise SystemExit(
            f"OMAKE.BIN plate: {widest[1]!r} needs {surface}px of the "
            f"{OMAKE_SURFACE_WIDTH}px text surface"
        )
    buf[OMAKE_PLATE_TABLE:OMAKE_PLATE_TABLE + OMAKE_ROWS] = plate
    return widest, surface


def _patch_omake_defeat(buf):
    """Print DEFEAT without the Compendium's registration bit.

    The enhanced build stores "registered in the Compendium" in bit 7 of the
    stock per-demon analysis counter (compendium.DEMON_FLAGS), which is the very
    byte this screen prints as DEFEAT -- so a demon that was only ever fused
    reads 128.  Masking the byte restores the true 0..127 tally.  The stock
    routine reloads the counter separately for each digit, so the whole block is
    rebuilt around a single masked read held in s3 (its stock use, the table
    base, dies with the last load).
    """
    lo = OMAKE_DEFEAT_TABLE & 0xFFFF
    hi = (OMAKE_DEFEAT_TABLE >> 16) + (1 if lo & 0x8000 else 0)
    hundreds_x, tens_x, ones_x = OMAKE_DEFEAT_DIGIT_X

    def move_pen(x):
        return [
            MOVE(A0, OMAKE_CTX), ADDIU(A1, ZERO, x),
            JAL(OMAKE_SET_PEN), ADDIU(A2, ZERO, OMAKE_DEFEAT_Y),
        ]

    def print_digit(reg):
        # reg holds digit*4; OMAKE_DIGITS is a table of glyph-string pointers.
        return [
            ADDU(reg, reg, OMAKE_DIGITS), LW(A1, 0, reg),
            JAL(OMAKE_PRINT), MOVE(A0, OMAKE_CTX),
        ]

    load = [
        LW(V0, OMAKE_ROW_INDEX, S2),        # current row
        LUI(A0, hi),
        ADDU(V0, V0, S1),                   # 0x801e6424 + row
        LBU(V1, 0, V0),                     # demon id
        ADDIU(A0, A0, lo),
        ADDU(V1, V1, A0),
        LBU(S3, 0, V1),                     # stock analysis counter
        NOP,
        ANDI(S3, S3, 0x7F),                 # drop the registration bit
    ]
    hundreds = [
        SLTIU(V0, S3, 100),
        None,                               # bnez v0, tens (patched below)
        NOP,
    ] + move_pen(hundreds_x) + [
        LUI(V1, 0x51EB), ORI(V1, V1, 0x851F),
        MULTU(S3, V1), MFHI(V0), SRL(V0, V0, 5),   # v0 = count / 100
        SLL(V0, V0, 2),
    ] + print_digit(V0)
    tens = [
        SLTIU(V0, S3, 10),
        None,                               # bnez v0, ones (patched below)
        NOP,
    ] + move_pen(tens_x) + [
        LUI(V1, 0x51EB), ORI(V1, V1, 0x851F),
        MULTU(S3, V1), MFHI(V1), SRL(V1, V1, 5),   # v1 = count / 100
        SLL(V0, V1, 1), ADDU(V0, V0, V1), SLL(V0, V0, 3),
        ADDU(V0, V0, V1), SLL(V0, V0, 2),          # v0 = 100 * (count / 100)
        SUBU(A2, S3, V0),                          # count % 100
        ANDI(A2, A2, 0xFF),
        MULTU(A2, OMAKE_DIV10), MFHI(A2), SRL(A2, A2, 3),
        SLL(A2, A2, 2),
    ] + print_digit(A2)
    ones = move_pen(ones_x) + [
        MULTU(S3, OMAKE_DIV10), MFHI(V0), SRL(V0, V0, 3),   # count / 10
        SLL(V1, V0, 2), ADDU(V1, V1, V0), SLL(V1, V1, 1),   # 10 * (count / 10)
        SUBU(V0, S3, V1),                                   # count % 10
        SLL(V0, V0, 2),
    ] + print_digit(V0)

    words = load + hundreds + tens + ones
    tens_at = len(load) + len(hundreds)
    ones_at = tens_at + len(tens)
    words[len(load) + 1] = BNEZ(V0, tens_at - (len(load) + 1) - 1)
    words[tens_at + 1] = BNEZ(V0, ones_at - (tens_at + 1) - 1)

    capacity = 0x180 // 4               # the stock DEFEAT block, instruction for instruction
    if len(words) > capacity:
        raise SystemExit(
            f"OMAKE.BIN DEFEAT: {len(words)} instructions exceed {capacity}"
        )
    words += [NOP] * (capacity - len(words))
    _write_code(buf, OMAKE_DEFEAT, words, OMAKE_DEFEAT_SHA256,
                label="OMAKE.BIN DEFEAT counter")


def patch_omake(source):
    """Translate the private race/demon lists used by the bonus viewer."""
    buf = bytearray(source)
    # This viewer stops at Virus and also omits Godly, Avatar, and Element.
    # Warrior, Divine General, and Fiend are absent from its private list.
    races = [
        race for index, race in enumerate(NT.RACES)
        if index not in {0, 6, 8, 41, 42, 43}
    ]
    races.reverse()
    slots = _aligned_slots(buf, 0x000, len(races), 0x144, label="OMAKE.BIN races")
    if slots[0][2] != "ウイルス" or slots[-1][2] != "大天使":
        raise SystemExit("OMAKE.BIN races: unexpected table order")
    _slots, race_offsets = _repack_table(
        buf, 0x000, len(races), 0x144, races, label="OMAKE.BIN races"
    )
    _patch_demon_table(buf, 0x144, 0xDDC, label="OMAKE.BIN demons")
    if WIDTHS10 is not None:
        _patch_omake_plate(buf, races, race_offsets)
        if ENHANCEMENTS:
            # Stock builds never set bit 7, so the raw byte is already correct.
            _patch_omake_defeat(buf)
    return bytes(buf)


def patch_rag(source):
    """Translate Rag's private Earthies material label."""
    buf = bytearray(source)
    # RAG reaches the hooked stock printer through the shop helper at 0x80045714.
    _patch_slot(buf, 0x008, 0x10, "アーシーズ", "Earthies", label="RAG.BIN")
    return bytes(buf)
