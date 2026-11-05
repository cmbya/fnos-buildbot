# Ekko 0.8.16 历史补丁兼容修复

## 原因

0.8.16 npm bundle 将旧布局曾使用的 `W8e` 名字分配给了 preview 模块的延时函数；历史 load/build 函数实际为 `VWr` / `Mrt`。旧适配器仅凭函数锚点误选旧布局，随后精确告警替换校验失败，因而中止 FPK 构建。npm 新版本提示不是失败原因。

## 修复

- 补丁标识更新为 `history-reasoning-classification-v3`。
- 组合布局边界、两处告警及 logger 选择适配器，不再仅凭混淆函数名判断。
- 0.8.16 固定 `function wWr(` 至 `var R$=` 的已审查区段 SHA256：`f9d25c57cf9e1310d0d2ee6d8bf0a0c2baec717341126e28081d33530f752174`。0.8.14 原有区段校验保留。
- 仍只增加告警分类/去重 helper 并替换两处告警；不改消息过滤、模型历史内容、工具链、游标描述符、投影和数据库。
- 回归测试执行 npm bundle 的真实历史函数；fixture 只替代数据库读取和外部 runtime 投影边界。
- 测试覆盖 0.8.14 / 0.8.16、reasoning-only、thinking 解析、工具链、游标、截断、projection，以及重复补丁、重复/缺失告警、区段变化和不产生部分写入。

## 云端验证和发布

`Verify and release Ekko history fix` 为本次定向恢复流程：固定 0.8.16，先历史回归，再调用原有 `build-app.yml` 完成 Debian 12 下 native、隔离生命周期、压缩前后冒烟测试和 FPK 自检；仅全部成功后发布 Ekko 产物到 FnDepot 日期 Release（同名资产按现有约定覆盖）并刷新索引。

流程仅在该工作流文件变更的 main push 或手动运行时启动，不对其他应用新增自动构建触发，不更改原有每日检查。云端结果保存为 `docs/ekko-ci-result.json`，状态与 run URL 是验收依据，提交修复不等于构建成功。

上游 npm tarball 的 SHA512 来自 registry；记录的 bundle SHA256 为 `b2ee9dfdd3036b29b1884659a32557b2fc7496370d86a9d9d203fb3159bdf4c0`。不在 NAS 本地安装依赖、下载构建工具、启动服务或编译。保留上游 BSL 1.1，商业使用仍须另行获得上游授权。

真机安装、升级、实际 Agent 调用及完整浏览器交互未由本流程验证。详见原有 `docs/ekko.md` 的数据保留、迁移和授权说明；其中 v2 是修复前记录，当前补丁以 v3 为准。
