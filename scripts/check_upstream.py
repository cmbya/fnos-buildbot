#!/usr/bin/env python3
"""检查上游是否有新版本，输出需要构建的应用列表。

用法:
    python3 scripts/check_upstream.py                 # 检查全部应用
    python3 scripts/check_upstream.py --app openlist  # 只检查一个应用
    python3 scripts/check_upstream.py --force         # 忽略已发布版本，强制构建

输出（写入 $GITHUB_OUTPUT，本地运行时打印）:
    changed = [{"id": "...", "version": "...", "tag": "...", ...}, ...]
    count   = N
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS_JSON = ROOT / "apps.json"
GH_API = "https://api.github.com"


def log(msg: str) -> None:
    print(msg, flush=True)


def gh_get(url: str, token: str | None) -> dict | list:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "fnos-buildbot/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def latest_release(repo: str, tag_prefix: str, token: str | None) -> tuple[str, str]:
    """返回 (tag, version)。只接受正式 Release，跳过 draft / prerelease。"""
    data = gh_get(f"{GH_API}/repos/{repo}/releases?per_page=30", token)
    for rel in data:
        if rel.get("draft") or rel.get("prerelease"):
            continue
        tag = rel["tag_name"]
        version = tag[len(tag_prefix):] if tag_prefix and tag.startswith(tag_prefix) else tag
        if not version:
            continue
        return tag, version
    raise RuntimeError(f"{repo} 没有找到正式 Release")


def published_versions(appname: str, target_repo: str, token: str | None) -> set[str]:
    """从目标仓库的 fnpack.json 读取该应用已经发布的版本集合。"""
    try:
        data = gh_get(f"{GH_API}/repos/{target_repo}/contents/fnpack.json", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return set()
        raise
    import base64
    raw = base64.b64decode(data["content"]).decode("utf-8")
    index = json.loads(raw)
    app = (index.get("apps") or {}).get(appname) or {}
    return set((app.get("releases") or {}).keys())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", help="只检查指定应用 id")
    ap.add_argument("--force", action="store_true", help="忽略已发布版本，强制构建")
    ap.add_argument("--config", default=str(APPS_JSON))
    args = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    target_repo = config["target_repo"]

    apps = config["apps"]
    if args.app:
        apps = [a for a in apps if a["id"] == args.app]
        if not apps:
            log(f"错误：apps.json 中没有 id={args.app}")
            return 2

    changed: list[dict] = []
    for app in apps:
        aid = app["id"]
        if app.get("strategy") != "github_release":
            log(f"[跳过] {aid}：strategy={app.get('strategy')} 暂不支持")
            continue
        try:
            tag, version = latest_release(app["upstream_repo"], app.get("tag_prefix", ""), token)
        except Exception as e:  # noqa: BLE001
            log(f"[错误] {aid}：读取上游版本失败：{e}")
            continue

        try:
            done = published_versions(app["appname"], target_repo, token)
        except Exception as e:  # noqa: BLE001
            log(f"[警告] {aid}：读取 FnDepot 索引失败（按未发布处理）：{e}")
            done = set()

        if not args.force and version in done:
            log(f"[最新] {aid}：{version} 已发布，跳过")
            continue

        log(f"[构建] {aid}：上游 {tag}（版本 {version}）")
        item = dict(app)
        item["tag"] = tag
        item["version"] = version
        changed.append(item)

    payload = json.dumps(changed, ensure_ascii=False, separators=(",", ":"))
    log(f"需要构建：{len(changed)} 个 -> {[c['id'] for c in changed]}")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"changed={payload}\n")
            f.write(f"count={len(changed)}\n")
    else:
        print("changed=" + payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
