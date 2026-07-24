"""Audit SMT II PSX demon-negotiation fragment composition.

The negotiation program is bytecode embedded in SLPM_869.24.  Several
bytecode operations emit a *slot*, not a fixed message ID.  At runtime the
slot is mapped through the current demon's speech family and variant.  This
tool follows every bytecode branch, records fragment sequences, and reports
the text that can precede hard-coded Yes/No prompts.

Usage:
    python tools/audit_negotiation.py
    python tools/audit_negotiation.py --exe Extracted/SLPM_869.24 \
        --markdown build/negotiation_audit.md \
        --tsv build/negotiation_combinations.tsv
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import build_en_tree as ET  # noqa: E402
import name_tables as NT  # noqa: E402
from menu_table import (  # noqa: E402
    AB_MENU,
    AB_MENU_OT,
    AB_MENU_STOCK_DATA,
    N_AB_MENU,
)
from translations import TRANS  # noqa: E402


SCRIPT_BASE = 0x800FCE88
SCRIPT_END = 0x80101266
ENTRY_TABLES = (0x80101266, 0x80101280, 0x8010129A)

# Used by 0x8007e29c to turn (speech family, variant, slot) into a bank-4 ID.
MESSAGE_BASES = (
    0x4025, 0x42F1, 0x45BE, 0x479E,
    0x4025, 0x42F1, 0x45BE, 0x479E,
    0x492A, 0x48F2, 0x4933, 0x4953,
)
VARIANT_COUNTS = (4, 3, 3, 2, 4, 3, 3, 2, 1, 2, 4, 9)

# Opcodes whose handlers select between a u16 relative target and the byte
# immediately following it.  All condition outcomes are retained: the point
# of the audit is to cover every result that the engine can compose.
CONDITIONAL_OPS = (
    set(range(0x25, 0x28))
    | {0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E}
    | set(range(0x30, 0x51))
    | set(range(0x52, 0x56))
    | set(range(0x57, 0x5E))
    | {0x74, 0x76}
)
CONDITIONAL_WITH_BYTE_ARG = {0x2D, 0x2E, 0x4D}

# These instructions interrupt slot composition.  Opcodes 0x13, 0x15, and
# 0x6C carry an explicit bank-5 message ID and are handled separately below:
# unlike the other fixed-message operations, those records can themselves be
# connective text (the reported 0x5006 + 0x47D2 join is one such case).
FIXED_MESSAGE_OPS = set(range(0x61, 0x6A)) | {0x6C}

DYNAMIC_NAMES = {
    "AG": "<actor>", "MG": "<demon>", "SY": "<speaker>",
    "SN": "<name>", "IT": "<item>", "PP": "<stat>",
    "Fe": "<number>", "A62": "<item>", "A63": "<demon>",
    "A64": "<race>", "A6B": "<party member>", "A6E": "<party member>",
    "A6F": "<player name>",
}
DISPLAY_CONTROLS = {"CR": " / ", "A65": " / ", "A67": " / "}
IGNORED_CONTROLS = {
    "ED", "WT", "PG", "A0E", "A0F", "A14", "A61", "A62", "A63",
    "A64", "A65", "A66", "A67", "A68", "A69", "A6B", "A6E", "A6F",
}

FONT12_ADDRESS = 0x800D4188
FONT12_WIDTH = 12
FONT12_HEIGHT = 12
FONT12_BYTES = 18
# The dialogue renderer reserves a stock 12px cell for its next-character
# lookahead even though the English glyphs advance proportionally.  Keeping
# rendered ink at or below 260px is therefore the conservative safe width for
# the 272px dialogue surface (see build.py's line-break patch).
PROMPT_SAFE_WIDTH = 260


@dataclass(frozen=True)
class Instruction:
    address: int
    opcode: int
    successors: tuple[int, ...]
    kind: str = "logic"
    slot: int | None = None
    message: int | None = None
    menu: tuple[tuple[int, int], ...] = ()


def file_offset(address: int) -> int:
    """Convert a loaded PS-X EXE address to its file offset."""
    return address - 0x80010000 + 0x800


class NegotiationProgram:
    def __init__(self, executable: bytes):
        self.executable = executable

    def byte(self, address: int) -> int:
        return self.executable[file_offset(address)]

    def u16(self, address: int) -> int:
        return struct.unpack_from("<H", self.executable, file_offset(address))[0]

    @staticmethod
    def aligned_after(address: int, argument_bytes: int = 0) -> int:
        # Handlers advance past the opcode/byte arguments and align the u16.
        return (address + 2 + argument_bytes) & ~1

    def relative(self, operand: int) -> int:
        return SCRIPT_BASE + self.u16(operand)

    def decode(self, address: int) -> Instruction:
        opcode = self.byte(address)
        if opcode >= 0x80:
            raise ValueError(f"invalid opcode {opcode:#x} at {address:#x}")

        if opcode <= 0x07 or 0x10 <= opcode <= 0x12:
            return Instruction(address, opcode, (), "terminal")
        if opcode in {0x08, 0x09, 0x0A, 0x0C, 0x0F, 0x14, 0x17}:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x0B:
            return Instruction(address, opcode, (address + 2,), "fixed_message")
        if opcode == 0x0D:
            return Instruction(
                address, opcode, (address + 2,), "emit", self.byte(address + 1)
            )
        if opcode == 0x0E:
            return Instruction(address, opcode, (address + 1, address + 2))
        if opcode in {0x13, 0x15}:
            operand = self.aligned_after(address)
            return Instruction(
                address, opcode, (operand + 2,), "fixed_message",
                message=self.u16(operand),
            )
        if opcode == 0x16:
            operand = self.aligned_after(address)
            return Instruction(
                address,
                opcode,
                (
                    self.relative(operand),
                    self.relative(operand + 2),
                    operand + 4,
                ),
            )
        if opcode == 0x18:
            return Instruction(address, opcode, (address + 1,), "emit", 0)
        if opcode == 0x19:
            return Instruction(address, opcode, (address + 3,))
        if 0x1A <= opcode <= 0x1E:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x1F:
            operand = self.aligned_after(address)
            return Instruction(
                address, opcode, (self.relative(operand), operand + 2)
            )
        if opcode == 0x20:
            operand = self.aligned_after(address)
            return Instruction(address, opcode, (self.relative(operand),))
        if opcode == 0x21:
            operand = self.aligned_after(address)
            return Instruction(
                address,
                opcode,
                tuple(self.relative(operand + 2 * index) for index in range(4)),
            )
        if opcode == 0x22:
            operand = self.aligned_after(address)
            return Instruction(
                address,
                opcode,
                (self.relative(operand), operand + 2),
                "yes_no",
            )
        if opcode == 0x23:
            option_count = self.byte(address + 1) + 1
            cursor = address + 2
            options = []
            for _index in range(option_count):
                label = self.byte(cursor)
                cursor += 1
                cursor = (cursor + 1) & ~1
                target = self.relative(cursor)
                cursor += 2
                options.append((label, target))
            return Instruction(
                address,
                opcode,
                tuple(target for _label, target in options),
                "menu",
                menu=tuple(options),
            )
        if opcode == 0x24:
            operand = self.aligned_after(address)
            return Instruction(address, opcode, (self.relative(operand),))
        if opcode in CONDITIONAL_OPS:
            argument_bytes = 1 if opcode in CONDITIONAL_WITH_BYTE_ARG else 0
            operand = self.aligned_after(address, argument_bytes)
            return Instruction(
                address, opcode, (self.relative(operand), operand + 2)
            )
        if opcode in {0x28, 0x51, 0x5E}:
            operand = self.aligned_after(address)
            return Instruction(
                address,
                opcode,
                (
                    self.relative(operand),
                    self.relative(operand + 2),
                    operand + 4,
                ),
            )
        if opcode == 0x2F:
            return Instruction(
                address, opcode, (address + 2,), "emit", self.byte(address + 1)
            )
        if opcode == 0x5F:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x60:
            return Instruction(
                address, opcode, (address + 2,), "emit", self.byte(address + 1)
            )
        if 0x61 <= opcode <= 0x68:
            return Instruction(address, opcode, (address + 1,), "fixed_message")
        if opcode == 0x69:
            return Instruction(address, opcode, (), "fixed_message")
        if 0x6A <= opcode <= 0x6B:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x6C:
            operand = self.aligned_after(address)
            return Instruction(
                address, opcode, (operand + 2,), "fixed_message",
                message=self.u16(operand),
            )
        if opcode == 0x6D:
            return Instruction(address, opcode, (address + 2,))
        if 0x6E <= opcode <= 0x73:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x75:
            return Instruction(address, opcode, (address + 2,))
        if 0x77 <= opcode <= 0x79:
            return Instruction(address, opcode, (address + 2,))
        if 0x7A <= opcode <= 0x7E:
            return Instruction(address, opcode, (address + 1,))
        if opcode == 0x7F:
            return Instruction(address, opcode, (address + 2,))

        raise ValueError(f"unhandled opcode {opcode:#x} at {address:#x}")

    def family_entries(self, family: int) -> tuple[int, ...]:
        return tuple(dict.fromkeys(
            [SCRIPT_BASE]
            + [SCRIPT_BASE + self.u16(table + 2 * family) for table in ENTRY_TABLES]
        ))

    def graph_for_family(self, family: int) -> dict[int, Instruction]:
        graph = {}
        queue = collections.deque(self.family_entries(family))
        while queue:
            address = queue.popleft()
            if address in graph:
                continue
            if not SCRIPT_BASE <= address < SCRIPT_END:
                raise ValueError(
                    f"control flow escaped negotiation bytecode: {address:#x}"
                )
            instruction = self.decode(address)
            graph[address] = instruction
            for successor in instruction.successors:
                if successor not in graph:
                    queue.append(successor)
        return graph


def message_id(family: int, variant: int, slot: int) -> int:
    return MESSAGE_BASES[family] + variant + VARIANT_COUNTS[family] * slot


def render_translation(message: int) -> str:
    result = []
    for token in TRANS.get(message, [f"<missing {message:#06x}>"]):
        if isinstance(token, str):
            if token in DISPLAY_CONTROLS:
                result.append(DISPLAY_CONTROLS[token])
            elif token in DYNAMIC_NAMES:
                result.append(DYNAMIC_NAMES[token])
            elif token in IGNORED_CONTROLS or re.fullmatch(
                r"A[0-9A-Fa-f]{2}", token
            ):
                continue
            else:
                result.append(token)
        elif isinstance(token, tuple):
            result.append(f"<control {token[0]:#x}>")
        else:
            result.append(str(token))
    return re.sub(r"\s+", " ", "".join(result)).strip()


def a14_connective_has_separator(message: int) -> bool:
    """Require authored whitespace before a record's trailing A14 join."""
    tokens = TRANS.get(message, ())
    if not tokens or tokens[-1] != "A14":
        return True
    for token in reversed(tokens[:-1]):
        if (
            not isinstance(token, str)
            or token in DYNAMIC_NAMES
            or token in IGNORED_CONTROLS
            or re.fullmatch(r"A[0-9A-Fa-f]{2}", token)
        ):
            continue
        return token.endswith((" ", "\t", "\n"))
    return False


