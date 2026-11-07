"""Cloud regression of the exact help commands in the reusable workflow."""
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


class FnpackHelpTests(unittest.TestCase):
    def run_help(self, program):
        workflow = (Path(__file__).resolve().parent.parent / '.github/workflows/build-app.yml').read_text()
        block = workflow.split('      - name: 安装 fnpack', 1)[1].split('      - name: 写入单应用配置', 1)[0]
        self.assertNotIn('fnpack --help |', block)
        commands = block[block.index('          fnpack --help'):].rstrip()
        commands = textwrap.dedent(commands)
        with tempfile.TemporaryDirectory(prefix='fnpack-help-') as tmp:
            root = Path(tmp)
            fnpack = root / 'fnpack'
            fnpack.write_text('#!/usr/bin/env python3\n' + program)
            fnpack.chmod(0o755)
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}', RUNNER_TEMP=tmp)
            result = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + commands + '\nprintf "CONTINUED\\n"\n'],
                                    env=env, text=True, capture_output=True, timeout=20)
            file = root / 'fnpack-help.txt'
            return result, file.read_text() if file.exists() else ''

    def test_large_help_completes_without_sigpipe(self):
        result, saved = self.run_help('import sys\nfor i in range(100000): print("help line", i)\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['help line 0', 'help line 1', 'help line 2', 'CONTINUED'])
        self.assertEqual(len(saved.splitlines()), 100000)

    def test_real_failure_is_not_masked(self):
        result, saved = self.run_help('import sys\nprint("partial help")\nsys.exit(7)\n')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertNotIn('CONTINUED', result.stdout)
        self.assertEqual(saved, 'partial help\n')

    def test_empty_success_is_not_a_broken_pipe(self):
        result, saved = self.run_help('pass\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'CONTINUED\n')
        self.assertEqual(saved, '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
