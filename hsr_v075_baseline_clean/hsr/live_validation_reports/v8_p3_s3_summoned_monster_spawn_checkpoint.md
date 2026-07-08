# v8 P3-S3 summoned monster 生成、位置、数量和延迟 admission 检查点

日期：2026-07-06

## 本步完成

- `SummonSystem.plan_spawn_summoned_monster` 改为按 `SummonMonsterEntryIR.count` 展开 spawn instance，不再把 plan unit 数硬绑定为 entry 数。
- `apply_spawn` 按展开后的 instance 生成 unit，保留 entry index、copy index、spawn index、entry count、position policy、level policy、profile/card source trace、delay policy 等审计字段。
- `summon_runtime` entity 记录补充 position / level / profile / monster card source trace，便于从 runtime registry 反查到 IR 和 TBGD source。
- summon spawn / servant spawn / remove records 改为标准 `SettlementRecord` 形态，并保留旧的观测字段；每个非 process-only record 都有 `mutation_id` 可追踪。
- lowering 收紧 `SummonMonsterDataList.LocationType` admission：只有 `BeforeCaster`、`AfterCaster`、`First`、`Last` 进入 executable；其他位置策略 blocked，不再等到 runtime 才失败。
- lowering 为 `count=1` 增加 `count_policy` evidence：当前 raw `SummonMonsterDataList` 没有 Count 字段，每条 list entry 只能 lowering 为一个 spawn instance。
- 新增 `simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn`，覆盖正例 spawn、multi-entry blocked、delay/position/profile/card/duplicate/missing-owner 负例、settlement traceability 和 replay。

## 关键矩阵

```text
intent_count=1178
coverage_status_counts={blocked: 1173, executable: 5}
entry_len_counts={1: 928, 2: 184, 3: 4, 4: 62}
executable_entry_len_counts={1: 5}
raw_occurrence_count=895
raw_multi_entry_occurrence_count=109
raw_count_field_occurrence_count=0
failed_group_count=0
```

Case group 结果：

```text
raw_source_inventory_ok=True
executable_spawn_trace_ok=True
multi_entry_boundary_ok=True
unsupported_source_boundaries_ok=True
count_unique_group_boundary_ok=True
matrix_is_lightweight=True
```

## 分层结论

- 当前数据库中有 5 条 executable `SummonMonster` intent，均为单 entry、count=1，已完成 spawn、timeline、runtime、target relation、settlement traceability 和 replay。
- 当前数据库中存在多 entry raw/IR 来源，但没有 executable 多 entry intent；样例均因 dynamic/custom monster id、profile/card、unsupported position 或 delay admission 被 blocked。S3 验证证明这些路径 state unchanged / process-only。
- 当前 `SummonMonsterDataList` raw 没有 `Count` 字段，也没有 `UniqueGroup` / `MaxSummonCount` 这类上限来源；count>1 和 unique group 不做 synthetic 正例，记录为当前 SummonMonster 范围的 source_absent_not_required。`SummonUnitData` 的 unique group 仍属 P3-S4。
- `LocationType` 现在在 lowering 层 admission；unsupported position 不能伪装成 executable 后再由 runtime fallback。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_summoned_monster_spawn
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema --output-dir /tmp/hsr_v8_p3_s2_summon_runtime_schema_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s0_summon_source_inventory --output-dir /tmp/hsr_v8_p3_s0_summon_source_inventory_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s1_summon_ir_rulebook_contract --output-dir /tmp/hsr_v8_p3_s1_summon_ir_rulebook_contract_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_p3_s3_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p3_s3_summoned_monster_spawn validation ok=True
v8 p1_3_summon_assistant_servant validation ok=True
v8 p3_s2_summon_runtime_schema validation ok=True
v8 p3_s0_summon_source_inventory validation ok=True
v8 p3_s1_summon_ir_rulebook_contract validation ok=True
v8 p1_8_battle_setup validation ok=True
v8 p1_9_phase1_aggregate validation ok=True phase1_repair_substrate_accepted=True phase1_minimum_battle_slice=True
```

## 本步没有完成

- 没有把 dynamic/custom monster id 的多 entry 来源提升为 executable；这需要真实 custom value / profile / card admission。
- 没有实现 SummonUnitData battle runtime admission；这是 P3-S4。
- 没有实现召唤单位动作执行链路；这是 P3-S6。
- 没有处理召唤物死亡、过期、wave 切换清场等完整生命周期；这是 P3-S9。

## 后续影响

- P3-S4 可以在不污染 `SummonMonster` 路径的前提下拆 `SummonUnitData` battle/client/catalog 来源。
- 后续若数据库出现真实 count>1 或 unique group 来源，runtime 已能按 instance 展开；但 validation 必须先证明 raw/lowering/RuleBook 来源真实。
- P3-S9 可以复用当前 per-mutation settlement record，继续扩展 remove / expire / wave cleanup 的 traceability。
