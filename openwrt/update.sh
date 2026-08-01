#!/bin/sh

set -eu

LIST_URL="${PBR_RUSSIA_LIST_URL:-https://raw.githubusercontent.com/Aleksan-S/pbr-russia/main/output/russia-domains.txt}"
TARGET="${PBR_RUSSIA_TARGET:-/etc/pbr/russia-domains.txt}"
TARGET_DIR=$(dirname "$TARGET")
TEMP_FILE=""

log() {
    printf '%s\n' "pbr-russia: $*"
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
}

trap cleanup EXIT HUP INT TERM

[ "$(id -u)" -eq 0 ] || {
    log "must be run as root"
    exit 1
}

mkdir -p "$TARGET_DIR"
TEMP_FILE=$(mktemp "$TARGET_DIR/.russia-domains.XXXXXX")
download "$LIST_URL" "$TEMP_FILE"

if [ ! -s "$TEMP_FILE" ]; then
    log "downloaded list is empty"
    exit 1
fi

if ! awk '
    {
        if (length($0) > 253 || $0 !~ /^[a-z0-9.-]+$/ || $0 ~ /\.\./) {
            exit 1
        }
        count = split($0, labels, ".")
        for (index = 1; index <= count; index++) {
            if (length(labels[index]) > 63 ||
                labels[index] !~ /^[a-z0-9]/ ||
                labels[index] !~ /[a-z0-9]$/) {
                exit 1
            }
        }
    }
    END { if (NR == 0) exit 1 }
' "$TEMP_FILE"; then
    log "downloaded list contains an invalid domain"
    exit 1
fi

if [ -f "$TARGET" ] && cmp -s "$TEMP_FILE" "$TARGET"; then
    log "domain list is already current"
    exit 0
fi

chmod 0644 "$TEMP_FILE"
mv -f "$TEMP_FILE" "$TARGET"
TEMP_FILE=""

if [ -x /etc/init.d/pbr ]; then
    /etc/init.d/pbr reload
else
    log "PBR init script was not found; list updated without reload"
    exit 1
fi

log "updated $TARGET and reloaded PBR"
