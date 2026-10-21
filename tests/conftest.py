"""Shared test fixtures: synthetic DICOM file generation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pydicom
import pytest
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
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
        if value is None:  # drop a default field entirely
            if key in dataset:
                delattr(dataset, key)
            continue
        setattr(dataset, key, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    pydicom.dcmwrite(path, dataset, enforce_file_format=True)
    return path


def _make_multiframe_dicom_file(
    path: Path,
    *,
    echo: int = 1,
    echo_time: float = 10.0,
    asl_context: str | None = None,
    frames: int = 2,
    **overrides: object,
) -> Path:
    """Write a synthetic Enhanced-MR-style file whose echo lives only in the per-frame groups."""
    per_frame = []
    for _ in range(frames):
        frame = Dataset()
        echo_item = Dataset()
        echo_item.EchoNumbers = echo
        echo_item.EffectiveEchoTime = echo_time
        frame.MREchoSequence = [echo_item]
        if asl_context is not None:
            asl_item = Dataset()
            asl_item.ASLContext = asl_context
            frame.MRArterialSpinLabelingSequence = [asl_item]
        per_frame.append(frame)
    return _make_dicom_file(
        path,
        EchoNumbers=None,
        NumberOfFrames=frames,
        PerFrameFunctionalGroupsSequence=per_frame,
        **overrides,
    )


@pytest.fixture
def make_multiframe_dicom_file() -> Callable[..., Path]:
    """Factory fixture: make_multiframe_dicom_file(path, echo=2, asl_context="LABEL", ...)."""
    return _make_multiframe_dicom_file


@pytest.fixture
def make_dicom_file() -> Callable[..., Path]:
    """Factory fixture: make_dicom_file(path, **overrides) -> Path."""
    return _make_dicom_file
