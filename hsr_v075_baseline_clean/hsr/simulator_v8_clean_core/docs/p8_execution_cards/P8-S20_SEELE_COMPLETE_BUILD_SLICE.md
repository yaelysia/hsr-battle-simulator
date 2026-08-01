# P8-S20 希儿完整装备构筑纵切执行卡

## 执行配置

- 对应问题：P8-I18，并端到端复核 P8-I03 至 I16。
- 硬前置：P8-S19 已验收；当前 RuleBook 中希儿、光锥 23001、套装 108/309 及下列六个五星模板均可正式装配。角色完整动作图属于后续角色卡内容闭合，不作为装备阶段前置。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，集成 worktree 串行执行。
- 选择理由：这是固定参考实例，但要同时核对合法 roll、面板、动态条件、来源和 replay；需要人工审查证据，不能用 Goal 模式以“跑通”为目标降低口径。

## 当前事实与阶段结果

本阶段只建立一个正式 example manifest，不新增希儿、光锥或套装规则。固定 ID 只允许出现在本卡、example manifest、focused validator 和报告中：希儿 `AvatarID=1102`，光锥《于夜色中》`EquipmentID=23001`，外圈“繁星璀璨的天才”`SetID=108`，内圈“繁星竞技场”`SetID=309`。生产 lowering、RuleBook、assembler 和 runtime 不得出现这些特判。

完成后，同一 manifest 经 S19 正式 API 导入，生成 80 级 E0 希儿、80 级晋阶 6 叠影 1《于夜色中》和六件 +15 五星遗器；所有定义和数值由 RuleBook/assembler 解析。构筑可进入战斗，装备 provider 完成正式注册，并验证速度分档、暴击门槛、量子弱点分支、来源审计和 replay。删除 example 文件不改变 core 行为。

## 版本化示例 Manifest

以下是执行阶段必须落成机器可读 JSON 的选择。`template_id/group_id/affix_id` 是当前 TBGD 的审计锚点，导入时仍通过类型化 RuleBook key 解析；禁止直接使用 raw row 计算规则。

### 角色与光锥

```text
character: AvatarID 1102, level 80, promotion 6, eidolon 0
traces: 本阶段不选择尚未准入的角色行迹或技能等级节点；不用“默认满级”伪造角色卡闭合
light cone: EquipmentID 23001, level 80, promotion 6, superimposition 1
```

### 六件遗器

所有遗器 `rarity=5`、`level=15`、`SubAffixGroup=5`，并直接输入养成完成后的四条副词条。`count` 和 `step` 只表达成品副词条的最终档位与精确数值，验证器只核对数量、属性、取值范围和最终值；不还原初始词条、强化次数或强化节点。若 S12 的成品输入契约与此定义不一致，必须先修订本卡，不能静默改 manifest。

| 实例 | 模板/槽位 | 主词条 | 副词条 `(AffixID, property, count, step)` |
|---|---|---|---|
| `seele-genius-head-v1` | 61081 / HEAD | `(51,1) HPDelta` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,2,2)`；`(7,SpeedDelta,3,1)`；`(8,CriticalChanceBase,1,1)` |
| `seele-genius-hand-v1` | 61082 / HAND | `(52,1) AttackDelta` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,3,3)`；`(8,CriticalChanceBase,1,1)`；`(4,HPAddedRatio,2,2)` |
| `seele-genius-body-v1` | 61083 / BODY | `(53,4) CriticalChanceBase` | `(9,CriticalDamageBase,4,4)`；`(5,AttackAddedRatio,3,3)`；`(4,HPAddedRatio,1,1)`；`(12,BreakDamageAddedRatioBase,1,1)` |
| `seele-genius-foot-v1` | 61084 / FOOT | `(54,2) AttackAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,3,3)`；`(4,HPAddedRatio,2,2)` |
| `seele-rutilant-orb-v1` | 63095 / NECK | `(55,9) QuantumAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,2,2)` |
| `seele-rutilant-rope-v1` | 63096 / OBJECT | `(56,4) AttackAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,3,3)`；`(4,HPAddedRatio,2,2)` |

