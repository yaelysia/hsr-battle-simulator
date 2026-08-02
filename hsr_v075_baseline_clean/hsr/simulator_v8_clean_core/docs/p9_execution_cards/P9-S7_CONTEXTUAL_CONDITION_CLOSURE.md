# P9-S7 动作、事件与结算上下文条件族闭合执行卡

## 执行配置

- 对应问题：P9-I07 第二部分；机制包 M05。
- 硬前置：P9-S6 已验收，其条件分区 manifest 与当前源码/来源指纹一致。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：剩余条件横跨 action、event、queue、damage、resource、toughness 等瞬时上下文，需要严格 typed payload 和生产者责任。

## 当前事实与阶段结果

S6 应关闭 committed-state 条件并留下 S7 集合。典型 S7 条件包括当前行动实体、战斗事件
实体、当前技能/目标类型、插入动作计数、伤害类型/来源、资源变化标签、韧性和行动窗口。

完成后，当前 M05 条件 family 在 lowering/evaluator 层零 gap。S7 建立统一
`EvaluationContext` 的类型化 transient 视图，并为每个字段记录 S9-S17 的真实生产者责任。
已有生产者必须走正式链验证；尚待领域阶段的生产者只能标记 end-to-end not-proven，不能用
裸 GameEvent 或手工字典冒充。

## 详细目标

1. 校验并消费 S6/S7 分区，S7 集合不得增删或与 S6 重叠。
2. 类型化 action/skill/turn/queue/event/damage/heal/resource/toughness 上下文字段及身份。
3. 条件 lowering 只引用明确字段；缺 payload、错误事件 window 或过期 action identity blocked。
4. 复用 S4 numeric、S5 relation 和 S6 comparator/quantifier，不按条件名复制 evaluator 分支。
5. 为每个 transient 字段绑定现有或未来 S9-S17 生产者，并输出 producer obligation ledger。
6. 当前已有正式生产入口的高频族至少各有真实 true/false/blocked 证据。

## 本阶段不做

- 不提前实现 S9-S17 的事件、伤害、资源、死亡或击破生命周期。
- 不在 evaluator 中从 source trace、状态日志或全局 flags 猜 transient context。
- 不手工创建与状态不连续的 GameEvent 作为端到端正例。
- 不把尚无生产者解释成 evaluator implementation failure。

## 架构与负例

- 同事件身份不同 payload、source/target 交换、action ID 过期和 queue item 不存在均 blocked。
- 正确 payload 但错误 window/kind 不能被相似字段名接受。
- `process_only` 事件不能为 gameplay 条件提供 executable context。
- producer obligation 只能由 S9-S17 正式入口关闭，validation fixture 不改变状态。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| S7 集合可信 | 继承分区当前、完整、互斥 | inherited partition check |
| evaluator 零 gap | 当前剩余条件均 typed/evaluable | contextual condition matrix |
| payload 严格 | kind/window/identity/字段完整校验 | payload negatives |
| 生产者诚实 | 每字段有正式 producer 或后续 obligation | producer ledger |
| 组合复用 | 不复制 numeric/target/comparator | code audit |

## 结构化通过谓词

```text
s6_partition_current=true
s7_contextual_family_gap_count=0
current_condition_family_internal_gap_count=0
transient_context_schema_typed=true
event_action_queue_identities_validated=true
process_only_event_not_gameplay_context=true
existing_producers_use_formal_entrypoints=true
future_producers_recorded_not_faked=true
missing_or_stale_context_blocked=true
character_specific_condition_handlers=0
```

## Gap 与停止条件

- evaluator 语义完整但正式生产者在 S9-S17：记录 `producer_not_proven`，不阻断 S7 evaluator 结论，但阻断最终 S20。
- 条件字段无法归属任何真实 producer：退回 S3/source audit，不能建立全局万能 dict。
- 需要修改事件身份根契约：限制在类型定义，实际派发交 S9；若不可分离，暂停修订依赖。
- S6 manifest 陈旧：停止，不能自行重分区后继续。

## 拟改范围

- `rules/evaluator.py` 的 typed transient context。
- `systems/action_contract.py`、`action_event_contract.py` 的只读上下文投影。
- `tbgd/expression_lowering.py` / `rules/ir.py` 的条件字段。
- 主验证 `tools/validate_p9_s7_contextual_condition_closure.py` 和报告。

## 验证与资源

- 只构建 S7 condition IR；用现有正式 action/event 入口证明可得字段，未来 producer 只做 schema negative。
- 一个主入口，direct 最多 2 项，仅触达 evaluator/action-event contract 时运行。
- 预算：8 分钟、1 GiB、5 MiB、900 行。
- 不跑 S6 完整主入口、不跑领域 runtime 聚合、不写合成全事件世界。

## 唯一执行清单

- [ ] S7 继承分区当前且条件内部 gap 为零。
- [ ] transient context 类型、window 和身份契约完整。
- [ ] 已有 producer 正式证明，未来 producer obligation 诚实记录。
- [ ] 缺失、错 kind、错 window、过期和 process-only 负例 blocked。
- [ ] evaluator 复用 S4-S6，无万能 payload 或角色特判。
- [ ] 主验证、必要 direct 和资源审计通过并提交 `ready_for_review`。
