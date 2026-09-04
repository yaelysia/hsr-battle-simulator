# v8 当前交接

本文只维护当前已验收边界、正在推进的阶段和下一入口。历史过程、阶段数字和修复流水账不在这里
重复；需要时从文档索引和 Git 历史按关键词追溯。

## 当前主线

```text
simulator_v8_clean_core
TurnBasedGameData -> compiler/lowering -> Canonical IR / 数据卡 IR -> Combat Core
```

项目不实现敌方 AI。外部推演器像玩家一样控制敌我双方，内核只负责给出合法动作、目标、时机和
确定性结算。

## 已验收边界

- P1-P7 已建立最小战斗循环、状态、召唤、波次、队列、目标、RNG、内容卡、动态参数、架构边界和
  可信状态提交等通用底座。
- P8 已完成当前来源下的光锥、普通玩家遗器、词条、套装、装备装配、构筑汇合、来源审计与 replay
  收口；`CUSTOM` 遗器模板保留来源但明确排除正式玩家构筑。
- CHAR-M1 已建立记忆角色与忆灵 owned-combatant 构筑边界。
- P9-S0 至 P9-S8B6 已验收。角色能力来源、构筑绑定、动态值、目标、条件、任务图 IR、共享原子执行、
  普通动作、独立能力、状态 callback 和跨入口 continuation 已进入统一生产链。
- P9-S8C1A 已验收：任务图具备加权 choice/selection 的严格 IR、稳定身份、父子 `.OddsList[i]`
  来源关系、数值定义配对、不可变容器和严格 JSON codec。
- P9-S8C1B 已验收：现有正式 `ability_phase_callback` action entry 的 `RandomConfig` 现在由共享 task-graph materializer 从同一 signed `CharacterAbilityRawSnapshot` 读取 `OddsList[i]`，复用既有 numeric lowering，并把 definition/choice 与既有 S8A branch 一一绑定到 `TaskGraphIR.weighted_selections`。真实 Direct 已动态证明单 entry 与 ability catalog 共享同一物化结果。
- P9-S8C1C 已验收：现有 `ability_phase_callback` 与 `status_callback` 对 `RandomConfig` 共用同一 weighted-selection materializer；完整 raw/S8A/source-ledger 来源分母与 level-specific formal-position multiplicity 已通过 STRICT 双向闭合，status 单 entry 与联合目录一致，S8C1B action 回归保持。
- P9-S8C1 聚合已验收：独立 STRICT 审计从实时来源重新得到 direct `RandomConfig` 分母 `24`，raw/S8A/source-ledger exact-equal，`formal_bound/no_formal_producer=14/10`；全部正式 producer/definition-level/task multiplicity 的 expected/actual formal positions 为 `117/117`，公开联合 catalog 的 weighted-selection ordinal/branch/`OddsList[i]`/numeric/source identity 一一闭合。最终执行 head `7a75e80a02f886ab1036cbe041b3b031d7057e82` 的 PR CI run `33857786539` 通过；`full_canonical_ir_build_count=0`，未执行 runtime RNG、mutation/event/settlement/replay。该检查点只完成静态任务图契约，不代表 S8C runtime/RNG 或 S5D2 transaction/replay 已闭合。
- P9-S5D2 的随机目标基础和弹射目标消费已完成，但其完整动作 transaction/replay 正例明确等待 S8
  随机控制流闭合后回验，因此该聚合项仍未勾选。

“底座已验收”不等于全内容完成。P1-P8 的完成结论只适用于各阶段声明的来源与功能范围。

## 当前工作

当前总计划：

```text
simulator_v8_clean_core/P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md
```

当前检查点停在：

```text
P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_AUDIT — accepted
```

当前没有可直接执行的下一张 P9 卡。S8C1 聚合已完成独立验收；S8C 与 S5D2 回验均未启动，本检查点不创建下一阶段执行卡、不创建新 PR，也不自动推进后续施工。

## 仍未完成

- P9-S8C 及后续角色共享控制流、事件、状态、伤害、资源、队列、死亡、击破、形态和独立行动实体。
- P9-S5D2 的完整动作 transaction/replay 回验，仍等待 S8 随机控制流闭合。
- P9 完成后的全角色目录回验，以及记忆、欢愉专属内容增量。
- 全怪物、全召唤内容、全关卡环境和特殊玩法的数据卡扩面。
- 当前阶段已经明确归属的 P3/P4/P5 内容来源缺口。
- 正式 UI、外部推演器和端到端产品流程。

这些缺口不能因为通用底座存在而标记为完成，也不能用 fixture 冒充真实内容可执行。

## 开工入口

新线程只读取与任务直接相关的最小集合：

1. 工作区永久约束：`AGENTS.md`。
2. 当前状态：本文。
3. 当前总计划的阶段依赖与唯一 checklist。
4. `docs/p9_execution_cards/README.md` 和当前唯一执行卡（若已有）。
5. 执行卡点名的生产符号、调用者和来源。

架构修改再读 `ARCHITECTURE_BOUNDARY_CONTRACT.md`、`FORBIDDEN.md`；规划或验收再读
`docs/AGENT_WORKFLOW_AND_VALIDATION.md`。禁止新线程默认通读全部计划、报告和历史验证器。

## 证据与历史

- P8 最终结论：`live_validation_reports/v8_p8_equipment_build_light_cone_relic_final_checkpoint.md`。
- P9-S8C1A ready-for-review 证据：`live_validation_reports/P9-S8C1A_WEIGHTED_SELECTION_IR_ready_for_review.md`；最终通过结论只认总计划 checklist、accepted 执行卡状态和合并后的 Git 检查点。
- P9-S8C1B 执行证据：`live_validation_reports/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_execution_report.md`；其真实 Direct 证明 action-entry 纵切并作为 S8C1C action 回归上游。
- P9-S8C1C 执行证据：`live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md`；其 STRICT Direct/Catalog 证明当前完整 RandomConfig 来源与 formal-position 闭合，不代表 runtime RNG、S8C1/S8C 聚合或 S5D2 已完成。
- P9-S8C1 聚合执行证据：`live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md`；其 STRICT Fast/Direct/Catalog 与 PR #4 最终 CI 证明当前静态 RandomConfig task-graph aggregate contract，不代表 S8C runtime/RNG 或 S5D2 已完成。
- P9 阶段状态只认总计划 checklist 和已验收 Git 检查点；`ready_for_review` 报告不是最终验收。
- 文档归属与归档：`simulator_v8_clean_core/DOCUMENTATION_INDEX.md`。
- 瘦身前交接全文：`simulator_v8_clean_core/docs/archive/CODEX_HANDOFF_PRE_SLIM_2026-07-24.md`。

## 工作边界

- runtime 不读 raw TBGD、TextMap、旧 v7 或旧 model pack。
- 内容差异进入数据卡与机制图，不进入核心特判。
- 缺来源、缺语义或身份冲突必须 blocked 且 state unchanged。
- UI 和推演器不复制规则。
- 验收必须检查生产代码、正式调用链和最小反例，不能只看 `ok=true`。
- 默认运行 fast 和必要 direct；catalog/full 仅由实际改动面触发。
- 执行线程只提交 `ready_for_review`；验收线程负责 checklist 和检查点。