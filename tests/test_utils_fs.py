from __future__ import annotations

from pathlib import Path

import pytest

from dichotomise.errors import DestinationExistsError
from dichotomise.utils.fs import copy_tree


def test_copy_tree_copies_nested_files_and_folders(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "series-a").mkdir(parents=True)
    (source / "series-a" / "1.dcm").write_bytes(b"first file")
    (source / "series-b" / "nested").mkdir(parents=True)
    (source / "series-b" / "nested" / "2.dcm").write_bytes(b"second file")

    destination = tmp_path / "destination"
    copy_tree(source, destination)

    assert (destination / "series-a" / "1.dcm").read_bytes() == b"first file"
    assert (destination / "series-b" / "nested" / "2.dcm").read_bytes() == b"second file"


def test_copy_tree_refuses_to_overwrite_an_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("data")

    destination = tmp_path / "destination"
    destination.mkdir()

    with pytest.raises(DestinationExistsError):
        copy_tree(source, destination)
