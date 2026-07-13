# v8 P8-S0 装备来源与机制基线 ready_for_review

## 阶段状态

```text
stage=P8-S0
execution_status=ready_for_review
acceptance_status=accepted
checklist_modified_by_execution=false
checklist_modified_by_acceptance=true
p8_s1_started=false
runtime_behavior_changed=false
formal_equipment_ir_added=false
```

本报告由执行线程提交为 evidence 索引；当前代码、验证谓词和独立 `/tmp` evidence 已由验收线程复核，P8-S0 已通过并由验收线程勾选唯一 Checklist。

## 本阶段实际交付

- 新增 `tbgd/equipment_discovery.py`，只在 L0 discovery / 审计层读取 TBGD raw。
- 新增 `tools/validate_p8_s0_equipment_source_inventory.py`，不构建 `CanonicalIR`、`RuleBook`、scenario 或 transition。
- 主来源使用 path + full content SHA-256；辅助来源区分完整内容指纹与明确字节范围的抽样指纹。
- 候选发现不局限于预设九表：动态列出 ExcelOutput 中名称含 equip / relic 的 JSON、`ConfigAbility/Equip` 全部 JSON，以及 ConfigAbility 中名称含 equip / relic 的 JSON。
- 当前新发现但没有来源角色策略的候选会以 `unclassified` 使验证失败；首次运行实际拒绝了 GridFight、IdleLive、PixAir 等 28 个候选，补充显式来源角色后才通过。
- 发布状态、遗器模式、未引用 ability、旧镜像差异和 unknown raw type 均进入结构化 evidence，没有丢弃。
- 能力机制扫描覆盖每个主能力文件的完整根对象：`AbilityList`、`GlobalModifiers`、`GlobalTemplates` 以及未来出现的任意新顶层段都由同一递归 walker 扫描；顶层段发现清单、扫描清单和未扫描清单进入 evidence。
- 引用完整性同时做正向解析与反向清点：所有 ability 名全局唯一，遗器部位定义唯一，未归属任何光锥的成长/叠影记录进入孤立来源清单并阻断通过。

## 目标与 evidence 映射

| 目标 | 当前代码 / evidence | 当前结果 |
|---|---|---|
| 主来源完整发现 | `discover_primary_equipment_paths`、`p8_s0_equipment_source_inventory.json` | 9 张核心表和 Equip 目录 15 个非 layout ability 文件被完整读取 |
| 主来源完整指纹 | `load_equipment_source_snapshot`、summary `primary_source_fingerprint` | 24 文件、3,034,164 bytes，path + full content SHA-256 |
| 候选发现不能自证 | `discover_equipment_candidate_paths`、special-source matrix | 107 个候选均有行；`unregistered_candidate_paths=[]` |
| 辅助指纹范围诚实 | full / sampled auxiliary fingerprint | 80 个辅助文件完整读取并纳入完整指纹；3 个大表只保留 `[0,65536)` 抽样和待确认状态 |
| 光锥引用闭合 | reference integrity | Equipment → promotion → skill rank → ability 正向解析闭合；promotion / skill rank 反向孤立清单为空；全部 ability（包括未引用 ability）名称全局唯一 |
| 遗器引用闭合 | reference integrity | template → base type / main group / sub group / set 与 set → threshold / ability 均闭合；7 条 base type 记录身份无重复 |
| 发布状态不丢失 | reference inventory / source inventory | 光锥与套装为 `published`；遗器模板因 raw 无 Release 字段保留为 `status_unknown`；ability 从引用来源派生发布状态 |
| 特殊模式不丢失 | relic mode dimensions / special source rows | `BASIC=720`、`CUSTOM=6`；CUSTOM 独立保留；特殊玩法来源保留为 unknown |
| 机制族无静默遗漏 | mechanism family matrix | 15 个文件的全部已发现顶层段均被扫描；文件级全局定义中的 64 个 raw type 及其 event / target / dynamic read / condition 证据进入矩阵；8 个 unknown raw type 保留样本 |
| 负例拒绝 | summary `negative_cases` | 六个数据负例直接修改深复制的 raw snapshot 并重建 reference / inventory；另有陈旧 fingerprint、漏动态候选两项边界负例，八项均被拒绝 |
| 资源受控 | summary `resource_budget` | lowering=0、RuleBook=0、transition=0；1 次控制构建加 6 次 raw 负例构建均在单进程内串行完成，没有写完整 raw / IR / RuleBook / transition |

