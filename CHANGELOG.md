# Changelog

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
