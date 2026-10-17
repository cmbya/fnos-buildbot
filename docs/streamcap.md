# StreamCap native source build

The unified twice-daily updater tracks official ihmily/StreamCap releases,
resolves the tag commit SHA, and checks out that SHA in Actions. No per-app cron.

Native7 behavior is preserved from cmbya/StreamCap-fnOS. The patch is applied
at build time, fails on changed anchors/warnings, and is tested against real
patched methods with mock streams/recorders. Recovery dispatch ordering is fixed
so it no longer depends on a browser Page. Source changes are recorded in BUILD.json.

Python 3.12 standalone, Node 20 and FFmpeg/FFprobe archives are digest-pinned.
v1.0.3 Python constraints capture the successful CI resolution; all final wheel
hashes, resolved versions, runtime file hashes and source provenance are bundled.
New upstream versions resolve their requirements in Actions and must pass the
same compatibility gates. Upstream's Flet web payload comes from flet-web 0.85.0;
there is no separate npm frontend build.

Installation/upgrade is offline. appname streamcap, port 6006, native-runtime/
userdata/config, recordings and StreamCap-Logs paths are retained. Historical
source trees remain recovery backups. Persistent JSON files are migrated before
source replacement; no recording or config tree is deleted.

Acceptance runs relocated in clean bookworm-slim, nonroot, network none: imports,
JSON configuration initialization, repeated upgrades and sentinels, authorized
path, native tools/conversion, real patched timed-window behavior, HTTP Flet
bootstrap/manifest, start/status/stop and reaped server exit 0. Every ELF must be
x86_64 and require GLIBC <=2.36. Lifecycle executable modes and complete file
inventory are checked again inside the FPK.

Limitations: no real fnOS installation/upgrade, live-platform recording, or
interactive Flutter browser session was tested. Recording necessarily needs
network access; offline refers to deployment and bundled server/runtime. Flet
browser rendering may fetch renderer resources; this is not certified as a
fully air-gapped browser application. Use authorized recording paths only.
