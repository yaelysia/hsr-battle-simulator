# v8 monster card admission checkpoint v0_277

## 本阶段完成

- 新增怪物卡规范 `simulator_v8_clean_core/MONSTER_CARD_SPEC.md`。
- 新增 `MonsterDataCardIR`，并接入 `CanonicalIR`、`RuleBook` 和 TBGD lowering。
- 新增 `tbgd/monster_cards.py`，从 `MonsterConfig`、`MonsterTemplateConfig`、`MonsterTemplateUniqueConfig`、`MonsterSkillConfig`、`MonsterSkillUniqueConfig`、`ConfigAI` 构建怪物卡。
- 第一版只 admission `UseSequencedSkill` 固定序列 AI；复杂 AIPath 保持 blocked，不执行。
- 怪物技能槽保留 `SkillList` 顺序、`SkillID`、`action_ref`、`SkillTriggerKey`、同 trigger key 技能组、技能参数和 source trace。
- 行动序列保留原始混淆字段、序列来源、技能 ID、是否在 SkillList 内、技能定义是否存在。
- `CustomValues`、`DynamicValues`、`OverrideSkillParams` 等保留 raw parameter block，不解释混淆字段含义。

## 验证结果

命令：

```bash
cd hsr_v075_baseline_clean/hsr
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_277 --output-dir /tmp/hsr_v8_monster_cards_v0_277
```

结果：

- `compileall` 通过。
- `validate_v0_277` 通过，`ok=true`。
- 生成怪物卡：2509，对齐 `MonsterConfig` 行数。
- 固定序列 AI admission：724。
- 怪物卡 coverage：709 lowered，1800 blocked。
- 结构化样例选择策略：普通模板、固定序列 AI、单技能、无召唤、无 custom/dynamic/override 参数、序列技能在 SkillList 内且技能定义存在。
- 当前样例实际选中：`MonsterID=1002011`、`MonsterTemplateID=1002011`、`Rank=MinionLv2`。该 ID 只作为报告结果，不作为选择条件。
- 复杂 AI blocked 样例实际选中：`MonsterID=1002020`。

## 未完成

- 敌方回合尚未由怪物卡驱动；scheduler/UI 中敌方临时跳过逻辑仍是测试台行为。
- 怪物技能 `MonsterSkillConfig` 还没有接入完整 ActionDefinition/Ability binding 执行链。
- 复杂 AI 未 admission，包括 `UseSkill`、`SelectAISkillTarget`、阶段判断、随机、stepper、技能可用性轴等。
- `StageConfig.Level` 与 `HardLevelGroup` 尚未接入怪物面板装配。
- 召唤、阶段切换、怪物专属 modifier、特殊玩法怪物仍未完整执行。

## 距离最小敌方行动纵切还缺

- 将固定序列怪物卡转换成可 route 的敌方动作候选，但目标仍由 route/推演器指定。
- 为 `MonsterSkillConfig` 建立安全的 action definition admission，明确技能参数、phase、ability graph 与 blocked 条件。
- 在 scheduler 中加入敌方回合读取怪物卡下一序列动作的通用路径；复杂 AI 继续 blocked，不 fallback。
- 增加敌方动作负例：缺技能、缺目标、复杂 AI、死亡目标、未接 ability binding 时不产生 mutation。

## 距离完整复刻还缺

- 全量怪物技能 ability graph 执行、怪物状态/被动、召唤物、阶段系统。
- 复杂 AI 决策、目标选择、阶段内/跨阶段序列、随机和冷却策略。
- 关卡波次、StageConfig 装配、HardLevelGroup/Level 面板公式。
- 光锥、遗器、环境、关卡机制与特殊玩法模式。
