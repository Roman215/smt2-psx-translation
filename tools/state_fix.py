#!/usr/bin/env python3
"""Repair a DuckStation SMT2 save state poisoned by the Rag's Jewelry crash.

Background (see build._patch_empty_party_plate_guard and overlay_text.patch_rag):

* The engine keeps the "currently open window object" in the global at
  0x801ce380.  Every menu, quick menu, battle command window and terminal
  prompt goes through the switcher at 0x800210a8, which tears the current
  object down via ``jalr *(obj+8)`` before installing the new one.
* Rag's demon list copies a sixth name past its five name slots, to RAM
  address 1.  The party panel then draws the bytes at address 0 as the
  "name" of every EMPTY party slot, and with an English name parked there the
  sixth plate's glyph shadows run over the globals after its buffer, ORing
  two colour-2 pixels into that pointer (0x800ea394 -> 0x802ea3b4).  RAM is
  mirrored at 0x80200000, so the switcher then runs the handlers of whatever
  sits 0x20 bytes past the real object: a hang (Roppongi report) or an
  endlessly re-opened sort menu (dismissing a demon after recruiting one).

This tool:

1. strips the two pixel bits from the window-object pointer;
2. clears the parked name at RAM address 1.. (the pointer word at 0 is a
   routine engine store and is left alone);
3. restores the other trampled globals in 0x801ce350..0x801ce38b to their
   healthy values;
4. applies the party-plate NULL-name guard to the state's in-RAM copy of the
   game code, so the next panel redraw cannot poison the pointer again (a save
   state carries its own copy of the executable);
5. if the Rag's overlay is resident, caps its list loop the same way the
   rebuilt disc does.

A state captured *after* the hang cannot be repaired: the CPU is already in
the BIOS.  Repaired states still carry the old code for everything else until
the game is rebooted from a rebuilt image.

Usage:  python tools/state_fix.py <state file> [-o out] [--check]
        (default output: fixed/<same file name>, ready to drop back into
        DuckStation's savestates folder)
"""
import argparse
import os
import struct
import sys

import zstandard as zstd

SLOT = 0x801CE380
GOOD = 0x800EA394
PIXEL_BITS = 0x00200020
# First bytes of the game's own EXE image, used to locate main RAM inside the
# decompressed state blob without depending on DuckStation's struct layout.
EXE_ANCHOR = b"\\BIN\\CMDINIT.BIN"    # first bytes of SLPM_869.24's load image
EXE_LOAD = 0x80010000
# Sanity check for the located base: first handler of the field window object.
BASE_CHECK = (0x800EA394, 0x8002D7F0)

# Party plate routine 0x80047558: `lbu $v0, 0($s1)` -> `move $v0, $s1`.
PLATE_TEST = 0x8004757C
PLATE_TEST_STOCK = 0x92220000
PLATE_TEST_FIXED = 0x02201021
# Rag's overlay (base 0x801e40f8) list loop: `sltiu $v0,$s1,0x10` -> `sltiu $v0,$s2,4`.
RAG_TEST = 0x801E499C
RAG_TEST_STOCK = 0x2E220010
RAG_TEST_FIXED = 0x2E420004
RAG_TEST_PREV = (0x801E4998, 0x3252FFFF)   # andi $s2, $a1, 0xffff -- overlay identity check

# Globals under the sixth plate's overflow.  0x801ce350..0x801ce35b are hit by
# the harmless two-glyph draw in every save; the rest are zero in a healthy
# save except the two flags below (always 1) and 0x801ce360 (0 or 2).
TRAMPLE_START, TRAMPLE_END = 0x801CE350, 0x801CE38C
HEALTHY = {0x801CE368: 1, 0x801CE370: 1}
KEEP_IF_SMALL = {0x801CE360}          # legit values 0/2 are indistinguishable from junk
PARKED_NAME = (4, 0x40)               # RAM bytes to clear (address 0 holds a pointer)


def _header(data):
    """Return (offset, compressed size, uncompressed size, compression type)."""
    if data[:4] != b"DUCC":
        raise SystemExit("not a DuckStation save state (missing DUCC magic)")
    version = struct.unpack_from("<I", data, 4)[0]
    path_len, path_off = struct.unpack_from("<2I", data, 0xA8)
    shot_size, shot_off = struct.unpack_from("<2I", data, 0xC0)
    ctype, csize, usize = struct.unpack_from("<3I", data, 0xC8)
    off = shot_off + shot_size
    if path_off + path_len > shot_off or off + csize != len(data):
        raise SystemExit(f"unrecognized save-state layout (version {version})")
    return off, csize, usize, ctype


def _ram_base(blob, exe_image):
    anchor = exe_image[:64] if exe_image else EXE_ANCHOR
    at = -1
    while True:
        at = blob.find(anchor, at + 1)
        if at < 0:
            raise SystemExit("could not locate the game's RAM image in the state")
        base = at - (EXE_LOAD - 0x80000000)
        probe = base + (BASE_CHECK[0] - 0x80000000)
        if base >= 0 and probe + 4 <= len(blob) and \
                struct.unpack_from("<I", blob, probe)[0] == BASE_CHECK[1]:
            return base


