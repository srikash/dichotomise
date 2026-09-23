"""rectified_path(): pure function from DICOM metadata to the rectified filename/path."""

from __future__ import annotations

from pathlib import Path

from dichotomise.pydcm.read import DicomMetadata
from dichotomise.utils.text import safe_filename_text


def rectified_path(base_dir: Path, metadata: DicomMetadata) -> Path:
    """Return the sorted, clearly named path a rectified copy of this file should have.

    Folder: <series number, 3 digits>-<scan protocol name>
    File:   <series number>_<series identifier>_<instance number, 4 digits>
            _e<echo number, 2 digits>.dcm
    """
    series = f"{metadata.series_number:03d}"
    instance = f"{metadata.instance_number:04d}"
    echo = f"{metadata.echo_number if metadata.echo_number is not None else 1:02d}"

    folder = f"{series}-{safe_filename_text(metadata.protocol_name)}"
    filename = f"{series}_{safe_filename_text(metadata.series_instance_uid)}_{instance}_e{echo}.dcm"
    return base_dir / folder / filename
