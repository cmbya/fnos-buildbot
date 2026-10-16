#!/bin/bash
# Offline atomic replacement. Never remove or relocate persistent user data.
set -euo pipefail
RUNTIME="${TRIM_PKGVAR:?}/runtime"
SOURCE="${TRIM_APPDEST:?}/native/litepan"
[ -x "$SOURCE" ] || { echo 'Bundled LitePan missing'; exit 1; }
mkdir -p "$RUNTIME" "${TRIM_PKGVAR}/data"
install -m 0755 "$SOURCE" "$RUNTIME/litepan.new"
mv -f "$RUNTIME/litepan.new" "$RUNTIME/litepan"
install -m 0644 "${TRIM_APPDEST}/native/BUILD.json" "$RUNTIME/BUILD.json"
echo 'Bundled LitePan installed; data, strm and mounts preserved.'
