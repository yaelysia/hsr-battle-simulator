# v8 P4-S4 Target Query Admission Ready For Review

日期：2026-07-08

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S4 角色 / 怪物 target alias、TargetQuery、fetch/sort admission 扩面。

目标产物：

- 补强 action target policy 的 source trace，使 action availability choice 和 executor target resolution 都能反查 action target source。
- 输出 target backlog matrix，按 action target policy、角色/怪物 alias、summon/servant alias、global/dot alias、TargetQuery、fetch、sort/filter/retarget、random RNG、P3 summon target backlog 拆行。
- 验证缺目标、错目标、removed/defeated target、缺 registry/错 key、缺 RNG choice 时 blocked，不 fallback 到默认目标或默认随机。
- 拆分 P3 summon target expression backlog，不用一个大 admission_gap 覆盖内部子项。

本阶段实际改动文件：

- `simulator_v8_clean_core/systems/target.py`
- `simulator_v8_clean_core/systems/action_preflight.py`
- `simulator_v8_clean_core/core/executor.py`
- `simulator_v8_clean_core/systems/action_availability.py`
- `simulator_v8_clean_core/systems/enemy_action.py`
- `simulator_v8_clean_core/tools/validate_p4_s4_target_query_admission.py`
- `live_validation_reports/v8_p4_s4_target_query_admission_ready_for_review.md`

本阶段未修改：

- 未让 target resolver 读取 raw TBGD 或 TextMap。
- 未新增默认目标 fallback、名称匹配 fallback、列表第一个目标 fallback。
- 未让推演器、UI 或 route 解释目标规则。
- 未改 lowering 的 target expression 投影。
- 未新增 P4-S12 聚合脚本。
- 未改 P4 第 22 节 checklist。

## 实际改动

`TargetPolicy` 新增只读携带字段：

- `source_trace`
- `metadata`

`target_policy_for_action()` 现在为 action target policy 填入：

- `source_trace.action_definition`
- `source_trace.action_event`
- `source_trace.target_mode`
- 可选 `source_trace.bounce_policy`
- action id、level、definition id、action event id、target mode、damage kind 等轻量 metadata

调用点已接入：

- `CombatExecutor.execute()`
- `ActionAvailabilitySystem._normal_action_choice()`
- `EnemyActionSystem.next_candidate()`

目标枚举和解析语义没有改；新增字段只把已有 IR 来源带入 policy metadata。

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s4_target_query_admission
```

主要文件：

```text
/tmp/hsr_v8_p4_s4_target_query_admission/validation_summary_p4_s4_target_query_admission.json
/tmp/hsr_v8_p4_s4_target_query_admission/p4_s4_target_backlog_matrix.json
```

S4 主验证：

```text
ok=True
row_count=11
unclassified_count=0

classification_counts:
  admission_gap=9
  boundary_only=1
  executable=1

target_expression_count=250958
target_expression_coverage_counts:
  executable=232222
  blocked=18736

gap_attribution_counts:
  admission_gap=18732
