"""Patch the pre-rendered 4bpp labels used by the status and equipment screens.

These UIs' static captions are not strings.  Each screen has its own 256x256,
4bpp texture embedded in PACKA.BIN; all are uploaded to VRAM at (704, 256).
English is drawn with the game's own 8x10 uppercase font and each texture's
native foreground/shadow palette indices, so the replacements match HP/MP/ST.
"""

import hashlib


TEXTURE_OFF = 0x323F840
TEXTURE_W = 256
TEXTURE_H = 256
TEXTURE_BYTES = TEXTURE_W * TEXTURE_H // 2
EXPECTED_SHA256 = "1f47dd3a292ec72d031bc8d9a3fde2690d9c6dcfe3313f62309237e0524f67be"
EQUIP_TEXTURE_OFF = 0x321C836
EQUIP_EXPECTED_SHA256 = "bbe0f717da0aa7a1332f0b7459c3800ca5a84f0bb8f4f2b9ec900c5167b4e9d3"
SHOP_TEXTURE_OFF = 0x3248040
SHOP_EXPECTED_SHA256 = "a75a08aaf63a8b83fcf420501b2d00efe6676dd61a34a550da157147e220d0e4"

HALFWIDTH_FONT_ADDR = 0x800E8078
PSX_EXE_LOAD_ADDR = 0x80010000
PSX_EXE_HEADER = 0x800


def _foff(address):
    return address - PSX_EXE_LOAD_ADDR + PSX_EXE_HEADER


