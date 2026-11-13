# Sub-Store 原生应用

## 实现与边界

- 保留 `appname=Sub-Store`，默认端口 `21678`，可在飞牛应用配置修改端口。
- 依赖飞牛 `nodejs_v24`，包内不带 Node、不使用 Docker/Nginx。
- 一个 Node 进程运行官方 `sub-store.bundle.js`，前后端合并模式。未配置时兼容默认 API `/path`；安装后通过网页“服务器设置 / 连接后端”配置持久的实际公开 API 前缀和额外 CORS 来源。
- 后端跟随正式 Release，检测时锁定前端正式 Release tag，构建时校验 asset SHA256 与大小，不取移动分支。
- 前端采用官方 `dist.zip`，替换唯一默认 API 常量为 `/path` 并插入无秘密的 fnOS 设置引导脚本，更新 gzip 和 Workbox revision。公开文件不写入用户配置的随机路径。
- `app/runtime/settings.cjs` 作为 Node 预加载层，在同一个监听端口映射动态前缀；不增加依赖或第二个公开服务端口。旧公开前缀切换后拒绝，内部 bundle 路径不是外部别名。
- `${TRIM_PKGVAR}` 保存原有订阅、日志与 PID，以及 `fnos-server-settings.json` 和权限 0600 的 `fnos-settings.key`；安装、升级不清理，卸载默认保留数据。
- 保留桌面 iframe 入口和 package 用户身份。启动通过只允许本机并验证管理密钥的 `/_fnos/health` 检查上游 API；停止验证进程身份。
- 包内 `BUILD.json` 记录 tag、下载校验与前端两类修改；保留后端 AGPL-3.0、前端 GPL-3.0 许可证与精确源码链接。

## 安装后修改来源和 API 路径

详细操作、接口安全、恢复与限制见 [网页服务器设置](substore-server-settings.md)。不是新增 FPK 安装/配置向导字段，也不是只改浏览器后端列表。

浏览器入口为网页右下角“服务器设置 / 连接后端”，或 `/_fnos/settings`。首次管理须从 NAS 应用数据目录本机读取管理密钥；不要分享密钥或新路径。来源可留空、多个来源精确匹配；API 路径可反复修改，保存后持久生效无需重启。当前浏览器记住新路径；其他设备需要手动填写。设置损坏时拒绝启动，不退回默认路径。

## 安全说明

**路径不是登录密码，CORS 不是身份认证。** 上游 API 没有额外全局登录层，管理密钥仅保护 fnOS 设置接口。公网应使用可信 VPN 或带鉴权的反代，特别是默认 /path 尚未修改时。不要用 * 关闭来源检查。

启动按当前 NAS 接口地址、主机名和端口生成内网白名单；端口/接口变化后重新启动以更新自动项。管理员的 `SUB_STORE_CORS_ALLOWED_ORIGINS` 精确列表可覆盖自动项，网页额外来源仍与基础列表合并。前缀轮换不撤销独立 `/share` 分享令牌，也不删除订阅数据。ESA 代理应绕过 API 和管理页缓存。

## 构建与发布

本次网页设置功能仅提交源码/测试；用户明确禁止本地执行、编译和打包，因此**新增测试全部未运行，未生成 FPK，未发布，未做真机回归**。需后续授权验证，不能据此直接宣称生产可用。

既有构建入口为 `Auto build fnOS FPK`（定时/手动，无 push 触发）。测试新封装重建同版本时需后续授权 `app=substore`、`force=true`、`dry_run=false`，是否发布单独确认。仅验证包时应设置 `publish=false`。本次不触发该流程，也不改变原来的定时任务。

后端无新正式版本通常会跳过；前端或封装单独更新需手动 force 才会重打，前端 tag 应固定。产物名 `Sub-Store-{version}-all.fpk`，发布后沿用 FnDepot 日期 Release/索引。all 模板不扩大现有 x86 商店范围。

后续授权测试命令及未覆盖的浏览器/官方 bundle 集成项目详见网页设置文档。旧包的测试脚本 `scripts/test_substore.py` 也需在后续联调中回归；不能把新隔离网关测试替代完整安装升级测试。

## 上游与许可

- 后端：https://github.com/sub-store-org/Sub-Store （AGPL-3.0）
- 前端：https://github.com/sub-store-org/Sub-Store-Front-End （GPL-3.0）
- 封装：https://github.com/cmbya/fnos-buildbot/tree/main/apps/substore
- 参考：shuangji66/FnDepot Sub-Store 2.39.9；生命周期脚本在本仓重新实现。
