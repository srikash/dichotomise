from __future__ import annotations

import shutil
from pathlib import Path

from dichotomise.pipeline import run_pipeline
from dichotomise.utils.archive import verify_archive

DATA_DIR = Path(__file__).parent / "data" / "default_export"


def _small_real_export(tmp_path: Path) -> Path:
    """A handful of real, but small, series folders: fast to copy/hash/compress in a test."""
    source = tmp_path / "export"
    candidates = (p for p in DATA_DIR.rglob("*_MR") if p.is_dir())
    small_folders = sorted(
        (p for p in candidates if sum(f.stat().st_size for f in p.glob("*.dcm")) < 3_000_000),
        key=lambda p: p.name,
    )[:3]
    assert small_folders, "expected at least one small real series under tests/data"
    for folder in small_folders:
        shutil.copytree(folder, source / folder.name)
    return source


def test_pipeline_runs_end_to_end_on_a_slice_of_real_scanner_data(tmp_path: Path) -> None:
    source = _small_real_export(tmp_path)

    run = run_pipeline(source, tmp_path / "out")

    archives = list(run.archives_dir.glob("*.tar.gz"))
    checksums = list(run.archives_dir.glob("*.sha256"))
    assert len(archives) == 1
    assert len(checksums) == 1
    assert verify_archive(archives[0], checksums[0]) is True


def test_pipeline_sanitises_real_scanner_data_without_error(tmp_path: Path) -> None:
    source = _small_real_export(tmp_path)

    run = run_pipeline(
        source, tmp_path / "out", sanitise_requested=True, label_mode="numerical", subject_id="1"
    )

    archives = list(run.archives_dir.glob("*.tar.gz"))
    assert len(archives) == 1
    assert "sub-0001" in archives[0].name
