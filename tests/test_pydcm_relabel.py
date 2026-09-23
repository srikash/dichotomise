from __future__ import annotations

import pytest
from pydicom.dataset import Dataset

from dichotomise.errors import PolicyNotFoundError, RelabelError
from dichotomise.pydcm.relabel import (
    Policy,
    apply_policy,
    generate_default_label,
    load_policy,
    normalise_numeric_label,
    validate_label,
)


def test_generate_default_label_uses_date_and_initials_from_the_patient_name() -> None:
    # Initials are last-name-first, then first-name, matching LAST^FIRST order.
    assert generate_default_label("Doe^Jane^19900101") == "19900101_DJ"


def test_generate_default_label_rejects_a_name_without_the_expected_shape() -> None:
    with pytest.raises(RelabelError):
        generate_default_label("Doe^Jane")


def test_generate_default_label_rejects_an_invalid_embedded_date() -> None:
    with pytest.raises(RelabelError):
        generate_default_label("Doe^Jane^19901301")  # month 13


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5", "sub-0005"),
        ("sub-42", "sub-0042"),
        ("0007", "sub-0007"),
    ],
)
def test_normalise_numeric_label_pads_to_four_digits(value: str, expected: str) -> None:
    assert normalise_numeric_label(value) == expected


@pytest.mark.parametrize("value", ["0", "10000", "abc", "sub-"])
def test_normalise_numeric_label_rejects_values_out_of_range(value: str) -> None:
    with pytest.raises(RelabelError):
        normalise_numeric_label(value)


def test_validate_label_accepts_letters_digits_underscore_and_hyphen() -> None:
    assert validate_label("sub-0005_A") == "sub-0005_A"


@pytest.mark.parametrize("label", ["has space", "semi;colon", "a" * 65])
def test_validate_label_rejects_unsafe_or_overlong_labels(label: str) -> None:
    with pytest.raises(RelabelError):
        validate_label(label)


def _dataset(**fields: object) -> Dataset:
    dataset = Dataset()
    for key, value in fields.items():
        setattr(dataset, key, value)
    return dataset


def test_load_policy_default_has_no_actions() -> None:
    policy = load_policy("default")

    assert policy.name == "default"
    assert policy.actions == {}


def test_load_policy_full_includes_standards_actions_as_well_as_its_own() -> None:
    policy = load_policy("full")

    assert "PatientName" in policy.actions  # inherited from standard
    assert policy.actions["PatientName"]["action"] == "replace"
    assert policy.actions["ProtocolName"]["action"] == "replace"  # full's own


def test_load_policy_custom_overrides_its_base_and_adds_new_fields() -> None:
    policy = load_policy("custom")

    assert policy.actions["PatientName"]["action"] == "replace"  # inherited via full -> standard
    assert policy.actions["ProtocolName"]["action"] == "keep"  # custom's override of full's replace
    assert policy.actions["AccessionNumber"]["action"] == "remove"  # custom's own addition


def test_load_policy_raises_a_plain_error_for_an_unknown_policy_name() -> None:
    with pytest.raises(PolicyNotFoundError):
        load_policy("does-not-exist")


