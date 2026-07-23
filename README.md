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

## Downloads

Pre-built patches are published on the
[Releases](https://github.com/Roman215/smt2-psx-translation/releases) page.
Each release carries three xdelta patches: one with the translated English
opening and game-over movies, one keeping the original Japanese movies, and a
clearly named Demon Compendium enhancement variant with the English movies.
Every release includes `sha256sums.txt` and step-by-step patching instructions.
The patches contain no game data; apply one of them to your own verified **Shin
Megami Tensei II (Japan) (Rev 1)** BIN image with
[Delta Patcher](https://github.com/marco-calautti/DeltaPatcher/releases) or
xdelta3.

To build from source instead, read on.

## Requirements

- Python 3.10 or newer
- A legally obtained, verified **Shin Megami Tensei II (Japan) (Rev 1)**
  MODE2/2352 BIN image (222,694,416 bytes)

Translating the movies uses [FFmpeg](https://ffmpeg.org/download.html)
from `PATH` (or `--ffmpeg PATH`). The build automatically downloads the pinned
[`psxavenc` 0.3.1](https://github.com/WonderfulToolchain/psxavenc/releases/tag/v0.3.1)
release for Windows or Linux when it is not already on `PATH`. It is cached at
`build/psxavenc/bin/psxavenc.exe` (or `psxavenc` on Linux).
`--psxavenc PATH` can still be used to select an existing copy. These movie
tools are optional: if either tool is unavailable, the download fails, or the
movies cannot be generated for any other reason, the build displays a warning
and keeps the original Japanese movies.

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
   - `build/GAMEOVER_EN.str` — generated fixed-size English game-over payload

   To write the generated artifacts somewhere else, pass `--output-dir`:

   ```powershell
   python build.py --output-dir "out"
   ```

   The movie build decodes both STRs from the supplied disc, replaces the
   baked-in Japanese text using the game's own font, and re-encodes them at the
   original 320x240, 15 fps, 10-sectors-per-frame layouts. Pass `--skip-movies`
   for development builds that should retain the Japanese movies without
   checking for or downloading `psxavenc`. Pass `--require-movies` to abort
   the build if either movie cannot be generated instead of warning and keeping
   the Japanese movies — release builds use this so the English-movie patch can
   never silently ship the wrong video.

4. To additionally create `SMT2_EN.xdelta` from the supplied source BIN, install
   `pyxdelta` as shown above and pass `--xdelta`:

   ```powershell
   python build.py --xdelta
   ```

### Optional Demon Compendium

The standard build preserves the original game mechanics. To build the
separate gameplay-enhancement variant, pass `--compendium`:

```powershell
python build.py --compendium
```

This creates `SMT2_EN_COMPENDIUM.bin` (and
`SMT2_EN_COMPENDIUM.xdelta` when combined with `--xdelta`). At the Cathedral
of Shadows, its **Demon Compendium** option lists normal demons that the player
has previously recruited or fused and lets the player summon their fixed,
default-stat form for `level x level x 20` Macca. Demons above the protagonist's
level and duplicates already held cannot be summoned. Human party members and
enemy-only records never enter the list through normal play. Existing party
demons are registered as soon as the enhanced Cathedral menu is rendered, so
they remain recorded even if the player chooses fusion before opening the
Compendium itself. Newly negotiated demons are registered when they are added
to the party, so abandoning one before visiting the Cathedral does not remove
its record.

The enhancement does not enlarge or rewrite the game's save structure. Its
registration flags reuse the high bit of an existing saved per-demon counter,
so the original payload size and memory-card checksum process stay unchanged.
Existing saves can be loaded, but keep a backup or a separate memory card for
the enhancement variant: returning that save to an unmodified game can make
the reused counter appear 128 higher. Conversely, a pre-existing save where a
particular demon's counter has already reached 128 may initially treat that
demon as registered. `build.py` never opens or modifies save states or
memory-card files.

The matching CUE can be copied or renamed to refer to the generated BIN. If
you create an xdelta for distribution, it must be applied to the same verified
source image.

## Releasing

Version history lives in [CHANGELOG.md](CHANGELOG.md). Maintainers cut
releases locally with `python release.py X.Y.Z`, which builds all patch
variants, tags the version, and uploads only the xdelta patches and checksums
to a GitHub release — see [RELEASING.md](RELEASING.md). CI verifies on every
push that no game data is tracked in the repository.

## Project layout

- `build.py` — full reproducible build; extracts the needed executable and data
  files directly from the supplied BIN, patches them, fixes Mode 2 EDC/ECC, and
  optionally creates an xdelta patch.
- `release.py` — release automation: builds every patch variant, stages
  checksums and notes from `CHANGELOG.md`, and publishes a GitHub release
  containing only distributable files.
- `tools/translations.py` — dialogue translation source.
- `tools/name_tables.py`, `menu_table.py`, `sys_strings.py`, and `map_names.py`
  — English UI, terminology, and location data.
- `tools/block_rebuild.py`, `build_en_tree.py`, `build_prod_exe.py`, `cdecc.py`,
  and `rdlogo.py` — codec and binary-patching support used by the build.
- `tools/dump_full_script.py` — optional developer utility that dumps the
  source dialogue directly from a supplied BIN.
- `tools/opening_movie.py` rebuilds the fixed-layout opening and game-over STRs
  with translated text.
- `tools/compendium.py` installs the optional Cathedral compendium and its
  save-compatible registration flags only for `--compendium` builds.

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
