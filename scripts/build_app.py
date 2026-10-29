#!/usr/bin/env python3
"""构建单个应用的 fnOS FPK。

用法:
    python3 scripts/build_app.py --app openlist --version 4.2.7 --tag v4.2.7
    python3 scripts/build_app.py --config /tmp/one.json   # 由 workflow 传入单应用 JSON

流程:
    1. 按 asset_regex 从上游 Release 下载 x86 产物
    2. 校验 checksum（上游提供时严格校验，缺失则跳过）
    3. 解压出可执行文件 -> <template>/<binary_dest>
    4. 复制额外文件（如 CLIProxyAPI 的 config.example.yaml）
    5. 更新 manifest 的 version/desc/changelog，更新 wizard 提示文字
    6. 打包 FPK（packer: tar 或 fnpack）
    7. 解包自检：manifest 字段、app.tgz 与 checksum 一致
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from build_source import build_source
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH_API = "https://api.github.com"
DOWNLOAD_BASE = "https://github.com"


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


def http_get(url: str, dst: Path, token: str | None = None) -> None:
    headers = {"User-Agent": "fnos-buildbot/1.0"}
    if token and url.startswith(GH_API):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f, length=1024 * 1024)


def http_text(url: str, token: str | None = None) -> str | None:
    headers = {"User-Agent": "fnos-buildbot/1.0"}
    if token and url.startswith(GH_API):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return None


def digest_of(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_asset(release: dict, pattern: str) -> dict:
    rx = re.compile(pattern)
    for asset in release.get("assets", []):
        if rx.search(asset["name"]):
            return asset
    names = [a["name"] for a in release.get("assets", [])]
    raise RuntimeError(f"上游 Release 中没有匹配 {pattern} 的资产；实际资产：{names}")


def fetch_release(repo: str, tag: str, token: str | None) -> dict:
    return json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                f"{GH_API}/repos/{repo}/releases/tags/{tag}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "fnos-buildbot/1.0",
                    **({"Authorization": f"Bearer {token}"} if token else {}),
                },
            ),
            timeout=60,
        ).read()
    )


def verify_checksum(app: dict, work: Path, archive: Path, release: dict, token: str | None) -> None:
    """上游提供校验文件时严格校验，否则跳过（不阻断构建）。"""
    pattern = app.get("checksums_asset_regex")
    if not pattern:
        log("上游未提供校验文件，跳过校验")
        return
    try:
        asset = find_asset(release, pattern)
    except RuntimeError:
        log("上游未提供校验文件，跳过校验")
        return

    txt_path = work / asset["name"]
    http_get(asset["browser_download_url"], txt_path, token)
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    algo = app.get("checksums_format", "sha256")
    if algo == "md5":
        algo = "md5"
    else:
        algo = "sha256"
    want_len = 32 if algo == "md5" else 64
    expected = None
    for line in text.splitlines():
        parts = line.replace("*", " ").split()
        if len(parts) < 2:
            continue
        if Path(parts[-1]).name != archive.name:
            continue
        cand = parts[0].lower()
        if len(cand) == want_len and all(c in "0123456789abcdef" for c in cand):
            expected = cand
            break
    if expected is None:
        log(f"校验文件中没有 {archive.name} 的记录，跳过校验")
        return
    actual = digest_of(archive, algo)
    if actual != expected:
        raise RuntimeError(f"{archive.name} {algo} 校验失败：期望 {expected}，实际 {actual}")
    log(f"{algo} 校验通过：{actual}")


def extract_member(archive: Path, archive_type: str, inner_name: str, dst: Path,
                   executable: bool = True, min_size: int = 100_000) -> None:
    """从归档中取出 basename 等于 inner_name 的文件写到 dst。"""
    if archive_type == "tar.gz":
        with tarfile.open(archive, "r:gz") as tf:
            cands = [m for m in tf.getmembers() if m.isfile() and Path(m.name).name == inner_name]
            if not cands:
                raise RuntimeError(f"{archive.name} 中没有找到 {inner_name}")
            cands.sort(key=lambda m: m.name.count("/"))
            src = tf.extractfile(cands[0])
            if src is None:
                raise RuntimeError(f"无法读取 {cands[0].name}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            with open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
    elif archive_type == "zip":
        with zipfile.ZipFile(archive) as zf:
            cands = [
                i for i in zf.infolist()
                if not i.is_dir() and Path(i.filename).name == inner_name
            ]
            if not cands:
                raise RuntimeError(f"{archive.name} 中没有找到 {inner_name}")
            cands.sort(key=lambda i: i.filename.count("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(cands[0]) as src, open(dst, "wb") as out:
                shutil.copyfileobj(src, out)
    else:
        raise RuntimeError(f"不支持的归档类型：{archive_type}")

    size = dst.stat().st_size
    if executable:
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if size < min_size:
            raise RuntimeError(f"{dst.name} 体积异常（{size} 字节），疑似取错文件")
    log(f"解压 {inner_name}（{size} 字节）")


def copy_extra_from_archive(archive: Path, archive_type: str, specs: list[dict], stage: Path) -> None:
    for spec in specs:
        name = spec["name"]
        dest = stage / spec["dest"]
        try:
            extract_member(archive, archive_type, name, dest,
                           executable=bool(spec.get("executable", False)),
                           min_size=int(spec.get("min_size", 0)))
        except RuntimeError as e:
            if spec.get("optional"):
                log(f"可选文件 {name} 缺失，跳过（{e}）")
                continue
            raise
        if not spec.get("executable"):
            dest.chmod(0o644)


def update_manifest(stage: Path, app: dict, version: str, keep_checksum: bool) -> None:
    p = stage / "manifest"
    text = p.read_text(encoding="utf-8")
    updates = {
        "version": version,
        "desc": app["desc"].format(version=version),
        "changelog": app["changelog"].format(version=version),
    }
    if not keep_checksum:
        updates["checksum"] = "PLACEHOLDER"
    for key, value in updates.items():
        pattern = rf"(?m)^{re.escape(key)}\s*=.*$"
        text, n = re.subn(pattern, f"{key}={value}", text, count=1)
        if n != 1 and key != "checksum":
            raise RuntimeError(f"manifest 缺少字段：{key}")
        if n == 0 and key == "checksum":
            text = text.rstrip("\n") + f"\nchecksum={value}\n"
    p.write_text(text, encoding="utf-8")
    log(f"manifest 已更新：version={version}")


def update_wizard(stage: Path, app: dict, version: str) -> None:
    """更新安装向导里的提示文字（把「首次安装需联网下载」改为「已内置」）。"""
    new_text = app.get("wizard_help_text")
    for rel in ("wizard/install", "wizard/config"):
        p = stage / rel
        if not p.is_file() or not new_text:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        touched = False
        for step in data:
            for item in step.get("items", []):
                t = item.get("helpText")
                if isinstance(t, str) and ("GitHub Release" in t or "GitHub" in t):
                    item["helpText"] = new_text.format(version=version)
                    touched = True
        if touched:
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            log(f"已更新 {rel} 的说明文字")


def pack_tar(stage: Path, dist: Path, out_name: str) -> Path:
    """与旧仓 build_fpk.sh 一致：app/ -> app.tgz，md5 回填 manifest.checksum，再整体打包。"""
    subprocess.run(["tar", "-czf", str(stage / "app.tgz"), "-C", str(stage / "app"), "."], check=True)
    md5 = digest_of(stage / "app.tgz", "md5")
    p = stage / "manifest"
    text, n = re.subn(r"(?m)^checksum\s*=.*$", f"checksum={md5}", p.read_text(encoding="utf-8"))
    if n != 1:
        raise RuntimeError("manifest 的 checksum 字段异常")
    p.write_text(text, encoding="utf-8")
    shutil.rmtree(stage / "app")

    dist.mkdir(parents=True, exist_ok=True)
    out = dist / out_name
    entries = [e for e in ("manifest", "ICON.PNG", "ICON_256.PNG", "LICENSE", "app.tgz", "config", "cmd", "wizard")
               if (stage / e).exists()]
    subprocess.run(["tar", "-czf", str(out), "-C", str(stage), *entries], check=True)
    log(f"tar 打包完成：{out.name}")
    return out


def pack_fnpack(stage: Path, dist: Path, out_name: str) -> Path:
    """fnpack 会把产物写到当前工作目录，所以在临时目录里打包，避免影响 dist 下的其它产物。"""
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fnpack-out-") as td:
        outdir = Path(td)
        subprocess.run(["fnpack", "build", "--directory", str(stage)], check=True, cwd=str(outdir))
        built = next(outdir.glob("*.fpk"), None)
        if built is None:
            raise RuntimeError("fnpack 没有生成 fpk")
        out = dist / out_name
        shutil.copy2(built, out)
    out.chmod(0o644)
    log(f"fnpack 打包完成：{out.name}")
    return out


def self_check(out: Path, app: dict, version: str, keep_checksum: bool) -> None:
    with tempfile.TemporaryDirectory(prefix="fnos-verify-") as td:
        subprocess.run(["tar", "-xzf", str(out), "-C", td], check=True)
        stage = Path(td)
        manifest = (stage / "manifest").read_text(encoding="utf-8")
        want = {
            "appname": app["appname"],
            "platform": app.get("platform", "x86"),
            "version": version,
        }
        for key, value in want.items():
            if not re.search(rf"(?m)^{key}\s*=\s*{re.escape(value)}\s*$", manifest):
                raise RuntimeError(f"自检失败：manifest 的 {key} 不是 {value}")
        if not (stage / "app.tgz").is_file():
            raise RuntimeError("自检失败：缺少 app.tgz")
        checksum = re.search(r"(?m)^checksum\s*=\s*(\S+)\s*$", manifest)
        if checksum is None:
            raise RuntimeError("自检失败：manifest 没有 checksum")
        actual = digest_of(stage / "app.tgz", "md5")
        if checksum.group(1).lower() != actual:
            raise RuntimeError(f"自检失败：checksum {checksum.group(1)} != app.tgz {actual}")
        for d in ("config", "cmd", "wizard"):
            if not (stage / d).is_dir():
                raise RuntimeError(f"自检失败：缺少目录 {d}")
        log("自检通过：manifest 字段、app.tgz checksum、目录结构均正常")


def relay_fpk(app: dict, version: str, tag: str, dist: Path, token: str | None) -> int:
    """校验并原样转存上游 FPK，不解包到磁盘、不修改或重新打包。"""
    release = fetch_release(app["upstream_repo"], tag, token)
    asset = find_asset(release, app["asset_regex"])
    out_name = app["fpk_name"].format(version=version)
    dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fpk-relay-") as td:
        work = Path(td)
        archive = work / "upstream.fpk"
        http_get(asset["browser_download_url"], archive, token)
        if archive.stat().st_size != asset["size"]:
            raise RuntimeError("上游 FPK 下载大小不一致")
        sha = digest_of(archive, "sha256")
        expected = asset.get("digest")
        if expected and expected != f"sha256:{sha}":
            raise RuntimeError("上游 Release asset digest 校验失败")
        # 校验文件中的文件名必须与上游资产一致。
        named_archive = work / asset["name"]
        archive.rename(named_archive)
        verify_checksum(app, work, named_archive, release, token)
        with tarfile.open(named_archive, "r:gz") as package:
            members = {m.name.removeprefix("./"): m for m in package.getmembers()}
            manifest = package.extractfile(members["manifest"]).read().decode("utf-8")
            for key, value in {"appname": app["appname"], "version": version, "platform": "x86"}.items():
                if not re.search(rf"(?m)^{key}\s*=\s*{re.escape(value)}\s*$", manifest):
                    raise RuntimeError(f"上游 FPK 的 {key} 不符合预期 {value}")
            checksum = re.search(r"(?m)^checksum\s*=\s*(\S+)\s*$", manifest)
            h = hashlib.md5()
            with package.extractfile(members["app.tgz"]) as payload:
                for chunk in iter(lambda: payload.read(1024 * 1024), b""):
                    h.update(chunk)
            if checksum is None or checksum.group(1).lower() != h.hexdigest():
                raise RuntimeError("上游 FPK 的 app.tgz checksum 校验失败")
        out = dist / out_name
        shutil.copy2(named_archive, out)
        if digest_of(out, "sha256") != sha:
            raise RuntimeError("转存后的 FPK 与上游不一致")
    log(f"原样转存成功：{asset['name']} -> {out_name}（{out.stat().st_size} 字节）")
    print(f"sha256={sha}")
    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(f"fpk_name={out_name}\nfpk_path={out}\nfpk_sha256={sha}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="apps.json 中的应用 id")
    ap.add_argument("--version", help="上游版本号（不含 v 前缀）")
    ap.add_argument("--tag", help="上游 tag（含 v 前缀）")
    ap.add_argument("--config", help="单应用 JSON 文件（workflow 传入，优先于 --app）")
    ap.add_argument("--dist", default="dist")
    args = ap.parse_args()

    if args.config:
        app = json.loads(Path(args.config).read_text(encoding="utf-8"))
    else:
        cfg = json.loads((ROOT / "apps.json").read_text(encoding="utf-8"))
        matches = [a for a in cfg["apps"] if a["id"] == args.app]
        if not matches:
            log(f"apps.json 中没有 id={args.app}")
            return 2
        app = dict(matches[0])

    version = args.version or app.get("version")
    tag = args.tag or app.get("tag") or f"{app.get('tag_prefix', '')}{version}"
    if not version or not tag:
        log("缺少版本信息：需要 --version/--tag 或 config 中带 version/tag")
        return 2
    if not re.fullmatch(r"[0-9]+(\.[0-9]+)+([.\-+][0-9A-Za-z.\-]+)?", version):
        log(f"非法版本号：{version}")
        return 2

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    dist = ROOT / args.dist
    if app.get("strategy") == "github_fpk":
        return relay_fpk(app, version, tag, dist, token)
    template = ROOT / app["template"]
    if not template.is_dir():
        log(f"模板目录不存在：{template}")
        return 1

    log(f"应用 {app['id']}，上游 {app['upstream_repo']}，版本 {version}（tag {tag}）")
    source_build = app.get("strategy") == "github_source"
    npm_build = app.get("strategy") == "npm_package"
    substore_build = app.get("strategy") == "substore_release"
    if not source_build and not npm_build and not substore_build:
        release = fetch_release(app["upstream_repo"], tag, token)
        asset = find_asset(release, app["asset_regex"])
        log(f"选中上游资产：{asset['name']}（{asset['size']} 字节）")

    with tempfile.TemporaryDirectory(prefix=f"fnos-{app['id']}-") as td:
        work = Path(td)
        stage = work / "stage"
        shutil.copytree(template, stage)
        if substore_build:
            from build_substore import build
            build(app, version, tag, stage, work, token)
        elif npm_build:
            from build_ekko import build
            build(app, version, stage, work)
        elif source_build:
            build_source(app, ROOT / '.work/source', stage, work)
        else:
            archive = work / asset["name"]
            http_get(asset["browser_download_url"], archive, token)
            log(f"下载完成：{archive.stat().st_size} 字节")
            verify_checksum(app, work, archive, release, token)
            extract_member(archive, app["archive_type"], app["inner_binary"], stage / app["binary_dest"])
            copy_extra_from_archive(archive, app["archive_type"], app.get("copy_from_archive", []), stage)

        keep_checksum = app.get("packer") == "fnpack"
        update_manifest(stage, app, version, keep_checksum)
        update_wizard(stage, app, version)

        out_name = app["fpk_name"].format(version=version)
        if app.get("packer") == "fnpack":
            out = pack_fnpack(stage, dist, out_name)
        else:
            out = pack_tar(stage, dist, out_name)

        self_check(out, app, version, keep_checksum)
        if source_build:
            from build_source import verify_embedded
            verify_embedded(out, app)
        size = out.stat().st_size
        sha = digest_of(out, "sha256")
        log(f"构建成功：{out}（{size} 字节）")
        print(f"sha256={sha}")

    out_file = os.environ.get("GITHUB_OUTPUT")
    if out_file:
        with open(out_file, "a", encoding="utf-8") as f:
            f.write(f"fpk_name={out_name}\n")
            f.write(f"fpk_path={dist / out_name}\n")
            f.write(f"fpk_sha256={sha}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
