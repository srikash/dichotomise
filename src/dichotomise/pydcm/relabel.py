"""Replacement-label generation and the sanitisation-policy engine."""

from __future__ import annotations

import calendar
import json
import random
import re
from collections.abc import Callable, Iterator, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pydicom
from pydicom.dataset import Dataset
from pydicom.sequence import Sequence
from pydicom.uid import generate_uid

from dichotomise.errors import PolicyNotFoundError, PolicyValidationError, RelabelError
from dichotomise.pydcm.names import generate_name

_POLICIES_DIR = Path(__file__).parent / "policies"

_LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_MAX_LABEL_LENGTH = 64


def generate_default_label(patient_name: str) -> str:
    """Build the legacy ``YYYYMMDD_LF`` label from a DICOM patient name."""
    match = re.fullmatch(r"([^\^]+)\^([^\^]+)\^(\d{8})", patient_name)
    if match is None:
        raise RelabelError("A default replacement label needs LAST^FIRST^YYYYMMDD PatientName")
    surname, given_name, birth_date = match.groups()
    try:
        datetime.strptime(birth_date, "%Y%m%d")
    except ValueError as error:
        raise RelabelError(f"PatientName contains an invalid birth date: {birth_date!r}") from error
    return f"{birth_date}_{surname[0].upper()}{given_name[0].upper()}"


def normalise_numeric_label(value: str) -> str:
    """Turn a plain number (with or without a "sub-" prefix) into "sub-NNNN"."""
    suffix = value.removeprefix("sub-")
    if not re.fullmatch(r"\d+", suffix):
        raise RelabelError("A numerical replacement ID must be a number from 1 to 9999")
    number = int(suffix)
    if not 1 <= number <= 9999:
        raise RelabelError("A numerical replacement ID must be a number from 1 to 9999")
    return f"sub-{number:04d}"


def validate_label(label: str) -> str:
    """Return `label` unchanged if it is safe to use in a filename and DICOM field."""
    if _LABEL_PATTERN.fullmatch(label) is None:
        raise RelabelError(
            "A replacement ID may only contain letters, digits, underscores, and hyphens"
        )
    if len(label) > _MAX_LABEL_LENGTH:
        raise RelabelError(f"A replacement ID must be {_MAX_LABEL_LENGTH} characters or fewer")
    return label


@dataclass(frozen=True)
class Policy:
    """A named sanitisation policy: what happens to each DICOM field."""

    name: str
    actions: dict[str, dict[str, Any]]
    description: str = ""


_ACTIONS_REQUIRING_VALUE = {"replace", "add", "add_code_sequence"}
_VALID_ACTIONS = {
    "keep",
    "remove",
    "replace",
    "add",
    "add_code_sequence",
    "regenerate",
    "scramble_date",
    "random_name",
}


def _validate_actions(policy_name: str, actions: object) -> dict[str, dict[str, Any]]:
    """Validate policy actions before they are applied to a DICOM dataset."""
    if not isinstance(actions, dict):
        raise PolicyValidationError(f"Policy {policy_name!r} needs an actions object.")
    validated: dict[str, dict[str, Any]] = {}
    for field, instruction in actions.items():
        if not isinstance(field, str) or not isinstance(instruction, dict):
            raise PolicyValidationError(
                f"Policy {policy_name!r} has an invalid action instruction."
            )
        action = instruction.get("action")
        if not isinstance(action, str) or action not in _VALID_ACTIONS:
            raise PolicyValidationError(
                f"Policy {policy_name!r} has an unsupported action for {field}: {action!r}."
            )
        if action in _ACTIONS_REQUIRING_VALUE and "value" not in instruction:
            raise PolicyValidationError(
                f"Policy {policy_name!r} needs a value for {field}'s {action} action."
            )
        if action == "add_code_sequence" and not isinstance(instruction["value"], list):
            raise PolicyValidationError(
                f"Policy {policy_name!r} needs a list of codes for {field}."
            )
        validated[field] = instruction
    return validated


def load_policy(name: str) -> Policy:
    """Load one of the bundled policies ("retain", "standard", or "full").

    "full" is written as "standard" plus a few extra fields (its JSON file's
    "extends" key), so its actions here already include everything
    "standard" does, with "full"'s own entries taking priority where the two
    disagree.
    """
    name = name.removesuffix(".json")
    if name == "default":
        return Policy(name="default", actions={})
    return _load_policy(name, ancestors=frozenset())


