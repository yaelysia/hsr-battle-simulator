# v8 P4-S1 数据卡 / RuleBook 契约复核 ready_for_review

日期：2026-07-08

状态：`ready_for_review`

本报告是执行线程证据包，不是 `done` 标记。按当前协作口径，S0 已由验收线程确认，后续阶段允许连续执行；本报告不修改 P4 第 22 节 checklist。

## 阶段执行卡

阶段：`P4-S1 CharacterDataCard / MonsterDataCard / RuleBook 契约复核`

目标产物：

- 输出数据卡 / RuleBook contract matrix。
- 复核 card id、entity_ref、profile id、action ref、formula binding、mechanism slot 等查询面。
- 补齐必要的只读 RuleBook accessor。
- 提交 ready_for_review 报告，不改 checklist。

本阶段实际改动文件：

- `simulator_v8_clean_core/rules/rulebook.py`
- `simulator_v8_clean_core/tools/validate_p4_s1_data_card_rulebook_contract.py`
- `live_validation_reports/v8_p4_s1_data_card_rulebook_contract_ready_for_review.md`

本阶段未修改：

- 未改 runtime/core/reducer/damage/status/target/queue 执行语义。
- 未改 lowering 生成规则事实。
- 未新增 P4-S12 聚合脚本。
- 未改 P4 第 22 节 checklist。

## 实际新增 / 修改

RuleBook 新增只读查询面：

- `combatant_profile_by_profile_id(profile_id)`
- `avatar_profile_by_profile_id(profile_id)`

新增 S1 验证脚本：

- `build_p4_s1_data_card_rulebook_contract_matrix`
- `validate_p4_s1_data_card_rulebook_contract_matrix`
- `character / monster data card core contract`
- `character / monster card link contract`
- `combatant profile contract`
- `combatant action set contract`
- `formula binding contract`
- `character mechanism / trace / eidolon contract`
- `monster passive contract`
- servant / summoned monster / build-stage hook contract
- source audit contract

## 验证输出

输出目录：

```text
/tmp/hsr_v8_p4_s1_data_card_rulebook_contract
```

主要文件：

```text
/tmp/hsr_v8_p4_s1_data_card_rulebook_contract/validation_summary_p4_s1_data_card_rulebook_contract.json
/tmp/hsr_v8_p4_s1_data_card_rulebook_contract/p4_s1_data_card_rulebook_contract_matrix.json
```

关键 summary：

```text
ok=True
contract_count=13
unclassified_count=0

classification_counts:
  admission_gap=7
  boundary_only=3
  executable=2
  validation_gap=1

gap_attribution_counts:
  admission_gap=24475
  validation_gap=28

raw_count_total=184880
ir_count_total=212619
rulebook_visible_count_total=212591
blocked_or_gap_count_total=24503
```

## Contract Matrix 摘要

```text
character_data_card_core_contract: executable
character_card_link_contract: executable
monster_data_card_core_contract: admission_gap
monster_card_link_contract: validation_gap
combatant_profile_contract: admission_gap
combatant_action_set_contract: admission_gap
formula_binding_contract: admission_gap
character_mechanism_trace_eidolon_contract: admission_gap
monster_passive_contract: admission_gap
servant_subcard_hook_contract: boundary_only
summoned_monster_lifecycle_hook_contract: boundary_only
equipment_build_stage_environment_hook_contract: boundary_only
source_audit_contract: admission_gap
```

## 新增或修正的来源分类

- CharacterDataCard core 与 link contract 当前 executable：card id、entity_ref、avatar profile id、action set、action definition、formula binding、mechanism/trace/eidolon/bounce link 均可由 RuleBook 查到。
- MonsterDataCard core 是 admission_gap：卡与 entity_ref 可查，但 monster card 当前大多是 lowered，不代表 runtime executable。
- Monster card link 有 `validation_gap=28`：部分 MonsterDataCard 有卡对象但缺对应 `CombatantActionSetIR`，且卡本身未给 blocked reason；不能由 S1 伪造 action set。
- CombatantProfile 是 admission_gap：profile id 与 entity id 查询已补齐，但有 blocked profile 缺 stat/toughness，原因如 `monster_template_base_stat_missing:StanceBase`。
- Character mechanism / trace / eidolon 是 admission_gap：836 个机制槽缺 character card ref，但都有 blocked reason，例如 `character_data_card_missing_for_avatar_skill`。
- CombatantActionSet 是 admission_gap：2 个 action set 缺 executable action，原因是 `combatant_action_set_has_no_executable_actions`。
- Hook 行均为 boundary_only，缺输入时 state unchanged，不生成 runtime mutation。

