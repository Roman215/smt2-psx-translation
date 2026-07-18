# Shin Megami Tensei II (PSX) English Translation

Work-in-progress fan translation tools for the PlayStation release of *Shin
Megami Tensei II*. This repository contains only the translation source and
build tooling. It does not contain, distribute, or download game data.

## Screenshots

<p align="center">
  <a href="screenshots/Intro.png"><img src="screenshots/Intro.png" width="32%" alt="Translated opening crawl"></a>
  <a href="screenshots/1.png"><img src="screenshots/1.png" width="32%" alt="Translated in-game dialogue"></a>
  <a href="screenshots/2.png"><img src="screenshots/2.png" width="32%" alt="Translated equipment menu"></a>
</p>

## Requirements

- Python 3.10 or newer
- A legally obtained, verified **Shin Megami Tensei II (Japan) (Rev 1)**
  MODE2/2352 BIN image (222,694,416 bytes)

Translating the opening movie uses [FFmpeg](https://ffmpeg.org/download.html)
from `PATH` (or `--ffmpeg PATH`). The build automatically downloads the pinned
[`psxavenc` 0.3.1](https://github.com/WonderfulToolchain/psxavenc/releases/tag/v0.3.1)
release for Windows or Linux when it is not already on `PATH`. It is cached at
`build/psxavenc/bin/psxavenc.exe` (or `psxavenc` on Linux).
`--psxavenc PATH` can still be used to select an existing copy. These movie
tools are optional: if either tool is unavailable, the download fails, or the
movie cannot be generated for any other reason, the build displays a warning
and keeps the original Japanese opening movie.

[`pyxdelta`](https://pypi.org/project/pyxdelta/) is optional and is needed only
when building an xdelta patch:

```powershell
python -m pip install pyxdelta
```

## Build

1. Place the supported BIN image in the repository root. Its CUE file may sit
   alongside it for emulator use, but the build uses the BIN directly.
2. Run:

   ```powershell
   python build.py
   ```

   The build automatically mines its dialogue compression dictionary from the
   current translation corpus. The generated entries remain in memory and do
   not create or modify translation-source files.

   The usual Redump-style filename, `Shin Megami Tensei II (Japan) (Rev 1).bin`,
   is detected automatically. If the file has another name, it will still be
   used when it is the only root-level `.bin`; otherwise specify it explicitly:

   ```powershell
   python build.py --input "my-smt2-rev1.bin"
   ```

3. By default, the build writes these generated files, which are intentionally
   ignored by Git:

   - `build/SMT2_EN.bin` — rebuilt game image
   - `build/OPENING_EN.str` — generated fixed-size English opening payload

   To write the generated artifacts somewhere else, pass `--output-dir`:

   ```powershell
   python build.py --output-dir "out"
   ```

   The opening build decodes the movie from the supplied disc, replaces the
   baked-in Japanese crawl using the game's own font, and re-encodes it at the
   original 320x240, 15 fps, 10-sectors-per-frame layout. Pass `--skip-opening`
   for development builds that should retain the Japanese movie without
   checking for or downloading `psxavenc`.

4. To additionally create `SMT2_EN.xdelta` from the supplied source BIN, install
   `pyxdelta` as shown above and pass `--xdelta`:

   ```powershell
   python build.py --xdelta
   ```

The matching CUE can be copied or renamed to refer to `SMT2_EN.bin`. If you
create an xdelta for distribution, it must be applied to the same verified
source image.

## Project layout

- `build.py` — full reproducible build; extracts the needed executable and data
  files directly from the supplied BIN, patches them, fixes Mode 2 EDC/ECC, and
  optionally creates an xdelta patch.
- `tools/translations.py` — dialogue translation source.
- `tools/name_tables.py`, `menu_table.py`, `sys_strings.py`, and `map_names.py`
  — English UI, terminology, and location data.
- `tools/block_rebuild.py`, `build_en_tree.py`, `build_prod_exe.py`, `cdecc.py`,
  and `rdlogo.py` — codec and binary-patching support used by the build.
- `tools/dump_full_script.py` — optional developer utility that dumps the
  source dialogue directly from a supplied BIN.
- `tools/opening_movie.py` rebuilds the fixed-layout opening STR with the
  translated crawl.

## Developer utility

To regenerate a Japanese source-script reference without extracting the disc:

```powershell
python tools/dump_full_script.py --input "Shin Megami Tensei II (Japan) (Rev 1).bin"
```

It writes `SMT2_full_script.txt` containing the raw Japanese script.

## Legal

Use only a game image created from media you own, where permitted by applicable
law. Do not commit game binaries, CUE sheets, extracted disc files, or save
states to the repository. Release xdelta patches separately if you choose to
publish them. The build scripts target the Japan Rev 1 image only; other
revisions are not supported.
