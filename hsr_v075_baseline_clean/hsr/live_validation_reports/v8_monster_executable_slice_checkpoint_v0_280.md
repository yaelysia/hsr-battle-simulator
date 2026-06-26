# v8 怪物可执行纵切 checkpoint v0_280

## 本阶段完成

- 接通普通怪物技能的通用可执行链路：
  `MonsterSkillConfig/MonsterSkillUniqueConfig -> ActionDefinitionIR -> ActionAbilityBindingIR -> AbilityPhaseIR/AbilityTaskIR -> DamageEmissionIR/ToughnessEmissionIR -> CombatExecutor`。
- 拆分怪物动作命名空间：
  - `monster_skill:<SkillID>` 只代表普通怪物技能表。
  - `ilbattle_monster_skill:<ID>` 只代表 `ILBattleMonsterSkill`。
  - 怪物 action set 不再因为 ID 相同借用 ILBattle 来源。
- 从 `MonsterTemplate.JsonConfig -> ConfigCharacter/Monster` 接入 `SkillTriggerKey`、`EntryAbility`、`SkillAbilityList` 和目标信息。
- 通过 ability name 的结构化索引定位 `Config/ConfigAbility/Monster/**/*.json`，缺失、歧义或未读到 ability 时保持 blocked。
- 将冰锋类 `AllEnemy` 目标结构化降为 `aoe`；未接目标类型仍 blocked。
- 新增怪物公式绑定：
  - `DynamicValues.Floats[*].ReadInfo.Type=SkillParam` 绑定 `MonsterSkillConfig.ParamList[Index]`。
  - `DamageByAttackProperty.AttackProperty.DamagePercentage` 作为直接伤害倍率来源。
  - `SPHitRatio * MonsterSkillConfig.SPHitBase` 作为削韧来源。
- `SkillFormulaBindingIR` 增加通用 `data_card_id`、`data_card_kind`、`owner_entity_ref`，保留旧 `character_data_card_id` 兼容角色验证。
- 新增 `validate_v0_280`，验证结构化筛选样例、手动 route 执行和负例边界。
- 更新怪物卡规范 `MONSTER_CARD_SPEC.md`，明确 v0_280 的普通怪物技能执行边界。

## 样例结果

样例卡：

`simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_280.json`

当前结构化选择实际选中：

- 中文名：`冰锋`
- 英文名：`Ice Edge`
- `MonsterID=1002011`
- `MonsterTemplateID=1002011`
- `Rank=MinionLv2`
- 技能：`100201101`
- 动作：`monster_skill:100201101`
- 技能名：`冰风 / Icy Wind`
- 目标：`AllEnemy -> aoe`
- 伤害：冰属性直接伤害，倍率来自 `ParamList[0]`
- 削韧：`SPHitBase=10` 乘 ability task 的 `SPHitRatio=1`
- ability 来源：`Config/ConfigAbility/Monster/Monster_W1_CocoliaP1_01_Ability.json`

该 ID 只作为报告结果；主路径选择按结构化谓词筛选，不按固定 MonsterID 或技能 ID。

## 执行验证

手动 route 让 `enemy:target` 释放 `monster_skill:100201101`，目标为 `ally:saber`。验证结果：

- action enabled。
- target resolution 命中 `ally:saber`。
- 产生 damage mutation。
- 产生 toughness mutation。
- settlement 中存在 damage record 和 toughness record。
- snapshot replay/source audit/static checks 通过。

## 负例与边界

- 缺怪物公式绑定的普通怪物技能仍 blocked，不产生假伤害。
- 未接目标类型仍 blocked，不产生 mutation。
- 复杂 AIPath 仍不是 executable。
- 普通怪物 action set 只接 `monster_skill:`，不借 `ilbattle_monster_skill:`。
- `validate_v0_278` 的旧边界检查已调整为“来源不混用”，不再要求普通怪物动作必须 blocked。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_277 --output-dir /tmp/hsr_v8_monster_cards_v0_277
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_280 --output-dir /tmp/hsr_v8_monster_executable_v0_280 --example-output simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_280.json
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_278 --output-dir /tmp/hsr_v8_monster_cards_v0_278 --example-output simulator_v8_clean_core/examples/monster_cards/simple_sequence_monster_card_v0_278.json
```

结果：

- `compileall` 通过。
- `validate_v0_277` 通过，`ok=true`。
- `validate_v0_280` 通过，`ok=true`。
- `validate_v0_278` 通过，`ok=true`。

## 未完成

- 敌方自动决策还没接；当前只支持 route/命令显式指定怪物动作和目标。
- 固定序列尚未接入 scheduler 敌方回合自动候选。
- 关卡等级、HardLevelGroup、波次、阶段、召唤、怪物被动、怪物专属 modifier 仍未接。
- 本阶段只证明冰锋类简单普通怪物技能纵切可执行，不代表全怪物技能都已 admission。

## 距离最小敌方行动纵切还缺

- 在 scheduler 中读取怪物卡固定序列，生成敌方动作候选。
- 目标仍由 route/推演器枚举，不做复杂 AI 目标选择。
- 给敌方动作补完整 blocked 传播：缺目标、缺 ability、缺公式、复杂 AI、死亡目标都保持 state unchanged。
- 增加最小敌方行动样例，证明敌方回合可按固定序列进入通用执行器。

## 距离完整复刻还缺

- 全怪物技能 ability graph admission。
- 复杂 AI、阶段内/跨阶段序列、随机、冷却、目标选择策略。
- 波次系统、关卡面板装配、HardLevelGroup/Level 公式。
- 召唤物、assistant、特殊玩法怪物、环境机制。
- 光锥、内外圈遗器及套装机制。
