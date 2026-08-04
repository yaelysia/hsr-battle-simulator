# v8 Documentation Index

本索引只负责告诉线程“当前任务该读什么”。它不复制阶段状态、验收历史或执行清单。

## 默认入口

- 当前状态：`../CODEX_HANDOFF.md`
- 项目概览：`README.md`
- 架构边界：`ARCHITECTURE_BOUNDARY_CONTRACT.md`
- 最终目标：`PROJECT_GOALS.md`
- 禁止事项：`FORBIDDEN.md`
- 工作流与验证：`docs/AGENT_WORKFLOW_AND_VALIDATION.md`

新线程先读 `CODEX_HANDOFF.md`，随后只按任务类型增加文档。禁止默认读取下面所有条目。

## 按任务选择

### 实施阶段

只读：

1. 当前阶段执行卡。
2. 执行卡明确列出的直接依赖。
3. 拟改代码和调用链。

P8 执行卡入口：

```text
docs/p8_execution_cards/README.md
```

记忆角色执行卡：

```text
docs/character_execution_cards/
```

全角色机制闭合：

```text
P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md
docs/p9_execution_cards/README.md
docs/character_execution_cards/CHARACTER_ABILITY_SCOPE_CLASSIFICATION.md
docs/character_execution_cards/CHARACTER_CATALOG_READINESS_INVENTORY.md
docs/character_execution_cards/CHARACTER_SHARED_MECHANISM_GAP_PLAN.md
```

P9 总计划保存总目标、严格阶段顺序和唯一 checklist；执行卡索引保存各阶段入口，其中原 S5
按架构边界拆为严格串行的 S5A-S5D。
后三份依次是纳入/排除范围、当前可用程度以及共享机制归并的权威基线。
需要逐族审计时再读 `CHARACTER_ABILITY_SCOPE_LEDGER.md`，普通执行线程不默认读取该附录。

验证治理与状态完整性执行卡：

```text
docs/validation_execution_cards/
```

### 架构和共享内核

必读：

- `ARCHITECTURE_BOUNDARY_CONTRACT.md`
- `FORBIDDEN.md`
- 与修改系统直接相关的现行计划或 checkpoint

不要为了解一个共享符号通读 P1-P8；先用 CodeGraph 查看定义、调用链和影响范围。

### 规划与验收

必读：

- `docs/AGENT_WORKFLOW_AND_VALIDATION.md`
- 当前阶段计划和执行卡
- 当前 `ready_for_review` 报告
- 本次修改 diff 和直接调用链

历史报告只用于追溯，不是自动回归要求。

### 怪物卡

- `MONSTER_CARD_SPEC.md`
- `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
- 对应怪物 checkpoint

### UI

- `simulator_v8_ui/`
- `simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`（存在时）

UI 只负责编排、查询和展示，不定义规则。

## 当前阶段计划

- `P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md`
- `P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md`
- `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
- `P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md`
- `P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md`
- `P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
- `P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`
- `P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`
- `VALIDATION_GOVERNANCE_AND_STATE_INTEGRITY_PLAN.md`

这些计划是按需参考资料，不是新线程必读列表。当前执行状态以 `CODEX_HANDOFF.md` 和对应 checklist 为准。

## 验收报告

报告目录：

```text
../live_validation_reports/
```

使用规则：

- `ready_for_review` 是执行 evidence 索引，不是验收裁决。
- `checkpoint` 表示验收线程形成的阶段结论。
- 查询当前状态先读最新 checkpoint；查询具体机制再读对应专项报告。
- P8 装备体系最终 checkpoint：`../live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。
- 不全量读取报告目录，不用旧报告的 `ok=true` 代替当前源码回归。
- P1 历史位于 `live_validation_reports/archive/phase1/`。

## 历史归档

- P1 过程计划：`docs/archive/phase1/`
- 旧完整入口文档：`docs/archive/*_PRE_SLIM_2026-07-24.md`
- 其他历史材料：`docs/archive/`、`live_validation_reports/archive/`

归档内容保持可搜索，但不进入默认上下文。

## 文档新增规则

- 长期稳定约束放主目录。
- 工作流和按需参考放 `docs/`。
- 单阶段执行目标放对应 execution card 目录。
- 执行 evidence 放 `live_validation_reports/`。
- 历史过程材料放 `docs/archive/` 或 `live_validation_reports/archive/`。
- 同一阶段只能有一套可勾选 checklist。
- 当前状态只维护在 `CODEX_HANDOFF.md`，不要再复制到 `AGENTS.md` 和本索引。

## 验证入口

验证不再从文档索引列出 P1-P8 全量命令。根据 `docs/AGENT_WORKFLOW_AND_VALIDATION.md` 选择：

```text
fast -> direct -> catalog -> full
```

默认只运行 `fast` 和必要的 `direct`。阶段卡必须明确说明更高层验证的触发理由。
