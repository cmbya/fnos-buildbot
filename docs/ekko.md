# Ekko Studio fnOS 包

沿用集中构建、每日两轮检测、日期 Release 和 FnDepot 双版本索引。仅 x86；不修改其他应用策略。

兼容 shuangji66 原包：产物 `Ekko-{version}-x86.fpk`，应用标识 `Ekko`、显示名 `Ekko Studio`、桌面入口 `Ekko.Application`、package 用户和 Ekko 共享目录不变；安装向导字段仍为 `port`，默认 8770。既有用户的自定义端口（例如 8770）保持原值，不强制重置。npm 包使用官方新名称 `ekko-studio`，不等于改 fnOS 应用身份。

升级定向迁移 default/当前 profile 的旧 MCP 路径，先留原文件备份，保留环境变量、端口与开关状态。不批量修改其他 profile。配置变更时，仅对已运行应用重新启停以应用新端口。停机宽限延长至 90 秒，但包含真实 Gateway 的停机仍需真机回归。历史处理补丁：仅有 reasoning 的记录继续过滤但不误报警；真正的空消息按会话/消息 ID 去重告警（最多缓存 1024 个键）。保留正文、工具调用及过滤规则；不修改或清理聊天数据库。补丁匹配不到上游代码即阻止发布，Actions 执行真实历史函数回归测试。

- 应用标识 `Ekko`，沿用第三方包的数据共享目录 `Ekko`，默认端口 8770（安装/配置向导可改）。覆盖安装可能继续使用既有 Ekko 数据，操作前由用户备份；不会自动导入其他应用数据。
- 从 npm registry 的 `ekko-studio` latest 获取正式版本并固定版本安装，内置 Node 24.22.0。Actions Debian 12 容器安装编译工具，正常执行 npm lifecycle，不用 `--ignore-scripts` 绕过 node-pty 编译。
- Node 官方 SHA256 与 npm registry integrity 校验；记录实际依赖清单与来源。FPK 复用现有 tar packer 和完整性自检。
- 飞牛模板在 `apps/ekko/`；遵循 shuangji66/buildbot 的目录兼容约定：服务在 `${TRIM_APPDEST}/server`，Node/npm 及全局工具在 `${TRIM_PKGVAR}/node`（原包的 Codex 安装位置）。target 内 Node 只作安装种子；安装/升级按版本覆盖运行时文件，不删除持久目录或第三方全局包。启动 PATH 和 `NPM_CONFIG_PREFIX` 指向持久 Node，HOME 仍为 Ekko 共享目录，升级不覆盖会话、配置及 Agent 数据。保留进程身份检查、90秒优雅停机、端口保护及历史补丁。卸载脚本不主动删除共享数据；若飞牛卸载时选择清除应用数据，PKGVAR 下工具可能随之删除，应先备份。
- 构建冒烟测试加入持久 Codex 替身、重复升级保留及 npm prefix 检查；替身只验证发现链路，不代表真实 Codex 登录/模型调用通过。新包生效需安装/升级后重新启动，仓库修改不直接改变当前NAS服务。
- Actions 检查 node-pty 实际 PTY、sharp 加载、隔离 HOME 下 Web HTTP /health 与前端、生命周期启停与升级数据保留；不连接生产 NAS，不把 CI 冒烟测试等同于真机验收。
- FPK 内置 Web 工作台和 Node，不预装所有 Agent、模型或浏览器；首次配置这些功能仍可能需要联网。
- 保留上游 BSL 1.1；仅非商业用途授权，商业使用需向 EKKOLearnAI 另行获取许可。图标来自上游 npm 包。

手动入口：Auto build fnOS FPK，app=ekko。正常升级由每日调度发现 npm 新版本后构建。
