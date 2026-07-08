# v8 P3-S2 summon runtime schema v2 与实体身份统一检查点

日期：2026-07-06

## 本步完成

- 将 `summon_runtime` 升级为 `p3_summon_runtime_v2`，保留 `p1_3_summon_runtime_v1` 只读 normalize 边界。
- 新增 schema boundary，说明向前兼容边界和上一版 schema。
- runtime entity 现在记录：
  - `runtime_id` / `unit_id` / `template_ref` / `summon_kind`
  - `owner_id` / `summoner_id` / `team_side`
  - `source_intent_id` / `source_trace` / `source_entry_id` / `source_entry_trace`
  - `created_event_index` / `removed_event_index` / `removed_reason` / `status`
  - `targetability` / `actionability` / `timeline` / `lifetime` / `wave_clear_policy`
- `SummonRuntimeView` 暴露 schema boundary 和 `last_servants`，且保持纯查询。
- spawn、remove、owner cleanup 都同步写 runtime registry；remove / cleanup 会从 active indexes（例如 `by_owner`）移除实体，但不删除 `entities` / `servants` 中的 audit record。
- target system 接受 v1/v2 schema，但召唤目标解析必须有 runtime entity source trace；flag-only 和缺 source trace 不会被解析为真实目标。
- 更新 P1-3 / P1-6 验证中的旧 schema 断言和 fixture，使其不再绑定 v1。
- 新增 `simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema`，默认只输出 summary 和轻量矩阵。

## 关键矩阵

```text
schema_version=p3_summon_runtime_v2
case_group_count=5
failed_group_count=0

positive_runtime_groups:
- summoned_monster_runtime
- servant_runtime_remove
- owner_cleanup_runtime

negative_boundary_groups:
- negative_boundaries
```

P3-S2 checks：

```text
summoned_monster_runtime_ok=True
servant_runtime_remove_ok=True
owner_cleanup_runtime_ok=True
legacy_view_normalization_ok=True
negative_boundaries_ok=True
schema_version_is_v2=True
matrix_is_lightweight=True
```

## 负例边界

- 缺 `summon_runtime`：target blocked，state unchanged。
- 错 schema：target blocked，state unchanged。
- flag-only servant：action availability blocked，target blocked，state unchanged。
- runtime entity 缺 `source_trace`：target blocked，且 blocked reason 为 `summon_runtime_entity_source_trace_missing`。
- removed servant：audit registry record 保留，但 active index 清理，target 不再解析。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema --output-dir /tmp/hsr_v8_p3_s2_summon_runtime_schema
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_target_system_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory --output-dir /tmp/hsr_v8_p3_s0_summon_source_inventory_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s1_summon_ir_rulebook_contract --output-dir /tmp/hsr_v8_p3_s1_summon_ir_rulebook_contract_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289_p3_s2_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s2_summon_runtime_schema validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
v8 p1_6_target_system validation ok=True
v8 p3_s0_summon_source_inventory validation ok=True
v8 p3_s1_summon_ir_rulebook_contract validation ok=True
v8 p1_8_battle_setup validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
v8 v0_289 validation ok=True
```

## 本步没有完成

- 没有扩展 `SummonMonster` 的多 entry / 多 count / unique group 语义；这是 P3-S3。
- 没有把 `SummonUnitData` 从 boundary-only 提升为 battle runtime admission；这是 P3-S4。
- 没有放开 assistant actor / stats / action execution；这是 P3-S7。
- 没有宣称 servant damage stat binding、资源归属、完整技能执行完成；这些仍属于后续 S5/S6/S10。

## 后续影响

- P3-S3 可以依赖 v2 runtime registry 的身份、source trace、lifetime 和 timeline 字段继续完善 summoned monster admission。
- P3-S5 / S9 可以复用 removed record retained 语义，避免移除后丢失审计。
- P3-S8 的 target 扩展必须继续坚持 runtime entity source trace；不能退回只看 `UnitState.flags`。
