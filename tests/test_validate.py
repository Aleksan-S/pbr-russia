from __future__ import annotations

from pathlib import Path

import pytest

import validate


def test_validation_accepts_large_clean_category() -> None:
    lines = [f"host-{index}.example.ru" for index in range(1500)]

    report = validate.validate_lines(lines)

    assert report.valid
    assert report.domains == 1500
    assert not report.errors()


def test_validation_reports_duplicates_invalid_reserved_and_small_output() -> None:
    lines = [
        "example.ru",
        "example.ru",
        "example",
        "bad domain.ru",
        "service.test",
        "service.invalid",
    ]

    report = validate.validate_lines(lines)

    assert not report.valid
    assert report.duplicates == ("example.ru",)
    assert report.invalid == ("bad domain.ru", "example")
    assert report.forbidden_suffixes == ("service.invalid", "service.test")
    assert any("below minimum" in error for error in report.errors())


@pytest.mark.parametrize(
    "suffix",
    (".rl", ".test", ".invalid", ".example", ".localhost"),
)
def test_each_reserved_suffix_is_rejected(suffix: str) -> None:
    report = validate.validate_lines([f"service{suffix}"], minimum_domains=0)
    assert report.forbidden_suffixes == (f"service{suffix}",)


def test_validation_cli_uses_distinct_exit_codes(tmp_path: Path) -> None:
    valid = tmp_path / "valid.txt"
    valid.write_text("example.ru\n", encoding="utf-8")
    invalid = tmp_path / "invalid.txt"
    invalid.write_text("example\n", encoding="utf-8")

    assert validate.main([str(valid), "--minimum", "1"]) == 0
    assert validate.main([str(invalid), "--minimum", "1"]) == 1
    assert validate.main([str(tmp_path / "missing.txt")]) == 2
    assert validate.main([str(valid), "--minimum", "-1"]) == 2
