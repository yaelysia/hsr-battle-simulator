# v8 工程交接手册

## 0. 一句话状态

当前主线是 `simulator_v8_clean_core`。P1 最终收口已完成：P1-9 聚合输出 `ok=true`、`p1_9_done_eligible=true`、`phase1_repair_substrate_accepted=true`、`phase1_minimum_battle_slice=true`，且 blocker 列表为空。第一阶段最小完整战斗纵切已通过，后续应进入 P2，不要继续按旧 P1 blocker 修补。

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
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PROJECT_GOALS.md`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md`
5. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/MONSTER_CARD_SPEC.md`
6. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/PHASE1_SUMMARY.md`
7. `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`
8. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_status_target_event_database_audit_checkpoint_v0_287.md`
9. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_ir_checkpoint_v0_288.md`
10. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_sequence_filter_retarget_checkpoint_v0_289.md`

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

## 5. 当前明确没做到什么

P1 minimum 已完成，但完整复刻仍远未完成：

- P1-4：deterministic dispel、refresh、stack、duration、expire、DoT、chance/resist/immunity 等已有专项正例；`DispelStatus(Order=Random)` 当前是 `source_absent_not_required`，不再作为第一阶段 blocker；`stack + duration refresh` 当前没有组合来源正例，禁止 synthetic positive case。
- P1-5：counter 已有 P1-FINAL 端到端正例；follow-up 当前未发现第一阶段可执行来源，不阻塞 P1；assistant 仍是 `boundary_only`。
- P1-6：formation sort、toughness sort、owner fetch、servant target 已修正为 executable；更完整的特殊玩法目标、复杂 fetch/sort、召唤物/servant 扩展语义仍在后续阶段。
- P1-7：`random_source_paths` 已拆分口径；random dispel 当前是 `source_absent_not_required`，control resist 是 control admission/formula 缺口。
- P1-8：servant/忆灵 initial setup 已有真实来源正例；battle_unit_summon / `SummonUnitData` catalog 不是自动 battle spawn trigger，当前是 `boundary_only`，已验证 blocked/no mutation。

最新缺口归因报告：

- `hsr_v075_baseline_clean/hsr/live_validation_reports/archive/phase1/v8_p1_gap_attribution_audit_checkpoint.md`

状态系统主体还没完整：

- 叠层、刷新、概率、失败分支。
- 持续时间、tick、expire。
- DoT tick。
- 控制、抵抗、免疫、驱散。

目标系统还没完整：

- 更完整的 `TargetSort*`。
- 更完整的 `TargetFetch*`。
- 随机目标扩展。
- 相邻目标。
- 唯一实体查询。
- 召唤物/servant 目标扩展。
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

- summon、assistant、servant 完整行为。
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

建议进入 P2，而不是继续 P1 修补。后续仍要继续做 executable / boundary_only / source_absent_not_required / implementation_missing 分流；当前数据库确实无真实来源且不属于当前阶段必做的项继续保持 source_absent_not_required 或 boundary_only。

推荐顺序：

1. 扩展完整状态系统主体：组合叠层+持续时间刷新、更多 tick/控制/抵抗/免疫/驱散分支。
2. 扩展角色/怪物数据卡解释范围，继续禁止 runtime 特判角色或怪物。
3. 扩展 servant/召唤物/assistant 完整行为，但保持 servant 已有 P1 纵切不回退。
4. 进入 battle_unit_summon admission 审计时先区分 catalog/visual/adventure 与真实 battle spawn trigger。

理由：

- v0_287 已经做过数据库审计矩阵。
- v0_288/v0_289 已经补了目标表达式底座。
- 怪物技能、状态监听、AddModifier 已经能把更多状态挂入系统。
- P1 minimum 已不再被 servant 或 counter 阻塞；后续最大工作量仍是状态、角色/怪物机制、装备和关卡系统扩面。

## 8. P1 回归验证命令

这些命令用于复核 P1 最小纵切，不是 P2 每次小改的默认全量验证。在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_counter_final
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_counter_final
git diff --check
```

如果下一步改状态系统，新增验证应至少覆盖：

- 正例：状态叠层、刷新、概率成功/失败、持续时间递减、到期移除。
- 负例：缺来源、缺 duration、缺 chance source、unsupported stack rule、blocked listener 不产生 mutation。
- audit：每个状态 mutation 能反查到 status definition、modifier definition、effect/callback、target expression、source trace。

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
当前接续 v8 P2。先读 CODEX_HANDOFF、PHASE1_SUMMARY、README、PROJECT_GOALS、FORBIDDEN、MONSTER_CARD_SPEC 和归档最终报告 `live_validation_reports/archive/phase1/v8_p1_final_acceptance_checkpoint_v0_292.md`。P1-9 最终聚合已通过，`phase1_minimum_battle_slice=true` 且 blocker 为空；P1 过程计划和中间报告只作追溯，不作为当前任务入口。下一步继续按 executable / boundary_only / source_absent_not_required / implementation_missing 分流推进 P2，runtime 仍只能读 Canonical IR/数据卡 IR，缺来源或缺条件必须 blocked/state unchanged。
```

不要从旧 `CODEX_HANDOFF` 的 v7 叙述接续；本文件已经替换为 v8 当前交接手册。
