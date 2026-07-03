# v8 工程交接手册

## 0. 一句话状态

当前主线是 `simulator_v8_clean_core`，已经推进到 `P1-9 phase1 aggregate validation`。最近已通过 P1-9 聚合验收：`validate_p1_9_phase1_aggregate` 输出 `ok=true`、`p1_9_done_eligible=true`、`phase1_full_acceptance=false`。这表示第一阶段聚合底座可验收，但第一阶段全正例仍被 source gap 阻塞，不能标为完整完成。

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
6. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p1_9_phase1_aggregate_checkpoint.md`
7. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_status_target_event_database_audit_checkpoint_v0_287.md`
8. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_ir_checkpoint_v0_288.md`
9. `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_target_expression_sequence_filter_retarget_checkpoint_v0_289.md`

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
- P1-9 聚合 scenario 覆盖 two-wave setup、source-backed initial status、source-backed summoned monster、servant source gap、explicit timeline、scenario RNG ledger、objective metadata 和至少一个 route transition。
- P1-9 route transition 当前是 route contract 样本；若无 mutation，会在 samples 中标为 `route_contract_only_no_mutation`，不作为 core source audit 正例。
- core snapshot replay / source audit 正例使用 source-backed direct status transition，要求 `mutation_count>0`、`checked_mutations>0`、`checked_records>0`。
- executable 矩阵项只有 `replay_ok=true` 且 `source_audit_ok=true` 才能随聚合 `ok=true` 通过；status setup 的 source trace 统计会识别嵌套 lifecycle/status instance source trace。
- 聚合输出在 `/tmp/hsr_v8_p1_9_phase1_aggregate/`，关键文件包括 `validation_summary_p1_9_phase1_aggregate.json`、`phase1_system_matrix_p1_9.json`、`phase1_source_gap_matrix_p1_9.json`、`phase1_transition_audit_samples_p1_9.json`。
- P1-9 summary 当前结论：`ok=true`、`p1_9_done_eligible=true`、`phase1_full_acceptance=false`、`implementation_missing=0`。

后续已修正 P1-6 目标系统误缺口：`TargetAliasConfig` / `TargetOperationConfig` 现在会 lower 成带真实来源的 `TargetExpressionIR`，`formation sort`、`toughness sort`、`owner fetch` 均有 executable 正例；`ModifierOwnerEntity` 缺 owner 时不再 fallback 到 caster。

## 5. 当前明确没做到什么

P1-9 后仍明确没有完整：

- P1-4：`DispelStatus(Order=Random)` 当前确认是真 source gap；`stack + duration refresh` 不再直接判为 raw source gap，当前更可能是 validation/lowering/admission gap，需要审计 `Stacking`、`Count`、`LifeTime`、`StackProperty` 等 raw 字段如何投影。
- P1-6：formation sort、toughness sort、owner fetch 已修正为 executable；servant target raw/IR 均有大量候选，但 runtime servant registry/admission 未完成。
- P1-7：`random_source_paths` 需要拆分；random dispel 是 source gap，control resist 是 control admission/formula 缺口。
- P1-8：servant initial setup、battle_unit_summon initial setup 不能再简单叫 source gap。raw/IR 定义存在，但 stat/timeline/lifecycle/action/source admission 未完成，已验证 blocked/no mutation。

最新缺口归因报告：

- `hsr_v075_baseline_clean/hsr/live_validation_reports/v8_p1_gap_attribution_audit_checkpoint.md`

状态系统主体还没完整：

- 叠层、刷新、概率、失败分支。
- 持续时间、tick、expire。
- DoT tick。
- 控制、抵抗、免疫、驱散。

目标系统还没完整：

- `TargetSort*`。
- `TargetFetch*`。
- 随机目标。
- 相邻目标。
- 唯一实体查询。
- 召唤物/servant 目标。
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

建议下一阶段继续做 source gap / implementation gap 分流，不要继续扩动作入口，也不要为了 full acceptance 合成正例。优先处理当前 RuleBook / Canonical IR 中确有真实来源但 runtime admission 或验证不足的项；当前数据库确实无真实来源的项继续保持 source_gap_blocked。

推荐顺序：

1. 重新审查 P1-4 stack/refresh/chance/duration/dispel，先区分真实来源缺口与 runtime 实现缺口。
2. 补齐有真实来源的 status lifecycle / chance / duration / tick / dispel admission 和 negative validation。
3. 复查 P1-7 RNG source admission，继续要求 missing/invalid choice blocked 且 no mutation。
4. 进入 servant / battle_unit_summon admission 审计，拆清 servant、battle unit summon、summoned monster、adventure summon unit。

理由：

- v0_287 已经做过数据库审计矩阵。
- v0_288/v0_289 已经补了目标表达式底座。
- 怪物技能、状态监听、AddModifier 已经能把更多状态挂入系统。
- 现在最大的机制阻塞点是状态自身生命周期和判定语义。

## 8. 推荐验证命令

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_after_p1_9
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_284 --output-dir /tmp/hsr_v8_monster_attached_status_v0_284
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
当前接续 P1-9 phase1 aggregate validation。先读 CODEX_HANDOFF、README、PROJECT_GOALS、FORBIDDEN、MONSTER_CARD_SPEC 和 `v8_p1_9_phase1_aggregate_checkpoint.md`。P1-9 聚合底座已通过，但 `phase1_full_acceptance=false`；下一步先做 source gap / implementation gap 分流，runtime 仍只能读 Canonical IR/数据卡 IR，缺来源或缺条件必须 blocked/state unchanged。
```

不要从旧 `CODEX_HANDOFF` 的 v7 叙述接续；本文件已经替换为 v8 当前交接手册。
