# v8 工程交接手册

## 0. 一句话状态

当前主线是 `simulator_v8_clean_core`。P1 最终收口、P2 状态系统底座、P4 角色卡 / 怪物卡数据卡扩面底座、P5 公式 / 动态值 / 参数绑定通用准入底座、P6 架构边界回正均有既有闭环验收；P3 的历史检查点曾按旧 transition 口径验收，但 P7 原子提交收紧后重新暴露 servant action graph 的真实 `implementation_missing`，因此当前不能继续称为“原样继承的 P3 底座闭环”。P6 聚合入口 `validate_p6_architecture_boundary_refactor` 的历史输出为 `ok=true`、`stages=4/4`、`ready_for_review=true`、`p6_all_mechanisms_reimplemented=false`；S0 当时 `violation_row_count=0`，P6 自有越界显式延期白名单为空。P6 是边界回正，不是全机制复刻完成。

P7 内核可信执行与战斗语义回正已于 2026-07-13 完成统一验收。计划 checklist 的 S0-S19 和 P7-DONE 已全部勾选；P7-I01 至 P7-I24 均有当前代码、结构化运行谓词和负例证据。最终验收复跑包含 S1-S18 的 18 份结构化摘要、一次共享 RuleBook 的 9 项当前源码回归，以及空检查、缺项、错误类型和错误源码指纹拒绝负例；最终检查点见 `live_validation_reports/v8_p7_kernel_trust_and_combat_semantics_final_checkpoint.md`。

P7 当前通用能力包括 selected execution graph 原子提交、规则/审计分离、typed expression、动作 ownership/window、选择目标/打击集合、query-submit、显式阶段机、timeline/control、queue 前进、damage/toughness pipeline、shield/HP routing、状态准入、RNG identity/replay、战中召唤、波次事件和 compact semantic state。这些能力已按 P7 当前准入范围验收，不等于全部内容卡和关卡机制已经复刻。

当前已建立 P8 光锥、遗器与角色构筑装配计划，P8-S0 至 P8-S3 已通过独立验收，下一步只执行 P8-S4 光锥实例、成长与命途激活决策。P8 的架构方向是：角色卡、光锥卡、遗器卡作为并列内容来源，玩家构筑引用具体实例，L2 构筑装配器生成静态属性贡献、已启用机制和来源账本，runtime 只消费装配结果。S1 已退役 P4 的字符串式装备边界并建立类型化结构；S2 已接通角色晋阶成长、能量上限、行迹 / 星魂子来源、统一贡献账本和正式 scenario 准入；S3 已将当前已发布光锥完整投影为 source-backed 类型化定义目录并接入 Canonical IR / RuleBook。当前仍未创建玩家光锥实例、计算指定等级贡献、lower 遗器或执行装备效果。

S3-S9 首轮统一验收中暴露的 callback 顺序、来源字段参与行为、动作授权、未知动作和非法阶段等问题均已修正并通过后续验收。S4 AST 门禁会扫描 `core/rules/systems` 全部 runtime 文件；S16/S17 已共享真实 lowering 复跑，servant policy 与 wave definition/entry 的审计字段裁剪不改变行为。

P1-P6 更新口径回归保留真实内容缺口：P1 的 counter/servant action graph、P2 的 action-delay callback graph、P3 的 servant action graph 与 admission/source gap、P4-S3 的 action formula runtime graph、P6-S1 的上游动作图都没有被伪装成 executable。P2 当前分类为 `retained_action_delay_content_gap`；P3 当前分类为 `reopened_servant_action_content_gap`，不再声称历史闭环原样继承。按用户资源要求，P4-P6 使用直接触达验证与既有 checkpoint 组合，没有重复运行完整聚合；统一验收线程可按风险决定是否补跑。

## 1. 路径与事实来源

项目路径：

```text
/home/zhangjinhao/code/hsr
```

主线目录：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

本地 UI 测试台：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_ui/
```

数据库来源：

```text
turnbasedgamedata-main/
```

事实来源链路固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR -> Combat Core
```

旧 v7：

```text
hsr_v075_baseline_clean/hsr/simulator_v7_7/
```

