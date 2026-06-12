# v0.76 检查点：ActionTransition 与状态变更内核

## 目的

本检查点把结算层从“日志旁路记录”继续推进为“动作状态转移记录”：

```text
ActionRequest + before_snapshot + StateChange[] -> after_snapshot
```

目标是不再只从 route trace 或 log 反推动作过程，而是在动作执行同一位置生成可序列化、可追溯、可复现的 transition。

## 本次提交范围

- `simulator_v7_7/hsr_engine/kernel.py`
- `simulator_v7_7/hsr_engine/settlement/__init__.py`
- `simulator_v7_7/hsr_engine/settlement/collector.py`
- `simulator_v7_7/hsr_simulator_prototype_v7_7.py`

## 新增核心对象

`hsr_engine.kernel` 新增以下通用数据对象：

- `SourceRef`
- `ActionRequest`
- `TargetResolution`
- `StateChange`
- `ActionTransition`

当前编码：

```text
transition: hsr.kernel.action_transition.v1
snapshot:   hsr.kernel.full_scene_snapshot.v1
```

## 当前 transition 输出

每个 action settlement 现在包含：

```json
{
  "transition": {
    "encoding": "hsr.kernel.action_transition.v1",
    "snapshot_encoding": "hsr.kernel.full_scene_snapshot.v1",
    "request": { "...": "..." },
    "target_resolution": { "...": "..." },
    "before_snapshot": { "...": "full_scene_snapshot" },
    "after_snapshot": { "...": "full_scene_snapshot" },
    "state_changes": []
  }
}
```

`before_snapshot` / `after_snapshot` 复用现有 `full_scene_snapshot()`，覆盖资源、状态、行动轴、队列、触发计数、敌人机制 flags 等当前完整场面信息。

## 已收敛的状态写入

以下核心状态字段的运行期写入已经收敛到 `StateChange -> commit_state_change()`：

- `global.skill_points`
- `global.skill_point_cap`
- `global.flags.*`
- `unit.hp`
- `unit.shield`
- `unit.energy`
- `unit.max_hp`
- `unit.hp_bars_remaining`
- `unit.alive`
- `unit.flags.*`

当前搜索结果显示，HP、护盾、能量、SP、存活、多血条等字段的直接写入基本只剩初始化和 commit 层内部。

## 本次发现并修复的问题

`phase_hp` 敌人触发血条切换时，`apply_damage_result()` 中相位 flag 的 reason 使用了未定义变量 `label`。

现在改为稳定 reason：

- `damage:phase_transition:current_phase`
- `damage:phase_transition:monster_phase`

临时 phase_hp 验证确认以下字段会进入同一个 `ActionTransition.state_changes`，并同步到 `after_snapshot`：

- `unit.hp_bars_remaining: 2 -> 1`
- `unit.flags.current_phase: 1 -> 2`
- `unit.flags.monster_phase: 1 -> 2`

## 验证结果

已执行：

```bash
cd /home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr
python3 -m compileall -q simulator_v7_7
python3 -B simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
python3 -B simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only --route-mode exact --output /tmp/hsr_kernel_snapshot_c0_to_c8.json
python3 -B simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only --route-mode auto_probe --auto-probe-steps 1 --output /tmp/hsr_kernel_snapshot_auto_probe.json

cd /home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr/simulator_v7_7
python3 -B test_phase3_verify.py
python3 -B test_phase4_verify.py
```

结果：

- model pack validation: ok
- C0->C8 exact route: `route_assertions.ok = true`
- route steps: 8
- log events: 172
- Tribbie follow-up total: `4393.00559968331`
- Seele skill total: `115919.63539530325`
- auto_probe assertion: ok
- break / DoT phase3 verification: pass
- super-break phase4 verification: pass

## 仍未完成

这还不是最终战斗状态机。下一步重点：

1. 把 queued action、turn tick、route effect/setup effect 也表达为独立 transition 或 battle transition；
2. 把 `DamageSettlement`、`ModifierLedger`、`StatusChange`、`ResourceChange`、`AVChange` 从宽泛 `StateChange` 里进一步强类型化；
3. 让 transition 可作为下一步输入的权威快照，而不是只挂在 route trace 下；
4. 建立 RNG ledger，用于目标选择、暴击、命中、抵抗等随机过程；
5. 继续把剩余特殊机制从硬编码路径迁移到规则/IR 驱动。