def _load_policy(name: str, *, ancestors: frozenset[str]) -> Policy:
    if name in ancestors:
        chain = " -> ".join((*sorted(ancestors), name))
        raise PolicyValidationError(f"Policy inheritance is circular: {chain}.")
    policy_file = _POLICIES_DIR / f"{name}.json"
    if not policy_file.is_file():
        available = ", ".join(sorted(p.stem for p in _POLICIES_DIR.glob("*.json")))
        raise PolicyNotFoundError(
            f"No sanitisation policy named '{name}'. Available policies: {available}"
        )
    try:
        raw = json.loads(policy_file.read_text())
    except json.JSONDecodeError as error:
        raise PolicyValidationError(f"Policy {name!r} is not valid JSON.") from error
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise PolicyValidationError(f"Policy {name!r} needs a string name.")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise PolicyValidationError(f"Policy {name!r} needs a string description.")
    actions: dict[str, dict[str, Any]] = {}
    base_name = raw.get("extends")
    if base_name is not None:
        if not isinstance(base_name, str):
            raise PolicyValidationError(f"Policy {name!r} has an invalid extends value.")
        actions.update(_load_policy(base_name, ancestors=ancestors | {name}).actions)
    actions.update(_validate_actions(name, raw.get("actions", {})))
    return Policy(name=raw["name"], actions=actions, description=description)


def _remove_field(dataset: Dataset, field: str) -> None:
    if hasattr(dataset, field):
        delattr(dataset, field)


def _iter_nested_datasets(dataset: Dataset) -> Iterator[Dataset]:
    """Yield a dataset and every dataset contained in its sequences."""
    yield dataset
    for element in dataset:
        if element.VR != "SQ" or not isinstance(element.value, Sequence):
            continue
        for item in element.value:
            yield from _iter_nested_datasets(item)


def _iter_policy_datasets(dataset: Dataset) -> Iterator[Dataset]:
    """Yield the main dataset, nested datasets, and DICOM file metadata."""
    yield from _iter_nested_datasets(dataset)
    file_meta = getattr(dataset, "file_meta", None)
    if file_meta is not None:
        yield from _iter_nested_datasets(file_meta)


def _replace_field(
    dataset: Dataset, field: str, instruction: dict[str, Any], placeholders: dict[str, str]
) -> None:
    if "value" not in instruction:
        return  # nothing to set yet; see docs/sanitise-policies.md
    value = instruction["value"]
    if isinstance(value, str) and value in placeholders:
        value = placeholders[value]
    setattr(dataset, field, value)


def _add_code_sequence(dataset: Dataset, field: str, instruction: dict[str, Any]) -> None:
    """Add a DICOM coded sequence from the policy's serialisable code records."""
    records = instruction.get("value")
    if not isinstance(records, list):
        raise RelabelError(f"{field} needs a list of coded values")
    items = []
    for record in records:
        if not isinstance(record, dict):
            raise RelabelError(f"{field} contains a code that is not an object")
        item = Dataset()
        for attribute, value in record.items():
            setattr(item, attribute, value)
        items.append(item)
    setattr(dataset, field, Sequence(items))


def _cached_value(
    dataset: Dataset,
    field: str,
    replacement_cache: MutableMapping[str, str],
    generate: Callable[[str], str],
) -> str | None:
    """Return a new value for `field`, generated once and reused for every later call.

    `replacement_cache` is shared across every file in a subject's run, keyed
    by field name plus the field's original value, so the same original
    value (the same person's real UID, birth date, or name) always maps to
    the same replacement, however many files it appears in.
    """
    original = str(getattr(dataset, field, "")).strip()
    if not original:
        return None
    key = f"{field}:{original}"
    if key not in replacement_cache:
        replacement_cache[key] = generate(original)
    return replacement_cache[key]


def _regenerate_field(
    dataset: Dataset, field: str, replacement_cache: MutableMapping[str, str]
) -> None:
    new_value = _cached_value(dataset, field, replacement_cache, lambda _original: generate_uid())
    if new_value is not None:
        setattr(dataset, field, new_value)


def _scramble_date(original: str, field: str) -> str:
    """A random valid date shifted by exactly one year from `original` (never 0)."""
    try:
        year = int(original[:4])
    except (ValueError, IndexError) as error:
        raise RelabelError(f"{field} is not a valid date to scramble: {original!r}") from error
    new_year = year + random.choice((-1, 1))
    new_month = random.randint(1, 12)
    new_day = random.randint(1, calendar.monthrange(new_year, new_month)[1])
    return f"{new_year:04d}{new_month:02d}{new_day:02d}"


