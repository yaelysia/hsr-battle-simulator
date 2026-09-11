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
- P9-S8C2 已验收：共享 `TaskGraphExecutor` 现在具备 `RandomConfig` / `weighted_single` 专用的类型化 weighted-selection hook/result contract，由 executor 反查 accepted IR 校验 selection/choice/ordinal/branch identity，只执行被选 branch，并将恰一个合法 `RNGEvent` 纳入既有 task-graph result、duplicate identity 与原子 rollback 空间。执行 head `5e14526f4046626528aee4a594a8e7eb8a9ef14a` 的 PR #5 CI run `34080289369` 已通过独立核验。该检查点不计算动态权重、不接真实 ability/status RNG ledger caller，也不代表 projectile、barrier、parallel、sequence-select 或整个 S8C 已闭合。
- Route A 前置 A1 `P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY` 已通过独立 REVIEW：正式 action admission 现在从与 `AbilityTaskSystem` 一致的 `action_root` 图闭包做静态支持投影，只通过真实 `TriggerAbility` 链接纳入 `nested_only`，排除闭包外 bound phase/task，同时保留 reachable blocker、process-only 区分、external-legacy 与上游准入门。REVIEW 返修补齐了跨图路径敏感 active-cycle fail-closed；实现 head `84ee94b4d1bf25221d783f8a84d7b79f8e46f896` 的 hosted CI run `34122026242` 已通过。该检查点不包含 A2，也不代表 PR #9 caller/RNG-ledger 已完成。
- Route A 的 A2 独立 L0 前置 `P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION` 已通过独立 REVIEW：`tbgd/lowering.py` 在既有 status event producer 与 typed `TriggerAbility` link 事实形成后增加单一 post-link admission finalization，只移除来源可证明为过早冻结的精确 `status_callback_event_not_admitted:<event>` blocker。STRICT Direct 在 lowering 之前从 formal raw/source graph 动态枚举 action-window `TriggerAbility` occurrence，并与 pre-finalizer IR、typed target/final graph、production audit 双向 exact 对账；当前来源只有 1 条真实正例发生 blocked→executable transition，其余同 action-window event 独立 blocker 均保持。真实 queue resolution 驱动 invocation role，A1 admission regression 保持；生产实现 commit `a73576c6d5d751f6c5d14713e5ed49883fc82b2f`，PR #12 最终执行证据 run `34193467352` 全绿且 workflow 权限为只读。该检查点只闭合 A2 的 merged-master L0 admission prerequisite，不代表 PR #11 的 action-window status→nested formal ability runtime transport/routing 已完成，也不替代其真实 `CombatExecutor.execute(ActionCommand)` Direct。
- Route A 的 A2-P1 前置 `P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY` 已通过独立 REVIEW：formal lowering 现在只在同一 `process_only` task 的 own `EffectIR` 唯一且旧 source 与 canonicalization 前 task source exact-equal 时同步 canonical `IRSource`；既有 client-only `TriggerAbility` post-conversion 路径也只在唯一 exact pair 下同步，ambiguity/source disagreement 均保持 no-rewrite/fail-closed。STRICT Direct 从 pinned TBGD/current formal lowering 动态重建完整分母，`5073` 条 baseline mismatch 全部由 topology-evidence normalization 唯一解释并在当前生产 lowering 中降为 `0`，`8120` 条 non-process-only pair 与独立来源保持不变；same-owner 正式 action 只移除 `process_only_task_effect_source_mismatch`，`ability_task_graph_nested_identity_mismatch`、S8C/S11 等后续 blocker 继续 fail-closed。生产修复 commit `d163e0d3225a8e31bfd4af602541049332614e59`；REVIEW 返修后 final EXEC head `4cca72510761331c9fb721999d436bf6f0861e66` 的 P1 run `34330329036` 与 P0 regression `34330328967` 全绿，workflow 权限保持只读。该检查点只闭合 formal process-only task/effect source identity，不代表后续 same-owner formal blocker、PR #11 A2 runtime transport 或 PR #9 caller/RNG-ledger 已完成。
- Route A 的 A2-P2 前置 `P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY` 已通过独立 REVIEW：A1 formal action admission 现在只让 canonical `ability_call` 或 non-process-only gameplay `TriggerAbility` 进入 nested-edge identity 路径，合法 process-only `TriggerAbility` materialized `leaf` 在既有 process-only source/effect contract 通过后不再被 opcode-only 误判为 nested gameplay edge；process-only `ability_call`、non-process-only `TriggerAbility` leaf、普通 task `ability_call` 以及 reference/link/nested graph mismatch 仍 fail-closed。STRICT Direct 从 pinned TBGD 与 merged production 动态选择 same-owner ordinary action，只移除该 process-only leaf 的 `ability_task_graph_nested_identity_mismatch` provenance，root/reachable/excluded identity 与 hit-random/audit/unsupported/damage-heal-shield 等其它 blocker 保持，ActionContract 仍按后续域 fail-closed，runtime graph/mutation/RNG 均为 `0`。final EXEC head `a5ad6031bbe02f0e7e90d7c227124814d4e662d1` 的 P2 run `34569640362` 全绿，workflow 权限保持只读；PR #14 已以 squash merge `d1c28c0c0e10ed8b268739b71bab1784574a8d93` 合入。该检查点只闭合 A1 对 process-only TriggerAbility leaf 的 admission identity，不代表后续 same-owner formal blocker、PR #11 A2 runtime transport 或 PR #9 caller/RNG-ledger 已完成。
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
P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY — accepted (Route A predecessor)
```

下一步必须由 PLAN 从包含 A2-P2 的最新 merged master 重新运行 same-owner outer-action formal blocker attribution。若仍暴露独立、source-backed、早于 A2 transport 的下一单一 authority blocker，只为该最早 blocker新建一张 Route-A predecessor；不得把 S8C/S11 或多个责任域打包。若该前置链已经清空，则恢复既有 PR #11 / A2：保留其现有实现，更新到新的 merged master，并原样重跑其既有 Fast 与真实 `CombatExecutor.execute(ActionCommand)` Direct。PR #9 继续保持暂停，只有 PR #11 的 A2 独立验收并合并后，才允许在原 PR 上恢复 RandomConfig caller/RNG-ledger 工作。

## 仍未完成

- Route A 前置 A2 runtime：action-window status callback -> nested formal ability continuation/hook transport/routing；其 A2-P0、A2-P1 与 A2-P2 前置已验收，但 P2 merge 后仍需由 PLAN 重新归因剩余 same-owner outer-action formal blockers，再决定下一 predecessor 或恢复 PR #11。
- P9-S8C 剩余真实 RandomConfig caller/RNG-ledger integration、projectile、多 hit identity、barrier、parallel、sequence-select/timeline-wait，以及后续角色共享控制流、事件、状态、伤害、资源、队列、死亡、击破、形态和独立行动实体。
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
- P9-S8C2 执行证据：PR #5 正式 `[HANDOFF:REVIEW]` 评论 `5564689207`、执行 head `5e14526f4046626528aee4a594a8e7eb8a9ef14a` 与 CI run `34080289369`；独立 REVIEW 已核对生产 diff、聚焦测试和 Actions 日志。该证据只接受共享 weighted-selection executor contract，不接受真实 caller 或 S8C 聚合。
- Route A A1 执行与 REVIEW 证据：`live_validation_reports/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY_execution_report.md`、PR #10 `[RETURN_FOR_FIX]` 评论 `5570308533`、修复后实现 head `84ee94b4d1bf25221d783f8a84d7b79f8e46f896` 与 CI run `34122026242`。该证据只接受 formal action graph admission authority；A2 与 PR #9 caller/RNG-ledger 仍未验收。
- Route A A2-P0 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md`、PR #12 REVIEW 返修评论 `5578826676` / `5579864543`、生产实现 commit `a73576c6d5d751f6c5d14713e5ed49883fc82b2f` 与最终执行 CI run `34193467352`。该证据只接受 merged-master L0 action-window status callback/task admission finalization prerequisite；PR #11 的 A2 runtime transport/routing 与真实 `CombatExecutor.execute(ActionCommand)` Direct 仍未验收，PR #9 caller/RNG-ledger 继续暂停。
- Route A A2-P1 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md`、PR #13 REVIEW 返修评论 `5597805187`、生产修复 commit `d163e0d3225a8e31bfd4af602541049332614e59`、final EXEC head `4cca72510761331c9fb721999d436bf6f0861e66` 与 P1 CI run `34330329036`。该证据只接受 formal process-only task/own-effect canonical source identity closure；后续 same-owner formal blockers、PR #11 runtime transport 与 PR #9 caller/RNG-ledger 仍未验收。
- Route A A2-P2 执行与 REVIEW 证据：`live_validation_reports/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY_execution_report.md`、PR #14 final EXEC head `a5ad6031bbe02f0e7e90d7c227124814d4e662d1`、P2 CI run `34569640362` 与 squash merge `d1c28c0c0e10ed8b268739b71bab1784574a8d93`。该证据只接受 process-only `TriggerAbility` canonical leaf 的 A1 admission identity closure；后续 same-owner formal blockers、PR #11 runtime transport 与 PR #9 caller/RNG-ledger 仍未验收。
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
