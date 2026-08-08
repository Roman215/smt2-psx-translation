# -*- coding: utf-8 -*-
"""Alignment-driven rotation for the 2D-map player marker.

The blue marker on the overhead map is a SEVEN-FRAME sprite animation, not a 3D
model: a 16x16 SPRT_16 (GPU code 0x7c) drawn from texture page 0x063a (4bpp, VRAM
page 640,256) with CLUT 0x7880, always on texture row v=0x40, with the frames laid
out horizontally at u = 0x00,0x10 ... 0x60.  Frame 6 (u=0x60) is the one whose
arms are widest / fully sideways; u=0x70 is blank.

All of it lives in the 2DMAP.BIN overlay, which loads at 0x801e40f8 (file offset 0
maps to that address -- note this is NOT overlay_text.OVERLAY_BASE, which is
3DMAP's).  Stock behaviour, inlined at four separate draw sites:

    counter @0x801ea9d8            +2 per frame while the map scrolls, +1 idle
    frame   = (counter / 2) % 7    signed div-by-7, magic 0x92492493
    u       = frame * 16           then andi 0xf0

so the marker always turns the same way regardless of alignment.  In other SMT
games the spin encodes alignment: clockwise for Law, counter-clockwise for Chaos,
and a Neutral zig-zag that rocks around the sideways frame without ever turning
past it.

Rather than rewrite the div-by-7 at every draw site, this patch keeps the stock
counter untouched and adds a SHADOW word holding `frame * 2`.  Every draw site
still computes `(x / 2) % 7`, which for a shadow of `frame * 2` yields `frame`
unchanged -- so one hook plus four load-offset edits covers everything, and the
rotation speed (including the existing 2x spin while walking) is identical in all
three cases.

Thresholds are the game's own.  Three sites in the exe classify the alignment byte
at 0x801fc8d7 -- 0x8008e0d8, 0x8007d3a8 and 0x800857c4 all do `lhu 0x801fc8d6;
srl 8` then compare against 112 and 144 -- and the same pair classifies the demon
table's alignment column at 0x801046de + id*32 + 11.  So:

    align <  112   LAW      clockwise      frame = t % 7
    112..143       NEUTRAL  zig-zag        frame = ZIGZAG[t % 8]
    align >= 144   CHAOS    anticlockwise  frame = 6 - (t % 7)
"""

import hashlib
import struct

from compendium import _Asm, _foff


# ---- 2DMAP.BIN -------------------------------------------------------------------
OVERLAY_SECTOR = 66992
OVERLAY_SIZE = 59632
OVERLAY_BASE = 0x801E40F8          # file offset 0 -> this address

COUNTER = 0x801EA9D8               # stock rotation counter (overlay BSS)
MODE_BYTE = 0x801EA9DC             # byte the hook displaces a load of

# The overlay's only free run inside its loaded image: 40 zero bytes that stay
# zero at runtime (verified in two savestates).  Only the first word is used.
SHADOW = 0x801EA358
SHADOW_HOLE_END = 0x801EA380

HOOK = 0x801E8C28                  # common continuation after the counter bump

# The four draw sites that compute (counter/2) % 7 for the marker.  Deliberately
# NOT included: 0x801e8c4c, which feeds (counter/8) % 4 at texture row v=0x50 for a
# different icon, and 0x801e98c4, which draws at v=0x90.
MARKER_LOADS = (0x801E8D70, 0x801E8E3C, 0x801E8F28, 0x801E9004)

