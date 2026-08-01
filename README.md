# pbr-russia

[![Update Russian domain list](https://github.com/Aleksan-S/pbr-russia/actions/workflows/update.yml/badge.svg)](https://github.com/Aleksan-S/pbr-russia/actions/workflows/update.yml)

An automatically maintained domain list for [OpenWrt Policy Based Routing](https://docs.openwrt.melmac.net/pbr/). The generator downloads the current [`v2fly/domain-list-community`](https://github.com/v2fly/domain-list-community) source, recursively resolves `category-ru`, merges local additions, validates and normalizes every domain, and writes a deterministic PBR-compatible list.

## What is included

`category-ru` is V2Fly's Russian-services aggregation. Resolving it recursively includes its Russian TLD, banking, government, ecommerce, entertainment, medicine, retail, travel, and company lists. `custom-domains.txt` is merged afterward for domains that have not reached upstream.

The parser accepts V2Fly `domain:` and `full:` rules, including the documented prefix-less shorthand for `domain:`. It removes attributes following `@`, ignores `regexp:`, `keyword:`, and unknown rules, converts internationalized names to IDNA, rejects invalid DNS labels, removes duplicates, and sorts the final output.

The generated file is [`output/russia-domains.txt`](output/russia-domains.txt).

## Generate locally

Python 3.12 or newer is required.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python update.py
```

On Windows, activate the environment with `.venv\Scripts\activate`.

Optional CLI arguments:

```text
--entry NAME       Resolve a different/additional V2Fly entry list (repeatable)
--custom PATH      Read local additions from another file
--output PATH      Write to another destination
--archive-url URL  Use another compatible source archive
--log-level LEVEL  DEBUG, INFO, WARNING, or ERROR
```

Add custom entries as bare domains, `domain:example.ru`, or `full:host.example.ru`. Comments and `@attributes` are accepted. Invalid or unsupported entries are logged and skipped.

## OpenWrt installation

The router must have the `pbr` package installed and configured. Run as root:

```sh
uclient-fetch -qO- https://raw.githubusercontent.com/Aleksan-S/pbr-russia/main/openwrt/install.sh | sh
```

The installer:

- downloads the current list to `/etc/pbr/russia-domains.txt`;
- installs the updater at `/usr/libexec/pbr-russia/update.sh`;
- ensures `curl` is installed, as PBR requires it for local `file://` sources;
- creates an idempotent `pbr.russia_domains` policy using `file:///etc/pbr/russia-domains.txt`;
- routes that policy through `wan` by default; and
- schedules a router-side refresh every Monday at 04:17.

To select another PBR interface, set it during installation:

```sh
PBR_INTERFACE=wg0 uclient-fetch -qO- https://raw.githubusercontent.com/Aleksan-S/pbr-russia/main/openwrt/install.sh | sh
```

Run an immediate update with:

```sh
/usr/libexec/pbr-russia/update.sh
```

The updater validates the download, replaces it atomically only when changed, and reloads PBR. Environment variables `PBR_RUSSIA_LIST_URL` and `PBR_RUSSIA_TARGET` can override its source and destination.

> The policy interface determines where matching Russian traffic is routed. Confirm that `wan` (or your override) matches your network design before installation.

## Automation

The GitHub Actions workflow runs every Monday at 03:00 UTC and can also be started manually. It runs Black, Ruff, and pytest, regenerates the list, and commits only when `output/russia-domains.txt` changed.

## Quality checks

```sh
black --check .
ruff check .
pytest
```

The downloader uses HTTPS, bounded downloads, retries, timeouts, archive path validation, and atomic output replacement. Unit tests cover recursive resolution, cycles, missing includes, supported and ignored rules, IDNA/domain validation, custom merging, deterministic output, and unsafe archives.

## License

This project is licensed under the [MIT License](LICENSE). The generated domain data originates from V2Fly's domain-list-community project; review its license and source history when redistributing derived data.
