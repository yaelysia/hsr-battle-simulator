# v8 怪物卡规范 v0_277

怪物卡是 TBGD 到 Canonical IR 的数据卡层，不是运行时规则系统，也不是敌方 AI 执行器。

## 边界

- 怪物卡构建层可以读取 TBGD raw 表和 `Config/ConfigAI`。
- runtime 只能读取 Canonical IR 中的 `MonsterDataCardIR`、`CombatantProfileIR`、`CombatantActionSetIR` 等结构。
- runtime 禁止读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- 怪物机制不能写进核心系统特判；怪物专属内容必须先进入怪物卡机制/数据槽位，再接通用系统。
- 缺模板、缺技能、缺序列、复杂 AI 未 admission 时必须 blocked 或 process-only，不能为了让敌方行动可跑而猜规则。

## 来源

第一版怪物卡只 admission 以下来源：

- `ExcelOutput/MonsterConfig.json`：怪物实例、技能列表、弱点、抗性、召唤、覆盖参数、Override AI。
- `ExcelOutput/MonsterTemplateConfig.json` 与 `MonsterTemplateUniqueConfig.json`：模板、Rank、基础面板、JsonConfig、默认 AIPath、默认 AISkillSequence。
- `ExcelOutput/MonsterSkillConfig.json` 与 `MonsterSkillUniqueConfig.json`：技能定义、trigger key、伤害类型、phase、参数。
- `Config/ConfigAI/*.json`：AI 结构审计，第一版只 admission `UseSequencedSkill` 固定序列。

## 卡内容

`MonsterDataCardIR` 必须保留：

- 身份：`monster_id`、`template_id`、`rank`、`entity_ref`。
- 通用引用：`profile_id`、`action_set_id`。
- 技能：原始 `SkillList` 顺序、`SkillID`、`action_ref`、`SkillTriggerKey`、同 trigger key 技能组。
- AI：`ai_path`、AI task type 摘要、固定序列 admission 状态、复杂 AI blocked 原因。
- 行动序列：序列来源、序列下标、原始混淆字段、技能 ID、是否在 SkillList 内、技能定义是否存在。
- 参数块：`CustomValues`、`DynamicValues`、`OverrideSkillParams` 等保持 raw block，不解释混淆字段含义。
- 来源：每个关键段落必须能回到 TBGD source path、raw type、raw id、row index。

## 第一版 AI admission

第一版只允许以下 AI 策略进入可审计固定序列：

- AI 文件包含 `RPG.GameCore.UseSequencedSkill`。
- AI 文件不包含 `UseSkill`、`SelectAISkillTarget`、随机、stepper、技能可用性轴等复杂决策任务。
- 行动序列来自 `MonsterConfig.OverrideAISkillSequence`，没有 override 时来自模板 `AISkillSequence`。
- 序列技能必须能在对应 `SkillList` 和怪物技能表中找到。

满足条件时，只表示固定序列来源已 admission；不表示敌方回合运行时已接通。敌方实际出手、目标选择和推演枚举后续单独实现。

## 禁止项

- 禁止按怪物名、固定 MonsterID、固定 SkillID、固定 AIPath 白名单驱动 runtime。
- 禁止把复杂 AIPath 简化成固定序列执行。
- 禁止把混淆字段名改成自造语义后作为规则来源。
- 禁止用观测结果或旧 v7 行为补怪物技能、目标选择、倍率或 AI。
- 禁止在敌方行动未接通时产生怪物伤害 mutation。
