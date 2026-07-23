#!/usr/bin/env python3
"""SMT2 PSX translation -- release automation.

Builds the four distributable xdelta patches covering English/Japanese movies
and enhanced/original gameplay, stages release notes and checksums, tags the
version, and creates a GitHub release carrying ONLY the patch files.

Game data never leaves this machine: the build runs locally against your own
source image, and a hard allowlist (`assert_assets_safe`) refuses to upload
anything that is not a small .xdelta/.txt/.md file.

Typical flow (see RELEASING.md):

    1. Move the [Unreleased] notes in CHANGELOG.md under a new version
       heading, commit everything.
    2. python release.py 0.1.0
    3. Test build/release/v0.1.0/*/*.bin if desired, then publish the
       draft release on GitHub (or re-run with --publish next time).
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
RELEASE_BRANCH = "master"
STAGING_ROOT = ROOT / "build" / "release"
MOVIE_FAILURE_MARKER = "WARNING: the movies were not translated"

# The default release is the recommended enhanced build. Each independent
# opt-out gets a filename suffix, so all four movie/gameplay combinations are
# explicit without burdening the default patch with qualifiers.
VARIANTS = {
    "default": {
        "english_movies": True,
        "enhancements": True,
        "suffix": "",
        "description": "English movies and modern gameplay enhancements (recommended)",
    },
    "no-enhancements": {
        "english_movies": True,
        "enhancements": False,
        "suffix": "_NO_ENHANCEMENTS",
        "description": "English movies and original gameplay mechanics",
    },
    "jp-movies": {
        "english_movies": False,
        "enhancements": True,
        "suffix": "_JP_movies",
        "description": "Original Japanese movies and modern gameplay enhancements",
    },
    "no-enhancements-jp-movies": {
        "english_movies": False,
        "enhancements": False,
        "suffix": "_NO_ENHANCEMENTS_JP_movies",
        "description": "Original Japanese movies and original gameplay mechanics",
    },
}

# The only things a release may upload. Everything else -- above all any
# BIN/CUE or other game data -- is rejected before gh is ever invoked.
ALLOWED_ASSET_SUFFIXES = {".xdelta", ".txt", ".md"}
MAX_ASSET_BYTES = 100 * 2**20


def fail(message):
    raise SystemExit(f"release: {message}")


def run_capture(cmd, check=True, cwd=ROOT):
    """Run a short command, capturing stdout/stderr."""
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        fail(f"`{' '.join(map(str, cmd))}` failed:\n{detail}")
    return result


def run_streaming(cmd, cwd=ROOT):
    """Run a long command, echoing output live while also capturing it."""
    process = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    lines = []
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    process.wait()
    return process.returncode, "".join(lines)


def git(*args, check=True):
    return run_capture(["git", *args], check=check)


def find_gh():
    """Locate the GitHub CLI, including fresh winget installs not yet on PATH."""
    found = shutil.which("gh")
    if found:
        return found
    winget_packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/gh.exe",
        Path("C:/Program Files/GitHub CLI/gh.exe"),
        *(sorted(winget_packages.glob("GitHub.cli*/bin/gh.exe"))
          if winget_packages.is_dir() else ()),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    fail(
        "GitHub CLI (gh) not found. Install it with "
        "`winget install --id GitHub.cli --scope user`, then run `gh auth login`."
    )


def changelog_section(version):
    """Extract this version's notes from CHANGELOG.md."""
    changelog = ROOT / "CHANGELOG.md"
    if not changelog.is_file():
        fail("CHANGELOG.md not found")
    text = changelog.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        fail(
            f"CHANGELOG.md has no `## [{version}]` section. Move the "
            f"[Unreleased] notes under `## [{version}] - {date.today().isoformat()}` "
            "and commit before releasing."
        )
    body = match.group(1).strip()
    if not body:
        fail(f"the `## [{version}]` section in CHANGELOG.md is empty")
    return body


