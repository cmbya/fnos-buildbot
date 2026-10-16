"""Source build and isolated runtime verification (GitHub Actions only)."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import tarfile
import time
import urllib.request


def run(args, cwd, **kw):
    return subprocess.run(args, cwd=cwd, check=True, **kw)


def validate_elf(binary):
    hdr = binary.read_bytes()[:64]
    if hdr[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', hdr[18:20])[0] != 62:
        raise RuntimeError('Expected little-endian ELF64 x86_64')
    headers = subprocess.check_output(['readelf', '-l', str(binary)], text=True)
    dynamic = subprocess.check_output(['readelf', '-d', str(binary)], text=True)
    if 'INTERP' in headers or '(NEEDED)' in dynamic:
        raise RuntimeError('Unexpected dynamic runtime dependency')
    print('ELF64 amd64, no interpreter or DT_NEEDED', flush=True)


def smoke(binary, work):
    root = work / 'smoke'
    root.mkdir()
    (root / 'mounts').mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, LITEPAN_DATA_DIR=str(root / 'data'),
               LITEPAN_STRM_DIR=str(root / 'strm'), LITEPAN_LISTEN=f'127.0.0.1:{port}')
    with open(root / 'process.log', 'w+') as log:
        proc = subprocess.Popen([str(binary)], cwd=root, env=env, stdout=log, stderr=log)
        try:
            for _ in range(90):
                if proc.poll() is not None:
                    raise RuntimeError(f'LitePan exited {proc.returncode}')
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                        body = response.read().lower()
                        if response.status == 200 and b'<html' in body and (b'/assets/' in body):
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError('Web UI failed readiness check')
            if not (root / 'data/litepan.db').is_file():
                raise RuntimeError('No SQLite database in isolated data dir')
            print('SMOKE PASS: HTTP 200 embedded frontend, persistent SQLite initialized', flush=True)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=35)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise RuntimeError('Graceful shutdown timed out')
            log.seek(0)
            print(log.read())
        if proc.returncode != 0:
            raise RuntimeError(f'Graceful shutdown failed: {proc.returncode}')
    print('SMOKE PASS: graceful SIGTERM shutdown', flush=True)


def build_source(app, source, stage, work):
    if app['id'] == 'bililivetools':
        from build_bililive import build
        return build(app, source, stage, work)
    if app['id'] != 'litepan':
        raise RuntimeError('No source handler for this app')
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    if sha != app['source_sha']:
        raise RuntimeError('Source checkout does not match resolved tag SHA')
    env = dict(os.environ, CGO_ENABLED='0', GOOS='linux', GOARCH='amd64', GOTOOLCHAIN='local')
    run(['npm', 'ci'], source / 'web')
    run(['npm', 'run', 'type-check'], source / 'web')
    run(['npm', 'run', 'build'], source / 'web')
    binary = stage / app['binary_dest']
    binary.parent.mkdir(parents=True, exist_ok=True)
    run(['go', 'build', '-tags', 'fuse', '-trimpath', '-ldflags=-s -w', '-o', str(binary), './cmd/litepan'], source, env=env)
    binary.chmod(0o755)
    validate_elf(binary)
    smoke(binary, work)
    shutil.copy2(source / 'LICENSE', stage / 'LICENSE')
    metadata = {'repo': app['upstream_repo'], 'tag': app['tag'], 'commit': sha,
                'version': app['version'], 'cgo': False, 'tags': ['fuse'],
                'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()}
    (stage / 'app/native/BUILD.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # Exercise the actual offline installer twice against an old runtime/data tree.
    pkgvar = work / 'upgrade-test'
    (pkgvar / 'data').mkdir(parents=True)
    (pkgvar / 'runtime').mkdir()
    (pkgvar / 'data/sentinel').write_text('keep')
    (pkgvar / 'runtime/litepan').write_text('old binary')
    install_env = dict(os.environ, TRIM_APPDEST=str(stage / 'app'), TRIM_PKGVAR=str(pkgvar))
    for _ in range(2):
        run(['bash', str(stage / 'app/native/install.sh')], work, env=install_env)
    if (pkgvar / 'data/sentinel').read_text() != 'keep' or (pkgvar / 'runtime/litepan').read_bytes() != binary.read_bytes():
        raise RuntimeError('Offline upgrade preservation check failed')
    print('Offline install/upgrade idempotence and data preservation verified', flush=True)
    print('Source provenance:', json.dumps(metadata), flush=True)


def verify_embedded(out, app):
    with tarfile.open(out, 'r:gz') as package:
        members = {m.name.removeprefix('./'): m for m in package.getmembers()}
        for name, member in members.items():
            if name.startswith('cmd/') and member.isfile() and not member.mode & 0o111:
                raise RuntimeError(f'Lifecycle script is not executable: {name}')
        with tarfile.open(fileobj=io.BytesIO(package.extractfile(members['app.tgz']).read()), mode='r:gz') as payload:
            files = {m.name.removeprefix('./'): m for m in payload.getmembers()}
            binary = files[app['binary_dest'].removeprefix('app/')]
            meta = json.load(payload.extractfile(files['native/BUILD.json']))
            if not binary.mode & 0o111 or hashlib.sha256(payload.extractfile(binary).read()).hexdigest() != meta['binary_sha256']:
                raise RuntimeError('Embedded executable checksum/mode mismatch')
            if meta['commit'] != app['source_sha'] or meta['version'] != app['version']:
                raise RuntimeError('Embedded source provenance mismatch')
    print('FPK embedded binary SHA256 and fixed-tag provenance verified', flush=True)
