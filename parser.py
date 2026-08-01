"""Download and parse V2Fly domain-list-community data."""

from __future__ import annotations

import io
import logging
import os
import re
import stat
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOGGER = logging.getLogger(__name__)

DEFAULT_ARCHIVE_URL = (
    "https://github.com/v2fly/domain-list-community/" "archive/refs/heads/master.zip"
)
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_INCLUDE_DEPTH = 100

_DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_LIST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._!+-]*")
_UNSUPPORTED_RULE_PREFIXES = ("keyword:", "regexp:")


class DomainListError(RuntimeError):
    """Base error for domain-list generation failures."""


class DownloadError(DomainListError):
    """Raised when the upstream repository cannot be downloaded safely."""


class ParseError(DomainListError):
    """Raised when the requested list graph cannot be resolved."""


@dataclass(frozen=True, slots=True)
class ParseResult:
    """Immutable output and metrics from a parser run."""

    domains: frozenset[str]
    includes: int = 0
    duplicates_removed: int = 0
    invalid_removed: int = 0
    manual_domains: int = 0
    smart_home_domains: int = 0


class DomainListDownloader:
    """Download and safely extract the latest upstream source archive."""

    def __init__(
        self,
        archive_url: str = DEFAULT_ARCHIVE_URL,
        *,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        session: requests.Session | None = None,
    ) -> None:
        self.archive_url = archive_url
        self.max_download_bytes = max_download_bytes
        self._session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        session = requests.Session()
        session.headers.update({"User-Agent": "pbr-russia-domain-list/1.0"})
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def download(self, destination: Path) -> Path:
        """Download into *destination* and return the extracted repository root."""
        destination.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Downloading V2Fly data from %s", self.archive_url)

        try:
            with self._session.get(
                self.archive_url,
                stream=True,
                timeout=(10, 90),
            ) as response:
                response.raise_for_status()
                archive_bytes = io.BytesIO()
                size = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.max_download_bytes:
                        raise DownloadError(
                            "Upstream archive exceeds the configured size limit"
                        )
                    archive_bytes.write(chunk)
        except requests.RequestException as exc:
            raise DownloadError(f"Failed to download upstream archive: {exc}") from exc

        archive_bytes.seek(0)
        try:
            with zipfile.ZipFile(archive_bytes) as archive:
                self._validate_archive(archive, destination)
                archive.extractall(destination)
        except (OSError, zipfile.BadZipFile) as exc:
            raise DownloadError(f"Invalid upstream archive: {exc}") from exc

        repositories = [
            path.parent for path in destination.glob("*/data") if path.is_dir()
        ]
        if len(repositories) != 1:
            raise DownloadError(
                "Upstream archive did not contain exactly one repository data directory"
            )

        LOGGER.info("Downloaded %d bytes of upstream data", size)
        return repositories[0]

    @staticmethod
    def _validate_archive(archive: zipfile.ZipFile, destination: Path) -> None:
        root = destination.resolve()
        for member in archive.infolist():
            member_path = PurePosixPath(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise DownloadError("Upstream archive contains an unsafe path")

            target = destination.joinpath(*member_path.parts).resolve()
            if target != root and root not in target.parents:
                raise DownloadError("Upstream archive escapes the destination")

            unix_mode = member.external_attr >> 16
            if unix_mode and stat.S_ISLNK(unix_mode):
                raise DownloadError("Upstream archive contains a symbolic link")


class DomainListParser:
    """Resolve V2Fly domain lists and return normalized domains."""

    def __init__(
        self,
        data_directory: Path,
        *,
        max_include_depth: int = DEFAULT_MAX_INCLUDE_DEPTH,
    ) -> None:
        if max_include_depth < 0:
            raise ValueError("max_include_depth must not be negative")
        self.data_directory = data_directory.resolve()
        self.max_include_depth = max_include_depth
        self._cache: dict[str, tuple[str, ...]] = {}
        self._includes = 0
        self._invalid_removed = 0

    def parse(self, entry_lists: Iterable[str]) -> set[str]:
        """Recursively resolve one or more entry lists."""
        return set(self.parse_with_statistics(entry_lists).domains)

    def parse_with_statistics(self, entry_lists: Iterable[str]) -> ParseResult:
        """Recursively resolve lists and return domains with generation metrics."""
        self._cache.clear()
        self._includes = 0
        self._invalid_removed = 0

        occurrences: list[str] = []
        for entry_list in entry_lists:
            occurrences.extend(self._parse_list(entry_list, ()))

        domains = frozenset(occurrences)
        return ParseResult(
            domains=domains,
            includes=self._includes,
            duplicates_removed=len(occurrences) - len(domains),
            invalid_removed=self._invalid_removed,
        )

    def _parse_list(self, list_name: str, stack: tuple[str, ...]) -> tuple[str, ...]:
        list_name = list_name.strip()
        if not _LIST_NAME.fullmatch(list_name):
            raise ParseError(f"Invalid include name: {list_name!r}")
        if list_name in stack:
            chain = " -> ".join((*stack, list_name))
            raise ParseError(f"Circular include detected: {chain}")
        if len(stack) > self.max_include_depth:
            chain = " -> ".join((*stack, list_name))
            raise ParseError(
                f"Maximum include depth of {self.max_include_depth} exceeded "
                f"while resolving: {chain}"
            )
        if list_name in self._cache:
            return self._cache[list_name]

        source_path = (self.data_directory / list_name).resolve()
        if self.data_directory not in source_path.parents:
            raise ParseError(f"Include escapes the data directory: {list_name!r}")
        if not source_path.is_file():
            raise ParseError(f"Included list does not exist: {list_name!r}")

        LOGGER.debug("Parsing V2Fly list %s", list_name)
        domains: list[str] = []
        next_stack = (*stack, list_name)
        try:
            lines = source_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise ParseError(f"List is not valid UTF-8: {list_name!r}") from exc

        for line_number, raw_line in enumerate(lines, start=1):
            line = self._clean_line(raw_line)
            if not line:
                continue

            if line.startswith("include:"):
                include_value = line.removeprefix("include:").strip()
                if not include_value:
                    raise ParseError(
                        f"Empty include target in {list_name}:{line_number}"
                    )
                include_name = include_value.split(maxsplit=1)[0]
                self._includes += 1
                domains.extend(self._parse_list(include_name, next_stack))
                continue

            domain, invalid = _parse_domain_rule_with_status(line)
            if domain is not None:
                domains.append(domain)
            elif invalid:
                self._invalid_removed += 1
            elif not line.startswith(_UNSUPPORTED_RULE_PREFIXES):
                LOGGER.debug(
                    "Ignoring unsupported or invalid rule in %s:%d: %s",
                    list_name,
                    line_number,
                    line,
                )

        result = tuple(domains)
        self._cache[list_name] = result
        return result

    @staticmethod
    def _clean_line(raw_line: str) -> str:
        without_comment = raw_line.split("#", maxsplit=1)[0]
        without_attributes = without_comment.split("@", maxsplit=1)[0]
        return without_attributes.strip()


def parse_domain_rule(line: str) -> str | None:
    """Parse a supported V2Fly rule, returning a normalized domain if valid."""
    domain, _ = _parse_domain_rule_with_status(DomainListParser._clean_line(line))
    return domain


def _parse_domain_rule_with_status(line: str) -> tuple[str | None, bool]:
    """Return a domain and whether a supported rule was syntactically invalid."""
    if line.startswith(_UNSUPPORTED_RULE_PREFIXES) or line.startswith("include:"):
        return None, False

    if ":" in line:
        rule_type, value = line.split(":", maxsplit=1)
        if rule_type not in {"domain", "full"}:
            return None, False
    else:
        # V2Fly documents a missing prefix as shorthand for ``domain:``.
        value = line

    domain = normalize_domain(value)
    return domain, domain is None


def normalize_domain(value: str) -> str | None:
    """Convert a domain to lowercase ASCII and validate its DNS labels."""
    if not value or value != value.strip() or any(char.isspace() for char in value):
        return None
    value = value.rstrip(".")
    if not value or value.startswith("."):
        return None

    try:
        normalized = value.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None

    if len(normalized) > 253:
        return None
    labels = normalized.split(".")
    if any(not _DOMAIN_LABEL.fullmatch(label) for label in labels):
        return None
    if len(labels) == 1 and not normalized.startswith("xn--"):
        return None
    return normalized


def load_custom_domains(path: Path) -> set[str]:
    """Load supported domain rules from a local customization file."""
    return set(load_custom_domains_with_statistics(path).domains)


def load_custom_domains_with_statistics(path: Path) -> ParseResult:
    """Load custom rules and return domains with validation metrics."""
    if not path.is_file():
        raise ParseError(f"Custom domain file does not exist: {path}")

    occurrences: list[str] = []
    invalid_removed = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = DomainListParser._clean_line(raw_line)
        if not line:
            continue
        domain, invalid = _parse_domain_rule_with_status(line)
        if domain is None:
            if invalid:
                invalid_removed += 1
                LOGGER.warning(
                    "Ignoring invalid custom rule at %s:%d", path, line_number
                )
            continue
        occurrences.append(domain)

    domains = frozenset(occurrences)
    return ParseResult(
        domains=domains,
        duplicates_removed=len(occurrences) - len(domains),
        invalid_removed=invalid_removed,
    )


def load_custom_sources_with_statistics(
    custom_directory: Path | None,
    legacy_path: Path | None = None,
) -> ParseResult:
    """Load every custom TXT source plus an optional legacy customization file.

    ``smart-home.txt`` is tracked separately for reporting. All other files,
    including the legacy file, are counted as manually maintained sources.
    Missing directories and missing legacy files are intentionally ignored so
    existing installations can migrate incrementally.
    """
    source_paths: list[Path] = []
    if custom_directory is not None:
        if custom_directory.exists() and not custom_directory.is_dir():
            raise ParseError(
                f"Custom domain directory is not a directory: {custom_directory}"
            )
        if custom_directory.is_dir():
            source_paths.extend(
                sorted(custom_directory.glob("*.txt"), key=lambda path: path.name)
            )

    if legacy_path is not None and legacy_path.exists():
        if not legacy_path.is_file():
            raise ParseError(f"Custom domain file is not a file: {legacy_path}")
        known_paths = {path.resolve() for path in source_paths}
        if legacy_path.resolve() not in known_paths:
            source_paths.append(legacy_path)

    merged_domains: set[str] = set()
    manual_domains: set[str] = set()
    smart_home_domains: set[str] = set()
    duplicates_removed = 0
    invalid_removed = 0

    for source_path in source_paths:
        result = load_custom_domains_with_statistics(source_path)
        duplicates_removed += result.duplicates_removed
        duplicates_removed += len(merged_domains & result.domains)
        invalid_removed += result.invalid_removed
        merged_domains.update(result.domains)

        if source_path.name == "smart-home.txt":
            smart_home_domains.update(result.domains)
        else:
            manual_domains.update(result.domains)

    LOGGER.info(
        "Loaded %d custom domains from %d source files",
        len(merged_domains),
        len(source_paths),
    )
    return ParseResult(
        domains=frozenset(merged_domains),
        duplicates_removed=duplicates_removed,
        invalid_removed=invalid_removed,
        manual_domains=len(manual_domains),
        smart_home_domains=len(smart_home_domains),
    )


def atomic_write_text(content: str, output_path: Path) -> bool:
    """Atomically replace a UTF-8 file if and only if its content changed."""
    if output_path.is_file() and output_path.read_text(encoding="utf-8") == content:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            delete=False,
        ) as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_name = temporary_file.name
        os.replace(temporary_name, output_path)
        return True
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def write_domain_list(domains: Iterable[str], output_path: Path) -> bool:
    """Write a deterministic list atomically."""
    sorted_domains = sorted(set(domains))
    if not sorted_domains:
        raise ParseError("Refusing to write an empty domain list")

    invalid = [
        domain for domain in sorted_domains if normalize_domain(domain) != domain
    ]
    if invalid:
        raise ParseError(f"Refusing to write invalid domain: {invalid[0]!r}")

    content = "\n".join(sorted_domains) + "\n"
    return atomic_write_text(content, output_path)
