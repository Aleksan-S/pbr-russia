"""Generate the checksum manifest for files published to GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "output" / "SHA256SUMS"
PUBLISHED_FILES = (
    ("install.sh", PROJECT_ROOT / "openwrt" / "install.sh"),
    ("update.sh", PROJECT_ROOT / "openwrt" / "update.sh"),
    ("russia-domains.txt", PROJECT_ROOT / "output" / "russia-domains.txt"),
    ("statistics.json", PROJECT_ROOT / "output" / "statistics.json"),
)


def build_manifest() -> str:
    """Return a deterministic sha256sum-compatible manifest."""
    lines = []
    for asset_name, source_path in PUBLISHED_FILES:
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {asset_name}")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of updating an out-of-date manifest",
    )
    args = parser.parse_args(argv)
    expected = build_manifest()
    current = (
        MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else ""
    )
    if args.check:
        if current != expected:
            print("output/SHA256SUMS is out of date")
            return 1
        return 0

    if current != expected:
        MANIFEST_PATH.write_text(expected, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
