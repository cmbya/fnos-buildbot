#!/usr/bin/env python3
"""把安装包内已内置的 OpenList 可执行文件部署到运行时目录。

与旧版不同：新构建体系在打包阶段就把二进制放进 FPK，安装/升级时无需联网，
只做本地复制与数据目录软链接。
"""
import argparse
import os
import shutil
import stat
from pathlib import Path

BUNDLED = Path(__file__).resolve().parent / "openlist"


def log(msg: str) -> None:
    print(f"[OpenList fnOS] {msg}", flush=True)


def ensure_data_link(runtime: Path, data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    link = runtime / "data"
    if link.is_symlink():
        try:
            current = Path(os.readlink(link))
        except OSError:
            current = None
        if current != data:
            link.unlink()
            link.symlink_to(data, target_is_directory=True)
    elif link.exists():
        if link.is_dir() and not any(link.iterdir()):
            link.rmdir()
            link.symlink_to(data, target_is_directory=True)
        elif link.resolve() != data.resolve():
            raise RuntimeError(f"{link} 已存在且不是可替换的空目录/软链接")
    else:
        link.symlink_to(data, target_is_directory=True)


def install(runtime: Path, data: Path, version: str) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    binary = runtime / "openlist"
    marker = runtime / "VERSION"

    if not BUNDLED.is_file():
        raise RuntimeError(f"安装包内缺少内置程序：{BUNDLED}")

    if binary.is_file() and marker.is_file() and marker.read_text(encoding="utf-8").strip() == version:
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        ensure_data_link(runtime, data)
        log(f"OpenList {version} 已就位，跳过部署")
        return

    if BUNDLED.stat().st_size < 1024 * 1024:
        raise RuntimeError("安装包内的 openlist 文件异常过小")

    newbin = runtime / "openlist.new"
    shutil.copy2(BUNDLED, newbin)
    newbin.chmod(0o755)
    os.replace(newbin, binary)
    marker.write_text(version + "\n", encoding="utf-8")
    log(f"已部署 OpenList {version} Linux amd64（来自安装包内置文件）")

    ensure_data_link(runtime, data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    install(Path(args.runtime), Path(args.data), args.version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
