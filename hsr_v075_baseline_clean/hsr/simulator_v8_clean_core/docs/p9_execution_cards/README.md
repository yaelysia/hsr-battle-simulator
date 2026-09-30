# P9 执行卡参考索引

本目录保留原 P9 的机制拆分、来源导航和历史检查点。当前路线以
[P9 总计划第 0 节](../../P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md#0-当前路线机制优先内容逐步扩充)
为准：先完成通用底层，再接入角色、敌人和场地，并按实际需要实现特殊机制。
特殊机制即使需要扩展 L1，也不因此提前成为底层阶段的前置；CLI MVP 用于运行与游戏对照。

当前进度和下一项只看 [CODEX_HANDOFF.md](../../../CODEX_HANDOFF.md)。本索引不另设唯一执行卡，
旧卡的允许写集合、阶段顺序、审批角色和全目录验收不自动成为新任务限制。
工作方式采用 [本地执行与验证约定](../AGENT_WORKFLOW_AND_VALIDATION.md#0-当前本地工作方式)。

## 复用方式

- 先核对当前实现和已完成的本地修改，再按机制读取旧卡的真实来源与调用者导航。
- 复用已完成的来源、构筑、目标、条件、任务图、状态 callback 和 A2 跨入口成果。
- S8C1/S8C2 证明随机图和共享 executor 契约，尚不代表正式 caller/RNG 全链完成；当前路线先补
  该实际断点，但不要求为此重开全部前置阶段或复制旧审计套餐。
- PR #9 是已排除的失败测试片，不读取、恢复、移植或操作；后续在当前主线加本地成果上实施。
- 任务按实际行为划分，必要时跨旧卡修复同一根因；不追角色数量、覆盖率或全目录零缺口。
- 已完成/未完成的历史边界保留在总计划第 12 节，不能把旧卡的 `ready_for_review` 当作当前功能已完成。

## 聚合说明文件

以下文件说明较大目标和拆分关系，不是直接执行入口：

- `P9-S8_CONTROL_FLOW_SEQUENCE_CLOSURE.md`
- `P9-S8B_ATOMIC_TASK_GRAPH_RUNTIME.md`
- `P9-S8B3_ABILITY_STANDALONE_MIGRATION.md`
- `P9-S8B4_STATUS_CALLBACK_MIGRATION.md`
- `P9-S8B5_CROSS_ENTRY_INTEGRATION_AUDIT.md`
- `P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md`
- `P9-S8C1_RANDOM_CONFIG_GRAPH_CONTRACT.md`

这些聚合文件和子卡均只作机制与历史参考，不能覆盖当前路线和用户授权。

## 开工方式

从当前交接与总计划第 0 节确定机制目标，只读对应生产符号、正式调用者和真实来源，
需要时再查旧卡。禁止默认通读全部 P9 卡、历史报告和验证器。

按实际依赖完成同一根因的实现与必要检查，在交接中说明可用行为和剩余边界。
发现规则或范围确实不明时询问用户；普通接线修复不恢复独立规划/验收线程或审批卡。

## P9 永久约束

- 角色专属差异只能进入内容 IR，不能形成角色名、技能名或固定 ID runtime handler。
- 普通动作、状态 callback、独立 ability 和角色战斗事件复用同一任务图与效果契约。
- 未知来源、缺上下文或未准入分支必须在生产边界 fail-closed，且 state、mutation、event 和 RNG 不变。
- 通用机制同时服务角色与怪物；记忆/欢愉专属内容按后续路线增量处理，非战斗产品范围仍排除。
- source gap、lowering gap、admission gap、implementation missing 和 validation gap 不能互相改名。
- fixture 可以证明通用边界，不能证明真实角色或 gameplay 来源 executable。

## 验证边界

依照本地约定，围绕本次实际行为和风险选择必要检查；不强制新增反例、全目录核对或历史套餐。
来源读取与 IR 构建尽量采用已有窄范围入口，不为一次机制修复构建无关的全量目录。
文档只记录有效结果和未完成边界；实现不收敛时重新定位根因，不通过加测试或扩大范围掩盖问题。