按当前 SubAffixGroup 5 精确值，该 manifest 的速度副词条为 `6.3`，战斗外速度预期为角色基础速度加该固定值；《于夜色中》档位必须由 runtime 当前速度计算。五条单次中档暴击率副词条合计约 `14.58%`，配合角色基础、叠影 1 光锥 `18%`、暴击率躯干和繁星竞技场静态 `8%`，用于稳定跨过当前 `70%` 条件。上述百分比只用于独立 oracle，不可写回 manifest 作为最终值。

## 本阶段只做

- 新增版本化 example manifest，引用正式角色卡、光锥定义、遗器模板和 affix 实例，不复制规则。
- 用 S19 查询/提交 API 导入并输出完整 assembly ledger、final panel、provider 和 battle admission。
- 证明六件 roll 合法且最终暴击率在 75%-85%、暴击伤害至少 160%、战斗外攻击至少 2900；目标只用于验收结果，不是输入。
- 用同一正式出生状态的受控 runtime 速度切片验证《于夜色中》档位随当前速度变化；该切片不冒充希儿战技动作已闭合。
- 验证繁星竞技场静态暴击率与 70% 条件伤害分离；阈值以下反例只关闭条件伤害。
- 验证天才套二件量子伤害、四件基础防御无视及敌人有量子弱点时额外分支。
- 经正式场景构建和 provider 注册生成 snapshot/replay；装备阶段不伪造或修补尚未闭合的希儿角色动作图。
- 生成受控反例：降低暴击率、拆一件外圈、拆一件内圈、敌人无量子弱点；只改变对应机制。

## 本阶段不做

- 不自动配装、评分、最大化伤害或注册角色默认 preset。
- 不创建 sample-only IR、手工 modifier、手工伤害修正或验证 metadata 效果。
- 不修改角色卡/装备公式来满足目标面板；若目标不成立先审查 manifest 和来源。
- 不用一张面板截图或最终伤害替代 ledger、条件决策和来源证据。
- 不以该示例通过宣称全装备完成；S21 负责当前源码全量聚合。

## 端到端不变量

1. manifest 只包含选择和实例 roll，不包含 final panel、active flag、档位、伤害或 settlement。
2. 所有固定 ID 仅存在于 example/validator/report，通用代码扫描必须为零。
3. 六件实例分别通过 S10-S12，套装激活通过 S13，静态/动态机制通过 S14-S19；无旁路。
4. 光锥速度档位、繁星竞技场条件和量子弱点分支读取 runtime 当前状态，不读取 manifest 中的派生结果。
5. 只影响公式的机制用 calculation/condition decision 审计，不强行伪造 mutation。
6. snapshot/replay 锁定 manifest/source/IR/engine rule fingerprint；受控反例使用派生新 manifest。
7. 删除 example manifest 后 production behavior 和全局目录 fingerprint 不变。
8. 希儿普攻、战技和终结技的完整动作图由后续角色卡内容阶段闭合；S20 不得把演出节点兼容或角色技能 lowering 混入装备实现。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| manifest 真实合法 | 六模板、主词条和 24 条成品副词条均由 RuleBook/oracle 重算 | legality matrix |
| 最终面板可重算 | 每个 term 可追溯，目标区间由 ledger 得出而非反填 | assembly ledger + oracle |
| 三套装备机制生效 | 《于夜色中》、天才 2/4 件、竞技场静态/条件均有真实决策/settlement | mechanism matrix |
| 正式运行边界 | 正式场景构建、provider 注册和构筑锁定均成功，不依赖角色动作 fixture | runtime boundary evidence |
| 分支隔离 | 四个受控反例只改变对应 term/provider/condition | counterfactual matrix |
| 来源闭合 | 静态 term 与三类动态 decision 完整 walkback | audit samples |
| replay 可信 | assembly、初态、每次 transition 精确回放 | replay summary |
| 无特判 | 通用代码无固定 ID/名称，删除 example 不改行为 | static scan + deletion probe |

## 拟改文件与关键符号

- 新增 `scenarios/examples/p8_s20_seele_complete_equipment_build.json` 或项目现有正式 example 目录的等价文件。
- 新增 `tools/validate_p8_s20_seele_complete_build_slice.py`。
- `live_validation_reports/v8_p8_s20_seele_complete_build_slice_ready_for_review.md`。
- 只允许为暴露已存在 bug 做最小通用修复；若涉及 S18/S19 契约或装备机制，必须停止并退回对应阶段，不在示例 validator 补逻辑。

## 结构化验收谓词

