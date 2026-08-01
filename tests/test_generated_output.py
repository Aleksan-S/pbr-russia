from __future__ import annotations

import json
from pathlib import Path

from parser import normalize_domain
from validate import MINIMUM_DOMAIN_COUNT, validate_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SMART_HOME_REPRESENTATIVES = {
    "hik-connect.com",
    "ezviz.com",
    "api.io.mi.com",
    "open-ru.aqara.com",
    "roborock.com",
    "iot.dreame.tech",
    "api.yeelight.com",
    "tplinkcloud.com",
    "nabu.casa",
    "security-app-eu.eufylife.com",
    "api.switch-bot.com",
    "shelly.cloud",
    "iotx-eu.meross.com",
    "openapi.tuyaeu.com",
    "openapi.api.govee.com",
    "nanoleaf.me",
    "api.meethue.com",
    "lgthinq.com",
    "api.smartthings.com",
    "homegraph.googleapis.com",
    "api.eu.amazonalexa.com",
    "icloud.com",
}


def test_committed_outputs_are_consistent() -> None:
    domain_path = PROJECT_ROOT / "output" / "russia-domains.txt"
    statistics_path = PROJECT_ROOT / "output" / "statistics.json"

    report = validate_file(domain_path)
    statistics = json.loads(statistics_path.read_text(encoding="utf-8"))

    assert report.valid, report.errors()
    assert statistics["domains"] == report.domains
    assert statistics["domains"] >= MINIMUM_DOMAIN_COUNT
    assert statistics["includes"] >= 1
    assert statistics["duplicates_removed"] >= 0
    assert statistics["invalid_removed"] >= 0
    assert statistics["manual_domains"] >= 0
    assert statistics["smart_home_domains"] >= len(SMART_HOME_REPRESENTATIVES)
    assert statistics["generated_at"].endswith("Z")


def test_smart_home_domains_are_present_in_committed_output() -> None:
    domains = set(
        (PROJECT_ROOT / "output" / "russia-domains.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert domains >= SMART_HOME_REPRESENTATIVES


def test_smart_home_source_is_normalized_unique_and_sorted() -> None:
    domains = (
        (PROJECT_ROOT / "custom" / "smart-home.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )

    assert domains == sorted(domains)
    assert len(domains) == len(set(domains))
    assert all(normalize_domain(domain) == domain for domain in domains)
