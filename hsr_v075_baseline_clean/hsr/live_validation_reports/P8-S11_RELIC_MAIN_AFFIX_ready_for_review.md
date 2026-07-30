# P8-S11 主词条合法池与精确数值 ready_for_review（验收差量修复后）

## 状态

- 阶段：`P8-S11`
- 结论：`ready_for_review`（首轮验收 4 项阻断已全部修复并复验）
- 基线检查点：`04dbd8a5a1251df7e945cf1d289883c8f60e7579`
- Checklist：未勾选
- Git 提交：未创建
- 后续阶段：未进入 `P8-S12`

## 验收阻断修复映射

1. **来源快照不一致崩溃 → 结构化 blocked（已修）**
   - `admit_relic_main_affix` 在构造计算结果前预检四路来源指纹一致性；不一致
     返回 `relic_main_affix_source_fingerprint_mismatch` 诊断，装配 blocked、
     正式通道全空，不抛异常。负例 `source_fingerprint_mismatch` 证明
     `crashed=false` 且诊断精确。

2. **稀有度/分组一致性进入生产契约（已修，属执行卡预留的 lowering_gap 回修）**
   - `tbgd/relic_cards.py` 新增 `_project_main_group_rarities`：从真实
     RelicConfig 模板行投影每个主词条组的可用稀有度集合，不解析固定 ID。
   - `RelicMainAffixGroupDefinitionIR` 新增类型化 `rarity_types`（codec 同步；
     S1 fixture 构造点已迁移，fixture codec round-trip 复验通过）。
   - 引用闭包校验新增 `relic_template_main_group_rarity_ambiguous` /
     `relic_template_main_group_rarity_mismatch`：稀有度污染模板在 RuleBook
     解析层即 `equipment_definition_reference_closure_invalid`。
   - 计算器强制 `len(rarity_types)==1` 且 `template.rarity` 匹配
     （`relic_main_affix_group_rarity_ambiguous` / `_mismatch`），直接探针复验。

3. **计算器身份闭合（已修）**
   - 计算前先核对 `instance.template_key == template.key`、
     `instance.slot_key == template.slot_key`、
     `slot_definition.key == template.slot_key`、解析组身份等于模板声明组；
     三类失配各有独立 reason 并被定向探针验证，纯函数可安全复用于 S12/S14。

4. **oracle 独立规范化（已修）**
   - 验证器不再导入生产 `canonical_decimal`；raw 读取（parse_float=Decimal）、
     公式计算与最终规范化均为验证器内部实现，并附带 6 例规范化自测
     （指数/尾零/负零/整数形态）。

## 生产改动汇总

1. `equipment/models.py`
   - `RelicMainAffixComputation`：四路 key/来源、Decimal 精确值、linear_growth
     依据、computation_fingerprint、exact-field codec。
   - `RelicAssemblySelection.main_affix`；affix 状态
     `main_affix_validated_sub_affix_deferred_to_s12`；blocker reason
     `relic_sub_affix_validation_deferred_to_s12`。
   - `RelicMainAffixGroupDefinitionIR.rarity_types` 及引用闭包稀有度校验。
2. `tbgd/relic_cards.py`：group→rarity 真实模板关联投影（lowering 回修）。
3. `builds/relic_affix_calculator.py`（新增）：身份闭合 → 等级 → 解析 →
   group/rarity → 部位池 → 指纹预检 → Decimal 计算，逐层 fail-closed。
4. `builds/equipment_assembler.py`：接线计算器；非法主词条装配 blocked 零贡献。
5. `tools/validate_p8_s1_equipment_type_contract.py`：fixture group 构造点补
   `rarity_types`（schema 迁移，S1 不端到端装配遗器，行为不变）。
6. 未改动：rulebook（S9 窄查询足够）、runtime/ScenarioStateBuilder、S9/S10
   验证器。

## 验收谓词

主验证 16/16 通过（12 项执行卡谓词 + 4 项阻断修复谓词）：

