# v8 complete monster example card checkpoint v0_278

## 本阶段修正

- 补上 v0_277 缺失的“完整示例怪物卡”落地文件。
- 示例卡路径：`simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_278.json`。
- 示例卡由通用 builder 和结构化选择器导出，不手写单怪机制，不按固定 `MonsterID` 选择。
- 修正普通 `MonsterConfig.SkillList` 与 `ILBattleMonsterSkill` 同 ID action definition 的来源错配：
  - 普通怪物 action set 不能借用 ILBattle action definition。
  - 当前示例 action slot 明确 blocked，原因是 `action_definition_source_mismatch_for_monster_config_skill`。

## 示例卡内容

当前结构化选择实际选中：

- `MonsterID=1002011`
- `MonsterTemplateID=1002011`
- `Rank=MinionLv2`
- 技能：`100201101`
- AI：`Monster_Common_SequenceThree_AI` 的 `UseSequencedSkill`
- 序列来源：`MonsterTemplateConfig.AISkillSequence`
- 技能来源：`MonsterSkillConfig`

示例卡展开内容包括：

- 身份、模板、Rank、card id。
- 面板来源：`CombatantProfileIR`、模板基础值、实例倍率。
- 弱点、伤害抗性、debuff 抗性。
- 技能槽：SkillID、trigger key、伤害类型、AttackType、SPHitBase、DelayRatio、AI_CD、AI_ICD、PhaseList、ParamList、modifier/extra effect 列表。
- AI 与行动序列：AI task type、admission 状态、序列步骤、原始混淆字段、source trace。
- 执行边界：敌方回合 runtime execution 未 admission、目标选择未 admission、damage mutation 不允许。
- raw parameter blocks：`CustomValues`、`DynamicValues`、`OverrideSkillParams` 等原样保留。
- source trace：card、template、skill、sequence、AI。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_278 --output-dir /tmp/hsr_v8_monster_cards_v0_278 --example-output simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_278.json
git diff --check
```

结果：

- `compileall` 通过。
- `validate_v0_278` 通过，`ok=true`。
- `git diff --check` 通过。
- 完整示例卡包含身份、面板来源、弱点抗性、技能、AI/序列、执行边界和来源追踪。
- 负向检查确认普通怪物技能不会被 ILBattle 同 ID action definition 错误标成 executable。

## 未完成

- 示例卡仍不是完整怪物机制执行卡；它是完整数据卡和来源链样例。
- `MonsterSkillConfig -> ActionDefinitionIR -> ActionAbilityBindingIR -> DamageEmissionIR` 仍未 admission。
- 敌方回合、目标选择、复杂 AI、阶段、召唤、关卡等级和 HardLevelGroup 仍未接入。

## 后续最小纵切

下一步应先 admission 普通 `MonsterSkillConfig` 的 action definition，但必须与 ILBattle 分源，避免同 ID 污染。随后只对固定序列怪物接敌方 route 候选，目标由 route/推演器指定；缺目标、缺 ability binding 或复杂 AI 时继续 blocked，不产生 mutation。
