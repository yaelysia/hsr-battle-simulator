# v8 工程交接手册

## 0. 一句话状态

当前主线是 `simulator_v8_clean_core`。P1 最终收口、P2 状态系统底座、P3 召唤物体系底座、P4 角色卡 / 怪物卡数据卡扩面底座、P5 公式 / 动态值 / 参数绑定通用准入底座、P6 架构边界回正均已完成当前闭环验收。P6 聚合入口 `validate_p6_architecture_boundary_refactor` 输出 `ok=true`、`stages=4/4`、`ready_for_review=true`、`p6_all_mechanisms_reimplemented=false`；S0 当前 `violation_row_count=0`，P6 自有越界显式延期白名单为空。P6 是边界回正，不是全机制复刻完成。

当前规划主线是 P7 内核可信执行与战斗语义回正。P7-S0 问题基线、P7-S1 Transition 可信结果契约和 P7-S2 Mutation 前置条件与 reducer 冲突检测已经独立验收。Mutation 现在显式区分路径存在性与 null，支持结构化 set/delete/spawn，并在创建时递归冻结 before/after/metadata、缓存 stable ID；reducer 写状态前防御性 thaw，避免原始对象和 BattleState 别名污染。单位状态完整 payload 已收敛到单一 `core/unit_state_codec.py`，reducer/lifecycle/spawn 共同使用。P1-1、P1-2、P1-4 直接回归均通过。下一步只能执行 P7-S3 所选执行图原子提交；P3/P4/P5 admission gap 和内容扩面继续保留。

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

P3 召唤物 / 忆灵聚合验收更正：

- 新增 `tools/validate_p3_summon_assistant_servant_complete.py`，默认只做一次 TBGD lowering / RuleBook 构建，不串联 subprocess，不写完整 Canonical IR 或全量 transition dump。
- 聚合现在能诚实继承分步矩阵缺口，并把 source/mechanism 宽域正例拆成 executable slice 与 gap 子行；AssistantAvatar 另记为 scope exclusion。这是底座闭环验收通过，不是全正例完成。
- P3-S12 最新 summary：
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
- allowed gap evidence matrix：3 rows，`allowed_gap_count=2150`、`disallowed_gap_count=0`、`all_evidence_ok=true`。P3 底座闭环验收通过；全正例完成仍要求 inherited gap 为 0。
- scope exclusion matrix：1 row，AssistantAvatar / `TurnInsertAssistantAbility` `out_of_scope`，raw=5、IR=5、RuleBook visible=5、`p3_gap_count=0`。
- 正例样本 8 条、blocked / state unchanged 样本 7 条、source audit 样本 5 条、replay 样本 8 条均通过。
- 当前 P3 可依赖能力：
  - summoned monster source-backed spawn / runtime registry / fixed-sequence action availability / target relation / replay / source audit。
  - `SummonUnitData` / `ConfigSummonUnit` catalog 和非 battle 来源保持 boundary，不会自动 spawn。
  - servant definition、owner/stat/lifecycle、spawn/remove、action availability、status holder、BattleSetup initial setup 和 scenario route。
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

推荐下一步只执行 P7-S3 所选执行图原子提交：把一次动作实际选择并触发的全部节点纳入统一预检和提交门，任一节点 blocked、partial、unsupported 或 reducer 冲突时，整次动作必须 mutation 为零且 state unchanged。开始编码前仍须提交独立执行卡，不得提前展开 S4-S19。P7 完成可信状态转移、动作 / 目标 / 调度和核心战斗语义回正前，暂停大规模内容扩面。

P7 仍要延续并收紧 P4/P5/P7 的执行结构：

1. 一次只做一个阶段。
2. 每阶段先提交阶段执行卡，等待确认后再改文件。
3. 执行线程只能提交 `ready_for_review`，不能自称 `done`，不能改 checklist。
4. 聚合只能在所有分步均由验收线程确认后实现。
5. 聚合必须继承分步 gap，不能用宽域 executable 正例掩盖内部缺口。

后续仍要继续做 executable / boundary_only / source_absent_not_required / implementation_missing / admission_gap / source_gap_blocked 分流；当前数据库确实无真实来源且不属于当前阶段必做的项继续保持 source_absent_not_required 或 boundary_only。状态、召唤物、数据卡或 action/query 如果被再次触达，应把对应 P2/P3/P4 聚合和直接相关回归列入验证范围。

## 8. 推荐验证命令

这些命令用于复核当前 P1-P6 已验收底座范围，不代表 P7 发现的问题已经解决，也不是每次小改都要全量运行。P7-S0 已通过自身轻量基线；后续阶段按触达范围选择直接回归，P1-P6 全聚合默认只在 P7-S19 串行运行。在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s2_mutation_reducer_contract --output-dir /tmp/hsr_v8_p7_s2_mutation_reducer_contract
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p7_s1_transition_trust_contract --output-dir /tmp/hsr_v8_p7_s1_after_p7_s2
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_architecture_boundary_refactor --output-dir /tmp/hsr_v8_p6_current
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
- 每个较大代码变动后创建 git 检查点提交。
- 阶段汇报要说清：做了什么、没做什么、当前进度、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些大模块、验证结果。

## 10. 下个线程接续提示

如果要继续推进，建议开局说清：

```text
当前接续 v8 P7-S2 Mutation 前置条件与 reducer 冲突检测验收检查点。先读 CODEX_HANDOFF、README、ARCHITECTURE_BOUNDARY_CONTRACT、PROJECT_GOALS、FORBIDDEN、P7 计划及 S0/S1/S2 evidence。S0、S1、S2 已验收；下一步只能为 P7-S3 所选执行图原子提交提交详细执行卡，重点处理多 task、状态 partial、callback 中间失败和 reducer 冲突时的整动作 state unchanged。UI `enemy_ai_auto_skip` 的既有验证错位继续归 P7-S8，不得在 S3 顺手修复。
```

不要从旧 `CODEX_HANDOFF` 的 v7 叙述接续；本文件已经替换为 v8 当前交接手册。
