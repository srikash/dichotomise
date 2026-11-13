"""The placeholder-name generator and its word lists."""

from __future__ import annotations

from dichotomise.pydcm.names import ADJECTIVES, SURNAMES, generate_name


def test_word_lists_have_no_duplicates() -> None:
    assert len(ADJECTIVES) == len(set(ADJECTIVES))
    assert len(SURNAMES) == len(set(SURNAMES))


def test_generate_name_returns_one_adjective_and_one_surname() -> None:
    adjective, surname = generate_name()

    assert adjective in ADJECTIVES
    assert surname in SURNAMES
