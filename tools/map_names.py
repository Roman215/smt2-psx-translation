# -*- coding: utf-8 -*-
"""SMT2 field/location names (shown on the SAVE/LOAD file list + area displays).

These are ~144 unique raw-SJIS strings in the exe (block 0x80016124-0x80016c6c),
referenced by TWO absolute-pointer tables:
  - AREA table @0x80119978, 17 entries  (region names: Valhalla, Arcadia, ... Sefirot)
  - MAP  table @0x8011a084, 512 entries (per-map-ID location names; many IDs share a name)
The save screen looks up the map ID -> pointer -> string. The control char 0x8197 (shown
as '@' below) is a LINE-BREAK in the name display (that's why "Valhalla / -Downtown"
renders on two lines).

English names run longer than the katakana, so we RELOCATE the translated strings into
the free rodata font-placeholder cave and REPOINT both tables. No code changes.

Cave: 0x800d7500 .. 0x800d8300.  The following 0x800d8300 .. 0x800d8500 range is
reserved for the marker-based one-byte system-string printer and its ASCII/SJIS table.

Translation notes: dropped the redundant "旧" (former) prefix (all of Tokyo is ruined),
'@' = line break so long names split Name/Floor for the ~2-line display, Kabbalah Sefirot
spellings (Keter/Chokmah/Binah/Chesed/Geburah/Tiferet/Netzach/Hod/Yesod/Malkuth), and the
Atziluth/Beriah/Yetziratic "corridor"->Hall. Tweak any string below + re-run build.py.
"""

import struct
import build_en_tree as ET

AREA_TABLE = 0x80119978
AREA_COUNT = 17
MAP_TABLE = 0x8011a084
MAP_COUNT = 512
STR_LO, STR_HI = 0x80016000, 0x80017000     # original string block bounds
CAVE_LO, CAVE_HI = 0x800d7500, 0x800d8300    # 0x800d8300+ reserved by build.py
BR = 0x8197                                   # line-break control char

# English for each unique string, in ASCENDING-ADDRESS order (must be exactly 144 long).
# None = leave the original pointer untouched (empty slot / already-English "NEW GAME").
# '@' becomes the 0x8197 line-break.
ENGLISH = [
    # --- region names (AREA table targets) ---
    "Malkuth", "Yesod", "Netzach", "Hod", "Tiferet", "Chesed", "Geburah",
    "Chokmah", "Binah", "Keter", "Eden", "Underworld", "Arcadia", "Factory",
    "Holy Town", "Center", "Valhalla",
    # --- dungeons / maps ---
    "Diamond@Realm", "Gov Bldg@18F", "Imperial@Palace", "Gov Bldg@1F", "Gov Bldg@15F",
    "Tokyo Twr@30F", "Ichigaya@1F", "Tokyo Twr@45F", "Tokyo Twr@1F", "Ichigaya@B1",
    "Ark 3F", "Ark 2F", "Ark 4F", "Hyperspace", "Ark 1F",
    "Chokmah@Twr 4F", "Chokmah@Twr 3F", "Chokmah@Twr 2F", "Chokmah@Twr 1F",
    "Atziluth@Hall B2", "Binah Town", "Atziluth@Hall B1",
    "Geburah@Fort 1F", "Geburah@Fort B2", "Chesed@Temple", "Geburah@Fort B1",
    "Beriah@Hall B1", "Beriah@Hall B2",
    "Keter@Castle 8F", "Keter@Castle 9F", "Keter@Castle 7F", "Keter@Castle 6F",
    "Keter@Castle 5F", "Keter@Castle 4F", "Keter@Castle 3F", "Keter@Castle 1F",
    "Keter@Castle 2F",
    "Inside@Abaddon", "Yetzirah@Hall B2", "Yetzirah@Hall B1", "Netzach@Town",
    "Roppongi", "Yesod Town",
    "Sealed@Cave B4", "Sealed@Cave B3", "Sealed@Cave B2", "Sealed@Cave B1", "Sealed@Cave 1F",
    "Kojimachi@4F", "Kojimachi@3F", "Kojimachi@2F", "Kojimachi@1F",
    "Tiferet@Town", "Otemachi",
    "Shibuya@2F", "Shibuya@3F", "Shibuya@1F",
    "Roppongi@B2", "Roppongi@B1", "Roppongi@1F",
    "Akasaka@B4", "Akasaka@B2", "Akasaka@B3", "Akasaka@1F",
    "Shinjuku@B1", "Shinjuku@B3", "Shinjuku@B2", "Shinjuku@1F", "Suidobashi",
    "Arcadia@to Center", "Factory@to Center", "Valhalla@to Center", "Holy Town@to Center",
    "E.Shinjuku@2F", "E.Shinjuku@1F", "E.Shinjuku@3F",
    "Center@22F", None, None, "Center@21F", "Center@20F",
    "Watch Twr@12F", "Watch Twr@11F", "Watch Twr@13F", "Watch Twr@10F", "Watch Twr@9F",
    "Watch Twr@8F", "Watch Twr@7F", "Watch Twr@6F", "Watch Twr@5F", "Watch Twr@4F",
    "Watch Twr@3F", "Watch Twr@2F", "Watch Twr@1F",
    "Prison@B1", "Dig Site@Bottom",
    "Valhalla@Tunnel B7", "Factory@Town", "Factory@Terminal", "Arcadia@Terminal",
    "Worker@Dorm", "Prison@1F",
    "Dig Site@B3", "Dig Site@B2", "Dig Site@B1", "Dig Site@1F", "Holy Town",
    "Cathedral@B60", "Cathedral@3F", "Cathedral@2F", "Cathedral@1F",
    "Arcadia@5F", "Arcadia@4F", "Arcadia@3F", "Arcadia@2F", "Arcadia@1F", "Arcadia@Homes",
    "Virtual@Space", "Madam's@Manor", "Colosseum", "Valhalla@Terminal", "Hod Town",
    "Valhalla@Tunnel B2", "Valhalla@Downtown", "Big Gym",
    "Valhalla@Slums 1F", "Valhalla@Slums B1",
]


