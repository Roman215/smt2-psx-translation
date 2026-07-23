"""Patch a DuckStation/SwanStation RZIP state with the current compendium code.

This is a temporary local verification helper, not part of the patch build.
"""

from pathlib import Path
import struct
import sys
import zlib

import compendium


RAM_OFFSET = 0x8F
RAM_BASE = 0x80000000
ICACHE_NAME = b"ICache_Bulk"


def read_rzip(path):
    packed = path.read_bytes()
    if packed[:8] != b"#RZIPv\x01#":
        raise SystemExit("not a v1 RZIP state")
    block_size = struct.unpack_from("<I", packed, 8)[0]
    raw_size = struct.unpack_from("<Q", packed, 12)[0]
    cursor = 20
    raw = bytearray()
    while len(raw) < raw_size:
        packed_size = struct.unpack_from("<I", packed, cursor)[0]
        cursor += 4
        raw += zlib.decompress(packed[cursor:cursor + packed_size])
        cursor += packed_size
    if len(raw) != raw_size:
        raise SystemExit(f"bad RZIP size: {len(raw)} != {raw_size}")
    return block_size, raw


def write_rzip(path, block_size, raw):
    packed = bytearray(b"#RZIPv\x01#")
    packed += struct.pack("<IQ", block_size, len(raw))
    for cursor in range(0, len(raw), block_size):
        block = zlib.compress(raw[cursor:cursor + block_size], 9)
        packed += struct.pack("<I", len(block))
        packed += block
    path.write_bytes(packed)


def ram_offset(address):
    return RAM_OFFSET + address - RAM_BASE


def patch_jump(raw, address, target):
    struct.pack_into(
        "<II",
        raw,
        ram_offset(address),
        (0x02 << 26) | ((target >> 2) & 0x03FFFFFF),
        0,
    )


def patch_call(raw, address, target):
    struct.pack_into(
        "<I",
        raw,
        ram_offset(address),
        (0x03 << 26) | ((target >> 2) & 0x03FFFFFF),
    )


