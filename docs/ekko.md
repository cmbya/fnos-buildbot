# Ekko Studio fnOS 包

沿用集中构建、每日两轮检测、日期 Release 和 FnDepot 双版本索引。仅 x86；不修改其他应用策略。

兼容 shuangji66 原包：产物 `Ekko-{version}-x86.fpk`，应用标识 `Ekko`、显示名 `Ekko Studio`、桌面入口 `Ekko.Application`、package 用户和 Ekko 共享目录不变；安装向导字段仍为 `port`，默认 8770。既有用户的自定义端口（例如 8770）保持原值，不强制重置。npm 包使用官方新名称 `ekko-studio`，不等于改 fnOS 应用身份。

升级定向迁移 default/当前 profile 的旧 MCP 路径，先留原文件备份，保留环境变量、端口与开关状态。不批量修改其他 profile。配置变更时，仅对已运行应用重新启停以应用新端口。停机宽限延长至 90 秒，但包含真实 Gateway 的停机仍需真机回归。重复空消息日志属于上游问题，本包不修改聊天数据库或上游日志处理代码。

- 应用标识 `Ekko`，沿用第三方包的数据共享目录 `Ekko`，默认端口 8770（安装/配置向导可改）。覆盖安装可能继续使用既有 Ekko 数据，操作前由用户备份；不会自动导入其他应用数据。
- 从 npm registry 的 `ekko-studio` latest 获取正式版本并固定版本安装，内置 Node 24.22.0。Actions Debian 12 容器安装编译工具，正常执行 npm lifecycle，不用 `--ignore-scripts` 绕过 node-pty 编译。
- Node 官方 SHA256 与 npm registry integrity 校验；记录实际依赖清单与来源。FPK 复用现有 tar packer 和完整性自检。
- 程序和 Node 都放在只读 target；HOME 使用 fnOS 创建的 Ekko 共享目录，升级不覆盖会话、配置及 Agent 数据。卸载脚本不主动删除共享数据。
- Actions 检查 node-pty 实际 PTY、sharp 加载、隔离 HOME 下 Web HTTP /health 与前端、生命周期启停与升级数据保留；不连接生产 NAS，不把 CI 冒烟测试等同于真机验收。
- FPK 内置 Web 工作台和 Node，不预装所有 Agent、模型或浏览器；首次配置这些功能仍可能需要联网。
- 保留上游 BSL 1.1；仅非商业用途授权，商业使用需向 EKKOLearnAI 另行获取许可。图标来自上游 npm 包。

手动入口：Auto build fnOS FPK，app=ekko。正常升级由每日调度发现 npm 新版本后构建。
