# P9-S13 timeline、queue、插入与额外动作闭合执行卡

## 执行配置

- 对应问题：P9-I13、P9-I09 队列部分；机制包 M11、M07。
- 硬前置：P9-S12 已验收并形成检查点，S9 event partition 当前。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：行动身份、额外行动和队列进展错误会破坏推演树与确定性，且与动作窗口、资源和目标强耦合。

## 当前事实与阶段结果

当前 M11 有 9 个来源族、234 次出现，涉及62条角色。现有 timeline、queue、scheduler、
skill continuation 已有基础，但角色来源中的 delay lock/redirect、insert ability/action、one-more
和相关条件/事件仍未完整闭合。

完成后，行动延迟、提前、锁定/重定向、插入 ability、插入完整 action 和额外行动具有不同
typed identity 与生命周期。队列保证有限进展；推演器只选择内核公布的行动，不负责排序、
成本或效果。S13-owned queue/action events 由正式 scheduler/queue 产生并可 replay。

## 详细目标

1. 闭合 Modify/Set/Reset/Lock/Redirect action delay 和 near-target 关系来源。
2. 区分插入 ability、插入 action、one-more continuation、追加攻击和普通下一回合。
3. queue item 保存 owner/source/action/target/window/priority/sequence 和稳定 identity。
4. 资源预占、目标候选、action set 和事件身份在提交前重新校验，拒绝 stale queue plan。
5. 生产 insert/start/finish/abort/phase 和 action-delay 等 S13-owned 事件，同次生命周期不重复。
6. scheduler 对空队列、全 blocked、重复插入和自循环有明确前进/终止语义。

## 本阶段不做

- 不决定敌我 AI 行动。
- 不把动画等待、视觉 delay 或 action-bar 显示当 timeline 规则。
- 不把独立行动实体出生/owner 生命周期放进队列实现；S17 负责实体。
- 不按角色名定义优先级或额外行动次数。

## 架构与负例

- duplicate identity、source/owner 错配、已死亡/不可行动 owner、过期目标和 stale cost 均 blocked。
- 同一额外行动不能被事件重放重复插入。
- queue mutation 失败不改变 timeline、resource、events 或 RNG。
- 无法前进的循环必须结构化 blocked，不能靠任意迭代 cap 静默退出。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| queue family 闭合 | 当前 M11 family 零内部 gap | queue matrix |
| action kind 分离 | ability/action/continuation/follow-up 不混淆 | identity matrix |
| 前进保证 | 合法队列推进，非法循环 fail-closed | progress matrix |
| 事件真实 | S13-owned 事件来自 queue/scheduler | event trace |
| replay/原子 | 插入、资源、目标、顺序可重放 | transition samples |

## 结构化通过谓词

```text
s9_event_partition_current=true
current_timeline_queue_family_gap_count=0
s13_queue_event_family_gap_count=0
insert_ability_action_and_continuation_distinct=true
queue_identity_and_priority_stable=true
timeline_progress_guaranteed_or_blocked=true
stale_queue_plan_rejected=true
duplicate_insert_event_idempotent=true
failed_queue_transition_state_unchanged=true
sampled_queue_replay_equal=true
character_specific_queue_rules=0
```

## Gap 与停止条件

- 来源无法区分 ability 与完整 action：退 S1/S3，不靠名字判断。
- action set 尚未有 producer：记录 S16 obligation，不复制动作定义。
- 独立行动实体关系缺失：交 S17；S13 只提供通用 queue consumer。
- 需要改 scheduler 根进展契约：先审查 P7 影响，选择最小 direct，不跑全量聚合。

## 拟改范围

- `systems/timeline.py`、`queue.py`、`scheduler.py`、`skill_continuation.py`。
- `systems/action_contract.py` / `action_event_contract.py`。
- queue/delay lowering 和相关 IR。
- 主验证 `tools/validate_p9_s13_timeline_queue_extra_action_closure.py` 和报告。

## 验证与资源

- 按 M11 与 S13-owned events 窄投影；用正式 query-submit-scheduler 链执行。
- 不手工向 queue append 内部对象冒充正式来源。
- direct 最多 2 项：timeline progress、queue atomic identity，仅实际触达时运行。
- 预算：10 分钟、1 GiB、8 MiB、1,000 行；不跑 P7 全阶段、波次/召唤聚合。

## 唯一执行清单

- [ ] 当前 timeline/queue/insert/one-more 来源零内部 gap。
- [ ] 各 action kind、identity、priority 和生命周期严格分离。
- [ ] queue 有前进保证，stale/重复/非法循环原子 blocked。
- [ ] S13-owned 事件由正式 scheduler/queue 原生产生。
- [ ] 推演器只选择合法行动，无 AI 或角色优先级特判。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
