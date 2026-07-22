"""Audit punctuation and spacing around SMT II runtime text insertions.

The script text contains controls which insert the hero, heroine, party member,
demon, race, and skill names at runtime.  Those controls are separate tokens in
``translations.py``; spaces and punctuation therefore have to be supplied by
the adjacent English fragments.  Timing controls such as WT and A68 make the
boundary easy to miss during an ordinary text review.

This audit checks every name-like insertion, adjacent runtime-name inserts,
text that can continue across neighboring message records, the speaker-colon
evidence in the raw Japanese dump, standalone speaker-prefix records, and
literal ``Name:text`` patterns.  It writes a compact Markdown summary and a TSV
suitable for sorting.

Usage:
    python tools/audit_name_insertions.py
    python tools/audit_name_insertions.py --script SMT2_full_script.txt \
        --markdown build/name_insertion_audit.md \
        --tsv build/name_insertion_audit.tsv
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from translations import TRANS  # noqa: E402


CD_CONTROLS = set(
    "CR WT PG ED SY SN Fe TI IT FI FO NI AG SU S2 MN KO OT ZK ZO MG MH "
    "PP AL SE TW".split()
)
AB_CONTROLS = {
    f"A{value:02X}"
    for value in (
        0x0E, 0x0F, 0x14, 0x61, 0x62, 0x63, 0x64, 0x65,
        0x66, 0x67, 0x68, 0x69, 0x6B, 0x6E, 0x6F,
    )
}
ALL_CONTROLS = CD_CONTROLS | AB_CONTROLS

# These insert text whose spelling/length is not known until runtime.  ZK/ZO
# and A64 are races and MH is a skill, but they obey the same lexical-boundary
# rules as character names and are included to make the audit comprehensive.
NAME_INSERTS = (
    "SY", "SN", "Fe", "FI", "FO", "NI", "AG", "MN", "ZK", "ZO",
    "MG", "MH", "AL", "A63", "A64", "A6B", "A6E", "A6F",
)
NAME_INSERT_SET = set(NAME_INSERTS)

# These controls delay printing without creating a visual separator.  The
# audit deliberately looks through them.  CR/PG and the A/B layout controls
# are barriers because a new line/page is itself a separator.
TRANSPARENT_CONTROLS = {"WT", "TI", "TW", "A68"}

# These controls can occur after the final visible Japanese character without
# supplying a separator.  Do not strip runtime inserts here: a space before a
# final [SY]/[MG]/etc. belongs to that inserted name, not to the next record.
SOURCE_TRAILING_CONTROLS = {"ED", "WT", "TI", "TW"}
VISUAL_SEPARATORS = {"CR", "PG"}
SOURCE_CONTROL_AT_END_RE = re.compile(r"\[([A-Za-z0-9]+)\]$")


@dataclass
class BoundaryRow:
    message_id: int
    insert: str
    occurrence: int
    left: str
    right: str
    left_ok: bool
    right_ok: bool

    @property
    def status(self) -> str:
        return "OK" if self.left_ok and self.right_ok else "REVIEW"


def parse_raw_script(path: Path) -> dict[int, str]:
    messages: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("0x") or "\t" not in line:
            continue
        key, text = line.split("\t", 1)
        messages[int(key, 16)] = text
    return messages


def visible_neighbor(tokens: list[object], start: int, direction: int) -> str:
    """Return adjacent authored text, looking only through timing controls."""
    index = start + direction
    while 0 <= index < len(tokens) and tokens[index] in TRANSPARENT_CONTROLS:
        index += direction
    if not 0 <= index < len(tokens):
        return ""
    token = tokens[index]
    if not isinstance(token, str) or token in ALL_CONTROLS:
        return ""
    return token


SPACE_REQUIRING_PUNCTUATION = set(".,!?:;")


def left_boundary_ok(text: str) -> bool:
    if not text or text[-1].isspace():
        return True
    if text[-1].isalnum():
        return False
    # An ellipsis immediately before a recalled or hesitantly spoken name is
    # intentional ("...Hawk").  Other sentence punctuation needs a separator.
    return text.endswith(("...", "?!", "!!", "!?")) or text[-1] not in SPACE_REQUIRING_PUNCTUATION


def right_boundary(tokens: list[object], insert_index: int) -> tuple[str, bool]:
    """Check direct text and ``name + punctuation + timing + word`` tails."""
    index = insert_index + 1
    while index < len(tokens) and tokens[index] in TRANSPARENT_CONTROLS:
        index += 1
    if index >= len(tokens):
        return "", True
    fragment = tokens[index]
    if not isinstance(fragment, str) or fragment in ALL_CONTROLS or not fragment:
        return "", True
    if fragment[0].isalnum():
        return fragment, False
    if not all(char in SPACE_REQUIRING_PUNCTUATION for char in fragment):
        return fragment, True

    # A punctuation-only fragment is attached to the name.  Continue through
    # a following delay so ``Hawk . WT I'm`` cannot evade the boundary check.
    next_index = index + 1
    while next_index < len(tokens) and tokens[next_index] in TRANSPARENT_CONTROLS:
        next_index += 1
    if next_index >= len(tokens):
        return fragment, True
    following = tokens[next_index]
    if not isinstance(following, str) or following in ALL_CONTROLS or not following:
        return fragment, True
    context = f"{fragment} <timing> {following}"
    return context, not following[0].isalnum()


def boundary_rows() -> list[BoundaryRow]:
    rows: list[BoundaryRow] = []
    occurrence_counts: collections.Counter[tuple[int, str]] = collections.Counter()
    for message_id, tokens in sorted(TRANS.items()):
        for index, token in enumerate(tokens):
            if token not in NAME_INSERT_SET:
                continue
            key = (message_id, token)
            occurrence_counts[key] += 1
            left = visible_neighbor(tokens, index, -1)
            right, right_ok = right_boundary(tokens, index)
            rows.append(
                BoundaryRow(
                    message_id,
                    token,
                    occurrence_counts[key],
                    left,
                    right,
                    left_boundary_ok(left),
                    right_ok,
                )
            )
    return rows


def count_english_colons_after(tokens: list[object], insert: str) -> int:
    count = 0
    for index, token in enumerate(tokens):
        if token != insert:
            continue
        right = visible_neighbor(tokens, index, 1)
        if right.startswith(":"):
            count += 1
    return count


def dynamic_colon_issues(raw: dict[int, str]) -> tuple[int, list[str]]:
    """Compare explicit C/D ``[name]：`` occurrences with the English tokens."""
    expected_total = 0
    issues: list[str] = []
    cd_names = [name for name in NAME_INSERTS if not name.startswith("A")]
    for message_id, japanese in sorted(raw.items()):
        english = TRANS.get(message_id)
        for insert in cd_names:
            expected = len(re.findall(rf"\[{re.escape(insert)}\]\uff1a", japanese))
            if not expected:
                continue
            expected_total += expected
            actual = count_english_colons_after(english or [], insert)
            if actual < expected:
                issues.append(
                    f"0x{message_id:04X} {insert}: Japanese has {expected} "
                    f"speaker colon(s), English has {actual}"
                )
    return expected_total, issues


def standalone_header_issues(raw: dict[int, str]) -> tuple[list[int], list[str]]:
    """Check records such as ``STEVEN：[ED]`` which prefix another record."""
    header_ids = [
        message_id
        for message_id, text in sorted(raw.items())
        if re.search(r"\uff1a\[ED\]$", text)
    ]
    issues: list[str] = []
    for message_id in header_ids:
        tokens = TRANS.get(message_id, [])
        authored = [
            token
            for token in tokens
            if isinstance(token, str) and token not in ALL_CONTROLS
        ]
        if not authored or not authored[-1].endswith(": "):
            issues.append(
                f"0x{message_id:04X}: standalone speaker prefix does not end ': '"
            )
    return header_ids, issues


def implicit_ab_colon_issues(raw: dict[int, str]) -> tuple[list[int], list[str]]:
    """Check A/B heroine lines whose hidden insert precedes an initial colon."""
    message_ids = [
        message_id
        for message_id, text in sorted(raw.items())
        if message_id >= 0x4000 and re.match(r"^\u3000*\uff1a", text)
    ]
    issues: list[str] = []
    for message_id in message_ids:
        tokens = TRANS.get(message_id, [])
        has_insert_colon = any(
            token in NAME_INSERT_SET
            and visible_neighbor(tokens, index, 1).startswith(":")
            for index, token in enumerate(tokens)
        )
        if not has_insert_colon:
            issues.append(
                f"0x{message_id:04X}: implicit A/B speaker insert lacks a colon"
            )
    return message_ids, issues


def literal_colon_issues() -> list[str]:
    issues: list[str] = []
    for message_id, tokens in sorted(TRANS.items()):
        for index, token in enumerate(tokens):
            if not isinstance(token, str) or token in ALL_CONTROLS:
                continue
            if re.search(r":(?=\S)", token):
                issues.append(
                    f"0x{message_id:04X} fragment {index}: colon has no following space"
                )
    return issues


def adjacent_insert_issues() -> list[str]:
    """Find two runtime names rendered without any authored separator."""
    issues: list[str] = []
    for message_id, tokens in sorted(TRANS.items()):
        for index, token in enumerate(tokens):
            if token not in NAME_INSERT_SET:
                continue
            next_index = index + 1
            while (next_index < len(tokens)
                   and tokens[next_index] in TRANSPARENT_CONTROLS):
                next_index += 1
            if (next_index < len(tokens)
                    and tokens[next_index] in NAME_INSERT_SET):
                issues.append(
                    f"0x{message_id:04X} fragments {index}/{next_index}: "
                    f"adjacent {token}/{tokens[next_index]} inserts lack a separator"
                )
    return issues


def source_has_trailing_separator(text: str) -> bool:
    """Whether Japanese preserves a visible space before its final controls."""
    while True:
        match = SOURCE_CONTROL_AT_END_RE.search(text)
        if not match or match.group(1) not in SOURCE_TRAILING_CONTROLS:
            break
        text = text[:match.start()]
    return text.endswith((" ", "\u3000"))


def record_edge(tokens: list[object], reverse: bool) -> tuple[str, bool]:
    """Return a record's edge text and whether a line/page separates it."""
    sequence = reversed(tokens) if reverse else iter(tokens)
    for token in sequence:
        if token == "ED" or token in TRANSPARENT_CONTROLS:
            continue
        if token in VISUAL_SEPARATORS:
            return "", True
        if token in NAME_INSERT_SET:
            return f"<{token}>", False
        if not isinstance(token, str) or token in ALL_CONTROLS:
            return "", False
        return token, False
    return "", False


