"""Drift guards for the docs: the policy table and the relative links."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
POLICIES = ROOT / "src" / "dichotomise" / "pydcm" / "policies"


def test_policy_table_lists_exactly_the_shipped_policies() -> None:
    text = (ROOT / "docs" / "sanitise-policies.md").read_text()
    table = text.split("## Five policies")[1].split("\n## ")[0]
    listed = set(re.findall(r"^\| `([\w-]+\.json)`", table, flags=re.MULTILINE))
    assert listed == {path.name for path in POLICIES.glob("*.json")}


def test_relative_markdown_links_resolve() -> None:
    broken = []
    for page in [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]:
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", page.read_text()):
            external = "://" in target or target.startswith("mailto:")
            if not external and not (page.parent / target).exists():
                broken.append(f"{page.relative_to(ROOT)} -> {target}")
    assert not broken