```text
six_real_slot_pools_non_empty=true
main_affix_requires_slot_and_template_group=true
fixed_head_hand_are_source_derived=true
cross_slot_main_affixes_rejected=true
template_group_restriction_enforced=true
level_zero_mid_max_match_independent_oracle=true
numeric_values_never_pass_through_float=true
display_projection_not_rule_input=true
user_final_value_rejected=true
ambiguous_affix_definition_blocked=true
all_results_source_backed=true
blocked_main_affix_contributes_nothing=true
source_fingerprint_mismatch_blocked=true
group_rarity_enforced_in_production=true
calculator_identity_closure_enforced=true
numeric_oracle_independent_of_production_code=true
```

证据要点：

- 六槽合法池三层动态交叉，typed pool 与独立 raw `ValidPropertyList` 一致；
  HEAD/HAND 固定属性来源推导，无特殊分支。
- 端到端正例 28 例 + 720 个已发布 BASIC 模板全定义 admission。
- 跨槽 30 例端到端 `relic_main_affix_not_in_template_group`；部位池防御 28 例
  `relic_main_affix_property_not_allowed_for_slot`。
- 数值 oracle：112 个 BASIC group 词条 × +0/中/满级共 336 点逐字段一致；
  rarity→MaxLevel 全目录唯一。
- 生产加固负例 7 例：指纹混合不崩溃且精确 blocked、稀有度污染端到端
  reference 闭包 blocked、计算器 rarity mismatch/ambiguous 直探、三类身份
  失配直探。
- 来源反查 112 词条 + 六槽模板/部位关系行全部 backed；指纹确定且两两不同。
- 全部端到端负例正式通道为空，无 `exact_value`/`set_count` 泄漏。

## 验证记录

| 验证 | 结果 | 墙钟 | 峰值 RSS |
|---|---|---:|---:|
| `compileall`（bytecode 定向 `/tmp`） | 通过 | — | — |
| 主验证最终运行 | 16/16，退出码 0 | 2.875 s | 100,940 KiB |
| S10 level-mode 小型 direct | ok=True | 3.912 s | 100,832 KiB |
| `git diff --check` | 通过 | — | — |

说明：

- 宿主为 Windows Git Bash，无 `/usr/bin/time -v`/`ionice`；计量用等效 ctypes
  PeakWorkingSetSize 包装器，`nice -n 15` 保留。TBGD 实际检出位于
  `/home/zhangjinhao/code/hsr/turnbasedgamedata-main`。
- S9 主验证在本宿主不可运行（其验证器 `import resource` 为 Unix 专用），未作为
  direct；S9  lowering 与引用闭包的变更由 S11 主验证（全目录 720 模板零新增
  reference issue、全部 resolved）与 S10 slice 端到端覆盖。
- 主验证单次 2.875 s / 约 99 MiB（上限 5 分钟 / 768 MiB）；产物合计 120,801
  bytes（12 个 JSON，上限 3 MiB）；验证器 898 非空行（上限 900）。
- 未运行 S10 完整主验证、scenario direct、S9 及任何历史/聚合验证。
- 范围外临时产物 `.workbuddy/` 与 `overview.md` 已按验收要求删除。

## S10 契约差量说明

实例 admission 语义有一处有意变更：非法主词条由「assembled + deferred
blocker」改为「装配 blocked」。S10 其余已验收契约由 level-mode direct 复验。
S10 主验证器作为 historical_evidence 冻结，其 `deferred_affix` 旧谓词被本阶段
语义取代，不重跑、不扩写。

## Deferred

- S12：副词条所属池、数量、roll 历史及升级合法性（blocker
  `relic_sub_affix_validation_deferred_to_s12` 保持战斗准入 blocked）。
- S13+：套装计数与档位；S14：主词条精确值进入最终静态贡献账本。
- 本阶段未实现掉落概率/随机生成，未处理副词条、套装统计与最终面板。

## Gap 登记

无。独立 oracle 与生产值全部一致；未触发停止条件。
