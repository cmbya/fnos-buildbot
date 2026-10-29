#!/usr/bin/env python3
"""Focused unit and packaged-runtime tests. Uses isolated scratch data only."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error
import zipfile

from build_substore import patch_frontend, unpack_frontend, checked_download

ROOT = Path(__file__).resolve().parent.parent


class SubStoreTests(unittest.TestCase):
    def test_frontend_patch_and_precache(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            js = b'const key="hostAPI",api="https://sub.store",next=1;'
            (p / 'main.js').write_bytes(js)
            (p / 'main.js.gz').write_bytes(gzip.compress(js))
            (p / 'sw.js').write_text('{url:"main.js",revision:"abcd"}')
            patch_frontend(p)
            self.assertIn(b'api="/path"', (p / 'main.js').read_bytes())
            self.assertEqual(gzip.decompress((p / 'main.js.gz').read_bytes()), (p / 'main.js').read_bytes())
            self.assertIn(hashlib.md5((p / 'main.js').read_bytes()).hexdigest(), (p / 'sw.js').read_text())
            with self.assertRaises(RuntimeError):
                patch_frontend(p)

    def test_reject_ambiguous_frontend(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / 'main.js').write_text('a="https://sub.store",b="https://sub.store",c=1')
            with self.assertRaises(RuntimeError):
                patch_frontend(p)

    def test_reject_archive_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            with zipfile.ZipFile(p / 'bad.zip', 'w') as z:
                z.writestr('dist/../../escape', 'bad')
            with self.assertRaises(RuntimeError):
                unpack_frontend(p / 'bad.zip', p / 'www')
            self.assertFalse((p / 'escape').exists())

    def test_reject_wrong_sha(self):
        with tempfile.TemporaryDirectory() as td:
            def download(url, dest, token):
                dest.write_bytes(b'bad')
            release = {'assets': [{'name': 'asset', 'size': 3, 'digest': 'sha256:' + '0' * 64, 'browser_download_url': 'https://example.org/asset'}]}
            with patch('build_app.http_get', download), self.assertRaises(RuntimeError):
                checked_download(release, 'asset', Path(td) / 'asset', None)

    def test_existing_platform_default_preserved(self):
        import build_app
        self.assertIn('app.get("platform", "x86")', __import__('inspect').getsource(build_app.self_check))

    def test_packaged_runtime_and_lifecycle(self):
        fpk = Path(os.environ.get('SUBSTORE_TEST_FPK', ROOT / 'dist/Sub-Store-2.44.2-all.fpk'))
        self.assertTrue(fpk.is_file(), 'Build the FPK first')
        node = os.environ.get('SUBSTORE_TEST_NODE') or __import__('shutil').which('node')
        self.assertTrue(node and Path(node).is_file())
        with tempfile.TemporaryDirectory(prefix='substore-test-') as td:
            p = Path(td)
            def unpack(archive, dest):
                # Works on the NAS Python 3.11 as well as GitHub runner Python.
                with tarfile.open(archive) as tf:
                    for member in tf.getmembers():
                        rel = Path(member.name)
                        if rel.is_absolute() or '..' in rel.parts or not (member.isfile() or member.isdir()):
                            raise RuntimeError(f'Unsafe package member: {member.name}')
                        out = dest / rel
                        if member.isdir():
                            out.mkdir(parents=True, exist_ok=True)
                        else:
                            out.parent.mkdir(parents=True, exist_ok=True)
                            out.write_bytes(tf.extractfile(member).read())
            unpack(fpk, p / 'package')
            package = p / 'package'
            unpack(package / 'app.tgz', p / 'target')
            target = p / 'target'
            build = json.loads((target / 'BUILD.json').read_text())
            backend = target / 'server/sub-store.bundle.js'
            self.assertEqual(hashlib.sha256(backend.read_bytes()).hexdigest(), build['backend_asset']['sha256'])
            for gz in (target / 'www').rglob('*.js.gz'):
                self.assertEqual(gzip.decompress(gz.read_bytes()), gz.with_suffix('').read_bytes())
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            env = {**os.environ, 'TRIM_APPDEST': str(target), 'TRIM_PKGVAR': str(p / 'data'), 'port': str(port),
                   'SUB_STORE_BACKEND_API_HOST': '127.0.0.1', 'PATH': str(Path(node).parent) + ':' + os.environ['PATH']}
            env.pop('SUB_STORE_CORS_ALLOWED_ORIGINS', None)
            main = package / 'cmd/main'
            def run(action, expected=0):
                result = subprocess.run(['bash', str(main), action], env=env, capture_output=True, text=True, timeout=45)
                if result.returncode != expected and (p / 'data/info.log').exists():
                    print((p / 'data/info.log').read_text()[-6000:])
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            def request(path, data=None):
                req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(data).encode() if data else None,
                                             headers={'Content-Type': 'application/json', 'Origin': f'http://127.0.0.1:{port}'})
                with urllib.request.urlopen(req, timeout=5) as r:
                    return r.status, r.read()
            try:
                run('start')
                run('status')
                status, page = request('/')
                self.assertEqual(status, 200)
                self.assertIn(b'<title>Sub-Store</title>', page)
                status, body = request('/path/api/utils/env')
                self.assertEqual(status, 200)
                self.assertIn(build['backend_tag'].encode(), body)
                # Exercise browser-style module requests, including LAN/IPv6 and
                # rejection of untrusted origins; no-Origin HTTP 200 is insufficient.
                hosts = subprocess.check_output(['hostname', '-I'], text=True).split()
                origins = [f'http://localhost:{port}', f'http://[::1]:{port}']
                origins += [f'http://[{h}]:{port}' if ':' in h else f'http://{h}:{port}' for h in hosts]
                main_chunk = build['frontend_patch']['file']
                for origin in origins:
                    for path in ['/index.js', '/' + main_chunk, '/path/api/utils/env']:
                        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', headers={'Origin': origin})
                        with urllib.request.urlopen(req, timeout=5) as r:
                            self.assertEqual(r.status, 200)
                            self.assertEqual(r.headers['Access-Control-Allow-Origin'], origin)
                for origin in ['https://untrusted.invalid', f'http://127.0.0.1:{port + 1}']:
                    req = urllib.request.Request(f'http://127.0.0.1:{port}/index.js', headers={'Origin': origin})
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(req, timeout=5)
                    self.assertEqual(error.exception.code, 403)
                status, body = request('/path/api/subs', {'name': 'packaging-test', 'source': 'local', 'content': '[]'})
                self.assertEqual(status, 201, body)
                run('stop')
                run('status', 3)
                self.assertTrue((p / 'data/sub-store.json').is_file())
                run('start')
                _, body = request('/path/api/subs')
                self.assertIn(b'packaging-test', body)
                run('stop')
                for script in ['install_init', 'install_callback', 'upgrade_init', 'upgrade_callback', 'uninstall_callback']:
                    subprocess.run(['bash', str(package / 'cmd' / script)], env=env, check=True)
                self.assertIn('packaging-test', (p / 'data/sub-store.json').read_text())
                # A stale PID belonging to another process must not be signalled.
                (p / 'data/app.pid').write_text(str(os.getpid()) + '\n')
                run('status', 3)
                run('stop')
                subprocess.run(['bash', str(package / 'cmd/uninstall_callback')], env={**env, 'wizard_data_action': 'delete'}, check=True)
                self.assertEqual(list((p / 'data').iterdir()), [])
                bad = subprocess.run(['bash', str(main), 'start'], env={**env, 'port': '65536'}, capture_output=True)
                self.assertNotEqual(bad.returncode, 0)
                print('Runtime evidence: UI/API HTTP 200; POST 201; persisted subscription after restart; lifecycle keep/delete; stale PID safe')
            finally:
                subprocess.run(['bash', str(main), 'stop'], env=env, capture_output=True, timeout=20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
