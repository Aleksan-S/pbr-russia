from __future__ import annotations

import argparse
from pathlib import Path

import update


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


def test_run_merges_custom_domains(tmp_path: Path, monkeypatch: object) -> None:
    custom = tmp_path / "custom.txt"
    custom.write_text("custom.ru\n", encoding="utf-8")
    output = tmp_path / "output.txt"
    args = argparse.Namespace(
        entries=None,
        custom=custom,
        output=output,
        archive_url="https://example.invalid/archive.zip",
    )
    monkeypatch.setattr(update, "DomainListDownloader", FakeDownloader)  # type: ignore[attr-defined]

    assert update.run(args) == 0
    assert output.read_text(encoding="utf-8") == (
        "api.company.ru\ncustom.ru\nupstream.ru\n"
    )
