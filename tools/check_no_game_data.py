#!/usr/bin/env python3
"""Fail if any Git-tracked file looks like game data.

Run by CI on every push and by release.py before cutting a release. Only the
tracked tree is checked; local BIN/CUE working files are expected and stay
ignored via .gitignore.
"""
import subprocess
import sys
from pathlib import Path

# Disc images, disc descriptors, extracted disc files, save data, patches,
# and executables have no business being version-controlled in this project.
FORBIDDEN_SUFFIXES = {
    ".bin", ".cue", ".iso", ".img", ".ecm", ".chd", ".mdf", ".mds", ".ccd",
    ".sub", ".str", ".xdelta", ".sav", ".mcr", ".srm", ".exe", ".dll",
}
FORBIDDEN_NAME_PARTS = (".state", ".sstate")
MAX_TRACKED_BYTES = 10 * 2**20


def main():
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout.split("\0")
    problems = []
    for name in tracked:
        if not name:
            continue
        lower = name.lower()
        suffix = Path(lower).suffix
        if suffix in FORBIDDEN_SUFFIXES:
            problems.append(f"{name}: forbidden file type `{suffix}`")
            continue
        if any(part in lower for part in FORBIDDEN_NAME_PARTS):
            problems.append(f"{name}: looks like an emulator save state")
            continue
        path = Path(name)
        if path.is_file() and path.stat().st_size > MAX_TRACKED_BYTES:
            problems.append(
                f"{name}: {path.stat().st_size:,} bytes exceeds the "
                f"{MAX_TRACKED_BYTES:,}-byte limit for tracked files"
            )
    if problems:
        print("Tracked files that must not be committed:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print(f"OK: {sum(1 for name in tracked if name)} tracked files, no game data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