```text
manifest_contains_choices_not_results=true
all_definition_refs_resolve_current_rulebook=true
six_relic_instances_legal=true
all_final_sub_affix_values_legal=true
outer_four_and_planar_two_active=true
final_panel_reconstructs_from_ledger=true
crit_rate_target_met_without_override=true
crit_damage_target_met_without_override=true
attack_target_met_without_override=true
in_the_night_speed_tiers_runtime_driven=true
rutilant_threshold_runtime_driven=true
genius_quantum_weakness_branch_runtime_driven=true
formal_scene_and_provider_registration_succeed=true
controlled_negatives_isolated=true
static_and_dynamic_sources_walk_back=true
assembly_and_transitions_replay_equal=true
production_fixed_example_ids=0
deleting_example_changes_core_behavior=false
```

## Gap 与停止条件

- manifest 不合法：先按 S10-S12 定位，不允许改 validator 期望或手填最终值。
- 某装备完整图 blocked：退回 S8/S17，S20 不做局部绕过。
- 希儿角色动作图的现有 blocker：记录为外部角色卡内容依赖，不在 P8 修复，也不影响装备构筑纵切通过；不得用 kernel fixture 冒充角色动作闭合。
- 目标区间与真实来源冲突：审查当前版本参数、行迹和 roll 选择；需要改 manifest 时必须更新本卡和依据，不静默调整。
- 通用接口不足：退回 S18/S19 修复并重新验收，不在 example 加专用入口。

## 验证命令与资源

生产边界先保证：manifest loader、正式装配、场景构建、provider 注册和 replay API 各自在自身边界拒绝非法构筑、派生结果、过期选择和篡改证据。S20 验证器只消费这些正式入口，不复制 S18 面板算法或 S19 replay 逻辑。

本阶段固定只运行一个业务主验证：

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s20_time_v.txt timeout --signal=TERM 10m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s20_seele_complete_build_slice --tbgd-root ../../turnbasedgamedata-main --manifest simulator_v8_clean_core/scenarios/examples/p8_s20_seele_complete_equipment_build.json --output-dir /tmp/hsr_v8_p8_s20_seele_complete_build_slice
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s20_pycache python3 -m compileall -q simulator_v8_clean_core
git diff --check
```

- 主验证复用一次当前 RuleBook，只执行正式场景/provider 注册和四个受控反例；S18/S19 已验收结论作为前置继承，禁止再次运行其整体验证器。
- 若示例暴露 core 缺陷，立即停止并退回最早责任阶段修复和验收；S20 不顺手修改通用内核，因此默认没有额外 direct 套餐。
- 完整主验证最多一次诊断运行和一次最终运行；中间只运行失败的 manifest/route/negative 切片。
- 单次主验证预算：墙钟 10 分钟、峰值 RSS 1 GiB；阶段累计验证预算 20 分钟；默认产物不超过 10 MiB。超限立即暂停。
- 默认只输出 manifest、ledger summary、关键 settlement、condition matrix 和 replay 摘要，不写完整 RuleBook/全 transition；不运行 S18、S19、S21、阶段聚合或 `validate_v0_209`。

## Ready-for-review 产物

- 机器可读 manifest、24 条成品副词条的独立数值与合法性 oracle。
- assembly ledger、最终面板重算、provider 注册和关键阶段顺序。
- 光锥/两个套装的 condition/settlement、四个反例和完整来源反查。
- snapshot/replay、固定 ID 静态扫描、删除 example 行为不变证据。
- 攻略仅作选型说明，TBGD/IR 才是规则来源。

## 唯一执行清单（仅验收线程可勾）

- [x] 版本化 manifest 与本卡一致，六件遗器和 24 条成品副词条可独立重算。
- [x] 正式装配得出目标面板，无 final value/active flag/fixture override。
- [x] 《于夜色中》、天才套和竞技场的静态/动态/条件分支均按 runtime 当前值执行。
- [x] 正式场景、provider 注册、构筑锁定与 replay 成功，不借用角色动作 fixture。
- [x] 四个受控反例只影响对应机制，来源 walkback 和 replay 完整。
- [x] 固定 ID 仅在 example/validator/report，无 sample-only core 路径。
- [x] `ready_for_review` evidence 和资源审计完整；未用重跑 S18/S19 代替本阶段正式入口证明。
