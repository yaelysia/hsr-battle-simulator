# v8 P2-S6 控制状态 gate 检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s6_status_control_gate`。
- 修复控制状态 metadata 来源：modifier definition 的 `behavior_flags` 中存在 `STAT_CTRL` 或 `DisableAction` 时，状态实例归类为 `status_category=control`。
- `control_kind` 从结构化 `STAT_*` flag 派生，不按角色名、怪物名或状态名硬编码。
- 验证真实控制 AddModifier 对行动可用性、scheduler 直接执行、queue preflight 三条路径统一阻断。
- 验证控制解除后 gate 消失，expired/removed/missing source trace 负例不误阻断。

## 关键事实

控制来源矩阵：

```text
control_behavior_flags executable source_count=108
action_availability_gate executable source_count=118
scheduler_gate executable source_count=118
queue_preflight_gate executable source_count=118
timeline_delay_from_control source_absent_not_required source_count=0
ultimate_window_gate boundary_only source_count=0
counter_or_followup_control_policy boundary_only source_count=0
```

本步真实控制正例按结构化谓词选择：

```text
EffectIR opcode=AddModifier
modifier_definition.behavior_flags contains DisableAction
modifier_definition.behavior_flags contains STAT_CTRL
target_alias=ParamEntity
```

样例 behavior flags：

```text
DisableAction
STAT_CTRL_Frozen_Effect
STAT_CTRL_Frozen
STAT_CTRL
```

关键断言：

```text
status_category_control=True
control_kind_from_behavior_flags=True
availability_reason_is_control=True
scheduler_execution_blocked=True
scheduler_state_unchanged=True
queue_preflight_blocked=True
gate_source_trace_present=True
```

负例：

```text
expired_control_ignored=True
removed_control_ignored=True
missing_source_trace_ignored=True
gate_removed=True
queue_not_control_blocked=True
```

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s6_status_control_gate --output-dir /tmp/hsr_v8_p2_s6_status_control_gate
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s6_status_control_gate validation ok=True
```

## 剩余范围

- S6 完成控制状态对普通行动、scheduler 和 queue preflight 的统一 gating。
- 当前没有独立的控制导致 timeline delay 来源；不新增 synthetic timeline mutation。
- S7 继续覆盖状态数值影响和动态值绑定。
