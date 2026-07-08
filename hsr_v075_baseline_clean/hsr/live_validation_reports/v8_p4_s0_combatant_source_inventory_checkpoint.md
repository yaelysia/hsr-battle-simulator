# v8 P4-S0 角色 / 怪物数据卡来源总账本 checkpoint

日期：2026-07-08

状态：`accepted_checkpoint`

本报告由执行线程证据包复核后转为验收 checkpoint。验收线程已复核脚本、矩阵、报告和最小验证输出，并已更新第 22 节 checklist。

## 验收结论

- P4-S0 通过验收。
- S0 只证明来源总账本与范围定界完成，不证明 P4 角色卡 / 怪物卡扩面完成。
- 剩余 `lowering_gap=5`、`admission_gap=36` 是 S0 暴露并要求后续继承的缺口，不作为 S0 失败。
- S0 未改 runtime / reducer / RuleBook / lowering schema，不触发 P1/P2/P3 聚合回归。

## 阶段执行卡

阶段：`P4-S0 角色 / 怪物数据卡来源总账本与范围定界`

目标产物：

- 重写 S0 来源盘点脚本，输出逐 source-family 账本，而不是宽域聚合。
- 输出 summary / source-family matrix / gap attribution / boundary samples。
- 提交 ready_for_review 证据包，不修改 checklist；验收通过后转为本 checkpoint。

本阶段实际改动文件：

- `simulator_v8_clean_core/tools/validate_p4_s0_combatant_source_inventory.py`
- `live_validation_reports/v8_p4_s0_combatant_source_inventory_checkpoint.md`

本阶段未修改：

- 未改 runtime/core/reducer/target/damage/status/queue。
- 未改 RuleBook / lowering schema。
- 执行阶段未改 P4 第 22 节 checklist；验收通过后由验收线程勾选 P4-S0。
- 未新增 P4-S12 聚合脚本。

实际新增 / 修改的主要函数：

- `build_p4_s0_combatant_source_inventory_matrix`
- `validate_p4_s0_combatant_source_inventory_matrix`
- `_build_source_family_rows`
- `_source_family_row`
- `_formula_row`
- `_target_row`
- `_hook_row`
- `_p3_source_family_row`
- `_source_family_classification`
- `_source_family_gap_attribution`
- `_raw_ir_mismatch_attribution`
- `_items_by_source`
- `_items_by_source_and_tokens`
- `_rulebook_visible`
- `_raw_inventory`
- `_raw_source_samples`
- `_json_row_field_value_count`
- `_json_row_field_value_samples`
- `_json_tree_field_value_token_count`
- `_json_tree_field_value_token_samples`
- `_count_matching_field_values`
- `_iter_matching_field_value_paths`

## 本步完成了什么

- 将 S0 矩阵从旧的 18 个宽域行改为 58 个逐 source-family 行。
- 每行输出：
  - `source_family`
  - `raw_source_kind`
  - `raw_path_or_field`
  - `raw_count`
  - `raw_source_samples`
  - `ir_container`
  - `ir_count`
  - `rulebook_query_surface`
  - `rulebook_visible_count`
  - `projection_predicate`
  - `classification`
  - `gap_attribution`
  - `sample_source_trace`
  - `blocked_boundary_samples`
  - `future_owner`
- 新增自检禁止旧宽域行回流：`old_broad_domain_rows_absent=true`。
- 修正 raw 盘点错误：`MonsterConfig.json` 是 list，不是 dict；`MonsterConfig.AbilityNameList` 现在正确计入 `raw=291`。
- 修正 target registry selector：按 lowering 真实 raw type `TargetAliasConfig.AliasDict` / `TargetAliasOperationChain` 统计，避免把 selector 过窄误报为 lowering gap。
- 自审后继续拆细角色秘技、强化形态、行迹状态添加，以及怪物 passive/listener 事件族，避免用宽域 action/config/global modifier 行覆盖子项 gap。
- P3 backlog 显式继承为：
  - `p3_summon_target_backlog`
  - `p3_summoned_monster_intent_backlog`
- future / out-of-scope 行显式保留：
  - `equipment_light_cone_build_hook`
  - `relic_set_build_hook`
  - `monster_stage_override_hook`
  - `stage_environment_sources`
  - `assistant_avatar_sources`
  - `client_visual_config_exclusion`
  - `ui_only_sources`

## 验证输出

执行线程输出目录：

```text
/tmp/hsr_v8_p4_s0_source_inventory
```

