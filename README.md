# fnos-buildbot

飞牛 fnOS（fnOS）第三方应用的**集中自动构建仓**。

每天北京时间 10:05 / 22:05（GitHub cron 用 UTC：`02:05` / `14:05`）检查上游有没有新版本；
有新版本才编译 x86 架构的 FPK，推送到 [`cmbya/FnDepot`](https://github.com/cmbya/FnDepot) 的**日期 Release**，
再由 FnDepot 自己的索引脚本更新 `fnpack.json`。

## 为什么这样做

原来每个应用一个仓库、一份 workflow，改一处公共逻辑要改 N 遍。
现在：**一套骨架 + 每个应用一条配置**。加应用只改 `apps.json` 和放一份模板目录，不用动 workflow。

## 目录结构

```
.
├─ .github/workflows/
│  ├─ auto-build.yml      主流程：定时/手动 → 检测 → 构建(matrix) → 发布 → 触发索引
│  └─ build-app.yml       可复用子流程：构建单个应用
├─ apps/                  每个应用一份 fnOS 打包模板
│  ├─ openlist/           manifest / cmd / config / wizard / app / 图标
│  ├─ cliproxyapi/
│  └─ taosync/
├─ scripts/
│  ├─ check_upstream.py   检测上游新版本，对比 FnDepot 已发布版本
│  └─ build_app.py        取包 → 校验 → 解压 → 注入版本 → 打包 → 自检
└─ apps.json              应用注册表（唯一需要维护的清单）
```

## 加一个新应用

1. 在 `apps/` 下新建目录（可从现有目录复制改造），放入 `manifest`、`cmd/`、`config/`、`wizard/`、图标等。
2. 在 `apps.json` 的 `apps` 数组里加一条记录，至少填：
   - `id`、`name`、`appname`（**必须与 FnDepot 索引里的 app key 一致**）
   - `template`、`strategy`、`upstream_repo`、`tag_prefix`
   - `asset_regex`、`archive_type`、`inner_binary`、`binary_dest`
   - `packer`（`tar` 或 `fnpack`）、`fpk_name`
3. 手动触发一次 `Auto build fnOS FPK`，`app` 填新应用的 `id` 验证。

> ⚠️ `appname` 与 FnDepot 索引 key 不一致时，客户端会把它当成另一个应用，**不会提示更新**。

## 打包方式（packer）

| 值 | 行为 | 用在 |
|---|---|---|
| `tar` | 脚本自己把 `app/` 压成 `app.tgz`，MD5 回填 `manifest.checksum`，再整体 `tar -czf` | OpenList、TaoSync（沿用旧仓逻辑） |
| `fnpack` | 调用飞牛官方 `fnpack build`（自动打 `app.tgz` 并回填 checksum） | CLIProxyAPI |

## 取包策略（strategy）

| 值 | 状态 | 说明 |
|---|---|---|
| `github_release` | ✅ 已实现 | 从上游 Release 按 `asset_regex` 下载 x86 产物 |
| `npm_package` | 计划中 | biliLive-tools：npm registry + 补丁校验 |
| `github_source_tag` | 计划中 | StreamCap、MeTube：源码 tag + 补丁 / FFmpeg 校验 |
| `docker_registry` | 计划中 | LitePan：从 Docker Hub 抽取二进制 |

## 上游版本命名

**版本号直接跟随上游**，不加 `-nativeN` 后缀。
原因：后缀会导致版本号无法比较，用户可能收不到更新提示。

## 需要配置的 Secret

| 名称 | 内容 | 权限 |
|---|---|---|
| `FNDEPOT_TOKEN` | Fine-grained PAT | 仅 `cmbya/FnDepot`：Contents 读写、Actions 读写 |

**这个 token 只对 FnDepot 有写权限**，不会外泄到其它仓库。

## 手动触发

Actions → **Auto build fnOS FPK** → Run workflow：

| 输入 | 说明 |
|---|---|
| `app` | 只构建指定应用（如 `openlist`）；留空=全部 |
| `force` | 忽略「已发布」判断，强制重建 |
| `dry_run` | 只检测不构建 |

## 本地验证（不联网构建也可跑通打包）

```bash
python3 scripts/check_upstream.py            # 看上游有哪些新版本
python3 scripts/build_app.py --app openlist --version 4.2.7 --tag v4.2.7
```

产物在 `dist/`。

## 注意

- 构建产物**尚未在真实飞牛设备上完整安装回归测试**，请自行验证后再用于正式环境。
- 应用源码与版本来自各自上游，本仓只做 fnOS 封装。
- 二进制已**内置在 FPK 中**（构建时下载），安装与升级不需要 NAS 联网访问 GitHub。
