# P9-S7 动作、事件与结算上下文条件族闭合执行卡

## 执行配置

- 对应问题：P9-I07 第二部分；机制包 M05。
- 硬前置：P9-S6A、S6B 已验收，S6A 责任目录与当前源码/来源指纹一致。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：剩余条件横跨 action、event、queue、damage、resource、toughness 等瞬时上下文，需要严格 typed payload 和生产者责任。

## 当前事实与阶段结果

S6B 已关闭 committed-state 条件。按当前来源实时重建，S6A 留给 S7 的完整分母为 48 条记录、
17 个 family；这里的数量是当前调查事实，不是固定验收常量。真实集合只涉及动作、队列、事件参数、
伤害、资源变化和状态 callback，没有当前 S7 来源记录要求 heal 或 toughness 上下文。

完成后，当前 M05 条件 family 在 lowering/evaluator 层零 gap。S7 建立统一
`EvaluationContext` 的类型化 transient fact 通道，并为每个字段记录 S9-S16 的真实生产者责任。
已有生产者必须走正式链验证；尚待领域阶段的生产者只能标记 end-to-end not-proven，不能用
裸 GameEvent 或手工字典冒充。

## 闭合地图

### 权威边界

- 完成分母：从当前 `CharacterConditionResponsibilityCatalog` 选择全部
  `evaluation_stage=p9_s7_transient_context` 的记录；必须与 S6A 同来源指纹，和 S6B、排除集合互斥。
- 输入权威：ConditionIR 的严格字段、已解析目标集合，以及正式 transient fact provider；
  `event_payload`、global flags、source trace 和日志均不是 S7 新 family 的事实权威。
- 输出权威：统一 `true / false / blocked`。业务 false 可选择失败分支；缺 provider、错事实类型、
  错调用身份或未来 producer 未实现必须 blocked，且不产生 mutation、event 或 RNG。
- 当前已有来源权威只有 `action.target_type` 与 `action.dynamic_target`，来自 S5C1/S5C2 的
  `ActionTargetContractIR`。动作查询、已准入能力任务和动作窗口已经显式接收 typed provider，
  但当前两条真实 S7 来源都没有形成可连续执行的正式内容链：动态目标准入依赖 S8，状态 callback
  运输依赖 S9。因此本阶段只提交 source-backed provider 组件证据，真实 gameplay end-to-end 计数
  保持零；普通事件字典不能升级为事实权威。其余字段只有 evaluator 组件语义和 producer obligation。

### 真实字段值域与后续 owner

| family | 当前字段形状与真实值域 | 类型化 fact | 正式 producer |
|---|---|---|---|
| `ByCheckModifierCallBackModifierValue` | 比较符；数值表达式；`Layer/LifeTime` | callback 数值 | S10 |
| `ByCompareNextUnusedInsertAction` | `ActionTypeIs+CasterIs` 或 `CustomTagIs+Inverse` | 下一条未消费插入动作是否匹配 | S13 |
| `ByCompareParamString` | 单个非空字符串 | 事件参数字符串 | S9 |
| `ByCompareSPChangeTag` | 当前来源恰一项枚举标签；多项组合语义未获来源证明时阻断 | 资源变化标签集合 | S12 |
| `ByCompareTurnActionEntityTeamType` | 当前只有 `TeamLight`，模型同时严格支持合法敌方值 | 行动实体队伍 | S13 |
| `ByCompareUnusedInsertAbilityCount` | 比较符与数值表达式 | 未消费插入能力数量 | S13 |
| `ByCompareUnusedUltraSkillCount` | 比较符、数值，可选 owner 与是否计入插入动作 | 未消费终结技数量 | S13 |
| `ByCurrentSkillTargetType` | 目标类型字符串或严格布尔 `IsDynamic`；二者互斥 | 动作目标类型/动态目标标志 | current |
| `ByDamageSourceContainBehaviorFlag` | 非空、无重复行为标签列表 | 伤害来源行为标签集合 | S11 |
| `ByHasInsertActionByTarget` | 类型化目标表达式 | 指定目标是否存在插入动作 | S13 |
| `ByIsDamageType` | 非空、无重复属性列表与类型化目标 | 该目标关联的伤害属性 | S11 |
| `ByIsInCharmAction` | 无额外字段 | 是否处于魅惑动作 | S16 |
| `ByIsSplitDamage` | 类型化目标，可选严格布尔反转 | 是否为分摊伤害 | S11 |
| `ByIsTurnActionEntity` | 类型化目标，可选严格布尔反转 | 当前行动实体身份 | S13 |
| `ByTurnOwnerActionPhaseEnd` | 可选严格布尔反转 | 回合拥有者动作阶段是否结束 | S13 |
| `ByTurnOwnerHasActionInTurn` | 无额外字段 | 回合拥有者本回合是否已有动作 | S13 |
| `ByTurnOwnerHasPendingOneMore` | 可选严格布尔反转 | 回合拥有者是否待执行额外回合 | S13 |

`TargetType`、`CasterIs` 和 `SkillOwnerType` 必须继续复用 S5A/S5B 的类型化目标与文件内别名作用域。
数值继续复用 S4，比较符继续复用 S6B。`TagList`、字符串形式的 `IsDynamic` 等当前真实序列化形状
必须在 lowering 边界规范化；未知同级字段、未知枚举、重复集合成员和非严格 bool 均 fail-closed。

### 身份与窗口口径

