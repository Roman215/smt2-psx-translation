"""Dump every compressed text-bank entry from a supported SMT2 Japan Rev 1 BIN.

Banks 0-3 contain the field, NPC, and story script. Banks 4-7 contain negotiation,
battle, and shared system text. Raw strings owned by standalone overlays (for example,
RDLOGO.BIN) are outside this codec and are intentionally not part of this dump.
"""

import argparse
import hashlib
import struct
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECTOR_SIZE = 2352
USER_DATA_OFFSET = 24
USER_DATA_SIZE = 2048
EXPECTED_BIN_SIZE = 222_694_416
SLPM_SECTOR = 67202
SLPM_SIZE = 2_025_472
PACKA_SECTOR = 68191
PACKA_SIZE = 53_948_416
EXPECTED_SLPM_SHA256 = "831a6cceb94c88c9736f6df88a7fd9e08ff1261ca781b40b7e6ff449cf0fd24e"
EXPECTED_PACKA_SHA256 = "c4dbe96e0aa921e0ea3d3194b6a5846e9a74a7164f13695a0c97eeb773126367"
EXPECTED_BANK_COUNTS = {0: 974, 1: 43, 2: 621, 3: 455, 4: 2432, 5: 98, 6: 301, 7: 32}

CD_STRUCT, CD_SYM = 0x80117EC4, 0x801187A4
AB_STRUCT, AB_SYM = 0x8010130C, 0x80101978
TREES = {"CD": (CD_STRUCT, CD_SYM), "AB": (AB_STRUCT, AB_SYM)}
ED = (0x4544, True)
FULLWIDTH_SPACE = (0x8140, False)


def foff(address):
    return (address - 0x80010000) + 0x800


# bank, description, source, base, allocation, Huffman table
BLOCKS = [
    (0, "field/system", "packa", 0x32FB000, 0x7800, "CD"),
    (1, "field",        "packa", 0x3302800, 0x1000, "CD"),
    (2, "town/NPC",     "packa", 0x3303800, 0x8000, "CD"),
    (3, "story/demons", "packa", 0x330B800, 0x6800, "CD"),
    (4, "negotiation",  "packa", 0x32F1000, 0x7800, "AB"),
    (5, "battle-cmd",   "packa", 0x32F8800, 0x2800, "AB"),
    (6, "battle-msg",   "slpm",  foff(0x80115BD8), 0x80116F2C - 0x80115BD8, "CD"),
    (7, "system",       "slpm",  foff(0x80116F2C), 0x80117CC8 - 0x80116F2C, "CD"),
]


def extract_from_bin(bin_data, base_sector, file_size):
    """Read a contiguous MODE2/2352 file payload directly from a BIN image."""
    out = bytearray()
    sector = base_sector
    while len(out) < file_size:
        start = sector * SECTOR_SIZE + USER_DATA_OFFSET
        end = start + USER_DATA_SIZE
        if end > len(bin_data):
            raise SystemExit(
                f"BIN ends while extracting sector {sector} "
                f"({len(out):,}/{file_size:,} bytes read)"
            )
        out += bin_data[start:end]
        sector += 1
    return bytes(out[:file_size])


def u16_ram(slpm, address):
    return struct.unpack_from("<H", slpm, foff(address))[0]


def decode_range(buf, start, end, table, slpm, stop_at_first_ed=False):
    """Decode one byte-bounded stream without imposing an arbitrary token cap."""
    if not 0 <= start <= end <= len(buf):
        raise ValueError(f"invalid stream bounds {start:#x}..{end:#x}")
    struct_base, sym_base = TREES[table]
    pos = start
    high_nibble = True
    tokens = []

    while pos < end:
        node = 0
        for _depth in range(64):
            if pos >= end:
                return tokens
            byte = buf[pos]
            nibble = (byte >> 4) if high_nibble else (byte & 0x0F)
            if high_nibble:
                high_nibble = False
            else:
                high_nibble = True
                pos += 1

            entry_address = (node & 0xFFFE) + nibble * 2
            next_node = u16_ram(slpm, struct_base + entry_address)
            if next_node == 0x7FFF:
                # An unused trailing nibble can lead to an empty branch. The exact
                # byte boundary still prevents this from entering the next stream.
                return tokens
            if next_node & 0x8000:
                token = (
                    u16_ram(slpm, sym_base + entry_address),
                    bool(next_node & 0x4000),
                )
                tokens.append(token)
                if stop_at_first_ed and token == ED:
                    return tokens
                break
            node = next_node
        else:
            raise ValueError(f"Huffman path exceeds 64 levels at file offset {pos:#x}")
    return tokens


def render(tokens):
    out = []
    for symbol, control in tokens:
        # The A/B tree also uses 0x8140 leaves with its flag bit set; the game
        # treats those as ordinary fullwidth spaces, not named control codes.
        if symbol == 0x8140:
            out.append("　")
        elif control:
            try:
                out.append("[" + struct.pack(">H", symbol).decode("ascii") + "]")
            except (UnicodeDecodeError, ValueError):
                out.append(f"[{symbol:04x}]")
        else:
            try:
                out.append(struct.pack(">H", symbol).decode("shift_jis"))
            except (UnicodeDecodeError, ValueError):
                out.append(f"[{symbol:04x}]")
    return "".join(out)


def _last_ab_stream_end(buf, start, allocation_end):
    """AB banks have no ED terminator; their final stream is followed by 0xCC fill."""
    fill = buf.find(b"\xCC" * 16, start, allocation_end)
    if fill < 0:
        raise ValueError(f"could not find AB-bank fill after final stream at {start:#x}")
    return fill


