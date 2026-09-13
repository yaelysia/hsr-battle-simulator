# R6 — Encounter / Spawn / Phase / Termination v1

## 1. Record metadata / checkpoint verdict

```text
THREAD_ID=R6-ENCOUNTER-SPAWN-PHASE-TERMINATION-V1
research_date=2026-09-11
input_head=65932e3f42b216c5a61fbbdfdd7237f46a6c30cd
pinned_tbgd=14c1d18f91a8101d610e6c523447a7517de3fae1
status=partial
bounded_complete=no
decision_needed=separate lowering/runtime alignment repair card
evidence_maturity=manually_confirmed
confidence=high for inspected raw identities and static contracts; runtime behavior unvalidated
authority_class=mixed_requires_filter
battle_scope_verdict=include, with operation-level exclusions
runtime_changed=no
runtime_tests=not_run
tracking=Issue #7 / PR #8
```

本记录完成 Stage 103201 的配置、波次、槽位、monster/profile/birth-template 输入追踪，解析 Stage 301001 的真实 StageAbility，并对照当前首波、后续波、phase 与 termination 消费者。**不把候选数值投影或已存在的消费者误报为成功生成 UnitState。**

发现一个可由当前源码直接定位的 producer/consumer 不一致：`_wave_enemy_birth_template` 生成的 `monster_rank_source_trace` 没有 `evidence`，而 `UnitSpawnPlan.to_unit` 递归要求每个 source identity 携带 evidence mapping。按此直接调用链，正常 wave birth 会被 materialization 校验拒绝。见 §7；这是静态发现及错误字符串推导，不是已执行的 runtime 日志。因此本轮交付 independently reviewable **partial checkpoint**，不宣布 R6 bounded complete，也不修改 runtime 规避检查。

### 证据桶与版本

- **S**：本 pin 的原始字段、引用与 task/callback 声明。
- **K**：上述业务仓库 input head 的实际实现；不是 TBGD 原始权威。
- **I**：逐边 source/kernel 对齐推论，注明成立条件和失败点。
- **G**：export、native engine、convention、transport 或 validation gap。

最终矩阵另用 A=source-facing closed、B=export/engine gap、C=local implementation present、D=source-aligned、E=runtime validated/test-backed。全文无 E 晋级。版本上下文仅限上述 release-data pin；没有用 live/beta 数值补洞。

## 2. Kernel-first preflight / scope gate

先用实际 GitHub 插件确认 PR head 与规划起点一致且仍为 Draft，再按该 SHA 读取 AGENTS、BATTLE_SCOPE、EVIDENCE_RECORD_TEMPLATE、README、POST_R5_RESEARCH_COMPACTION、PINNED_SOURCE_INDEX、SOURCE_FAMILY_INVENTORY 及现有 stage/monster 记录。当前 sequencing 采用 post-R5 compaction，不采用旧 worklist 的 Next closure 顺序。

复用记录：

- `docs/tbgd_evidence/stages/stage_config_wave_source.md`：ordinary HardLevel 与 conditional Unique 修正、两个 stage anchor。
- `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md`：monster identity/reference 方法及 phase/config 同名边界。
- `docs/tbgd_evidence/shared/global_shared_reverse_scan.md`：已有 ordinary Sam / shared task-template 证据；本轮不是 W17 broad scan。