def neighboring_record_issues(raw: dict[int, str]) -> list[str]:
    """Audit likely joins between consecutive C/D dialogue records.

    The event engine can append separately stored records without moving the
    text cursor.  Japanese marks many such joins with a final fullwidth space.
    A second conservative check catches an English clause ending in a letter
    followed by a lowercase continuation, even when Japanese joins the clause
    with a particle and therefore has no source-space evidence.

    A/B negotiation fragments are excluded: their source records are padded
    uniformly and their reachable composition is audited by audit_negotiation.
    """
    issues: list[str] = []
    for message_id, tokens in sorted(TRANS.items()):
        if message_id >= 0x4000 or message_id + 1 not in TRANS:
            continue
        left, left_barrier = record_edge(tokens, reverse=True)
        right, right_barrier = record_edge(TRANS[message_id + 1], reverse=False)
        if left_barrier or right_barrier or not left or not right:
            continue
        if left[-1].isspace() or right[0].isspace():
            continue
        source_separator = source_has_trailing_separator(raw.get(message_id, ""))
        lexical_continuation = left[-1].isalnum() and right[0].islower()
        if source_separator or lexical_continuation:
            evidence = (
                "Japanese trailing separator"
                if source_separator else "lowercase lexical continuation"
            )
            issues.append(
                f"0x{message_id:04X}->0x{message_id + 1:04X}: "
                f"records join without whitespace ({evidence}); "
                f"left={left!r}, right={right!r}"
            )
    return issues


