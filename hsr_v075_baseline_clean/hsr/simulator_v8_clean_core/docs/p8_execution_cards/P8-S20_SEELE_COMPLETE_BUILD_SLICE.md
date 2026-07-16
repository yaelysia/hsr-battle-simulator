# P8-S20 希儿完整装备构筑纵切执行卡

## 执行配置

- 对应问题：P8-I18，并端到端复核 P8-I03 至 I16。
- 硬前置：P8-S19 已验收；当前 RuleBook 中希儿、光锥 23001、套装 108/309 及下列六个五星模板均可正式装配和执行。
- 推荐模型：5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通聚焦模式，集成 worktree 串行执行。
- 选择理由：这是固定参考实例，但要同时核对合法 roll、面板、动态条件、动作、来源和 replay；需要人工审查证据，不能用 Goal 模式以“跑通”为目标降低口径。

## 当前事实与阶段结果

本阶段只建立一个正式 example manifest，不新增希儿、光锥或套装规则。固定 ID 只允许出现在本卡、example manifest、focused validator 和报告中：希儿 `AvatarID=1102`，光锥《于夜色中》`EquipmentID=23001`，外圈“繁星璀璨的天才”`SetID=108`，内圈“繁星竞技场”`SetID=309`。生产 lowering、RuleBook、assembler 和 runtime 不得出现这些特判。

完成后，同一 manifest 经 S19 正式 API 导入，生成 80 级 E0 希儿、80 级晋阶 6 叠影 1《于夜色中》和六件 +15 五星遗器；所有定义和数值由 RuleBook/assembler 解析。构筑可进入战斗，完成普攻、战技、终结技路线，验证速度分档、暴击门槛、量子弱点分支、来源审计和 replay。删除 example 文件不改变 core 行为。

## 版本化示例 Manifest

以下是执行阶段必须落成机器可读 JSON 的选择。`template_id/group_id/affix_id` 是当前 TBGD 的审计锚点，导入时仍通过类型化 RuleBook key 解析；禁止直接使用 raw row 计算规则。

### 角色与光锥

```text
character: AvatarID 1102, level 80, promotion 6, eidolon 0
traces: 当前已准入的 source-backed 完整静态/动态节点；技能等级显式记录，不使用“默认满级”
light cone: EquipmentID 23001, level 80, promotion 6, superimposition 1
```

### 六件遗器

所有遗器 `rarity=5`、`level=15`、`SubAffixGroup=5`、初始四副词条。每件四个初始 roll 加五次强化，总 `count=9`。`step` 是每次 roll 档位索引的累计值；除速度特别注明外，下面均以中档 witness `[1, ...]` 实现。若 S12 验收后的规范语义与此定义不一致，必须在编码前交回规划线程修订本卡，不能静默改 manifest。

| 实例 | 模板/槽位 | 主词条 | 副词条 `(AffixID, property, count, step)` |
|---|---|---|---|
| `seele-genius-head-v1` | 61081 / HEAD | `(51,1) HPDelta` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,2,2)`；`(7,SpeedDelta,3,1)`；`(8,CriticalChanceBase,1,1)` |
| `seele-genius-hand-v1` | 61082 / HAND | `(52,1) AttackDelta` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,3,3)`；`(8,CriticalChanceBase,1,1)`；`(4,HPAddedRatio,2,2)` |
| `seele-genius-body-v1` | 61083 / BODY | `(53,4) CriticalChanceBase` | `(9,CriticalDamageBase,4,4)`；`(5,AttackAddedRatio,3,3)`；`(4,HPAddedRatio,1,1)`；`(12,BreakDamageAddedRatioBase,1,1)` |
| `seele-genius-foot-v1` | 61084 / FOOT | `(54,2) AttackAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,3,3)`；`(4,HPAddedRatio,2,2)` |
| `seele-rutilant-orb-v1` | 63095 / NECK | `(55,9) QuantumAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(5,AttackAddedRatio,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,2,2)` |
| `seele-rutilant-rope-v1` | 63096 / OBJECT | `(56,4) AttackAddedRatio` | `(9,CriticalDamageBase,3,3)`；`(8,CriticalChanceBase,1,1)`；`(2,AttackDelta,3,3)`；`(4,HPAddedRatio,2,2)` |

生成历史 witness：每个属性先出现一次；`count-1` 是五个强化节点分配数。一般项目每个 roll 使用 step tier 1，因此累计 `step=count`；头部速度使用 tiers `[1,0,0]`，得到 `count=3, step=1`。验证器必须用 S12 的独立 feasibility oracle 重新证明，不得因为本卡声明而信任。

按当前 SubAffixGroup 5 精确值，该 manifest 的速度副词条为 `6.3`，战斗外速度预期为角色基础速度加该固定值；施放战技后的速度和《于夜色中》档位必须由 runtime 当前值计算。五条单次中档暴击率副词条合计约 `14.58%`，配合角色基础、叠影 1 光锥 `18%`、暴击率躯干和繁星竞技场静态 `8%`，用于稳定跨过当前 `70%` 条件。上述百分比只用于独立 oracle，不可写回 manifest 作为最终值。

## 本阶段只做

