"""Attach fnOS web settings bootstrap; source-only helper, no frontend rebuild."""
from __future__ import annotations

import gzip
import hashlib
import re
from pathlib import Path


def install_settings_ui(www: Path):
    index = www / 'index.html'
    old = index.read_bytes()
    text = old.decode('utf-8')
    script = '<script src="/_fnos/client.js"></script>'
    if script in text or text.count('<head>') != 1:
        raise RuntimeError('Unexpected frontend head layout; refusing to inject settings bootstrap')
    # Must precede upstream ES modules: fetch/XHR adapters are installed first.
    new = text.replace('<head>', '<head>' + script, 1).encode('utf-8')
    index.write_bytes(new)
    gz = index.with_suffix('.html.gz')
    if gz.exists():
        gz.write_bytes(gzip.compress(new, mtime=0))
    sw = www / 'sw.js'
    if sw.exists():
        source = sw.read_text()
        pattern = re.compile(r'(\{url:["\']/?index\.html["\'],revision:["\'])([0-9a-f]+)(["\']\})')
        source, count = pattern.subn(lambda m: m[1] + hashlib.md5(new).hexdigest() + m[3], source)
        if count > 1:
            raise RuntimeError('Ambiguous frontend index precache entry')
        # Some releases intentionally do not precache index.html.
        sw.write_text(source)
        swgz = www / 'sw.js.gz'
        if swgz.exists():
            swgz.write_bytes(gzip.compress(sw.read_bytes(), mtime=0))
    return {'file': 'index.html', 'original_sha256': hashlib.sha256(old).hexdigest(),
            'patched_sha256': hashlib.sha256(new).hexdigest(), 'settings_page': '/_fnos/settings'}
