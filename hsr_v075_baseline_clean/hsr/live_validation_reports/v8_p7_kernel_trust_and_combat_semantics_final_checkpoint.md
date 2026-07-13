# v8 P7 内核可信执行与战斗语义回正最终检查点

## 验收状态

```text
accepted=true
p7_done=true
accepted_at=2026-07-13
acceptance_authority=unified_acceptance_thread
```

P7-S0 至 P7-S19 已全部完成独立验收，计划中的 P7-I01 至 P7-I24 均有当前代码、结构化运行谓词和负例证据。`P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md` 的唯一 Checklist 已全部勾选。

## 最终证据

- S19 验收复跑：`/tmp/p7_s19_unified_acceptance_v11/validation_summary_p7_s19_kernel_invariant_aggregate.json`。
- 当前源码共享回归：`/tmp/p7_current_shared_regressions_v11/p7_current_tree_shared_regression_manifest.json`。
- 当前阶段证据清单：`/tmp/p7_current_stages_v11/stage_evidence_manifest_v2.json`。
- 结果：24 项问题证据无失败，18 个阶段证据无失败，P1-P6 当前口径回归均通过。
- P4/P6 结构化结果必须包含非空且类型正确的指定检查项；空集合、缺项、错误类型和非布尔结果均被负例拒绝。
- 旧证据负例由当前摘要现场派生错误源码指纹，即使同步更新外层摘要哈希也会被拒绝，不依赖历史临时文件。
- `compileall` 与 `git diff --check` 通过。

## P7 完成后的可信范围

P7 完成的是内核可信状态转移和当前已准入战斗语义：原子执行图、严格 Mutation、规则与审计分离、类型化表达式、动作与目标契约、查询提交闭环、阶段机、时间线、队列、伤害削韧、护盾、状态准入、随机分支、战中召唤、波次生命周期和紧凑语义状态。

P7 完成不代表全角色、全怪物、全装备、全关卡或所有内容图已经复刻。P2 action-delay callback graph、P3 servant action graph、P4 action formula runtime graph、P6 上游动作图及既有 admission/source gap 已在总账中保留，后续不得用本检查点掩盖这些内容缺口。
