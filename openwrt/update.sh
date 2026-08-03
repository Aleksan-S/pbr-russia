#!/bin/sh

set -eu

DEFAULT_RELEASE_BASE="https://github.com/Aleksan-S/pbr-russia/releases/latest/download"
RELEASE_BASE="${PBR_RUSSIA_RELEASE_BASE:-$DEFAULT_RELEASE_BASE}"
LIST_URL="${PBR_RUSSIA_LIST_URL:-${RELEASE_BASE%/}/russia-domains.txt}"
CHECKSUMS_URL="${PBR_RUSSIA_CHECKSUMS_URL:-${RELEASE_BASE%/}/SHA256SUMS}"
TARGET="${PBR_RUSSIA_TARGET:-/etc/pbr/russia-domains.txt}"
PBR_INIT_SCRIPT="${PBR_INIT_SCRIPT:-/etc/init.d/pbr}"
RESTART_PBR="${PBR_RUSSIA_RESTART:-yes}"
STATUS_FILE="${PBR_RUSSIA_STATUS_FILE:-}"
MINIMUM_DOMAINS="${PBR_RUSSIA_MINIMUM_DOMAINS:-1500}"
SKIP_ROOT_CHECK="${PBR_RUSSIA_SKIP_ROOT_CHECK:-no}"
TARGET_DIR=$(dirname "$TARGET")
TEMP_FILE=""
TEMP_CHECKSUMS=""

log() {
    printf '%s\n' "pbr-russia: $*"
}

write_status() {
    if [ -n "$STATUS_FILE" ]; then
        printf '%s\n' "$1" >"$STATUS_FILE"
    fi
}

download() {
    url=$1
    destination=$2

    if command -v uclient-fetch >/dev/null 2>&1; then
        uclient-fetch -q -O "$destination" "$url"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$destination" "$url"
    elif command -v curl >/dev/null 2>&1; then
        curl --fail --location --silent --show-error --output "$destination" "$url"
    else
        log "no supported downloader found (uclient-fetch, wget, or curl)"
        return 1
    fi
}

cleanup() {
    if [ -n "$TEMP_FILE" ] && [ -f "$TEMP_FILE" ]; then
        rm -f "$TEMP_FILE"
    fi
    if [ -n "$TEMP_CHECKSUMS" ] && [ -f "$TEMP_CHECKSUMS" ]; then
        rm -f "$TEMP_CHECKSUMS"
    fi
}

checksum_for() {
    asset_name=$1
    manifest=$2
    awk -v asset="$asset_name" '
        $2 == asset && length($1) == 64 && $1 !~ /[^0-9A-Fa-f]/ {
            checksum = tolower($1)
            matches++
        }
        END {
            if (matches == 1) print checksum
            else exit 1
        }
    ' "$manifest"
}

validate_list() {
    list=$1

    awk -v minimum="$MINIMUM_DOMAINS" '
        {
            if (length($0) > 253 || $0 !~ /^[a-z0-9.-]+$/ || $0 ~ /\.\./) {
                exit 1
            }
            count = split($0, labels, ".")
            if (count < 2 && $0 !~ /^xn--/) {
                exit 1
            }
            for (label_index = 1; label_index <= count; label_index++) {
                if (length(labels[label_index]) > 63 ||
                    labels[label_index] !~ /^[a-z0-9]/ ||
                    labels[label_index] !~ /[a-z0-9]$/) {
                    exit 1
                }
            }
        }
        END {
            if (NR < minimum) exit 1
        }
    ' "$list" || return 1

    if LC_ALL=C sort "$list" | uniq -d | grep -q .; then
        return 1
    fi
    if grep -Eq '\.(rl|test|invalid|example|localhost)$' "$list"; then
        return 1
    fi
}

trap cleanup EXIT HUP INT TERM

case "$RESTART_PBR" in
    yes | no) ;;
    *)
        log "PBR_RUSSIA_RESTART must be 'yes' or 'no'"
        exit 2
        ;;
esac

case "$MINIMUM_DOMAINS" in
    '' | *[!0-9]*)
        log "PBR_RUSSIA_MINIMUM_DOMAINS must be a non-negative integer"
        exit 2
        ;;
esac

if [ "$SKIP_ROOT_CHECK" != "yes" ] && [ "$(id -u)" -ne 0 ]; then
    log "must be run as root"
    exit 1
fi

command -v sha256sum >/dev/null 2>&1 || {
    log "sha256sum is required"
    exit 1
}

mkdir -p "$TARGET_DIR"
TEMP_FILE=$(mktemp "$TARGET_DIR/.russia-domains.XXXXXX")
TEMP_CHECKSUMS=$(mktemp "$TARGET_DIR/.checksums.XXXXXX")
download "$CHECKSUMS_URL" "$TEMP_CHECKSUMS"
download "$LIST_URL" "$TEMP_FILE"

EXPECTED_SHA256=$(checksum_for "russia-domains.txt" "$TEMP_CHECKSUMS") || {
    log "checksum manifest has no unique valid entry for russia-domains.txt"
    exit 1
}
NEW_SHA256=$(sha256sum "$TEMP_FILE" | awk '{print tolower($1)}')
if [ "$NEW_SHA256" != "$EXPECTED_SHA256" ]; then
    log "SHA-256 verification failed for russia-domains.txt"
    exit 1
fi
rm -f "$TEMP_CHECKSUMS"
TEMP_CHECKSUMS=""

if [ ! -s "$TEMP_FILE" ] || ! validate_list "$TEMP_FILE"; then
    log "downloaded list failed validation"
    exit 1
fi

if [ -f "$TARGET" ]; then
    CURRENT_SHA256=$(sha256sum "$TARGET" | awk '{print tolower($1)}')
    if [ "$NEW_SHA256" = "$CURRENT_SHA256" ]; then
        write_status "unchanged"
        printf '%s\n' "Already up to date."
        exit 0
    fi
fi

chmod 0644 "$TEMP_FILE"
mv -f "$TEMP_FILE" "$TARGET"
TEMP_FILE=""
write_status "changed"

if [ "$RESTART_PBR" = "yes" ]; then
    if [ ! -x "$PBR_INIT_SCRIPT" ]; then
        log "PBR init script was not found: $PBR_INIT_SCRIPT"
        exit 1
    fi
    "$PBR_INIT_SCRIPT" restart
fi

log "updated $TARGET (sha256: $NEW_SHA256)"