旧 v7 只能作为行为参考和数值对照，不能作为 v8 runtime 依赖。旧 `model_pack_v3_0` 也不能作为 v8 规则事实来源。

## 2. 下一线程必读

按这个顺序读，不要一上来扫全项目：

1. `AGENTS.md`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/README.md`
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ARCHITECTURE_BOUNDARY_CONTRACT.md`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/DOCUMENTATION_INDEX.md`
5. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md`
6. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md`
7. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/MONSTER_CARD_SPEC.md`
8. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PHASE1_SUMMARY.md`
9. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P2_STATUS_SYSTEM_COMPLETE_TASK_PLAN.md`
10. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P3_SUMMON_ASSISTANT_SERVANT_COMPLETE_TASK_PLAN.md`
11. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md`
12. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md`
13. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P6_ARCHITECTURE_BOUNDARY_REFACTOR_TASK_PLAN.md`
14. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P7_KERNEL_TRUST_AND_COMBAT_SEMANTICS_REPAIR_TASK_PLAN.md`
15. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p6_architecture_boundary_refactor_checkpoint.md`
16. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p5_formula_dynamic_param_binding_checkpoint.md`
17. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p4_combatant_data_card_expansion_checkpoint.md`
18. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p3_summon_assistant_servant_complete_checkpoint.md`
19. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p2_status_system_complete_checkpoint.md`
20. `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`
21. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_status_target_event_database_audit_checkpoint_v0_287.md`
22. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_ir_checkpoint_v0_288.md`
23. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_sequence_filter_retarget_checkpoint_v0_289.md`

P1 的详细执行计划和过程报告已经归档，默认不要作为下一阶段入口：

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/archive/phase1/`
- `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/`

需要追怪物历史时再读：

- `live_validation_reports/v8_monster_card_admission_checkpoint_v0_277.md`
- `live_validation_reports/v8_monster_executable_slice_checkpoint_v0_280.md`
- `live_validation_reports/v8_monster_status_listener_counter_checkpoint_v0_282.md`
- `live_validation_reports/v8_monster_action_candidate_checkpoint_v0_283.md`
- `live_validation_reports/v8_monster_skill_attached_status_checkpoint_v0_284.md`
- `live_validation_reports/v8_status_event_family_checkpoint_v0_285.md`
- `live_validation_reports/v8_mutation_backed_event_sources_checkpoint_v0_286.md`

## 3. 必须记住的硬约束

- runtime 只能读取 Canonical IR / 数据卡 IR。
- runtime 禁止读取 raw TBGD、TextMap、技能文本、旧 v7、旧 model pack。
- TBGD raw schema 只能在 compiler/lowering/discovery/审计工具层读取。
- UI、TextMap 名称、中文名、英文名、技能说明、游戏观测值只能用于展示或验证，不能作为规则来源。
- 不允许按角色名、怪物名、技能名、固定 action id、固定 MonsterID、固定文件名、固定 hash、观测数值驱动 runtime。
- 角色、怪物、光锥、遗器、关卡机制不能写进核心系统特判；专属内容必须进入数据卡机制槽位，再接通用系统。
- 缺来源、缺条件、缺目标、缺公式、缺事件 payload、缺队列优先级时必须 blocked/process-only，并保持 state unchanged。
- `audit_only`、`discovered_only`、`blocked`、placeholder 不得产生 mutation。
- 每个新增 mutation 类机制必须有 source audit 正例和 state unchanged 负例。
- settlement 不能从日志事后反推，必须由执行路径原生生成。
- `engine_convention` 必须显式标注，不能伪装成 TBGD 来源。
- 验证主路径必须按结构化谓词选择，不靠固定角色、怪物、技能、文件或观测答案。

## 4. 当前内核已做到什么

基础层：

- Canonical IR、RuleBook、coverage/static checks。
- `BattleTransition`、snapshot、Mutation replay、settlement traceability、source audit。
- action definition、ability binding、ability phase/task、effect、status callback、event dispatch。
- resource、timeline scheduler、queue/window、extra action 语义。

伤害与资源：

