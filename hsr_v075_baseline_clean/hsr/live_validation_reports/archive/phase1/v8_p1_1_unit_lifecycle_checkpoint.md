# v8 P1-1 UnitLifecycle checkpoint

## 范围

本阶段把单位生命周期抽成 v8 core 通用底座，覆盖：

- `active`：在场，可作为普通行动 actor、普通 alive target、普通伤害目标。
- `defeated`：已击败，默认不能行动、不能作为普通 alive target，但保留在 `BattleState.units` 中用于击杀归因、事件和 replay。
- `removed`：已退场，不能行动、不能作为普通 target、不能接收普通伤害；仍保留 tombstone snapshot。

旧 state 缺 `flags.lifecycle_status` 时，由 `UnitLifecycleSystem.status_of()` 集中兼容推断：

- `hp > 0` => `active`
- `hp <= 0` => `defeated`

该兼容只在 lifecycle helper 内部，不再由 target/timeline/queue/action availability 各自发明判断。

## 实现落点

- 新增 `systems/unit_lifecycle.py`
  - `UnitLifecycleStatus`
  - `UnitLifecycleView`
  - `UnitLifecycleSystem.view/status_of/can_act/can_target/can_receive_damage`
  - `spawn_mutation/defeat_mutation/defeat_record_mutation/remove_mutations/revive_blocked`
- `core/model.py`
  - unit snapshot 输出 `lifecycle_status`、`defeated`、`removed`、`lifecycle`
  - battle snapshot 保留原 `teams` 历史/当前单位列表，并新增 `active_teams`
- `core/reducer.py`
  - 支持 `("units", unit_id)` + `metadata.lifecycle_operation="unit_spawn"` 插入完整 `UnitState`
  - 未知 unit 的普通字段 mutation 仍拒绝
  - 重复 spawn 拒绝
- `systems/damage.py`
  - HP 正数到 0 时产生 HP mutation、`unit_defeat` lifecycle mutation、`unit_defeat_record` mutation
  - `unit.defeated` process event 保留，并关联 lifecycle mutation id
  - removed/defeated target 不再作为普通 damage target；同一 damage sequence continuation 仍按既有 ledger 记录 process-only skip/continuation
- `systems/target.py`
  - action target enumeration、explicit target、group alias、bounce、adjacent target 全部使用 lifecycle helper
  - `allow_defeated=True` 只允许 defeated，不允许 removed
- `systems/timeline.py`
  - `plan_next_actor` 使用 lifecycle helper；`action_disabled` 仍是独立 gating
- `systems/action_availability.py`
  - active turn actor defeated/removed 时 blocked，不暴露 action choices
  - queue action boundary 检查 actor/target lifecycle
- `systems/queue.py`
  - queue actor defeated/removed blocked
  - queue target removed/defeated blocked 或从 group target 中过滤
- `systems/status.py`、`systems/status_callbacks.py`
  - 状态相关 group target/alive helper 使用 lifecycle helper

## Spawn / Remove / Revive 策略

- UnitSpawn：当前支持从已构造 `UnitState` 生成 unit-level mutation，由 reducer replay 插入；spawn 后自动写入 `lifecycle_status=active`。
- UnitRemove：不删除 `state.units`，只写 `lifecycle_status=removed` 和 `removed_record`，保留 tombstone。
- UnitRevive：P1-1 不实现 executable 复活；`revive_blocked()` 只返回 blocked/state unchanged 记录，不产生 mutation。

## 验证

新增：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_unit_lifecycle
```

覆盖：

- lifecycle view active/defeated/removed。
- HP <= 0 旧 state 推断 defeated。
- explicit removed 覆盖 HP > 0。
- damage defeat 产生 HP mutation + lifecycle mutation + defeat record。
- damage defeat event 关联 lifecycle mutation id。
- repeat damage 对 defeated target process-only skipped。
- defeated target 默认不可选，`allow_defeated` 可选 defeated。
- removed target 不可选。
- defeated/removed actor 不进 timeline。
- active turn actor defeated/removed 时 action availability blocked。
- queue actor removed blocked，group target 过滤 defeated/removed。
- UnitSpawn replay。
- UnitRemove replay。
- UnitRevive blocked/state unchanged。
- duplicate spawn 和 unknown unit field mutation 被拒绝。

本次已运行结果：

- `compileall simulator_v8_clean_core simulator_v8_ui`：通过。
- `validate_p1_1_unit_lifecycle`：`ok=True`。
- `validate_p1_0_action_boundary`：`ok=True`。
- `validate_v0_283`：`ok=True`。
- `validate_v0_289`：`ok=True`。
- `git diff --check`：通过。

`validate_v0_264` 本次仍为 `ok=False`，失败原因是既有目标组样例 action blocked 为 `missing_ability_phase_in_ability_file`；该失败的 target resolution、snapshot replay、source audit、settlement traceability 均为 true，未观察到 lifecycle gate 引入的新失败。

## 剩余范围

- P1-2 WaveSystem 需要用 UnitSpawn/UnitRemove 推进波次。
- P1-3 Summon/Assistant/Servant 需要用 UnitSpawn/UnitRemove 管理实体生灭。
- 复活仍必须等待真实来源和通用语义 admission 后才能 executable。
- removed unit 的 queue cleanup/cancel mutation 策略仍留给后续 P1-5 扩展；P1-1 当前采用 blocked/state unchanged。
