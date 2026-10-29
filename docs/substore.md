# Sub-Store 原生应用

## 实现与边界

- 保留 `appname=Sub-Store`，默认端口 `21678`，可在安装/配置向导修改。
- 依赖飞牛应用 `nodejs_v24`，包内不带 Node、不使用 Docker/Nginx。
- 一个 Node 进程运行官方 `sub-store.bundle.js`，开启前后端合并模式；前端默认 API `/path`。
- 后端跟随正式 Release；检测时锁定前端正式 Release tag，构建时校验 GitHub asset SHA256 与下载大小。不取移动分支，不转存第三方 FPK。
- 前端采用官方 `dist.zip`，只替换默认 API 常量为 `/path`；要求唯一匹配，否则停止构建；重建对应 gzip 和 PWA precache revision。
- 包内 `BUILD.json` 记录前后端 tag、上游下载 SHA256 与前端修改信息；附带后端 AGPL-3.0、前端 GPL-3.0 许可证及源码链接。
- `${TRIM_PKGVAR}` 保存 `sub-store.json`、`root.json`、日志与 PID；安装、升级不清理数据。卸载默认保留数据，明确选择删除才清空该目录。
- 保留参考包的桌面 iframe 入口和 package 用户身份。端口启动时校验，启动检测本机 `/path/api/utils/env`，停止验证进程身份，避免误杀其他 PID。

## 安全说明

这是无额外登录层的本地管理服务。`/path` 不是密码；不要直接将端口暴露到公网。远程访问需可信 VPN 或带鉴权的反向代理。
不沿用参考包的任意来源 CORS `*`，使用上游默认策略；同源前端无需开启任意跨域。

## 构建与发布

复用 `Auto build fnOS FPK`：`app=substore`。默认定时检查后端新正式版本，无更新则跳过；前端单独更新时需 `force=true` 重打当前后端版本。
产物名 `Sub-Store-{version}-all.fpk`，发布到 FnDepot 日期 Release，沿用索引更新流程。当前 FnDepot 客户端源以 x86 为收录范围；模板本身为 all，不扩张商店现有平台范围。

本地：

```bash
python3 scripts/check_upstream.py --app substore
python3 scripts/build_app.py --app substore --version 2.44.2 --tag 2.44.2
python3 scripts/test_substore.py
```

本地直接构建会解析最新前端正式 Release，流水线使用检测阶段传入的固定 `frontend_tag`。运行测试需要 Node 24，可通过 `SUBSTORE_TEST_NODE` 指定。
验证包括校验失败拒绝、前端资源/PWA 一致性、实际 HTTP 前端/API、订阅写入重启后保留及退出；不等于真实 fnOS 安装、升级或外部订阅服务验收。

## 上游与许可

- 后端：https://github.com/sub-store-org/Sub-Store （AGPL-3.0）
- 前端：https://github.com/sub-store-org/Sub-Store-Front-End （GPL-3.0）
- 封装：https://github.com/cmbya/fnos-buildbot/tree/main/apps/substore
- 实现参考：shuangji66/FnDepot 的 Sub-Store 2.39.9 包；生命周期脚本在本仓重新实现。