def _foff(a):
    return (a - 0x80010000) + 0x800


def _enc(s):
    """English (with '@' line-breaks) -> SJIS bytes."""
    out = bytearray()
    for ch in s:
        if ch == '@':
            out += struct.pack(">H", BR)
        else:
            out += struct.pack(">H", ET.fullwidth(ch))
    return bytes(out)


def _read_table(exe, base, count):
    return [struct.unpack_from("<I", exe, _foff(base) + i * 4)[0] for i in range(count)]


def relocate_map_names(exe):
    """Translate the field/location names, write them into the rodata cave, and repoint
    the AREA + MAP pointer tables. exe is a bytearray of the SLPM file."""
    area = _read_table(exe, AREA_TABLE, AREA_COUNT)
    mapt = _read_table(exe, MAP_TABLE, MAP_COUNT)
    uniq = sorted({p for p in area + mapt if STR_LO <= p < STR_HI})
    if len(uniq) != len(ENGLISH):
        raise SystemExit(f"map_names: expected {len(uniq)} unique strings, ENGLISH has {len(ENGLISH)}")

    # write English strings into the cave; build old-addr -> new-addr map
    remap = {}
    pos = CAVE_LO
    for addr, en in zip(uniq, ENGLISH):
        if en is None:
            continue
        data = _enc(en) + b"\x00"
        if pos + len(data) > CAVE_HI:
            raise SystemExit(f"map_names: cave overflow at {en!r} ({pos:#x}+{len(data)} > {CAVE_HI:#x})")
        exe[_foff(pos):_foff(pos) + len(data)] = data
        remap[addr] = pos
        pos += len(data)

    # repoint both tables (entries whose target we relocated)
    for base, count in ((AREA_TABLE, AREA_COUNT), (MAP_TABLE, MAP_COUNT)):
        for i in range(count):
            o = _foff(base) + i * 4
            old = struct.unpack_from("<I", exe, o)[0]
            if old in remap:
                struct.pack_into("<I", exe, o, remap[old])
    return pos - CAVE_LO  # bytes used in the cave
