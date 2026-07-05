# v8 P2-S4 状态生命周期检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s4_status_lifecycle`。
- 建立生命周期时点矩阵，区分真实来源、无来源时点和边界-only 状态。
- 验证持有者 tick、`ModifierPhase1End` sweep、`ActionPhaseEnd` sweep、到期移除、过期事件分发、跨波状态清理。
- 补充 defeated / removed 单位状态生命周期 tick 阻断，避免死亡或退场单位继续产生状态持续时间 mutation。
- 验证缺 `remaining_duration`、缺 duration admission 的负例均 blocked/process-only/state unchanged。

## 关键事实

当前 IR 中状态持续时间来源的 `LifeStepMoment` 分布：

```text
<missing>=25119
ModifierPhase1End=1455
ActionPhaseEnd=86
```

缺失 `LifeStepMoment` 的普通 buff/debuff 仍按已有规则默认到 `ModifierPhase1End`，source trace 中保留 `default_life_step_moment`。当前没有 `TurnStart`、行动前、波次开始/结束 tick 的真实持续时间来源，因此这些时点记录为 `source_absent_not_required`，不新增 synthetic hook。

关键断言：

```text
holder_tick_mutates=True
modifier_phase_sweep.scheduler_sweep_mutates=True
action_phase_end_sweep.scheduler_sweep_mutates=True
expire_remove.status_detail_removed=True
expire_remove.expire_events_present=True
wave_cleanup.statuses_cleared=True
wave_cleanup.status_details_removed=True
source_audit=True
replay=True
```

负例：

```text
defeated_reason=unit_not_active_for_status_lifecycle:defeated
removed_reason=unit_not_active_for_status_lifecycle:removed
missing_remaining_reason=remaining_duration_missing
missing_source_reason=duration_admission_not_executable
```

这些负例均无 mutation，且 state unchanged。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s4_status_lifecycle --output-dir /tmp/hsr_v8_p2_s4_status_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s4_status_lifecycle validation ok=True
```

## 剩余范围

- S4 完成状态生命周期、过期和跨波清理边界。
- S5 继续覆盖概率、效果抵抗、控制抵抗和免疫的可回放分支。
