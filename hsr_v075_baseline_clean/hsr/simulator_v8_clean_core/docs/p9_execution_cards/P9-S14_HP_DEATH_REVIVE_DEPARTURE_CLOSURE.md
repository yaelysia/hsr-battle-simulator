# P9-S14 生命、死亡、复活、limbo 与离场闭合执行卡

## 执行配置

- 对应问题：P9-I14、P9-I09 单位生命周期部分；机制包 M12、M07。
- 硬前置：P9-S13 已验收并形成检查点，S9 event partition 当前。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：生命状态机同时影响可选目标、队列、状态清理、死亡回响和 replay，必须原子且全局唯一。

## 当前事实与阶段结果

当前 M12 有 7 个顶层来源族、48 次出现，涉及15条角色。现有 unit lifecycle、死亡事件、
召唤清理和 P8-R2 死亡链可复用，但角色来源还有锁血、负生命、即时死亡、不可选、limbo、
复活和离场组合。

完成后，所有战斗单位共用一套类型化生命状态机。生命变化、dying/dead/reviving/limbo/
departed/selectable 状态、队列清理、关系对账和 S14-owned 事件在单一 atomic transition 中
一致；同次死亡只有一个规范身份，回响不会重复触发。

## 详细目标

1. 闭合 SetHP、LoseHP/ratio、negative HP、HP lock/unlock、force/immediate death 和 entity action state 来源。
2. 明确 alive、dying、dead、reviving、limbo、departed、unselectable 的合法转换和互斥不变量。
3. 死亡/复活/离场同步更新 target、queue、status、summon/relation 和 wave membership。
4. 生产 before-dying/death/defeated/revive/departed/selectability 等 S14-owned 事件，身份稳定去重。
5. 复活来源、次数、恢复值和状态清理来自 typed IR；不能用默认复活或角色名规则。
6. 两次正式动作/事件间快照连续，禁止验证器直接改 defeated flag 制造正例。

## 本阶段不做

- 不处理记忆 owned-combatant 专属出生/死亡规则。
- 不实现死亡动画、慢镜头或 UI 灰化。
- 不在角色 handler 直接移除 queue/status 绕过 unit lifecycle。
- 不把怪物专属阶段规则扩进当前角色卡。

## 架构与负例

- HP 与 defeated/selectable/queue 状态矛盾、重复 death identity、伪 revive source 和 departed unit 行动均 blocked。
- lifecycle transition 任一子系统对账失败时整体回滚。
- 同一死亡事件重复派发不得重复回能、状态或追加动作。
- 生命为零但存在明确 limbo/negative-HP 规则时按来源状态机，不按数值单独猜死亡。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| HP/lifecycle family 闭合 | M12 来源零内部 gap | lifecycle matrix |
| 状态机合法 | 全转换和互斥不变量通过 | transition graph |
| 跨系统一致 | target/queue/status/relation 同步 | reconciliation matrix |
| 事件唯一 | S14-owned 事件由正式转换生产且去重 | death/revive trace |
| 连续/replay | 正式前后快照连续并可重放 | replay samples |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_hp_lifecycle_family_gap_count=0
s14_lifecycle_event_family_gap_count=0
unit_lifecycle_state_machine_typed=true
hp_defeated_selectable_queue_consistent=true
death_event_identity_unique=true
revive_and_departure_source_backed=true
lifecycle_reconciliation_failure_atomic=true
formal_snapshots_continuous=true
sampled_lifecycle_replay_equal=true
character_specific_death_handlers=0
```

## Gap 与停止条件

- 新状态无法由现有 unit lifecycle 表达：建立通用状态/转换，先评估召唤、波次和 target 影响。
- 来源只有表现死亡或动画标记：non-gameplay，不进入状态机。
- 事件需要 S17 独立实体 producer：记录 obligation，S14 提供通用 consumer。
- 旧验证直接注入 defeated state：不得作为正例；迁移有效谓词或退役。

## 拟改范围

- `systems/unit_lifecycle.py`、`battle_state_transition.py`、`target.py`、`queue.py`。
- `systems/status.py`、`summon.py`、`wave.py` 仅生命周期对账的最小修改。
- HP/lifecycle lowering、事件 IR。
- 主验证 `tools/validate_p9_s14_hp_death_revive_departure_closure.py` 和报告。

## 验证与资源

- 按 M12 和 S14-owned events 窄投影；使用连续正式动作/ability 产生生命转换。
- 不构造完整队伍世界；只保留能证明跨系统不变量的最小真实单位关系。
- direct 最多 2 项：unit lifecycle atomicity、death event/replay，仅实际触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 P3/P7/P8 聚合。

## 唯一执行清单

- [ ] 当前 HP、死亡、复活、limbo、离场来源零内部 gap。
- [ ] 单位生命状态机及合法转换类型化。
- [ ] target/queue/status/relation/wave 对账原子一致。
- [ ] S14-owned 事件正式生产、稳定去重且不可伪造。
- [ ] 连续快照、settlement、audit 和 replay 闭合。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