def test_apply_policy_default_leaves_a_dataset_unchanged() -> None:
    dataset = _dataset(PatientName="Doe^Jane^19900101", PatientID="12345")

    apply_policy(
        dataset,
        load_policy("default"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache={},
    )

    assert dataset.PatientName == "Doe^Jane^19900101"
    assert dataset.PatientID == "12345"


def test_apply_policy_standard_replaces_identity_and_removes_institution() -> None:
    dataset = _dataset(
        PatientName="Doe^Jane^19900101",
        PatientID="12345",
        PatientBirthDate="19900101",
        PatientSex="F",
        InstitutionName="Sunnybrook Health Sciences Center",
        StudyInstanceUID="1.1",
    )

    apply_policy(
        dataset,
        load_policy("standard"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache={},
    )

    assert dataset.PatientName == "sub-0005"
    assert dataset.PatientID == "sub-0005"
    assert dataset.PatientBirthDate != "19900101"  # scrambled, not the real DOB
    assert dataset.PatientSex == "F"  # demographic fields are kept
    assert dataset.PatientIdentityRemoved == "YES"
    assert not hasattr(dataset, "InstitutionName")
    assert dataset.StudyInstanceUID != "1.1"


def test_apply_policy_regenerates_the_same_uid_consistently_across_files() -> None:
    replacement_cache: dict[str, str] = {}
    first = _dataset(StudyInstanceUID="1.1")
    second = _dataset(StudyInstanceUID="1.1")

    apply_policy(
        first,
        load_policy("standard"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache=replacement_cache,
    )
    apply_policy(
        second,
        load_policy("standard"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache=replacement_cache,
    )

    assert first.StudyInstanceUID == second.StudyInstanceUID
    assert first.StudyInstanceUID != "1.1"


def test_apply_policy_full_also_removes_descriptive_fields() -> None:
    dataset = _dataset(
        PatientName="Doe^Jane^19900101",
        PatientID="12345",
        ProtocolName="bto_CS4.8_MP2RAGE_0.8mm_iso",
        SeriesDescription="bto_CS4.8_MP2RAGE_0.8mm_iso_INV2",
    )

    apply_policy(
        dataset,
        load_policy("full"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache={},
    )

    assert dataset.ProtocolName == "DeIdentified"
    assert not hasattr(dataset, "SeriesDescription")


def test_apply_policy_scramble_date_shifts_year_by_exactly_one() -> None:
    policy = Policy(name="test", actions={"PatientBirthDate": {"action": "scramble_date"}})
    dataset = _dataset(PatientBirthDate="19900615")

    apply_policy(
        dataset, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache={}
    )

    scrambled = dataset.PatientBirthDate
    assert scrambled != "19900615"
    assert len(scrambled) == 8
    assert int(scrambled[:4]) in (1989, 1991)  # +/- 1 year, never the real year


def test_apply_policy_scramble_date_is_consistent_across_files() -> None:
    cache: dict[str, str] = {}
    first = _dataset(PatientBirthDate="19900615")
    second = _dataset(PatientBirthDate="19900615")
    policy = Policy(name="test", actions={"PatientBirthDate": {"action": "scramble_date"}})

    apply_policy(
        first, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache=cache
    )
    apply_policy(
        second, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache=cache
    )

    assert first.PatientBirthDate == second.PatientBirthDate


def test_apply_policy_random_name_replaces_with_a_generated_name() -> None:
    policy = Policy(name="test", actions={"PatientName": {"action": "random_name"}})
    dataset = _dataset(PatientName="Doe^Jane^19900101")

    apply_policy(
        dataset, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache={}
    )

    assert dataset.PatientName != "Doe^Jane^19900101"
    assert dataset.PatientName  # non-empty


def test_apply_policy_random_name_is_formatted_last_caret_first_and_title_cased() -> None:
    policy = Policy(name="test", actions={"PatientName": {"action": "random_name"}})
    dataset = _dataset(PatientName="Doe^Jane^19900101")

    apply_policy(
        dataset, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache={}
    )

    last, caret, first = str(dataset.PatientName).partition("^")
    assert caret == "^"
    assert last and last[0].isupper()
    assert first and first[0].isupper() and first[1:].islower()


def test_random_name_title_cases_mc_surnames_correctly() -> None:
    from dichotomise.pydcm.relabel import _format_name_part

    assert _format_name_part("mclean") == "McLean"
    assert _format_name_part("mccarthy") == "McCarthy"
    assert _format_name_part("gracious") == "Gracious"


def test_apply_policy_random_name_is_consistent_across_files() -> None:
    cache: dict[str, str] = {}
    first = _dataset(PatientName="Doe^Jane^19900101")
    second = _dataset(PatientName="Doe^Jane^19900101")
    policy = Policy(name="test", actions={"PatientName": {"action": "random_name"}})

    apply_policy(
        first, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache=cache
    )
    apply_policy(
        second, policy, subject_label="sub-0005", scan_date="20260914", replacement_cache=cache
    )

    assert first.PatientName == second.PatientName


def test_load_policy_minimal_keeps_standards_removals_but_overrides_name_and_dob() -> None:
    policy = load_policy("minimal")

    assert policy.actions["InstitutionName"]["action"] == "remove"  # inherited from standard
    assert policy.actions["PatientName"]["action"] == "random_name"  # minimal's own override
    assert policy.actions["PatientBirthDate"]["action"] == "replace"
    assert policy.actions["PatientBirthDate"]["value"] == "<scan-date>"


def test_apply_policy_minimal_gives_a_random_name_and_scandate_birthdate() -> None:
    dataset = _dataset(
        PatientName="Doe^Jane^19900101",
        PatientID="12345",
        PatientBirthDate="19900101",
    )

    apply_policy(
        dataset,
        load_policy("minimal"),
        subject_label="sub-0005",
        scan_date="20260914",
        replacement_cache={},
    )

    assert dataset.PatientName not in ("Doe^Jane^19900101", "sub-0005")
    assert dataset.PatientID == "sub-0005"
    assert dataset.PatientBirthDate == "20260914"
