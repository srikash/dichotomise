"""Replacement-label generation and the sanitisation-policy engine."""

from __future__ import annotations

import calendar
import json
import random
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydicom.dataset import Dataset
from pydicom.uid import generate_uid

from dichotomise._vendor.funkybob import RandomNameGenerator
from dichotomise.errors import PolicyNotFoundError, RelabelError

_POLICIES_DIR = Path(__file__).parent / "policies"

_LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_MAX_LABEL_LENGTH = 64
_DEFAULT_NAME_PATTERN = re.compile(r"(?P<last>[^\^]+)\^(?P<first>[^\^]+)\^(?P<date>\d{8})")


def generate_default_label(patient_name: str) -> str:
    """Derive a replacement label from a name shaped LAST^FIRST^YYYYMMDD.

    Returns the embedded date plus the subject's initials, e.g.
    "Doe^Jane^19900101" -> "19900101_JD". This is a replacement label, not
    de-identification: it is predictable from the source name on purpose.
    """
    match = _DEFAULT_NAME_PATTERN.fullmatch(patient_name)
    if match is None:
        raise RelabelError(
            "Cannot work out a default replacement label: the patient name must be "
            "written as LAST^FIRST^YYYYMMDD. Use a numerical or custom replacement ID "
            "instead."
        )
    try:
        datetime.strptime(match["date"], "%Y%m%d")
    except ValueError as error:
        raise RelabelError(
            "Cannot work out a default replacement label: the date in the patient name "
            "is not a real date. Use a numerical or custom replacement ID instead."
        ) from error
    return f"{match['date']}_{match['last'][0].upper()}{match['first'][0].upper()}"


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


def load_policy(name: str) -> Policy:
    """Load one of the bundled policies ("default", "standard", or "full").

    "full" is written as "standard" plus a few extra fields (its JSON file's
    "extends" key), so its actions here already include everything
    "standard" does, with "full"'s own entries taking priority where the two
    disagree.
    """
    policy_file = _POLICIES_DIR / f"{name}.json"
    if not policy_file.is_file():
        available = ", ".join(sorted(p.stem for p in _POLICIES_DIR.glob("*.json")))
        raise PolicyNotFoundError(
            f"No sanitisation policy named '{name}'. Available policies: {available}"
        )
    raw = json.loads(policy_file.read_text())
    actions: dict[str, dict[str, Any]] = {}
    base_name = raw.get("extends")
    if base_name is not None:
        actions.update(load_policy(base_name).actions)
    actions.update(raw.get("actions", {}))
    return Policy(name=raw["name"], actions=actions)


def _remove_field(dataset: Dataset, field: str) -> None:
    if hasattr(dataset, field):
        delattr(dataset, field)


def _replace_field(
    dataset: Dataset, field: str, instruction: dict[str, Any], placeholders: dict[str, str]
) -> None:
    if "value" not in instruction:
        return  # nothing to set yet; see docs/sanitise-policies.md
    value = instruction["value"]
    if isinstance(value, str) and value in placeholders:
        value = placeholders[value]
    setattr(dataset, field, value)


def _cached_value(
    dataset: Dataset, field: str, replacement_cache: MutableMapping[str, str], generate: Any
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


def _random_name_field(
    dataset: Dataset, field: str, replacement_cache: MutableMapping[str, str]
) -> None:
    new_value = _cached_value(
        dataset,
        field,
        replacement_cache,
        lambda _original: next(iter(RandomNameGenerator())),  # type: ignore[no-untyped-call]
    )
    if new_value is not None:
        setattr(dataset, field, new_value)


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
    placeholders = {"<subject-label>": subject_label, "<scan-date>": scan_date}
    handlers = {
        "keep": lambda field, instruction: None,
        "remove": lambda field, instruction: _remove_field(dataset, field),
        "replace": lambda field, instruction: _replace_field(
            dataset, field, instruction, placeholders
        ),
        "add": lambda field, instruction: _replace_field(dataset, field, instruction, placeholders),
        "regenerate": lambda field, instruction: _regenerate_field(
            dataset, field, replacement_cache
        ),
        "scramble_date": lambda field, instruction: _scramble_date_field(
            dataset, field, replacement_cache
        ),
        "random_name": lambda field, instruction: _random_name_field(
            dataset, field, replacement_cache
        ),
    }
    for field, instruction in policy.actions.items():
        action = instruction["action"]
        handler = handlers.get(action)
        if handler is None:
            raise RelabelError(f"Unknown sanitisation action for {field}: {action}")
        handler(field, instruction)
