"""Discover domains in dnsmasq query logs that are absent from the PBR list."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TextIO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parser import normalize_domain  # noqa: E402

DEFAULT_DOMAIN_LIST = PROJECT_ROOT / "output" / "russia-domains.txt"
QUERY_PATTERN = re.compile(r"\bquery\[(?:A|AAAA)\]\s+(\S+)", re.IGNORECASE)
RESERVED_SUFFIXES = (".rl", ".test", ".invalid", ".example", ".localhost", ".local")

IGNORED_SUFFIXES = frozenset(
    {
        "akamai.net",
        "akamaiedge.net",
        "akamaized.net",
        "amazonaws.com",
        "amazontrust.com",
        "apple-dns.net",
        "apple.com",
        "azure.com",
        "azureedge.net",
        "azurewebsites.net",
        "bing.com",
        "cdn-apple.com",
        "chatgpt.com",
        "cloudflare-dns.com",
        "cloudflare.com",
        "cloudflareinsights.com",
        "cloudflare.net",
        "cloudfront.net",
        "digicert.com",
        "doubleclick.net",
        "edgekey.net",
        "edgesuite.net",
        "facebook.com",
        "fastly.net",
        "fastlylb.net",
        "fbcdn.net",
        "fbsbx.com",
        "github.com",
        "github.io",
        "githubassets.com",
        "githubstatus.com",
        "githubusercontent.com",
        "google.com",
        "google.ru",
        "googleapis.com",
        "googlesyndication.com",
        "googletagmanager.com",
        "googleusercontent.com",
        "googlevideo.com",
        "gstatic.com",
        "icloud-content.com",
        "icloud.com",
        "instagram.com",
        "letsencrypt.org",
        "live.com",
        "messenger.com",
        "meta.com",
        "microsoft.com",
        "microsoftonline.com",
        "msedge.net",
        "msftconnecttest.com",
        "msn.com",
        "mzstatic.com",
        "ntp.org",
        "oaiusercontent.com",
        "oaistatic.com",
        "office.com",
        "office365.com",
        "openai.com",
        "push.apple.com",
        "skype.com",
        "steamcommunity.com",
        "steamcontent.com",
        "steampowered.com",
        "steamserver.net",
        "steamstatic.com",
        "whatsapp.net",
        "windows.com",
        "windows.net",
        "workers.dev",
        "youtube-nocookie.com",
        "youtube.com",
        "ytimg.com",
    }
)


def normalize_observed_domain(value: str) -> str | None:
    """Normalize a queried hostname and reject non-production name forms."""
    domain = normalize_domain(value)
    if domain is None or any(domain.endswith(suffix) for suffix in RESERVED_SUFFIXES):
        return None
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        return domain
    return None


def parse_dnsmasq_queries(lines: Iterable[str]) -> set[str]:
    """Extract unique normalized A and AAAA query names from dnsmasq logs."""
    domains: set[str] = set()
    for line in lines:
        match = QUERY_PATTERN.search(line)
        if match is None:
            continue
        domain = normalize_observed_domain(match.group(1))
        if domain is not None:
            domains.add(domain)
    return domains


def is_ignored_domain(domain: str) -> bool:
    """Return whether a domain belongs to a known high-volume public service."""
    return any(
        domain == suffix or domain.endswith(f".{suffix}") for suffix in IGNORED_SUFFIXES
    )


def load_generated_domains(path: Path) -> set[str]:
    """Load and verify the generated domain list used for comparison."""
    domains: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        domain = normalize_observed_domain(line)
        if domain != line:
            raise ValueError(f"invalid domain at {path}:{line_number}: {line!r}")
        domains.add(domain)
    return domains


def discover_missing_domains(
    lines: Iterable[str], generated_domains: set[str]
) -> tuple[str, ...]:
    """Return sorted observed domains absent from the generated list."""
    observed = parse_dnsmasq_queries(lines)
    return tuple(
        sorted(
            domain
            for domain in observed
            if domain not in generated_domains and not is_ignored_domain(domain)
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Find normalized dnsmasq A/AAAA query domains missing from the "
            "generated PBR list."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="dnsmasq log file (default: stdin)",
    )
    parser.add_argument(
        "--domains",
        type=Path,
        default=DEFAULT_DOMAIN_LIST,
        help="generated domain list used for comparison",
    )
    return parser


def print_report(domains: Sequence[str], stream: TextIO | None = None) -> None:
    """Print a stable, copy-friendly discovery report."""
    output = stream or sys.stdout
    if not domains:
        print("No missing domains.", file=output)
        return
    print("Missing domains:\n", file=output)
    for domain in domains:
        print(domain, file=output)


def main(argv: Sequence[str] | None = None, stdin: TextIO | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        generated_domains = load_generated_domains(args.domains)
        if args.input is None:
            missing = discover_missing_domains(stdin or sys.stdin, generated_domains)
        else:
            with args.input.open(encoding="utf-8") as input_file:
                missing = discover_missing_domains(input_file, generated_domains)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print_report(missing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
