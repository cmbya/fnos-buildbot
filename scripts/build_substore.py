#!/usr/bin/env python3
"""Package official Sub-Store release assets; no npm installs or NAS-time downloads."""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


def checked_download(release, name, dest, token):
    from build_app import http_get, digest_of
    matches = [a for a in release['assets'] if a['name'] == name]
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one asset: {name}')
    asset = matches[0]
    expected = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected):
        raise RuntimeError(f'Missing/invalid upstream SHA256: {name}')
    http_get(asset['browser_download_url'], dest, token)
    actual = digest_of(dest, 'sha256')
    if dest.stat().st_size != asset['size'] or expected != f'sha256:{actual}':
        raise RuntimeError(f'Asset integrity check failed: {name}')
    return {'name': name, 'sha256': actual, 'url': asset['browser_download_url']}


def patch_frontend(www):
    """Fail closed on layout change; keep gzip and Workbox hashes in sync."""
    pattern = re.compile(r'(\b[A-Za-z_$][\w$]*=)(["\'])https://sub\.store\2(?=,)')
    candidates = []
    for path in www.rglob('*.js'):
        text = path.read_text()
        for match in pattern.finditer(text):
            candidates.append((path, text, match))
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one frontend default API constant, got {len(candidates)}')
    path, text, match = candidates[0]
    old = path.read_bytes()
    replacement = match.group(1) + match.group(2) + '/path' + match.group(2)
    new = (text[:match.start()] + replacement + text[match.end():]).encode()
    path.write_bytes(new)
    gz = path.with_suffix(path.suffix + '.gz')
    if gz.exists():
        gz.write_bytes(gzip.compress(new, mtime=0))
    sw = www / 'sw.js'
    if sw.exists():
        source = sw.read_text()
        rel = path.relative_to(www).as_posix()
        rx = re.compile(r'(\{url:["\']/?' + re.escape(rel) + r'["\'],revision:["\'])([0-9a-f]+)(["\']\})')
        source, count = rx.subn(lambda m: m[1] + hashlib.md5(new).hexdigest() + m[3], source)
        if count != 1:
            raise RuntimeError('Cannot update frontend Workbox precache entry')
        sw.write_text(source)
        swgz = www / 'sw.js.gz'
        if swgz.exists():
            swgz.write_bytes(gzip.compress(sw.read_bytes(), mtime=0))
    return {'file': path.relative_to(www).as_posix(), 'original_sha256': hashlib.sha256(old).hexdigest(),
            'patched_sha256': hashlib.sha256(new).hexdigest(), 'default_api': '/path'}


def unpack_frontend(archive, www):
    www.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            p = PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] != 'dist':
                raise RuntimeError(f'Unexpected frontend archive path: {item.filename}')
            if item.is_dir():
                continue
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError('Frontend archive symlinks are not allowed')
            dst = www.joinpath(*p.parts[1:])
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(item))
    if not (www / 'index.html').is_file():
        raise RuntimeError('Frontend index.html missing')


def build(app, version, tag, stage, work, token):
    from build_app import fetch_release, http_get
    from check_upstream import latest_release
    frontend_repo = app['frontend_repo']
    frontend_tag = app.get('frontend_tag') or latest_release(frontend_repo, '', token)[0]
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', frontend_tag):
        raise RuntimeError('Invalid frontend release tag')
    backend = fetch_release(app['upstream_repo'], tag, token)
    frontend = fetch_release(frontend_repo, frontend_tag, token)
    for release in (backend, frontend):
        if release.get('draft') or release.get('prerelease'):
            raise RuntimeError('Only official stable releases are accepted')
    server = stage / 'app/server'
    server.mkdir(parents=True, exist_ok=True)
    be = checked_download(backend, 'sub-store.bundle.js', server / 'sub-store.bundle.js', token)
    head = (server / 'sub-store.bundle.js').read_text()[:300]
    if f'SUB_STORE_BACKEND_VERSION: {version}' not in head:
        raise RuntimeError('Backend bundle version does not match release')
    fe = checked_download(frontend, 'dist.zip', work / 'dist.zip', token)
    www = stage / 'app/www'
    unpack_frontend(work / 'dist.zip', www)
    patch = patch_frontend(www)
    # Preserve the exact release-tag component licenses.
    for repo, release_tag, dest in [(app['upstream_repo'], tag, server / 'LICENSE'),
                                     (frontend_repo, frontend_tag, www / 'LICENSE')]:
        http_get(f'https://raw.githubusercontent.com/{repo}/{release_tag}/LICENSE', dest, None)
        expected_license = ('GNU AFFERO GENERAL PUBLIC LICENSE' if repo == app['upstream_repo']
                            else 'GNU GENERAL PUBLIC LICENSE')
        if expected_license not in dest.read_text():
            raise RuntimeError(f'Unexpected upstream license: {repo}')
    shutil.copy2(server / 'LICENSE', stage / 'LICENSE')
    sources = (f'Backend source: https://github.com/{app["upstream_repo"]}/tree/{tag}\n'
               f'Frontend source: https://github.com/{frontend_repo}/tree/{frontend_tag}\n'
               'Packaging and frontend patch: https://github.com/cmbya/fnos-buildbot\n'
               'Backend: AGPL-3.0; frontend: GPL-3.0. Frontend default API changed to /path.\n')
    (stage / 'app/SOURCES.txt').write_text(sources)
    (www / 'SOURCES.txt').write_text(sources)
    (stage / 'app/BUILD.json').write_text(json.dumps({
        'backend_tag': tag, 'frontend_tag': frontend_tag,
        'backend_asset': be, 'frontend_asset': fe, 'frontend_patch': patch,
    }, indent=2) + '\n')
    print(f'[substore] backend={tag}, frontend={frontend_tag}, checked SHA256; patched {patch["file"]}')