验收线程复跑输出目录：

```text
/tmp/hsr_v8_p4_s0_acceptance
```

主要文件：

```text
/tmp/hsr_v8_p4_s0_source_inventory/validation_summary_p4_s0_combatant_source_inventory.json
/tmp/hsr_v8_p4_s0_source_inventory/p4_s0_combatant_source_inventory_matrix.json
/tmp/hsr_v8_p4_s0_acceptance/validation_summary_p4_s0_combatant_source_inventory.json
/tmp/hsr_v8_p4_s0_acceptance/p4_s0_combatant_source_inventory_matrix.json
```

关键 summary：

```text
ok=True
domain_count=58
unclassified_count=0

classification_counts:
  admission_gap=36
  boundary_only=4
  executable=9
  lowering_gap=5
  out_of_scope=4

gap_attribution_counts:
  admission_gap=709526
  lowering_gap=3002

raw_count_total=437212
ir_count_total=1250056
rulebook_visible_count_total=1250056
executable_count_total=539867
blocked_or_gap_count_total=712528
```

关键 self-check：

```text
required_domains_present=true
old_broad_domain_rows_absent=true
required_columns_present=true
all_domains_classified=true
unclassified_zero=true
raw_source_samples_recorded=true
ir_source_traces_sampled_by_domain=true
raw_ir_mismatch_attributed=true
gap_rows_have_attribution=true
gap_rows_have_blocked_boundary_sample=true
required_blocked_boundary_samples_present=true
p3_backlog_projected=true
future_hooks_recorded=true
no_large_artifacts=true
```

Diagnostics：

```text
missing_required_domains=[]
old_broad_domain_rows_present=[]
rows_missing_required_columns=[]
missing_raw_sample_rows=[]
missing_ir_trace_rows=[]
raw_ir_mismatch_rows=[]
gap_rows_without_attribution=[]
gap_rows_without_boundary_sample=[]
```

## Source-family 覆盖摘要

角色侧：

```text
avatar_config_profile_cards: executable
avatar_config_ld_profile_cards: executable
avatar_config_enhanced_profile_cards: executable
avatar_promotion_config_profile_stats: executable
avatar_skill_config_actions: admission_gap
avatar_technique_skill_sources: admission_gap
avatar_enhanced_skill_effect_sources: admission_gap
common_avatar_skill_config_actions: admission_gap
avatar_skilltree_config_trace_slots: admission_gap
avatar_skilltree_status_add_sources: admission_gap
avatar_rank_config_eidolon_slots: admission_gap
config_character_localplayer_sources: lowering_gap
config_ability_avatar_graphs: admission_gap
avatar_skill_param_formula_sources: admission_gap
avatar_skill_resource_fields: executable
```

servant / 子单位：

```text
avatar_servant_config_subcard_sources: executable
avatar_servant_skill_config_actions: admission_gap
config_character_servant_sources: lowering_gap
config_ability_servant_graphs: admission_gap
```

怪物侧：

```text
monster_config_base_cards: admission_gap
monster_template_config_profiles: admission_gap
monster_template_unique_config_overrides: admission_gap
monster_config_skill_list_action_set: admission_gap
monster_skill_config_actions: admission_gap
monster_skill_unique_config_actions: admission_gap
ilbattle_monster_skill_actions: admission_gap
config_character_monster_sources: admission_gap
config_ability_monster_graphs: admission_gap
monster_config_override_ai_sequence: admission_gap
monster_template_ai_sequence: admission_gap
monster_config_ability_name_list_passives: admission_gap
config_global_modifier_listener_sources: admission_gap
monster_passive_start_enter_listener_sources: admission_gap
monster_passive_wave_listener_sources: admission_gap
monster_passive_death_listener_sources: admission_gap
monster_passive_hit_attack_listener_sources: admission_gap
monster_passive_phase_skill_trigger_sources: admission_gap
monster_config_summon_id_list_refs: boundary_only
```

公式 / dynamic / target：

```text
avatar_skill_param_formula_sources: admission_gap
monster_skill_param_formula_sources: lowering_gap
ilbattle_skill_param_formula_sources: lowering_gap
dynamic_config_ability_fields: admission_gap
dynamic_avatar_skilltree_param_fields: admission_gap
dynamic_monster_custom_value_fields: admission_gap
dynamic_modifier_hash_fields: admission_gap
target_battle_target_config: lowering_gap
target_alias_config_alias_dict: executable
target_operation_config_operation_dict: executable
target_ability_payloads: admission_gap
```

