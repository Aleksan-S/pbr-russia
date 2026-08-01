"""Generate the OpenWrt PBR Russian domain list."""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from parser import (
    DEFAULT_ARCHIVE_URL,
    DomainListDownloader,
    DomainListError,
    DomainListParser,
    ParseResult,
    atomic_write_text,
    load_custom_sources_with_statistics,
    write_domain_list,
)

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class GenerationStatistics:
    """Stable, JSON-serializable generation metrics."""

    generated_at: str
    domains: int
    includes: int
    duplicates_removed: int
    invalid_removed: int
    manual_domains: int = 0
    smart_home_domains: int = 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a PBR-compatible Russian domain list from V2Fly data."
    )
    parser.add_argument(
        "--entry",
        action="append",
        dest="entries",
        help="V2Fly entry list to resolve (repeatable; default: category-ru)",
    )
    parser.add_argument(
        "--custom",
        type=Path,
        default=PROJECT_ROOT / "custom-domains.txt",
        help="path to the legacy additional domain rules file",
    )
    parser.add_argument(
        "--custom-dir",
        type=Path,
        default=PROJECT_ROOT / "custom",
        help="directory of additional *.txt domain rule files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "russia-domains.txt",
        help="destination domain list",
    )
    parser.add_argument(
        "--statistics",
        type=Path,
        default=PROJECT_ROOT / "output" / "statistics.json",
        help="destination generation statistics",
    )
    parser.add_argument(
        "--archive-url",
        default=DEFAULT_ARCHIVE_URL,
        help="override the V2Fly source archive URL",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
    )
    return parser


def build_statistics(
    upstream: ParseResult,
    custom: ParseResult,
    *,
    generated_at: datetime | None = None,
) -> GenerationStatistics:
    """Combine parser metrics without losing cross-source duplicates."""
    domains = upstream.domains | custom.domains
    source_overlap = len(upstream.domains & custom.domains)
    timestamp = generated_at or datetime.now(UTC)
    return GenerationStatistics(
        generated_at=timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        domains=len(domains),
        includes=upstream.includes,
        duplicates_removed=(
            upstream.duplicates_removed + custom.duplicates_removed + source_overlap
        ),
        invalid_removed=upstream.invalid_removed + custom.invalid_removed,
        manual_domains=custom.manual_domains,
        smart_home_domains=custom.smart_home_domains,
    )


def write_statistics(
    statistics: GenerationStatistics,
    output_path: Path,
    *,
    force_new_timestamp: bool,
) -> bool:
    """Write statistics atomically while preserving stable no-op generations."""
    if output_path.is_file() and not force_new_timestamp:
        try:
            existing = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = None
        if isinstance(existing, dict):
            numeric_fields_match = all(
                existing.get(field) == getattr(statistics, field)
                for field in (
                    "domains",
                    "includes",
                    "duplicates_removed",
                    "invalid_removed",
                    "manual_domains",
                    "smart_home_domains",
                )
            )
            if numeric_fields_match and isinstance(existing.get("generated_at"), str):
                statistics = replace(statistics, generated_at=existing["generated_at"])

    content = json.dumps(asdict(statistics), indent=2, ensure_ascii=True) + "\n"
    return atomic_write_text(content, output_path)


def run(args: argparse.Namespace) -> int:
    entries = args.entries or ["category-ru"]
    with tempfile.TemporaryDirectory(prefix="pbr-russia-") as temporary_directory:
        repository = DomainListDownloader(args.archive_url).download(
            Path(temporary_directory)
        )
        upstream = DomainListParser(repository / "data").parse_with_statistics(entries)

    custom = load_custom_sources_with_statistics(
        getattr(args, "custom_dir", None),
        args.custom,
    )
    domains = upstream.domains | custom.domains
    domain_list_changed = write_domain_list(domains, args.output)
    statistics_path = getattr(
        args, "statistics", args.output.with_name("statistics.json")
    )
    statistics = build_statistics(upstream, custom)
    statistics_changed = write_statistics(
        statistics,
        statistics_path,
        force_new_timestamp=domain_list_changed,
    )
    LOGGER.info(
        "Generated %d domains (%d upstream, %d custom) at %s; changed=%s",
        len(domains),
        len(upstream.domains),
        len(custom.domains),
        args.output,
        domain_list_changed or statistics_changed,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return run(args)
    except DomainListError as exc:
        LOGGER.error("Domain list update failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
