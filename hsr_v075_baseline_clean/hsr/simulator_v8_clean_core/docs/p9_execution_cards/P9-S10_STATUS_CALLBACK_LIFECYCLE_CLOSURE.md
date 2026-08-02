# P9-S10 状态生命周期、属性修改与 callback 事件闭合执行卡

## 执行配置

- 对应问题：P9-I10、P9-I09 状态部分；机制包 M08、M07。
- 硬前置：P9-S9 已验收，其 event partition 当前且完整。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：角色来源大量复用状态和回调，旧窄准入会把同一 handler 重复报成数千个缺口。

## 当前事实与阶段结果

当前 M08 有 13 个来源族、3,792 次出现，覆盖全部79条角色。`StatusSystem` 已有添加、移除、
驱散、叠层、持续时间和部分 callback/runtime handler；主要缺口是 callback event/task admission、
modifier/property value 形状和统一 effect route。

完成后，当前状态 family 和 S9 分配给状态领域的事件族零内部 gap。普通 ability 和状态
callback 通过同一 EffectRegistry/计划执行状态、动态值和属性修改；callback 的 producer、
mutation、状态实例、正式事件、settlement 和 replay 保持同一连续链。

## 详细目标

1. 复用 P2 状态实例和生命周期，不建立角色状态子系统。
2. 闭合 add/remove/self-remove/dispel/remodifier、stack、duration、behavior flag、modifier value 和 property stack 来源形状。
3. 状态实例保存 owner/caster/source、生命周期、stack/duration、动态值和 callback 引用的稳定身份。
4. callback task 调用 S4-S8 公共 effect/condition/target/control 路由，不复制 opcode handler。
5. 生产并派发 OnCreate/OnDestroy/OnStack/ModifierAdd/Remove 等 S10-owned 事件；同次生命周期不重复。
6. 默认生命周期只来自类型化来源与已验收 P2 规则，不读取文本；特殊叠层/刷新规则必须显式来源。
7. 光环、跨波次和成员变化只复用现有通用 status/halo relation，不为角色另建路径。

## 本阶段不做

- 不重写 P2 已验收状态底座。
- 不实现纯表现 modifier effect、status desc 或 UI mark。
- 不在 callback 中手工执行伤害/资源/队列；交公共 handler 和后续领域阶段。
- 不用角色文本决定可叠层、持续时间或驱散顺序。

## 架构与负例

- callback event 正确但 task/source/target 错误时整组原子回滚。
- 伪状态实例、重复 callback ID、跨 owner 状态、stack/duration 非法和来源篡改必须拒绝。
- OnCreate/Destroy 只能由真实 lifecycle 产生，不能外部直接伪触发。
- presentation callback 零 mutation、零 gameplay event/RNG。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 状态 family 闭合 | M08 lowering/admission/runtime 零 gap | status family matrix |
| callback 共用执行 | task 走 S4-S8/EffectRegistry | call-path audit |
| 生命周期事件真实 | create/stack/remove 由正式状态变化产生 | lifecycle trace |
| 失败原子 | 任一 child/来源冲突整组零副作用 | negative matrix |
| 来源/replay | 状态与 callback mutation 可追溯重放 | audit/replay sample |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_status_family_gap_count=0
s10_status_event_family_gap_count=0
ability_and_callback_effect_route_shared=true
status_instance_identity_complete=true
stack_duration_and_removal_source_backed=true
lifecycle_events_producer_backed_and_unique=true
callback_group_failure_atomic=true
presentation_callback_gameplay_effect_count=0
sampled_status_replay_equal=true
character_specific_status_handlers=0
```

## Gap 与停止条件

- callback 中出现后续领域 effect：公共路由可到达但领域 producer not-proven，记录给 S11-S15，不伪造完成。
- 当前真实状态形状需要 P2 模型无法表达：先提出通用模型变更和影响，不局部塞任意 dict。
- 旧 P2 验证假设与当前来源冲突：判断契约有效性，不能迁就旧脚本。
- event partition 陈旧：停止，回 S9 更新。

## 拟改范围

- `systems/status.py`、`systems/status_callbacks.py`、`systems/effect.py`。
- `rules/ir.py`、`tbgd/lowering.py` 的状态/callback payload。
- `systems/event_dispatch.py` 仅接 S10-owned 生产者。
- 主验证 `tools/validate_p9_s10_status_callback_lifecycle_closure.py` 和报告。

## 验证与资源

- 按 M08 与 S10-owned events 窄投影；每种 lifecycle/source shape 选真实最小样本。
- 正例必须从正式 ability/status application 产生，不能直接调用 callback 冒充生命周期。
- direct 最多 2 项：状态生命周期、atomic callback；仅触达时运行小切片。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 P2 全阶段或全角色 callback 聚合。

## 唯一执行清单

- [ ] 当前状态和属性修改 family 零内部 gap。
- [ ] S10-owned 状态事件由真实 lifecycle 唯一生产。
- [ ] 普通 ability/callback 共用 effect、condition、target 和 control 路由。
- [ ] stack/duration/value/source 和原子失败语义完整。
- [ ] settlement、audit、replay 与表现退役证据成立。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
