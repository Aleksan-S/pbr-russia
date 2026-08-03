#!/bin/sh

set -eu

DEFAULT_RELEASE_BASE="https://github.com/Aleksan-S/pbr-russia/releases/latest/download"
RELEASE_BASE="${PBR_RUSSIA_RELEASE_BASE:-$DEFAULT_RELEASE_BASE}"
if [ -n "${PBR_RUSSIA_RAW_BASE:-}" ]; then
    DEFAULT_UPDATE_URL="${PBR_RUSSIA_RAW_BASE%/}/openwrt/update.sh"
    DEFAULT_CHECKSUMS_URL="${PBR_RUSSIA_RAW_BASE%/}/output/SHA256SUMS"
else
    DEFAULT_UPDATE_URL="${RELEASE_BASE%/}/update.sh"
    DEFAULT_CHECKSUMS_URL="${RELEASE_BASE%/}/SHA256SUMS"
fi
UPDATE_URL="${PBR_RUSSIA_UPDATE_URL:-$DEFAULT_UPDATE_URL}"
CHECKSUMS_URL="${PBR_RUSSIA_CHECKSUMS_URL:-$DEFAULT_CHECKSUMS_URL}"
PBR_INTERFACE="${PBR_INTERFACE:-wan}"
INSTALL_CRON="${INSTALL_CRON:-no}"
ETC_DIR="${PBR_RUSSIA_ETC_DIR:-/etc}"
INSTALL_DIR="${PBR_RUSSIA_INSTALL_DIR:-/usr/libexec/pbr-russia}"
UPDATE_SCRIPT="$INSTALL_DIR/update.sh"
DOMAIN_FILE="${PBR_RUSSIA_TARGET:-$ETC_DIR/pbr/russia-domains.txt}"
PBR_CONFIG="$ETC_DIR/config/pbr"
PBR_INIT_SCRIPT="${PBR_INIT_SCRIPT:-$ETC_DIR/init.d/pbr}"
CRON_INIT_SCRIPT="${CRON_INIT_SCRIPT:-$ETC_DIR/init.d/cron}"
CRON_FILE="${PBR_RUSSIA_CRON_FILE:-$ETC_DIR/crontabs/root}"
CRON_ENTRY="30 4 * * 1 $UPDATE_SCRIPT"
SKIP_ROOT_CHECK="${PBR_RUSSIA_SKIP_ROOT_CHECK:-no}"
CONFIG_CHANGED=0
CRON_CHANGED=0
FILE_STATUS="unchanged"
TEMP_SCRIPT=""
TEMP_CHECKSUMS=""
TEMP_CRON=""
STATUS_FILE=""

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
    [ -z "$TEMP_SCRIPT" ] || rm -f "$TEMP_SCRIPT"
    [ -z "$TEMP_CHECKSUMS" ] || rm -f "$TEMP_CHECKSUMS"
    [ -z "$TEMP_CRON" ] || rm -f "$TEMP_CRON"
    [ -z "$STATUS_FILE" ] || rm -f "$STATUS_FILE"
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

verify_checksum() {
    file=$1
    asset_name=$2
    manifest=$3
    expected=$(checksum_for "$asset_name" "$manifest") || {
        log "checksum manifest has no unique valid entry for $asset_name"
        return 1
    }
    actual=$(sha256sum "$file" | awk '{print tolower($1)}')
    if [ "$actual" != "$expected" ]; then
        log "SHA-256 verification failed for $asset_name"
        return 1
    fi
}

ensure_curl() {
    if command -v curl >/dev/null 2>&1; then
        return 0
    fi

    log "installing curl, which PBR requires for file:// policy sources"
    if command -v apk >/dev/null 2>&1; then
        apk update
        apk add curl
    elif command -v opkg >/dev/null 2>&1; then
        opkg update
        opkg install curl
    else
        log "cannot install curl: neither apk nor opkg was found"
        return 1
    fi
    command -v curl >/dev/null 2>&1
}

set_uci_value() {
    key=$1
    desired=$2
    current=$(uci -q get "$key" 2>/dev/null || true)
    if [ "$current" != "$desired" ]; then
        uci set "$key=$desired"
        CONFIG_CHANGED=1
    fi
}

