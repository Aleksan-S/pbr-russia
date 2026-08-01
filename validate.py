"""Validate generated domain lists for CI and release safety."""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from parser import normalize_domain

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent
MINIMUM_DOMAIN_COUNT = 1500
FORBIDDEN_SUFFIXES = (".rl", ".test", ".invalid", ".example", ".localhost")


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Detailed validation outcome for a generated list."""

    domains: int
    duplicates: tuple[str, ...]
    invalid: tuple[str, ...]
    forbidden_suffixes: tuple[str, ...]
    minimum_domains: int

    @property
    def valid(self) -> bool:
        return (
            self.domains >= self.minimum_domains
            and not self.duplicates
            and not self.invalid
            and not self.forbidden_suffixes
        )

    def errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.duplicates:
            errors.append(
                f"duplicate domains found ({len(self.duplicates)}): "
                + ", ".join(self.duplicates[:5])
            )
        if self.invalid:
            errors.append(
                f"invalid domains found ({len(self.invalid)}): "
                + ", ".join(repr(domain) for domain in self.invalid[:5])
            )
        if self.forbidden_suffixes:
            errors.append(
                "forbidden reserved suffixes found "
                f"({len(self.forbidden_suffixes)}): "
                + ", ".join(self.forbidden_suffixes[:5])
            )
        if self.domains < self.minimum_domains:
            errors.append(
                f"domain count {self.domains} is below minimum "
                f"{self.minimum_domains}"
            )
        return tuple(errors)


def validate_lines(
    lines: Sequence[str], *, minimum_domains: int = MINIMUM_DOMAIN_COUNT
) -> ValidationReport:
    """Validate normalized output lines without modifying them."""
    counts = Counter(lines)
    duplicates = tuple(sorted(domain for domain, count in counts.items() if count > 1))
    invalid = tuple(
        sorted(domain for domain in lines if normalize_domain(domain) != domain)
    )
    forbidden = tuple(
        sorted(
            domain
            for domain in lines
            if any(domain.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
        )
    )
    return ValidationReport(
        domains=len(lines),
        duplicates=duplicates,
        invalid=invalid,
        forbidden_suffixes=forbidden,
        minimum_domains=minimum_domains,
    )


def validate_file(
    path: Path, *, minimum_domains: int = MINIMUM_DOMAIN_COUNT
) -> ValidationReport:
    """Read and validate a UTF-8 domain list."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return validate_lines(lines, minimum_domains=minimum_domains)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a generated domain list.")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "output" / "russia-domains.txt",
    )
    parser.add_argument(
        "--minimum",
        type=int,
        default=MINIMUM_DOMAIN_COUNT,
        help="minimum required domain count",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.minimum < 0:
        LOGGER.error("minimum domain count must not be negative")
        return 2
    try:
        report = validate_file(args.path, minimum_domains=args.minimum)
    except (OSError, UnicodeError) as exc:
        LOGGER.error("cannot read %s: %s", args.path, exc)
        return 2
    if not report.valid:
        for error in report.errors():
            LOGGER.error("%s", error)
        return 1
    LOGGER.info("Validated %d unique domains", report.domains)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
