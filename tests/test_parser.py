from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import requests

import parser as parser_module
from parser import (
    DomainListDownloader,
    DomainListParser,
    DownloadError,
    ParseError,
    atomic_write_text,
    load_custom_domains,
    load_custom_sources_with_statistics,
    normalize_domain,
    parse_domain_rule,
    redact_url_credentials,
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

    result = DomainListParser(data).parse_with_statistics(["first", "second"])

    assert result.domains == {"example.ru"}
    assert result.duplicates_removed == 1


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


def test_parser_enforces_maximum_include_depth(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(data, "root", "include:level-1\n")
    write_list(data, "level-1", "include:level-2\n")
    write_list(data, "level-2", "include:level-3\n")
    write_list(data, "level-3", "domain:example.ru\n")

    with pytest.raises(ParseError, match="Maximum include depth of 2 exceeded"):
        DomainListParser(data, max_include_depth=2).parse(["root"])


def test_empty_and_large_categories(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(data, "empty", "# comments only\n\n")
    write_list(
        data,
        "large",
        "\n".join(f"host-{index}.example.ru" for index in range(1600)),
    )

    assert DomainListParser(data).parse(["empty"]) == set()
    assert len(DomainListParser(data).parse(["large"])) == 1600


def test_parser_statistics_count_includes_and_invalid_rules(tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_list(
        data,
        "root",
        "include:nested\nexample\ndomain:\nkeyword:ignored\nexample.ru\n",
    )
    write_list(data, "nested", "example.ru\n")

    result = DomainListParser(data).parse_with_statistics(["root"])

    assert result.domains == {"example.ru"}
    assert result.includes == 1
    assert result.duplicates_removed == 1
    assert result.invalid_removed == 2


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Example.RU.", "example.ru"),
        ("пример.рф", "xn--e1afmkfd.xn--p1ai"),
        ("xn--80asehdb", "xn--80asehdb"),
        ("example", None),
        ("http://example.ru", None),
        ("https://example.ru", None),
        ("*.ru", None),
        ("domain:", None),
        ("full:", None),
        ("regexp:", None),
        ("keyword:", None),
        ("example .ru", None),
        (" example.ru", None),
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


def test_parse_domain_rule_strips_attributes() -> None:
    assert parse_domain_rule("domain:Example.RU @ads @tracking") == "example.ru"
    assert parse_domain_rule("full:api.example.ru@private") == "api.example.ru"


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


def test_multiple_custom_files_are_merged_and_deduplicated(
    tmp_path: Path,
) -> None:
    custom_directory = tmp_path / "custom"
    write_list(custom_directory, "manual.txt", "manual.ru\nshared.ru\n")
    write_list(custom_directory, "smart-home.txt", "shared.ru\nsmart.ru\n")
    write_list(custom_directory, "vendor.txt", "extra.ru\n")
    legacy = tmp_path / "custom-domains.txt"
    legacy.write_text("legacy.ru\nshared.ru\n", encoding="utf-8")

    result = load_custom_sources_with_statistics(custom_directory, legacy)

    assert result.domains == {
        "extra.ru",
        "legacy.ru",
        "manual.ru",
        "shared.ru",
        "smart.ru",
    }
    assert result.duplicates_removed == 2
    assert result.manual_domains == 4
    assert result.smart_home_domains == 2


def test_legacy_custom_file_remains_supported(tmp_path: Path) -> None:
    legacy = tmp_path / "custom-domains.txt"
    legacy.write_text("Legacy.RU.\n", encoding="utf-8")

    result = load_custom_sources_with_statistics(None, legacy)

    assert result.domains == {"legacy.ru"}
    assert result.manual_domains == 1
    assert result.smart_home_domains == 0


def test_writer_sorts_and_refuses_empty_output(tmp_path: Path) -> None:
    output = tmp_path / "output" / "domains.txt"
    write_domain_list(["z.ru", "a.ru", "z.ru"], output)
    assert output.read_text(encoding="utf-8") == "a.ru\nz.ru\n"

    with pytest.raises(ParseError, match="empty"):
        write_domain_list(set(), output)

    with pytest.raises(ParseError, match="invalid domain"):
        write_domain_list({"example"}, output)


def test_atomic_write_preserves_original_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "domains.txt"
    output.write_text("original\n", encoding="utf-8")

    def fail_replace(source: str, destination: Path) -> None:
        del source, destination
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(parser_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failure"):
        atomic_write_text("replacement\n", output)

    assert output.read_text(encoding="utf-8") == "original\n"
    assert not list(tmp_path.glob(".domains.txt.*"))


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


class FailingSession(requests.Session):
    def get(self, url: str, **kwargs: object) -> FakeResponse:
        del kwargs
        raise requests.ConnectionError(f"failed to connect to {url}")


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


def test_archive_url_credentials_are_redacted_from_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    content = make_zip({"repository/data/category-ru": "ru\n"})
    archive_url = (
        "https://build-user:super-secret@example.invalid/archive.zip"
        "?access_token=query-secret&branch=main"
    )
    downloader = DomainListDownloader(archive_url, session=FakeSession(content))

    with caplog.at_level("INFO"):
        downloader.download(tmp_path)

    assert "super-secret" not in caplog.text
    assert "query-secret" not in caplog.text
    assert "build-user" not in caplog.text
    assert "REDACTED" in caplog.text
    assert "branch=main" in caplog.text


def test_malformed_archive_url_is_never_logged_verbatim() -> None:
    assert redact_url_credentials(
        "https://user:secret@example.invalid:bad/archive"
    ) == ("<redacted-url>")


def test_archive_url_credentials_are_redacted_from_download_errors(
    tmp_path: Path,
) -> None:
    archive_url = "https://user:secret@example.invalid/archive.zip?token=query-secret"
    downloader = DomainListDownloader(archive_url, session=FailingSession())

    with pytest.raises(DownloadError) as error:
        downloader.download(tmp_path)

    assert "secret" not in str(error.value)
    assert "REDACTED" in str(error.value)