def _scramble_date_field(
    dataset: Dataset, field: str, replacement_cache: MutableMapping[str, str]
) -> None:
    new_value = _cached_value(
        dataset, field, replacement_cache, lambda original: _scramble_date(original, field)
    )
    if new_value is not None:
        setattr(dataset, field, new_value)


def _format_name_part(word: str) -> str:
    """Title-case one name-generator word, e.g. "gracious" -> "Gracious".

    A "Mc"-prefixed surname (none currently in pydcm/names.py's list, but
    kept in case one is added later) needs that prefix capitalised specially
    rather than a plain str.capitalize(), e.g. "mclean" -> "McLean" rather
    than "Mclean".
    """
    if word.startswith("mc") and len(word) > 2:
        return "Mc" + word[2:].capitalize()
    return word.capitalize()


def format_subject_name(label: str) -> str:
    """Format a generated ``surname_given`` label as a DICOM person name."""
    surname, separator, given_name = label.partition("_")
    if not separator:
        return _format_name_part(surname)
    return f"{_format_name_part(surname)}^{_format_name_part(given_name)}"


def _generate_person_name() -> str:
    """A random "Surname^Firstname"-style placeholder, in DICOM PN form."""
    given, _, family = generate_name().rpartition("_")
    return f"{_format_name_part(family)}^{_format_name_part(given)}"


def _random_name_field(
    dataset: Dataset, field: str, replacement_cache: MutableMapping[str, str]
) -> None:
    new_value = _cached_value(
        dataset, field, replacement_cache, lambda _original: _generate_person_name()
    )
    if new_value is not None:
        setattr(dataset, field, new_value)


def _apply_action(
    dataset: Dataset,
    field: str,
    instruction: dict[str, Any],
    placeholders: dict[str, str],
    replacement_cache: MutableMapping[str, str],
) -> None:
    action = instruction["action"]
    if action == "keep":
        return
    if action == "remove":
        _remove_field(dataset, field)
        return
    if action in ("replace", "add"):
        _replace_field(dataset, field, instruction, placeholders)
        return
    if action == "add_code_sequence":
        _add_code_sequence(dataset, field, instruction)
        return
    if action == "regenerate":
        _regenerate_field(dataset, field, replacement_cache)
        return
    if action == "scramble_date":
        _scramble_date_field(dataset, field, replacement_cache)
        return
    if action == "random_name":
        _random_name_field(dataset, field, replacement_cache)
        return
    raise RelabelError(f"Unknown sanitisation action for {field}: {action}")


def _sync_file_meta_sop_instance_uid(dataset: Dataset) -> None:
    """Keep the file-meta SOP instance UID aligned with the main dataset."""
    file_meta = getattr(dataset, "file_meta", None)
    if file_meta is None or not hasattr(dataset, "SOPInstanceUID"):
        return
    if hasattr(file_meta, "MediaStorageSOPInstanceUID"):
        file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID


def apply_policy(
    dataset: Dataset,
    policy: Policy,
    *,
    subject_label: str,
    scan_date: str,
    replacement_cache: MutableMapping[str, str],
) -> None:
    """Apply `policy` to `dataset` in place.

    `replacement_cache` is kept and reused by the caller across every file in
    a run, so a regenerated UID, scrambled date, or random name that appears
    in more than one file comes out the same everywhere, rather than a
    different one per file.
    """
    placeholders = {
        "<subject-label>": subject_label,
        "<subject-name>": format_subject_name(subject_label),
        "<scan-date>": scan_date,
    }
    for field, instruction in policy.actions.items():
        action = instruction["action"]
        for current_dataset in _iter_policy_datasets(dataset):
            if action in ("add", "add_code_sequence") and current_dataset is not dataset:
                continue
            if current_dataset is not dataset and not hasattr(current_dataset, field):
                continue
            _apply_action(
                current_dataset,
                field,
                instruction,
                placeholders,
                replacement_cache,
            )
    _sync_file_meta_sop_instance_uid(dataset)


def sanitise_file(
    source_path: Path,
    target_path: Path,
    policy: Policy,
    *,
    subject_label: str,
    scan_date: str,
    replacement_cache: MutableMapping[str, str],
) -> None:
    """Read, sanitise, save, and re-open one DICOM file.

    The caller owns path selection and the shared replacement cache; this
    function owns all DICOM-specific file handling.
    """
    dataset = pydicom.dcmread(source_path)
    apply_policy(
        dataset,
        policy,
        subject_label=subject_label,
        scan_date=scan_date,
        replacement_cache=replacement_cache,
    )
    dataset.save_as(target_path)
    pydicom.dcmread(target_path, stop_before_pixels=True)