## 当前 source fingerprint

```text
algorithm=sha256-path-and-full-content-v1
file_count=24
byte_count=3034164
sha256=39b5d5d55a5d4d7e9a3739a5de098944b5851593de0f2311ffa661fe384a346a
coverage=full_content_for_every_primary_source_file
```

该 hash 只绑定当前主来源，不作为未来固定通过答案。验证根据当前目录重新发现文件并重新计算；陈旧 expected fingerprint 负例会被拒绝。

辅助来源另有两套指纹：

- `full_auxiliary_fingerprint`：所有完整分类的辅助文件均有逐文件完整 SHA-256，并进入组合指纹。
- `sampled_pending_auxiliary_fingerprint`：只覆盖明确的文件大小、`[0,65536)` 字节范围和样本 SHA-256，不声称覆盖整文件。

当前仅抽样、不得作为完整分类依据的文件：

- `ExcelOutput/SpecialAvatarRelic.json`
- `ExcelOutput/SpecialAvatarRelicMainValue.json`
- `ExcelOutput/SpecialAvatarRelicSubValue.json`

三者均为 `classification=unknown`、`classification_status=sampled_pending_confirmation`。

## 当前来源与引用观察

以下均由当前数据动态计算，不是验证常量：

```text
equipment=162
equipment_promotion_rows=1134
equipment_skill_rows=810
equipment_publication={published: 162}

relic_templates=726
relic_template_publication={status_unknown: 726}
relic_modes={BASIC: 720, CUSTOM: 6}

relic_sets=58
relic_set_thresholds=90
relic_set_publication={published: 58}
relic_set_threshold_publication={published: 90}

ability_records=226
referenced_abilities=224
unreferenced_abilities=2
reference_issue_count=0
orphan_promotion_records=0
orphan_superimposition_records=0
relic_base_type_records=7
relic_base_type_duplicate_identities=0
```

未引用 ability 没有被删除：

- `Ability29000`：`Config/ConfigAbility/Equip/EquipmemtAbility.json#/AbilityList/0`
- `RelicAbility100`：`Config/ConfigAbility/Equip/RelicAbility.json#/AbilityList/0`

根目录旧能力文件也未被静默合并：

- `Config/ConfigAbility/EquipmemtAbility.json`：114 个 ability 名，均为主 Equip 目录能力集合的子集，但不是相同集合。
- `Config/ConfigAbility/RelicAbility.json`：44 个 ability 名，均为主 Equip 目录能力集合的子集，但不是相同集合。

完整差异列表保存在 `p8_s0_equipment_special_source_classification.json` 的 `mirror_evidence` 中。

## 完整能力文件扫描与当前 unknown 机制

机制 walker 不再只遍历 `AbilityList`。当前 15 个主能力文件的每一个根对象都先枚举顶层段，再逐段递归扫描；evidence 中每个文件均满足：

```text
discovered_top_level_sections == scanned_top_level_sections
unscanned_top_level_sections == []
```

当前文件级定义扫描结果为动态观察值，不是固定通过常量：

```text
GlobalModifiers / GlobalTemplates structural occurrences=128
raw_type=64
event=5
condition=3
target_alias=26
target_type=26
dynamic_read_type=4
```

每个聚合机制行都记录 `source_scope_counts`，样本也记录 `source_scope`；验证器会从机制行反算文件级分维度数量，并要求与扫描覆盖账本完全一致。因此文件级节点不会因与 `AbilityList` 中已有机制类别相同而在覆盖验证中消失。

S0 不把未知 task 伪装为 non-gameplay。当前 8 个 unknown raw type 及来源样本均保留：

```text
DIHCJLDIMNA
JDOLDFECMPL
RPG.GameCore.AddBuffPerform
RPG.GameCore.ModifierAttachEffect
RPG.GameCore.StackStatusDesc
RPG.GameCore.ToggleSkillPreShow
RPG.GameCore.TriggerEffect
RPG.GameCore.WaitSecond
```