# ---- exe side --------------------------------------------------------------------
# The orphaned original Japanese map-name block.  map_names.relocate_map_names
# moves every English name into the font cave and repoints both pointer tables
# (AREA 0x80119978 x17, MAP 0x8011a084 x512), leaving this rodata unreferenced.
# Verified on the built exe: AREA keeps 0 pointers into the block and MAP keeps 11
# entries covering 2 strings; a live pointer sub-table and its targets occupy
# 0x80016220..0x800162de.
#
# The cave deliberately starts well past that, at the first run of pure orphaned
# SJIS names.  0x800162c0..0x800162ec is NOT free: it holds live numeric records
# (paired counts and signed deltas) and the word 0x801e40f8 -- the 2DMAP overlay's
# own load address -- reached by computed offsets rather than absolute pointers,
# so a pointer scan does not see it.  Nothing is claimed below 0x80016300.  The
# helper and its eight-byte table occupy exactly 0x108 bytes; the following
# orphaned names are reserved by build.py's universal instant-text patch.
CAVE = 0x80016300
CAVE_END = 0x80016408
# The stock block is left physically in place by relocate_map_names (only the two
# pointer tables move), so the guard is a pristine-source hash, not a zero check.
CAVE_SOURCE_SHA256 = "f531b9b6939cf52e7d05f9fec8905dd2ec5f839e4a83d6168f4ae6aea222eaa5"

ALIGN_BYTE = 0x801FC8D7            # party slot 0 + 0x2f
LAW_BELOW = 112
CHAOS_FROM = 144

# 7 -> 1 -> 2 -> 1 -> 7 -> 6 -> 5 -> 6 in one-based frame numbers.  Rocks two
# frames either side of the widest/sideways frame and never turns past it.
ZIGZAG = (6, 0, 1, 0, 6, 5, 4, 5)

FRAMES = 7


def _hi(address):
    return ((address >> 16) + (1 if address & 0x8000 else 0)) & 0xFFFF


def _lo(address):
    return address & 0xFFFF


def _sra(a, rd, rt, sa):
    """_Asm has sll but not sra."""
    a.word((a.R[rt] << 16) | (a.R[rd] << 11) | (sa << 6) | 0x03)


def build_helper(base=CAVE):
    """Assemble the once-per-frame shadow updater.

    Runs from the hook at 0x801e8c28, immediately after the stock counter bump and
    before any marker draw, so a single call covers every site.  Only v0, v1, at
    and t0 are touched: v0 is reloaded by the displaced code's successor, t0 is
    dead, at is scratch, and v1 is restored to the value the displaced `lbu` would
    have produced.  `ra` is free because the enclosing function spilled it in its
    prologue and calls other routines anyway.
    """
    a = _Asm(base)
    zz = base + 0x100                       # table parked past the code

    a.lui("at", _hi(ALIGN_BYTE))
    a.lbu("t0", _lo(ALIGN_BYTE), "at")      # t0 = alignment byte
    a.lui("at", _hi(COUNTER))
    a.lw("v0", _lo(COUNTER), "at")          # v0 = stock counter
    _sra(a, "v0", "v0", 1)                  # v0 = t = counter / 2 (counter >= 0)

    a.sltiu("at", "t0", LAW_BELOW)
    a.bne("at", "zero", "law")
    a.sltiu("at", "t0", CHAOS_FROM)         # delay slot; branch operands already read
    a.beq("at", "zero", "chaos")
    a.nop()

    # ---- neutral: rock around the sideways frame, period 8
    a.andi("v0", "v0", 7)
    a.lui("at", _hi(zz))
    a.addu("at", "at", "v0")
    a.lbu("v1", _lo(zz), "at")
    a.beq("zero", "zero", "store")          # unconditional
    a.nop()

    # ---- law: clockwise
    a.label("law")
    a.addiu("at", "zero", FRAMES)
    a.divu("v0", "at")
    a.nop()
    a.nop()
    a.mfhi("v1")                            # v1 = t % 7
    a.beq("zero", "zero", "store")
    a.nop()

    # ---- chaos: anticlockwise
    a.label("chaos")
    a.addiu("at", "zero", FRAMES)
    a.divu("v0", "at")
    a.nop()
    a.nop()
    a.mfhi("v1")
    a.addiu("v0", "zero", FRAMES - 1)
    a.subu("v1", "v0", "v1")                # v1 = 6 - (t % 7)

    a.label("store")
    a.sll("v1", "v1", 1)                    # shadow = frame * 2
    a.lui("at", _hi(SHADOW))
    a.sw("v1", _lo(SHADOW), "at")
    a.lui("at", _hi(MODE_BYTE))
    a.lbu("v1", _lo(MODE_BYTE), "at")       # restore the displaced load
    a.jr("ra")
    a.nop()

    code = bytearray(a.blob())
    if len(code) > 0x100:
        raise SystemExit(f"map marker: helper is {len(code)} bytes, overruns its table")
    blob = bytearray(code) + bytes(0x100 - len(code)) + bytes(ZIGZAG)
    if base + len(blob) > CAVE_END:
        raise SystemExit("map marker: helper overruns the orphaned map-name cave")
    return bytes(blob)


