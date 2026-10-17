#!/usr/bin/env python3
"""Prepare and upgrade a native StreamCap runtime for fnOS.

Design goals for native2:
- no Docker;
- keep StreamCap mutable config outside the replaceable source tree;
- migrate native1 config automatically;
- only replace source/venv when the pinned StreamCap version changes;
- stage new source and venv before swapping, so a failed upgrade leaves the
  old runtime available;
- keep recordings outside the source tree via a downloads symlink.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

STREAMCAP_VERSION = "v1.0.3"
SOURCE_URL = "https://github.com/ihmily/StreamCap/archive/refs/tags/v1.0.3.tar.gz"
FFMPEG_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/"
    "autobuild-2026-08-12-13-15/ffmpeg-master-latest-linux64-gpl.tar.xz"
)
FFMPEG_SHA256 = "4020b075a3e2b311f4d7311177680ce63ff883f6a247e957d3cb3e855302b4ac"

# StreamCap's ConfigManager stores mutable state in these files under config/.
# default_settings.json, language.json and version.json remain versioned source
# files and are intentionally not persisted across source upgrades.
PERSISTENT_CONFIG_FILES = (
    "user_settings.json",
    "cookies.json",
    "recordings.json",
    "accounts.json",
    "web_auth.json",
)


def log(msg: str) -> None:
    print(f"[StreamCap native2] {msg}", flush=True)


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    log("RUN: " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def download(url: str, dest: Path) -> None:
    log(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "StreamCap-fnOS-native2/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError(f"Unsafe path in archive: {member.name}")
    tf.extractall(dest)


def read_installed_version(runtime: Path) -> str:
    p = runtime / "VERSION"
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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


def ensure_env(source: Path, port: int) -> None:
    env_file = source / ".env"
    if env_file.exists():
        return
    env_file.write_text(
        "PLATFORM=web\n"
        "HOST=0.0.0.0\n"
        f"PORT={port}\n"
        "TZ=Asia/Shanghai\n",
        encoding="utf-8",
    )


def prepare_source(runtime: Path) -> Path:
    stage = runtime / "source.new"
    if stage.exists() or stage.is_symlink():
        if stage.is_dir() and not stage.is_symlink():
            shutil.rmtree(stage)
        else:
            stage.unlink()

    with tempfile.TemporaryDirectory(prefix="streamcap-src-", dir=runtime) as td:
        td_path = Path(td)
        archive = td_path / "source.tar.gz"
        download(SOURCE_URL, archive)
        extract = td_path / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:gz") as tf:
            safe_extract(tf, extract)
        roots = [p for p in extract.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "main.py").is_file():
            raise RuntimeError("Unexpected StreamCap source archive structure")
        shutil.move(str(roots[0]), str(stage))
    log(f"Prepared StreamCap {STREAMCAP_VERSION} source")
    return stage


def prepare_venv(runtime: Path, source: Path, python: str) -> Path:
    venv = runtime / "venv.new"
    if venv.exists():
        shutil.rmtree(venv)
    run([python, "-m", "venv", str(venv)])
    py = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run([
        str(pip), "install", "--prefer-binary", "--no-cache-dir",
        "-r", str(source / "requirements-web.txt"),
    ])
    return venv


def ensure_existing_venv(runtime: Path, source: Path, python: str) -> Path:
    venv = runtime / "venv"
    py = venv / "bin" / "python"
    if py.exists():
        return venv
    # Repair path: source is already present but venv was removed/corrupted.
    stage_venv = prepare_venv(runtime, source, python)
    stage_venv.rename(venv)
    return venv


def ensure_ffmpeg(runtime: Path) -> Path | None:
    system_ffmpeg = shutil.which("ffmpeg")
    system_ffprobe = shutil.which("ffprobe")
    if system_ffmpeg and system_ffprobe:
        log(f"Using system FFmpeg: {system_ffmpeg}")
        return None

    bindir = runtime / "ffmpeg" / "bin"
    ffmpeg = bindir / "ffmpeg"
    ffprobe = bindir / "ffprobe"
    if ffmpeg.exists() and ffprobe.exists():
        log(f"Using bundled FFmpeg: {ffmpeg}")
        return bindir

    with tempfile.TemporaryDirectory(prefix="streamcap-ffmpeg-", dir=runtime) as td:
        td_path = Path(td)
        archive = td_path / "ffmpeg.tar.xz"
        download(FFMPEG_URL, archive)
        got = sha256(archive)
        if got.lower() != FFMPEG_SHA256.lower():
            raise RuntimeError(f"FFmpeg SHA256 mismatch: {got}")
        extract = td_path / "extract"
        extract.mkdir()
        with tarfile.open(archive, "r:xz") as tf:
            safe_extract(tf, extract)
        candidates = list(extract.rglob("bin/ffmpeg"))
        if not candidates:
            raise RuntimeError("FFmpeg executable not found in downloaded archive")
        src_bin = candidates[0].parent
        bindir.mkdir(parents=True, exist_ok=True)
        for name in ("ffmpeg", "ffprobe"):
            src = src_bin / name
            if not src.exists():
                raise RuntimeError(f"{name} missing from FFmpeg archive")
            shutil.copy2(src, bindir / name)
            os.chmod(bindir / name, 0o755)
    log(f"Installed x86_64 FFmpeg to {bindir}")
    return bindir


def link_runtime_dirs(source: Path, runtime: Path, downloads: Path | None) -> None:
    logs = runtime / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    mappings: list[tuple[Path, Path]] = [(source / "logs", logs)]
    if downloads:
        downloads.mkdir(parents=True, exist_ok=True)
        mappings.append((source / "downloads", downloads))

    for link, target in mappings:
        if link.is_symlink():
            try:
                if link.resolve() == target.resolve():
                    continue
            except OSError:
                pass
            link.unlink()
        elif link.exists():
            if link.is_dir() and not any(link.iterdir()):
                link.rmdir()
            else:
                log(f"Keeping non-empty existing path instead of replacing it: {link}")
                continue
        link.symlink_to(target, target_is_directory=True)


def atomic_swap(runtime: Path, new_source: Path, new_venv: Path) -> None:
    source = runtime / "source"
    venv = runtime / "venv"
    source_old = runtime / "source.old"
    venv_old = runtime / "venv.old"

    for old in (source_old, venv_old):
        if old.exists():
            if old.is_dir() and not old.is_symlink():
                shutil.rmtree(old)
            else:
                old.unlink()

    source_moved = False
    venv_moved = False
    try:
        if source.exists():
            source.rename(source_old)
            source_moved = True
        if venv.exists():
            venv.rename(venv_old)
            venv_moved = True
        new_source.rename(source)
        new_venv.rename(venv)
    except Exception:
        # Roll back to the previous working runtime if any rename fails.
        if source.exists() and source != source_old:
            try:
                if source.is_dir() and not source.is_symlink():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            except OSError:
                pass
        if venv.exists() and venv != venv_old:
            try:
                if venv.is_dir() and not venv.is_symlink():
                    shutil.rmtree(venv)
                else:
                    venv.unlink()
            except OSError:
                pass
        if source_moved and source_old.exists():
            source_old.rename(source)
        if venv_moved and venv_old.exists():
            venv_old.rename(venv)
        raise
    else:
        for old in (source_old, venv_old):
            if old.exists():
                shutil.rmtree(old)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--downloads", default="")
    ap.add_argument("--python", default="/var/apps/python312/target/bin/python3")
    ap.add_argument("--port", type=int, default=6006)
    args = ap.parse_args()

    runtime = Path(args.runtime).resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    userdata = runtime / "userdata"
    userdata.mkdir(parents=True, exist_ok=True)
    downloads = Path(args.downloads).resolve() if args.downloads else None
    python = Path(args.python)
    if not python.exists():
        raise RuntimeError("fnOS python312 runtime is not installed")

    source = runtime / "source"
    installed_version = read_installed_version(runtime)

    # First native2 run migrates native1 config before any source replacement.
    if source.exists():
        migrate_user_config(source, userdata)

    source_healthy = (source / "main.py").is_file() and (source / "requirements-web.txt").is_file()
    version_changed = installed_version != STREAMCAP_VERSION

    if not source_healthy or version_changed:
        log(
            f"Preparing runtime update: installed={installed_version or 'unknown'}, "
            f"target={STREAMCAP_VERSION}"
        )
        new_source = prepare_source(runtime)
        ensure_env(new_source, args.port)
        link_persistent_config(new_source, userdata)
        link_runtime_dirs(new_source, runtime, downloads)
        new_venv = prepare_venv(runtime, new_source, str(python))
        ensure_ffmpeg(runtime)
        atomic_swap(runtime, new_source, new_venv)
        source = runtime / "source"
        (runtime / "VERSION").write_text(STREAMCAP_VERSION + "\n", encoding="utf-8")
    else:
        # Same upstream StreamCap version (e.g. native1 -> native2): do not
        # redownload everything. Just migrate/relink persistent state.
        ensure_env(source, args.port)
        link_persistent_config(source, userdata)
        link_runtime_dirs(source, runtime, downloads)
        ensure_existing_venv(runtime, source, str(python))
        ensure_ffmpeg(runtime)
        (runtime / "VERSION").write_text(STREAMCAP_VERSION + "\n", encoding="utf-8")

    log("Native2 runtime is ready")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"ERROR: {exc}")
        raise
