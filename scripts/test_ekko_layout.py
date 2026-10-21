"""Offline lifecycle regression; no production service starts or configuration writes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def test_layout(node_seed, package):
    with tempfile.TemporaryDirectory(prefix='ekko-layout-', dir=os.environ.get('TMPDIR')) as tmp:
        root = Path(tmp)
        app, var, home = root/'app', root/'var', root/'home'
        (app/'native').mkdir(parents=True)
        (app/'server/lib/node_modules').mkdir(parents=True)
        home.mkdir()
        # Seed is read-only: copy installation outputs only into isolated var.
        (app/'node').symlink_to(Path(node_seed).resolve(), target_is_directory=True)
        (app/'server/lib/node_modules/ekko-studio').symlink_to(Path(package).resolve(), target_is_directory=True)
        (app/'native/migrate-mcp.cjs').write_bytes((ROOT/'apps/ekko/app/native/migrate-mcp.cjs').read_bytes())
        env = dict(os.environ, TRIM_APPDEST=str(app), TRIM_PKGVAR=str(var), TRIM_DATA_SHARE_PATHS=str(home), HOME=str(home), HERMES_HOME=str(home/'.hermes'), port='8770')
        def run(name):
            subprocess.run(['bash', str(ROOT/'apps/ekko/cmd'/name)], env=env, check=True, timeout=60)
        runtime = var/'node'
        (runtime/'bin').mkdir(parents=True)
        marker = runtime/'bin/codex'
        marker.write_text('#!/bin/sh\nprintf "codex-cli fixture\\n"\n')
        marker.chmod(0o755)
        (home/'.hermes').mkdir()
        config = home/'.hermes/config.yaml'
        config.write_text(json.dumps({'mcp_servers': {'ekko-studio-use': {'command': '/old/runtime/node', 'args': ['/vol2/@appcenter/Ekko/server/lib/node_modules/hermes-web-ui/bin/ekko-studio-mcp.mjs', 'use'], 'enabled': False}}, 'untouched': True}))
        run('install_callback')
        run('upgrade_callback')
        run('upgrade_callback')
        assert marker.read_text().startswith('#!/bin/sh')
        env.update(PATH=f'{runtime}/bin:'+env['PATH'], NPM_CONFIG_PREFIX=str(runtime))
        assert subprocess.check_output(['npm', 'prefix', '-g'], env=env, text=True).strip() == str(runtime)
        assert subprocess.check_output(['codex', '--version'], env=env, text=True).strip() == 'codex-cli fixture'
        node = runtime/'bin/node'
        js = 'const y=require("yaml");console.log(JSON.stringify(y.parse(require("fs").readFileSync(process.argv[1],"utf8"))))'
        result = json.loads(subprocess.check_output([str(node), '-e', js, str(config)], cwd=package, text=True))
        entry = result['mcp_servers']['ekko-studio-use']
        assert entry['command'] == str(node) and entry['enabled'] is False
        assert result['untouched'] is True
        assert len(list(config.parent.glob('config.yaml.before-*'))) == 1
        assert subprocess.run(['bash', str(ROOT/'apps/ekko/cmd/main'), 'status'], env=env, check=False).returncode == 3
        print('PASS: fresh persistent runtime, preserved Codex, repeated upgrades, npm prefix, MCP migration and disabled state')

if __name__ == '__main__':
    import sys
    test_layout(*sys.argv[1:])
