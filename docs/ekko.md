# Ekko Studio fnOS 包

沿用集中构建、每日两轮检测、日期 Release 和 FnDepot 双版本索引。仅 x86；不修改其他应用策略。

兼容 shuangji66 原包：产物 `Ekko-{version}-x86.fpk`，应用标识 `Ekko`、显示名 `Ekko Studio`、桌面入口 `Ekko.Application`、package 用户和 Ekko 共享目录不变；安装向导字段仍为 `port`，默认 8770。既有用户的自定义端口（例如 8770）保持原值，不强制重置。npm 包使用官方新名称 `ekko-studio`，不等于改 fnOS 应用身份。

升级定向迁移 default/当前 profile 的旧 MCP 路径，先留原文件备份，保留环境变量、端口与开关状态。不批量修改其他 profile。配置变更时，仅对已运行应用重新启停以应用新端口。停机宽限延长至 90 秒，但包含真实 Gateway 的停机仍需真机回归。

## 历史告警补丁与上游更新

历史处理补丁只改善告警：仅有 reasoning 的记录继续过滤但不误报警；真正的空消息按会话/原始消息 ID 去重（FIFO 最多 1024）。保留正文、工具调用、过滤规则、非枚举 cursorId、游标上下文和投影；不修改或清理聊天数据库。

补丁标识为 `history-reasoning-classification-v3`，继续严格校验已审查布局，不依赖模糊替换。**未知布局不再阻断整个 FPK 更新**：保留官方 bundle 原始字节并明确 warning，`BUILD.json` 中 `patches=[]`、`history_patch.status=skipped_unsupported`。已适配并应用补丁则必须通过真实函数回归，才记录 `status=applied`。重复/残缺补丁、意外异常、应用后的测试失败不能降级跳过。未知版可能暂时保留上游重复/误判空消息告警，不宣称完成其历史函数语义回归。

完整策略、测试和不发布的新版验证入口见 [Ekko 上游更新兼容策略](ekko-upstream-compatibility.md)。旧 0.8.16 修复背景见 [历史补丁修复记录](ekko-history-fix.md)。

实际历史函数回归在 Actions 内执行，覆盖 0.8.14 / 0.8.16 的 reasoning-only、thinking 解析、正文与 tool_use、输出与输入不变、cursor 描述符、工具截断、excludeLastUser、projection 与 full/cursor 上下文，验证跨 load/build 去重、独立会话/原始 ID 和 FIFO 上限。DB 读取和运行时 projection 使用 fixture，不访问真实数据库或 Agent。未知布局只验证原文不变和语法，并由完整构建强制执行运行时检查；这些不替代真实历史语义和 fnOS 验收。

## 运行时与数据保留

- 应用标识 `Ekko`，沿用第三方包的数据共享目录 `Ekko`，默认端口 8770（安装/配置向导可改）。覆盖安装可能继续使用既有 Ekko 数据，操作前由用户备份；不会自动导入其他应用数据。
- 从 npm registry 的 `ekko-studio` latest 获取正式版本并固定版本安装，内置 Node 24.22.0。Actions Debian 12 容器安装编译工具，正常执行 npm lifecycle，不用 `--ignore-scripts` 绕过 node-pty 编译。
- Node 官方 SHA256 与 npm registry integrity 校验；记录实际依赖清单与来源。FPK 复用现有 tar packer 和完整性自检。
- 飞牛模板在 `apps/ekko/`；遵循 shuangji66/buildbot 的目录兼容约定：服务在 `${TRIM_APPDEST}/server`，Node/npm 及全局工具在 `${TRIM_PKGVAR}/node`（原包的 Codex 安装位置）。target 内 Node 只作安装种子；安装/升级按版本覆盖运行时文件，不删除持久目录或第三方全局包。启动 PATH 和 `NPM_CONFIG_PREFIX` 指向持久 Node，HOME 仍为 Ekko 共享目录，升级不覆盖会话、配置及 Agent 数据。保留进程身份检查、90秒优雅停机、端口保护。卸载脚本不主动删除共享数据；若飞牛卸载时选择清除应用数据，PKGVAR 下工具可能随之删除，应先备份。
- 构建冒烟测试加入持久 Codex 替身、重复升级保留及 npm prefix 检查；替身只验证发现链路，不代表真实 Codex 登录/模型调用通过。新包生效需安装/升级后重新启动，仓库修改不直接改变当前 NAS 服务。
- Actions 检查 node-pty 实际 PTY、sharp 加载、隔离 HOME 下 Web HTTP /health 与前端、生命周期启停与升级数据保留；不连接生产 NAS，不把 CI 冒烟测试等同于真机验收。
- FPK 内置 Web 工作台和 Node，不预装所有 Agent、模型或浏览器；首次配置这些功能仍可能需要联网。
- 保留上游 BSL 1.1；仅非商业用途授权，商业使用需向 EKKOLearnAI 另行获取许可。图标来自上游 npm 包。

手动入口：Auto build fnOS FPK，`app=ekko`（应用 id 区分大小写，不是 `Ekko`）；重新编译同版本时 `force=true`，验证构建选 `publish=false`。检查器自动查询最新 npm 版本。正常升级由每日调度发现 npm 新版本后构建。独立兼容验证流程只生成 artifact，不发布。

压缩布局跟随原包：服务先压为 `server.tar.xz`，Node 保留经过 SHA256 校验的官方 `node.tar.xz`；安装时展开到程序目录与持久运行时目录。压缩前后各运行一次隔离生命周期测试，最终 FPK 不重复携带展开的 server/node。压缩归档在安装后保留，供同版本修复/重复升级使用，不删除用户全局工具。
