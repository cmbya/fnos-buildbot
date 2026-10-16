#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

TARGET_VERSION = "3.19.0"
CLI_VERSION = "3.19.0"
WEBUI_URL = "https://github.com/renmu123/biliLive-webui/archive/refs/heads/webui.tar.gz"
FFMPEG_FILENAME = "ffmpeg-master-latest-linux64-gpl.tar.xz"
FFMPEG_URL = f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{FFMPEG_FILENAME}"
FFMPEG_CHECKSUMS_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/checksums.sha256"
MESIO_URL = "https://github.com/hua0512/rust-srec/releases/download/mesio-v0.5.0/mesio-x86_64-unknown-linux-musl"
REC_URL = "https://github.com/renmu123/BililiveRecorder/releases/download/v3.4.0/BililiveRecorder-CLI-linux-x64.zip"
DM_URL = "https://github.com/renmu123/DanmakuFactory/releases/download/v2.1.2/DanmakuFactory-linux-x86_64-CLI.zip"


def log(msg: str) -> None:
    print(f"[biliLive-tools native1] {msg}", flush=True)


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    log("RUN: " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def download(url: str, dest: Path, timeout: int = 180) -> None:
    log(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "biliLive-tools-fnOS-native1/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 1024)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for m in tf.getmembers():
        target = (dest / m.name).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError(f"unsafe tar path: {m.name}")
    tf.extractall(dest)


def safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for name in zf.namelist():
        target = (dest / name).resolve()
        if target != root and root not in target.parents:
            raise RuntimeError(f"unsafe zip path: {name}")
    zf.extractall(dest)


def copy_first(root: Path, names: tuple[str, ...], dest: Path) -> bool:
    for p in root.rglob("*"):
        if p.is_file() and any(p.name == n or (n.endswith("*") and p.name.startswith(n[:-1])) for n in names):
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
            dest.chmod(0o755)
            return True
    return False


def ensure_bilikey(runtime: Path) -> None:
    p = runtime / "bilikey"
    if p.exists() and p.stat().st_size > 0:
        return
    p.write_text(os.urandom(32).hex() + "\n", encoding="ascii")
    p.chmod(0o600)


def ensure_video_link(runtime: Path, video_dir: Path) -> None:
    video_dir.mkdir(parents=True, exist_ok=True)
    link = runtime / "video"
    if link.is_symlink():
        try:
            if link.resolve() == video_dir.resolve():
                return
        except OSError:
            pass
        link.unlink()
    elif link.exists():
        if link.is_dir() and not any(link.iterdir()):
            link.rmdir()
        else:
            log(f"保留已有非空目录 {link}，不替换为软链接")
            return
    link.symlink_to(video_dir, target_is_directory=True)


def npm_env(runtime: Path) -> dict[str, str]:
    env = os.environ.copy()
    node_bin = "/var/apps/nodejs_v22/target/bin"
    env["PATH"] = node_bin + ":/usr/local/bin:/usr/bin:/bin:" + env.get("PATH", "")
    env["HOME"] = str(runtime / "home")
    env["npm_config_cache"] = str(runtime / "npm-cache")
    env["npm_config_audit"] = "false"
    env["npm_config_fund"] = "false"
    env["npm_config_update_notifier"] = "false"
    env["npm_config_fetch_retries"] = "4"
    env["npm_config_fetch_retry_mintimeout"] = "20000"
    env["npm_config_fetch_retry_maxtimeout"] = "120000"
    # bililive-cli may declare the Windows-only ntsuspend package
    # as a normal dependency. npm rejects that package on Linux unless force is used.
    # ntsuspend's own install script only downloads its native binary on win32,
    # so forcing the platform check is safe for the Linux runtime.
    env["npm_config_force"] = "true"
    env["SKIP_NTSUSPEND_BINARY"] = "1"
    return env


def install_backend(runtime: Path) -> None:
    node = Path("/var/apps/nodejs_v22/target/bin/node")
    npm = Path("/var/apps/nodejs_v22/target/bin/npm")
    if not node.exists() or not npm.exists():
        raise RuntimeError("fnOS Node.js 22 运行时不存在")
    stage = runtime / "backend.new"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    (stage / "package.json").write_text('{"name":"bililive-tools-fnos-runtime","private":true}\n', encoding="utf-8")
    log(f"安装 bililive-cli {CLI_VERSION}（与上游 biliLive-tools {TARGET_VERSION} 对齐）")
    run([
        str(npm), "install", "--force", "--omit=dev", "--no-audit", "--no-fund", "--prefer-online",
        f"bililive-cli@{CLI_VERSION}"
    ], cwd=stage, env=npm_env(runtime))
    entry = stage / "node_modules" / "bililive-cli" / "lib" / "index.cjs"
    if not entry.is_file():
        matches = list((stage / "node_modules" / "bililive-cli").rglob("index.cjs"))
        if not matches:
            raise RuntimeError("npm 安装完成但未找到 bililive-cli/lib/index.cjs")
        entry = matches[0]
    # Smoke-test the installed CLI on Linux before replacing the previous backend.
    # This catches accidental unconditional imports of Windows-only modules early.
    run([str(node), str(entry), "--version"], cwd=stage, env=npm_env(runtime))
    rel = entry.relative_to(stage)
    (stage / "ENTRY").write_text(str(rel) + "\n", encoding="utf-8")
    old = runtime / "backend.old"
    backend = runtime / "backend"
    if old.exists():
        shutil.rmtree(old)
    if backend.exists():
        backend.rename(old)
    stage.rename(backend)
    if old.exists():
        shutil.rmtree(old)


def install_webui(runtime: Path) -> None:
    stage = runtime / "webui.new"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="bililive-webui-", dir=runtime) as td:
        td = Path(td)
        arc = td / "webui.tar.gz"
        extract = td / "extract"
        extract.mkdir()
        download(WEBUI_URL, arc)
        with tarfile.open(arc, "r:gz") as tf:
            safe_extract_tar(tf, extract)
        indexes = list(extract.rglob("index.html"))
        if not indexes:
            raise RuntimeError("biliLive-webui 下载成功但未找到 index.html")
        root = indexes[0].parent
        shutil.copytree(root, stage, dirs_exist_ok=True)
    # native1 does not modify the upstream WebUI on disk.
    # The fnOS wrapper injects the same-origin API address and the current passKey
    # into index.html at response time, which avoids the upstream Login page reload loop.
    old = runtime / "webui.old"
    webui = runtime / "webui"
    if old.exists():
        shutil.rmtree(old)
    if webui.exists():
        webui.rename(old)
    stage.rename(webui)
    if old.exists():
        shutil.rmtree(old)


def ensure_ffmpeg(runtime: Path) -> None:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        log("检测到系统 FFmpeg，直接使用")
        return
    bindir = runtime / "bin"
    ffmpeg = bindir / "ffmpeg"
    ffprobe = bindir / "ffprobe"
    if ffmpeg.is_file() and ffprobe.is_file():
        return
    bindir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bililive-ffmpeg-", dir=runtime) as td:
        td = Path(td)
        arc = td / "ffmpeg.tar.xz"
        extract = td / "extract"
        extract.mkdir()
        download(FFMPEG_URL, arc, 300)
        checksums = td / "checksums.sha256"
        download(FFMPEG_CHECKSUMS_URL, checksums, 60)
        expected = ""
        for line in checksums.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[-1].lstrip("*") == FFMPEG_FILENAME:
                expected = parts[0]
                break
        if not expected:
            raise RuntimeError(f"FFmpeg checksums 中未找到 {FFMPEG_FILENAME}")
        got = sha256(arc)
        if got.lower() != expected.lower():
            raise RuntimeError(f"FFmpeg SHA256 校验失败: expected={expected}, got={got}")
        with tarfile.open(arc, "r:xz") as tf:
            safe_extract_tar(tf, extract)
        candidates = list(extract.rglob("bin/ffmpeg"))
        if not candidates:
            raise RuntimeError("FFmpeg 压缩包中未找到 ffmpeg")
        srcbin = candidates[0].parent
        for name in ("ffmpeg", "ffprobe"):
            src = srcbin / name
            if not src.is_file():
                raise RuntimeError(f"FFmpeg 压缩包缺少 {name}")
            shutil.copy2(src, bindir / name)
            (bindir / name).chmod(0o755)


def best_effort_file(url: str, dest: Path, label: str) -> None:
    if dest.is_file() and os.access(dest, os.X_OK):
        return
    try:
        tmp = dest.with_suffix(dest.suffix + ".download")
        download(url, tmp, 180)
        tmp.replace(dest)
        dest.chmod(0o755)
        log(f"{label} 安装完成")
    except Exception as e:
        log(f"WARN: {label} 安装失败（不阻止主程序安装）: {e}")


def best_effort_zip_tool(url: str, runtime: Path, dest: Path, names: tuple[str, ...], label: str) -> None:
    if dest.is_file() and os.access(dest, os.X_OK):
        return
    try:
        with tempfile.TemporaryDirectory(prefix="bililive-tool-", dir=runtime) as td:
            td = Path(td)
            arc = td / "tool.zip"
            extract = td / "extract"
            extract.mkdir()
            download(url, arc, 180)
            with zipfile.ZipFile(arc) as zf:
                safe_extract_zip(zf, extract)
            if not copy_first(extract, names, dest):
                raise RuntimeError("压缩包内未找到目标程序")
        log(f"{label} 安装完成")
    except Exception as e:
        log(f"WARN: {label} 安装失败（不阻止主程序安装）: {e}")


def configure(runtime: Path, back_port: int) -> None:
    bindir = runtime / "bin"
    ffmpeg = shutil.which("ffmpeg") or str(bindir / "ffmpeg")
    ffprobe = shutil.which("ffprobe") or str(bindir / "ffprobe")
    audio = shutil.which("audiowaveform") or "audiowaveform"
    cfg = {
        "port": back_port,
        "host": "127.0.0.1",
        "configFolder": str(runtime / "data"),
        "ffmpegPath": ffmpeg,
        "ffprobePath": ffprobe,
        "mesioPath": str(bindir / "mesio"),
        "bililiveRecorderPath": str(bindir / "BililiveRecorder.Cli"),
        "audiowaveformPath": audio,
        "danmakuFactoryPath": str(bindir / "DanmakuFactory"),
        "logPath": str(runtime / "data" / "main.log"),
    }
    (runtime / "config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    from offline import install
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--runtime', required=True)
    p.add_argument('--video', required=True)
    p.add_argument('--appdest', required=True)
    p.add_argument('--back-port', type=int, default=18010)
    a = p.parse_args()
    install(Path(a.runtime).resolve(), Path(a.video).resolve(), Path(a.appdest).resolve(), a.back_port)
    return 0


def obsolete_network_installer_never_called() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--back-port", type=int, default=18010)
    p.add_argument("--appdest", required=True)
    a = p.parse_args()

    runtime = Path(a.runtime).resolve()
    video = Path(a.video).resolve()
    appdest = Path(a.appdest).resolve()
    for d in (runtime, runtime / "data", runtime / "bin", runtime / "home", runtime / "npm-cache"):
        d.mkdir(parents=True, exist_ok=True)
    ensure_bilikey(runtime)
    ensure_video_link(runtime, video)

    installed = ""
    vp = runtime / "VERSION"
    if vp.is_file():
        installed = vp.read_text(encoding="utf-8", errors="ignore").strip()

    entry_ok = (runtime / "backend" / "ENTRY").is_file()
    web_ok = (runtime / "webui" / "index.html").is_file()
    if installed != TARGET_VERSION or not entry_ok or not web_ok:
        log(f"准备 biliLive-tools {TARGET_VERSION} 原生运行环境（当前：{installed or '未安装'}）")
        install_backend(runtime)
        install_webui(runtime)
        ensure_ffmpeg(runtime)
        vp.write_text(TARGET_VERSION + "\n", encoding="utf-8")
    else:
        log(f"程序版本已是 {TARGET_VERSION}，保留现有后端、WebUI 和用户数据")
        ensure_ffmpeg(runtime)

    # Optional helpers: failures here should not make the whole application uninstallable.
    best_effort_file(MESIO_URL, runtime / "bin" / "mesio", "mesio 0.5.0")
    best_effort_zip_tool(REC_URL, runtime, runtime / "bin" / "BililiveRecorder.Cli", ("BililiveRecorder.Cli",), "BililiveRecorder CLI 3.4.0")
    best_effort_zip_tool(DM_URL, runtime, runtime / "bin" / "DanmakuFactory", ("DanmakuFactory", "DanmakuFactory*"), "DanmakuFactory 2.1.2")

    configure(runtime, a.back_port)
    shutil.copy2(appdest / "native" / "web_server.js", runtime / "web_server.js")
    log("原生运行环境准备完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