下列 K 路径均相对 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/`，均按 input head 读取；前六项在继续 TBGD tracing 之前检查：

| K consumer / producer | 本轮检查的责任 |
| --- | --- |
| `systems/wave.py` | `WaveSystem.view/plan_transition/apply_transition`、清波、pending queue、非当前敌人、remove、next spawn、终局 |
| `systems/unit_spawn.py` | request、template contract、materialization、`to_unit`、source-proof fail-closed |
| `systems/phase_machine.py` | `WAVE_TRANSITION` 及 wave/terminal event phase gate |
| `systems/battle_state_transition.py` | typed global_flags transition；不等同 monster phase 或 spawn |
| `tbgd/monster_cards.py` | normal/unique 字典加载、MonsterTemplateID join、card 来源与参与条件 |
| `tbgd/lowering.py` | `_lower_combatant_profiles`、`_lower_wave_definitions`、`_hard_level_profiles`、`_wave_level_policy`、`_lower_unit_birth_templates`、`_wave_enemy_birth_template` 及直接 value/resource helpers；仅定位读取相关段落 |
| `scenarios/build_state.py` | 补查首波 `_with_initial_wave_units/_wave_unit_spec/_initial_wave_runtime`，不是将后续波假充首波入口 |
| `rules/engine_rule_registry.py` | 仅 birth 所需 timeline convention；不重开 W07 |
| `rules/ir.py` | 仅直接相关 `UnitBirthTemplateIR` 定义，排除构造时自动补 source evidence 的假设 |
| `systems/unit_lifecycle.py` | active/defeated/removed 与 presence 的区别；不把清波简化为裸 HP 比较 |

**具体战斗后果测试**：配置决定实际敌方实体的数量、位置、身份和出生输入；StageAbility 改变冻结期间的属性/受击数据；phase 可修改已有实体而不分配新实体；清波决定 remove、生成下一波或写终局。模型依据是本轮指定的普通战斗问题和已复用证据，随后由 S 声明与 K 分支核对；未声称独立游戏实测。

**冻结边界**：不寻找隐藏 generic configured-stat 方法，不猜 native 乘加顺序、flat ModifyValue placement、clamp/rounding，不猜 Stage-vs-Monster HardLevel/Elite precedence；不用 ILHardLevelGroup；不默认 Unique；不重开 W17/W07/W10/W12 或 R2/R3/R4 generic evaluator；不扩 progression、rewards、deferred modes；不改 runtime/lowering/IR/tests/CI/dependencies/pin；不进入 R7。§7 的本地接口矛盾只登记为独立修复前置，不解除这些冻结项。

## 3. Exact-pin raw evidence index

以下链接全部固定到 TBGD pin。JSON occurrence 用字段 predicate 标识，不依赖文件名相似或搜索排名。

| Ref | Exact path / occurrence | Blob（已取到时） |
| --- | --- | --- |
| [S1][S1] | `ExcelOutput/StageConfig.json`，`StageID=103201`、`301001` | `91840cadab4a1d01831cbdc3219bf4baff493fce` |
| [S2][S2] | `ExcelOutput/MonsterConfig.json`，selected `MonsterID=1022020/1023010/8003020` | `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` |
| [S3][S3] | `ExcelOutput/MonsterTemplateConfig.json`，explicit `MonsterTemplateID=1022020/1023010` | 以 exact-pin 内容为准 |
| [S4][S4] | `ExcelOutput/HardLevelGroup.json`，`(HardLevelGroup,Level)=(1,29)/(1,40)` | `9ee36b767b010d2c85aa7169e86e9f0a4220a935` |
| [S5][S5] | `ExcelOutput/MonsterUniqueConfig.json`，检查上述三个 selected MonsterID 的参与性 | 未用 family 存在代替 row participation |
| [S6][S6] | `ExcelOutput/MonsterTemplateUniqueConfig.json`，检查 selected TemplateID；区分图片路径命中 | `a784cea34a5d5791dc40c5d9ca2a02ce682bdd5d` |
| [S7][S7] | `Config/Level/StageCommonTemplate.json`，stage ability/born/wave/terminal task lists | `d76c3f1d8a2536da6a6f79e4bb44b79f48b91c5a` |
| [S8][S8] | `Config/ConfigAbility/Level/Level_MazeChallengeBuff_Ability.json`，`AbilityList[Name=StageAbility_301001]` | `dd09d51c85e4b62400c83c8028626cabaa527dbc` |
| [S9][S9] | `Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json`，`Monster_ChangePhase`、`Wave_CommonPreProcess/Process`、`TaskList_WaveMonsterDelayCreate` | exact-pin 定义读取 |
| [S10][S10] | `Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json`，Passive01 / AIChange / OnEndBreak | exact-pin sibling discriminator |
| [S11][S11] | `Config/GlobalConfig/GameCoreConstValue.json`，`MonsterRankScore.MinionLv2.Value=1` | 只纳入 selected birth 直接读取的 rank 输入 |

大表读取曾返回空 content 而携带 blob SHA。S1/S2 随后通过对应 Git blob GET 实际读取正文；空返回不是 export omission。默认分支搜索仅用于定位候选路径，S8/S10 均重新按 pin 读取；不以 default revision 内容作为证据。

## 4. Stage -> ordered WaveDefinitionIR / WaveMonsterEntryIR

### 4.1 S：两个 stage 的真实输入

| Field | 103201，primary | 301001，StageAbility / Elite discriminator |
| --- | --- | --- |
| StageType | `Mainline` | `Mainline` |
| Level / HardLevelGroup | `29 / 1` | `40 / 1` |
| LevelGraphPath | `Config/Level/StageCommonTemplate.json` | 同一显式 path |
| StageAbilityConfig | `[]` | `["StageAbility_301001"]` |
| StageConfigData 的 `_Wave` | `"1"` | `"1"` |
| concrete MonsterList wave count | `1` | `1` |
| wave 0 ordered slots | `Monster0=1022020; Monster1=1023010; Monster2=1022020` | `Monster0=1022020; Monster1=1023010; Monster2=8003020; Monster3=1022020` |
| Stage-level EliteGroup | inspected row 未声明该 key；不是 S=0 | `5` |
| LevelLoseCondition / LevelWinCondition | `[] / []` | `[] / []` |

`_Wave` 的真实序列化结构是 `StageConfigData` 中 `BFLIFKBEOPJ="_Wave"` 与 `MNDFOPKBHKP="1"`。两行另有 `_IsEliteBattle="1"`；这不等同于证明 EliteGroup 的运算优先级。空 win/lose 数组也不意味着没有通用终局检查（S7 仍有）。

### 4.2 K：实际 lowering，不是重写 encounter runtime

`_lower_wave_definitions` 从 StageConfig rows 读取并按 MonsterList 原始 list 顺序枚举零基 wave_index。每个 wave 内，`_stage_monster_items` 对 `MonsterN` 的数值后缀排序，得到 position；不是按 monster ID 排序或去重 roster。

103201 的静态构造结果身份如下（不是已运行 compiler 的导出文件）：

```text
WaveDefinitionIR.wave_definition_id = wave_definition:stage:103201
stage_id = 103201; wave_count = 1; level = 29; hard_level_group = 1
stage_ability_refs = ()
definition source = (ExcelOutput/StageConfig.json, StageConfig, 103201)
```

| wave / position | entry_id | monster_entity_ref | birth_template_id | entry source raw_id |
| --- | --- | --- | --- | --- |
| 0 / 0 | `wave_entry:stage:103201:w0:p0:1022020` | `monster:1022020` | `unit_birth_template:wave:103201:1022020` | `103201:0:Monster0` |
| 0 / 1 | `wave_entry:stage:103201:w0:p1:1023010` | `monster:1023010` | `unit_birth_template:wave:103201:1023010` | `103201:0:Monster1` |
| 0 / 2 | `wave_entry:stage:103201:w0:p2:1022020` | `monster:1022020` | `unit_birth_template:wave:103201:1022020` | `103201:0:Monster2` |

entry source 的 raw_type 是 `StageConfig.MonsterList`，evidence 保留 StageID、stage_row_index、StageConfigData、declared_wave_count、原 MonsterList index/key、monster_id、level_policy。definition source 保留 declared/concrete count、entry counts、Level、HardLevelGroup、StageAbilityConfig 和 level_policy。重复的 1022020 共用模板，但不合并两个 entry、slot 或实例。

301001 同理产生 `wave_definition:stage:301001`、四个 `w0:p0..p3` entries；`stage_ability_refs=("StageAbility_301001",)`，并选择 HardLevel `(1,40)`。这一步只运输 ability 名称，不证明已安装/执行该 ability。

### 4.3 Fail-closed 与未验证的结构边界

| 输入情形 | 当前 K 行为 | 本轮结论 |
| --- | --- | --- |
| 有正 declared count，但与 concrete list 长度不等 | definition blocked：`stage_wave_count_monster_list_mismatch` | 没有静默修正为可执行 |
| declared count 缺失/无效/非正 | 内部 wave_count 可暂用 list 长度，随后 blocked：`stage_wave_count_missing` | fallback 值不等于 admission |
| Level/HardLevel row 或 ratio 不可用 | level_policy/entry/definition blocked | 不应补默认难度 |
| monster 空/0、缺 entity/profile/card | 对应 entry blocked，传播到 definition | 不是容许空槽直接运行 |
| MonsterList 缺失、非 list 或空 | 该 stage 在这个 builder 中被跳过 | source-preservation/admission residual，不声称全 pipeline 已报错 |
| inner wave 非 dict；非 Monster key；Monster 非数值后缀 | 分别跳过、忽略、position=9999；还有 ID 类型正规化 | 静态发现的 validation gaps；没有运行 malformed-input 反例，也没有发现 primary row 被此逻辑改写 |

K 并未在这个 WaveDefinitionIR producer 中运输 Stage `EliteGroup`、`LevelGraphPath`、win/lose 数组；因此它不是完整 Level graph 的语义复制品。不能把保留下来的 Stage ID 反推为所有 stage 行为已实现。

## 5. Wave entry -> actual monster inputs -> birth template

### 5.1 S / K participation

对 primary slot 0：S1 的 `Monster0=1022020` -> S2 **MonsterID 主键** -> 该 row 的显式 `MonsterTemplateID=1022020` -> S3 的对应主键 row。虽两数相同，join 依据是字段，不是相同数字或文件名。

S2[1022020]：五个 Attack/Defence/HP/Speed/Stance ModifyRatio 均为 1；HardLevelGroup=1、EliteGroup=1；未声明 selected flat ModifyValue。Weakness 为 Ice/Wind/Imaginary；Physical/Fire/Thunder/Quantum resistance 分别为 0.2/0.4/0.2/0.2；DebuffResist 的 STAT_DOT_Burn=1。CustomValues、DynamicValues、SummonIDList 为空。

S3[1022020]：Rank=MinionLv2；HPBase=139.5、AttackBase=18、DefenceBase=210、SpeedBase=100、StanceBase=60；StatusResistanceBase=0.1、InitialDelayRatio=1。其 JsonConfig 是 `Config/ConfigCharacter/Monster/Monster_W1_Soldier01_01_Config.json`，并有显式 AI/skill references；本轮不把 card 存在宣称为全部 AI/action 已验收。

primary slot 1 的显式 join 是 `MonsterID1023010 -> MonsterTemplateID1023010`：五个 ModifyRatio 均为 1，template Rank=Elite、HPBase=1023、AttackBase=18、DefenceBase=210、SpeedBase=100、StanceBase=300。邻近 `102301001` 等变体不是 selected row，不能把其 flat/ratio 混进本链。

| Difficulty input | S4 (1,29) | S4 (1,40) |
| --- | --- | --- |
| AttackRatio | 5.19238 | 8.634539 |
| DefenceRatio | 2.333333 | 2.857143 |
| HPRatio | 5.020885 | 9.524581 |
| SpeedRatio / StanceRatio | 1 / 1 | 1 / 1 |

**Unique conditionality**：K monster-card builder 确实加载 normal table，再按 ID 用 unique dictionary update；但 S5 对三个 selected MonsterID 都没有命中。S6 中 1022020/1023010/8003020 仅命中其他 TemplateID（7002030/7003080/7003010）的图片路径，不是这些 selected TemplateID。结论仅为 **not participating in inspected chains**；不是 universal override、零值或推定 default。

**Elite / HardLevel 边界**：selected monsters 的 HardLevel=1 与两个 stage 的 group=1 一致，不能提供 native precedence discriminator。301001 的 Stage EliteGroup=5 与 Monster EliteGroup=1 共存；当前 inspected profile/wave birth 不应用 Stage Elite 运算，也不能因此证明 native 应忽略它。两项 precedence 均留 G。

### 5.2 K：候选字段投影与 convention 身份

`_monster_profile_stats` 先按 template base × monster ModifyRatio 构造 profile；`_wave_enemy_birth_template` 再乘 Stage-selected HardLevel ratio。这是 **K arithmetic**，不因 Ratio 字段名而晋级为 S 的 native 最终公式；flat placement、clamp、rounding 均未闭合。

对 `unit_birth_template:wave:103201:1022020` 的候选规格：

| Birth field | 本轮手算的 K 投影 / binding | S / convention 分类 |
| --- | --- | --- |
| template_id | `monster:1022020` | K concrete monster identity；不是 Excel MonsterTemplateID 字段本身 |
| level | 29 | S Stage Level，经 K 运输 |
| max_hp | 700.4134575 | S 输入；K 运算 |
| hp | `copy_unit_field(max_hp)` | K 满血出生规则 |
| attack | 93.46284 | S 输入；K 运算 |
| defense | 489.99993 | S 输入；K 运算；不擅自四舍五入为 490 |
| speed | 100 | S 输入；K 运算 |
| toughness / max_toughness | 60 / 60 | S Stance 输入；K 映射及初始化 |
| energy / max_energy | 0 / 0 | builder 直接置零的 K，不是未见 source row 的零值证明 |
| action_value | `timeline_action_value(speed, gauge=10000, multiplier=1)`，投影 100 | registry 明示 engine_convention；不是 S native scheduler |

timeline rule 是 `timeline_rule:engine_convention:base_action_gauge_10000`，registry version `hsr_v8_engine_rules_v6`。S3 InitialDelayRatio=1 的存在不能证明 wave builder 读取它；此 builder 的 multiplier 是直接写入 1.0。也不能拿另一个 `SpeedToDelayDistance` 字段替代已明确为 convention 的 gauge。

resources 从 profile resistances 经 `_birth_profile_resources` 的 `f"{damage_type}_resistance"` 映射，另带 `effect_resistance=0.1`。flags 包括 weaknesses/debuff resistances、card/profile source、rank/score（S11 的 MinionLv2=1）、passive slot IDs、Stage level/difficulty source、wave/slot/request sources。`wave_member_kind=stage_wave_enemy`、`wave_clear_policy=counts`、初始 lifecycle active、空 statuses/shields/stat pools 是 K 的初始化/消费约定。

以上是**尚未成功通过 §7 materialization 校验的候选规格**，不是实际执行日志或已生成单位快照。

## 6. Request identity / first-wave versus next-wave consumer

primary slot 0 的具体 request 身份由实际 builder 字段逐项代入：

```text
spawn_kind=wave_enemy
unit_id=enemy:stage:103201:wave:0:pos:0
birth_template_id=unit_birth_template:wave:103201:1022020
entity_ref=monster:1022020
source_id=wave_definition:stage:103201
entry_id=wave_entry:stage:103201:w0:p0:1022020
wave_definition_id=wave_definition:stage:103201
stage_id=103201
wave_index=0
position=0
source_trace=(ExcelOutput/StageConfig.json, StageConfig, 103201, evidence mapping)
entry_source_trace=(ExcelOutput/StageConfig.json, StageConfig.MonsterList,
                    103201:0:Monster0, evidence mapping)
