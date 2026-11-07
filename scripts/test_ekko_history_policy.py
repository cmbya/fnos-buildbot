"""Cloud-only policy guards plus the exact npm version selected for the FPK."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ekko_history_policy import patch_metadata, prepare_history
from patch_ekko_history import PATCH_ID, UnsupportedHistoryLayout
from test_ekko_patch import fetch


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ekko-policy-')
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name)
        self.target = self.package / 'dist/server/index.js'
        self.target.parent.mkdir(parents=True)
        self.original = b'// unreviewed official layout\nconst upstream = true;\n'
        self.target.write_bytes(self.original)

    def test_unknown_layout_is_byte_identical_and_not_claimed_patched(self):
        state = prepare_history(self.package, shutil.which('node'))
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(state['status'], 'skipped_unsupported')
        self.assertEqual(state['original_bundle_sha256'], state['packaged_bundle_sha256'])
        self.assertEqual(patch_metadata(state)['patches'], [])

    def test_invalid_unpatched_javascript_is_fatal(self):
        self.target.write_text('const broken = ;')
        with self.assertRaises(subprocess.CalledProcessError):
            prepare_history(self.package, shutil.which('node'))

    def test_already_or_partially_patched_bundle_is_fatal(self):
        for marker in ['function ekkoWarnEmptyHistory(', 'ekkoWarnEmptyHistory(s,m,p,l)',
                       'const ekkoEmptyHistoryWarnings=new Set()']:
            with self.subTest(marker=marker):
                data = ('// ' + marker).encode()
                self.target.write_bytes(data)
                with self.assertRaises(RuntimeError) as error:
                    prepare_history(self.package, shutil.which('node'))
                self.assertNotIsInstance(error.exception, UnsupportedHistoryLayout)
                self.assertEqual(self.target.read_bytes(), data)

    def test_unexpected_and_io_errors_are_not_skipped(self):
        for error in [RuntimeError('unexpected bug'), OSError('filesystem failure')]:
            with self.subTest(error=type(error).__name__):
                with patch('ekko_history_policy.apply', side_effect=error):
                    with self.assertRaises(type(error)):
                        prepare_history(self.package, 'node')

    def test_partial_write_cannot_be_skipped(self):
        def unsafe(_package):
            self.target.write_bytes(b'changed')
            raise UnsupportedHistoryLayout('not safe')
        with patch('ekko_history_policy.apply', side_effect=unsafe):
            with self.assertRaisesRegex(RuntimeError, 'modified the official bundle'):
                prepare_history(self.package, 'node')

    def test_regression_failure_after_patch_is_fatal(self):
        def edited(_package):
            self.target.write_bytes(b'const patched = true;')
        with patch('ekko_history_policy.apply', side_effect=edited):
            with patch('ekko_history_policy.subprocess.run', side_effect=[None, subprocess.CalledProcessError(1, ['history-regression'])]) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    prepare_history(self.package, 'node')
                self.assertEqual(run.call_count, 2)
                self.assertIn('test_ekko_history.cjs', run.call_args.args[0][1])
        self.assertEqual(self.target.read_bytes(), b'const patched = true;')

    def test_only_verified_applied_patch_is_recorded(self):
        with patch('ekko_history_policy.apply'):
            with patch('ekko_history_policy.subprocess.run') as run:
                state = prepare_history(self.package, 'node')
                self.assertEqual(run.call_count, 2)
        self.assertEqual(state['regression'], 'passed')
        self.assertEqual(patch_metadata(state)['patches'], [PATCH_ID])
        with self.assertRaises(RuntimeError):
            patch_metadata(dict(state, regression='pending'))
        with self.assertRaises(RuntimeError):
            patch_metadata(dict(state, status='skipped_unsupported', packaged_bundle_sha256='different'))


def test_selected_version(version):
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise RuntimeError('Expected a fixed official npm release version')
    original = fetch(version)  # Existing npm SHA512 verification; no npm install here.
    with tempfile.TemporaryDirectory(prefix='ekko-selected-') as tmp:
        package = Path(tmp)
        target = package / 'dist/server/index.js'
        target.parent.mkdir(parents=True)
        target.write_text(original)
        before = target.read_bytes()
        state = prepare_history(package, shutil.which('node'))
        metadata = patch_metadata(state)
        if state['status'] == 'skipped_unsupported':
            assert target.read_bytes() == before
            assert metadata['patches'] == []
        else:
            assert metadata['patches'] == [PATCH_ID]
            assert state['regression'] == 'passed'
        print('PASS: selected npm version', version, json.dumps(metadata, sort_keys=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise SystemExit(1)
    test_selected_version(args.version)