def preflight(version, args):
    """Every cheap check runs before the (long) builds start."""
    tag = f"v{version}"

    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch != RELEASE_BRANCH:
        fail(f"releases must be cut from `{RELEASE_BRANCH}` (currently on `{branch}`)")
    if not args.allow_dirty:
        dirty = git("status", "--porcelain").stdout.strip()
        if dirty:
            fail(
                "working tree is not clean; commit (or stash) first, "
                "or pass --allow-dirty:\n" + dirty
            )
    # An existing tag is fine only when it points at HEAD -- that is a
    # recovery re-run of this same release after a failed upload. A tag on
    # any other commit means the version number is already taken.
    head = git("rev-parse", "HEAD").stdout.strip()
    local_tag = git("rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}", check=False)
    if local_tag.returncode == 0 and local_tag.stdout.strip() != head:
        fail(
            f"tag {tag} already exists on another commit; pick a new version "
            f"or delete it (`git tag -d {tag}`)"
        )
    remote_tag = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}").stdout.strip()
    if remote_tag and local_tag.returncode != 0:
        fail(f"tag {tag} already exists on origin but not locally; pick a new version")

    guard = run_capture([sys.executable, "tools/check_no_game_data.py"], check=False)
    if guard.returncode != 0:
        fail("game-data guard failed:\n" + (guard.stdout + guard.stderr).strip())

    gh = find_gh()
    auth = run_capture([gh, "auth", "status"], check=False)
    if auth.returncode != 0:
        fail(f"GitHub CLI is not authenticated. Run: {gh} auth login")
    if run_capture([gh, "release", "view", tag], check=False).returncode == 0:
        fail(
            f"a GitHub release for {tag} already exists. If it is a leftover "
            f"partial draft, delete it first: gh release delete {tag}"
        )

    notes_body = changelog_section(version)

    # Fail on a missing source image or pyxdelta now, not an hour into a build.
    sys.path.insert(0, str(ROOT))
    import build as build_module
    input_bin = build_module.find_input_bin(args.input)
    build_module.require_pyxdelta()
    return tag, gh, notes_body, input_bin, build_module


def build_variant(staging, name, config, input_bin):
    """Run one full build; return the resulting xdelta path."""
    variant_dir = staging / name
    command = [sys.executable, "build.py", "--xdelta", "--output-dir", str(variant_dir)]
    if not config["enhancements"]:
        command.append("--no-enhancements")
    # --require-movies aborts the build at the movie step, so a failed movie
    # can never fall back to Japanese video in the English-movie patch.
    command.append(
        "--require-movies" if config["english_movies"] else "--skip-movies"
    )
    if input_bin is not None:
        command += ["--input", str(input_bin)]
    print(f"\n=== building variant `{name}` ===")
    returncode, output = run_streaming(command)
    if returncode != 0:
        fail(f"build for variant `{name}` failed (exit {returncode})")
    if config["english_movies"] and MOVIE_FAILURE_MARKER in output:
        # Backstop only: --require-movies should already have failed the build.
        fail(
            "the English-movie build fell back to Japanese movies "
            "(see WARNING above). Releases must not silently ship the "
            "wrong movie -- fix FFmpeg/psxavenc availability and retry."
        )
    return verify_variant(staging, name, config)


def verify_variant(staging, name, config):
    """Check a built (or --skip-build reused) variant's artifacts."""
    variant_dir = staging / name
    xdelta = variant_dir / "SMT2_EN.xdelta"
    output_bin = variant_dir / "SMT2_EN.bin"
    for artifact in (xdelta, output_bin):
        if not artifact.is_file():
            fail(f"variant `{name}` is missing {artifact}")
    if config["english_movies"]:
        for movie in ("OPENING_EN.str", "GAMEOVER_EN.str"):
            if not (variant_dir / movie).is_file():
                fail(f"variant `{name}` has no {movie}; its movies were not translated")
    if xdelta.stat().st_size == 0:
        fail(f"variant `{name}` produced an empty xdelta")
    return xdelta


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def assert_assets_safe(assets, expected_bin_size):
    """Hard gate: only small patch/text files may ever reach GitHub."""
    for asset in assets:
        suffix = asset.suffix.lower()
        if suffix not in ALLOWED_ASSET_SUFFIXES:
            fail(f"refusing to upload `{asset.name}`: `{suffix}` is not an allowed asset type")
        size = asset.stat().st_size
        if size == 0:
            fail(f"refusing to upload empty asset `{asset.name}`")
        if size > MAX_ASSET_BYTES or size == expected_bin_size:
            fail(
                f"refusing to upload `{asset.name}` ({size:,} bytes): too large "
                "to plausibly be a patch -- this looks like game data"
            )


