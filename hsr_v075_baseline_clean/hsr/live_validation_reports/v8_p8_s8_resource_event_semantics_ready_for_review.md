# P8-S8 资源事件旧语义清理：ready_for_review

> 当前说明：本报告的资源事件专项证据仍然有效；P8-S8 后续整体进展请以 `v8_p8_s8_remaining_gameplay_ready_for_review.md` 为准。

状态：`ready_for_review`（仅本次资源事件子范围）。

本报告不表示整个 P8-S8 已完成，不处理记忆角色、跨命途装配或其他暂缓事项；Checklist 未修改，Git 未提交。

## 当前契约

- `BattleState.skill_points` 只产生 `bp.change`，只对应 `OnListenBpChange`，作用域为 `global_listener`。
- `UnitState.energy` 产生 `energy.before_change` / `energy.change`；分别对应 `OnBeforeEnergyPointChange`，以及 `OnEnergyPointChange` / `OnSPChange`，作用域为 `being_hit_target_local`。
- `OnSPChange` 的 `change_value` 来自单位能量 mutation 的实际 `after - before`。
- `sp.change` 已从生产事件集合、lowering 映射和 dispatcher 作用域判断移除，不保留兼容别名；它只作为退役事件负例存在。
- 权威映射集中在 `resource_event_contract.py`，mutation 生产、lowering admission、dispatcher scope 和验证均从该契约派生。

## 验收谓词

来自 `/tmp/hsr_p8_s8_resource_only_final_v2/validation_summary_p8_s8_resource_events.json`：

```text
team_skill_points_use_bp_event=true
unit_energy_uses_energy_event=true
on_sp_change_receives_energy_delta=true
resource_event_cross_trigger_count=0
dead_production_resource_event_count=0
retired_sp_change_blocked_unchanged=true
executable_event_families_have_real_runtime_producers=true
resource_event_mutations_settled=true
resource_event_replay_equal=true
```

同一证据包还验证：

- 战技点增加和消耗均进入真实 `OnListenBpChange` 光锥监听链。
- 能量增加和消耗均进入真实 `OnSPChange` 光锥监听链。
- 已安装 BP 监听器不响应能量事件，已安装 `OnSPChange` 监听器不响应 BP 事件。
- callback mutation 具备 settlement、来源审计并可 replay。
- 伪造 `sp.change` 时 blocked、零 mutation、state unchanged。

## 串行验证

均使用单进程、低优先级、小型 `/tmp` 产物；未运行 P1-P7 聚合或 `validate_v0_209`。

```bash
ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m simulator_v8_clean_core.tools.validate_p8_s8_light_cone_remaining_gameplay_closure \
  --resource-events-only \
  --tbgd-root /home/zhangjinhao/code/hsr/turnbasedgamedata-main \
  --output-dir /tmp/hsr_p8_s8_resource_only_final_v2

ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m simulator_v8_clean_core.tools.validate_v0_286 \
  --resource-events-only \
  --output-dir /tmp/hsr_p8_s8_resource_v0_286_focused

ionice -c 3 nice -n 15 env PYTHONDONTWRITEBYTECODE=1 \
  python3 -m simulator_v8_clean_core.tools.validate_p7_s1_transition_trust_contract \
  --output-dir /tmp/hsr_p8_s8_resource_p7_s1_rerun

env PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile \
  simulator_v8_clean_core/resource_event_contract.py \
  simulator_v8_clean_core/systems/mutation_events.py \
  simulator_v8_clean_core/systems/event_dispatch.py \
  simulator_v8_clean_core/tbgd/lowering.py \
  simulator_v8_clean_core/tools/validate_v0_286.py \
  simulator_v8_clean_core/tools/validate_p7_s1_transition_trust_contract.py \
  simulator_v8_clean_core/tools/validate_p8_s7_light_cone_status_condition_listener_closure.py \
  simulator_v8_clean_core/tools/validate_p8_s8_light_cone_remaining_gameplay_closure.py

git diff --check
```

结果：全部通过。三份验证目录分别约 40 KiB、44 KiB、52 KiB。

完整 S8 验证在超过约两分钟预算后主动终止；完整历史 v0_286 在超过约九十秒预算后主动终止。二者均未作为通过证据，随后使用上述资源专用模式完成本次直接范围验证，避免重复全量 lowering 和无关矩阵。
