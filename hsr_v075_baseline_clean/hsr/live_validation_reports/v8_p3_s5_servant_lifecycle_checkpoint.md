# v8 P3-S5 servant / 忆灵定义、属性、生命周期和 owner 关系检查点

日期：2026-07-06

## 本步完成

- `SummonSystem.plan_spawn_servant` 增加同 owner 同 servant 的 active duplicate admission；当前没有多实例、替换或拒绝策略来源时，重复生成 blocked，不靠 unit id 碰撞兜底。
- servant spawn mutation metadata 补充 `owner_entity_ref`、`servant_stat_source`、`servant_timeline_source`、`servant_lifecycle_source`、`servant_action_set`、`servant_ability_graph_ids`、`servant_skipped_slots`、runtime stat values 和 owner cleanup source。
- servant unit flags 补充 owner source、runtime stat values、HP/速度公式、attack/defense schema carry 边界和 skipped slot 审计。
- 新增 `simulator_v8_clean_core.tools.validate_p3_s5_servant_lifecycle`，按定义矩阵、正例 spawn/owner cleanup/source audit、负例 boundary 三组验证。

## 关键计数

```text
raw_count=6
definition_count=6
executable_definition_count=6
blocked_definition_count=0
negative_case_count=7
failed_group_count=0
spawn_replay_ok=True
cleanup_replay_ok=True
```

Case group 结果：

```text
servant_definition_matrix: executable, ok=True
servant_spawn_owner_lifecycle: executable, ok=True
servant_negative_boundaries: boundary_only, ok=True
```

## 分层结论

- 当前 6 条 `AvatarServantConfig` 均 lower 为 executable `ServantDefinitionIR`，RuleBook 可按 definition id 和 owner entity ref 查询。
- HP 与速度来源来自 `AvatarServantConfig` / servant stat skill 参数，并在 spawn 后按 `owner.max_hp * hp_inherit + hp_base`、`owner.speed * speed_inherit + speed_base` 计算；mutation metadata 可反查 stat source。
- timeline / action value、targetability、lifetime、owner death remove policy 都保留 source trace，owner cleanup 能产生 remove mutation 并通过 replay。
- action set 记录 executable binding 与 skipped slots；本步只声明 action availability/source admission，不声明完整 action execution，这是 P3-S6。
- attack / defense 仍是 `schema_carry_only`，只为 `UnitState` schema 可用而继承 owner 当前值；当前没有把它们 admission 进 servant damage formula。
- 多实例/重复生成当前没有真实策略来源；同 owner 同 servant 的 active duplicate 会 blocked / process-only / state unchanged。

## 负例覆盖

```text
owner_missing -> servant_owner_missing
owner_entity_mismatch -> servant_owner_entity_mismatch
non_positive_runtime_stats -> servant_runtime_max_hp_non_positive;servant_runtime_speed_non_positive
action_set_blocked -> validation_missing_action_set
timeline_source_blocked -> validation_missing_timeline_source
lifecycle_source_blocked -> validation_missing_lifecycle_source
duplicate_active_servant -> servant_duplicate_active_policy_missing
```

所有负例均验证：

```text
no_mutations=True
process_only_record=True
state_unchanged=True
```

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s5_servant_lifecycle --output-dir /tmp/hsr_v8_p3_s5_servant_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s5_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema --output-dir /tmp/hsr_v8_p3_s2_summon_runtime_schema_p3_s5_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_summoned_monster_spawn_p3_s5_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_p3_s5_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_p3_s5_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s5_servant_lifecycle validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
v8 p3_s2_summon_runtime_schema validation ok=True
v8 p3_s3_summoned_monster_spawn validation ok=True
v8 p1_8_battle_setup validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
```

## 本步没有完成

- 没有实现 servant action execution；本步只保证 action set、binding、skipped slots 和 action availability 的来源边界，这是 P3-S6 的入口。
- 没有把 servant attack / defense admission 进 damage formula；当前真实来源不足，保持 schema carry 边界。
- 没有处理 assistant actor/stats/action graph；这是 P3-S7。
- 没有扩展召唤物死亡、过期、wave 切换清场完整生命周期；这是 P3-S9。

## 后续影响

- P3-S6 可以在已有 servant action admission 和 source trace 基础上实现外部推演器选择后的 action execution。
- P3-S10 处理 servant damage/resource attribution 时，必须先补真实 attack/defense 或公式来源，不能直接使用 schema carry 值。
- 若后续数据库出现 servant 多实例或替换策略来源，应先扩展 lifecycle/admission 和负例，再放开 duplicate spawn。
