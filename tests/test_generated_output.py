from __future__ import annotations

import json
from pathlib import Path

from validate import MINIMUM_DOMAIN_COUNT, validate_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_committed_outputs_are_consistent() -> None:
    domain_path = PROJECT_ROOT / "output" / "russia-domains.txt"
    statistics_path = PROJECT_ROOT / "output" / "statistics.json"

    report = validate_file(domain_path)
    statistics = json.loads(statistics_path.read_text(encoding="utf-8"))

    assert report.valid, report.errors()
    assert statistics["domains"] == report.domains
    assert statistics["domains"] >= MINIMUM_DOMAIN_COUNT
    assert statistics["includes"] >= 1
    assert statistics["duplicates_removed"] >= 0
    assert statistics["invalid_removed"] >= 0
    assert statistics["generated_at"].endswith("Z")