def _pixel_offset(x, y):
    return y * (TEXTURE_W // 2) + x // 2


def _get_pixel(texture, x, y):
    value = texture[_pixel_offset(x, y)]
    return (value >> 4) & 0x0F if x & 1 else value & 0x0F


def _set_pixel(texture, x, y, value):
    off = _pixel_offset(x, y)
    if x & 1:
        texture[off] = (texture[off] & 0x0F) | ((value & 0x0F) << 4)
    else:
        texture[off] = (texture[off] & 0xF0) | (value & 0x0F)


def _clear_slot(texture, x, y, width, height, foreground=9, shadow=1):
    old_values = {
        _get_pixel(texture, px, py)
        for py in range(y, y + height)
        for px in range(x, x + width)
    }
    if not old_values <= {0, shadow, foreground}:
        raise SystemExit(
            f"status texture slot ({x},{y},{width},{height}) has unexpected "
            f"palette indices: {sorted(old_values)}"
        )
    for py in range(y, y + height):
        for px in range(x, x + width):
            _set_pixel(texture, px, py, 0)


def _paint_mask(texture, mask, slot, foreground=9, shadow=1):
    """Draw the texture's native one-pixel down/right shadow, then foreground."""
    x, y, width, height = slot
    for px, py in mask:
        sx, sy = px + 1, py + 1
        if x <= sx < x + width and y <= sy < y + height:
            _set_pixel(texture, sx, sy, shadow)
    for px, py in mask:
        if x <= px < x + width and y <= py < y + height:
            _set_pixel(texture, px, py, foreground)


def _draw_game_font(
    texture, exe, x, y, width, text, height=13, y_offset=2,
    foreground=9, shadow=1,
):
    """Render fixed-cell 8x10 text on the Japanese captions' 13px baseline."""
    slot = (x, y, width, height)
    _clear_slot(texture, *slot, foreground=foreground, shadow=shadow)
    font_off = _foff(HALFWIDTH_FONT_ADDR)
    mask = set()
    for char_index, char in enumerate(text):
        glyph_index = ord(char) - 0x20
        if not 0 <= glyph_index < 96:
            raise SystemExit(f"unsupported status-label character: {char!r}")
        glyph = exe[font_off + glyph_index * 10:font_off + (glyph_index + 1) * 10]
        gx = x + char_index * 8
        for gy, row in enumerate(glyph):
            for bit in range(8):
                if row & (0x80 >> bit):
                    mask.add((gx + bit, y + y_offset + gy))
    _paint_mask(texture, mask, slot, foreground=foreground, shadow=shadow)


_FONT_5X7 = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "G": ("01110", "10001", "10000", "10111", "10001", "10001", "01110"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
}


def _draw_compact_stat(
    texture, x, y, text, height=13, y_offset=2, foreground=9, shadow=1
):
    """Fit an Atlus-style two-letter stat abbreviation in the original 12px tile."""
    slot = (x, y, 12, height)
    _clear_slot(texture, *slot, foreground=foreground, shadow=shadow)
    mask = set()
    for char_index, char in enumerate(text):
        rows = _FONT_5X7[char]
        gx = x + char_index * 6
        for gy, row in enumerate(rows):
            for px, value in enumerate(row):
                if value == "1":
                    mask.add((gx + px, y + y_offset + gy))
    _paint_mask(texture, mask, slot, foreground=foreground, shadow=shadow)


def patch_status_texture(packa, exe):
    """Replace Japanese status/equipment captions in-place in PACKA."""
    source = bytes(packa[TEXTURE_OFF:TEXTURE_OFF + TEXTURE_BYTES])
    actual_hash = hashlib.sha256(source).hexdigest()
    if actual_hash != EXPECTED_SHA256:
        raise SystemExit(
            f"status texture at PACKA 0x{TEXTURE_OFF:x}: unexpected SHA-256 {actual_hash}"
        )
    texture = memoryview(packa)[TEXTURE_OFF:TEXTURE_OFF + TEXTURE_BYTES]

    # Human status: two physical-attack pairs, then defense/magic rows.
    for x, y, width, text in (
        (72, 0, 24, "ATK"),
        (72, 13, 24, "HIT"),
        (72, 26, 24, "ATK"),
        (72, 39, 24, "HIT"),
        (48, 52, 24, "DEF"),
        (48, 65, 24, "EVA"),
        (48, 78, 48, "M.PWR"),
        (48, 91, 48, "M.EFF"),
        # Demon/alternate status layout uses its own duplicate label block.
        (132, 0, 24, "ATK"),
        (132, 13, 24, "HIT"),
        (132, 26, 24, "DEF"),
        (132, 39, 24, "EVA"),
        (132, 52, 48, "M.PWR"),
        (132, 65, 48, "M.EFF"),
    ):
        _draw_game_font(texture, exe, x, y, width, text)

    # The original attribute sprites are only 12px wide.  Two-letter labels
    # are both legible and consistent with Atlus status-screen conventions.
    for row, text in enumerate(("ST", "IN", "MA", "VI", "AG", "LU")):
        _draw_compact_stat(texture, 192, row * 13, text)

    equip_source = bytes(
        packa[EQUIP_TEXTURE_OFF:EQUIP_TEXTURE_OFF + TEXTURE_BYTES]
    )
    equip_hash = hashlib.sha256(equip_source).hexdigest()
    if equip_hash != EQUIP_EXPECTED_SHA256:
        raise SystemExit(
            f"equipment texture at PACKA 0x{EQUIP_TEXTURE_OFF:x}: "
            f"unexpected SHA-256 {equip_hash}"
        )
    equip = memoryview(packa)[
        EQUIP_TEXTURE_OFF:EQUIP_TEXTURE_OFF + TEXTURE_BYTES
    ]

    # Main comparison panel and the duplicate weapon/armor detail captions.
    # The duplicates occupy separate atlas cells even when their English text
    # is the same, so patch every cell that the various equipment types use.
    for x, y, width, text in (
        (56, 0, 24, "ATK"),
        (80, 0, 24, "ATK"),
        (128, 0, 24, "DEF"),
        (56, 13, 24, "HIT"),
        (80, 13, 24, "HIT"),
        (128, 13, 24, "EVA"),
        (56, 26, 24, "ATK"),
        (80, 26, 48, "HITS"),
        # 相性: armor damage affinity/resistance (Normal, Fire/Ice, etc.),
        # not the item's Law/Neutral/Chaos equip restriction.
        (128, 26, 24, "AFF"),
        (56, 39, 24, "HIT"),
        (80, 39, 48, "EFFECT"),
        (32, 52, 24, "DEF"),
        (80, 52, 24, "ALN"),
        (128, 52, 24, "ALN"),
        (32, 65, 24, "EVA"),
        (32, 78, 48, "M.PWR"),
        (32, 91, 48, "M.EFF"),
    ):
        _draw_game_font(equip, exe, x, y, width, text)

    # Gun/special-weapon captions use a second packed block whose real row
    # starts are 65, 77, 90, 103, and 116. Treating them as a regular 13px
    # grid (65, 78, 91, 104, 117) shifts each successive English label down
    # and leaves Japanese edge pixels behind. Keep those true cell boundaries.
    # The Gun and Ammo first-row ATK cells sit one pixel lower when sampled, so
    # compensate inside those two cells; rows 2-5 use the Sword-page baseline.
    _draw_game_font(equip, exe, 80, 65, 24, "ATK", height=12, y_offset=1)
    _draw_game_font(equip, exe, 128, 65, 24, "ATK", height=12, y_offset=1)

    for x, y, width, height, text in (
        (128, 77, 24, 13, "HIT"),
        (128, 90, 48, 13, "HITS"),
        (80, 103, 48, 13, "EFFECT"),
        # Row 128 begins an unrelated full-width colored sprite.
        (80, 116, 24, 12, "ALN"),
        (128, 116, 24, 12, "ALN"),
    ):
        _draw_game_font(equip, exe, x, y, width, text, height=height, y_offset=2)

    for row, text in enumerate(("ST", "IN", "MA", "VI", "AG", "LU")):
        _draw_compact_stat(equip, 212, row * 13, text)

    # Shops use a third copy of the comparison captions.  Unlike the Status
    # and Equip atlases above, its cells are packed on a strict 12px grid and
    # use palette index 1 for the foreground and 2 for the shadow.  State11's
    # live GPURAM copy at
    # (704, 256) matches this PACKA asset, including the duplicate captions
    # selected by different weapon and armor types.
    shop_source = bytes(packa[SHOP_TEXTURE_OFF:SHOP_TEXTURE_OFF + TEXTURE_BYTES])
    shop_hash = hashlib.sha256(shop_source).hexdigest()
    if shop_hash != SHOP_EXPECTED_SHA256:
        raise SystemExit(
            f"shop comparison texture at PACKA 0x{SHOP_TEXTURE_OFF:x}: "
            f"unexpected SHA-256 {shop_hash}"
        )
    shop = memoryview(packa)[
        SHOP_TEXTURE_OFF:SHOP_TEXTURE_OFF + TEXTURE_BYTES
    ]

    for x, y, width, text in (
        # Blue comparison boxes: two physical-attack pairs, then defenses.
        (36, 0, 24, "ATK"),
        (36, 12, 24, "HIT"),
        (36, 24, 24, "ATK"),
        (36, 36, 24, "HIT"),
        (12, 48, 24, "DEF"),
        (12, 60, 24, "EVA"),
        (12, 72, 48, "M.PWR"),
        (12, 84, 48, "M.EFF"),
        # Alternate item-detail cells in the same atlas.
        (60, 0, 24, "ATK"),
        (108, 0, 24, "DEF"),
        (60, 12, 24, "HIT"),
        (108, 12, 24, "EVA"),
        (60, 24, 48, "HITS"),
        (108, 24, 24, "AFF"),
        (60, 36, 48, "EFFECT"),
        (108, 36, 48, "EFFECT"),
        (60, 48, 24, "ALN"),
        (108, 48, 24, "ALN"),
    ):
        _draw_game_font(
            shop, exe, x, y, width, text,
            height=12, y_offset=1, foreground=1, shadow=2,
        )

    for row, text in enumerate(("ST", "IN", "MA", "VI", "AG", "LU")):
        _draw_compact_stat(
            shop, 0, row * 12, text,
            height=12, y_offset=2, foreground=1, shadow=2,
        )
