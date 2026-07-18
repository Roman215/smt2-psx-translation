#!/usr/bin/env python3
"""Rebuild SMT2's opening crawl as a video-only PlayStation STR stream.

The Japanese narration is baked into OPENING.STR.  This module decodes the
movie from the source BIN, blacks out only the crawl band, draws the English
copy with the game's own 12x12 font, and feeds the result to psxavenc.  The
result keeps the stock 1,100-frame, 10-sectors-per-frame layout so it can be
written back in place without moving any ISO files.
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import build_en_tree as ET


SECTOR_SIZE = 2352
USER_DATA_SIZE = 2048
OPENING_LBA = 19689
OPENING_SECTORS = 11000
FRAME_SECTORS = 10
FRAME_COUNT = 1100
WIDTH = 320
HEIGHT = 240
FPS = 15

FONT_ADDRESS = 0x800D4188
FONT_WIDTH = 12
FONT_HEIGHT = 12
GLYPH_BYTES = 18

CRAWL_TOP = 150
CRAWL_START = 13.0
CRAWL_SPEED = 7.1
CRAWL_LINE_HEIGHT = 16
CRAWL_COLOR = (18, 78, 75)

# Physical lines deliberately mirror the Japanese crawl's spacing.  This
# keeps each thought on screen for about as long as in the stock movie.
CRAWL_LINES = (
    "Several decades after the Great Destruction...",
    "Tilling the wasteland, fighting hordes of demons,",
    "through countless cycles of life and death,",
    "humanity had survived...",
    "",
    "Yet people were not strong enough to live",
    "with nothing to depend on or cling to.",
    "They sought hope in tomorrow...",
    "",
    "The Messian Church preached",
    "the coming of the Messiah.",
    "Believers gathered, and a city arose...",
    "where the Cathedral once stood...",
    "",
    "20XX",
    "Thus, Tokyo became",
    "TOKYO Millennium",
)


def _foff(address: int) -> int:
    return (address - 0x80010000) + 0x800


def _sidx(code: int) -> int:
    b1, b2 = code >> 8, code & 0xFF
    row = (b1 - 0x81) if b1 < 0xA0 else (b1 - 0xC1)
    return (b2 - 0x40) + row * 189


class GameFont:
    """Tiny renderer for the executable's row-major 1bpp 12x12 font."""

    def __init__(self, executable: bytes, widths: dict[int, int]):
        self.executable = executable
        self.widths = widths
        self.base = _foff(FONT_ADDRESS)

    def index(self, character: str) -> int:
        try:
            return _sidx(ET.fullwidth(character))
        except KeyError as exc:
            raise ValueError(f"opening crawl has unsupported character {character!r}") from exc

    def advance(self, character: str, fixed: int | None = None) -> int:
        if fixed is not None:
            return fixed
        index = self.index(character)
        return self.widths.get(index, FONT_WIDTH)

    def text_width(self, text: str, tracking: int = 0, fixed: int | None = None) -> int:
        if not text:
            return 0
        return sum(self.advance(ch, fixed) for ch in text) + tracking * (len(text) - 1)

    def draw_centered(
        self,
        frame: bytearray,
        text: str,
        top: int,
        color: tuple[int, int, int],
        *,
        clip_top: int = 0,
        clip_bottom: int = HEIGHT,
        tracking: int = 0,
        fixed: int | None = None,
    ) -> None:
        if not text:
            return
        left = (WIDTH - self.text_width(text, tracking, fixed)) // 2
        for character in text:
            index = self.index(character)
            glyph = self.base + index * GLYPH_BYTES
            for y in range(FONT_HEIGHT):
                py = top + y
                if py < clip_top or py >= clip_bottom:
                    continue
                for x in range(FONT_WIDTH):
                    bit = y * FONT_WIDTH + x
                    if self.executable[glyph + (bit >> 3)] & (1 << (7 - (bit & 7))):
                        px = left + x
                        if 0 <= px < WIDTH:
                            offset = (py * WIDTH + px) * 3
                            frame[offset : offset + 3] = bytes(color)
            left += self.advance(character, fixed) + tracking