P3 backlog：

```text
p3_summon_target_backlog: admission_gap
p3_summoned_monster_intent_backlog: admission_gap
```

Future / out-of-scope：

```text
equipment_light_cone_build_hook: boundary_only
relic_set_build_hook: boundary_only
monster_stage_override_hook: boundary_only
stage_environment_sources: out_of_scope
assistant_avatar_sources: out_of_scope
client_visual_config_exclusion: out_of_scope
ui_only_sources: out_of_scope
```

## 新增或修正的来源分类

- `MonsterConfig.AbilityNameList` 现在作为独立 source family 入账，不再被 `monster_passive_listener_sources` 大域吞掉。
- `AvatarSkillConfig` 中秘技来源按 `SkillTriggerKey=SkillMaze` / `AttackType=Maze` 独立入账，不被 `avatar_skill_config_actions` 覆盖。
- `AvatarSkillConfig.SkillEffect=Enhance` 独立入账，强化 / 替换动作来源不被普通技能正例覆盖。
- `AvatarSkillTreeConfig.StatusAddList` 独立入账，行迹状态添加 / 开局类输入不被行迹字段存在性覆盖。
- 怪物 passive/listener 按 `start/enter/create`、`wave`、`death/die/dying`、`hit/attack/attacked`、`phase/skill` 事件族拆行，不能用 `config_global_modifier_listener_sources` 一个宽域行覆盖。
- `TargetAliasConfig.AliasDict` 和 `TargetOperationConfig.OperationDict` 分行入账，且已按实际 lowering raw type 反查到 `TargetExpressionIR`。
- `BattleTargetConfig` 当前为 `lowering_gap`，没有被 target registry 正例覆盖。
- `MonsterConfig.SummonIDList` 当前为 `boundary_only`，只作为 catalog/lifecycle 输入，不作为 executable spawn trigger。
- `ConfigCharacter/LocalPlayer`、`ConfigCharacter/Servant` 当前为 `lowering_gap`，说明 raw config 文件存在但 S0 没找到对应 IR 投影；未用 source_absent 或 out_of_scope 掩盖。
- `monster_skill_param_formula_sources`、`ilbattle_skill_param_formula_sources` 当前为 `lowering_gap`，未用怪物技能 action 正例覆盖公式/参数缺口。

## 正例选择方式

正例不按角色名、怪物名、技能 ID、文件名或 hash 选择。

S0 正例来自结构化 source-family predicate，例如：

- `IR source.raw_type == AvatarConfig`
- `IR source.raw_type == TargetAliasConfig.AliasDict`
- `AvatarSkillConfig.SkillTriggerKey == SkillMaze or AttackType == Maze`
- `AvatarSkillConfig.SkillEffect == Enhance`
- `AvatarSkillTreeConfig.StatusAddList exists`
- listener `Event` field contains start/enter/create/wave/death/hit/phase/skill token families
- `MonsterDataCardIR.summon_refs non-empty`
- `PassiveMechanismSlotIR.data_card_kind == monster`
- `TargetExpressionIR source matches registry/table source`
- `IR JSON contains dynamic/custom/hash/readinfo tokens`

宽域正例不能覆盖子行 gap。脚本显式检查 `old_broad_domain_rows_absent=true`。

### Predicate 宽窄自审

本阶段 predicate 分三类：

- 精确来源 predicate：`source.raw_type`、具体 JSON 字段、具体 registry raw type，例如 `AvatarConfig`、`TargetAliasConfig.AliasDict`、`SkillEffect=Enhance`。这类用于确认 raw -> IR / RuleBook 可见性。
- 结构化字段族 predicate：`StatusAddList`、`SkillTriggerKey=SkillMaze`、`AttackType=Maze`、`Event` 字段值 token family。它们只用于 S0 来源盘点，不证明机制语义已经 admitted。
- 宽 token discovery predicate：dynamic/custom/hash/readinfo、target payload、listener event family。它们可能 over-select，但只会增加 `admission_gap` / blocked 样本，不会把行标为 executable，也不会产生 runtime mutation。

当前可能过宽的 predicate：

- `monster_passive_phase_skill_trigger_sources` 的 `phase/skill` token family 会覆盖一批后续需要更细分的 phase 与 skill-use listener。
- `monster_passive_hit_attack_listener_sources` 的 `hit/attack/attacked` token family 会覆盖攻击前后、受击、命中监听的多个子族。
- `dynamic_config_ability_fields` 与 `target_ability_payloads` 是 intentionally broad inventory，目的是避免误报 source gap，不是 admission 证明。