def write_tsv(path: Path, rows: list[BoundaryRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter="\t")
        writer.writerow(
            ("message_id", "insert", "occurrence", "left_text", "right_text",
             "left_ok", "right_ok", "status")
        )
        for row in rows:
            writer.writerow(
                (
                    f"0x{row.message_id:04X}", row.insert, row.occurrence,
                    row.left, row.right, row.left_ok, row.right_ok, row.status,
                )
            )


def write_markdown(
    path: Path,
    rows: list[BoundaryRow],
    header_ids: list[int],
    ab_colon_ids: list[int],
    dynamic_colon_count: int,
    issues: list[str],
) -> None:
    counts = collections.Counter(row.insert for row in rows)
    message_count = len({row.message_id for row in rows})
    lines = [
        "# Runtime name-insertion audit",
        "",
        f"- Name-like insert occurrences: **{len(rows)}** in **{message_count}** messages",
        f"- Raw-Japanese explicit dynamic-name speaker colons: **{dynamic_colon_count}**",
        f"- Raw-Japanese standalone speaker prefixes: **{len(header_ids)}**",
        f"- Raw-Japanese implicit A/B speaker-colon records: **{len(ab_colon_ids)}**",
        f"- Issues requiring review: **{len(issues)}**",
        "",
        "## Insert coverage",
        "",
        "| Insert | Occurrences |",
        "|---|---:|",
    ]
    lines.extend(f"| `{insert}` | {counts[insert]} |" for insert in NAME_INSERTS)
    lines.extend(["", "## Findings", ""])
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("No unresolved spacing or speaker-colon issues were found.")
    lines.extend(
        [
            "",
            "The boundary check looks through `WT`, `TI`, `TW`, and `A68` because",
            "those controls delay text without supplying punctuation or whitespace.",
            "Line/page controls are treated as visual separators.",
            "The neighboring-record check also preserves separators evidenced by",
            "the raw Japanese and catches lowercase English clause continuations.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, default=ROOT / "SMT2_full_script.txt")
    parser.add_argument(
        "--markdown", type=Path, default=ROOT / "build" / "name_insertion_audit.md"
    )
    parser.add_argument(
        "--tsv", type=Path, default=ROOT / "build" / "name_insertion_audit.tsv"
    )
    args = parser.parse_args()

    raw = parse_raw_script(args.script)
    rows = boundary_rows()
    boundary_issues = [
        f"0x{row.message_id:04X} {row.insert} occurrence {row.occurrence}: "
        f"left={row.left!r}, right={row.right!r}"
        for row in rows
        if row.status != "OK"
    ]
    header_ids, header_issues = standalone_header_issues(raw)
    ab_colon_ids, ab_colon_issues = implicit_ab_colon_issues(raw)
    dynamic_colon_count, colon_issues = dynamic_colon_issues(raw)
    issues = (
        boundary_issues
        + adjacent_insert_issues()
        + neighboring_record_issues(raw)
        + colon_issues
        + header_issues
        + ab_colon_issues
        + literal_colon_issues()
    )

    write_tsv(args.tsv, rows)
    write_markdown(
        args.markdown,
        rows,
        header_ids,
        ab_colon_ids,
        dynamic_colon_count,
        issues,
    )
    print(
        f"Audited {len(rows)} name-like inserts in "
        f"{len({row.message_id for row in rows})} messages; {len(issues)} issue(s)."
    )
    print(f"Markdown: {args.markdown}")
    print(f"TSV: {args.tsv}")
    if issues:
        for issue in issues:
            print(f"REVIEW: {issue}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