class Ram:
    def __init__(self, blob, base):
        self.blob, self.base, self.changes = blob, base, []

    def off(self, addr):
        # Main RAM (2 MiB) is mirrored four times in KSEG0, so a poisoned
        # 0x802xxxxx pointer reads the same bytes the console would.
        return self.base + ((addr - 0x80000000) & 0x1FFFFF)

    def is_object(self, addr):
        """True if addr looks like a window object: handler code pointers."""
        if addr & 3 or not (0x800E0000 <= addr < 0x80120000):
            return False
        words = [self.u32(addr + 4 * i) for i in range(3)]
        code = lambda w: 0x80010000 <= w < 0x800E0000 and w & 3 == 0
        return code(words[0]) and code(words[2])   # +8 is what the switcher calls

    def u32(self, addr):
        return struct.unpack_from("<I", self.blob, self.off(addr))[0]

    def set32(self, addr, value, label):
        old = self.u32(addr)
        if old != value:
            struct.pack_into("<I", self.blob, self.off(addr), value)
            self.changes.append(f"{label}: {addr:#010x} {old:#010x} -> {value:#010x}")

    def set8(self, addr, value, label):
        old = self.blob[self.off(addr)]
        if old != value:
            self.blob[self.off(addr)] = value
            self.changes.append(f"{label}: {addr:#010x} {old:#04x} -> {value:#04x}")


def repair(ram):
    """Apply every repair; returns True if the pointer was (or is) sane."""
    current = ram.u32(SLOT)
    stripped = current & ~PIXEL_BITS
    # Only the low pixel (bit 5) is ambiguous: window objects are packed
    # 12-byte handler triples, so both `current` and `current & ~0x20` can be
    # real objects (seen in a state parked on the "who leaves?" menu, where the
    # pointer legitimately ended in 0xac).  A set high pixel (0x00200000) is
    # never legitimate for this table.
    if current == stripped or (not current & 0x00200000 and ram.is_object(current)):
        if current != stripped:
            print(f"{SLOT:#010x} = {current:#010x}: valid object, keeping it "
                  f"({stripped:#010x} is also an object; overflow did not reach it)")
        else:
            print(f"{SLOT:#010x} = {current:#010x} (already valid)")
        ok = True
    elif ram.is_object(stripped):
        ram.set32(SLOT, stripped, "window-object pointer")
        ok = True
    else:
        print(f"WARNING: {SLOT:#010x} = {current:#010x} is not the known pattern; "
              f"forcing {GOOD:#010x}", file=sys.stderr)
        ram.set32(SLOT, GOOD, "window-object pointer")
        ok = False

    # The parked demon name (RAM address 1..) that the empty plates keep drawing.
    lo, hi = PARKED_NAME
    if any(ram.blob[ram.base + lo:ram.base + hi]):
        ram.changes.append(f"parked name at RAM 0x{lo:x}..0x{hi:x} cleared: "
                           f"{bytes(ram.blob[ram.base:ram.base + 0x18]).hex(' ')}")
        ram.blob[ram.base + lo:ram.base + hi] = bytes(hi - lo)

    # Globals under the overflow.
    for addr in range(TRAMPLE_START, TRAMPLE_END):
        if SLOT <= addr < SLOT + 4:
            continue
        cur = ram.blob[ram.off(addr)]
        word = addr & ~3
        if word in HEALTHY:
            want = HEALTHY[word] if addr == word else 0
        elif word in KEEP_IF_SMALL and addr == word and cur in (0, 2):
            want = cur
        elif (cur & 0xF) not in (0, 1, 2) or (cur >> 4) not in (0, 1, 2):
            want = cur               # nibble outside the pixel palette: real data
        else:
            want = 0
        ram.set8(addr, want, "trampled global")

    # In-RAM code: the party plate guard (the state carries its own exe copy).
    if ram.u32(PLATE_TEST) == PLATE_TEST_STOCK:
        ram.set32(PLATE_TEST, PLATE_TEST_FIXED, "party plate NULL-name guard")
    elif ram.u32(PLATE_TEST) != PLATE_TEST_FIXED:
        print(f"WARNING: unexpected code at {PLATE_TEST:#x}: {ram.u32(PLATE_TEST):#010x}",
              file=sys.stderr)
    # Rag's overlay, only if resident right now.
    if ram.u32(RAG_TEST_PREV[0]) == RAG_TEST_PREV[1] and ram.u32(RAG_TEST) == RAG_TEST_STOCK:
        ram.set32(RAG_TEST, RAG_TEST_FIXED, "Rag's list cap (resident overlay)")
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("state")
    ap.add_argument("-o", "--out", help="output file (default: <state>.fixed)")
    ap.add_argument("--exe", help="optional SLPM_869.24 image to anchor RAM with")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args(argv)

    data = open(args.state, "rb").read()
    off, csize, usize, ctype = _header(data)
    if ctype != 2:
        raise SystemExit(f"unsupported state compression type {ctype} (expected zstd)")
    blob = bytearray(zstd.ZstdDecompressor().decompress(
        data[off:off + csize], max_output_size=usize))

    exe_image = None
    if args.exe:
        raw = open(args.exe, "rb").read()
        exe_image = raw[0x800:0x800 + 64] if raw[:8] == b"PS-X EXE" else raw[:64]
    ram = Ram(blob, _ram_base(blob, exe_image))

    repair(ram)
    for line in ram.changes:
        print(line)
    if not ram.changes:
        print("nothing to do")
        return 0
    if args.check:
        return 1

    packed = zstd.ZstdCompressor().compress(bytes(blob))
    out = bytearray(data[:off]) + packed
    struct.pack_into("<3I", out, 0xC8, ctype, len(packed), len(blob))
    path = args.out
    if not path:
        os.makedirs("fixed", exist_ok=True)
        path = os.path.join("fixed", os.path.basename(args.state))
    open(path, "wb").write(bytes(out))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
