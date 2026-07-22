#!/usr/bin/env python3
"""Rebuild SMT2's subtitled video-only PlayStation STR streams.

The Japanese narration is baked into OPENING.STR and GAMEOVER.STR.  This
module decodes both movies from the source BIN, removes only their Japanese
text, draws English with the game's own 12x12 font, and feeds the result to
psxavenc.  Each result keeps its stock frame and sector layout so it can be
written back in place without moving any ISO files.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import build_en_tree as ET


SECTOR_SIZE = 2352
USER_DATA_SIZE = 2048
FRAME_SECTORS = 10
WIDTH = 320
HEIGHT = 240
FPS = 15


@dataclass(frozen=True)
class MovieSpec:
    filename: str
    output_name: str
    lba: int
    sectors: int
    frames: int


OPENING = MovieSpec("OPENING.STR", "OPENING_EN.str", 19689, 11000, 1100)
GAMEOVER = MovieSpec("GAMEOVER.STR", "GAMEOVER_EN.str", 11739, 5650, 565)
MOVIES = (OPENING, GAMEOVER)

# Compatibility constants used by older tooling and external scripts.
OPENING_LBA = OPENING.lba
OPENING_SECTORS = OPENING.sectors
FRAME_COUNT = OPENING.frames

PSXAVENC_VERSION = "0.3.1"
PSXAVENC_RELEASE_URL = (
    "https://github.com/WonderfulToolchain/psxavenc/releases/download/"
    f"v{PSXAVENC_VERSION}"
)
PSXAVENC_DOWNLOADS = {
    "win32": (
        "psxavenc-windows.zip",
        "bin/psxavenc.exe",
        "b44a4cf5a8c293a27182cddcca513428b26f0e143189ad53e29e6729b3d9a7a5",
    ),
    "linux": (
        "psxavenc-linux.zip",
        "bin/psxavenc",
        "ad22b887683631149fb8c7c85ecea8bb760dd482f9e18cce2b35b11319e95e51",
    ),
}

FONT_ADDRESS = 0x800D4188
FONT_WIDTH = 12
FONT_HEIGHT = 12
GLYPH_BYTES = 18

CRAWL_TOP = 150
CRAWL_START = 13.0
CRAWL_SPEED = 7.1
CRAWL_LINE_HEIGHT = 16
CRAWL_COLOR = (18, 78, 75)

GAMEOVER_CLEAN_START = 199       # zero-based frame 200
GAMEOVER_CLEAN_END = 232         # through frame 232, before the text fade
GAMEOVER_TEXT_START = 232        # frame 233, first faded text
GAMEOVER_TEXT_END = 319          # frame 319, last faded text
GAMEOVER_PATCH_LEFT = 30
GAMEOVER_PATCH_RIGHT = 290
GAMEOVER_PATCH_TOP = 141
GAMEOVER_PATCH_BOTTOM = 200
GAMEOVER_TEXT_TOP = 148
GAMEOVER_LINE_HEIGHT = 16
GAMEOVER_TEXT_COLOR = (240, 240, 240)
GAMEOVER_LINES = (
    "Charon: Beyond the river lies the eternal land,",
    "where the souls of the dead await rebirth.",
    "Now, cross the river...",
)

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
            raise ValueError(f"movie text has unsupported character {character!r}") from exc

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
        outline: int = 0,
        outline_color: tuple[int, int, int] = (0, 0, 0),
        alpha: float = 1.0,
    ) -> None:
        if not text or alpha <= 0:
            return
        alpha = min(alpha, 1.0)
        left = (WIDTH - self.text_width(text, tracking, fixed)) // 2
        pixels = set()
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
                            pixels.add((px, py))
            left += self.advance(character, fixed) + tracking

        def paint(points, paint_color):
            solid = bytes(paint_color)
            for px, py in points:
                if not (0 <= px < WIDTH and clip_top <= py < clip_bottom):
                    continue
                offset = (py * WIDTH + px) * 3
                if alpha >= 1:
                    frame[offset : offset + 3] = solid
                else:
                    for component in range(3):
                        frame[offset + component] = round(
                            frame[offset + component] * (1 - alpha)
                            + paint_color[component] * alpha
                        )

        if outline:
            outlined = {
                (px + dx, py + dy)
                for px, py in pixels
                for dy in range(-outline, outline + 1)
                for dx in range(-outline, outline + 1)
            }
            paint(outlined - pixels, outline_color)
        paint(pixels, color)


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


def _extract_raw_movie(input_bin: Path, output: Path, spec: MovieSpec) -> None:
    with input_bin.open("rb") as source, output.open("wb") as target:
        source.seek(spec.lba * SECTOR_SIZE)
        remaining = spec.sectors * SECTOR_SIZE
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RuntimeError(f"source BIN ended while extracting {spec.filename}")
            target.write(chunk)
            remaining -= len(chunk)

    with output.open("rb") as stream:
        first = stream.read(SECTOR_SIZE)
        stream.seek((spec.sectors - 1) * SECTOR_SIZE)
        last = stream.read(SECTOR_SIZE)
    expected = (0x0160, 0x8001, 0, FRAME_SECTORS)
    if struct.unpack_from("<HHHH", first, 24) != expected:
        raise RuntimeError(f"unexpected {spec.filename} first-sector header")
    if struct.unpack_from("<I", first, 32)[0] != 1:
        raise RuntimeError(f"unexpected {spec.filename} first frame number")
    if struct.unpack_from("<I", last, 32)[0] != spec.frames:
        raise RuntimeError(f"unexpected {spec.filename} final frame number")


def _opening_editor(font: GameFont):
    black_frame = bytes(WIDTH * HEIGHT * 3)
    black_band = bytes((HEIGHT - CRAWL_TOP) * WIDTH * 3)

    def edit(frame: bytearray, frame_number: int) -> None:
        timestamp = frame_number / FPS

        # Replace the stock Japanese date card.  Its background is solid
        # black, so no source art is discarded here.
        if timestamp < 4.7:
            frame[:] = black_frame
            fade = min((timestamp - 0.5) / 0.8, (4.7 - timestamp) / 0.8, 1.0)
            if fade > 0:
                color = tuple(round(component * fade) for component in CRAWL_COLOR)
                font.draw_centered(
                    frame, "20XX  TOKYO", 95, color, tracking=6, fixed=12
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

    return edit


def _gameover_editor(font: GameFont):
    clean_frames = []
    compare_rows = (*range(136, 141), *range(200, 205))
    compare_columns = range(GAMEOVER_PATCH_LEFT, GAMEOVER_PATCH_RIGHT, 4)

    def boundary_error(frame: bytearray, candidate: bytes) -> int:
        error = 0
        for y in compare_rows:
            for x in compare_columns:
                offset = (y * WIDTH + x) * 3
                error += abs(frame[offset] - candidate[offset])
                error += abs(frame[offset + 1] - candidate[offset + 1])
                error += abs(frame[offset + 2] - candidate[offset + 2])
        return error

    def restore_text_band(frame: bytearray) -> None:
        if len(clean_frames) != GAMEOVER_CLEAN_END - GAMEOVER_CLEAN_START:
            raise RuntimeError("GAMEOVER.STR clean-frame reservoir is incomplete")
        clean = min(clean_frames, key=lambda candidate: boundary_error(frame, candidate))
        feather = 5
        for y in range(GAMEOVER_PATCH_TOP, GAMEOVER_PATCH_BOTTOM):
            vertical = min(
                1.0,
                (y - GAMEOVER_PATCH_TOP) / feather,
                (GAMEOVER_PATCH_BOTTOM - 1 - y) / feather,
            )
            for x in range(GAMEOVER_PATCH_LEFT, GAMEOVER_PATCH_RIGHT):
                alpha = min(
                    vertical,
                    (x - GAMEOVER_PATCH_LEFT) / feather,
                    (GAMEOVER_PATCH_RIGHT - 1 - x) / feather,
                    1.0,
                )
                if alpha <= 0:
                    continue
                offset = (y * WIDTH + x) * 3
                for component in range(3):
                    frame[offset + component] = round(
                        frame[offset + component] * (1 - alpha)
                        + clean[offset + component] * alpha
                    )

    def edit(frame: bytearray, frame_number: int) -> None:
        if GAMEOVER_CLEAN_START <= frame_number < GAMEOVER_CLEAN_END:
            clean_frames.append(bytes(frame))

        if GAMEOVER_TEXT_START <= frame_number < GAMEOVER_TEXT_END:
            restore_text_band(frame)
            source_frame = frame_number + 1
            if source_frame <= 236:
                fade = (0.4, 0.6, 0.8, 1.0)[source_frame - 233]
            elif source_frame >= 316:
                fade = (0.85, 0.7, 0.55, 0.4)[source_frame - 316]
            else:
                fade = 1.0
            for line_number, line in enumerate(GAMEOVER_LINES):
                font.draw_centered(
                    frame,
                    line,
                    GAMEOVER_TEXT_TOP + line_number * GAMEOVER_LINE_HEIGHT,
                    GAMEOVER_TEXT_COLOR,
                    outline=1,
                    alpha=fade,
                )

    return edit


def _render_video(
    raw_movie: Path,
    output_video: Path,
    ffmpeg: str,
    spec: MovieSpec,
    edit_frame,
) -> None:
    frame_size = WIDTH * HEIGHT * 3

    decoder = subprocess.Popen(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "psxstr",
            "-i",
            str(raw_movie),
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
            "gbrp",
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
        for frame_number in range(spec.frames):
            decoded = _read_exact(decoder.stdout, frame_size)
            if len(decoded) != frame_size:
                raise RuntimeError(
                    f"FFmpeg decoded only {frame_number}/{spec.frames} "
                    f"{spec.filename} frames"
                )
            frame = bytearray(decoded)
            edit_frame(frame, frame_number)

            encoder.stdin.write(frame)
            last_frame = bytes(frame)

        # psxavenc 0.3.1 consumes two look-ahead frames without emitting them.
        # Two cloned tail frames yield the stock frame count exactly.
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


def _validate_black_first_frame(
    path: Path, raw_movie: Path, ffmpeg: str, spec: MovieSpec
) -> None:
    preview = path.with_suffix(".first-frame.raw")
    with path.open("rb") as payload, raw_movie.open("rb") as source, preview.open("wb") as out:
        for _ in range(FRAME_SECTORS):
            sector = bytearray(source.read(SECTOR_SIZE))
            chunk = payload.read(USER_DATA_SIZE)
            if len(sector) != SECTOR_SIZE or len(chunk) != USER_DATA_SIZE:
                raise RuntimeError(f"could not stage {spec.filename} first-frame validation")
            sector[24 : 24 + USER_DATA_SIZE] = chunk
            out.write(sector)
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "psxstr",
                "-i",
                str(preview),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        )
    finally:
        preview.unlink(missing_ok=True)
    frame = result.stdout
    if len(frame) != WIDTH * HEIGHT * 3 or max(frame, default=255) > 2:
        raise RuntimeError(
            f"encoded {spec.filename} does not begin on a true-black frame; "
            "this can produce a colored startup flicker"
        )


def _validate_strv(path: Path, raw_movie: Path, ffmpeg: str, spec: MovieSpec) -> None:
    expected_size = spec.sectors * USER_DATA_SIZE
    if path.stat().st_size != expected_size:
        raise RuntimeError(
            f"encoded {spec.filename} is {path.stat().st_size:,} bytes; "
            f"expected {expected_size:,}"
        )
    with path.open("rb") as stream:
        first = stream.read(USER_DATA_SIZE)
        stream.seek((spec.sectors - FRAME_SECTORS) * USER_DATA_SIZE)
        last_frame = stream.read(USER_DATA_SIZE)
    if struct.unpack_from("<HHHHI", first, 0) != (0x0160, 0x8001, 0, 10, 1):
        raise RuntimeError(f"encoded {spec.filename} has an unexpected first frame header")
    if struct.unpack_from("<HHHHI", last_frame, 0) != (
        0x0160,
        0x8001,
        0,
        10,
        spec.frames,
    ):
        raise RuntimeError(f"encoded {spec.filename} has an unexpected final frame header")
    _validate_black_first_frame(path, raw_movie, ffmpeg, spec)


def generate_movies(
    input_bin: str | Path,
    executable: bytes,
    widths: dict[int, int],
    output_directory: str | Path,
    *,
    ffmpeg: str,
    psxavenc: str,
) -> dict[str, Path]:
    """Generate fixed-size English movie payloads keyed by disc filename."""

    input_bin = Path(input_bin)
    output_directory = Path(output_directory)
    output_directory.mkdir(parents=True, exist_ok=True)
    # Stage on the output drive so the large intermediates never cross volumes.
    # Do not rename the encoded files into the output directory: on Windows a
    # rename preserves the temporary directory's ACL, which can make the final
    # files unreadable by a later sandboxed build process.  Copying the bytes
    # into a destination created directly under output_directory makes the
    # final files inherit that directory's ACL.
    with tempfile.TemporaryDirectory(
        prefix="smt2-movies-", dir=output_directory
    ) as temporary:
        temporary = Path(temporary)
        font = GameFont(executable, widths)
        encoded = {}
        for spec, editor in (
            (OPENING, _opening_editor(font)),
            (GAMEOVER, _gameover_editor(font)),
        ):
            stem = Path(spec.filename).stem
            raw_movie = temporary / f"{stem}_raw.str"
            translated_video = temporary / f"{stem}_EN.mkv"
            encoded_movie = temporary / spec.output_name
            _extract_raw_movie(input_bin, raw_movie, spec)
            _render_video(raw_movie, translated_video, ffmpeg, spec, editor)
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
                    str(encoded_movie),
                ],
                check=True,
            )
            _validate_strv(encoded_movie, raw_movie, ffmpeg, spec)
            encoded[spec.filename] = encoded_movie

        outputs = {}
        for spec in MOVIES:
            output = output_directory / spec.output_name
            shutil.copyfile(encoded[spec.filename], output)
            outputs[spec.filename] = output
    return outputs


def download_psxavenc(install_directory: str | Path) -> Path:
    """Download and atomically install the pinned psxavenc release."""

    try:
        archive_name, archive_member, expected_hash = PSXAVENC_DOWNLOADS[sys.platform]
    except KeyError as exc:
        raise RuntimeError(f"no psxavenc download is available for {sys.platform}") from exc

    install_directory = Path(install_directory)
    install_directory.parent.mkdir(parents=True, exist_ok=True)
    url = f"{PSXAVENC_RELEASE_URL}/{archive_name}"
    request = urllib.request.Request(url, headers={"User-Agent": "SMT2-English-build"})

    with tempfile.TemporaryDirectory(
        prefix="psxavenc-download-", dir=install_directory.parent
    ) as temporary:
        temporary = Path(temporary)
        archive_path = temporary / archive_name
        with urllib.request.urlopen(request, timeout=30) as response:
            with archive_path.open("wb") as archive_file:
                shutil.copyfileobj(response, archive_file)

        digest = hashlib.sha256()
        with archive_path.open("rb") as archive_file:
            for chunk in iter(lambda: archive_file.read(1024 * 1024), b""):
                digest.update(chunk)
        actual_hash = digest.hexdigest()
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"downloaded {archive_name} has SHA-256 {actual_hash}; "
                f"expected {expected_hash}"
            )

        temporary_executable = temporary / Path(archive_member).name
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(archive_member) as source:
                with temporary_executable.open("wb") as destination:
                    shutil.copyfileobj(source, destination)
        if sys.platform != "win32":
            temporary_executable.chmod(0o755)

        installed_executable = install_directory / archive_member
        installed_executable.parent.mkdir(parents=True, exist_ok=True)
        temporary_executable.replace(installed_executable)

    return installed_executable


def find_tool(
    requested: str | None,
    name: str,
    local: Path | None = None,
    *,
    required: bool = True,
) -> str | None:
    """Resolve an external executable, optionally returning None if unavailable."""

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
    if not required:
        return None
    hint = f" (or pass its path explicitly)" if requested is None else ""
    raise SystemExit(f"Required movie tool not found: {name}{hint}")
