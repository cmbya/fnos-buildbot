#!/bin/bash
set -u
RUNTIME="${TRIM_PKGVAR}/native-runtime"
# Native wrapper replaces Docker gosu/tini only; business source is unchanged.
# Do not run nightly pip upgrades: this package is a lockfile-based offline bundle.
unset YTDL_NIGHTLY_UPDATE_TIME
bgutil-pot server >> "${TRIM_PKGVAR}/bgutil-pot.log" 2>&1 &
pot=$!
"$RUNTIME/python/bin/python3.14" app/main.py &
app=$!
cleanup(){ kill -TERM "$app" "$pot" 2>/dev/null || true; wait "$app"; code=$?; wait "$pot" 2>/dev/null || true; echo "MeTube shutdown exit=$code"; }
trap 'cleanup; exit 0' TERM INT
wait "$app"
result=$?
kill -TERM "$pot" 2>/dev/null || true
wait "$pot" 2>/dev/null || true
exit "$result"
