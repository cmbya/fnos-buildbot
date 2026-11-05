"""Cloud-only official bundle regression and fail-closed patch guard tests."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.request

from patch_ekko_history import apply


def fetch(version):
    with urllib.request.urlopen('https://registry.npmjs.org/ekko-studio/' + version, timeout=60) as r:
        info = json.load(r)
    with urllib.request.urlopen(info['dist']['tarball'], timeout=120) as r:
        data = r.read()
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
    assert integrity == info['dist']['integrity'], 'npm SHA512 mismatch'
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        return archive.extractfile('package/dist/server/index.js').read().decode()


def rejected(target, text):
    target.write_text(text)
    try:
        apply(target.parents[2])
    except RuntimeError:
        assert target.read_text() == text, 'rejected patch wrote partial output'
    else:
        raise AssertionError('unsafe patch accepted')


def test():
    for version in ['0.8.14', '0.8.16']:
        original = fetch(version)
        with tempfile.TemporaryDirectory(prefix='ekko-history-') as tmp:
            target = Path(tmp) / 'dist/server/index.js'
            target.parent.mkdir(parents=True)
            target.write_text(original)
            apply(Path(tmp))
            patched = target.read_text()
            subprocess.run(['node', '--check', str(target)], check=True)
            subprocess.run(['node', str(Path(__file__).with_name('test_ekko_history.cjs')), str(target)], check=True)
            rejected(target, patched)
            warning = '[chat-run-socket] skipped empty assistant message %s while loading session %s'
            rejected(target, original.replace(warning, warning + ' changed', 1))
            rejected(target, original + '\nX.warn("' + warning + '",n.id,e);')
            anchor = 'function Mrt(t,e,r={}){' if version == '0.8.16' else 'function Frt(t,e,r={}){'
            rejected(target, original.replace(anchor, anchor + '/* unexpected change */', 1))
            rejected(target, original + '\n' + anchor + '}')
            if version == '0.8.16':
                assert 'function W8e(t){return new Promise' in original
                assert 'function W8e(t){return new Promise' in patched
            print('PASS: reviewed', version, 'actual functions, duplicate/missing sites, changed region, double patch, no partial writes', flush=True)


if __name__ == '__main__':
    test()
