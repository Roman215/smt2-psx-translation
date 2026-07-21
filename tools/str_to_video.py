#!/usr/bin/env python3
"""Convert SMT2's Extracted/STR PlayStation movies into files you can watch.

The files under ``Extracted/STR`` are raw STR *payloads*: 2048 data bytes per
CD sector with the CD sync/header/subheader stripped, each sector beginning
with the standard STR frame header (``0x0160 0x8001 ...``).  FFmpeg's ``psxstr``
demuxer expects full 2352-byte raw CD (Mode 2) sectors, so this tool re-wraps
each payload block back into a sector, decodes the MDEC video with FFmpeg, and
re-encodes to an H.264 MP4 that plays in VLC or Media Player Classic.

The extraction dropped the interleaved XA audio, so these previews are silent.
That is fine for the purpose here: confirming what on-screen text each movie
has so the Japanese can be translated (see tools/opening_movie.py for the
OPENING/GAMEOVER subtitle rebuild).

Usage
-----
    # Convert every *.STR in Extracted/STR -> Extracted/STR/preview/*.mp4
    python tools/str_to_video.py

    # Just one or a few (by name or path)
    python tools/str_to_video.py OPENING.STR GAMEOVER.STR

    # 2x nearest-neighbour upscale (crisper small text), custom output dir
    python tools/str_to_video.py --scale 2 --out watch OPENING.STR
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SECTOR_SIZE = 2352
PAYLOAD_SIZE = 2048
HEADER_SIZE = 24  # 12-byte sync + 4-byte address/mode + 8-byte subheader
FPS = 15  # SMT2's MDEC streams play at 15 fps (matches tools/opening_movie.py)

# First four payload bytes of an STR video sector: the frame header's
# 0x0160 status word followed by the 0x8001 STR magic (both little-endian).
# Movies that carry sound interleave XA-audio sectors (typically every 8th
# sector); those lack this signature and must not be wrapped as video.
STR_VIDEO_MAGIC = bytes([0x60, 0x01, 0x01, 0x80])

# 12-byte CD sector sync pattern.
SYNC = bytes([0x00] + [0xFF] * 10 + [0x00])
# Subheader: file 0, channel 0, submode 0x08 (data), coding 0 -- written twice.
# FFmpeg's psxstr demuxer reads the channel at sector[0x11] and the submode at
# sector[0x12]; the data submode routes the sector into the video stream.
SUBHEADER = bytes([0x00, 0x00, 0x08, 0x00]) * 2

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT_DIR = REPO_ROOT / "Extracted" / "STR"


def _bcd(value: int) -> int:
    return (value // 10 << 4) | (value % 10)


def _address(lba: int) -> bytes:
    """Encode a logical block address as the sector's BCD MM:SS:FF + mode 2."""
    minutes = lba // (75 * 60)
    seconds = (lba // 75) % 60
    frames = lba % 75
    return bytes([_bcd(minutes), _bcd(seconds), _bcd(frames), 0x02])


def _wrap_sector(payload: bytes, lba: int) -> bytes:
    """Rebuild a 2352-byte Mode 2 sector around a 2048-byte STR payload."""
    sector = SYNC + _address(lba) + SUBHEADER + payload
    return sector + bytes(SECTOR_SIZE - len(sector))


def build_raw_stream(source: Path, destination: Path) -> tuple[int, int]:
    """Re-wrap the video payloads of ``source`` into a psxstr-readable file.

    Only sectors that begin with the STR video magic are wrapped and written;
    interleaved XA-audio sectors are dropped (their 2048-byte extracts are
    truncated and cannot be cleanly decoded anyway).  Returns
    ``(video_sectors, dropped_sectors)``.  The starting LBA is arbitrary (150,
    the usual post-pregap start); only its steadily increasing value matters,
    and the demuxer ignores it entirely.
    """
    size = source.stat().st_size
    if size % PAYLOAD_SIZE:
        raise ValueError(
            f"{source.name} is {size} bytes, not a whole number of "
            f"{PAYLOAD_SIZE}-byte STR payload sectors"
        )
    total = size // PAYLOAD_SIZE
    written = 0
    with source.open("rb") as src, destination.open("wb") as dst:
        for _ in range(total):
            payload = src.read(PAYLOAD_SIZE)
            if payload[:4] != STR_VIDEO_MAGIC:
                continue
            dst.write(_wrap_sector(payload, 150 + written))
            written += 1
    return written, total - written


def find_ffmpeg(requested: str | None) -> str:
    if requested:
        candidate = Path(requested)
        if candidate.is_file():
            return str(candidate.resolve())
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise SystemExit(
        "FFmpeg was not found on PATH. Install it or pass --ffmpeg <path>."
    )


def convert(
    source: Path,
    destination: Path,
    ffmpeg: str,
    *,
    scale: int = 1,
    crf: int = 18,
    fps: int = FPS,
) -> None:
    """Decode one STR payload file to a playable H.264 video at ``destination``."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smt2-str-") as tmp:
        raw = Path(tmp) / "raw.str"
        video_sectors, audio_sectors = build_raw_stream(source, raw)

        video_filters = []
        if scale > 1:
            video_filters.append(f"scale=iw*{scale}:ih*{scale}:flags=neighbor")

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "psxstr",
            "-r",
            str(fps),
            "-i",
            str(raw),
            "-an",
            "-c:v",
            "libx264",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
        ]
        if video_filters:
            command += ["-vf", ",".join(video_filters)]
        command.append(str(destination))

        subprocess.run(command, check=True)
    shown = (
        destination.relative_to(REPO_ROOT)
        if destination.is_relative_to(REPO_ROOT)
        else destination
    )
    audio_note = f", {audio_sectors} audio sectors dropped" if audio_sectors else ""
    print(f"  {source.name} ({video_sectors} video sectors{audio_note}) -> {shown}")


def _resolve_sources(names: list[str], input_dir: Path) -> list[Path]:
    if not names:
        sources = sorted(input_dir.glob("*.STR")) + sorted(input_dir.glob("*.str"))
        if not sources:
            raise SystemExit(f"No .STR files found in {input_dir}")
        # De-duplicate on case-insensitive filesystems.
        seen: dict[str, Path] = {}
        for path in sources:
            seen.setdefault(path.name.lower(), path)
        return list(seen.values())

    sources = []
    for name in names:
        candidate = Path(name)
        if not candidate.is_file():
            candidate = input_dir / name
        if not candidate.is_file():
            raise SystemExit(f"STR file not found: {name}")
        sources.append(candidate)
    return sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert Extracted/STR PlayStation MDEC movies to watchable video "
            "(silent) so their on-screen text can be reviewed for translation."
        )
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="STR files to convert (name or path). Default: every *.STR in the input dir.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"directory holding the STR files (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: <input-dir>/preview)",
    )
    parser.add_argument(
        "--format",
        default="mp4",
        help="output container/extension, e.g. mp4 or mkv (default: mp4)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=1,
        help="integer nearest-neighbour upscale for crisper small text (default: 1)",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=18,
        help="libx264 quality; lower is better/larger (default: 18)",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=FPS,
        help=f"playback frame rate (default: {FPS})",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="path to the FFmpeg executable (default: found on PATH)",
    )
    args = parser.parse_args(argv)

    if args.scale < 1:
        parser.error("--scale must be 1 or greater")

    ffmpeg = find_ffmpeg(args.ffmpeg)
    sources = _resolve_sources(args.files, args.input_dir)
    out_dir = args.out if args.out is not None else args.input_dir / "preview"
    extension = args.format.lstrip(".")

    print(f"Converting {len(sources)} movie(s) -> {out_dir}")
    failures = 0
    for source in sources:
        destination = out_dir / f"{source.stem}.{extension}"
        try:
            convert(
                source,
                destination,
                ffmpeg,
                scale=args.scale,
                crf=args.crf,
                fps=args.fps,
            )
        except (subprocess.CalledProcessError, ValueError) as error:
            failures += 1
            print(f"  FAILED {source.name}: {error}", file=sys.stderr)

    if failures:
        print(f"{failures} movie(s) failed.", file=sys.stderr)
        return 1
    print("Done. These previews are silent (STR audio was not extracted).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
