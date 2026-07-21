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

from menu_table import AB_MENU  # noqa: E402
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

# These instructions display non-slot text.  A subsequent slot cannot be a
# continuation of the earlier slot, so they terminate a composition chain.
FIXED_MESSAGE_OPS = set(range(0x61, 0x6A)) | {0x6C}

DYNAMIC_NAMES = {
    "AG": "<actor>", "MG": "<demon>", "SY": "<speaker>",
    "SN": "<name>", "IT": "<item>", "PP": "<stat>",
    "Fe": "<number>",
}
DISPLAY_CONTROLS = {"CR": " / ", "A65": " / ", "A67": " / "}
IGNORED_CONTROLS = {
    "ED", "WT", "PG", "A0E", "A0F", "A14", "A61", "A62", "A63",
    "A64", "A65", "A66", "A67", "A68", "A69", "A6B", "A6E", "A6F",
}


@dataclass(frozen=True)
class Instruction:
    address: int
    opcode: int
    successors: tuple[int, ...]
    kind: str = "logic"
    slot: int | None = None
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
            return Instruction(address, opcode, (operand + 2,), "fixed_message")
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
            return Instruction(address, opcode, (operand + 2,), "fixed_message")
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
            elif token in IGNORED_CONTROLS or token.startswith("A") and token[1:].isalnum():
                continue
            elif token in DYNAMIC_NAMES:
                result.append(DYNAMIC_NAMES[token])
            else:
                result.append(token)
        elif isinstance(token, tuple):
            result.append(f"<control {token[0]:#x}>")
        else:
            result.append(str(token))
    return re.sub(r"\s+", " ", "".join(result)).strip()


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


def slots_for(graph: dict[int, Instruction], chain: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(graph[address].slot for address in chain)  # type: ignore[arg-type]


def write_tsv(path: Path, program: NegotiationProgram, japanese: dict[int, str]):
    rows = []
    totals = collections.Counter()
    for family in range(len(MESSAGE_BASES)):
        graph = program.graph_for_family(family)
        completed, yes_no, menus, adjacent, truncated = collect_paths(
            graph, program.family_entries(family)
        )
        totals["nodes"] += len(graph)
        totals["chains"] += len(completed)
        totals["yes_no"] += len(yes_no)
        totals["menus"] += len(menus)
        totals["adjacent"] += len(adjacent)
        totals["truncated"] += len(truncated)
        totals["repeat_loops"] += sum(first == second for first, second in adjacent)
        for variant in range(VARIANT_COUNTS[family]):
            def add_row(kind, address, chain, labels=""):
                slots = slots_for(graph, chain)
                messages = tuple(message_id(family, variant, slot) for slot in slots)
                fragments = tuple(render_translation(message) for message in messages)
                english = " + ".join(fragments)
                source = " + ".join(japanese.get(message, "") for message in messages)
                rows.append({
                    "kind": kind,
                    "family": family,
                    "variant": variant,
                    "script_address": f"0x{address:08x}" if address is not None else "",
                    "slot_sequence": " ".join(f"{slot:02x}" for slot in slots),
                    "message_ids": " ".join(f"{message:04x}" for message in messages),
                    "menu_labels": labels,
                    "yes_no_review": (
                        "OK"
                        if kind != "yes_no" or yes_no_natural(fragments[-1])
                        else "CHECK"
                    ),
                    "english": english,
                    "japanese": source,
                })

            for chain in sorted(completed):
                if len(chain) >= 2:
                    add_row("fragment_sequence", None, chain)
            for address, chain in sorted(yes_no):
                add_row("yes_no", address, chain, "Yes | No")
            for address, labels, chain in sorted(menus):
                label_text = " | ".join(
                    AB_MENU[label] if label < len(AB_MENU) else f"<{label}>"
                    for label in labels
                )
                add_row("custom_menu", address, chain, label_text)
            for first, second in sorted(adjacent):
                add_row("adjacent_pair", None, (first, second))
                if first == second:
                    add_row(
                        "repeatable_fragment", first, (first,),
                        "may repeat any number of times",
                    )

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
        "The executable is used only to establish control flow, fragment slots, and menu",
        "type. The `japanese` column is loaded verbatim from `SMT2_full_script.txt` and is",
        "the source of truth for translation meaning and voice.",
        "",
        "## Coverage",
        "",
        f"- {totals['nodes']} family-specific reachable bytecode nodes",
        f"- {totals['adjacent']} family-specific fragment adjacencies",
        f"- {totals['chains']} completed fragment chains",
        f"- {totals['yes_no']} family-specific binary Yes/No prompt sites",
        f"- {totals['menus']} custom response-menu sites",
        f"- {totals['repeat_loops']} family-specific unbounded fragment loop",
        f"- {totals['truncated']} loop exit states reached the eight-repeat display cap",
        "",
        "The TSV is the complete reference. `fragment_sequence` rows show maximal slot",
        "chains between message/choice boundaries; `adjacent_pair` rows are the compact",
        "control-flow graph of every possible join. The same slot maps to different message",
        "IDs for each speech family and variant.",
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
    args = parser.parse_args()

    executable = args.exe.read_bytes()
    program = NegotiationProgram(executable)
    japanese = load_japanese(args.script)
    rows, totals = write_tsv(args.tsv, program, japanese)
    write_markdown(args.markdown, rows, totals, japanese)
    print(f"wrote {len(rows)} rows to {args.tsv}")
    print(f"wrote summary to {args.markdown}")


if __name__ == "__main__":
    main()
