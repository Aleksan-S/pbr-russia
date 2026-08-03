from __future__ import annotations

import re
from pathlib import Path

from tools.generate_checksums import MANIFEST_PATH, PUBLISHED_FILES, build_manifest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIRECTORY = PROJECT_ROOT / ".github" / "workflows"
ACTION_REFERENCE = re.compile(r"^\s*uses:\s*[^@\s]+@([^\s#]+)", re.MULTILINE)


def test_every_github_action_is_pinned_to_a_commit_sha() -> None:
    workflows = sorted(WORKFLOW_DIRECTORY.glob("*.yml"))
    assert workflows

    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        references = ACTION_REFERENCE.findall(content)
        assert references, f"no action references found in {workflow.name}"
        assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in references)


def test_workflows_default_to_no_token_permissions() -> None:
    for workflow in WORKFLOW_DIRECTORY.glob("*.yml"):
        content = workflow.read_text(encoding="utf-8")
        assert "\npermissions: {}\n" in content

    update_workflow = (WORKFLOW_DIRECTORY / "update.yml").read_text(encoding="utf-8")
    assert update_workflow.count("contents: write") == 1
    assert "github.event_name != 'pull_request'" in update_workflow
    assert "--clobber" not in update_workflow
    assert "${GITHUB_RUN_NUMBER}" in update_workflow
    assert "${GITHUB_RUN_ATTEMPT}" in update_workflow


def test_published_checksum_manifest_is_current() -> None:
    assert MANIFEST_PATH.read_text(encoding="utf-8") == build_manifest()
    manifest_names = {
        line.split(maxsplit=1)[1] for line in build_manifest().splitlines()
    }
    assert manifest_names == {asset_name for asset_name, _ in PUBLISHED_FILES}


def test_sensitive_local_file_patterns_are_ignored() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert {
        ".env",
        ".env.*",
        "*.key",
        "*.pem",
        "*.p12",
        "*.crt",
        "*.ovpn",
        "wg*.conf",
        "openvpn*.conf",
    } <= set(gitignore)