owner/summoner not required for wave_enemy
```

K template 的 `template_source_role=source`：template.source 是 Stage definition source，而 plan.source_trace 是 entry source；monster/profile/card origin 另存 flags。Stage+Monster 共享模板不固定 position，但 request 保留两个重复 monster 的独立 entry/slot/实例。

**首波路径（K）**：`ScenarioStateBuilder.build -> _with_initial_wave_units -> _wave_unit_spec -> UnitSpawnSystem.plan -> plan.to_unit`；之后复制为 `UnitSpec(build_mode=kernel_fixture, PanelInput(...))`，供 builder 构造初始 BattleState。`_initial_wave_runtime` 记录 schema `p1_2_wave_runtime_v1`、current IDs、total_waves、source，并先置 pending_start；不是调用 next-wave spawn 假充初始出生。这个 panel round trip 也不是 R5 formal character admission 已验证的证明。

**后续波路径（K）**：WaveSystem 按下一波真实 entries 生成同一种 request 和 plan，apply 时重新校验 expected request/template，再通过 lifecycle spawn mutations 入场。`_wave_spawn_request_plan_blocked_reason` 检查 counts、unit ID、template/entity、definition/source ID、stage、wave、entry、position。

UnitSpawnSystem 检查 request 完整性、template coverage/contract、owner 规则、source identity、必要 unit fields、有限数值与 timeline binding。`to_unit` 重新 materialize expected payload，比较行为字段，验证 plan/expected sources 和 flags，再调用 UnitState codec。source mismatch 有明确 blocked/ValueError 路径，不能降级为无来源 spawn。

I：selected Stage/wave/slot/Monster 身份本身能够无歧义供应结构化 request；**完整 payload 却因 §7 source-proof 缺口不能宣称通过。** source identity 校验使用 path/type/id，并要求 evidence mapping；它不是重读 TBGD 的哈希认证，evidence 内容也不会自动成为原始权威。

## 7. K mismatch R6-G01 — rank source proof blocks materialization

### 7.1 实际 producer 与 consumer

在 [lowering.py][K-lowering] `_wave_enemy_birth_template`（input head 的 10173–10177 附近），flag 直接构造为：

```python
"monster_rank_source_trace": {
    "source_path": "Config/GlobalConfig/GameCoreConstValue.json",
    "raw_type": "MonsterRankScore",
    "raw_id": monster_rank,
},
```

没有 `evidence`。`UnitBirthTemplateIR` 是保存这些 dict 的 dataclass；本轮检查该类，没有发现会为该 flag 自动补 evidence 的构造 hook。`_materialize_unit_payload` 对 flag 使用 `_resolve_spec`；此普通 dict 不带 binding_kind，按 JSON copy 保留原样。

在 [unit_spawn.py][K-spawn]，`UnitSpawnPlan.to_unit` 调用 `_validate_nested_source_proofs(self.unit, "unit")` 及 expected payload 检查。该 helper 遇到同时含 source_path/raw_type/raw_id 的 dict 就调用 `_required_source_trace_identity`；后者要求 `evidence` 为 Mapping，否则抛出 `unit_spawn_plan_<field_name>_evidence_missing`。

所以，对保留该真实 flag 的 payload，遍历到此项必然无法通过该要求。按字段路径推导的错误为：

```text
unit_birth_template_materialization_invalid:
unit_spawn_plan_unit_flags_monster_rank_source_trace_evidence_missing
```

上面按阅读换行；实际 wrapper 会用冒号直接连接。**这是当前源码推出的错误，不是本轮实际运行得到的异常日志。** 若另有更早的独立失败，可能先报告另一个错误；这不消除此字段的独立不一致。

### 7.2 影响与修复边界

`UnitSpawnSystem.plan` 在返回成功前会自己调用 `plan.to_unit`，捕获 ValueError 后返回 blocked。因此不能绕过“用户稍后才会 to_unit”的假设。首波 `_wave_unit_spec` 遇到 blocked plan 会抛出 ValueError；next-wave 也依赖同一 consumer。

这不是缺失 S11 rank 值：selected Rank 和 score 的原始输入已经找到。它是 **K producer 输出无法满足 K consumer 契约**，应由独立 lowering/runtime 修复卡提供完整、来源正确的 proof 并保留 fail-closed 验证，而不是削弱 gate 或把缺 evidence 当作 source default。

本卡已完成的工作是 source identity、模板字段及失败 consumer 的精确对照；未完成的是该 actual head 的成功 materialization 和出生后动态执行证据。建议独立卡至少验证 primary 103201 两种 monster/重复 slot、首波和后续波，以及 missing/tampered proof 的拒绝反例。这里不提供未授权代码变更，不新建测试、不把建议写成 passed。

## 8. StageAbility_301001 — owner, timing, operation-level classification

S chain（每条引用均按 pin 人工检查）：

```text
StageConfig[301001].StageAbilityConfig[0]
 -> AbilityList[Name=StageAbility_301001] in S8
 -> OnAdd: AddModifier(Caster, StageAbility_301001_Modifier)
 -> modifier callbacks on create / frozen add-remove / being hit
