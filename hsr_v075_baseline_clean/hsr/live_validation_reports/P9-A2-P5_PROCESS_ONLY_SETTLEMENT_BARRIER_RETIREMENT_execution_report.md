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

通过既有 P0 raw action-window TriggerAbility denominator，把每个 raw occurrence 精确匹配到同一
`task_source_path + task_json_path` 的 scope record，再用该 raw `AbilityName` 的既有 source-graph
phase binding 唯一得到 outer action source；不使用角色名、文件名、action-id 或数量指纹。结果候选含三条
`DamageByAttackProperty` 和两条 eligible barrier。相同候选在基线有两条
`task_graph_control_requires_domains:damage_heal_shield` node provenance；当前两条均移除，两个
barrier 均为 execution-only materialized leaf，仍各带一个 deferred audit effect reference。

外层 action 仍 fail-closed：余下 blocker 为 audit-only effect definition；三条
`DamageByAttackProperty` 均逐一保留 deferred audit-only effect reference，并与 blocker provenance
task-id 集合双向一致，仍为 non-executable。

Direct 观测 task graph execute、condition evaluation、RNG draw、mutation、event、settlement、replay
均为 0；wall `27.821813s`，peak RSS `452496 KiB`。

## 审核修复

- A/B/C 分母只将 lowering 的两种明确 settlement-payload reason 归入 B；raw 缺失、类型/schema/unknown
  field 或 field-invalid 等任何其他 source shape 均进入 C 并触发 Direct fail-closed。
- P5 CI 复用仓内既有 `.ci-venv` 模式，固定 provision `pytest==8.3.5`，使 Fast、A1、Direct 和 diff
  gate 均能在 hosted runner 上依次运行。

## 已运行验证

- P5 focused pytest：17 passed。
- P3 regression pytest：25 passed。
- scoped compile：通过。
- A1 Fast：11 cases，`ok=true`。
- P5 Direct：`ok=true`。
- fixed-base `git diff --check`：通过。

报告更新后已重跑以上命令；hosted CI 仍由 PR final head 运行，不以本地结果替代。