- direct、DoT、hp loss、break、break DoT、super-break。
- target group、bounce、多段、damage source frame、击杀归因。
- HP、护盾、能量、战技点、韧性等 mutation-backed 事件源。

状态与事件：

- 普通状态生命周期，buff/debuff 共用 unit-attached status lifecycle。
- dynamic values、StatusInstance dynamic values、DynamicValueStore。
- 状态监听事件族矩阵 `StatusEventFamilyIR`。
- runtime 只执行已有真实事件源、payload、条件、目标、task 全部 admission 的 listener。
- P2 状态系统聚合验收已完成：全量状态来源矩阵 10 个 family 和 6 个来源域均已分类，family/domain 层具备可执行正例，implementation/lowering/admission/validation gap 为 0。
- 个体来源层仍存在被明确阻断的状态来源；这些不是未完成 gap，而是缺事件 payload、缺条件、缺目标、缺公式、unsupported task、缺真实事件源等边界项，已验证为 process-only / state unchanged。
- 状态系统正例覆盖施加、移除、驱散、生命周期、概率/抵抗/免疫、控制行动门、数值绑定、DoT/状态伤害、callback queue/action delay/dynamic value。
- P2 复核已补上 blocked 状态事件源的 queue 下游 IR 一致性检查：被事件源阻断的 queue intent 不会留下 executable queue resolution/window/lifecycle/extra-action。
- 银鬃尉官基础反击纵切已打通：技能挂监听状态、受击触发、条件判断、插入反击、执行反击。
- P1 最终 counter 验收已不依赖固定角色/怪物名选择：P1-5 按 `OnAfterBeingAttacked` / `TurnInsertAbility` / attacker target alias 的结构化谓词选出真实来源，入列、drain、伤害/效果、replay、source audit、负例均通过。

角色：

- 角色数据卡边界。
- 加强版希儿示例卡。
- 行迹/星魂通用开关、等级提升、监听接口。

怪物：

- `MonsterDataCardIR` 与怪物卡规范。
- 普通怪物技能与 ILBattle 怪物技能分命名空间：
  - `monster_skill:<SkillID>`
  - `ilbattle_monster_skill:<ID>`
- 普通怪物技能可执行纵切：ability binding、公式绑定、伤害、削韧。
- 怪物固定序列行动候选：scheduler 轮到敌方时产出候选，但不自动选目标。
- 怪物技能 `AddModifier` 附带状态纵切。

目标表达式：

- `TargetExpressionIR`。
- 已支持：简单别名、明确群体、`SkillTargetEntityList`、`ParamEntityList`、`TeamFormation`、`TargetSequence`、`TargetConcat`、确定性 `TargetFilter`、确定性 `Retarget`。
- `Retarget` 当前只影响本次 effect/callback 的目标解析，不改写整次 action 的主目标。

UI：

- `simulator_v8_ui/` 是零新依赖本地 Web UI。
- 它只做 scenario 编排、战场式查看、事件回放、审计详情、观测对照。
- UI 不计算伤害、不补规则、不绕过 blocked、不进入 runtime 规则系统。

P1-9 聚合验收：

- 新增 `tools/validate_p1_9_phase1_aggregate.py`，默认只做一次 TBGD lowering / RuleBook 构建，不用 subprocess 串联旧验证。
- P1-7 验证脚本已统一为 `run_validation(package_root, tbgd_root, output_dir)`，CLI 输出保持兼容。
- P1-9 聚合 scenario 覆盖 two-wave setup、source-backed initial status、source-backed summoned monster、source-backed servant、explicit timeline、scenario RNG ledger、objective metadata 和至少一个 route transition。
- P1-9 route transition 当前是 route contract 样本；若无 mutation，会在 samples 中标为 `route_contract_only_no_mutation`，不作为 core source audit 正例。
- core snapshot replay / source audit 正例使用 source-backed direct status transition，要求 `mutation_count>0`、`checked_mutations>0`、`checked_records>0`。
- executable 矩阵项只有 `replay_ok=true` 且 `source_audit_ok=true` 才能随聚合 `ok=true` 通过；status setup 的 source trace 统计会识别嵌套 lifecycle/status instance source trace。
- 最近聚合输出在 `/tmp/hsr_v8_p1_9_counter_final/`，关键文件包括 `validation_summary_p1_9_phase1_aggregate.json`、`phase1_system_matrix_p1_9.json`、`phase1_source_gap_matrix_p1_9.json`、`phase1_transition_audit_samples_p1_9.json`。
- P1-9 summary 必须继续区分 `executable`、`boundary_only`、`source_absent_not_required`、`implementation_missing`。P1 最终收口后 `phase1_minimum_battle_slice=true` 且 `phase1_minimum_battle_slice_blocked_by=[]`。

