# Changelog

## v2.6.4

- README: document plain `venv` and conda/mamba as the primary install paths; `uv` is now its own section, kept for continuity with this project's dev/CI setup rather than presented as the default.
- No other code changes; this is the release tagged with an actual GitHub release, to trigger Zenodo DOI archiving via its release webhook (v2.6.3 only got a git tag + PyPI/container publish).

## v2.6.3

- No code changes; cuts a release/tag to trigger Zenodo DOI archiving via the GitHub release webhook.

## v2.6.2

- More informative CLI output: an opening banner (version, source path, and either the output directory or "QC Mode"), a subject/file count right after capture, a live "Time elapsed" ticker while a run is in progress (interactive terminals only), and a total-time summary at the end.
- Archive creation (source, dichotomised, and review archives) now reports byte progress (`KB done/KB total`) on an interactive terminal.
- The banner's "Output:" line now shows the actual created, timestamped run folder rather than the raw `--out-dir` argument.
- `--keep-working-files` now warns that it keeps a full second copy of every subject's files on disk, on top of the archive.
- Long paths in CLI output (banner, success/error messages) no longer wrap mid-path.

## v2.6.0

- QC/audit tables (CLI and `stage-01-report.json`/`stage-01-audit.csv`) now sort series folders in numeric series order (e.g. `..._6_MR` before `..._29_MR`) instead of alphabetically.
- Cut redundant DICOM copying: `capture()` no longer copies files into a working tree, and `sift()` is now a logical split — rectify() is the pipeline's one real copy of each file's bytes, reading straight from the original source.
- `source_archive()` now archives each subject's files straight from the original source directory, before anything else touches them, rather than from a working copy.
- `archives/` now holds the source archive alongside the dichotomised and review archives (previously a separate `source/` folder).
- New `--keep-unzipped` flag: in addition to the always-created archive, also writes each study's final (optionally sanitised) files unarchived, into `final/` — e.g. for a later BIDS conversion.

## v2.5.0

- Published Docker and Apptainer/Singularity images to GHCR on every release, alongside PyPI.
- Added `scripts/dichotomise-container`, a wrapper with the exact same CLI as native `dichotomise` (its `--help` is byte-identical) that runs everything inside the published container — auto-detects `docker`/`apptainer` and handles the bind mounts for you.
- CI now auto-tags `main` whenever `pyproject.toml`'s version changes, so a version bump alone triggers the PyPI release and container builds with no manual tagging step.

## v2.4.0

- Review files (duplicates, misfiled) no longer disappear with the working directory by default. They're renamed like retained files, then archived separately as a checksummed `review-archive.tar.gz` in `archives/`.
- `--sanitise` now covers review files too — same policy, same replacement IDs as the main archive, so excluded files can't leak real PHI in a sanitised run.
- A rename collision in review (misfiled/duplicate metadata causes these) no longer aborts the run; colliding files get a `-dupNN` suffix.
- New per-subject manifests: `source-manifest.csv`, `retained-manifest.csv`, `review-manifest.csv` — file, size, timestamps.
- `stage-02-report.json` gained `review_rename_collisions`, `review_archive`, `review_archive_checksum`, `review_archive_sanitised`.
- CLI summary table: new "Review archive" column.
