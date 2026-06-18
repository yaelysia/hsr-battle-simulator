# v8 Combatant Profile Checkpoint v0_229

## Scope

本检查点建立敌方 `CombatantProfileIR` 来源基线，不实现削韧、击破、break damage、DoT、super-break 或队列。

目标链路：

```text
MonsterConfig + MonsterTemplateConfig -> CombatantProfileIR -> ScenarioStateBuilder -> BattleState snapshot
```

## Implemented

- `CombatantProfileIR` 加入 Canonical IR，记录：
  - `entity_id/entity_type/template_id`
  - `base_stats`
  - `toughness_profile`
  - `weaknesses`
  - `resistances`
  - `source_trace/coverage_status/blocked_reason`
- `TBGDLowering` 从 `MonsterConfig` 与 `MonsterTemplateConfig` 生成 profile。
  - `StanceBase * StanceModifyRatio` 作为当前范围 `max_toughness/current_toughness` 来源。
  - `StanceWeakList` 与 `DamageTypeResistance` 保留 source evidence。
  - 缺模板、缺基础数值、缺修正倍率时 profile blocked，不静默填 0。
- `ScenarioStateBuilder` 对 monster / monster_template 的缺失 panel 字段优先使用 executable profile。
  - 显式 panel 字段仍作为当前战斗输入覆盖 profile。
  - snapshot flags 记录 `combatant_profile_source_trace`、`combatant_profile_coverage_status`、`panel_overrides`。
- `RuleBook` 增加 `combatant_profile()` 与 `require_combatant_profile()`。
- Coverage matrix 增加 `combatant_profile_status`。

## Validation

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_regression_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_229 --output-dir /tmp/hsr_v8_v0_229
```

结果：全部通过。

v0_229 结构化样例：

- selected profile：`monster:1002011`
- source：`ExcelOutput/MonsterConfig.json` + `ExcelOutput/MonsterTemplateConfig.json`
- profile counts：`lowered=3086`，`executable=2395`，`blocked=152`，`lowered_only=539`
- selected action：`avatar_skill:121209` level `1`
- selection mode：`structured_predicate`

## Remaining Boundaries

- 本阶段 profile 是敌方基础战斗参数来源，不是完整等级/难度/关卡最终面板证明。
- `ShowStanceList` 仍不作为 executable toughness damage。
- 削韧 mutation、击破触发、break damage、super-break、DoT、queue 仍未实现。
- 角色面板仍允许 scenario 输入；AvatarPromotion、装备、遗器、光锥的完整面板来源后续单独接入。
