# 验收报告入口

当前任务与已验收范围只看[交接](../CODEX_HANDOFF.md)。按交接点名读取证据，不以历史报告的
`ready_for_review`、阶段名称或文件日期推断当前仍待审、已完成或需要重跑。

- 未被现行验证入口引用的历史报告已从当前树移除。需要追溯时使用
  `git show c3b3483:hsr_v075_baseline_clean/hsr/live_validation_reports/<原相对路径>`。
- 当前保留的报告由 CI 中仍使用的验证器直接引用，不代表新的验收要求。
- [工程文档与归档索引](../simulator_v8_clean_core/DOCUMENTATION_INDEX.md)。

新证据沿当前任务的现有说明记录即可；本目录不另建任务账本，也不要求每批新增一份报告。
