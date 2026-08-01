from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import requests

from parser import (
    DomainListDownloader,
    DomainListParser,
    DownloadError,
    ParseError,
    load_custom_domains,
    normalize_domain,
    parse_domain_rule,
    write_domain_list,
)


def write_list(data_directory: Path, name: str, content: str) -> None:
    data_directory.mkdir(parents=True, exist_ok=True)
    (data_directory / name).write_text(content, encoding="utf-8")


def test_parser_resolves_includes_and_supported_rules(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(
        data,
        "category-ru",
        """
        # root comment
        include:companies @selected
        domain:Example.RU @ads
        full:api.example.ru @tracking # inline comment
        shorthand.ru
        regexp:^ignored\\.ru$
        keyword:ignored
        unsupported:ignored.ru
        invalid_domain.ru
        """,
    )
    write_list(data, "companies", "include:nested\ndomain:vk.ru\n")
    write_list(data, "nested", "full:cdn.vk.ru\ndomain:example.ru\n")

    assert DomainListParser(data).parse(["category-ru"]) == {
        "api.example.ru",
        "cdn.vk.ru",
        "example.ru",
        "shorthand.ru",
        "vk.ru",
    }


def test_parser_deduplicates_multiple_entries(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(data, "first", "domain:example.ru\n")
    write_list(data, "second", "full:example.ru\n")

    assert DomainListParser(data).parse(["first", "second"]) == {"example.ru"}


def test_parser_rejects_circular_include(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(data, "first", "include:second\n")
    write_list(data, "second", "include:first\n")

    with pytest.raises(ParseError, match="Circular include"):
        DomainListParser(data).parse(["first"])


def test_parser_rejects_missing_include(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(data, "first", "include:missing\n")

    with pytest.raises(ParseError, match="does not exist"):
        DomainListParser(data).parse(["first"])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Example.RU.", "example.ru"),
        ("пример.рф", "xn--e1afmkfd.xn--p1ai"),
        ("ru", "ru"),
        ("-bad.ru", None),
        ("bad_.ru", None),
        ("bad..ru", None),
        ("", None),
    ],
)
def test_normalize_domain(value: str, expected: str | None) -> None:
    assert normalize_domain(value) == expected


def test_parse_domain_rule_ignores_unsupported_rules() -> None:
    assert parse_domain_rule("domain:example.ru") == "example.ru"
    assert parse_domain_rule("full:www.example.ru") == "www.example.ru"
    assert parse_domain_rule("example.ru") == "example.ru"
    assert parse_domain_rule("keyword:example") is None
    assert parse_domain_rule("regexp:.*") is None
    assert parse_domain_rule("unknown:example.ru") is None


def test_custom_domains_are_validated_and_deduplicated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    custom = tmp_path / "custom.txt"
    custom.write_text(
        "domain:Example.RU\nfull:api.example.ru @attr\nbad_domain.ru\n",
        encoding="utf-8",
    )

    assert load_custom_domains(custom) == {"example.ru", "api.example.ru"}
    assert "Ignoring invalid custom rule" in caplog.text


def test_writer_sorts_and_refuses_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "output" / "domains.txt"
    write_domain_list(["z.ru", "a.ru", "z.ru"], output)
    assert output.read_text(encoding="utf-8") == "a.ru\nz.ru\n"

    with pytest.raises(ParseError, match="empty"):
        write_domain_list(set(), output)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> list[bytes]:
        del chunk_size
        return [self.content]


class FakeSession(requests.Session):
    def __init__(self, content: bytes) -> None:
        super().__init__()
        self.content = content

    def get(self, *args: object, **kwargs: object) -> FakeResponse:
        del args, kwargs
        return FakeResponse(self.content)


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_downloader_extracts_repository(tmp_path: Path) -> None:
    content = make_zip({"domain-list-community-master/data/category-ru": "ru\n"})
    downloader = DomainListDownloader(session=FakeSession(content))

    repository = downloader.download(tmp_path)

    assert (repository / "data" / "category-ru").read_text(encoding="utf-8") == "ru\n"


def test_downloader_rejects_path_traversal(tmp_path: Path) -> None:
    content = make_zip(
        {
            "domain-list-community-master/data/category-ru": "ru\n",
            "../escaped": "unsafe",
        }
    )
    downloader = DomainListDownloader(session=FakeSession(content))

    with pytest.raises(DownloadError, match="unsafe path"):
        downloader.download(tmp_path)
