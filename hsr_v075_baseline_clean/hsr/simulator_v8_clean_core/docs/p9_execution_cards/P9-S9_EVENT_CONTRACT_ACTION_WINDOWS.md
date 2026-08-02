# P9-S9 事件所有权分区、通用契约与动作窗口执行卡

## 执行配置

- 对应问题：P9-I09 主干；机制包 M07。
- 硬前置：P9-S8 已验收并形成检查点。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 理由：事件身份和 payload 是状态、伤害、资源、死亡等机制共用边界，必须先固定所有权和失败语义。

## 当前事实与阶段结果

当前目标来源有 125 个战斗事件族、2,405 次事件出现。现有 `event_dispatch`、
`action_event_contract`、status callback 和 atomic commit 可复用，但旧 lowering 仍以窄事件名/
task admission 拦截大量真实来源。

完成后，当前事件族按真实生产者形成 S9-S17 穷尽互斥分区。S9 建立统一事件身份、typed
payload、候选/派发结果和 callback 调用契约，并关闭动作、技能、攻击边界和通用队列窗口中
由当前生产代码直接拥有的事件。其他事件只留下明确责任阶段，不合成生产者。

## 详细目标

1. 从 S0 当前来源动态建立 event family -> producer domain -> consumer/callback 的责任矩阵。
2. 分区覆盖动作/技能、状态、伤害/治疗/护盾、资源、队列、单位生命、击破、形态、战斗事件实体和波次。
3. 统一事件身份包含事件 kind/window、producer identity、source/target、动作/状态/结算实例和生命周期序号。
4. typed payload 只携带该事件语义所需字段；缺字段、额外 gameplay 字段和错误 kind fail-closed。
5. 候选事件、提交后正式事件、dispatcher 和 callback 在同一 transition 连续链路产生。
6. 关闭当前正式动作/技能的 before/after use、attack begin/end、insert/phase 等 S9 责任事件。
7. client `_CL` 和 process-only 事件不进入 gameplay dispatcher。

## 本阶段不做

- 不提前生成状态、伤害、资源、死亡、击破或独立实体领域事件；交 S10-S17。
- 不建立每个事件名一个 dispatcher/handler。
- 不把裸 `GameEvent` 拿到无关 BattleState 中执行 callback。
- 不复活旧事件对 whitelist 作为最终架构。

## 架构与负例

- S9-S17 分区合集必须等于当前125个战斗事件族，交集为空；新事件未归属即 blocked。
- 同一事件身份不同 payload/来源、重复提交、过期动作和伪 settlement identity 必须拒绝。
- producer mutation 失败时没有正式事件；callback 失败按所属原子组回滚。
- 事件排序由 transition/lifecycle 定义，不依赖文件或 dict 顺序。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 分区完整 | S9-S17 穷尽互斥且指纹当前 | event ownership matrix |
| 契约严格 | identity/payload/window/source 校验完整 | contract negatives |
| 动作窗口真实 | 正式 action 产生 mutation 后事件并派发 | action event trace |
| 原子与幂等 | 冲突/重复/失败零额外副作用 | commit matrix |
| 后续责任明确 | 每个未执行族有唯一 producer stage | handoff ledger |

## 结构化通过谓词

```text
event_ownership_partition_current=true
s9_s17_event_union_equals_current_gameplay=true
s9_s17_event_intersection_empty=true
event_identity_and_payload_typed=true
same_identity_conflict_fail_closed=true
failed_producer_emits_no_gameplay_event=true
s9_action_window_family_gap_count=0
formal_action_event_chain_continuous=true
client_and_process_only_event_dispatched_count=0
event_name_specific_dispatch_handlers=0
```

## Gap 与停止条件

- 事件无法确定真实 producer：记录 source/admission gap，阶段不能将其随意归 callback。
- 建立 typed payload 需要领域状态字段：只建字段契约并归相应 S10-S17，不伪造 producer。
- 分区遗漏/重叠或只靠固定名单而非当前目录重算：阶段阻断。
- 改动需要跨 core commit 根契约且无法局部兼容：暂停审查影响范围。

## 拟改范围

- `systems/action_event_contract.py`、`systems/event_dispatch.py`、`systems/mutation_events.py`。
- `core/atomic_commit.py` / transition 只在事件原子边界确有缺口时最小修改。
- `rules/ir.py`、角色 callback/event lowering。
- 主验证 `tools/validate_p9_s9_event_contract_action_windows.py` 和报告。

## 验证与资源

- 一次读取 event family，构建 partition；只执行 S9-owned family，其他只验证责任元数据。
- 通过正式 action/executor 产生事件，不手工拼接 mutation 或 dispatcher 顺序。
- direct 最多 2 项：atomic event commit、action event contract，仅实际触达时运行。
- 预算：8 分钟、1 GiB、5 MiB、900 行；不跑125族全部端到端或旧九族聚合。

## 唯一执行清单

- [ ] 当前事件族形成 S9-S17 穷尽互斥责任分区。
- [ ] 通用 identity、payload、window 和原子派发契约完整。
- [ ] S9 动作/技能窗口通过正式 action 链闭合。
- [ ] 同身份冲突、失败 producer、重复和 process-only 负例 blocked。
- [ ] 无事件名专用 handler 或合成后续 producer。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