后续已修正 P1-6 目标系统误缺口：`TargetAliasConfig` / `TargetOperationConfig` 现在会 lower 成带真实来源的 `TargetExpressionIR`，`formation sort`、`toughness sort`、`owner fetch` 均有 executable 正例；`ModifierOwnerEntity` 缺 owner 时不再 fallback 到 caster。

后续已修正 servant/忆灵与 P1-8 setup 缺口：`AvatarServantConfig` / `AvatarServantSkillConfig` lowering 到 `ServantDefinitionIR`，runtime 支持 servant spawn/remove、target registry、action availability 和 initial setup；flag-only servant 负例不会被解析为真实目标。

P3 召唤物 / 忆灵聚合口径更正：

- 新增 `tools/validate_p3_summon_assistant_servant_complete.py`，默认只做一次 TBGD lowering / RuleBook 构建，不串联 subprocess，不写完整 Canonical IR 或全量 transition dump。
- 聚合现在能诚实继承分步矩阵缺口，并把 source/mechanism 宽域正例拆成 executable slice 与 gap 子行；AssistantAvatar 另记为 scope exclusion。P7 收紧后，servant 初始 setup、生命周期、target registry 和来源审计仍是可依赖底座，但 servant action graph 不再以半执行结果冒充可信后继。
- 下列 P3-S12 数值是历史检查点，不再代表当前工作树：
  - `ok=true`
  - `validation_gate_ok=true`
  - `p3_summon_foundation_closed=true`
  - `p3_summon_phase_complete=true`
  - `p3_summon_substrate_complete=true`
  - `p3_summon_all_executable_complete=false`
  - `p3_summon_sources_classified=true`
  - `p3_summon_admission_gap_count=2123`
  - `p3_summon_source_gap_blocked_count=27`
  - `p3_summon_scope_exclusion_count=1`
  - `p3_summon_implementation_missing_count=0`
  - `p3_summon_lowering_gap_count=0`
  - `p3_summon_validation_gap_count=0`
  - `p3_summon_unclassified_count=0`
- source matrix：13 rows，`executable=6`、`boundary_only=2`、`source_absent_not_required=2`、`admission_gap=2`、`source_gap_blocked=1`，`gap_count=2150`。
- mechanism matrix：19 rows，`executable=11`、`boundary_only=4`、`source_absent_not_required=1`、`admission_gap=2`、`source_gap_blocked=1`，`gap_count=2150`。
- inherited gap matrix：3 rows，`gap_count=2150`，其中 `admission_gap=2123`、`source_gap_blocked=27`。
- allowed gap evidence matrix：3 rows，`allowed_gap_count=2150`、`disallowed_gap_count=0`、`all_evidence_ok=true`。这是历史验收证据；当前 P7 回归必须另外输出 `p3_summon_foundation_closed=false`、`p3_summon_implementation_missing_count>0` 和 `validation_gate_ok_phase_incomplete_with_disallowed_gaps`，直到 servant action graph 被完整实现并重新验收。
- 该重新打开项归类为“P7 发现的既有内容缺口”，不是 P7 内核不变量修复必须顺带补齐的全 servant 技能扩面。P7 总账可以把它作为明确保留缺口，但不能再输出 `all_p1_p6_regressions_ok=true` 或声称 P3 原样继承。
- scope exclusion matrix：1 row，AssistantAvatar / `TurnInsertAssistantAbility` `out_of_scope`，raw=5、IR=5、RuleBook visible=5、`p3_gap_count=0`。
- 正例样本 8 条、blocked / state unchanged 样本 7 条、source audit 样本 5 条、replay 样本 8 条均通过。
- 当前 P3 可依赖能力：
  - summoned monster source-backed spawn / runtime registry / fixed-sequence action availability / target relation / replay / source audit。
  - `SummonUnitData` / `ConfigSummonUnit` catalog 和非 battle 来源保持 boundary，不会自动 spawn。
  - servant definition、owner/stat/lifecycle、spawn/remove、action query/admission 边界、status holder、BattleSetup initial setup 和 scenario route；完整 servant action graph 当前保持 `implementation_missing`，不可提交可信后继。
  - AssistantAvatar raw / IR / RuleBook / queue window 可审计，但已移出 P3 summon/servant acceptance；后续单独处理，不能作为 P3 admission gap。
  - summon / servant target relation、remove / owner cleanup / wave policy、status/resource/damage boundary 与击杀归因 source frame。
  - `FriendServantSelect` / AssistantAvatar target boundary 当前 `out_of_scope`；P3-S8 summon/servant target relation 当前 `executable=7`；S0 lifecycle `OnEnterBattle` admission gap 已清零。