```

另一个显式 edge 是 S1.LevelGraphPath -> S7。S7 声明 `AddStageAbilityByName(ReadFromTable=true)`，其顺序在 CreatePlayerTeam / WaveMonster 之前；还分别安排 StageAbility/BeforeCharacterBorn/BeforeCharacterBorn2 与 AfterCharacterBorn bindings。它提供 table-driven 安装与出生时序的 source-facing graph，不暴露 native loader 内部实现。

| Exact S8 occurrence / operation | Consequence / timing | 分类与限制 |
| --- | --- | --- |
| ability OnAdd -> AddModifier(Caster, main modifier) | 建立 stage ability 的 callback owner | battle-authoritative 安装声明；Caster/Level owner 的 native attachment body 仍不冒充已导出 |
| main `OnListenCharacterCreate` -> ByTargetTeam(ParamEntity,TeamDark) -> AddModifier(ParamEntity, `StageAbility_301001_Modifier_Sub`) | 敌方创建通知时给该新实体挂受击监听 | battle-authoritative；发生在创建回调，不是预先重写 MonsterTemplate base |
| main `OnListenModifierAdd` -> ByAnd(TeamDark, ByCheckModifierCallBackBehaviorFlag STAT_CTRL_Frozen) -> AddModifier(ParamEntity, `_Sub2`) | live battle 中监听冻结加入 | predicate/callback 为 battle-supporting 控制声明，AddModifier 为 battle-authoritative |
| `_Sub2` Stacking=ReplaceByCaster；OnStack -> StackProperty(ModifierOwnerEntity, SpeedAddedRatio, -0.3) | 写入冻结期间速度属性修正 | battle-authoritative；不是 action advance/delay；不推出 native 最终速度乘法 |
| main `OnListenModifierRemove` -> ByContainBehaviorFlag(ParamEntity,STAT_CTRL_Frozen) 的 FailedTaskList -> RemoveModifier(ParamEntity, `_Sub2`) | 回调时若不再含冻结标记，移除速度修正 | battle-authoritative；不能简化为任意一个冻结 modifier remove 必然移除所有冻结效果 |
| `_Sub` OnBeforeBeingHitAll -> ByContainBehaviorFlag(ModifierOwnerEntity,STAT_CTRL_Frozen) -> ModifyDamageData(Defender_AllDamageTypeTakenRatio,0.5) | 冻结目标被击前修改该次 damage data | battle-authoritative；不重开 damage evaluator，也不把 0.5 直接宣称最终伤害公式 |

S8 的这个 ability body 没有靠 camera/animation 执行上述后果。S7/S9 同图出现的 BGM、camera、UI refresh/show 是 presentation-only；WaitForTurnEnd、dying checks、server frame / callback handshakes 不能仅因含 wait 就整体丢作 presentation。具体 native concurrency、callback dispatcher 与数值叠加法则保持 G。

K / I 边界：WaveDefinitionIR 保存 stage_ability_refs，WaveSystem/UnitSpawnSystem 的被检查路径并不因此等于执行了 S8 callbacks。本轮没有证明 Stage301001 在当前 runtime 中完成安装、冻结、受击、解冻全链；不能给 D（完整行为）或 E。S8 owner graph 已解析，不能继续称该 StageAbility 是“source 未找到”。

## 9. Wave clear / next spawn / termination

### 9.1 K：WaveSystem contract

| 条件 / 分支 | 当前实现的实际含义 |
| --- | --- |
| pending queues 非空 | 先阻断 wave transition；不能抢在 pending resolution 前推进 |
| 没有 active ally | defeat，早于按剩余敌人决定胜利；同时清空双方时的优先级只是 K |
| pending_start 且 current entries/units 满足检查 | 标记当前波开始，发 wave.started / wave.monster；首波单位已由 setup 构造 |
| 当前波仍有 active enemy | 不清波、不推进 |
| active non-current enemy | 不一概忽略：其他 wave 的 stage enemy、非 ignore 的 enemy summon、未知 membership 可阻断；不能把所有 reinforcement 排除在 clear 之外 |
| current IDs 缺失或来源不符 | blocked，而不是把消失当作正常击败 |
| 当前波均不 active，且无其他 blocker | 收集非 removed 的清波单位；apply 清理 statuses/status_details 并做 lifecycle remove |
| next index 小于总波数 | 校验下一波 entry/template/request、collision 与出生 plan；全部成功后 remove 旧波、写 wave_index、spawn 新单位、更新 runtime |
| next index 到达总波数 | final victory；清理旧波，产生 wave.cleared、removal、battle.victory、battle.completed |
| defeat apply | 设置终局，产生 battle.defeat 与 battle.completed；不等同 victory 清波/removal 分支 |

active 由 lifecycle/presence 相关 gate 决定，不能将全表敌人 HP=0 直接替换为同一个谓词。apply 返回 mutations/events，仍需正常提交路径消费；本轮没有执行 reducer/CombatExecutor。

终局写 `global_flags.battle_outcome`、`phase=ended`、`current_window=battle_end`。`battle.completed` 是胜负两种终局之后的公共完成事件，不是第三种胜负，也不能重复结算成另一次 victory。

phase_machine 将 wave/terminal events 纳入 WAVE_TRANSITION contract；battle_state_transition 的 typed global_flags changes 是另一责任边界，不能将它当成 monster phase 或 wave spawn 的统一原始机制。

### 9.2 S：原始图给到哪一步

S7/S9 提供实际声明链：WaveMonster、dark-team passive、出生后 bindings、TriggerModifierEnterBattle；`DarkTeamDestroyCheck(ForWaveEnd=true)` 后 `ByCompareWaveCount(Equal,CompareWithMax=true)`，成功进入 `Stage_PreLocalWin`，失败调用 `TriggerNextWave` 参数序列。S7 的 Stage_Wave1End/Stage_Wave2End 等序列实际引用两个 Wave_Common templates。

S7 终局 graph 还包含：

```text
lose predicates (ByLevelLoseCheck / ByCheckTrialCharacterDie / additional conditions)
 -> Stage_PlayerTeamDie -> Stage_WriteLocalLose
 -> SetBattleResult [IsWin field absent in this serialized lose task]
 -> TriggerModifierLeaveBattle

