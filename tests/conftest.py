"""Shared test fixtures: synthetic DICOM file generation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


def _make_dicom_file(path: Path, **overrides: object) -> Path:
    """Write a minimal, valid synthetic DICOM file to `path` and return it.

    Fields can be overridden by keyword, e.g.
    make_dicom_file(path, PatientID="sub-01", SeriesNumber=3).
    """
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    dataset = FileDataset(str(path), {}, file_meta=file_meta, preamble=b"\x00" * 128)
    dataset.PatientID = "sub-01"
    dataset.PatientName = "Test^Subject"
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.SeriesNumber = 1
    dataset.SeriesDescription = "test_series"
    dataset.ProtocolName = "test_series"
    dataset.InstanceNumber = 1
    dataset.EchoNumbers = 1
    dataset.StudyDate = "20260101"
    dataset.StudyTime = "120000"

    for key, value in overrides.items():
        setattr(dataset, key, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    pydicom.dcmwrite(path, dataset, enforce_file_format=True)
    return path


@pytest.fixture
def make_dicom_file() -> Callable[..., Path]:
    """Factory fixture: make_dicom_file(path, **overrides) -> Path."""
    return _make_dicom_file
