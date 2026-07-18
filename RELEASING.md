# Releasing

Releases are GitHub Releases carrying **only** xdelta patches, checksums, and
notes. Game data (BIN/CUE, extracted files, patched images) is never uploaded;
`release.py` enforces this with an asset allowlist, and CI independently
verifies that no game data is ever committed to the repository.

Because building requires the (non-distributable) source image, releases are
always built locally and then published with the GitHub CLI. There is no CI
build.

## One-time setup

```powershell
winget install --id GitHub.cli --scope user
gh auth login
python -m pip install pyxdelta
```

FFmpeg must be on `PATH` (the build downloads its own pinned psxavenc), and
the verified Japan Rev 1 BIN must sit in the repository root, exactly as for
a normal `python build.py` run.

## Cutting a release

1. Make sure everything to be released is committed on `master` and the tree
   is clean.
2. Update `CHANGELOG.md`: move the `[Unreleased]` notes under a new
   `## [X.Y.Z] - YYYY-MM-DD` heading (add comparison links at the bottom),
   and commit:

   ```powershell
   git commit -am "Prepare vX.Y.Z"
   ```

   Versioning while below 1.0.0: bump **minor** for notable new content or
   features, **patch** for fixes and small text improvements.

3. Run the release script:

   ```powershell
   python release.py X.Y.Z
   ```

   It builds both variants from scratch (translated opening movie, and
   `--skip-opening` for the original Japanese movie), stages everything under
   `build/release/vX.Y.Z/`, hashes the source and outputs, pushes the
   `vX.Y.Z` tag, and creates a **draft** GitHub release with:

   - `SMT2_EN_vX.Y.Z.xdelta` — English opening movie
   - `SMT2_EN_vX.Y.Z_JP_opening.xdelta` — original Japanese opening movie
   - `sha256sums.txt` — patch and expected-output checksums

   The release notes are generated from the version's `CHANGELOG.md` section
   plus standard patching instructions.

4. Optionally boot-test the staged images
   (`build/release/vX.Y.Z/en-opening/SMT2_EN.bin` and
   `.../jp-opening/SMT2_EN.bin`) — they are local-only and never uploaded.

5. Publish the draft from the GitHub Releases page, or:

   ```powershell
   gh release edit vX.Y.Z --draft=false
   ```

   (Use `python release.py X.Y.Z --publish` to skip the draft stage
   entirely.)

6. `build/release/vX.Y.Z/` can be deleted afterwards to reclaim ~450 MB.

## Recovering from a failed run

- Failure **before** the tag was pushed: fix the problem and re-run; pass
  `--skip-build` to reuse the already-built artifacts.
- Failure **after** the tag was pushed (e.g. `gh` upload error): re-run with
  `--skip-build`; if the tag itself must be recreated, first delete it with
  `git tag -d vX.Y.Z` and `git push origin :refs/tags/vX.Y.Z`.