P4 角色卡 / 怪物卡数据卡扩面 checkpoint：

- 新增聚合入口 `tools/validate_p4_combatant_data_card_expansion.py`，默认只构建一次 TBGD lowering / RuleBook，在内存中重建 S0-S11 子矩阵和 P3 backlog 视图；不串联 subprocess，不写完整 Canonical IR 或全量 transition dump。
- P4-S12 输出目录：`/tmp/hsr_v8_p4_combatant_data_card_expansion/`，关键文件为 `validation_summary_p4_combatant_data_card_expansion.json` 和 `p4_combatant_data_card_expansion_matrix.json`。
- 最新 summary：
  - `ok=true`
  - `validation_gate_ok=true`
  - `p4_combatant_data_card_phase_complete=true`
  - `p4_combatant_data_card_substrate_complete=true`
  - `p4_all_executable_complete=false`
  - `p4_sources_classified=true`
  - `p4_admission_gap_count=1333000`
  - `p4_source_gap_blocked_count=55`
  - `p4_implementation_missing_count=0`
  - `p4_lowering_gap_count=0`
  - `p4_validation_gap_count=0`
  - `p4_unclassified_count=0`
  - `allowed_gap_evidence_summary.all_evidence_ok=true`
  - `allowed_gap_evidence_summary.disallowed_gap_count=0`
- P4 final matrix 继承分步 gap，不允许用 source/mechanism 宽域正例覆盖内部子项 gap。当前保留 gap 均为 allowed `admission_gap` / `source_gap_blocked`；不是 executable。
- P4 source matrix 当前 58 rows：`admission_gap=37`、`boundary_only=4`、`executable=10`、`out_of_scope=7`，`unclassified=0`。
- P4 action availability matrix 当前 7 rows：`boundary_only=2`、`executable=4`、`source_absent_not_required=1`；executable choice 均带 action definition 和 actor data card source trace。
- P4 allowed gap evidence matrix 当前 96 rows，`allowed_gap_count=1333056`、`disallowed_gap_count=0`、`all_evidence_ok=true`。
- P4 scope exclusion matrix 当前 9 rows，包含 BattleTargetConfig stage objective、LocalPlayer maze/local-player config、ILBattle special action、AssistantAvatar 等非当前 P4 战斗数据卡 runtime 范围。
- S12 期间修正了 S0 早期误分类：`BattleTargetConfig` 是 stage/environment objective，不是 action target expression；`ConfigCharacter/LocalPlayer` 是 maze/local-player layer，不是战斗角色卡 config；`ILBattleMonsterSkill:ParamList` 没有当前怪物卡 owner，不能合成无 owner 的 `SkillFormulaBindingIR`。
- S12 期间修正了 S2 继承记录口径：`s1_monster_card_action_set_link_gap_inherited` 是 boundary record，不是 executable action choice 样本。
- P4 回归验证已串行通过：P4 聚合、`compileall`、P1-9 聚合、P2 聚合、P3 聚合、`git diff --check`。