def load_japanese(path: Path) -> dict[int, str]:
    messages = {}
    if not path.exists():
        return messages
    pattern = re.compile(r"^(0x[0-9a-fA-F]{4})\t(.*)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            messages[int(match.group(1), 16)] = match.group(2)
    return messages


def decode_stock_ab_menu(executable: bytes) -> tuple[str, ...]:
    """Decode the original Japanese negotiation labels from the A/B tree."""
    def u16(address: int) -> int:
        return struct.unpack_from("<H", executable, file_offset(address))[0]

    labels = []
    for index in range(N_AB_MENU):
        position = AB_MENU_STOCK_DATA + u16(AB_MENU_OT + 2 * index)
        high_nibble = True
        node = 0
        encoded = bytearray()
        for _step in range(1000):
            packed = executable[file_offset(position)]
            nibble = packed >> 4 if high_nibble else packed & 0x0F
            high_nibble = not high_nibble
            if high_nibble:
                position += 1
            entry = (node & 0xFFFE) + 2 * nibble
            descriptor = u16(0x8010130C + entry)
            if descriptor == 0x7FFF:
                raise ValueError(f"invalid A/B branch in menu entry {index}")
            if descriptor & 0x8000:
                symbol = u16(0x80101978 + entry)
                if descriptor & 0x4000:
                    break
                encoded.extend(symbol.to_bytes(2, "big"))
                node = 0
            else:
                node = descriptor
        else:
            raise ValueError(f"unterminated A/B menu entry {index}")
        labels.append(encoded.decode("cp932"))
    return tuple(labels)


def _font_index(code: int) -> int:
    lead, trail = code >> 8, code & 0xFF
    row = lead - 0x81 if lead < 0xA0 else lead - 0xC1
    return trail - 0x40 + row * 189


class PromptMeasurer:
    """Measure the final visible page of a composed English prompt."""
    def __init__(self, executable: bytes):
        self.executable = executable
        self.width_cache: dict[str, int] = {" ": 4}
        self.dynamic_text = {
            "A63": max(NT.DEMONS, key=self.text_width),
            "A64": max(NT.RACES, key=self.text_width),
        }
        # Player-entered names may contain eight characters.  Use eight copies
        # of the widest selectable glyph as a conservative bound for A6F.
        name_chars = set("".join(NT.DEMONS + NT.RACES)) | set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789?!'-."
        )
        widest_name_char = max(name_chars, key=self.char_width)
        self.dynamic_text["A6F"] = widest_name_char * 8

    def char_width(self, char: str) -> int:
        if char in self.width_cache:
            return self.width_cache[char]
        try:
            code = ET.fullwidth(char)
        except KeyError:
            # A few non-prompt audit rows contain dictionary-rendered symbols
            # outside the ordinary Latin table. They cannot be narrower than
            # the English glyph assumptions, so retain a full-cell bound.
            self.width_cache[char] = FONT12_WIDTH
            return FONT12_WIDTH
        index = _font_index(code)
        start = file_offset(FONT12_ADDRESS) + index * FONT12_BYTES
        columns = []
        for y in range(FONT12_HEIGHT):
            for x in range(FONT12_WIDTH):
                bit = y * FONT12_WIDTH + x
                if self.executable[start + bit // 8] & (1 << (7 - bit % 8)):
                    columns.append(x)
        width = 4 if not columns else max(columns) - min(columns) + 2
        self.width_cache[char] = width
        return width

    def text_width(self, text: str) -> int:
        return sum(self.char_width(char) for char in text)

    def measure(self, messages: tuple[int, ...]) -> dict[str, int | bool]:
        explicit_widths = [0]
        rendered_widths = [0]

        def newline(widths: list[int]) -> None:
            # The installed line-break guard makes a break at line start a
            # no-op, preventing authored and automatic breaks from doubling.
            if widths[-1]:
                widths.append(0)

        def append_text(text: str) -> None:
            for char in text:
                width = self.char_width(char)
                explicit_widths[-1] += width
                if rendered_widths[-1] and rendered_widths[-1] + width > PROMPT_SAFE_WIDTH:
                    rendered_widths.append(0)
                rendered_widths[-1] += width

        for message in messages:
            for token in TRANS.get(message, ()):
                if not isinstance(token, str):
                    continue
                if token == "A66":
                    # A66 clears/scrolls the old page before the response page.
                    explicit_widths[:] = [0]
                    rendered_widths[:] = [0]
                elif token in {"A65", "CR"}:
                    newline(explicit_widths)
                    newline(rendered_widths)
                elif token in self.dynamic_text:
                    append_text(self.dynamic_text[token])
                elif token in DYNAMIC_NAMES:
                    # No other dynamic insertion is currently reachable in a
                    # custom-menu prompt. Retain a conservative eight-character
                    # bound if a future bytecode/script edit introduces one.
                    append_text("W" * 8)
                elif token in IGNORED_CONTROLS or re.fullmatch(
                    r"A[0-9A-Fa-f]{2}", token
                ):
                    continue
                else:
                    append_text(token)

        def occupied_lines(widths: list[int]) -> int:
            occupied = [index for index, width in enumerate(widths) if width]
            return occupied[-1] + 1 if occupied else 1

        return {
            "prompt_explicit_lines": occupied_lines(explicit_widths),
            "prompt_rendered_lines": occupied_lines(rendered_widths),
            "prompt_max_line_px": max(rendered_widths),
            "prompt_has_dynamic_insert": any(
                isinstance(token, str) and token in self.dynamic_text
                for message in messages for token in TRANS.get(message, ())
            ),
        }


def yes_no_natural(text: str) -> bool:
    """Flag binary prompts that are not phrased as questions at all."""
    plain = re.sub(r"<[^>]+>", "someone", text).strip()
    # Some prompts ask the question first and follow it with an exclamation,
    # threat, or stage direction.  They still give Yes/No a clear referent.
    return "?" in plain


def collect_paths(
    graph: dict[int, Instruction], entries: tuple[int, ...], max_fragments: int = 8
):
    """Return completed fragment chains and the chains used as prompts."""
    completed = set()
    yes_no = set()
    menus = set()
    adjacent = set()
    truncated = set()
    queue = collections.deque((entry, ()) for entry in entries)
    seen = set()
    while queue:
        address, chain = queue.popleft()
        state = (address, chain)
        if state in seen:
            continue
        seen.add(state)
        instruction = graph[address]
        next_chain = chain
        if instruction.kind == "emit":
            if chain:
                adjacent.add((chain[-1], address))
            next_chain = chain + (address,)
            if len(next_chain) > max_fragments:
                truncated.add(next_chain)
                next_chain = next_chain[-max_fragments:]
        elif instruction.kind == "yes_no":
            if chain:
                completed.add(chain)
                yes_no.add((address, chain))
            next_chain = ()
        elif instruction.kind == "menu":
            if chain:
                completed.add(chain)
                labels = tuple(label for label, _target in instruction.menu)
                menus.add((address, labels, chain))
            next_chain = ()
        elif instruction.kind in {"terminal", "fixed_message"}:
            if chain:
                completed.add(chain)
            next_chain = ()

        if not instruction.successors and next_chain:
            completed.add(next_chain)
        for successor in instruction.successors:
            queue.append((successor, next_chain))
    return completed, yes_no, menus, adjacent, truncated


def collect_fixed_adjacencies(
    graph: dict[int, Instruction], entries: tuple[int, ...]
) -> set[tuple[int, int]]:
    """Find joins on either side of explicit bank-5 message operations.

    Fixed messages can be connective records, but carrying every earlier
    dialogue page through them would pollute prompt layout/wording checks.
    Track only the nearest emitted record on each side, which captures the
    physical cross-bank join without treating a whole exchange as one prompt.
    """
    adjacent = set()
    queue = collections.deque((entry, None) for entry in entries)
    seen = set()
    while queue:
        address, previous = queue.popleft()
        state = (address, previous)
        if state in seen:
            continue
        seen.add(state)
        instruction = graph[address]
        next_previous = previous
        is_slot = instruction.kind == "emit"
        is_explicit_fixed = (
            instruction.kind == "fixed_message"
            and instruction.message is not None
        )
        if is_slot or is_explicit_fixed:
            if previous is not None and (
                graph[previous].message is not None
                or instruction.message is not None
            ):
                adjacent.add((previous, address))
            next_previous = address
        elif instruction.kind in {"yes_no", "menu", "terminal", "fixed_message"}:
            next_previous = None

        for successor in instruction.successors:
            queue.append((successor, next_previous))
    return adjacent


def slots_for(
    graph: dict[int, Instruction], chain: tuple[int, ...]
) -> tuple[int | None, ...]:
    return tuple(graph[address].slot for address in chain)


def messages_for(
    graph: dict[int, Instruction],
    family: int,
    variant: int,
    chain: tuple[int, ...],
) -> tuple[int, ...]:
    messages = []
    for address in chain:
        instruction = graph[address]
        if instruction.kind == "emit":
            assert instruction.slot is not None
            messages.append(message_id(family, variant, instruction.slot))
        else:
            assert instruction.message is not None
            messages.append(instruction.message)
    return tuple(messages)


def write_tsv(
    path: Path,
    program: NegotiationProgram,
    japanese: dict[int, str],
    japanese_menu: tuple[str, ...],
    measurer: PromptMeasurer,
):
    rows = []
    totals = collections.Counter()
    for family in range(len(MESSAGE_BASES)):
        graph = program.graph_for_family(family)
        completed, yes_no, menus, adjacent, truncated = collect_paths(
            graph, program.family_entries(family)
        )
        fixed_adjacencies = collect_fixed_adjacencies(
            graph, program.family_entries(family)
        )
        totals["nodes"] += len(graph)
        totals["chains"] += len(completed)
        totals["yes_no"] += len(yes_no)
        totals["menus"] += len(menus)
        totals["adjacent"] += len(adjacent)
        totals["fixed_adjacencies"] += len(fixed_adjacencies)
        totals["truncated"] += len(truncated)
        totals["repeat_loops"] += sum(first == second for first, second in adjacent)
        for variant in range(VARIANT_COUNTS[family]):
            def add_row(kind, address, chain, labels: tuple[int, ...] = ()):
                slots = slots_for(graph, chain)
                messages = messages_for(graph, family, variant, chain)
                fragments = tuple(render_translation(message) for message in messages)
                english = " + ".join(fragments)
                source = " + ".join(japanese.get(message, "") for message in messages)
                layout = measurer.measure(messages)
                label_text = " | ".join(
                    AB_MENU[label] if label < len(AB_MENU) else f"<{label}>"
                    for label in labels
                )
                source_label_text = " | ".join(
                    japanese_menu[label]
                    if label < len(japanese_menu) else f"<{label}>"
                    for label in labels
                )
                if kind == "yes_no":
                    label_text = "Yes | No"
                    source_label_text = "はい | いいえ"
                rows.append({
                    "kind": kind,
                    "family": family,
                    "variant": variant,
                    "script_address": f"0x{address:08x}" if address is not None else "",
                    "slot_sequence": " ".join(
                        f"{slot:02x}" if slot is not None else "--"
                        for slot in slots
                    ),
                    "message_ids": " ".join(f"{message:04x}" for message in messages),
                    "menu_indices": " ".join(str(label) for label in labels),
                    "menu_labels": label_text,
                    "menu_japanese": source_label_text,
                    "yes_no_review": (
                        "OK"
                        if kind != "yes_no" or yes_no_natural(fragments[-1])
                        else "CHECK"
                    ),
                    "a14_join_review": (
                        "OK"
                        if kind not in {"adjacent_pair", "fixed_adjacent_pair"}
                        or a14_connective_has_separator(messages[0])
                        else "CHECK"
                    ),
                    **layout,
                    "layout_review": (
                        "OK" if kind != "custom_menu"
                        or int(layout["prompt_rendered_lines"]) <= 2 else "CHECK"
                    ),
                    "english": english,
                    "japanese": source,
                })

            for chain in sorted(completed):
                if len(chain) >= 2:
                    add_row("fragment_sequence", None, chain)
            for address, chain in sorted(yes_no):
                add_row("yes_no", address, chain)
            for address, labels, chain in sorted(menus):
                add_row("custom_menu", address, chain, labels)
            for first, second in sorted(adjacent):
                add_row("adjacent_pair", None, (first, second))
                if first == second:
                    add_row(
                        "repeatable_fragment", first, (first,),
                    )
            for first, second in sorted(fixed_adjacencies):
                add_row("fixed_adjacent_pair", None, (first, second))

    rows.sort(key=lambda row: (
        row["kind"], row["family"], row["variant"], row["message_ids"],
        row["script_address"],
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return rows, totals


def write_menu_tsv(path: Path, rows: list[dict[str, object]]) -> int:
    """Write the focused raw-Japanese prompt-to-choice review reference."""
    menu_rows = [row for row in rows if row["kind"] == "custom_menu"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=menu_rows[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(menu_rows)
    return len(menu_rows)


def write_choice_uses_tsv(
    path: Path,
    rows: list[dict[str, object]],
    japanese_menu: tuple[str, ...],
) -> int:
    """Invert the menu audit so every A/B choice has its prompt contexts."""
    menu_rows = [row for row in rows if row["kind"] == "custom_menu"]
    uses: dict[int, list[dict[str, object]]] = collections.defaultdict(list)
    for row in menu_rows:
        for label in str(row["menu_indices"]).split():
            uses[int(label)].append(row)

    output = []
    for index, (english_choice, japanese_choice) in enumerate(
        zip(AB_MENU, japanese_menu)
    ):
        contexts = uses.get(index, [])
        if not contexts:
            output.append({
                "choice_index": index,
                "choice_japanese": japanese_choice,
                "choice_english": english_choice,
                "reachable_custom_menu": "NO",
                "expanded_use_count": 0,
                "script_address": "",
                "family": "",
                "variant": "",
                "message_ids": "",
                "prompt_japanese": "",
                "prompt_english": "",
                "choice_set_indices": "",
                "choice_set_japanese": "",
                "choice_set_english": "",
                "prompt_rendered_lines": "",
            })
            continue
        for row in contexts:
            output.append({
                "choice_index": index,
                "choice_japanese": japanese_choice,
                "choice_english": english_choice,
                "reachable_custom_menu": "YES",
                "expanded_use_count": len(contexts),
                "script_address": row["script_address"],
                "family": row["family"],
                "variant": row["variant"],
                "message_ids": row["message_ids"],
                "prompt_japanese": row["japanese"],
                "prompt_english": row["english"],
                "choice_set_indices": row["menu_indices"],
                "choice_set_japanese": row["menu_japanese"],
                "choice_set_english": row["menu_labels"],
                "prompt_rendered_lines": row["prompt_rendered_lines"],
            })

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=output[0].keys(), delimiter="\t")
        writer.writeheader()
        writer.writerows(output)
    return len(output)


def write_markdown(
    path: Path,
    rows: list[dict[str, object]],
    totals,
    japanese: dict[int, str],
):
    yes_no_rows = [row for row in rows if row["kind"] == "yes_no"]
    flagged = [row for row in yes_no_rows if row["yes_no_review"] == "CHECK"]
    unique_flagged: dict[int, dict[str, object]] = {}
    flagged_occurrences = collections.Counter()
    for row in flagged:
        final_message = int(str(row["message_ids"]).split()[-1], 16)
        unique_flagged.setdefault(final_message, row)
        flagged_occurrences[final_message] += 1

    repeat_rows = [row for row in rows if row["kind"] == "repeatable_fragment"]
    menu_rows = [row for row in rows if row["kind"] == "custom_menu"]
    menu_sites = {
        (row["family"], row["script_address"]) for row in menu_rows
    }
    menu_addresses = {row["script_address"] for row in menu_rows}
    menu_contexts = {
        (row["script_address"], row["message_ids"], row["menu_indices"])
        for row in menu_rows
    }
    used_menu_indices = sorted({
        int(label)
        for row in menu_rows
        for label in str(row["menu_indices"]).split()
    })
    two_line_menu_rows = [
        row for row in menu_rows if int(row["prompt_rendered_lines"]) == 2
    ]
    overlong_menu_rows = [
        row for row in menu_rows if row["layout_review"] == "CHECK"
    ]
    unsafe_a14_joins = {
        int(str(row["message_ids"]).split()[0], 16): row
        for row in rows
        if row["kind"] in {"adjacent_pair", "fixed_adjacent_pair"}
        and row["a14_join_review"] == "CHECK"
    }

    examples = {}
    for row in rows:
        if (
            row["kind"] == "adjacent_pair"
            and "42b1" in str(row["message_ids"]).lower()
        ):
            examples.setdefault((row["message_ids"], row["english"]), row)
    lines = [
        "# Demon negotiation composition audit",
        "",
        "Generated by `python tools/audit_negotiation.py` from the executable bytecode and",
        "the current entries in `tools/translations.py`.",
        "",
        "The executable is used to establish control flow, fragment slots, and menu type.",
        "Prompt Japanese in the `japanese` column is loaded verbatim from",
        "`SMT2_full_script.txt`; choice Japanese is decoded directly from the pristine",
        "executable's stock A/B Huffman table. Those two raw-Japanese columns are the",
        "source of truth for translation meaning and voice.",
        "",
        "## Coverage",
        "",
        f"- {totals['nodes']} family-specific reachable bytecode nodes",
        f"- {totals['adjacent']} family-specific fragment adjacencies",
        (
            f"- {totals['fixed_adjacencies']} adjacencies involving explicit "
            "bank-5 message records"
        ),
        f"- {totals['chains']} completed fragment chains",
        f"- {totals['yes_no']} family-specific binary Yes/No prompt sites",
        f"- {totals['menus']} custom response-menu sites",
        f"- {totals['repeat_loops']} family-specific unbounded fragment loop",
        f"- {totals['truncated']} loop exit states reached the eight-repeat display cap",
        f"- {len(unsafe_a14_joins)} unsafe A14 connective joins",
        "",
        "The TSV is the complete reference. `fragment_sequence` rows show maximal slot",
        "chains between message/choice boundaries; `adjacent_pair` rows are the compact",
        "control-flow graph of their possible joins. `fixed_adjacent_pair` rows add the",
        "nearest joins on either side of explicit bank-5 message records embedded in the",
        "bytecode. The same slot maps to different message IDs for each speech family",
        "and variant.",
        "",
        "An unbounded loop cannot be enumerated as a finite list. It is represented",
        "symbolically by `repeatable_fragment` plus its incoming/outgoing `adjacent_pair`",
        "rows, so no possible transition is omitted by the eight-repeat display cap.",
        "",
        "## Repeatable fragment",
        "",
    ]
    for row in repeat_rows:
        lines.append(
            f"- `{row['message_ids']}` may repeat any number of times: {row['english']}"
        )
    if not repeat_rows:
        lines.append("- No repeatable fragment was found.")

    lines += [
        "",
        "## Original reported join",
        "",
    ]
    if examples:
        for row in list(examples.values())[:8]:
            lines.append(
                f"- `{row['message_ids']}`: {row['english']}"
            )
    else:
        lines.append("- No reachable `42b1` adjacency was found.")

    fixed_examples = {}
    for row in rows:
        if (
            row["kind"] == "fixed_adjacent_pair"
            and "5006" in str(row["message_ids"]).lower()
        ):
            fixed_examples.setdefault((row["message_ids"], row["english"]), row)
    lines += [
        "",
        "## Cross-bank connective join",
        "",
    ]
    if fixed_examples:
        for row in list(fixed_examples.values())[:8]:
            lines.append(f"- `{row['message_ids']}`: {row['english']}")
    else:
        lines.append("- No reachable `5006` adjacency was found.")
    if unsafe_a14_joins:
        lines += [
            "",
            "### A14 joins missing authored whitespace",
            "",
        ]
        for message, row in sorted(unsafe_a14_joins.items()):
            lines.append(f"- `{message:04x}`: {row['english']}")

    lines += [
        "",
        "## Custom prompt and response menus",
        "",
        f"- {len(menu_addresses)} distinct custom-menu bytecode addresses",
        f"- {len(menu_sites)} reachable family-specific custom-menu sites",
        f"- {len(menu_contexts)} distinct prompt/choice contexts after family variants",
        f"- {len(used_menu_indices)} of {len(AB_MENU)} A/B menu labels are reachable here",
        f"- {len(two_line_menu_rows)} expanded prompt uses render on two lines",
        f"- {len(overlong_menu_rows)} expanded prompt uses exceed the two-line allowance",
        "",
        "`negotiation_menu_prompts.tsv` is the focused translation reference. Each row",
        "pairs the complete reachable raw-Japanese prompt composition with its exact",
        "stock Japanese choices, A/B indices, and current English prompt/choices. Dynamic",
        "demon, race, and player-name inserts are measured at their conservative maximum",
        "when calculating `prompt_rendered_lines`.",
        "`negotiation_choice_uses.tsv` provides the inverse view: all 115 A/B entries",
        "in index order, followed by every prompt and complete choice set that can use",
        "each entry. Unreachable entries remain present and are marked `NO`.",
        "",
    ]
    if overlong_menu_rows:
        lines += [
            "### Prompts still exceeding two lines",
            "",
            "| Address | Messages | Lines | Current English | Choices |",
            "|---|---|---:|---|---|",
        ]
        seen_overlong = set()
        for row in overlong_menu_rows:
            key = (row["script_address"], row["message_ids"], row["menu_indices"])
            if key in seen_overlong:
                continue
            seen_overlong.add(key)
            english = str(row["english"]).replace("|", "\\|")
            choices = str(row["menu_labels"]).replace("|", "\\|")
            lines.append(
                f"| `{row['script_address']}` | `{row['message_ids']}` | "
                f"{row['prompt_rendered_lines']} | {english} | {choices} |"
            )
        lines.append("")
    else:
        lines += [
            "All reachable custom-menu prompts fit the two-line allowance after the",
            "response window's one-row downward shift.",
            "",
        ]

    lines += [
        "",
        "## Binary prompts needing wording review",
        "",
        "This is deliberately conservative: prompts are flagged when they do not look like",
        "an English polar question. A translator should still review every `yes_no` TSV row.",
        "",
        (
            f"The structural check found {len(unique_flagged)} unique final prompt "
            "messages needing review."
        ),
        "Raw Japanese, current English, context, and every family/variant expansion",
        "remain available in the TSV.",
        "",
        "| Message ID | Raw Japanese | Current English | Expanded uses |",
        "|---|---|---|---:|",
    ]
    for message, row in sorted(unique_flagged.items()):
        source = japanese.get(message, "").replace("|", "\\|")
        english = render_translation(message).replace("|", "\\|")
        lines.append(
            f"| `{message:04x}` | {source} | {english} | "
            f"{flagged_occurrences[message]} |"
        )
    if not unique_flagged:
        lines.append("| — | — | No prompts were flagged. | 0 |")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=ROOT / "Extracted" / "SLPM_869.24")
    parser.add_argument(
        "--script", type=Path, default=ROOT / "SMT2_full_script.txt",
        help="Japanese bank dump used only for reference text",
    )
    parser.add_argument(
        "--markdown", type=Path, default=ROOT / "build" / "negotiation_audit.md"
    )
    parser.add_argument(
        "--tsv", type=Path, default=ROOT / "build" / "negotiation_combinations.tsv"
    )
    parser.add_argument(
        "--menus-tsv", type=Path,
        default=ROOT / "build" / "negotiation_menu_prompts.tsv",
        help="focused raw-Japanese prompt and exact response-choice reference",
    )
    parser.add_argument(
        "--choice-uses-tsv", type=Path,
        default=ROOT / "build" / "negotiation_choice_uses.tsv",
        help="A/B choice-index inventory with every reachable prompt context",
    )
    args = parser.parse_args()

    executable = args.exe.read_bytes()
    program = NegotiationProgram(executable)
    japanese = load_japanese(args.script)
    japanese_menu = decode_stock_ab_menu(executable)
    measurer = PromptMeasurer(executable)
    rows, totals = write_tsv(
        args.tsv, program, japanese, japanese_menu, measurer
    )
    menu_row_count = write_menu_tsv(args.menus_tsv, rows)
    choice_row_count = write_choice_uses_tsv(
        args.choice_uses_tsv, rows, japanese_menu
    )
    write_markdown(args.markdown, rows, totals, japanese)
    print(f"wrote {len(rows)} rows to {args.tsv}")
    print(f"wrote {menu_row_count} menu rows to {args.menus_tsv}")
    print(f"wrote {choice_row_count} choice-use rows to {args.choice_uses_tsv}")
    print(f"wrote summary to {args.markdown}")
    unsafe_a14_joins = sorted({
        str(row["message_ids"]).split()[0]
        for row in rows
        if row["kind"] in {"adjacent_pair", "fixed_adjacent_pair"}
        and row["a14_join_review"] == "CHECK"
    })
    if unsafe_a14_joins:
        print(
            "unsafe A14 connective joins: " + ", ".join(unsafe_a14_joins),
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