```

## Matrix 摘要

```text
action_target_policy_source_trace: executable
action_target_boundary_negative: boundary_only
target_alias_character_domain: admission_gap, raw=112602, executable=107036, admission_gap=5566
target_alias_monster_domain: admission_gap, raw=76776, executable=72617, admission_gap=4159
target_alias_summon_servant_domain: admission_gap, raw=16160, executable=15566, admission_gap=594
target_alias_global_operation_dot_alias: admission_gap, raw=3812, executable=3183, admission_gap=629
target_query_subtypes: admission_gap, raw=22, executable=0, admission_gap=22
target_fetch_registry_boundaries: admission_gap, raw=9400, executable=9347, admission_gap=53
target_sort_filter_retarget_pipeline: admission_gap, raw=11224, executable=6104, admission_gap=5120
target_random_rng_ledger: admission_gap, raw=6299, executable=3714, admission_gap=2585
p3_summon_target_expression_backlog_split: admission_gap, raw=7, executable=5947, admission_gap=4
```

样本 ID 是验证输出，不是选择条件。action policy runtime 样例由结构化谓词选择：availability choice 必须含 target policy source trace，executor transition 的 target resolution policy 也必须含同源 trace，且 replay/source audit 通过。当前输出样本为 `avatar_skill:100107`、`character_data_card:avatar:1001`。

## P3 Summon Target 拆分

P3 summon target backlog 不再作为一个大 admission gap 记录，S4 拆成 7 个子行：

```text
CasterServant: executable, executable_count=1930
CasterSummonedMinions: executable, executable_count=2466
LastSummonMonsters: executable, executable_count=371
ServantEntityList: executable, executable_count=1
GetServant: executable, executable_count=632
GetSummoner: executable, executable_count=104
RemoveServant: admission_gap, executable_count=443, blocked_count=4
```

`RemoveServant` 的 4 个 blocked 样例继续保留为 admission gap，样例原因包括 `target_alias_not_admitted:TauntOrRandomEnemy.RemoveServant`。这不是 P3/S4 完成项，进入后续 backlog。

## 正例与负例

正例：

- `action_target_policy_source_trace`：action availability choice 和 executor transition 均包含 `target_policy.source_trace.action_definition/action_event`；transition replay 与 runtime source audit 通过。
- `target_fetch_registry_boundaries`：`TargetFetchPartner` 精确 registry 命中可解析。
- `target_random_rng_ledger`：显式 RNG choice 产生 `target_random` RNG event。

负例：

- 缺 enemy target candidates 时 blocked 为 `target_candidates_empty`。
- unknown target、defeated target、removed target 均被 `resolve_action_targets` 拒绝，state unchanged。
- registry 存在但命名 key 缺失时，`TargetFetchPartner` blocked 为 `target_partner_missing`，不会用 default registry 冒充命名来源。
- random target 缺 choice blocked 为 `requires_rng_choice`，错 choice blocked 为 `target_random_choice_invalid`，不使用默认随机。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/systems/target.py simulator_v8_clean_core/systems/action_preflight.py simulator_v8_clean_core/core/executor.py simulator_v8_clean_core/systems/action_availability.py simulator_v8_clean_core/systems/enemy_action.py simulator_v8_clean_core/tools/validate_p4_s4_target_query_admission.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s4_target_query_admission --output-dir /tmp/hsr_v8_p4_s4_target_query_admission
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_v0_288_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations --output-dir /tmp/hsr_v8_p3_s8_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s2_combatant_action_availability --output-dir /tmp/hsr_v8_p4_s2_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p4_s4
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
if rg -n "[[:blank:]]$" simulator_v8_clean_core/systems/target.py simulator_v8_clean_core/systems/action_preflight.py simulator_v8_clean_core/core/executor.py simulator_v8_clean_core/systems/action_availability.py simulator_v8_clean_core/systems/enemy_action.py simulator_v8_clean_core/tools/validate_p4_s4_target_query_admission.py; then exit 1; fi
```

结果：

- S4 主验证 `ok=True`。
- P1-6 `ok=True`。
- v0_288 `ok=True`。
- v0_289 `ok=True`。
- P3-S8 `ok=True`。
- P4-S2 回归 `ok=True`，S1 继承的 28 个 validation gap 未被覆盖。
- P1-0 `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- S4 新改代码尾随空白检查通过。

## 未完成 / Gap / Deferred

- TargetQuery 当前 `raw=22` 但 `executable=0`，全部保留为 admission gap；S4 未把 query source 硬升为 executable。
- 角色/怪物 target alias 仍有大量 blocked target expression，属于后续 admission 收敛，不因已有 executable 样例而完成全域。
- `RemoveServant` 仍有 4 个 admission gap。
- 一些 fetch/sort/filter/retarget/random 子族已 executable，但同族仍有 blocked expression，已按子域保留 gap。
- S4 不实现全角色/全怪物特殊 target 语义，也不处理 S10 的全部 summon target 与 summoned monster intent backlog。

## 当前进度口径

当前做到 P4-S4 ready_for_review：action target policy source trace 已接到 availability 和 executor target resolution；target alias/query/fetch/sort/random/P3 summon target backlog 已形成矩阵证据。

距离最小可用战斗纵切：P1/P3 纵切和 target 直接回归均未退化。

距离完整复刻：仍缺 S5 monster action graph、S6 passive/event/wave、S7/S8 角色机制、S9 状态/资源/伤害联动、S10 P3 backlog 深度回收、S11 调用契约和 S12 最终聚合。
