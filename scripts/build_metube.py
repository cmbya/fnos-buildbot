"""Fixed-source MeTube build. All builds/probes run in Actions containers."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request
import urllib.parse
import zipfile

NODE = 'node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32'
# Release assets are pinned, verified before extracting, and recorded in BUILD.json.
TOOLS = {
    'python': ('astral-sh/python-build-standalone', '20261013', 'cpython-3.14.8+20261013-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz', 'd8faa1b588506b9e3e5a3f57807bb056d534a1641a6b10d15b6ea3f0b413b960'),
    'uv': ('astral-sh/uv', '0.13.1', 'uv-x86_64-unknown-linux-gnu.tar.gz', 'eadd9d27c134ab5ac1ffd4473b97a741407f3ea238288f03121fc4deddf90220'),
    'deno': ('denoland/deno', 'v2.9.7', 'deno-x86_64-unknown-linux-gnu.zip', 'c6527f24f4b16031d3ae4fa9f658d5f11534c8d84ce7dc8502420280919c3490'),
    'ffmpeg': ('BtbN/FFmpeg-Builds', 'autobuild-2026-10-16-13-04', 'ffmpeg-n8.1.3-18-g46d899d7a0-linux64-gpl-8.1.tar.xz', 'c19bd7fec94e0c56032fad4f20bf56b2847f18fbe372c758b32ed10d4dec2176'),
    'bgutil': ('jim60105/bgutil-ytdlp-pot-provider-rs', 'v0.8.1', 'bgutil-pot-linux-x86_64', 'e7c264a574fa2705b6e5dc62283a8a4e80130f27b9d7e9df44e6b09aa6151a87'),
    'plugin': ('jim60105/bgutil-ytdlp-pot-provider-rs', 'v0.8.1', 'bgutil-ytdlp-pot-provider-rs.zip', '99fd83b98fa93b193d6a3b69dc74410d76e7a2b889868c54d16121cac9060344'),
}


def run(args, **kw):
    print('RUN', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kw)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def fetch(key, work):
    repo, tag, name, digest = TOOLS[key]
    url = f'https://github.com/{repo}/releases/download/{tag}/{urllib.parse.quote(name)}'
    dst = work / name
    run(['curl', '--fail', '--location', '--retry', '5', '--output', dst, url])
    if sha(dst) != digest:
        raise RuntimeError(f'{key} SHA256 mismatch')
    print('VERIFIED', key, digest, flush=True)
    return dst


def backend(source, bundle, work):
    bundle.mkdir(parents=True)
    (bundle / 'bin').mkdir()
    (bundle / 'licenses').mkdir()
    with tarfile.open(fetch('python', work)) as tf:
        tf.extractall(bundle)
    py = bundle / 'python/bin/python3.14'
    with tarfile.open(fetch('uv', work)) as tf:
        member = next(m for m in tf.getmembers() if m.name.endswith('/uv'))
        uv = work / 'uv'
        uv.write_bytes(tf.extractfile(member).read())
        uv.chmod(0o755)
    requirements = work / 'requirements.txt'
    run([uv, 'export', '--frozen', '--no-dev', '--no-emit-project', '--output-file', requirements], cwd=source)
    run([uv, 'pip', 'install', '--python', py, '--require-hashes', '-r', requirements], cwd=source)
    shutil.copy2(requirements, bundle / 'requirements.txt')
    shutil.copytree(source / 'app', bundle / 'source/app', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(source / 'ui/dist/metube', bundle / 'source/ui/dist/metube')
    for name in ['pyproject.toml', 'uv.lock', 'LICENSE']:
        shutil.copy2(source / name, bundle / 'source' / name)
    site = bundle / 'python/lib/python3.14/site-packages'
    with zipfile.ZipFile(fetch('plugin', work)) as z:
        z.extractall(site)
    with zipfile.ZipFile(fetch('deno', work)) as z:
        (bundle / 'bin/deno').write_bytes(z.read('deno'))
    shutil.copy2(fetch('bgutil', work), bundle / 'bin/bgutil-pot')
    with tarfile.open(fetch('ffmpeg', work)) as tf:
        for name in ['ffmpeg', 'ffprobe']:
            m = next(m for m in tf.getmembers() if m.name.endswith('/bin/' + name))
            (bundle / 'bin' / name).write_bytes(tf.extractfile(m).read())
        for m in tf.getmembers():
            if m.isfile() and ('license' in m.name.lower() or 'readme' in m.name.lower()):
                (bundle / 'licenses' / Path(m.name).name).write_bytes(tf.extractfile(m).read())
    for key, repo, tag, name in [('deno', 'denoland/deno', 'v2.9.7', 'LICENSE.md'), ('bgutil', 'jim60105/bgutil-ytdlp-pot-provider-rs', 'v0.8.1', 'LICENSE')]:
        run(['curl', '-fL', '--retry', '4', '-o', bundle / 'licenses' / (key + '-LICENSE'), f'https://raw.githubusercontent.com/{repo}/{tag}/{name}'])
    (bundle / 'licenses/NOTICE').write_text('MeTube source is unmodified. Python standalone includes its own licenses; Python dependencies retain dist-info licenses. Deno MIT; bgutil and FFmpeg GPL-3.0. See BUILD.json for fixed source/archive URLs and SHA256. FFmpeg 8.1 replaces legacy 7.0.2 per upstream HLS clip fix #1092. Optional aria2 external downloader is not bundled.\n')
    for p in (bundle / 'bin').iterdir():
        p.chmod(0o755)
    # Remove generated absolute shebang entrypoints; launch only python -m / Python scripts.
    for p in (bundle / 'python/bin').iterdir():
        if p.is_file() and p.read_bytes()[:2] == b'#!':
            p.unlink()
    # No absolute symlinks or unresolved dependencies are allowed.
    for p in bundle.rglob('*'):
        if p.is_symlink() and (os.path.isabs(os.readlink(p)) or not p.exists()):
            raise RuntimeError(f'Non-relocatable symlink {p}')
    max_glibc = (0, 0)
    count = 0
    for p in bundle.rglob('*'):
        if not p.is_file() or p.is_symlink():
            continue
        with p.open('rb') as f:
            header = f.read(64)
        if not header.startswith(b'\x7fELF'):
            continue
        count += 1
        if header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != 62:
            raise RuntimeError(f'Wrong ELF architecture: {p}')
        text = subprocess.check_output(['readelf', '--version-info', p], text=True)
        versions = [tuple(map(int, v.split('.'))) for v in re.findall(r'GLIBC_(\d+\.\d+)', text)]
        max_glibc = max([max_glibc] + versions)
        if versions and max(versions) > (2, 36):
            raise RuntimeError(f'GLIBC baseline exceeds bookworm: {p}: {max(versions)}')
        result = subprocess.run(['ldd', p], capture_output=True, text=True)
        if 'not found' in result.stdout + result.stderr:
            raise RuntimeError(f'Unresolved ELF dependency {p}: {result.stdout} {result.stderr}')
    print(f'ELF PASS: {count} x86_64 files; max GLIBC {max_glibc}; ldd closure on clean bookworm', flush=True)


def probe(stage, work):
    # Called in a fresh --network none bookworm container, no apt/build dependencies.
    work.mkdir(parents=True, exist_ok=True)
    pkgvar = work / 'pkgvar'
    state = pkgvar / 'native-runtime/state'
    home = pkgvar / 'native-runtime/home'
    downloads = work / 'downloads'
    authorized = work / 'authorized'
    for d in [state, home, downloads, authorized]:
        d.mkdir(parents=True, exist_ok=True)
        (d / 'sentinel').write_text('preserve')
    (home / 'settings.json').write_text('{"existing":true}')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, TRIM_APPDEST=str(stage / 'app'), TRIM_PKGVAR=str(pkgvar), TRIM_DATA_SHARE_PATHS=str(downloads), TRIM_DATA_ACCESSIBLE_PATHS=str(authorized), TRIM_SERVICE_PORT=str(port), TRIM_TEMP_LOGFILE=str(work / 'error.log'))
    for name in ['install_callback', 'upgrade_callback', 'upgrade_callback']:
        run(['bash', stage / 'cmd' / name], env=env)
    for d in [state, home, downloads, authorized]:
        assert (d / 'sentinel').read_text() == 'preserve'
    assert (home / 'settings.json').read_text() == '{"existing":true}'
    py = pkgvar / 'native-runtime/python/bin/python3.14'
    run([py, '-c', 'import ssl,sqlite3,aiohttp,socketio,yt_dlp,mutagen,curl_cffi,watchfiles; import yt_dlp_plugins.extractor.getpot_bgutil; print("Python ABI/imports PASS")'])
    tools = pkgvar / 'native-runtime/bin'
    run([tools / 'deno', '--version'])
    run([tools / 'ffmpeg', '-version'])
    run([tools / 'ffprobe', '-version'])
    run([tools / 'ffmpeg', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2', work / 'test.wav'])
    run([tools / 'ffprobe', '-v', 'error', '-show_entries', 'format=duration', work / 'test.wav'])
    try:
        run(['bash', stage / 'cmd/main', 'start'], env=env)
        run(['bash', stage / 'cmd/main', 'status'], env=env)
        for path in ['/', '/version', '/history', '/subscriptions', '/cookie-status']:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
                data = response.read()
                assert response.status == 200
                if path == '/':
                    assert b'<html' in data.lower() and b'.js' in data
                else:
                    json.loads(data)
                print('HTTP PASS', path, response.status, len(data), flush=True)
        assert list(state.iterdir()) != [state / 'sentinel']
        text = (pkgvar / 'metube.log').read_text()
        assert str(authorized) in text
        print('STATE PASS', [p.name for p in state.iterdir()], flush=True)
    finally:
        run(['bash', stage / 'cmd/main', 'stop'], env=env)
        print((pkgvar / 'metube.log').read_text() if (pkgvar / 'metube.log').exists() else 'no log', flush=True)
        print((pkgvar / 'bgutil-pot.log').read_text() if (pkgvar / 'bgutil-pot.log').exists() else 'no provider log', flush=True)
    result = subprocess.run(['bash', stage / 'cmd/main', 'status'], env=env)
    assert result.returncode == 3
    with socket.socket() as sock:
        assert sock.connect_ex(('127.0.0.1', port)) != 0
    print('OFFLINE PASS: repeated install/upgrade preserves state/settings/downloads; lifecycle start/status/stop, authorized path, HTTP UI/APIs; clean stop', flush=True)


def build(app, source, stage, work):
    source = source.resolve()
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    assert actual == app['source_sha']
    assert re.fullmatch(r'\d{4}\.\d{2}\.\d{2}', app['tag'])
    dockerfile = (source / 'Dockerfile').read_text()
    assert NODE in dockerfile and 'python:3.14-slim' in dockerfile and 'FFMPEG_BRANCH=8.1' in dockerfile
    # Use the official fixed builder digest and the project's packageManager/lockfile.
    run(['docker', 'run', '--rm', '-v', f'{source}:/metube', '-w', '/metube/ui', NODE, 'sh', '-ec', 'corepack enable; corepack prepare pnpm@12.6.0 --activate; CI=true pnpm install --frozen-lockfile; pnpm run build'])
    assert (source / 'ui/dist/metube/browser/index.html').is_file()
    bundle = stage / 'app/native/bundle'
    script = Path(__file__).resolve()
    run(['docker', 'run', '--rm', '-v', f'{script.parent}:/scripts:ro', '-v', f'{source}:/source:ro', '-v', f'{stage}:/stage', '-v', f'{work}:/build', 'debian:bookworm-slim', 'bash', '-euc', 'apt-get update -qq; apt-get install -y -qq python3 curl ca-certificates binutils xz-utils; python3 /scripts/build_metube.py backend /source /stage/app/native/bundle /build'])
    (bundle / 'VERSION').write_text(app['version'] + '\n')
    # Keep only offline wrappers in the package; old network bootstrap is reference only.
    (stage / 'app/native/bootstrap.py').unlink()
    binary = stage / app['binary_dest']
    metadata = {'repo': app['upstream_repo'], 'tag': app['tag'], 'commit': actual, 'version': app['version'], 'binary_sha256': sha(binary), 'node_builder': NODE, 'glibc_baseline_max': '2.36', 'source_modified': False, 'tools': {k: dict(zip(['repo', 'tag', 'asset', 'sha256'], v)) for k, v in TOOLS.items()}, 'locks': {p: sha(source / p) for p in ['uv.lock', 'pyproject.toml', 'ui/pnpm-lock.yaml', 'ui/package.json']}}
    (stage / 'app/native/BUILD.json').write_text(json.dumps(metadata, indent=2) + '\n')
    for p in (stage / 'cmd').iterdir():
        p.chmod(0o755)
    (stage / 'app/native/serve.sh').chmod(0o755)
    # Prove relocation: copied app tree, fresh container, disabled external network.
    relocated = work / 'relocated'
    shutil.copytree(stage, relocated, symlinks=True)

    # Embedded Python runs the probe itself, not a runner/system interpreter.
    run(['docker', 'run', '--rm', '--network', 'none', '-v', f'{script.parent}:/scripts:ro', '-v', f'{relocated}:/relocated:ro', '-v', f'{work}:/test', 'debian:bookworm-slim', '/relocated/app/native/bundle/python/bin/python3.14', '/scripts/build_metube.py', 'probe', '/relocated', '/test/offline'])
    changed = subprocess.check_output(['git', 'diff', '--name-only'], cwd=source, text=True).strip()
    assert not changed, f'Upstream tracked source modified: {changed}'
    shutil.copy2(source / 'LICENSE', stage / 'LICENSE')
    print('MeTube provenance:', json.dumps(metadata), flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'backend':
        backend(*map(Path, sys.argv[2:]))
    elif sys.argv[1] == 'probe':
        probe(*map(Path, sys.argv[2:]))