configure_cron() {
    mkdir -p "$(dirname "$CRON_FILE")"
    touch "$CRON_FILE"
    TEMP_CRON=$(mktemp "$(dirname "$CRON_FILE")/.pbr-russia-cron.XXXXXX")
    awk -v updater="$UPDATE_SCRIPT" 'index($0, updater) == 0' "$CRON_FILE" >"$TEMP_CRON"
    if [ "$INSTALL_CRON" = "yes" ]; then
        printf '%s\n' "$CRON_ENTRY" >>"$TEMP_CRON"
    fi

    if ! cmp -s "$TEMP_CRON" "$CRON_FILE"; then
        mv -f "$TEMP_CRON" "$CRON_FILE"
        TEMP_CRON=""
        CRON_CHANGED=1
    fi
}

trap cleanup EXIT HUP INT TERM

case "$INSTALL_CRON" in
    yes | no) ;;
    *)
        log "INSTALL_CRON must be 'yes' or 'no'"
        exit 2
        ;;
esac

if [ "$SKIP_ROOT_CHECK" != "yes" ] && [ "$(id -u)" -ne 0 ]; then
    log "must be run as root"
    exit 1
fi

command -v uci >/dev/null 2>&1 || {
    log "uci is required"
    exit 1
}
if [ ! -f "$PBR_CONFIG" ] || [ ! -x "$PBR_INIT_SCRIPT" ]; then
    log "the OpenWrt pbr package is not installed"
    exit 1
fi
if ! command -v dnsmasq >/dev/null 2>&1 ||
    ! dnsmasq --version 2>&1 | grep -qw nftset; then
    log "dnsmasq nftset support is required (install dnsmasq-full)"
    exit 1
fi

ensure_curl

command -v sha256sum >/dev/null 2>&1 || {
    log "sha256sum is required"
    exit 1
}

mkdir -p "$INSTALL_DIR" "$(dirname "$DOMAIN_FILE")"
TEMP_SCRIPT=$(mktemp "$INSTALL_DIR/.update.XXXXXX")
TEMP_CHECKSUMS=$(mktemp "$INSTALL_DIR/.checksums.XXXXXX")
download "$CHECKSUMS_URL" "$TEMP_CHECKSUMS"
download "$UPDATE_URL" "$TEMP_SCRIPT"
verify_checksum "$TEMP_SCRIPT" "update.sh" "$TEMP_CHECKSUMS"
rm -f "$TEMP_CHECKSUMS"
TEMP_CHECKSUMS=""
chmod 0755 "$TEMP_SCRIPT"
if [ ! -f "$UPDATE_SCRIPT" ] || ! cmp -s "$TEMP_SCRIPT" "$UPDATE_SCRIPT"; then
    mv -f "$TEMP_SCRIPT" "$UPDATE_SCRIPT"
    TEMP_SCRIPT=""
else
    rm -f "$TEMP_SCRIPT"
    TEMP_SCRIPT=""
fi

set_uci_value pbr.russia_domains policy
set_uci_value pbr.russia_domains.name "Russian domains"
set_uci_value pbr.russia_domains.interface "$PBR_INTERFACE"
set_uci_value pbr.russia_domains.dest_addr "file://$DOMAIN_FILE"
set_uci_value pbr.russia_domains.enabled 1
set_uci_value pbr.config.enabled 1
set_uci_value pbr.config.resolver_set dnsmasq.nftset
if [ "$CONFIG_CHANGED" -eq 1 ]; then
    uci commit pbr
fi

configure_cron
if [ "$CRON_CHANGED" -eq 1 ] && [ -x "$CRON_INIT_SCRIPT" ]; then
    "$CRON_INIT_SCRIPT" restart
fi

STATUS_FILE=$(mktemp "$INSTALL_DIR/.status.XXXXXX")
PBR_RUSSIA_TARGET="$DOMAIN_FILE" \
PBR_INIT_SCRIPT="$PBR_INIT_SCRIPT" \
PBR_RUSSIA_RESTART=no \
PBR_RUSSIA_STATUS_FILE="$STATUS_FILE" \
PBR_RUSSIA_SKIP_ROOT_CHECK="$SKIP_ROOT_CHECK" \
    "$UPDATE_SCRIPT"
if [ -s "$STATUS_FILE" ]; then
    FILE_STATUS=$(sed -n '1p' "$STATUS_FILE")
fi

if [ "$CONFIG_CHANGED" -eq 1 ] || [ "$FILE_STATUS" = "changed" ]; then
    "$PBR_INIT_SCRIPT" restart
fi

log "installed using interface '$PBR_INTERFACE'"
log "PBR source: file://$DOMAIN_FILE"
log "resolver: dnsmasq.nftset; weekly cron: $INSTALL_CRON"
