from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from tools.discover_domains import (
    discover_missing_domains,
    is_ignored_domain,
    parse_dnsmasq_queries,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DISCOVERY_SCRIPT = PROJECT_ROOT / "tools" / "discover_domains.py"


def test_parses_real_dnsmasq_a_and_aaaa_queries() -> None:
    log_lines = [
        "Aug  1 12:00:00 dnsmasq[1234]: query[A] "
        "APIIRUS.HIK-CONNECTRU.COM from 192.168.1.20\n",
        "Aug  1 12:00:01 dnsmasq[1234]: query[AAAA] "
        "ru.mqtt.io.mi.com. from 192.168.1.20\n",
        "Aug  1 12:00:02 dnsmasq[1234]: query[PTR] ignored.vendor.com "
        "from 192.168.1.20\n",
        "Aug  1 12:00:03 dnsmasq[1234]: query[A] 192.0.2.1 " "from 192.168.1.20\n",
        "Aug  1 12:00:04 dnsmasq[1234]: query[A] device.local " "from 192.168.1.20\n",
    ]

    assert parse_dnsmasq_queries(log_lines) == {
        "apiirus.hik-connectru.com",
        "ru.mqtt.io.mi.com",
    }


@pytest.mark.parametrize(
    "domain",
    [
        "fonts.googleapis.com",
        "one.one.one.one.cloudflare-dns.com",
        "login.microsoftonline.com",
        "gateway.icloud.com",
        "cdn.steamcontent.com",
        "i.ytimg.com",
        "chatgpt.com",
        "static.xx.fbcdn.net",
        "raw.githubusercontent.com",
        "assets.cloudfront.net",
    ],
)
def test_ignores_common_public_services(domain: str) -> None:
    assert is_ignored_domain(domain)


def test_discovers_sorted_unique_domains_missing_from_output() -> None:
    logs = [
        "dnsmasq: query[A] known.vendor.com from 192.168.1.2\n",
        "dnsmasq: query[A] MQTT.VENDOR.NET from 192.168.1.2\n",
        "dnsmasq: query[AAAA] mqtt.vendor.net from 192.168.1.2\n",
        "dnsmasq: query[A] api.vendor.com from 192.168.1.2\n",
        "dnsmasq: query[A] www.google.com from 192.168.1.2\n",
    ]

    missing = discover_missing_domains(logs, {"known.vendor.com"})

    assert missing == ("api.vendor.com", "mqtt.vendor.net")


def test_command_line_reads_file_and_prints_only_missing_domains(
    tmp_path: Path,
) -> None:
    generated = tmp_path / "domains.txt"
    generated.write_text("known.vendor.com\n", encoding="utf-8")
    dnsmasq_log = tmp_path / "dns.log"
    dnsmasq_log.write_text(
        "dnsmasq[42]: query[A] known.vendor.com from 192.168.1.5\n"
        "dnsmasq[42]: query[AAAA] cloud.vendor.io from 192.168.1.5\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(DISCOVERY_SCRIPT),
            "--input",
            str(dnsmasq_log),
            "--domains",
            str(generated),
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "Missing domains:\n\ncloud.vendor.io\n"


def test_command_line_supports_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from tools import discover_domains

    generated = tmp_path / "domains.txt"
    generated.write_text("known.vendor.com\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO("dnsmasq: query[A] api.vendor.com from 192.168.1.2\n"),
    )

    exit_code = discover_domains.main(["--domains", str(generated)])

    assert exit_code == 0
    assert capsys.readouterr().out == "Missing domains:\n\napi.vendor.com\n"