- 新增版本化 example manifest，引用正式角色卡、光锥定义、遗器模板和 affix 实例，不复制规则。
- 用 S19 查询/提交 API 导入并输出完整 assembly ledger、final panel、provider 和 battle admission。
- 证明六件 roll 合法且最终暴击率在 75%-85%、暴击伤害至少 160%、战斗外攻击至少 2900；目标只用于验收结果，不是输入。
- 验证战技前后《于夜色中》速度档位，实际 task 顺序决定战技本次结算读取提升前还是提升后速度。
- 验证繁星竞技场静态暴击率与 70% 条件伤害分离；阈值以下反例只关闭条件伤害。
- 验证天才套二件量子伤害、四件基础防御无视及敌人有量子弱点时额外分支。
- 经正式 action query/submit 完成含普攻、战技、终结技的合法路线并 snapshot/replay。
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
4. 战技速度 buff、光锥档位、繁星竞技场条件和量子弱点分支读取 runtime 当前状态。
5. 只影响公式的机制用 calculation/condition decision 审计，不强行伪造 mutation。
6. snapshot/replay 锁定 manifest/source/IR/engine rule fingerprint；受控反例使用派生新 manifest。
7. 删除 example manifest 后 production behavior 和全局目录 fingerprint 不变。

## 目标与证据映射

| 目标 | 通过条件 | 证据 |
|---|---|---|
| manifest 真实合法 | 六模板、主词条、24 条副词条和 roll history 全由 RuleBook/oracle 重算 | legality matrix |
| 最终面板可重算 | 每个 term 可追溯，目标区间由 ledger 得出而非反填 | assembly ledger + oracle |
| 三套装备机制生效 | 《于夜色中》、天才 2/4 件、竞技场静态/条件均有真实决策/settlement | mechanism matrix |
| 合法动作链 | query 返回并 submit 普攻/战技/终结技，transition committed | route evidence |
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
all_sub_affix_histories_feasible=true
outer_four_and_planar_two_active=true
final_panel_reconstructs_from_ledger=true
crit_rate_target_met_without_override=true
crit_damage_target_met_without_override=true
attack_target_met_without_override=true
in_the_night_speed_tiers_runtime_driven=true
rutilant_threshold_runtime_driven=true
genius_quantum_weakness_branch_runtime_driven=true
basic_skill_ultimate_route_uses_query_submit=true
controlled_negatives_isolated=true
static_and_dynamic_sources_walk_back=true
assembly_and_transitions_replay_equal=true
production_fixed_example_ids=0
deleting_example_changes_core_behavior=false
```

## Gap 与停止条件

- manifest 不合法：先按 S10-S12 定位，不允许改 validator 期望或手填最终值。
- 某装备完整图 blocked：退回 S8/S17，S20 不做局部绕过。
- 希儿角色卡已有真实 blocker：分类为角色卡前置缺口，不能用 kernel fixture；报告后停止。
- 目标区间与真实来源冲突：审查当前版本参数、行迹和 roll 选择；需要改 manifest 时必须更新本卡和依据，不静默调整。
- 通用接口不足：退回 S18/S19 修复并重新验收，不在 example 加专用入口。

## 验证命令与资源

```bash
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s20_seele_complete_build_slice --tbgd-root ../turnbasedgamedata-main --manifest hsr/simulator_v8_clean_core/scenarios/examples/p8_s20_seele_complete_equipment_build.json --output-dir /tmp/hsr_v8_p8_s20_seele_complete_build_slice
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s18_final_panel_and_birth_order --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s20_s18_panel_regression
PYTHONDONTWRITEBYTECODE=1 python3 -B -m hsr.simulator_v8_clean_core.tools.validate_p8_s19_query_audit_snapshot_replay --tbgd-root ../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s20_s19_replay_regression
PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/hsr_v8_p8_s20_pycache python3 -m compileall -q hsr/simulator_v8_clean_core
git diff --check
```

复用一次当前 RuleBook，主验证只执行一条短路线和四个受控反例；默认输出 manifest、ledger summary、关键 calculation/settlement、condition matrix 和 replay 摘要，不写完整 RuleBook/全 transition。不得运行 S21 全装备聚合。

## Ready-for-review 产物

- 机器可读 manifest、24 条副词条独立 oracle 和合法 history witness。
- assembly ledger、最终面板重算、动作路线和关键阶段顺序。
- 光锥/两个套装的 condition/settlement、四个反例和完整来源反查。
- snapshot/replay、固定 ID 静态扫描、删除 example 行为不变证据。
- 攻略仅作选型说明，TBGD/IR 才是规则来源。

## 唯一执行清单（仅验收线程可勾）

- [ ] 版本化 manifest 与本卡一致，六件遗器和全部 roll 可独立还原。
- [ ] 正式装配得出目标面板，无 final value/active flag/fixture override。
- [ ] 《于夜色中》、天才套和竞技场的静态/动态/条件分支均按 runtime 当前值执行。
- [ ] 普攻、战技、终结技通过正式 query/submit，顺序与 settlement 正确。
- [ ] 四个受控反例只影响对应机制，来源 walkback 和 replay 完整。
- [ ] 固定 ID 仅在 example/validator/report，无 sample-only core 路径。
- [ ] `ready_for_review` evidence、回归和资源审计完整。