def stage_release(staging, version, variant_xdeltas, input_bin, notes_body, build_module):
    """Copy patches to versioned names; write checksums and release notes."""
    if set(variant_xdeltas) != set(VARIANTS):
        missing = sorted(set(VARIANTS) - set(variant_xdeltas))
        extra = sorted(set(variant_xdeltas) - set(VARIANTS))
        fail(f"release variant mismatch; missing={missing or 'none'}, extra={extra or 'none'}")
    asset_names = {
        name: f"SMT2_EN_v{version}{config['suffix']}.xdelta"
        for name, config in VARIANTS.items()
    }
    assets_by_variant = {}
    for name, xdelta in variant_xdeltas.items():
        asset = staging / asset_names[name]
        shutil.copy2(xdelta, asset)
        assets_by_variant[name] = asset

    # Each English-movie patch rewrites both movie regions, so it must be
    # substantially larger than its otherwise matching Japanese-movie patch.
    # Equality means the movies silently failed to build.
    for english_name, japanese_name in (
        ("default", "jp-movies"),
        ("no-enhancements", "no-enhancements-jp-movies"),
    ):
        english_asset = assets_by_variant[english_name]
        japanese_asset = assets_by_variant[japanese_name]
        if english_asset.stat().st_size < japanese_asset.stat().st_size + (1 << 20):
            fail(
                f"variant `{english_name}` is not meaningfully larger than "
                f"`{japanese_name}`; the translated movies appear to be missing"
            )

    print("hashing source image and outputs...")
    source_sha = sha256_file(input_bin)
    bin_hashes = {
        name: sha256_file(staging / name / "SMT2_EN.bin")
        for name in VARIANTS
    }
    patch_hashes = {
        name: sha256_file(assets_by_variant[name])
        for name in VARIANTS
    }

    sums = staging / "sha256sums.txt"
    sum_lines = [
        f"# SMT2 PSX English Translation v{version}\n"
        f"# Apply to: Shin Megami Tensei II (Japan) (Rev 1), MODE2/2352 BIN, "
        f"{build_module.EXPECTED_BIN_SIZE:,} bytes\n"
        f"# Source BIN sha256:  {source_sha}\n"
    ]
    sum_lines.extend(
        f"# Patched BIN sha256 ({asset_names[name]}): {bin_hashes[name]}\n"
        for name in VARIANTS
    )
    sum_lines.extend(
        f"{patch_hashes[name]}  {asset_names[name]}\n"
        for name in VARIANTS
    )
    sums.write_text("".join(sum_lines), encoding="utf-8")

    downloads = "".join(
        f"| `{asset_names[name]}` | {config['description']} |\n"
        for name, config in VARIANTS.items()
    )
    output_hashes = "".join(
        f"   - `{asset_names[name]}` output: `{bin_hashes[name]}`\n"
        for name in VARIANTS
    )
    default_name = asset_names["default"]

    notes = staging / "RELEASE_NOTES.md"
    notes.write_text(
        f"{notes_body}\n\n"
        "## Downloads\n\n"
        "| File | Contents |\n"
        "| --- | --- |\n"
        f"{downloads}\n"
        "The default patches include the Demon Compendium, which automatically\n"
        "records recruited and fused demons and lets you summon default-stat\n"
        "copies from the Cathedral for Macca. Choose a `NO_ENHANCEMENTS` patch\n"
        "to preserve the original gameplay mechanics. Apply exactly one patch.\n\n"
        "The patches contain no game data. You need your own dump of the game;\n"
        "use only an image created from media you own, where permitted by\n"
        "applicable law.\n\n"
        "## How to apply\n\n"
        "1. Start from a verified **Shin Megami Tensei II (Japan) (Rev 1)**\n"
        f"   MODE2/2352 BIN image ({build_module.EXPECTED_BIN_SIZE:,} bytes).\n"
        f"   Its sha256 must be `{source_sha}`.\n"
        "2. Apply ONE of the patches with\n"
        "   [Delta Patcher](https://github.com/marco-calautti/DeltaPatcher/releases)\n"
        "   or xdelta3:\n\n"
        "   ```\n"
        f"   xdelta3 -d -s \"Shin Megami Tensei II (Japan) (Rev 1).bin\" {default_name} SMT2_EN.bin\n"
        "   ```\n\n"
        "3. Optionally verify the result against `sha256sums.txt`:\n"
        f"{output_hashes}"
        "4. Create `SMT2_EN.cue` next to the patched BIN with this content:\n\n"
        "   ```\n"
        "   FILE \"SMT2_EN.bin\" BINARY\n"
        "     TRACK 01 MODE2/2352\n"
        "       INDEX 01 00:00:00\n"
        "   ```\n",
        encoding="utf-8",
    )
    return [*(assets_by_variant[name] for name in VARIANTS), sums], notes


