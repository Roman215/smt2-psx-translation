# Changelog

All notable changes to the SMT2 PSX English translation are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/): while below
1.0.0, the minor version marks notable new content or features and the patch
version marks fixes and small text improvements.

Releases ship as xdelta patches only. No game data is ever distributed; see
the release notes attached to each GitHub release for how to apply a patch to
your own verified source image.

## [Unreleased]

## [0.1.0] - 2026-07-18

First public release.

### Added

- Variable-width English rendering across dialogue, menus, and status screens
  (kerned 12x12 and 10x10 fonts, VWF hooks on all three printer paths).
- English dialogue engine: dictionary-compressed text with rebuilt Huffman
  trees covering all dialogue banks, including the negotiation/battle banks.
- Translated name tables: demons, races, spells, items, locations, NPCs,
  traits, and drinks.
- Translated menus, system strings, boot disclaimer, map/save-list location
  names, and default party names.
- English name-entry screen: A-Z/a-z/0-9 grid with an END button.
- Translated opening movie crawl, re-rendered with the game's own font at the
  original resolution and frame layout.
- Complete story translation: all dialogue banks (0-7) are in English,
  including the negotiation/battle banks.
- Reproducible build (`build.py`) that patches a verified Japan Rev 1 image
  and emits distributable xdelta patches.

[Unreleased]: https://github.com/Roman215/smt2-psx-translation/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Roman215/smt2-psx-translation/releases/tag/v0.1.0