对应限制：

- 所有这些行当前都是 `admission_gap`，不是 executable。
- 每行都有 `projection_predicate`、`gap_attribution`、`blocked_boundary_samples`。
- 后续 S3/S4/S5/S6 必须按更精确 opcode、payload、event、target mode 做 admission；不能把 S0 的宽 predicate 当作机制完成证据。

## 负例 / blocked 边界

S0 不执行 battle transition，因此没有 mutation / settlement / replay 正例。本阶段负例是来源边界和 admission 边界：

- 缺 equipment/build assembly 时，光锥/遗器/套装只能 `boundary_only`，不产生装备规则 mutation。
- 缺 stage/environment layer 时，stage/environment 只能 `out_of_scope`，不伪装成角色/怪物卡规则。
- `MonsterConfig.SummonIDList` 只作为 catalog/lifecycle 输入，不能直接 spawn。
- target 缺 alias/operation/fetch/sort/filter/retarget/owner/caster/payload 时必须 blocked，无 fallback。
- AssistantAvatar 保持 out_of_scope，不混入 servant / summoned monster。
- UI-only 不能提供规则事实。

每个 gap 行都有 `gap_attribution` 和 `blocked_boundary_samples`。

## Source audit / replay / settlement traceability

S0 是来源盘点阶段，不执行 transition，因此不产生 settlement、mutation 或 replay transition。

本阶段验证的是：

- raw source sample 是否存在。
- IR source trace sample 是否存在。
- RuleBook visible count 是否记录。
- gap 是否有分层归因。
- blocked / boundary 是否有样例。

后续 executable runtime 机制必须在对应阶段补充 mutation -> settlement -> IR -> TBGD source 的反查验证。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s0_combatant_source_inventory.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s0_combatant_source_inventory --output-dir /tmp/hsr_v8_p4_s0_source_inventory
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
bash -lc 'if rg -n "[[:blank:]]$" simulator_v8_clean_core/tools/validate_p4_s0_combatant_source_inventory.py live_validation_reports/v8_p4_s0_combatant_source_inventory_checkpoint.md; then exit 1; fi'
```

补充说明：两个 S0 新文件当前是 untracked，普通 `git diff --check` 不覆盖 untracked 文件，因此额外运行 trailing-whitespace 检查。

未运行：

- 未运行 P4-S12 聚合：S12 才允许。
- 未运行 P1/P2/P3 聚合：S0 只改来源盘点工具和报告，不改 runtime/lowering schema/shared reducer。
- 未运行 transition 级验证：S0 不执行机制，transition 负例留给对应机制阶段。

## ok=true 实际检查了什么

S0 主验证检查了：

- required source family 是否全部出现。
- 是否存在旧宽域行。
- 每行是否有 required columns。
- 每行是否分类，且 `unclassified_count=0`。
- raw source sample 是否存在。
- 非空 IR 行是否有 source trace sample。
- raw/IR mismatch 是否有 attribution。
- gap 行是否有 gap attribution 和 blocked sample。
- P3 backlog 是否继承。
- future hook / out-of-scope 是否记录。
- 是否未写大产物。

S0 主验证没有检查：

- runtime transition 是否 state unchanged。
- mutation / settlement / replay 是否闭环。
- gap 是否已清零。
- P1/P2/P3 是否回归。

这些不属于 S0 可完成范围，必须在后续阶段按机制验证。

## 剩余 gap / deferred

当前 S0 矩阵仍有：

```text
lowering_gap=3002
admission_gap=709526
out_of_scope=4 rows
boundary_only=4 rows
```

主要 lowering gap 行：

```text
config_character_localplayer_sources
config_character_servant_sources
monster_skill_param_formula_sources
ilbattle_skill_param_formula_sources
target_battle_target_config
```

这些不是 S0 完成失败；S0 的目标是把来源和缺口查清。但这些 gap 必须被 S1-S12 或后续阶段继承，不能在 P4 最终聚合里被宽域正例覆盖。

## 对 P1/P2/P3 的影响

- 未改 runtime，因此 P1/P2/P3 既有完成口径不应变化。
- P3 backlog 已显式进入 P4 S0 矩阵：
  - `p3_summon_target_backlog`
  - `p3_summoned_monster_intent_backlog`
- S0 checkpoint 不代表 P4 底座闭环通过，也不代表 P4 全正例完成。
