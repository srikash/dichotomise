"""rectified_path(): pure function from DICOM metadata to the rectified filename/path."""

from __future__ import annotations

from pathlib import Path

from dichotomise.pydcm.read import DicomMetadata
from dichotomise.utils.text import safe_filename_text


def rectified_path(base_dir: Path, metadata: DicomMetadata) -> Path:
    """Return the sorted, clearly named path a rectified copy of this file should have.

    Folder: <series number, 3 digits>-<series description>
    File:   <series number>_<instance number, 4 digits>_<SOP instance UID>
            _e<echo number, 2 digits>.dcm

    The SOP Instance UID is the one identifier DICOM guarantees to be unique
    per file, so the name is unique without relying on instance numbers.
    """
    series = f"{metadata.series_number:03d}"
    instance = f"{metadata.instance_number:04d}"
    echo = f"{metadata.echo_number if metadata.echo_number is not None else 1:02d}"

    folder = f"{series}-{safe_filename_text(metadata.series_description)}"
    sop = safe_filename_text(metadata.sop_instance_uid)
    filename = f"{series}_{instance}_{sop}_e{echo}.dcm"
    return base_dir / folder / filename


def with_new_sop_instance_uid(path: Path, old_uid: str, new_uid: str) -> Path:
    """Return `path` renamed so its filename carries `new_uid` instead of `old_uid`.

    Used after sanitisation regenerates the SOP Instance UID, so the filename
    always matches the header and never exposes the original identifier.
    """
    old, new = safe_filename_text(old_uid), safe_filename_text(new_uid)
    return path.with_name(path.name.replace(old, new, 1))
