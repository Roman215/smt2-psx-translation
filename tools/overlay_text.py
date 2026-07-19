"""English text for executable overlays that carry private string tables.

Most UI text is resident in SLPM_869.24 or PACKA.BIN, but several overlays keep
their own raw Shift-JIS copies.  These strings use the same stock printer as the
main executable, so the global 0x1f ASCII wrapper installed by build.py works here
too (the boot disclaimer already relies on the same behavior).

The casino and bonus-viewer name lists deliberately reuse name_tables.py.  Keeping
one canonical spelling list prevents these rarely visited screens from drifting
away from the names shown in battle and the main menus.
"""

import struct

import name_tables as NT


ASCII_MARKER = 0x1F


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


OVERLAY_BASE = 0x801E4000


def _repack_table(buf, start, count, expected_end, english, *, label):
    """Repack an aligned raw-name table and retarget its absolute pointers.

    English is smaller overall, but a few individual names are longer than their
    Japanese slots.  Repacking the complete private bank avoids abbreviations while
    keeping its start/end addresses and every following overlay structure fixed.
    """
    slots = _aligned_slots(buf, start, count, expected_end, label=label)
    if len(english) != count:
        raise SystemExit(f"{label}: {len(english)} translations for {count} entries")

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
    return slots


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


def patch_omake(source):
    """Translate the private race/demon lists used by the bonus viewer."""
    buf = bytearray(source)
    # This viewer omits Godly, Avatar, Element, and Fiend from its race list.
    races = [
        race for index, race in enumerate(NT.RACES)
        if index not in {0, 6, 8, 41}
    ]
    races.reverse()
    slots = _aligned_slots(buf, 0x000, len(races), 0x144, label="OMAKE.BIN races")
    if slots[0][2] != "ウイルス" or slots[-1][2] != "大天使":
        raise SystemExit("OMAKE.BIN races: unexpected table order")
    _repack_table(buf, 0x000, len(races), 0x144, races, label="OMAKE.BIN races")
    _patch_demon_table(buf, 0x144, 0xDDC, label="OMAKE.BIN demons")
    return bytes(buf)


def patch_rag(source):
    """Translate Rag's private Earthies material label."""
    buf = bytearray(source)
    # RAG reaches the hooked stock printer through the shop helper at 0x80045714.
    _patch_slot(buf, 0x008, 0x10, "アーシーズ", "Earthies", label="RAG.BIN")
    return bytes(buf)
