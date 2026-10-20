# Ekko Studio fnOS 包

沿用集中构建、每日两轮检测、日期 Release 和 FnDepot 双版本索引。仅 x86；不修改其他应用策略。

- 应用标识 `Ekko`，沿用第三方包的数据共享目录 `Ekko`，默认端口 8758（安装/配置向导可改）。覆盖安装可能继续使用既有 Ekko 数据，操作前由用户备份；不会自动导入其他应用数据。
- 从 npm registry 的 `ekko-studio` latest 获取正式版本并固定版本安装，内置 Node 24.22.0。Actions Debian 12 容器安装编译工具，正常执行 npm lifecycle，不用 `--ignore-scripts` 绕过 node-pty 编译。
- Node 官方 SHA256 与 npm registry integrity 校验；记录实际依赖清单与来源。FPK 复用现有 tar packer 和完整性自检。
- 程序和 Node 都放在只读 target；HOME 使用 fnOS 创建的 Ekko 共享目录，升级不覆盖会话、配置及 Agent 数据。卸载脚本不主动删除共享数据。
- Actions 检查 node-pty 实际 PTY、sharp 加载、隔离 HOME 下 Web HTTP /health 与前端、生命周期启停与升级数据保留；不连接生产 NAS，不把 CI 冒烟测试等同于真机验收。
- FPK 内置 Web 工作台和 Node，不预装所有 Agent、模型或浏览器；首次配置这些功能仍可能需要联网。
- 保留上游 BSL 1.1；仅非商业用途授权，商业使用需向 EKKOLearnAI 另行获取许可。图标来自上游 npm 包。

手动入口：Auto build fnOS FPK，app=ekko。正常升级由每日调度发现 npm 新版本后构建。
