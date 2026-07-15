# v8 Documentation Index

本文档是 v8 当前文档入口索引。它用于降低后续线程的上下文成本，避免从过期阶段报告或旧 v7 文档接错主线。

## 1. 当前主线状态

当前主线：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

最近完成阶段：

```text
P8-S3 light-cone data cards and source linkage accepted
checkpoint: v8_p8_s3_light_cone_data_cards_ready_for_review.md
```

当前规划阶段：

```text
P8 equipment build, light-cone and relic assembly
P8 task plan established
P8-S0 equipment source and mechanism baseline accepted
P8-S1 typed equipment and build architecture accepted
P8-S2 formal character build input and base panel accepted
P8-S3 light-cone data cards and source linkage accepted
next stage: P8-S4 light-cone instance, growth and path activation decision
```

当前验收口径：

- P1 最小完整战斗纵切已通过。
- P2 状态系统底座已通过。
- P3 召唤物 / 忆灵曾按旧 transition 口径通过底座验收；P7 收紧后 servant action graph 已重新归类为内容缺口，spawn、生命周期、状态、目标关系和来源审计底座仍可依赖。
- P4 角色卡 / 怪物卡数据卡扩面底座已通过，但全正例未完成。
- P5 公式 / 动态值 / 参数绑定通用准入底座已通过，但全正例未完成。
- P6 架构边界回正已完成验收；出生模板、计算入口、访问边界和聚合阻断口径均已收口。
- P7-S0 问题基线已完成独立验收；当时 24 项问题以 `confirmed_open` 固化，随后已在 P7-S1 至 P7-S19 中逐项修正并完成最终验收。
- P7-S1 Transition 可信结果契约已完成独立验收；不完整、未知和矛盾结果不能冒充正式后继，父 scheduler transition 会保留 diagnostic child 身份。
- P7-S2 Mutation 前置条件与 reducer 冲突检测已完成独立验收；严格 before/op/after、路径存在性、同路径连续链、结构化冲突、整批回滚、不可变 Mutation JSON 和统一 UnitState codec 均已形成直接证据。
- P7-S3 至 P7-S19 已完成统一验收；最终总账包含 24 项问题证据、18 个阶段证据和一次共享 RuleBook 的 9 项当前源码回归，空检查、缺项、错误类型及错误源码指纹负例均被拒绝。
- P7-DONE 已于 2026-07-13 由验收线程勾选。P7 完成的是内核可信执行与当前已准入战斗语义，不代表 P2/P3/P4/P6 保留内容缺口或全角色 / 全怪物 / 全装备 / 全关卡扩面完成。
- P8-S0 装备来源与机制基线、P8-S1 类型化装备与构筑架构、P8-S2 正式角色构筑输入与基础面板、P8-S3 光锥数据卡与来源关联均已独立验收。当前已具备 source-backed 无装备角色面板和完整已发布光锥定义目录，但尚未创建玩家光锥实例、计算指定等级贡献或执行装备效果。

P6 后的内核深度复审确认：现有 transition / replay / source audit 骨架值得保留，但动作完整性、Mutation 前置校验、动作与目标契约、调度阶段、伤害、护盾、状态概率、RNG、召唤和波次等路径仍有会影响真实战斗结果的问题。P7 用实际代码问题总账和通用不变量逐项回正这些语义，不把旧聚合 `ok=true` 外推为完整正确。

P3/P4/P5 的 `*_all_executable_complete=false` 和 P6 的 `p6_all_mechanisms_reimplemented=false` 是已归因 backlog，不是当前底座失败。

当前推荐下一阶段：

```text
P8-S4 light-cone instance, growth and path activation decision
```

P7-S0 至 P7-S19 已全部验收，P8-S0 至 P8-S3 也已通过独立验收。当前装备 / 构筑主线下一步只执行 P8-S4；不能修改 P7 已完成口径来掩盖保留缺口，也不能把 S3 的光锥定义目录误读为玩家实例、指定等级贡献或装备效果已经完成。

## 2. 下一线程优先入口

新线程默认按以下顺序读：

