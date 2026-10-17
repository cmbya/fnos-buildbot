#!/usr/bin/env python3
"""Offline deployment preserving native7 config/recordings layout."""
import os
from pathlib import Path
import shutil
import time
import argparse
PERSISTENT_CONFIG_FILES = ('user_settings.json','cookies.json','recordings.json','accounts.json','web_auth.json')
def log(s): print(s, flush=True)
def migrate_user_config(old_source: Path, userdata: Path) -> None:
    """Copy native1 mutable config out of source before source replacement."""
    persistent = userdata / "config"
    persistent.mkdir(parents=True, exist_ok=True)
    old_cfg = old_source / "config"
    if not old_cfg.is_dir():
        return

    for name in PERSISTENT_CONFIG_FILES:
        src = old_cfg / name
        dst = persistent / name
        # Do not overwrite an already-persisted native2 file.
        if dst.exists():
            continue
        if src.is_file() and not src.is_symlink():
            shutil.copy2(src, dst)
            log(f"Migrated user config: {name}")
        elif src.is_symlink():
            try:
                resolved = src.resolve(strict=True)
            except FileNotFoundError:
                continue
            if resolved.is_file():
                shutil.copy2(resolved, dst)
                log(f"Recovered user config from symlink: {name}")


def link_persistent_config(source: Path, userdata: Path) -> None:
    persistent = userdata / "config"
    persistent.mkdir(parents=True, exist_ok=True)
    cfg = source / "config"
    cfg.mkdir(parents=True, exist_ok=True)

    for name in PERSISTENT_CONFIG_FILES:
        link = cfg / name
        target = persistent / name
        if link.is_symlink():
            try:
                if link.resolve() == target.resolve():
                    continue
            except OSError:
                pass
            link.unlink()
        elif link.exists():
            # If a freshly downloaded source ever ships one of these mutable
            # files, preserve it only when the persistent copy does not exist.
            if not target.exists() and link.is_file():
                shutil.copy2(link, target)
            if link.is_dir():
                shutil.rmtree(link)
            else:
                link.unlink()
        link.symlink_to(target)



p = argparse.ArgumentParser()
p.add_argument('--runtime', required=True)
p.add_argument('--downloads', required=True)
p.add_argument('--port', type=int, default=6006)
a = p.parse_args()
runtime = Path(a.runtime).resolve()
bundle = Path(__file__).resolve().parent / 'bundle'
runtime.mkdir(parents=True, exist_ok=True)
userdata = runtime / 'userdata'
userdata.mkdir(exist_ok=True)
if (runtime / 'source').exists(): migrate_user_config(runtime / 'source', userdata)
new = runtime / 'source.new'
if new.exists(): shutil.rmtree(new)
shutil.copytree(bundle / 'source', new)
link_persistent_config(new, userdata)
for name, target in [('logs', runtime / 'logs'), ('downloads', Path(a.downloads).resolve())]:
    target.mkdir(parents=True, exist_ok=True)
    link = new / name
    if link.is_dir(): shutil.rmtree(link)
    elif link.exists() or link.is_symlink(): link.unlink()
    link.symlink_to(target, target_is_directory=True)
(new / '.env').write_text('PLATFORM=web\nHOST=0.0.0.0\nPORT='+str(a.port)+'\nTZ=Asia/Shanghai\n')
old = runtime / ('source.prebundled-'+str(time.time_ns()))
if (runtime / 'source').exists(): (runtime / 'source').rename(old)
try: new.rename(runtime / 'source')
except Exception:
    if old.exists(): old.rename(runtime / 'source')
    raise
for name, target in [('python', bundle / 'python'), ('bin', bundle / 'bin')]:
    link=runtime/name
    if link.is_symlink(): link.unlink()
    elif link.exists(): link.rename(runtime/(name+'.prebundled-'+str(time.time_ns())))
    link.symlink_to(target, target_is_directory=True)
(runtime/'VERSION').write_text((bundle/'VERSION').read_text())
log('StreamCap offline deployment ready; userdata and recordings preserved')