其中混淆名称和表现候选都只表示“尚未完成结构化语义确认”。S0 允许这些明确的 unknown 存在，但后续 S7/S8/S16/S17/S21 不能忽略它们。

## 八项内存负例

```text
raw_missing_referenced_ability_rejected_after_rebuild=true
raw_duplicate_unreferenced_ability_rejected_after_rebuild=true
raw_duplicate_relic_base_type_rejected_after_rebuild=true
raw_orphan_promotion_rejected_after_rebuild=true
raw_orphan_superimposition_rejected_after_rebuild=true
raw_empty_core_table_rejected_after_rebuild=true
stale_source_fingerprint_rejected=true
omitted_discovered_candidate_rejected=true
mutates_source_files=false
```

前六项不再修改生成后的 match count 或摘要：验证脚本深复制 `EquipmentSourceSnapshot`，直接删除/复制/追加/清空其中的 raw 表记录或 ability 记录。每个 raw 负例都重新构建并验证 reference integrity、mechanism family matrix 和 source inventory；负例还要求出现对应的具体 issue kind 或孤立清单，不能靠无关失败冒充拒绝。后两项分别验证 expected fingerprint 与候选分类边界。所有负例均只修改内存副本，不修改 TBGD 或项目文件。

```text
raw_snapshot_rebuild_count=6
reference_integrity_build_count=7
mechanism_matrix_build_count=7
source_inventory_build_count=7
```

## Evidence 路径

```text
/tmp/hsr_v8_p8_s0_equipment_source_inventory/p8_s0_equipment_source_inventory.json
/tmp/hsr_v8_p8_s0_equipment_source_inventory/p8_s0_equipment_reference_integrity.json
/tmp/hsr_v8_p8_s0_equipment_source_inventory/p8_s0_equipment_mechanism_family_matrix.json
/tmp/hsr_v8_p8_s0_equipment_source_inventory/p8_s0_equipment_special_source_classification.json
/tmp/hsr_v8_p8_s0_equipment_source_inventory/validation_summary_p8_s0_equipment_source_inventory.json
```

## 验证范围

已串行执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s0_equipment_source_inventory --output-dir /tmp/hsr_v8_p8_s0_equipment_source_inventory
git diff --check
```

最终结果：

```text
compileall_exit_code=0
p8_s0_validation_exit_code=0
p8_s0_validation_ok=true
p8_s0_ready_for_review=true
git_diff_check_exit_code=0
new_file_whitespace_check_exit_code=0
evidence_integrity_check_exit_code=0
```

不运行 P1-P7 聚合、完整 RuleBook build 或 `validate_v0_209`，因为本阶段没有修改 lowering、Canonical IR、RuleBook、runtime、reducer、snapshot 或 replay；运行这些重验证与本阶段没有直接调用链关系。

## 尚未关闭的真实缺口

- 当前仍无正式装备 IR、构筑输入、装配结果或 RuleBook 窄查询面；这些属于 P8-S1 及以后阶段。
- 当前 lowering 对 `RelicSetSkillConfig` 的宽泛实体投影字段与 raw 实际字段不完整对应；S0 只记录事实，未提前修正。
- 8 个 unknown ability raw type 仍需后续机制语义、lowering、admission、runtime 和验证分流。
- 3 个 `SpecialAvatarRelic*` 大表仍是有界抽样的待确认辅助来源，不能用于 P8-DONE 完整分类。
- GridFight、IdleLive、PixAir、Rogue/Upgrade 等来源已显式列为特殊模式或工具候选，但没有进入普通光锥/遗器验收范围，也没有被判成 non-gameplay。

## 与最终目标的距离

P8-S0 只建立来源与机制基线，当前仍不能从角色构筑生成面板，也不能执行任何光锥、遗器或套装效果。距离最小正式装备战斗纵切仍缺 P8-S1 至 P8-S20；距离 P8 全量完成还需要 S21 对全部当前发布 gameplay ability、特殊来源分类、来源审计和 replay 做严格 gap=0 聚合。
