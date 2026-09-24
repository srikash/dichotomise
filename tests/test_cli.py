from __future__ import annotations

import shutil
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
    assert "DICOM inventory" in result.output
    assert "Series folder" in result.output
    assert "Pass" in result.output
    assert "Started: Study 1: archiving source DICOMs" in result.output
    assert "Completed: Study 1: creating verified archive" in result.output
    assert "Audit and archive summary" in result.output


def test_cli_help_groups_required_and_optional_flags() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0, result.output
    assert "Required flags" in result.output
    assert "Optional flags" in result.output
    assert "Usage" in result.output
    assert "Single-Subject mode" in result.output
    assert "Multi-Subject mode" in result.output
    assert "[required]" not in result.output
    assert "--sanitise-policy" in result.output
    assert "--sanitise-level" not in result.output
    assert "--subj-id" in result.output
    assert "--subject-id" not in result.output


def test_cli_audit_table_reports_metadata_and_structural_findings(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    series_folder = source / "nested-export" / "study-20260914" / "BTO_hires_fieldmap"
    first_file = make_dicom_file(
        series_folder / "1.dcm", PatientID="sub-01", StudyInstanceUID="study-a"
    )
    shutil.copy2(first_file, series_folder / "2.dcm")
    make_dicom_file(
        series_folder / "3.dcm",
        PatientID="sub-01",
        StudyInstanceUID="study-a",
        SeriesNumber=2,
        SeriesDescription="other_series",
        ProtocolName="other_series",
    )

    result = CliRunner().invoke(
        cli, ["--source-dir", str(source), "--out-dir", str(tmp_path / "out")]
    )

    assert result.exit_code == 0, result.output
    assert "Failed" in result.output
    assert "BTO_hires_fieldmap" in result.output
    assert "nested-export/study-20260914" not in result.output


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
            "--subj-id",
            "5",
        ],
    )

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert "sub-0005" in archives[0].name


def test_cli_new_id_adds_the_sub_prefix(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="scanner-42", StudyInstanceUID="study-a")
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli,
        [
            "--source-dir",
            str(source),
            "--out-dir",
            str(out_dir),
            "--sanitise",
            "--new-id",
            "ADNC0751",
        ],
    )

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert archives[0].name.startswith("sub-ADNC0751_")


def test_cli_automatically_enumerates_a_numerical_multi_study_run(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "one" / "1.dcm", PatientID="source-01", StudyInstanceUID="study-a")
    make_dicom_file(source / "two" / "1.dcm", PatientID="source-02", StudyInstanceUID="study-b")

    result = CliRunner().invoke(
        cli,
        [
            "--source-dir",
            str(source),
            "--out-dir",
            str(tmp_path / "out"),
            "--sanitise",
            "--subj-id",
            "6",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Warning: Multiple studies found with --subj-id" in result.output
    archives = list((tmp_path / "out").glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert any(archive.name.startswith("sub-0006_") for archive in archives)
    assert any(archive.name.startswith("sub-0007_") for archive in archives)


def test_cli_loads_a_json_mapping_file_when_its_extension_is_omitted(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(source / "series" / "1.dcm", PatientID="scanner-42", StudyInstanceUID="study-a")
    mapping_path = tmp_path / "labels.json"
    mapping_path.write_text(
        '{"instructions": ["This entry is ignored."], "scanner-42": "sub-0042"}'
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
            "--mapping-file",
            str(mapping_path.with_suffix("")),
        ],
    )

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert archives[0].name.startswith("sub-0042_")


def test_cli_accepts_a_custom_sanitise_policy(
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
            "--subj-id",
            "1",
            "--sanitise-policy",
            "custom.json",
        ],
    )

    assert result.exit_code == 0, result.output


def test_cli_reports_a_plain_error_for_an_unknown_sanitise_policy(
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
            "--subj-id",
            "1",
            "--sanitise-policy",
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
        ["--source-dir", str(source), "--out-dir", str(out_dir), "--subj-id", "5"],
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


def test_cli_random_name_implies_sanitise_with_the_minimal_policy(
    tmp_path: Path, make_dicom_file: Callable[..., Path]
) -> None:
    source = tmp_path / "export"
    make_dicom_file(
        source / "series" / "1.dcm",
        PatientID="sub-01",
        PatientName="Doe^Jane^19900101",
        StudyInstanceUID="study-a",
    )
    out_dir = tmp_path / "out"

    result = CliRunner().invoke(
        cli, ["--source-dir", str(source), "--out-dir", str(out_dir), "--random-name"]
    )

    assert result.exit_code == 0, result.output
    archives = list(out_dir.glob("*_dichotomise_outputs/archives/*.tar.gz"))
    assert len(archives) == 1
    # --sanitise wasn't passed explicitly, but --random-name implies it.
    assert "sub-01" not in archives[0].name


def test_cli_random_name_conflicting_with_sanitise_policy_is_an_error(
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
            "--random-name",
            "--sanitise-policy",
            "full",
        ],
    )

    assert result.exit_code != 0
    assert "--random-name" in result.output
