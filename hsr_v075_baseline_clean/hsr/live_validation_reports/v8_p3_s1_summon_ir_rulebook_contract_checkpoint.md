# v8 P3-S1 Summon / Servant IR 与 RuleBook 契约检查点（AssistantAvatar out_of_scope）

日期：2026-07-06

## 本步完成

- 新增 `simulator_v8_clean_core.tools.validate_p3_s1_summon_ir_rulebook_contract`，验证 P3-S1 的 IR 字段、source trace 和 RuleBook 查询契约。
- 补齐 RuleBook 只读查询：
  - `assistant_ability_resolutions_for_ability`
  - `servant_definitions_for_owner`
  - `queue_windows`
  - `queue_windows_by_family`
  - `queue_lifecycle_policies`
  - `queue_lifecycle_policies_by_family`
  - `extra_action_policies`
  - `combatant_action_sets`
  - `action_ability_binding_by_id`
- 修正 status callback task lowering：非 `PredicateTaskList` 的 `SuccessTaskList` / `FailedTaskList` 也会投影到 `StatusCallbackTaskIR` 派生链路，补上 `TurnInsertAssistantAbility` 在 `Retarget.FailedTaskList` 下的真实 raw 来源。
- 补齐 servant literal stat component 的 `AvatarServantConfig` 字段级 source trace，使 `timeline_source` 能追到 `SpeedBase` / `SpeedInherit` 原始字段。
- 本步不改变 runtime 执行语义；AssistantAvatar / `TurnInsertAssistantAbility` contract 只验证 raw/IR/RuleBook 可审计并分类为 `out_of_scope`。`SummonUnitData` 经 P3-S4 回归后确认当前数据库没有 battle runtime trigger，维持 definition/catalog boundary。

## 关键计数

```text
contract_group_count=6
failed_group_count=0
gap_attribution_counts={}

summon_unit_definition_count=36
summon_monster_intent_count=775
servant_definition_count=6
assistant_queue_intent_count=5
assistant_resolution_count=5
assistant_queue_window_count=5
```

Contract group 分类：

```text
summon_unit_definition_contract: boundary_only
summon_monster_intent_contract: executable
servant_definition_contract: executable
assistant_resolution_contract: out_of_scope
queue_lifecycle_and_action_admission_contract: boundary_only
target_and_cross_system_source_trace_contract: executable
```

这表示当前已有 IR 都能通过 RuleBook 结构化查询，并且 source trace 完整；不表示所有召唤体系机制已 executable。

## 对最终验收的影响

`assistant_resolution_contract` 现在是 AssistantAvatar scope exclusion，不是 P3 admission gap，也不是 boundary-only。P3-S12 聚合必须把它写入 scope exclusion 矩阵，而不是 inherited gap matrix：

```text
contract:assistant_resolution_contract
classification=out_of_scope
p3_gap_count=0
```

后续如要实现 AssistantAvatar / avatar assistant ability，应另立阶段处理，不阻塞 P3 summon/servant 底座闭环。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory --output-dir /tmp/hsr_v8_p3_s0_after_s1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s1_summon_ir_rulebook_contract --output-dir /tmp/hsr_v8_p3_s1_summon_ir_rulebook_contract
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p3_s1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s10_status_callback_coverage --output-dir /tmp/hsr_v8_p2_s10_after_p3_s1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p3_s1
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s0_summon_source_inventory validation ok=True
v8 p3_s1_summon_ir_rulebook_contract validation ok=True
v8 p1_5_queue_window_system validation ok=True
v8 p2_s10_status_callback_coverage validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
```

## 本步没有完成

- 没有升级 summon runtime schema。
- 没有让 `SummonUnitData` definition/catalog 自动 spawn；当前数据库无真实 battle runtime trigger。
- 没有放开 AssistantAvatar actor/stats/action graph 执行。
- 没有清理 `SummonMonster` 大量 blocked 子集、target admission gap 或 lifecycle cleanup gap。

## 后续影响

- P3-S2 可以依赖 RuleBook 查询而不是遍历 IR 内部字段。
- P3-S4 已基于 `SummonUnitData` 矩阵完成 battle trigger 拆分，并将当前数据库口径收敛为 source_absent / boundary。
- P3-S7 已基于 5 条 `TurnInsertAssistantAbility` resolution 完成 AssistantAvatar scope exclusion 和 queue/window boundary audit。
- P3-S8 已使用本步已验证的 target source trace 和 RuleBook 查询扩展 summon/servant target resolver；AssistantAvatar target boundary 已分类为 out_of_scope。
