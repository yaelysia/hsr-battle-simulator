# v8 P4-S2 Combatant Action Availability Ready For Review

阶段状态：`ready_for_review`。本报告不修改 `P4_COMBATANT_DATA_CARD_EXPANSION_TASK_PLAN.md` 第 22 节 checklist，不声明 `done`。

## 阶段执行卡

阶段：P4-S2 Combatant action set 与 action availability 扩面。

目标产物：

- 让 action availability choice 能直接反查 actor 所属数据卡或子卡 source。
- 用结构化谓词验证角色、普通怪物、servant、summoned monster 四类行动入口。
- 用边界样例验证缺 action set、缺目标、缺资源、缺 turn owner、缺 summon runtime 时只 blocked，查询 state unchanged。
- 继承 S1 的 monster card -> action set link validation gap，不用正例覆盖内部缺口。

本阶段实际只改：

- `simulator_v8_clean_core/systems/action_availability.py`
- `simulator_v8_clean_core/tools/validate_p4_s2_combatant_action_availability.py`
- `live_validation_reports/v8_p4_s2_combatant_action_availability_ready_for_review.md`

本阶段没有改：

- P4 checklist。
- reducer / executor admission 语义。
- enemy AI 或 route 决策。
- target/resource 规则本身。
- raw TBGD runtime 读取路径。

## 实际改动

`ActionAvailabilitySystem`：

- 为 normal action、summon action、enemy fixed sequence choice 增加 `source_trace.actor_data_card`。
- 增加 `_actor_data_card_source_trace()`，按 actor 结构化归属反查：
  - ally -> `RuleBook.character_data_card_for_entity(actor.template_id)`。
  - enemy -> `monster_data_card_id` 或 `RuleBook.monster_data_card_for_entity(actor.template_id)`。
  - summon -> `servant_definition_id` 或 `RuleBook.servant_definition(actor.template_id)`。
- 增加 `_compact_actor_data_card()`，在 metadata 中保留轻量卡片锚点。
- 没有改变 choice admission、target enumeration、resource plan、fixed sequence candidate 选择逻辑。

新增 S2 验证脚本：

- 构建一次 `TBGDLowering(...).build()` 和 `RuleBook(ir)`。
- 复用 S0 来源账本和 S1 contract matrix。
- 输出：
  - `/tmp/hsr_v8_p4_s2_combatant_action_availability/validation_summary_p4_s2_combatant_action_availability.json`
  - `/tmp/hsr_v8_p4_s2_combatant_action_availability/p4_s2_combatant_action_availability_matrix.json`
- 默认不写完整 IR、完整 transition dump 或大 artifact。

## Matrix 结果

S2 主验证：

```text
ok=True
case_count=7
classification_counts={'boundary_only': 1, 'executable': 4, 'source_absent_not_required': 1, 'validation_gap': 1}
gap_attribution_counts={'validation_gap': 28}
unclassified_count=0
```

case 摘要：

- `character_normal_action_availability`: executable。结构化选择第一个可执行 `CharacterDataCardIR + CombatantActionSetIR` choice；choice 含 `actor_data_card`、action definition、action event、combatant action set source。
- `monster_fixed_sequence_availability`: executable。结构化选择 fixed sequence `MonsterDataCardIR`；choice 为 `enemy_fixed_sequence`、`control=external`、command template `source=manual`，没有引入敌方 AI。
- `servant_subcard_action_availability`: executable。通过 `ServantDefinitionIR` spawn 后查询 `summon_action`；choice 含 servant definition 子卡 source、summon action admission、action definition、action event。
- `summoned_monster_fixed_sequence_availability`: executable。通过 `SummonMonsterIntentIR` spawn 后查询 source-backed fixed sequence choice。
- `availability_gate_boundaries`: boundary_only。覆盖 `combatant_action_set_missing`、`target_candidates_empty`、`insufficient_skill_points`、`turn_begin_requires_scheduler_step`、`summon_runtime_state_missing`，均 state unchanged。
- `missing_action_definition_source_scan`: source_absent_not_required。扫描 12854 个 action set entry，当前 executable entry 全部能解析到 `ActionDefinitionIR`；未合成缺 definition 假样例。
- `s1_monster_card_action_set_link_gap_inherited`: validation_gap。继承 S1 的 28 个 monster card action-set link gap。

样本 ID 是验证输出，不是选择条件。主路径选择谓词基于 IR 类型、coverage、action set、fixed sequence、choice kind、source trace 和 gate 结构。

## 验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/systems/action_availability.py simulator_v8_clean_core/tools/validate_p4_s2_combatant_action_availability.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s2_combatant_action_availability --output-dir /tmp/hsr_v8_p4_s2_combatant_action_availability
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p4_s2
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p4_s2
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s6_summon_action_execution --output-dir /tmp/hsr_v8_p3_s6_after_p4_s2
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
if rg -n "[[:blank:]]$" hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_availability.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p4_s2_combatant_action_availability.py; then exit 1; fi
```

结果：

- S2 主验证 `ok=True`。
- P1-0 `ok=True`。
- P1-3 `ok=True`。
- P3-S6 `ok=True`。
- `compileall` 通过。
- `git diff --check` 通过。
- 本阶段新/改文件尾随空白检查通过。

## 未完成 / Gap / Deferred

- S1 继承 gap：`monster_card_link_contract` 中 28 个 `action_set_refs` validation gap 仍存在，已进入 S2 matrix。
- 当前没有真实 executable action set entry 缺 `ActionDefinitionIR`；S2 只做 source scan，不造假负例。
- S2 只增强 action availability 查询契约，不宣称全角色动作、全怪物技能图、全资源门、全 target query 完成。
- 强化/替换动作、秘技、行迹/星魂动作等级提升、ILBattle 扩面、特殊资源/冷却等继续归属 S3/S4/S5/S7/S8。

## 当前进度口径

当前做到 P4-S2 ready_for_review：可行动单位的数据卡/子卡到 action availability 的查询锚点和主要边界已可验证。

距离最小可用战斗纵切：P1/P3 已有纵切基础；S2 补的是查询契约和来源锚点，不改变最小战斗执行链。

距离完整复刻：仍缺公式/dynamic/custom value 总账、target admission 扩面、怪物技能 action graph 覆盖、怪物被动/波次/阶段、角色行迹星魂与装备构筑等后续阶段。
