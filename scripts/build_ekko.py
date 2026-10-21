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
    subprocess.run(['npm', 'install', '-g', f'{app["npm_package"]}@{version}', '--prefix', str(server), '--no-audit', '--no-fund', '--allow-scripts=agent-browser,node-pty,protobufjs,vue-demi'], env=env, check=True)
    package = server / 'lib/node_modules' / app['npm_package']
    info = json.loads((package / 'package.json').read_text())
    if info['version'] != version or info['name'] != app['npm_package']:
        raise RuntimeError('Installed npm package identity mismatch')
    from patch_ekko_history import apply as patch_history
    patch_history(package)
    subprocess.run([str(node), '--check', str(package / 'dist/server/index.js')], env=env, check=True)
    subprocess.run([str(node), str(Path(__file__).with_name('test_ekko_history.cjs')), str(package / 'dist/server/index.js')], env=env, check=True)
    shutil.copy2(package / 'LICENSE', stage / 'LICENSE')
    # Exercise the native PTY rather than claiming that an import is sufficient.
    test = '''const pty=require('node-pty');require('sharp');
const p=pty.spawn('/bin/sh',['-c','printf EKKO_PTY_OK'],{cols:80,rows:24,env:process.env});
let out='';const timer=setTimeout(()=>{p.kill();process.exit(1)},10000);
p.onData(s=>out+=s);p.onExit(e=>{clearTimeout(timer);if(e.exitCode!==0||!out.includes('EKKO_PTY_OK'))process.exit(1);console.log('Native PTY and sharp PASS')});'''
    subprocess.run([str(node), '-e', test], cwd=package, env=env, check=True, timeout=20)
    metadata = {'package': info['name'], 'version': version, 'node_version': node_version, 'node_sha256': actual, 'patches': ['history-reasoning-classification-v1']}
    inventory = subprocess.check_output(['npm', 'ls', '-g', '--all', '--json', '--prefix', str(server)], env=env, text=True)
    (stage / 'app/native').mkdir(parents=True, exist_ok=True)
    (stage / 'app/native/dependencies.json').write_text(inventory)
    (stage / 'app/native/BUILD.json').write_text(json.dumps(metadata, indent=2) + '\n')
    for script in (stage / 'cmd').iterdir():
        script.chmod(0o755)
    subprocess.run(['python3', str(Path(__file__).with_name('test_ekko_layout.py')), str(stage / 'app/node'), str(package)], env=env, check=True, timeout=180)
    smoke(stage, work, env)
    # Match the original FPK's XZ payload layout; retain official Node archive.
    subprocess.run(['tar', '-cJf', str(stage / 'app/server.tar.xz'), '-C', str(stage / 'app'), 'server'], check=True)
    shutil.copy2(archive, stage / 'app/node.tar.xz')
    (stage / 'app/native/node-version').write_text(f'v{node_version}\n')
    shutil.rmtree(server)
    shutil.rmtree(stage / 'app/node')
    # Re-run full lifecycle tests against compressed installation inputs.
    packed_work = work / 'packed-smoke'
    packed_work.mkdir()
    smoke(stage, packed_work, env)
    # Installation expands server in target; ship only compressed input.
    shutil.rmtree(server)


def smoke(stage, work, base_env):
    home = work / 'isolated-home'
    home.mkdir()
    marker = home / 'preserve-test'
    marker.write_text('keep')
    # Seed the exact legacy configuration, including disabled browser entry.
    profile = home / '.hermes'
    profile.mkdir()
    legacy = {'mcp_servers': {name: {'command': '/old/runtime/node', 'args': ['/vol2/@appcenter/Ekko/server/lib/node_modules/hermes-web-ui/bin/ekko-studio-mcp.mjs', toolset], 'enabled': toolset != 'browser', 'env': {'HERMES_WEB_UI_URL': 'http://127.0.0.1:8770'}} for name, toolset in [('ekko-studio-use', 'use'), ('ekko-studio-interaction', 'plan'), ('ekko-studio-browser', 'browser')]}, 'untouched': 'preserve-me'}
    config = profile / 'config.yaml'
    config.write_text(json.dumps(legacy))
    config.chmod(0o600)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(base_env, HOME=str(home), HERMES_HOME=str(profile), TRIM_APPDEST=str(stage / 'app'), TRIM_PKGVAR=str(work / 'var'), TRIM_DATA_SHARE_PATHS=str(home), TRIM_TEMP_LOGFILE=str(work / 'error.log'), port=str(port), HERMES_WEB_UI_DISABLE_GATEWAY_AUTOSTART='1')
    main = stage / 'cmd/main'
    def run(name, *args, check=True):
        return subprocess.run(['bash', str(stage / 'cmd' / name), *args], env=env, check=check, timeout=240)
    run('install_init')
    run('install_callback')
    runtime = Path(env['TRIM_PKGVAR']) / 'node'
    # Simulate a previously installed CLI in the original package's persistent prefix.
    codex = runtime / 'bin/codex'
    fixture = '#!/bin/sh\nprintf "codex-cli 0.0.0-fixture\\n"\n'
    codex.write_text(fixture)
    codex.chmod(0o755)
    for name in ['upgrade_callback', 'upgrade_callback']:
        run(name)
    assert codex.read_text() == fixture
    runtime_env = dict(env, PATH=f'{runtime}/bin:{env["PATH"]}', NPM_CONFIG_PREFIX=str(runtime))
    assert subprocess.check_output(['npm', 'prefix', '-g'], env=runtime_env, text=True).strip() == str(runtime)
    assert 'codex-cli' in subprocess.check_output(['codex', '--version'], env=runtime_env, text=True)
    assert marker.read_text() == 'keep'
    node = str(runtime / 'bin/node')
    package = stage / 'app/server/lib/node_modules/ekko-studio'
    # YAML serialization is parsed by the same installed library.
    migrated = json.loads(subprocess.check_output([node, '-e', 'console.log(JSON.stringify(require("yaml").parse(require("fs").readFileSync(process.argv[1],"utf8"))))', str(config)], cwd=package, text=True))
    assert migrated['untouched'] == 'preserve-me'
    for name, entry in migrated['mcp_servers'].items():
        assert entry['command'] == node
        assert '/ekko-studio/bin/' in entry['args'][0]
        assert entry['env']['HERMES_WEB_UI_URL'] == 'http://127.0.0.1:8770'
    assert not migrated['mcp_servers']['ekko-studio-browser']['enabled']
    backups = list(profile.glob('config.yaml.before-ekko-path-migration-*'))
    assert len(backups) == 1 and json.loads(backups[0].read_text()) == legacy
    print('PASS: idempotent MCP migration, exact backup, disabled state and custom URL preserved', flush=True)
    cli = package / 'bin/ekko-studio-mcp.mjs'
    for toolset in ['api', 'use', 'plan']:
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'ci', 'version': '1'}}}, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}]
        result = subprocess.run([node, str(cli), toolset], input=''.join(json.dumps(m)+'\n' for m in messages), capture_output=True, text=True, env=env, check=True, timeout=20)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        assert next(r for r in responses if r.get('id') == 2)['result']['tools']
    print('PASS: api/use/plan MCP toolsets initialize and list tools; browser path migrated but live browser attachment not exercised', flush=True)
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
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            new_port = sock.getsockname()[1]
        env['port'] = str(new_port)
        run('config_init')
        run('config_callback')
        with urllib.request.urlopen(f'http://127.0.0.1:{new_port}/health', timeout=10) as response:
            assert response.status == 200
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0
        print('SMOKE PASS: configuration changes live port and releases old port', flush=True)
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
