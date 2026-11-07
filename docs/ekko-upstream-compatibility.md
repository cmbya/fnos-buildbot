# Ekko 上游更新兼容策略

## 问题

检测器跟随 npm `ekko-studio` latest，但历史消息告警补丁和真实函数 VM 回归依赖已审查 bundle 的混淆函数名、边界与代码哈希。上游重新打包，即使只是内部名字变化，也可能不再匹配。此前无条件打补丁并执行固定布局测试，导致可选的告警优化阻断整个 FPK 更新。

## 当前策略

- `patch_ekko_history.py` 仍是严格补丁工具；不做模糊替换、不扩大哈希白名单、不改变过滤、工具调用、上下文投影或数据库。
- `UnsupportedHistoryLayout` 仅在所有写入前表示未匹配已审查布局。
- `ekko_history_policy.prepare_history` 只捕获上述类型，并再次逐字节确认原文不变。未知布局保留官方代码，发出明确 warning；不再执行不适用于该 bundle 的固定布局补丁测试。
- 重复/残缺补丁、意外异常、文件系统错误、JavaScript 语法错误以及应用补丁后的回归失败依然终止构建，绝不回退为成功。
- 已审查布局仍必须执行实际 load/build 函数差分测试。
- 无论补丁是否应用，Node 校验、固定 npm 包身份、真实 node-pty/sharp、MCP 初始化、布局、HTTP 健康与前端、端口变更、压缩前后安装升级/停止及数据保留、FPK manifest/checksum 自检仍为强制检查。

未知版本可能暂时保留上游的重复/误判空消息告警。这比对未经审查的混淆代码猜测式修改更安全；如需适配告警补丁，应单独审查后增加适配，不阻断官方包的正常更新。此策略不保证未来所有上游依赖或运行不兼容都自动通过。

## 可追溯信息

FPK 的 `app/native/BUILD.json` 保留包版本、Node 校验与依赖来源，并新增 `history_patch`：

- `status=applied`：`patches` 包含真实补丁 ID，`regression=passed`。
- `status=skipped_unsupported`：`patches=[]`，原始与打包 bundle SHA256 相同，`regression=not_applicable_unmodified_upstream`，不宣称测试过未知历史函数。

构建还上传独立 `ekko-compatibility-evidence` artifact，不改变原 `fpk-ekko` artifact 的目录结构。

## 云端验证（不发布）

`Verify Ekko upstream compatibility (no publish)` 在相关修复 main push 或手动启动时：

1. 检测 latest 或读取指定版本，固定一个正式 npm 版本供本次测试与构建共用。
2. 运行 0.8.14 / 0.8.16 原有严格补丁回归。
3. 运行未知布局、字节不变、部分写入、重复/残缺补丁、意外异常、语法与回归失败不可吞掉、元数据真实性测试，再验证本次实际版本（tarball SHA512 核验）。
4. 复用原 Debian 12 构建链，生成 FPK artifact；没有发布任务、不读取 FNDEPOT_TOKEN、不上传 Release、不刷新 FnDepot 索引。
5. 将本次 run/commit、步骤结果、补丁元数据及有界脱敏错误信息写入 `docs/ekko-compat-ci.json`。这是云端结果，不是修改代码即视为成功。

原每日调度和其既有发布策略不变。原 `Verify and release Ekko history fix` 是固定 0.8.16 的历史恢复流程，**不要用它验证新版**，它有发布/同名覆盖副作用。

保留上游 BSL 1.1 与 LICENSE，商业使用仍需上游许可。本流程不在 NAS 安装软件、启动生产服务或读写用户聊天数据库；未替代真实 fnOS 安装升级及 Agent/浏览器验收。
