# v8 P2-S10 状态回调事件族与任务 opcode 覆盖检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s10_status_callback_coverage`。
- 修正 callback 目标上下文解析：`ParamEntity` / `CurrentActionTarget` 不再在缺 trigger payload 时回退到状态持有者。
- 修正 lowering admission：事件族缺 runtime source / payload 时，对应 callback、callback task、status damage、action delay、queue intent、damage modifier 均回填 blocked。
- 验证状态事件族矩阵覆盖当前所有 callback event，并区分 executable / boundary-only。
- 验证 callback task opcode 均有 executable、executable_control 或 blocked reason 分类。
- 验证 AddModifier、RemoveModifier、RemoveSelfModifier、动态值写入、队列插入、行动值变化、状态伤害 callback 正例均可 replay 和 source audit。
- 验证缺状态、缺事件源、缺 wave payload、缺条件、缺目标、unsupported task 均 blocked / state unchanged。

## 覆盖矩阵

```text
event_family executable=52 boundary_only=148
task_opcode executable=14 executable_control=1 boundary_only=528
```

关键 task 覆盖：

```text
AddModifier executable
RemoveModifier executable
RemoveSelfModifier executable
SetDynamicValue executable
TurnInsertAbility/TurnInsertAction executable
SetActionDelay executable
DamageByAttackProperty executable
PredicateTaskList executable_control
DispelStatus boundary_only
unsupported opcode boundary_only
```

## 关键断言

```text
families_cover_all_callback_events=True
executable_families_have_runtime_sources=True
blocked_families_have_reasons=True
all_non_executable_tasks_have_reason_or_control_lowered=True
no_unhandled_executable_task=True
missing_target_no_payload_fallback=True
source_audit=True
replay=True
settlement_traceability=True
```

`DispelStatus` callback task 当前数据库/IR 中没有 executable callback 正例，本步按 boundary-only 验收，不合成假执行路径。普通 effect 形态的 `DispelStatus` 已在 S9 验证。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s10_status_callback_coverage --output-dir /tmp/hsr_v8_p2_s10_status_callback_coverage
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s8_status_damage --output-dir /tmp/hsr_v8_p2_s8_status_damage_after_s10
git diff --check
```

关键输出：

```text
v8 p2_s10_status_callback_coverage validation ok=True
v8 p2_s8_status_damage validation ok=True
```

## 剩余范围

- S10 完成状态回调事件族和 task opcode admission 边界。
- S11 继续做全状态来源回扫，清理剩余未分类和实现缺口。
