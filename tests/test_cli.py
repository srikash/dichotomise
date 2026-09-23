from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from click.testing import CliRunner

from dichotomise.cli import cli


def test_cli_runs_end_to_end_and_reports_the_archives(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(cli, ["--source-dir", str(source), "--out-dir", str(out_dir)])

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert len(archives) == 1
    assert archives[0].name in result.output


def test_cli_sanitise_infers_numerical_mode_from_subject_id(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli,
        [
            "--source-dir",
            str(source),
            "--out-dir",
            str(out_dir),
            "--sanitise",
            "--subject-id",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert "sub-0005" in archives[0].name


def test_cli_accepts_a_custom_sanitise_level(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        ProtocolName="DWI",
    )
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli,
        [
            "--source-dir",
            str(source),
            "--out-dir",
            str(out_dir),
            "--sanitise",
            "--subject-id",
            "1",
            "--sanitise-level",
            "custom",
        ],
    )

    assert result.exit_code == 0, result.output


def test_cli_reports_a_plain_error_for_an_unknown_sanitise_level(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli,
        [
            "--source-dir",
            str(source),
            "--out-dir",
            str(out_dir),
            "--sanitise",
            "--subject-id",
            "1",
            "--sanitise-level",
            "does-not-exist",
        ],
    )

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "does-not-exist" in result.output


def test_cli_rejects_sanitise_options_without_the_sanitise_flag(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli,
        ["--source-dir", str(source), "--out-dir", str(out_dir), "--subject-id", "5"],
    )

    assert result.exit_code != 0
    assert "--sanitise" in result.output


def test_cli_reports_a_plain_error_when_no_dicom_files_are_found(tmp_path: Path) -> None:
    source = tmp_path / "export"
    source.mkdir()
    (source / "readme.txt").write_text("nothing here")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(cli, ["--source-dir", str(source), "--out-dir", str(out_dir)])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert "No DICOM files" in result.output