# Set by build.py: the marker rotation is a gameplay enhancement, so
# --no-enhancements leaves 2DMAP.BIN byte-identical to the original.
ENABLED = False


def _ovl(address):
    return address - OVERLAY_BASE


def patch_2dmap(source, base=CAVE):
    """Hook the overlay: call the helper once a frame, read the shadow four times."""
    if not ENABLED:
        return bytes(source)
    buf = bytearray(source)
    if len(buf) != OVERLAY_SIZE:
        raise SystemExit(f"2DMAP.BIN: expected {OVERLAY_SIZE} bytes, got {len(buf)}")

    def word(address):
        return struct.unpack_from("<I", buf, _ovl(address))[0]

    def put(address, value):
        struct.pack_into("<I", buf, _ovl(address), value)

    # The hole the shadow word lives in must really be spare.
    hole = bytes(buf[_ovl(SHADOW):_ovl(SHADOW_HOLE_END)])
    if hole.strip(b"\x00"):
        raise SystemExit(
            f"2DMAP.BIN: the spare run at {SHADOW:#x} is not zero-filled -- re-check")

    # Displace `lui t0, 0x801f` + `lbu v1, -0x5624(t0)` with a call.  The helper
    # re-does that load before returning, and nothing between here and the callee
    # relies on t0.
    if word(HOOK) != 0x3C08801F or word(HOOK + 4) != 0x9103A9DC:
        raise SystemExit(
            f"2DMAP.BIN: unexpected hook site at {HOOK:#x}: "
            f"{word(HOOK):#010x} {word(HOOK + 4):#010x}")
    put(HOOK, (0x03 << 26) | ((base >> 2) & 0x03FFFFFF))       # jal helper
    put(HOOK + 4, 0)                                            # nop (delay slot)

    # Repoint the four marker counter loads at the shadow.  Each site then computes
    # (shadow / 2) % 7 == frame, because the shadow holds frame * 2.
    for address in MARKER_LOADS:
        instruction = word(address)
        if (instruction >> 26) != 0x23 or (instruction & 0xFFFF) != _lo(COUNTER):
            raise SystemExit(
                f"2DMAP.BIN: {address:#x} is not the expected "
                f"`lw rX, -0x5628(rY)`: {instruction:#010x}")
        put(address, (instruction & 0xFFFF0000) | _lo(SHADOW))
    return bytes(buf)


def patch_exe(exe, base=CAVE):
    """Install the helper into the orphaned map-name block."""
    blob = build_helper(base)
    source = bytes(exe[_foff(CAVE):_foff(CAVE_END)])
    digest = hashlib.sha256(source).hexdigest()
    if digest != CAVE_SOURCE_SHA256:
        raise SystemExit(
            f"map marker: the orphaned map-name block at {CAVE:#x}..{CAVE_END:#x} "
            f"is not the pristine stock block (sha256 {digest}); relocate_map_names "
            "or the block layout changed -- re-verify that it is still unreferenced")
    start = _foff(base)
    exe[start:start + len(blob)] = blob
    return exe
