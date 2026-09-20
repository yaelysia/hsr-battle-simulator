# P9-A2-P5 execution report

固定基线为 `8064d5ab01837d1ebb4d8388ca072796c7946634`，pinned TBGD 为
`14c1d18f91a8101d610e6c523447a7517de3fae1`。

## 交付

`task_graph_materializer.py` 新增严格 settlement barrier gate。只有
`DamagePerformFinish` / `SkillPerformFinish` 的 source-proven `$type`-only、空 control
peer fields/responsibilities、无分支或模板、process-only `audit_only` task，且有唯一同 source
`audit_only` effect/process-only contract 的形状，才会在 generic domain deferral 前成为 leaf。
source disposition 只为同一 materialized node 移除 `damage_heal_shield`。

Effect reference 仍是 `task_graph_definition_not_admitted:effect:audit_only`；没有产生 runtime
effect、damage、HP mutation、event、RNG、settlement 或 replay 行为。

## Direct evidence

Direct 动态重建来源控制分母：580 条 = 566 条 eligible no-payload process-only + 14 条 explicit
S11 payload（DamagePerformFinish 7、SkillPerformFinish 7）+ 0 条 other/unresolved。payload 分母继续由
lowering 的 settlement-payload-not-admitted reason 保持 fail-closed。

通过既有 P0 raw action-window TriggerAbility denominator 动态找出 owner，再从当前 action source
重新选择 action-window candidate；不使用角色名、文件名或 action-id allowlist。结果候选含三条
`DamageByAttackProperty` 和两条 eligible barrier。相同候选在基线有两条
`task_graph_control_requires_domains:damage_heal_shield` node provenance；当前两条均移除，两个
barrier 均为 execution-only materialized leaf，仍各带一个 deferred audit effect reference。

外层 action 仍 fail-closed：余下 blocker 为 audit-only effect definition；三条
`DamageByAttackProperty` 仍为 non-executable audit-only references。

Direct 观测 task graph execute、condition evaluation、RNG draw、mutation、event、settlement、replay
均为 0；wall `27.318899s`，peak RSS `452360 KiB`。

## 已运行验证

- P5 focused pytest：10 passed。
- P3 regression pytest：25 passed。
- scoped compile：通过。
- A1 Fast：11 cases，`ok=true`。
- P5 Direct：`ok=true`。

最终报告提交后将重跑以上命令与 fixed-base `git diff --check`；本报告不把 hosted CI 视为已完成。