1. `AGENTS.md`
2. `hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/README.md`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md`
5. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md`
6. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md`
7. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/DOCUMENTATION_INDEX.md`
8. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
9. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`

如果任务涉及具体阶段，再读对应阶段计划和 checkpoint。

## 3. 长期约束文档

这些文档是长期有效约束：

- `ARCHITECTURE_BOUNDARY_CONTRACT.md`
  - 定义 UI / 推演器、内容卡、内核、来源编译层和审计横切层的边界。
- `PROJECT_GOALS.md`
  - 定义最终模拟器目标、transition、snapshot、settlement、replay 目标。
- `FORBIDDEN.md`
  - 定义 runtime 禁止行为、旧系统隔离、来源红线。
- `MONSTER_CARD_SPEC.md`
  - 定义怪物卡和怪物机制接入规范。
- `PHASE1_SUMMARY.md`
  - P1 最小完整战斗纵切总结。

这些文档优先于阶段过程报告。

## 4. 阶段计划文档

当前仍保留在主目录的阶段计划：

- `P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md`
- `P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md`
- `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
- `P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md`
- `P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md`
- `P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
- `P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md`

P1 过程计划已经归档，不作为默认入口：

- `docs/archive/phase1/`

后续新增大型阶段计划必须沿用 P4/P5/P7 结构：

- 只保留一套执行 checklist。
- 每阶段只做一个明确目标。
- 执行线程先提交阶段执行卡。
- 执行线程只提交 `ready_for_review`。
- 验收线程复核后才勾 checklist。
- 聚合阶段最后做，并继承所有分步 gap。

## 5. 验收报告入口

当前阶段 checkpoint：

- `../live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`
- `../live_validation_reports/v8_p2_status_system_complete_checkpoint.md`
- `../live_validation_reports/v8_p3_summon_assistant_servant_complete_checkpoint.md`
- `../live_validation_reports/v8_p4_combatant_data_card_expansion_checkpoint.md`
- `../live_validation_reports/v8_p5_formula_dynamic_param_binding_checkpoint.md`
- `../live_validation_reports/v8_p6_architecture_boundary_refactor_checkpoint.md`
- `../live_validation_reports/v8_p7_s0_kernel_trust_baseline_ready_for_review.md`（S0 执行 evidence；验收结论以 P7 checklist 和检查点提交为准）
- `../live_validation_reports/v8_p7_s1_transition_trust_contract_ready_for_review.md`（S1 执行 evidence；验收结论以 P7 checklist 和检查点提交为准）
- `../live_validation_reports/v8_p7_s2_mutation_reducer_contract_ready_for_review.md`（S2 执行 evidence；S2 已另行验收）
- `../live_validation_reports/v8_p7_s3_selected_graph_atomic_commit_ready_for_review.md` 至 `v8_p7_s18_compact_semantic_state_ready_for_review.md`（S3-S18 专项执行 evidence）
- `../live_validation_reports/v8_p7_s19_kernel_invariant_aggregate_ready_for_review.md`（S19 执行 evidence；最终裁决见检查点）
- `../live_validation_reports/v8_p7_kernel_trust_and_combat_semantics_final_checkpoint.md`（P7 统一验收最终检查点）

阶段内 `ready_for_review` 报告是 evidence 索引，不是验收结论本身。最终以对应 `checkpoint` 和验收线程结论为准。

## 6. 历史报告管理

`live_validation_reports/` 保留大量 v8 早期 checkpoint 和阶段内 evidence。默认不要全量阅读。

读取规则：

- 查当前阶段状态，先读最新阶段 checkpoint。
- 查具体机制历史，读对应机制 checkpoint。
- 查 P1 过程，读 `archive/phase1/`。
- 查 P2/P3/P4/P5 分阶段证据，读对应 `v8_p*_s*_*` 报告。
- 不要把旧 `ready_for_review` 报告当作最新验收结论。
- 不要用旧验证的过时 blocked 口径否定当前新版本；先检查该旧验证是否应迁移。

## 7. UI 文档

UI 文档和原型属于外部操作层：

- `simulator_v8_ui/`
- `simulator_v8_ui/UI_V2_WORKBENCH_TASK_PLAN.md`（若存在）

UI 只做 scenario 编排、查询、展示、审计和倒查底层缺口。UI mock / view model 不能定义 core 规则，不能写入正式 route / scenario 作为验收输入。

## 8. 当前推荐验证入口

在 `hsr_v075_baseline_clean/hsr` 下运行，按触达范围选择，不要无脑全量：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_architecture_boundary_refactor --output-dir /tmp/hsr_v8_p6_current
git diff --check
```

重验证必须串行运行，输出到 `/tmp`，默认不写完整 Canonical IR、完整 RuleBook 或全量 transition dump。

## 9. 文档新增规则

新增文档前先判断它属于哪一类：

- 长期约束：放在 `simulator_v8_clean_core/` 主目录。
- 阶段计划：放在 `simulator_v8_clean_core/` 主目录，命名 `P*_..._TASK_PLAN.md`。
- 阶段 evidence：放在 `live_validation_reports/`，命名 `v8_p*_s*_*_ready_for_review.md`。
- 阶段验收结论：放在 `live_validation_reports/`，命名 `v8_p*_*_checkpoint.md`。
- 归档历史：放在 `docs/archive/` 或 `live_validation_reports/archive/`。

不要为同一阶段写多套 checklist。背景、设计原则、风险矩阵只能作为参考资料；需要打勾的执行项必须集中到阶段计划对应小节。
