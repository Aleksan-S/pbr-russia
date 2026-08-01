from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = PROJECT_ROOT / "openwrt" / "install.sh"
UPDATE_SCRIPT = PROJECT_ROOT / "openwrt" / "update.sh"
POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="requires a POSIX shell")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def make_domain_list(path: Path, count: int = 1500) -> None:
    path.write_text(
        "".join(f"host-{index}.example.ru\n" for index in range(count)),
        encoding="utf-8",
    )


def make_fake_environment(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    etc_dir = tmp_path / "etc"
    (etc_dir / "config").mkdir(parents=True)
    (etc_dir / "config" / "pbr").touch()
    (etc_dir / "init.d").mkdir()
    init_log = tmp_path / "init.log"
    uci_state = tmp_path / "uci.state"
    uci_state.touch()
    commit_log = tmp_path / "commits.log"
    domain_source = tmp_path / "domains.txt"
    make_domain_list(domain_source)

    write_executable(
        fake_bin / "uclient-fetch",
        """#!/bin/sh
destination=$3
url=$4
case "$url" in
    */openwrt/update.sh) cp "$FAKE_UPDATE_SOURCE" "$destination" ;;
    *) cp "$FAKE_LIST_SOURCE" "$destination" ;;
esac
""",
    )
    write_executable(
        fake_bin / "uci",
        """#!/bin/sh
if [ "${1:-}" = "-q" ]; then shift; fi
command=$1
shift
case "$command" in
    get)
        key=$1
        value=$(
            awk -F= -v key="$key" \
                '$1 == key {sub(/^[^=]*=/, ""); print; exit}' \
                "$FAKE_UCI_STATE"
        )
        [ -n "$value" ] || exit 1
        printf '%s\n' "$value"
        ;;
    set)
        assignment=$1
        key=${assignment%%=*}
        value=${assignment#*=}
        awk -F= -v key="$key" '$1 != key' "$FAKE_UCI_STATE" >"$FAKE_UCI_STATE.tmp"
        printf '%s=%s\n' "$key" "$value" >>"$FAKE_UCI_STATE.tmp"
        mv "$FAKE_UCI_STATE.tmp" "$FAKE_UCI_STATE"
        ;;
    commit)
        printf 'commit\n' >>"$FAKE_COMMIT_LOG"
        ;;
    *) exit 2 ;;
esac
""",
    )
    write_executable(
        fake_bin / "dnsmasq",
        "#!/bin/sh\n"
        "printf '%s\n' "
        "'Dnsmasq version fixture Compile time options: nftset'\n",
    )
    write_executable(
        fake_bin / "curl",
        "#!/bin/sh\nexit 0\n",
    )
    for service in ("pbr", "cron"):
        write_executable(
            etc_dir / "init.d" / service,
            f"#!/bin/sh\nprintf '%s %s\\n' '{service}' \"$1\" >>\"$FAKE_INIT_LOG\"\n",
        )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "FAKE_UPDATE_SOURCE": str(UPDATE_SCRIPT),
            "FAKE_LIST_SOURCE": str(domain_source),
            "FAKE_UCI_STATE": str(uci_state),
            "FAKE_COMMIT_LOG": str(commit_log),
            "FAKE_INIT_LOG": str(init_log),
            "PBR_RUSSIA_RAW_BASE": "https://fixture.invalid",
            "PBR_RUSSIA_LIST_URL": "https://fixture.invalid/domains.txt",
            "PBR_RUSSIA_ETC_DIR": str(etc_dir),
            "PBR_RUSSIA_INSTALL_DIR": str(tmp_path / "install"),
            "PBR_RUSSIA_TARGET": str(tmp_path / "pbr" / "domains.txt"),
            "PBR_RUSSIA_CRON_FILE": str(etc_dir / "crontabs" / "root"),
            "PBR_RUSSIA_SKIP_ROOT_CHECK": "yes",
            "INSTALL_CRON": "yes",
        }
    )
    return environment, uci_state, init_log


def run_script(
    script: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    shell = shutil.which("sh")
    assert shell is not None
    return subprocess.run(
        [shell, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@POSIX_ONLY
def test_installer_is_idempotent(tmp_path: Path) -> None:
    environment, uci_state, init_log = make_fake_environment(tmp_path)

    first = run_script(INSTALL_SCRIPT, environment)
    second = run_script(INSTALL_SCRIPT, environment)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    state_lines = uci_state.read_text(encoding="utf-8").splitlines()
    assert state_lines.count("pbr.russia_domains=policy") == 1
    assert "pbr.config.resolver_set=dnsmasq.nftset" in state_lines
    cron_lines = (
        Path(environment["PBR_RUSSIA_CRON_FILE"])
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len([line for line in cron_lines if "pbr-russia" in line]) == 1
    assert cron_lines[0].startswith("30 4 * * 1 ")
    pbr_restarts = [
        line
        for line in init_log.read_text(encoding="utf-8").splitlines()
        if line == "pbr restart"
    ]
    assert len(pbr_restarts) == 1


@POSIX_ONLY
def test_update_unchanged_does_not_restart_pbr(tmp_path: Path) -> None:
    environment, _, init_log = make_fake_environment(tmp_path)
    target = Path(environment["PBR_RUSSIA_TARGET"])
    target.parent.mkdir(parents=True)
    shutil.copyfile(environment["FAKE_LIST_SOURCE"], target)

    result = run_script(UPDATE_SCRIPT, environment)

    assert result.returncode == 0, result.stderr
    assert "Already up to date." in result.stdout
    assert not init_log.exists() or "pbr restart" not in init_log.read_text(
        encoding="utf-8"
    )


@POSIX_ONLY
def test_update_changed_restarts_pbr_once(tmp_path: Path) -> None:
    environment, _, init_log = make_fake_environment(tmp_path)
    target = Path(environment["PBR_RUSSIA_TARGET"])
    target.parent.mkdir(parents=True)
    target.write_text("old.example.ru\n", encoding="utf-8")
    environment["PBR_INIT_SCRIPT"] = str(
        Path(environment["PBR_RUSSIA_ETC_DIR"]) / "init.d" / "pbr"
    )

    result = run_script(UPDATE_SCRIPT, environment)

    assert result.returncode == 0, result.stderr
    assert init_log.read_text(encoding="utf-8").splitlines() == ["pbr restart"]