## 正例选择方式

正例不按角色名、怪物名、技能 ID、固定文件名或 hash 选择。

S1 正例来自结构化契约谓词：

- `RuleBook.character_data_card(card_id)`
- `RuleBook.character_data_card_for_entity(entity_ref)`
- `RuleBook.avatar_profile_by_profile_id(profile_id)`
- `RuleBook.monster_data_card(card_id)`
- `RuleBook.monster_data_card_for_entity(entity_ref)`
- `RuleBook.combatant_profile_by_profile_id(profile_id)`
- `RuleBook.combatant_action_set(entity_ref)`
- `RuleBook.action_definition(action_ref, level)`
- `RuleBook.skill_formula_binding(binding_id)`
- `RuleBook.character_mechanism_slot / character_trace_node / character_eidolon_slot`

S1 不把字段存在等同于 contract 通过；每个 contract 同时检查 source trace 与 RuleBook 可见性。

## 负例 / blocked 边界

- servant 子卡 hook：缺完整 stat/action/lifecycle assembly 时只能 boundary_only。
- summoned monster lifecycle hook：缺 owner relation、target source、lifecycle 或 dynamic monster id admission 时 state unchanged。
- equipment/build/stage/environment hook：缺 future assembly layer 时不能创建数据卡 stats/actions/status/mutation。
- source audit contract：S1 不执行 transition；mutation/settlement/replay traceability 留给后续 runtime 阶段，不冒充完成。

每个 gap 行都有 `gap_attribution` 和 `blocked_boundary_samples`。

## ok=true 实际检查了什么

S1 主验证检查了：

- required contract 行是否全部存在。
- 每行 required columns 是否存在。
- classification 是否在允许状态内，且 `unclassified_count=0`。
- executable contract 是否有 source audit sample。
- gap 行是否有 attribution。
- blocked/gap 行是否有 boundary sample。
- hook boundary 是否存在。
- 默认没有写完整 IR、完整 TBGD dump 或 transition dump。

S1 主验证没有检查：

- runtime transition 是否真的 state unchanged。
- mutation -> settlement -> IR -> TBGD source 的完整反查。
- action availability 是否能产出 choice；这是 S2。
- formula/dynamic value 是否 admitted；这是 S3。
- monster action graph 是否补齐；这是 S5。

## 剩余 gap / deferred

```text
admission_gap=24475
validation_gap=28
boundary_only=3 rows
```

关键继承项：

- `monster_card_link_contract.validation_gap=28`：进入 S2/S5，不能被 monster card core 正例覆盖。
- `formula_binding_contract.admission_gap=2957`：进入 S3。
- `character_mechanism_trace_eidolon_contract.admission_gap=5290`：进入 S7/S8/S9。
- `monster_passive_contract.admission_gap=309`：进入 S6。
- `summoned_monster_lifecycle_hook_contract` 与 P3 backlog：进入 S10。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/rules/rulebook.py simulator_v8_clean_core/tools/validate_p4_s1_data_card_rulebook_contract.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s1_data_card_rulebook_contract --output-dir /tmp/hsr_v8_p4_s1_data_card_rulebook_contract
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
bash -lc 'if rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s1_data_card_rulebook_contract.py live_validation_reports/v8_p4_s1_data_card_rulebook_contract_ready_for_review.md; then exit 1; fi'
```

## 对 P1/P2/P3 的影响

- RuleBook 只新增只读 accessor，不改变既有 accessor 行为。
- 未改 runtime 行为，不应影响 P1/P2/P3 既有完成口径。
- S1 暴露的 profile/action/passive/summon gap 会进入 P4 后续阶段继承。
