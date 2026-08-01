#!/bin/sh

set -eu

RAW_BASE="${PBR_RUSSIA_RAW_BASE:-https://raw.githubusercontent.com/Aleksan-S/pbr-russia/main}"
PBR_INTERFACE="${PBR_INTERFACE:-wan}"
INSTALL_DIR="/usr/libexec/pbr-russia"
UPDATE_SCRIPT="$INSTALL_DIR/update.sh"
DOMAIN_FILE="/etc/pbr/russia-domains.txt"
CRON_FILE="/etc/crontabs/root"
CRON_ENTRY="17 4 * * 1 $UPDATE_SCRIPT"

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

    command -v curl >/dev/null 2>&1 || {
        log "curl installation did not provide a usable command"
        return 1
    }
}

[ "$(id -u)" -eq 0 ] || {
    log "must be run as root"
    exit 1
}

command -v uci >/dev/null 2>&1 || {
    log "uci is required"
    exit 1
}

if [ ! -f /etc/config/pbr ]; then
    log "the OpenWrt pbr package is not installed"
    exit 1
fi

ensure_curl

mkdir -p "$INSTALL_DIR" /etc/pbr
TEMP_SCRIPT=$(mktemp "$INSTALL_DIR/.update.XXXXXX")
trap 'rm -f "$TEMP_SCRIPT"' EXIT HUP INT TERM
download "$RAW_BASE/openwrt/update.sh" "$TEMP_SCRIPT"
chmod 0755 "$TEMP_SCRIPT"
mv -f "$TEMP_SCRIPT" "$UPDATE_SCRIPT"
TEMP_SCRIPT=""
trap - EXIT HUP INT TERM

PBR_RUSSIA_TARGET="$DOMAIN_FILE" "$UPDATE_SCRIPT"

uci -q delete pbr.russia_domains || true
uci set pbr.russia_domains='policy'
uci set pbr.russia_domains.name='Russian domains'
uci set pbr.russia_domains.interface="$PBR_INTERFACE"
uci set pbr.russia_domains.dest_addr="file://$DOMAIN_FILE"
uci set pbr.russia_domains.enabled='1'
uci set pbr.config.enabled='1'
uci commit pbr

touch "$CRON_FILE"
if ! grep -Fqx "$CRON_ENTRY" "$CRON_FILE"; then
    printf '%s\n' "$CRON_ENTRY" >>"$CRON_FILE"
fi

/etc/init.d/cron restart
/etc/init.d/pbr restart

log "installed using interface '$PBR_INTERFACE'"
log "PBR source: file://$DOMAIN_FILE"
