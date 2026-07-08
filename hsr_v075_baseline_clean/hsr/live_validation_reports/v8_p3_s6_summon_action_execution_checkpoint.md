# v8 P3-S6 召唤单位行动可用性和执行链路检查点

日期：2026-07-06
复查更新：2026-07-07

## 本步完成

- `SummonSystem` 为 summoned monster unit 补充 `timeline_admitted`、`summon_action_admitted` 和 `summon_action_admission`，source trace 指向 `SummonMonsterIntentIR`、entry、`MonsterDataCardIR` 和 `CombatantProfileIR`。
- `ActionAvailabilitySystem` 对 enemy-side summoned monster 也执行 summon runtime / action admission gate，避免只靠 `side="enemy"` 进入敌方固定序列。
- `ActionAvailabilitySystem` 的 enemy fixed-sequence choice 现在同时检查 `action_event` / ability binding admission，并把 `action_event` source trace 写入 choice；summoned monster action availability 不再只凭 action definition 放行。
- `CombatExecutor` 增加 summon execution preflight，直接手写 `ActionCommand` 也必须通过 runtime v2 entity、source intent binding、action admission、source trace 和 active 状态检查。
- 新增 `simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution`，覆盖 servant 正例 action execution、summoned monster action boundary、executor bypass 负例和 resource pressure source gap。

## 关键计数

```text
failed_group_count=0
servant_action_enabled=True
servant_action_mutation_count=5
servant_action_replay_ok=True
servant_action_source_audit_ok=True
negative_case_count=6
summoned_monster_action_classification=executable
resource_pressure_classification=source_absent_not_required
```

Servant action 正例 mutation source：

```text
combat_executor.timeline=3
effect_system=0
status_system=2
damage_mutation_count=0
toughness_mutation_count=0
resource_mutation_count=0
```

Case group 结果：

```text
servant_action_execution: executable, ok=True
summoned_monster_action_boundary: executable, ok=True
executor_bypass_boundaries: boundary_only, ok=True
resource_pressure_boundary: source_absent_not_required, ok=True
```

## 分层结论

- servant / 忆灵已有真实 action availability 和 action execution 正例。外部推演器从 availability 选择 target 后，`CombatExecutor` 执行真实 action，产生 timeline / status / effect mutation，并通过 replay 与 source audit。
- servant action 正例不产生 damage mutation；这与 P3-S5 的 attack / defense `schema_carry_only` 边界一致，不能把当前 owner 继承值 admission 进 damage formula。
- 当前可执行 `SummonMonster` spawn 样例可生成 runtime entity 和 action admission trace，并能通过 source-backed enemy fixed-sequence action availability。正例 choice 为 `choice_kind=enemy_fixed_sequence`、`action_id=monster_skill:100205001`，source trace 包含 `action_definition`、`action_event`、`action_sequence_step`、`ai_policy` 和 `monster_data_card`。
- 当前 executable servant summon-action choices 没有正 skill point cost；资源不足负例按 `source_absent_not_required` 记录，不合成资源消耗正例。

## 负例覆盖

```text
missing_target -> no_selected_target
runtime_missing -> summon_runtime_state_missing
timeline_not_admitted -> summon_timeline_not_admitted
action_source_not_admitted -> summon_action_source_not_admitted
runtime_binding_mismatch -> summon_runtime_source_binding_mismatch
defeated_actor -> unit_defeated
```

所有 executor bypass 负例均验证：

```text
action_enabled=False
no_mutations=True
state_unchanged=True
process_only action_blocked record=True
```

## 验证

本步涉及 action availability、executor、summon runtime 和 servant 生命周期。验证均串行运行；重验证不并行。

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution --output-dir /tmp/hsr_v8_p3_s6_gap_repair_v2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s5_servant_lifecycle --output-dir /tmp/hsr_v8_p3_s5_servant_lifecycle_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema --output-dir /tmp/hsr_v8_p3_s2_summon_runtime_schema_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_summoned_monster_spawn_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_p3_s6_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_p3_s6_regression
```

关键输出：

```text
v8 p3_s6_summon_action_execution validation ok=True
v8 p3_s5_servant_lifecycle validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
v8 p1_0_action_boundary validation ok=True
v8 p3_s2_summon_runtime_schema validation ok=True
v8 p3_s3_summoned_monster_spawn validation ok=True
v8 p1_8_battle_setup validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
```

## 本步没有完成

- 没有执行 summoned monster action 正例产生 mutation；本步只证明 action availability 侧 fixed-sequence admission 已闭环，执行侧仍由外部推演器选择并走 executor preflight。
- 没有实现 assistant action execution；这是 P3-S7。
- 没有把 servant attack / defense schema carry 值接入 damage attribution；这是 P3-S10 的前置来源问题。
- 没有扩展目标系统中的 summon / assistant 关系；这是 P3-S8。

## 后续影响

- P3-S7 可以基于 executor summon gate 和 source audit 口径处理 assistant queue/window/action boundary。
- P3-S8 可以继续扩展 target resolver，而不用担心 flag-only summon 绕过 runtime entity admission。
- 后续若执行 summoned monster action 正例，必须沿当前 fixed-sequence choice 进入 executor，并补 replay/source audit 样本，不能绕过 availability 与 summon runtime preflight。