def publish(tag, version, gh, assets, notes, draft):
    git("push", "origin", RELEASE_BRANCH)
    if git("rev-parse", "-q", "--verify", f"refs/tags/{tag}", check=False).returncode != 0:
        git("tag", "-a", tag, "-m", f"SMT2 PSX English Translation {tag}")
    git("push", "origin", tag)
    command = [
        gh, "release", "create", tag,
        *[str(asset) for asset in assets],
        "--title", f"SMT2 PSX English Translation v{version}",
        "--notes-file", str(notes),
        "--verify-tag",
    ]
    if draft:
        command.append("--draft")
    print(f"\n=== creating {'draft ' if draft else ''}GitHub release {tag} ===")
    returncode, _output = run_streaming(command)
    if returncode != 0:
        fail(
            f"gh release create failed (exit {returncode}). The tag {tag} was "
            "already pushed; after fixing the problem, re-run with "
            "`--skip-build` and delete the tag first if you need to re-tag "
            f"(`git tag -d {tag}` and `git push origin :refs/tags/{tag}`)."
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Cut a release of the SMT2 PSX translation.")
    parser.add_argument("version", help="semantic version to release, e.g. 0.1.0")
    parser.add_argument("--input", metavar="BIN", help="source BIN (default: auto-detect, as build.py)")
    parser.add_argument(
        "--publish", action="store_true",
        help="publish immediately instead of creating a draft release",
    )
    parser.add_argument(
        "--skip-build", action="store_true",
        help="reuse existing build/release/v<version>/ artifacts instead of rebuilding",
    )
    parser.add_argument(
        "--allow-dirty", action="store_true",
        help="skip the clean-working-tree check (not recommended)",
    )
    args = parser.parse_args(argv)
    # build.py and the source-BIN auto-detection resolve paths relative to the
    # repository root, so anchor there regardless of where this was invoked.
    os.chdir(ROOT)
    version = args.version.lstrip("v")
    if not VERSION_RE.match(version):
        fail(f"`{args.version}` is not a semantic version like 0.1.0")

    tag, gh, notes_body, input_bin, build_module = preflight(version, args)
    staging = STAGING_ROOT / tag
    staging.mkdir(parents=True, exist_ok=True)

    variant_xdeltas = {}
    if args.skip_build:
        print("reusing existing build artifacts (--skip-build)")
        for name, config in VARIANTS.items():
            variant_xdeltas[name] = verify_variant(staging, name, config)
    else:
        for name, config in VARIANTS.items():
            variant_xdeltas[name] = build_variant(
                staging, name, config, input_bin
            )

    assets, notes = stage_release(
        staging, version, variant_xdeltas, input_bin, notes_body, build_module,
    )
    assert_assets_safe(assets, build_module.EXPECTED_BIN_SIZE)
    publish(tag, version, gh, assets, notes, draft=not args.publish)

    print(f"\nDONE. Staged release files: {staging}")
    print("Uploaded assets: " + ", ".join(asset.name for asset in assets))
    if not args.publish:
        print(
            "The release is a DRAFT. Test the patched BINs in the staging "
            f"directory if desired, then publish it on GitHub or run:\n"
            f"  gh release edit {tag} --draft=false"
        )
    print(
        "The staged BINs stay on this machine and are safe to delete once "
        "the release is published."
    )


if __name__ == "__main__":
    main()