def _read_exact(stream, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _extract_raw_opening(input_bin: Path, output: Path) -> None:
    with input_bin.open("rb") as source, output.open("wb") as target:
        source.seek(OPENING_LBA * SECTOR_SIZE)
        remaining = OPENING_SECTORS * SECTOR_SIZE
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError("source BIN ended while extracting OPENING.STR")
            target.write(chunk)
            remaining -= len(chunk)

    with output.open("rb") as stream:
        first = stream.read(SECTOR_SIZE)
        stream.seek((OPENING_SECTORS - 1) * SECTOR_SIZE)
        last = stream.read(SECTOR_SIZE)
    expected = (0x0160, 0x8001, 0, FRAME_SECTORS)
    if struct.unpack_from("<HHHH", first, 24) != expected:
        raise RuntimeError("unexpected OPENING.STR first-sector header")
    if struct.unpack_from("<I", first, 32)[0] != 1:
        raise RuntimeError("unexpected OPENING.STR first frame number")
    if struct.unpack_from("<I", last, 32)[0] != FRAME_COUNT:
        raise RuntimeError("unexpected OPENING.STR final frame number")


def _render_video(
    raw_opening: Path,
    output_video: Path,
    ffmpeg: str,
    executable: bytes,
    widths: dict[int, int],
) -> None:
    frame_size = WIDTH * HEIGHT * 3
    font = GameFont(executable, widths)
    black_frame = bytes(frame_size)
    black_band = bytes((HEIGHT - CRAWL_TOP) * WIDTH * 3)

    decoder = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "psxstr",
            "-i",
            str(raw_opening),
            "-an",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    encoder = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{WIDTH}x{HEIGHT}",
            "-framerate",
            str(FPS),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "ffv1",
            "-level",
            "3",
            "-pix_fmt",
            "yuv420p",
            str(output_video),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert decoder.stdout is not None
    assert encoder.stdin is not None

    last_frame = None
    try:
        for frame_number in range(FRAME_COUNT):
            decoded = _read_exact(decoder.stdout, frame_size)
            if len(decoded) != frame_size:
                raise RuntimeError(
                    f"FFmpeg decoded only {frame_number}/{FRAME_COUNT} opening frames"
                )
            frame = bytearray(decoded)
            timestamp = frame_number / FPS

            # Replace the stock Japanese date card.  Its background is solid
            # black, so no source art is discarded here.
            if timestamp < 4.7:
                frame[:] = black_frame
                fade = min((timestamp - 0.5) / 0.8, (4.7 - timestamp) / 0.8, 1.0)
                if fade > 0:
                    color = tuple(round(component * fade) for component in CRAWL_COLOR)
                    font.draw_centered(
                        frame,
                        "20XX  TOKYO",
                        95,
                        color,
                        tracking=6,
                        fixed=12,
                    )

            # The crawl is entirely below the skyline.  Blank only that black
            # band, preserving every pixel of the moving city above it.
            elif timestamp < 58.4:
                frame[CRAWL_TOP * WIDTH * 3 :] = black_band
                first_top = 241 - CRAWL_SPEED * (timestamp - CRAWL_START)
                for line_number, line in enumerate(CRAWL_LINES):
                    top = round(first_top + line_number * CRAWL_LINE_HEIGHT)
                    if top < HEIGHT and top + FONT_HEIGHT > CRAWL_TOP:
                        font.draw_centered(
                            frame,
                            line,
                            top,
                            CRAWL_COLOR,
                            clip_top=CRAWL_TOP,
                            clip_bottom=HEIGHT,
                        )

            encoder.stdin.write(frame)
            last_frame = bytes(frame)

        # psxavenc 0.3.1 consumes two look-ahead frames without emitting them.
        # Two cloned tail frames yield the stock 1,100 encoded frames exactly.
        assert last_frame is not None
        encoder.stdin.write(last_frame)
        encoder.stdin.write(last_frame)
        encoder.stdin.close()
        decoder.stdout.close()

        decoder_error = decoder.stderr.read().decode("utf-8", errors="replace")
        encoder_error = encoder.stderr.read().decode("utf-8", errors="replace")
        decoder_code = decoder.wait()
        encoder_code = encoder.wait()
        if decoder_code:
            raise RuntimeError(f"FFmpeg STR decode failed:\n{decoder_error.strip()}")
        if encoder_code:
            raise RuntimeError(f"FFmpeg lossless encode failed:\n{encoder_error.strip()}")
    except Exception:
        decoder.kill()
        encoder.kill()
        raise


def _validate_strv(path: Path) -> None:
    expected_size = OPENING_SECTORS * USER_DATA_SIZE
    if path.stat().st_size != expected_size:
        raise RuntimeError(
            f"encoded OPENING.STR is {path.stat().st_size:,} bytes; "
            f"expected {expected_size:,}"
        )
    with path.open("rb") as stream:
        first = stream.read(USER_DATA_SIZE)
        stream.seek((OPENING_SECTORS - FRAME_SECTORS) * USER_DATA_SIZE)
        last_frame = stream.read(USER_DATA_SIZE)
    if struct.unpack_from("<HHHHI", first, 0) != (0x0160, 0x8001, 0, 10, 1):
        raise RuntimeError("encoded OPENING.STR has an unexpected first frame header")
    if struct.unpack_from("<HHHHI", last_frame, 0) != (
        0x0160,
        0x8001,
        0,
        10,
        FRAME_COUNT,
    ):
        raise RuntimeError("encoded OPENING.STR has an unexpected final frame header")


def generate_opening(
    input_bin: str | Path,
    executable: bytes,
    widths: dict[int, int],
    output: str | Path,
    *,
    ffmpeg: str,
    psxavenc: str,
) -> Path:
    """Generate a fixed-size English OPENING.STR payload and return its path."""

    input_bin = Path(input_bin)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smt2-opening-") as temporary:
        temporary = Path(temporary)
        raw_opening = temporary / "OPENING_raw.str"
        translated_video = temporary / "OPENING_EN.mkv"
        _extract_raw_opening(input_bin, raw_opening)
        _render_video(raw_opening, translated_video, ffmpeg, executable, widths)
        subprocess.run(
            [
                psxavenc,
                "-q",
                "-t",
                "strv",
                "-v",
                "v2",
                "-s",
                f"{WIDTH}x{HEIGHT}",
                "-r",
                str(FPS),
                "-x",
                "2",
                str(translated_video),
                str(output),
            ],
            check=True,
        )
    _validate_strv(output)
    return output


def find_tool(requested: str | None, name: str, local: Path | None = None) -> str:
    """Resolve a required external executable with a useful build error."""

    candidates = []
    if requested:
        candidates.append(Path(requested))
    if local is not None:
        candidates.append(local)
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    found = shutil.which(name)
    if found:
        return found
    hint = f" (or pass its path explicitly)" if requested is None else ""
    raise SystemExit(f"Required opening-movie tool not found: {name}{hint}")
