# P9 执行卡索引

本目录保存 P9 非记忆、非欢愉角色共享机制收口的执行卡。总目标、阶段依赖和唯一 checklist 位于
[`../../P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`](../../P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md)。
工作方式统一服从 [`../AGENT_WORKFLOW_AND_VALIDATION.md`](../AGENT_WORKFLOW_AND_VALIDATION.md)，
不在本索引复制验证协议或模型路由。

## 当前入口

当前没有可直接执行的 P9 卡。

`P9-S8C1A_WEIGHTED_SELECTION_IR_CONTRACT.md` 已完成独立验收。S8C1B、S8C1C 必须由规划线程根据
S8C1A 合并后的实际 materializer/公开 entry 调用面分别制定；在新卡形成 `ready_for_execution` 前不得实施。
本检查点不启动下一张卡。

## 阶段状态

| 状态 | 阶段 |
|---|---|
| 已验收 | S0-S4；S5A、S5B、S5C1、S5C2、S5D1；S6A、S6B；S7 |
| 已验收 | S8A、S8A-R1；S8B1、S8B2、S8B1-R2；S8B3A-S8B3C；S8B4A-S8B4B；S8B5A-S8B5C；S8B6 及对应聚合项；S8C1A |
| 部分完成 | S5D2 的随机目标和弹射消费已验收，完整动作 transaction/replay 等待 S8 后回验 |
| 待制定 | S8C1B、S8C1C |
| 后续 | S8C1 聚合、S8C、S9-S20 |

最终状态只认总计划 checklist 和已验收 Git 检查点。执行卡或报告中的 `ready_for_review` 不是通过结论。

## 聚合说明文件

以下文件说明较大目标和拆分关系，不是直接执行入口：

- `P9-S8_CONTROL_FLOW_SEQUENCE_CLOSURE.md`
- `P9-S8B_ATOMIC_TASK_GRAPH_RUNTIME.md`
- `P9-S8B3_ABILITY_STANDALONE_MIGRATION.md`
- `P9-S8B4_STATUS_CALLBACK_MIGRATION.md`
- `P9-S8B5_CROSS_ENTRY_INTEGRATION_AUDIT.md`
- `P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md`
- `P9-S8C1_RANDOM_CONFIG_GRAPH_CONTRACT.md`

聚合文件不能覆盖子卡的允许写集合、停止条件或验收状态。

## 开工规则

执行线程只读取：

1. 当前执行卡；
2. 卡内点名的起始符号和正式调用者；
3. 卡内明确列出的来源或前置契约；
4. 发生具体依赖缺口后才扩展的一小段导航。

禁止默认通读其他 P9 卡、历史报告和旧验证器。开工前先核对当前代码事实；若目标、权威、调用面或
风险与卡面不符，提交 `needs_replan`，不能自行扩大或缩小目标。

执行线程只能提交：

- `ready_for_review`：卡面生产完成条件、自审和必要验证均完成；
- `needs_replan`：发现第二权威、额外消费域、写集合或语义偏差；
- `blocked`：外部来源、环境或用户范围裁决阻止继续。

不得勾总计划、提交 Git 或自动进入下一阶段。

## P9 永久约束

- 角色专属差异只能进入内容 IR，不能形成角色名、技能名或固定 ID runtime handler。
- 普通动作、状态 callback、独立 ability 和角色战斗事件复用同一任务图与效果契约。
- 未知来源、缺上下文或未准入分支必须在生产边界 fail-closed，且 state、mutation、event 和 RNG 不变。
- 记忆、欢愉、怪物、关卡或非战斗产品内容只做精确归属，不借 P9 提前实现。
- source gap、lowering gap、admission gap、implementation missing 和 validation gap 不能互相改名。
- fixture 可以证明通用边界，不能证明真实角色或 gameplay 来源 executable。

## P9 验证边界

具体证据由当前卡和工作流按改动面选择。P9 额外遵守：

- source/family 过滤必须在来源读取、投影和 IR 构建前生效；
- 不先构建完整 Canonical IR 再过滤；
- 后序卡不重跑前序主入口，只运行本次 fast、必要 direct 和实际触发的 catalog；
- 不运行 P1-P8 聚合、`validate_v0_209` 或固定历史验证套餐；
- 每个新生产不变量保留一个最小反例，不以扩大验证器替代生产约束；
- 报告只记录实际改动、有效命令、资源异常和遗留 gap，不复述执行卡。

达到卡面资源预算或同一根因两次修复仍不收敛时停止，由规划/验收线程重拆，不通过增加验证模式或
换更强模型掩盖范围问题。