def decode_bank(bank, desc, buf, base, allocation, table, slpm):
    allocation_end = base + allocation
    if allocation_end > len(buf):
        raise ValueError(f"bank {bank}: allocation exceeds source file")

    data_offset = struct.unpack_from("<H", buf, base)[0]
    if data_offset < 2 or data_offset & 1 or base + data_offset > allocation_end:
        raise ValueError(f"bank {bank}: invalid table size {data_offset:#x}")
    count = (data_offset - 2) // 2
    if count != EXPECTED_BANK_COUNTS[bank]:
        raise ValueError(
            f"bank {bank}: found {count} entries; expected {EXPECTED_BANK_COUNTS[bank]}"
        )
    offsets = struct.unpack_from(f"<{count}H", buf, base + 2)
    data_base = base + data_offset
    data_capacity = allocation_end - data_base
    if not offsets or any(offset >= data_capacity for offset in offsets):
        raise ValueError(f"bank {bank}: string offset outside its allocation")

    unique_offsets = sorted(set(offsets))
    next_offset = {
        offset: (unique_offsets[i + 1] if i + 1 < len(unique_offsets) else None)
        for i, offset in enumerate(unique_offsets)
    }
    cache = {}
    unterminated = []

    for offset in unique_offsets:
        following = next_offset[offset]
        start = data_base + offset
        if following is None:
            if table == "CD":
                # The last table target has no following offset to bound it. C/D
                # streams are self-terminating, so stop at its first ED rather than
                # wandering into unrelated padding or executable data.
                tokens = decode_range(
                    buf, start, allocation_end, table, slpm, stop_at_first_ed=True
                )
            else:
                end = _last_ab_stream_end(buf, start, allocation_end)
                tokens = decode_range(buf, start, end, table, slpm)
        else:
            end = data_base + following
            tokens = decode_range(buf, start, end, table, slpm)
            if table == "CD":
                # Some entries intentionally contain multiple ED-separated pieces.
                # Preserve all of them, but discard a decoded alignment nibble after
                # the final ED.
                ed_positions = [i for i, token in enumerate(tokens) if token == ED]
                if ed_positions:
                    tokens = tokens[:ed_positions[-1] + 1]
                else:
                    while tokens and tokens[-1] == FULLWIDTH_SPACE:
                        tokens.pop()

        if table == "CD" and ED not in tokens:
            unterminated.append((bank << 12) | offsets.index(offset))
        cache[offset] = tokens

    messages = [cache[offset] for offset in offsets]
    aliases = count - len(unique_offsets)
    return messages, aliases, unterminated


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, metavar="BIN", help="source Japan Rev 1 MODE2/2352 BIN"
    )
    parser.add_argument(
        "--output", default="SMT2_full_script.txt", metavar="PATH", help="output text file"
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    bin_path = Path(args.input)
    if not bin_path.is_file():
        raise SystemExit(f"Source BIN not found: {bin_path}")
    if bin_path.stat().st_size != EXPECTED_BIN_SIZE:
        raise SystemExit(
            f"Unexpected BIN size: {bin_path.stat().st_size:,}; "
            f"expected {EXPECTED_BIN_SIZE:,} bytes for Japan Rev 1"
        )

    bin_data = bin_path.read_bytes()
    slpm = extract_from_bin(bin_data, SLPM_SECTOR, SLPM_SIZE)
    packa = extract_from_bin(bin_data, PACKA_SECTOR, PACKA_SIZE)
    for label, data, expected in (
        ("SLPM_869.24", slpm, EXPECTED_SLPM_SHA256),
        ("PACKA.BIN", packa, EXPECTED_PACKA_SHA256),
    ):
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise SystemExit(
                f"{label} does not match the supported Japan Rev 1 data "
                f"(SHA-256 {actual})"
            )
    sources = {"slpm": slpm, "packa": packa}

    header = [
        "# Shin Megami Tensei II (PSX) — complete compressed text-bank dump",
        "# Message ID = (bank << 12) | table index; control codes are shown in brackets.",
        "# Banks 0-3 contain the complete field/NPC/story script; banks 4-7 contain",
        "# negotiation, battle, and shared system text. Standalone overlay raw strings",
        "# are not encoded in these banks and are outside this file.",
        "# Huffman tables: banks 4-5 use A/B; all other banks use C/D.",
        "",
    ]
    lines = list(header)
    total_messages = 0
    total_unique = 0
    glyphs = 0
    unterminated = []

    for bank, desc, source, base, allocation, table in BLOCKS:
        messages, aliases, bank_unterminated = decode_bank(
            bank, desc, sources[source], base, allocation, table, slpm
        )
        total_messages += len(messages)
        total_unique += len(messages) - aliases
        unterminated.extend(bank_unterminated)
        lines.append(
            f"\n===== BANK {bank} ({desc}) — {len(messages)} entries, "
            f"{len(messages) - aliases} unique streams, table {table} ====="
        )
        for index, tokens in enumerate(messages):
            glyphs += sum(1 for symbol, control in tokens if not control and symbol != 0x8140)
            lines.append(f"{(bank << 12) | index:#06x}\t{render(tokens)}")

    output_path = Path(args.output)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"{total_messages} entries, {total_unique} unique streams, ~{glyphs} glyphs "
        f"-> {output_path} ({output_path.stat().st_size}B)"
    )
    if unterminated:
        ids = ", ".join(f"{message_id:#06x}" for message_id in unterminated)
        print(f"Note: C/D entries without ED (bounded by their next stream): {ids}")


if __name__ == "__main__":
    main()