## 5. 当前明确没做到什么

P1 minimum 已完成，但完整复刻仍远未完成：

- P1-4：deterministic dispel、refresh、stack、duration、expire、DoT、chance/resist/immunity 等已有专项正例；`DispelStatus(Order=Random)` 当前是 `source_absent_not_required`，不再作为第一阶段 blocker；`stack + duration refresh` 当前没有组合来源正例，禁止 synthetic positive case。
- P1-5 / P3-S7：counter 已有 P1-FINAL 端到端正例；follow-up 当前未发现第一阶段可执行来源，不阻塞 P1；AssistantAvatar queue/window 可审计，但已移出 P3 summon/servant acceptance，后续单独处理。
- P1-6：formation sort、toughness sort、owner fetch、servant target 已修正为 executable；更完整的特殊玩法目标、复杂 fetch/sort、召唤物/servant 扩展语义仍在后续阶段。
- P1-7：`random_source_paths` 已拆分口径；random dispel 当前是 `source_absent_not_required`，control resist 是 control admission/formula 缺口。
- P1-8：servant/忆灵 initial setup 已有真实来源正例；battle_unit_summon / `SummonUnitData` catalog 不是自动 battle spawn trigger，当前是 `boundary_only`，已验证 blocked/no mutation。

最新缺口归因报告：

- `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/v8_p1_gap_attribution_audit_checkpoint.md`

状态系统 P2 底座已完成，但不要把它误读成完整游戏复刻：

- 当前数据库内状态来源已经全量分类；blocked 项都有负例验证，不会假执行。
- 后续若要把 boundary/process-only 项扩成全正例，必须先证明 raw TBGD / lowering / RuleBook / runtime admission 具备真实来源链路。
- 特殊模式、新事件源、新 target/opcode、新 wave/custom event、未来数据库新增机制仍按 P4+ 单独扩面。

目标系统还没完整：

- 更完整的 `TargetSort*`。
- 更完整的 `TargetFetch*`。
- 随机目标扩展。
- 相邻目标。
- 唯一实体查询。
- 更复杂的召唤物/servant 目标扩展。
- 特殊玩法目标。

角色与装备还没完整：

- 完整角色面板装配。
- 全角色行迹。
- 光锥。
- 内圈/外圈遗器及套装效果。
- 上述装备与构筑缺口已经由 `P8_EQUIPMENT_BUILD_LIGHT_CONE_RELIC_TASK_PLAN.md` 拆为 S0-S21；S20 以希儿、《于夜色中》、四件“繁星璀璨的天才”和两件“繁星竞技场”验证完整正式构筑纵切，S21 才做全量聚合。未经逐阶段验收不能提前宣称底座或全量内容完成。

怪物还没完整：

- 全怪物技能和全怪物被动 admission。
- 复杂 AIPath。
- 阶段切换。
- 召唤。
- 波次。
- 关卡倍率。

其他大块：

- assistant executable actor/stats/action graph、servant HP damage formula、更多 summon/servant 特殊机制。
- 特殊战斗模式。
- 环境、关卡机制。
- `OnCustomEvent`、`OnWaveMonster` 等需要真实事件源或波次系统的 callback。

## 6. v0_289 的关键事实

`validate_v0_289` 当前构建结果：

```text
target_expression_count=243671
executable=198012
blocked=45659
```

新增可执行 composite 统计：

```text
TargetSequence=128
Retarget=823
TargetAlias=197061
```

正例覆盖：

- `SkillTargetEntityList` 从当前 action target resolution 解析目标列表。
- `ParamEntityList` 从事件 payload 的参数实体列表解析目标列表。
- `TeamFormation` 解析为施放者同阵营存活单位，按稳定顺序返回。
- `TargetSequence` resolver 正例通过。
- `Retarget` resolver 正例通过。
- AddModifier runtime 正例通过目标表达式解析后产生 `status_details` mutation。

负例覆盖：

