from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import update
from parser import ParseResult


class FakeDownloader:
    def __init__(self, archive_url: str) -> None:
        self.archive_url = archive_url

    def download(self, destination: Path) -> Path:
        repository = destination / "repository"
        data = repository / "data"
        data.mkdir(parents=True)
        (data / "category-ru").write_text(
            "domain:upstream.ru\ninclude:company\n", encoding="utf-8"
        )
        (data / "company").write_text("full:api.company.ru\n", encoding="utf-8")
        return repository


def test_run_merges_custom_domains_and_writes_statistics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custom = tmp_path / "custom.txt"
    custom.write_text("custom.ru\n", encoding="utf-8")
    output = tmp_path / "output.txt"
    statistics = tmp_path / "statistics.json"
    args = argparse.Namespace(
        entries=None,
        custom=custom,
        output=output,
        statistics=statistics,
        archive_url="https://example.invalid/archive.zip",
    )
    monkeypatch.setattr(update, "DomainListDownloader", FakeDownloader)

    assert update.run(args) == 0
    assert output.read_text(encoding="utf-8") == (
        "api.company.ru\ncustom.ru\nupstream.ru\n"
    )
    payload = json.loads(statistics.read_text(encoding="utf-8"))
    assert payload["domains"] == 3
    assert payload["includes"] == 1
    assert payload["duplicates_removed"] == 0
    assert payload["invalid_removed"] == 0
    assert payload["generated_at"].endswith("Z")


def test_build_statistics_counts_cross_source_duplicates() -> None:
    upstream = ParseResult(
        domains=frozenset({"example.ru", "upstream.ru"}),
        includes=4,
        duplicates_removed=2,
        invalid_removed=3,
    )
    custom = ParseResult(
        domains=frozenset({"example.ru", "custom.ru"}),
        duplicates_removed=1,
        invalid_removed=2,
    )
    generated_at = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)

    statistics = update.build_statistics(upstream, custom, generated_at=generated_at)

    assert statistics == update.GenerationStatistics(
        generated_at="2026-08-01T12:30:00Z",
        domains=3,
        includes=4,
        duplicates_removed=4,
        invalid_removed=5,
    )


def test_statistics_keep_timestamp_when_generation_is_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "statistics.json"
    first = update.GenerationStatistics(
        generated_at="2026-08-01T10:00:00Z",
        domains=1900,
        includes=40,
        duplicates_removed=10,
        invalid_removed=2,
    )
    second = update.GenerationStatistics(
        generated_at="2026-08-02T10:00:00Z",
        domains=1900,
        includes=40,
        duplicates_removed=10,
        invalid_removed=2,
    )

    assert update.write_statistics(first, path, force_new_timestamp=True)
    assert not update.write_statistics(second, path, force_new_timestamp=False)
    assert json.loads(path.read_text(encoding="utf-8"))["generated_at"] == (
        "2026-08-01T10:00:00Z"
    )
