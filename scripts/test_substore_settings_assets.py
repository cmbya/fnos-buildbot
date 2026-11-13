#!/usr/bin/env python3
"""Source-only unit tests; no downloads or FPK builds. Not run during authoring."""
import gzip
import hashlib
from pathlib import Path
import tempfile
import unittest
from substore_settings_assets import install_settings_ui


class SettingsAssetsTest(unittest.TestCase):
    def test_bootstrap_precedes_modules_and_precache_matches(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory)
            original = b'<html><head><script type="module" src="/main.js"></script></head><body></body></html>'
            (www / 'index.html').write_bytes(original)
            (www / 'index.html.gz').write_bytes(gzip.compress(original))
            (www / 'sw.js').write_text('{url:"index.html",revision:"0123456789abcdef"}')
            (www / 'sw.js.gz').write_bytes(gzip.compress((www / 'sw.js').read_bytes()))
            result = install_settings_ui(www)
            content = (www / 'index.html').read_bytes()
            self.assertLess(content.index(b'/_fnos/client.js'), content.index(b'type="module"'))
            self.assertEqual(gzip.decompress((www / 'index.html.gz').read_bytes()), content)
            self.assertIn(hashlib.md5(content).hexdigest(), (www / 'sw.js').read_text())
            self.assertEqual(gzip.decompress((www / 'sw.js.gz').read_bytes()), (www / 'sw.js').read_bytes())
            self.assertEqual(result['settings_page'], '/_fnos/settings')
            with self.assertRaises(RuntimeError):
                install_settings_ui(www)

    def test_unknown_layout_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            www = Path(directory)
            (www / 'index.html').write_text('<html><body>unexpected</body></html>')
            with self.assertRaises(RuntimeError):
                install_settings_ui(www)


if __name__ == '__main__':
    unittest.main()
