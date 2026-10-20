"""Ekko npm runtime assembly and isolated checks; executed in Actions Debian 12."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request


def build(app, version, stage, work):
    node_version = app['node_version']
    filename = f'node-v{node_version}-linux-x64.tar.xz'
    base = f'https://nodejs.org/dist/v{node_version}/'
    archive = work / filename
    urllib.request.urlretrieve(base + filename, archive)
    with urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60) as response:
        sums = response.read().decode().splitlines()
    expected = next(line.split()[0] for line in sums if line.split()[-1] == filename)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('Node archive SHA256 mismatch')
    # Debian 12's Python 3.11 tarfile lacks the filter keyword; the archive
    # is authenticated above against Node's official SHA256 inventory.
    download = work / 'node-download'
    download.mkdir()
    subprocess.run(['tar', '-xJf', str(archive), '-C', str(download)], check=True)
    shutil.move(str(work / 'node-download' / filename.removesuffix('.tar.xz')), stage / 'app/node')
    node = stage / 'app/node/bin/node'
    env = dict(os.environ, PATH=f'{node.parent}:{os.environ["PATH"]}')
    server = stage / 'app/server'
    subprocess.run(['npm', 'install', '-g', f'{app["npm_package"]}@{version}', '--prefix', str(server), '--no-audit', '--no-fund'], env=env, check=True)
    package = server / 'lib/node_modules' / app['npm_package']
    info = json.loads((package / 'package.json').read_text())
    if info['version'] != version or info['name'] != app['npm_package']:
        raise RuntimeError('Installed npm package identity mismatch')
    shutil.copy2(package / 'LICENSE', stage / 'LICENSE')
    # Exercise the native PTY rather than claiming that an import is sufficient.
    test = '''const pty=require('node-pty');require('sharp');
const p=pty.spawn('/bin/sh',['-c','printf EKKO_PTY_OK'],{cols:80,rows:24,env:process.env});
let out='';const timer=setTimeout(()=>{p.kill();process.exit(1)},10000);
p.onData(s=>out+=s);p.onExit(e=>{clearTimeout(timer);if(e.exitCode!==0||!out.includes('EKKO_PTY_OK'))process.exit(1);console.log('Native PTY and sharp PASS')});'''
    subprocess.run([str(node), '-e', test], cwd=package, env=env, check=True, timeout=20)
    metadata = {'package': info['name'], 'version': version, 'node_version': node_version, 'node_sha256': actual}
    inventory = subprocess.check_output(['npm', 'ls', '-g', '--all', '--json', '--prefix', str(server)], env=env, text=True)
    (stage / 'app/native/dependencies.json').write_text(inventory)
    (stage / 'app/native/BUILD.json').write_text(json.dumps(metadata, indent=2) + '\n')
    for script in (stage / 'cmd').iterdir():
        script.chmod(0o755)
    smoke(stage, work, env)


def smoke(stage, work, base_env):
    home = work / 'isolated-home'
    home.mkdir()
    marker = home / 'preserve-test'
    marker.write_text('keep')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(base_env, HOME=str(home), TRIM_APPDEST=str(stage / 'app'), TRIM_PKGVAR=str(work / 'var'), TRIM_DATA_SHARE_PATHS=str(home), TRIM_TEMP_LOGFILE=str(work / 'error.log'), port=str(port), HERMES_WEB_UI_DISABLE_GATEWAY_AUTOSTART='1')
    main = stage / 'cmd/main'
    def run(name, *args, check=True):
        return subprocess.run(['bash', str(stage / 'cmd' / name), *args], env=env, check=check, timeout=240)
    for name in ['install_init', 'install_callback', 'upgrade_callback', 'upgrade_callback']:
        run(name)
    assert marker.read_text() == 'keep'
    try:
        run('main', 'start')
        for _ in range(180):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as response:
                    assert response.status == 200
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3) as response:
                    assert response.status == 200 and b'<html' in response.read().lower()
                break
            except OSError:
                time.sleep(1)
        else:
            raise RuntimeError('Ekko health/frontend readiness timeout')
        run('main', 'status')
        print('SMOKE PASS: lifecycle start/status, HTTP health and frontend, repeated upgrade preserves data', flush=True)
    finally:
        run('main', 'stop')
        log = home / '.hermes-web-ui/server.log'
        # Do not print generated credentials or session tokens from the application log.
        print(f'Isolated server log exists: {log.is_file()}', flush=True)
    assert run('main', 'status', check=False).returncode == 3
    assert marker.read_text() == 'keep'
    print('SMOKE PASS: lifecycle stop/status; persistent data retained', flush=True)
    # Never ship CI HOME, PID files or authentication material in the FPK.
    assert not (stage / 'app/.hermes-web-ui').exists()
