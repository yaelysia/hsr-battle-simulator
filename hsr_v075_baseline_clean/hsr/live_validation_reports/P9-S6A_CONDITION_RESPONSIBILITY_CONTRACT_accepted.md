# P9-S6A 条件责任与来源分区契约验收报告

## 结论

状态：accepted。

本阶段只完成条件来源分母、责任目录和 lowering blocker，不宣称新增条件已经可以在战斗中求值。
P9-S6B 与 P9-S7 仍分别负责 committed-state 和 transient-context evaluator。

## 生产结果

- 新增递归不可变的条件责任、问题和目录模型。
- 从角色 scope projection 的类型化语义重建完整条件分母，不使用 `By*` 名称启发式。
- 当前 3,502 条正式条件记录完整分区：3,229 条属于现有 evaluator family；其余 273 条中，
  178 条归 S6B、48 条归 S7、47 条按 occurrence 明确排除，blocked/unclassified 为零。
- 273 条责任行均保存 raw 路径、字段签名、数据权威、所需上下文和后续生产阶段。
- lowering 删除重复的 executable family 列表，统一读取 evaluator 权威；新缺口获得精确阶段原因。
- 未知 family、未知字段、未知嵌套生产者和阶段/来源依据矛盾均 fail-closed。

“现有 evaluator family”只表示该 family 已有生产责任，不表示其全部 3,229 个 payload 都可执行；
payload、目标和动态值准入继续由各自既有契约决定。

## 代码审查发现

首次聚焦结果为绿后，代码审查发现表现分支判定忽略了 `IncludeTaskListTemplate`。真实
`TriggerStanceCountDown_*` 分支会通过全局模板执行击破伤害，不能因为同层存在时间减速表现就
排除。最终规则改为：只有所有实际末端均为 non-gameplay，且不存在未解析 ability/template
跳转时才可排除。姿态条件已重新归入 S6B，并增加结构化聚合门防止同类回归。

这次 finding 说明主验证应放在来源末端审查之后。后续卡先完成分母与引用闭包人工审查，再运行
唯一主入口，避免把开发中间态当成最终证据。

## 最终证据

- 主入口：`validate_p9_s6a_condition_responsibility_contract`，`ok=true`。
- 墙钟：3.80 秒；峰值 RSS：336,984 KiB。
- evidence：321,702 bytes。
- 验证器：514 物理行、477 非空行，低于 600 行预算。
- raw snapshot：1 次；scope projection：1 次；责任目录：1 次；完整 Canonical IR：0 次。
- `compileall`：通过。
- `git diff --check`：通过。

主入口在整个实施过程中共运行六次。前五次分别暴露或跟随了分支排除、来源跳转、空集总门和
注册表漂移等审查修正，最后一次才是验收运行。单次成本很低，但次数明显高于目标，说明本阶段
仍过早运行了主入口。流程现已改为：先完成生产自审与五面 finding ledger，再运行唯一主入口；
开发期只用编译和单个最小反例。本报告不把这些中间运行隐藏成一次。

## 验证器生命周期

`validate_p9_s6a_condition_responsibility_contract` 冻结为 `historical_evidence`。S6B 只消费生产责任
目录并建立自己的单一聚焦入口，不扩写或重跑本验证器。

## 后续边界

- P9-S6B：实现 178 条 committed-state 责任记录涉及的统一三态求值；后续领域生产者缺失时保持
  精确 blocked。
- P9-S7：实现 48 条 transient-context 责任记录所需的动作、事件、伤害、资源和队列上下文。
- P9-S11、S15、S17：提供 HP shared group、韧性分段、body-part/battle-event entity 等正式事实。
- P9-S20：最终按当前来源重新核对全部条件记录，不能直接复用本报告固定数量作为通过门。
