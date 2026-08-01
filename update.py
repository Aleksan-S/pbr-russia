"""Generate the OpenWrt PBR Russian domain list."""

from __future__ import annotations

import argparse
import logging
import tempfile
from collections.abc import Sequence
from pathlib import Path

from parser import (
    DEFAULT_ARCHIVE_URL,
    DomainListDownloader,
    DomainListError,
    DomainListParser,
    load_custom_domains,
    write_domain_list,
)

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent


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
        help="path to additional domain rules",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "output" / "russia-domains.txt",
        help="destination domain list",
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


def run(args: argparse.Namespace) -> int:
    entries = args.entries or ["category-ru"]
    with tempfile.TemporaryDirectory(prefix="pbr-russia-") as temporary_directory:
        repository = DomainListDownloader(args.archive_url).download(
            Path(temporary_directory)
        )
        upstream_domains = DomainListParser(repository / "data").parse(entries)

    custom_domains = load_custom_domains(args.custom)
    domains = upstream_domains | custom_domains
    write_domain_list(domains, args.output)
    LOGGER.info(
        "Wrote %d domains (%d upstream, %d custom) to %s",
        len(domains),
        len(upstream_domains),
        len(custom_domains),
        args.output,
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
