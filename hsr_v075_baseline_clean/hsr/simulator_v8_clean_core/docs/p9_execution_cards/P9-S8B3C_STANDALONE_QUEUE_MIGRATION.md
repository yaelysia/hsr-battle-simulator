# P9-S8B3C Queue Standalone Ability 迁移执行卡

## 执行配置

- 硬前置：P9-S8B3B 已验收并提交。
- 推荐：5.6 Sol / `high`。
- 本卡只迁移 scheduler 已准入的 standalone ability。

## 目标与边界

1. queue resolution 继续唯一决定 graph、actor、targets 和 queue identity；scheduler 不造临时
   action definition，也不解释 task 树。
2. `execute_standalone` 查询 B3A 的 `standalone_root` entry，并复用 B3B ability hooks 与 S8B2。
3. queue graph 缺失、身份不一致、递归或 leaf blocker 时，在发布 dequeue/ability 结果前
   fail-closed；既有 queue terminalization 语义保持一致。
4. standalone 的 mutation/event/RNG/settlement/node projection 原样运输到 scheduler 的原子提交，
   不进行第二次 reducer 模拟或从记录反推结果。
5. 非角色 standalone 来源保持外部内容依赖；不因本卡目录不存在而伪装成功。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 输入权威 | 已准入 queue drain plan 与 `QueueResolutionIR` 唯一提供 graph、actor、targets、queue identity |
| 图权威 | B3A 中 `invocation_role=standalone_root` 的 phase callback entry 与唯一 `TaskGraphIR` |
| 领域调用上下文 | ability 内部的不可变调用适配器；action 调用携带真实 action definition，queue standalone 明确不携带 action definition |
| 候选状态 | B2 `TaskGraphExecutor`；ability hook 只返回领域通道，不再提交整图 |
| 发布权威 | scheduler 最外层 queue transition 的一次原子提交；不得在 ability 结果与 queue transition 之间增加子提交 |
| 后续归属 | 跨 event active graph stack 归 S8B5；standalone damage/hit 的动作无关 source frame 归 S8C |

本卡只迁移一个消费域，不建立第二套动作或提交权威。调用适配器只运输已经由 action 或 queue
生产者确定的事实，不能自己推导动作身份、目标合法性或 queue resolution。

## 生产不变量

1. `standalone_root` 必须按 phase + callback 查询 B3A entry；phase 不属于 resolution 声明的 graph、
   actor/targets 与 queue entry 不一致、entry/graph 不唯一时，在第一条 mutation 前 blocked。
2. queue standalone 不得构造 `ActionDefinitionIR`，也不得把 standalone ability 伪装成玩家
   `ActionCommand`。依赖真实 action definition 的 leaf 必须给出精确 blocker，留给既定后续阶段。
3. action 与 standalone 可复用同一组 leaf/condition/count/target/graph hook，但 hook 读取的是类型化
   调用上下文；不得从字符串前缀、临时 action id 或 metadata 猜 invocation kind。
4. B2 结果只作为 scheduler 最外层 queue transition 的候选状态与正式通道输入。scheduler 不得对
   ability 子结果调用 `finalize_selected_execution_graph`；最外层 `_transition` 仍是唯一发布门。
5. formal standalone 任一 callback blocked 时，返回入口状态且 mutation/event/RNG/成功 settlement
   全空；scheduler 从原 queue 状态执行既有 terminalization，不能发布 dequeue 或部分 ability 通道。
6. `external_legacy` 不得误入 formal 路径；旧外部内容若仍依赖 legacy adapter，保持明确隔离并列账，
   不作为本卡成功证据。

## 允许修改

- `systems/ability.py`
- `systems/scheduler.py`
- B3B adapter（仅复用，不新增控制语义）
- 一个聚焦验证器和报告

不得修改 task graph 模型、materializer、RuleBook 查询语义、状态 callback 或跨事件上下文协议。
若完成本卡需要这些变更，提交 `plan_mismatch`，不得在本卡吸收。

## 验收谓词

```text
queue_standalone_uses_formal_graph_authority=true
queue_cannot_bypass_graph_admission=true
standalone_reuses_action_ability_hooks=true
standalone_root_is_in_active_graph_stack=true
queue_failure_publishes_no_partial_ability_channels=true
temporary_action_definition_created=false
temporary_action_command_created=false
standalone_action_dependent_leaf_fails_closed=true
standalone_child_atomic_commit_count=0
status_callback_behavior_changed=false
```

## 验证预算

- 一个主入口；一个真实 queue standalone 来源、一个最小成功 fixture 和每条新增生产不变量一个
  最小反例。真实来源若被后续 leaf 语义阻断，只证明正式路由和零泄漏，不冒充 executable。
- 45 秒、512 MiB、160 KiB evidence、验证器硬上限 560 非空行。
- 主验证前预检已在 260 行原估算失效时暂停并复核：公开 scheduler 入口所需的 typed queue
  fixture、B3B action direct、四通道运输和一个真实来源属于同一集成闭环，拆掉任一项都会降低
  证明力；继续沿用 260 行只会迫使调用私有 scheduler 入口或压缩反例。修订后冻结范围，不得再
  增加并列 fixture、源码字符串自证或第二个验证入口。
- 不重跑 B1-B3B 主入口，不构建完整 Canonical IR。

## 唯一执行清单

- [x] queue standalone 复用正式目录、共享执行器和同一 hook。
- [x] queue admission、原子失败和结果运输完成。
- [x] 唯一主验证通过并完成五面验收。
