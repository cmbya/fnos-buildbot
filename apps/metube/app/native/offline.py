#!/usr/bin/env python3
"""Offline fnOS deployment; never downloads or modifies user state."""
import argparse
import os
from pathlib import Path
import time

p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True)
p.add_argument('--download-dir', required=True)
a = p.parse_args()
runtime = Path(a.runtime)
bundle = Path(__file__).resolve().parent / 'bundle'
assert (bundle / 'python/bin/python3.14').is_file()
assert (bundle / 'source/ui/dist/metube/index.html').is_file()
for directory in (runtime, runtime / 'home', runtime / 'state', Path(a.download_dir)):
    directory.mkdir(parents=True, exist_ok=True)
# Keep historical source/venv/tool trees as recovery backups, not user data.
for name, target in [('source', bundle / 'source'), ('python', bundle / 'python'), ('bin', bundle / 'bin')]:
    dest = runtime / name
    if dest.is_symlink():
        if dest.resolve() == target.resolve():
            continue
    elif dest.exists():
        dest.rename(runtime / (name + '.prebundled-' + str(time.time_ns())))
    temporary = runtime / (name + '.new')
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target, target_is_directory=True)
    os.replace(temporary, dest)
(runtime / 'VERSION').write_text((bundle / 'VERSION').read_text())
print('MeTube offline runtime ready; existing home/state/downloads preserved', flush=True)
