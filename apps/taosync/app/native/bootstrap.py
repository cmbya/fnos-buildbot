#!/usr/bin/env python3
"""把安装包内已内置的 TaoSync 可执行文件部署到运行时目录。

与旧版不同：新构建体系在打包阶段就把二进制放进 FPK，安装/升级时无需联网，
只做本地复制与数据目录软链接。
"""
import argparse
import os
import shutil
import stat
from pathlib import Path

BUNDLED = Path(__file__).resolve().parent / "taoSync"


def log(msg: str) -> None:
    print(f"[TaoSync fnOS] {msg}", flush=True)


def ensure_data_link(runtime: Path, data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    link = runtime / "data"
    if link.is_symlink():
        if Path(os.readlink(link)) != data:
            link.unlink()
            link.symlink_to(data, target_is_directory=True)
    elif link.exists():
        if link.is_dir() and not any(link.iterdir()):
            link.rmdir()
            link.symlink_to(data, target_is_directory=True)
        else:
            raise RuntimeError(f"{link} 已存在且不是可替换的空目录/软链接")
    else:
        link.symlink_to(data, target_is_directory=True)


def install(runtime: Path, data: Path, version: str) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    current = runtime / "VERSION"
    binary = runtime / "taoSync"

    if not BUNDLED.is_file():
        raise RuntimeError(f"安装包内缺少内置程序：{BUNDLED}")

    if binary.is_file() and current.is_file() and current.read_text(encoding="utf-8").strip() == version:
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        log(f"TaoSync {version} 已就位，跳过部署")
    else:
        if BUNDLED.stat().st_size < 1024 * 1024:
            raise RuntimeError("安装包内的 taoSync 文件异常过小")
        newbin = runtime / "taoSync.new"
        shutil.copy2(BUNDLED, newbin)
        newbin.chmod(0o755)
        os.replace(newbin, binary)
        current.write_text(version + "\n", encoding="utf-8")
        log(f"已部署 TaoSync {version} StaticX amd64（来自安装包内置文件）")

    ensure_data_link(runtime, data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--version", required=True)
    args = ap.parse_args()
    try:
        install(Path(args.runtime), Path(args.data), args.version)
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {type(e).__name__}: {e}")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