Stage_PreLocalWin -> guarded SetLocalWinFlag -> Stage_WriteLocalWin
 -> SetBattleResult(IsWin=true) -> TriggerModifierLeaveBattle

independent WaitAndProcessBattleResult
```

guard 中有 ByContainCustomString hash `-1148494254` 及 lose/trial 检查；没有解码该 hash 的完整业务含义，不将其条件删掉。lose task 的 IsWin **未序列化**，不得伪写为 raw `false`。S 给出可辨识的控制结构和 terminal operations，但没有导出这些 native predicates/dispatcher/result-processing 的方法体。

I：primary 103201 有且只有一波。以**假设已合法构造的** BattleState 为输入，active ally 存在、queue 空、三个 current IDs 均 present 但不 active、无额外 active blocker，则 K 的 next_index=1 >= wave_count=1，选择 final victory/completed；这与 S 的末波比较/胜利结果声明有结构对齐。**不是 §7 已阻断的真实出生到胜利执行，也没有给 primary 虚构第二波。**

G：S 的 dying/turn-end/result guards 与 K pending queue/active predicate 不能直接逐字等价；`battle.victory/defeat/completed` 的本地事件命名、exact ordering、simultaneous defeat priority 和 leave-battle dispatch 并未由 native body 闭合。必须同时保留“source 已有终局声明”和“native 实现仍未导出”，不能混成 source 完全不存在。

## 10. Phase / new spawn / wave respawn / reinforcement discriminator

复用已有 ordinary Sam anchor，并按 pin 读取 S10：`Monster_W3_Sam_00_Passive01` 的 `Monster_W3_Sam_00_AIChange` modifier，`OnEndBreak` 在 `ModifierOwnerEntity` 上 AddModifier(WeakPointProtected) 后调用 `CharacterChangePhase(RevertToDefault=true)`。目标仍是已有 owner，不是新的 MonsterID/slot allocation。

S9 `Monster_ChangePhase` 模板同样对 Caster 执行 ExitBreakState、记录 MaxHP dynamic value、SetHP(ModifyRatio=1)、ResetStance/SetStanceCount，并暂挂 ChangephaseMark、触发 modifier custom event、移除 mark。`RefreshChangePhaseUI` 单独排为 presentation-only；SetStanceCount 的缺省值不猜测。这个 task list 没有 WaveMonster 或新 birth request。

| 概念 | 本轮可证 discriminator | 不可混淆的边界 |
| --- | --- | --- |
| same-entity phase mutation | Sam OnEndBreak / shared ChangePhase 的 owner/Caster target | 不分配新 wave entry；HP/stance 重置不等于复活或创建另一实例 |
| new monster spawn | K UnitSpawnRequest + UnitBirthTemplateIR + 新 unit_id；S WaveMonster 明示 creation operation | 不是调用 CharacterChangePhase |
| next-wave / wave respawn | K 清旧波、递增 wave_index、按新 entries 产生新实例；S Wave_Common graph | 即使 MonsterID 重复，wave/slot identity 仍不同；不是原实例 phase |
| delayed creation / reinforcement | S9 TaskList_WaveMonsterDelayCreate 由 ByContainMonsterOnWave(CreateTiming=DelayCreate,AfterWave=true) 控制，然后 WaveMonster(CreateTiming=DelayCreate) | 声明了有条件的 delayed spawn，不自动递增 wave，也不等同 phase；“reinforcement” 的具体 owner/参与 roster 需独立引用证据 |

primary 是低噪声 configured-wave chain，本轮不向其强加 phase/reinforcement。没有声称 DelayCreate 分支在 103201/301001 必然触发；其中序列化 MonsterList=[] 也不能推出不生成单位，因为其 table/timing reader 是另一个契约。具体 ordinary reinforcement caller 的全链未在本轮闭合；这是保留项，不通过新开怪物大范围调查硬凑覆盖。

## 11. A / B / C / D / E matrix

| 面向的事实 / 行为 | A: source-facing | B: export/engine gap | C: current implementation | D: source-aligned | E |
| --- | --- | --- | --- | --- | --- |
| selected Stage/wave count/order/slots/monster IDs | closed for A/B anchors | 不影响原始 roster 事实 | WaveDefinition/Entry builder 已读 | 手工逐身份对齐；不是生成物验收 | not run |
| normal Monster -> Template / Hard inputs | closed for selected IDs/rows | native stat arithmetic/precedence frozen | profile + wave builder 已读 | identity/transport 有限对齐；不含最终 native formula | not run |
| Unique participation | selected chains 排除；图片命中已区分 | 不外推其他 ID | normal/unique dictionary 行为已读 | selected normal row 参与相符 | not run |
| wave birth fields / request identity | S 输入已列全；K conventions 显式 | HP/energy/AV/native formula 非全 S | template/plan/to_unit 均在 | **完整 materialization 不成立：R6-G01** | not run |
| Stage301001 ability owner/callback/consequence | S8 graph closed | native loader/dispatcher/evaluator body 未闭合 | wave refs 保存；完整执行未验证 | 仅 reference transport；不宣称行为 D | not run |
| wave clear -> next / final victory | source graph 分支已解析 | native clear/queue/result guards | WaveSystem 已读 | primary final-wave 结构性、条件性对齐 | not run |
| defeat / completed | lose/win/result/leave 声明可见 | 缺省 IsWin、native processing、local event mapping | local defeat + common completed 已读 | 部分概念对齐，非 native exact ordering | not run |
| same-entity phase versus spawn | Sam/shared template 已区分 | 具体 reinforcement 完整 owner 链保留 | phase/global/wave/spawn 消费者责任已分开 | 不把不同机制合并；未证明完整 phase runtime | not run |

## 12. False friends / gaps / exit accounting

| ID | 类别 / 处置 |
| --- | --- |
| R6-G01 | **实际 K/K interface mismatch**：rank source trace 缺 evidence，严格 consumer 拒绝；独立 lowering/runtime 修复卡，保持 gate，不在本 PR 改代码 |
| R6-G02 | S 已有 base/ratio，native configured-stat arithmetic、flat placement、clamp、rounding 仍 B；不继续搜索同 dump 隐藏方法 |
| R6-G03 | Stage-vs-Monster HardLevel/Elite precedence 未证明；K 使用 Stage Hard、未在 inspected birth 应用 Stage Elite 不是 native 规则 |
| R6-G04 | StageAbility refs/LevelGraph/conditions 的运输与动态安装有边界；§8 graph 不是 current runtime E |
| R6-G05 | declared count mismatch fail-closed；malformed inner-wave/slot 和 stage omission 的总入口验证未执行，不能声称全结构 fail-closed |
| R6-G06 | native termination predicates/dispatcher/result body、local completed 对应关系仍 G；不能以 K 补 S |
| R6-G07 | first-wave panel round trip、完整 monster card/AI admission、实际 reinforcement caller 与出生后链未验证 |

明确排除：`ILHardLevelGroup.json` 是 RtBattle/IL false friend，不是 ordinary difficulty；Unique family 存在不代表 selected row 参与；unique template 图片 ID 不是 join；同名 RPG.GameCore.MonsterConfig 不等于 ExcelOutput/MonsterConfig；phase HP/stance reset 不等于 new spawn；camera/animation/presentation wait 不替代 battle callback；“executable” coverage 标记不等于 runtime_verified。

对执行卡 exit conditions 的核对：Stage -> 真正 builder/entry 身份、一个真实 monster -> birth template、字段来源/约定分类、ordinary HardLevel、conditional Unique、StageAbility graph、条件性清波/末波对照、defeat/completed contract、phase/spawn 区分、A–E matrix、false friends 均已有可复查记录。**真实成功的 birth -> UnitState 仍被 R6-G01 阻断，reinforcement 动态 owner 链未补造，因此不机械宣布全部 exit requirements 合格。** W14/W16 全局 checklist 不勾为 mechanism_closed。

## 13. Validation / handoff

- Actual reads：所有参与 raw 声明均 exact pin；所有 K consumers 均 exact input head。S1/S2 大表以 exact blob 成功回读；StageAbility 候选定位后重新 pin-read。查找无结果/空 content 均未冒充不存在证明。
- Identity checks：手工逐项核对 Stage -> wave/slot -> MonsterID -> explicit MonsterTemplateID；HardLevel composite key；重复实例与 shared template；request/trace fields；source-proof 失败调用链。
- Numerical/document checks：仅对本记录的候选算术、固定 revision、Markdown 结构和 allowed documentation paths 做静态检查；不是 compiler/runtime tests。
- Runtime/validator：未运行 simulator、CombatExecutor、pytest 或生产 Direct；没有导出实际 UnitState/胜负轨迹；不标 E。
- External corroboration：未做 live/gameplay 外部校验；本轮版本断言限定 pinned TBGD 与 K，不用攻略补 native 空白。
- Git/CI：最终实际 commit、parent、changed files、PR head、Draft 与 CI 状态写在本 PR 顶层 checkpoint；不能将 skipped 写为 passed。记录中的 input_head 始终指研究时 kernel 基线，不伪写未来 commit。

**Next**：停止在 R6；将 R6-G01 的精确 producer/consumer 不一致交回 integration/planning，另立受控修复/验证卡。完成修复后只补必要 materialization/transition 验证和本记录状态，不重做已闭合 raw tracing。不自动进入 R7。

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/StageConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterConfig.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/HardLevelGroup.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterUniqueConfig.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateUniqueConfig.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/Level/StageCommonTemplate.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Level/Level_MazeChallengeBuff_Ability.json
[S9]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[S10]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_W3_Sam_00_Ability.json
[S11]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[K-lowering]: https://github.com/yaelysia/hsr-battle-simulator/blob/65932e3f42b216c5a61fbbdfdd7237f46a6c30cd/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
[K-spawn]: https://github.com/yaelysia/hsr-battle-simulator/blob/65932e3f42b216c5a61fbbdfdd7237f46a6c30cd/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/unit_spawn.py