- `TargetSort*` / `TargetFetch*` blocked。
- unsupported `TargetFilter` condition blocked。
- 缺 `Retarget.TargetType` blocked。
- `ParamEntityList` 缺事件 payload blocked。
- blocked/audit-only/discovered-only 不产生 mutation。

## 7. 推荐下一步

P7 已完成，当前没有尚在执行的阶段。下一步应基于保留缺口重新制定独立计划，优先评估 P2 action-delay callback graph、P3 servant action graph、P4 action formula runtime graph 和 P6 上游动作图；不要把这些内容缺口重新塞回已经完成的 P7。

P7 仍要延续并收紧 P4/P5/P7 的执行结构：

1. 一次只做一个阶段。
2. 每阶段先提交阶段执行卡，等待确认后再改文件。
3. 执行线程只能提交 `ready_for_review`，不能自称 `done`，不能改 checklist。
4. 执行 evidence 与验收裁决继续分离，只有验收线程可以勾选阶段和创建检查点。
5. 聚合必须继承分步 gap，不能用宽域 executable 正例掩盖内部缺口。

后续仍要继续做 executable / boundary_only / source_absent_not_required / implementation_missing / admission_gap / source_gap_blocked 分流；当前数据库确实无真实来源且不属于当前阶段必做的项继续保持 source_absent_not_required 或 boundary_only。状态、召唤物、数据卡或 action/query 如果被再次触达，应把对应 P2/P3/P4 聚合和直接相关回归列入验证范围。

## 8. 推荐验证命令

P7 已完成后，日常修改只运行本阶段直接触达验证、`compileall` 和 `git diff --check`。下面的共享回归与 S19 命令仅用于重建 P7 验收 evidence，不是常规健康检查；S19 的 `ready_for_review` 聚合包含“执行线程尚未勾选 Checklist”的预验收权限门，P7-DONE 勾选后的最终裁决以 P7 最终检查点为准。若未来需要重开 P7，必须先建立新的修复阶段和验收口径，不能直接修改已接受检查点。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_current_tree_shared_regressions --output-dir /tmp/p7_current_shared_regressions
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.build_p7_s19_stage_evidence_manifest --stage-root /tmp/p7_current_stages --s6-real-source-evidence /tmp/p7_current_shared_regressions/p7_s6_real_source_evidence.json --output /tmp/p7_current_stages/stage_evidence_manifest_v2.json
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s19_kernel_invariant_aggregate --regression-root /tmp/p7_s19_regressions --stage-evidence-manifest /tmp/p7_current_stages/stage_evidence_manifest_v2.json --current-regression-manifest /tmp/p7_current_shared_regressions/p7_current_tree_shared_regression_manifest.json --output-dir /tmp/p7_s19_regressions/p7_s19_acceptance
git diff --check
```

高负载验证继续串行运行，默认输出到 `/tmp`，不要并行启动多个完整 lowering / RuleBook 构建脚本。

## 9. 工作习惯

- 非必要不要读整个项目。
- 结构性问题优先用 CodeGraph；文本搜索用 `rg`。
- 修改用 `apply_patch`。
- 不要引入新依赖，除非用户明确批准。
- 验证输出写 `/tmp` 或版本化输出目录，不污染仓库。
- 有意义结构阶段要更新 `live_validation_reports/`。
- 阶段验收通过后再由验收线程创建 git 检查点提交。
- 阶段汇报要说清：做了什么、没做什么、当前进度、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些大模块、验证结果。

## 10. 下个线程接续提示

如果要继续推进，建议开局说清：

```text
当前接续 v8 P7 最终验收检查点和已验收的 P8-S0 至 P8-S3。先读 CODEX_HANDOFF、架构边界合同、P8 计划以及 S0-S3 报告；下一步只执行 P8-S4 光锥实例、成长与命途激活决策。执行线程先提交详细执行卡，只能交 ready_for_review，不得修改 P8 唯一 checklist，也不得提前应用静态被动属性、启动动态 ability 或进入 P8-S5。
```

不要从旧 `CODEX_HANDOFF` 的 v7 叙述接续；本文件已经替换为 v8 当前交接手册。