- transient fact 必须携带事实种类、上下文种类、调用身份、窗口、领域 producer authority 和来源身份；
  provider 返回的身份或上下文种类与当前求值请求不一致时 blocked。
- P9 阶段编号只存在于 obligation ledger；运行时不得依赖 `P9-S9` 一类工程计划名称。
- S7 不预先猜测 S9-S16 尚未建立的具体窗口枚举。未来 producer 必须在对应阶段定义合法窗口并
  从正式事件/队列/结算对象投影，S7 只保留并核对该窗口身份。
- `process_only` 事件或手工 payload 本身不得成为正式 producer；若同一动作窗口另有已准入动作
  provider，权威来自该 provider 而不是事件。fixture 只可证明
  evaluator 组件语义，报告必须与真实 producer evidence 分栏。

## 详细目标

1. 校验并消费 S6A 责任目录，S7 集合不得增删或与 S6B 重叠。
2. 建立严格 transient fact request/resolution/provider 契约，覆盖闭合地图中的全部七类上下文及身份。
3. 条件 lowering 只引用明确字段；缺 payload、错误事件 window 或过期 action identity blocked。
4. 复用 S4 numeric、S5B relation 和 S6B comparator/quantifier，不按条件名复制 evaluator 分支。
5. 为每个 transient 字段绑定现有或未来 S9-S17 生产者，并输出 producer obligation ledger。
6. 当前已有正式生产入口的动作上下文族至少有 source-backed true/false/blocked 组件证据；
   不把尚未运输到 callback 的真实角色链标成端到端完成。

## 本阶段不做

- 不提前实现 S9-S17 的事件、伤害、资源、死亡或击破生命周期。
- 不在 evaluator 中从 source trace、状态日志或全局 flags 猜 transient context。
- 不手工创建与状态不连续的 GameEvent 作为端到端正例。
- 不把尚无生产者解释成 evaluator implementation failure。

## 架构与负例

- provider 事实种类、上下文种类、调用身份或来源身份不一致，以及 action ID/level 过期均 blocked；
  动作准入投影还必须携带目标查询、目标选择、选择上下文与契约四类完整身份。
- 正确字段但错误上下文 kind 不能被相似字段名接受；具体领域窗口由对应正式 producer 阶段验收。
- `process_only` 事件 payload 不能自行提供 gameplay context。
- producer obligation 只能由 S9-S17 正式入口关闭，validation fixture 不改变状态。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| S7 集合可信 | 继承分区当前、完整、互斥 | inherited partition check |
| evaluator 零 gap | 当前剩余条件均 typed/evaluable | contextual condition matrix |
| payload 严格 | kind/invocation/identity/字段完整校验 | payload negatives |
| 生产者诚实 | 每字段有正式 producer 或后续 obligation | producer ledger |
| 组合复用 | 不复制 numeric/target/comparator | code audit |

## 结构化通过谓词

```text
s6_partition_current=true
s7_contextual_family_gap_count=0
current_condition_family_internal_gap_count=0
transient_context_schema_typed=true
transient_fact_invocation_identities_validated=true
process_only_event_not_gameplay_context=true
action_source_components_use_typed_provider=true
current_gameplay_end_to_end_count=0
future_producers_recorded_not_faked=true
missing_or_stale_context_blocked=true
character_specific_condition_handlers=0
```

## Gap 与停止条件

- evaluator 语义完整但正式生产者在 S9-S17：记录 `producer_not_proven`，不阻断 S7 evaluator 结论，但阻断最终 S20。
- 条件字段无法归属任何真实 producer：退回 S3/source audit，不能建立全局万能 dict。
- 需要修改事件身份根契约：限制在类型定义，实际派发交 S9；若不可分离，暂停修订依赖。
- S6A 责任目录陈旧：停止，不能自行重分区后继续。

## 拟改范围

- `rules/condition_state.py`、`rules/evaluator.py` 的 typed transient context。
- `systems/action_selection.py`、`action_event_contract.py`、`ability.py`、`trigger.py`、`target.py`
  的显式只读上下文投影。
- `tbgd/expression_lowering.py` / `rules/ir.py` 的条件字段。
- 主验证 `tools/validate_p9_s7_contextual_condition_closure.py` 和报告。

## 验证与资源

- 只构建 S7 condition IR；用现有正式 action target contract 证明当前字段，未来 producer 的正反组件
  证据明确标记 validation fixture，不能计入真实端到端完成数。
- 一个主入口。S6A、S6B、S5C2 阶段验证均已冻结为 `historical_evidence`，不得重跑；若调用链审查
  发现现行 active direct，最多运行 1 个，否则 direct 为 0。
- 硬预算：8 分钟、1 GiB、5 MiB、900 非空行；630 行为默认软复核点，预计越过时先缩小证据或
  下沉生产不变量，不得致密压行。
- 不跑 S6A/S6B 完整主入口、不跑领域 runtime 聚合、不写合成全事件世界。

## 唯一执行清单

- [x] S7 继承分区当前且条件内部 gap 为零。
- [x] transient context 类型、window 和身份契约完整。
- [x] 已有动作来源通过 typed provider 形成组件证明，未完成的运输与未来 producer obligation 诚实记录。
- [x] 缺失、错 kind、错 window、过期和 process-only 负例 blocked。
- [x] evaluator 复用 S4-S6B，无万能 payload 或角色特判。
- [x] 主验证、必要 direct 和资源审计通过并提交验收。