def i_type(op, rs, rt, immediate):
    return ((op & 0x3F) << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (immediate & 0xFFFF)


def invalidate_instruction_cache(raw):
    """Force the emulator to refetch patched instructions from emulated RAM.

    Mednafen's serialized cache contains 1024 pairs of (tag, instruction).
    A patched savestate otherwise may continue executing the instruction that
    was cached before the state was captured, making RAM-only hooks appear not
    to run.
    """
    name_at = raw.find(ICACHE_NAME)
    if name_at < 0:
        raise SystemExit("savestate has no serialized instruction cache")
    size_at = name_at + len(ICACHE_NAME)
    size = struct.unpack_from("<I", raw, size_at)[0]
    if size != 0x2000:
        raise SystemExit(f"unexpected instruction-cache size: {size:#x}")
    data_at = size_at + 4
    for entry_at in range(data_at, data_at + size, 8):
        struct.pack_into("<I", raw, entry_at, 0xFFFFFFFF)


def main():
    source = Path(sys.argv[1])
    target = Path(sys.argv[2])
    block_size, raw = read_rzip(source)
    asm, code = compendium._emit_code()
    start = ram_offset(compendium.CAVE)
    raw[start:start + len(code)] = code
    extra_asm, extra_code = compendium._emit_extra_code()
    extra_start = ram_offset(compendium.EXTRA_CAVE)
    raw[extra_start:extra_start + len(extra_code)] = extra_code
    # Refresh the cave data area for the current prompt design: the browser
    # draws the item-target slot (0x1848), so the swap targets that slot now.
    prompt = b"\x1fSummon Cost:        Macca\x00\x00"
    raw[ram_offset(compendium.PROMPT):ram_offset(compendium.PROMPT) + 28] = prompt
    # These savestates were captured with the old build mid-browser: the old
    # code had already swapped its prompt into the Analyze slot (0x182c).
    # Restore that slot and capture pristine item-target bytes by rebuilding
    # both from their sys_strings wording.
    analyze = b"\x1fAnalyze whom?\x00"
    raw[ram_offset(0x8001102C):ram_offset(0x8001102C) + 28] = (
        analyze + bytes(28 - len(analyze))
    )
    original = bytes(
        raw[ram_offset(compendium.ORIGINAL_PROMPT):
            ram_offset(compendium.ORIGINAL_PROMPT) + 28]
    )
    if not original.startswith(b"\x1fUse it on whom?\x00"):
        original = bytes(
            raw[ram_offset(compendium.PROMPT_SLOT):
                ram_offset(compendium.PROMPT_SLOT) + 28]
        )
    if not original.startswith(b"\x1fUse it on whom?\x00"):
        raise SystemExit("item-target prompt slot has unexpected contents")
    raw[ram_offset(compendium.ORIGINAL_PROMPT):
        ram_offset(compendium.ORIGINAL_PROMPT) + 28] = original
    flag = struct.unpack_from("<I", raw, ram_offset(compendium.FLAG))[0]
    if flag == 2:
        raw[ram_offset(compendium.PROMPT_SLOT):
            ram_offset(compendium.PROMPT_SLOT) + 28] = prompt
        # Captures made in the browser have already passed the entry helper.
        # Hide the choice object directly; the dedicated dialogue-compositor
        # hook below suppresses the separate primitive that leaked its shared
        # texture into the lower panel.
        struct.pack_into(
            "<HHHH", raw,
            ram_offset(compendium.CATHEDRAL_CHOICE_WINDOW + 0x44),
            0, 0, 0, 0,
        )
        struct.pack_into(
            "<HHH", raw,
            ram_offset(compendium.CATHEDRAL_CHOICE_WINDOW + 0x56),
            0, 0, 0,
        )
        struct.pack_into(
            "<H", raw,
            ram_offset(compendium.CATHEDRAL_CHOICE_WINDOW + 0x8C),
            3,
        )
    # State10 predates the indexed-choice fix and still contains the obsolete
    # single-column resolver hook.  Restore those two stock instructions.
    struct.pack_into(
        "<II", raw, ram_offset(0x800579BC), 0x94821568, 0x3C04801D
    )
    # Restore obsolete resolver experiments before installing the active
    # two-column Cathedral selection hook.
    struct.pack_into(
        "<II", raw, ram_offset(0x80057F44), 0x94840000, 0x8CC315E0
    )
    struct.pack_into(
        "<II", raw, ram_offset(0x80057E90), 0x94850000, 0x8CC215E0
    )
    struct.pack_into(
        "<II", raw, ram_offset(0x80057D8C), 0x94440000, 0x24A57568
    )
    # Restore the obsolete Cathedral callback hook used by the first
    # compendium prototype; current builds intercept the deferred event target
    # in the main update loop instead.
    struct.pack_into(
        "<II", raw, ram_offset(0x80068D30), 0x94430000, 0x24A57568
    )
    # The superseded prototype bypassed the stock sort chooser.  Restore its
    # overwritten instructions so current code retains the four sort options.
    struct.pack_into(
        "<II", raw, ram_offset(compendium.LEGACY_SORT_MENU_CHECK),
        0x8E26D8FC, 0x24020009,
    )
    # Remove the superseded lower-renderer guard from states captured with the
    # previous build.  The actual fault is the still-open Cathedral choice
    # layer sharing texture storage with the blue sort chooser.
    struct.pack_into(
        "<II", raw, ram_offset(compendium.LEGACY_LOWER_SORT_RENDER),
        0x27BDFFD0, 0xAFB20018,
    )
    for address, label in {
        0x8005B918: "menu_start",
        0x8005B97C: "menu_loop",
        0x800545B0: "event_update",
        0x801FADB4: "availability",
        0x8007F374: "initial_scan",
        compendium.GRANT_DEMON: "grant",
        0x8007F59C: "selection",
    }.items():
        patch_jump(raw, address, asm.labels[label])
    patch_call(
        raw,
        compendium.ANALYSIS_LIST_UPDATE_CALL,
        asm.labels["price_update"],
    )
    patch_call(
        raw,
        compendium.CATHEDRAL_DIALOGUE_UPDATE_CALL,
        extra_asm.labels["cathedral_dialogue_update"],
    )
    patch_call(
        raw,
        compendium.PROMPT_RENDER_CALL,
        extra_asm.labels["dynamic_prompt"],
    )
    if len(sys.argv) > 3 and sys.argv[3] == "--trace-choice":
        # Tag each possible event-pointer commit site in a different scratch
        # word.  The handlers use 0x801d as their live global-data base, so
        # these diagnostic words deliberately live at 0x801d7240 rather than
        # beside the injected code at 0x800d7240.  Store the selected offset
        # itself; a zero marker would be indistinguishable from untouched RAM.
        # Replacing the ADDU invalidates that one selection in this disposable
        # state, but identifies the path without touching memory-card data.
        for address, word in {
            0x800579C4: i_type(0x2B, 4, 2, 0x7240),  # sw v0,7240(a0)
            0x80057D94: i_type(0x2B, 6, 4, 0x7244),  # sw a0,7244(a2)
            0x80057EA0: i_type(0x2B, 6, 5, 0x7248),  # sw a1,7248(a2)
            0x80057F50: i_type(0x2B, 6, 4, 0x724C),  # sw a0,724c(a2)
        }.items():
            struct.pack_into("<I", raw, ram_offset(address), word)
    invalidate_instruction_cache(raw)
    write_rzip(target, block_size, raw)
    print(
        f"wrote {target} with {len(code) + len(extra_code)} bytes "
        "of current compendium code"
    )


if __name__ == "__main__":
    main()
