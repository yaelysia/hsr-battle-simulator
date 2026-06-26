# v8 怪物卡规范 v0_281

怪物卡是 TBGD 到 Canonical IR 的数据卡层，不是运行时规则系统，也不是敌方 AI 执行器。

## 边界

- 怪物卡构建层可以读取 TBGD raw 表和 `Config/ConfigAI`。
- 怪物卡构建层可以读取 TextMap 生成展示名和说明，但这些字段只能用于 UI/审计展示。
- runtime 只能读取 Canonical IR 中的 `MonsterDataCardIR`、`CombatantProfileIR`、`CombatantActionSetIR` 等结构。
- runtime 禁止读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- runtime 禁止按展示名、中文名、英文名、技能文本或说明文字驱动任何规则、目标选择、伤害、AI 或 mutation。
- 怪物机制不能写进核心系统特判；怪物专属内容必须先进入怪物卡机制/数据槽位，再接通用系统。
- 缺模板、缺技能、缺序列、复杂 AI 未 admission 时必须 blocked 或 process-only，不能为了让敌方行动可跑而猜规则。

## 来源

怪物卡当前 admission 以下来源：

- `ExcelOutput/MonsterConfig.json`：怪物实例、技能列表、弱点、抗性、召唤、覆盖参数、Override AI。
- `ExcelOutput/MonsterTemplateConfig.json` 与 `MonsterTemplateUniqueConfig.json`：模板、Rank、基础面板、JsonConfig、默认 AIPath、默认 AISkillSequence。
- `ExcelOutput/MonsterSkillConfig.json` 与 `MonsterSkillUniqueConfig.json`：技能定义、trigger key、伤害类型、phase、参数。
- `Config/ConfigAI/*.json`：AI 结构审计，第一版只 admission `UseSequencedSkill` 固定序列。
- `Config/ConfigCharacter/Monster/*.json`：技能 trigger key、目标信息、入口 ability 与技能 ability 列表。
- `Config/ConfigAbility/Monster/**/*.json`：怪物 ability phase、task、effect、动态值读取路径。
- `MonsterConfig.AbilityNameList`：怪物被动入口；只作为被动来源，不与技能 `ModifierList` 混用。

## 动作与技能执行边界

v0_280 起普通怪物技能与 ILBattle 怪物技能必须分命名空间：

- `monster_skill:<SkillID>` 只代表 `MonsterSkillConfig` / `MonsterSkillUniqueConfig`。
- `ilbattle_monster_skill:<ID>` 只代表 `ILBattleMonsterSkill`。
- 怪物 action set 只能引用同源普通怪物技能动作，不能因为 ID 相同借用 ILBattle action definition。

普通怪物技能可执行纵切只 admission 以下链路：

- `MonsterConfig.SkillList -> SkillID -> monster_skill:<SkillID>`。
- `MonsterTemplate.JsonConfig -> ConfigCharacter/Monster -> SkillTriggerKey -> EntryAbility/SkillAbilityList`。
- ability name 通过结构化索引唯一定位 `ConfigAbility/Monster/**/*.json`；缺失或歧义必须 blocked。
- `DamageByAttackProperty.AttackProperty.DamagePercentage` 作为直接伤害倍率来源。
- `DynamicValues.Floats[*].ReadInfo.Type=SkillParam` 绑定到 `MonsterSkillConfig.ParamList[Index]`。
- `SPHitRatio * MonsterSkillConfig.SPHitBase` 作为削韧来源。

当前只接通显式 route/命令指定怪物释放某个 `monster_skill:<SkillID>` 的执行；敌方自动决策、自动选目标、复杂 AI、波次驱动仍未 admission。

## 被动槽位与执行边界

v0_281 起怪物被动进入通用 `PassiveMechanismSlotIR`：

- 怪物被动来源只承认 `MonsterConfig.AbilityNameList`。
- `MonsterSkill.ModifierList` 属于技能附带效果来源，本阶段不作为被动来源。
- ability name 必须唯一定位到 `Config/ConfigAbility/Monster/**/*.json`；缺失或歧义必须 blocked。
- 第一阶段只 admission 根级 `OnStart` 下的 `AddModifier`，且目标别名只允许 `Caster` / `ModifierOwnerEntity`。
- AddModifier 若请求动态值但没有结构化绑定，必须 blocked，不允许自造默认值。
- 将要添加的 modifier 若带事件 trigger，必须 blocked，避免事件类被动在未 admission 时被现有事件分发系统误执行。
- 事件触发、阶段、召唤、锁血、插队、波次相关被动只降槽位和覆盖报告，不产生 mutation。

成功 admission 的开场常驻被动由 scenario 构建阶段转成 startup spec，并复用：

`StandaloneAbilityGraphIR -> AbilityTaskIR -> EffectIR(AddModifier) -> StatusSystem.apply_add_modifier`

## 卡内容

`MonsterDataCardIR` 必须保留：

- 身份：`monster_id`、`template_id`、`rank`、`entity_ref`。
- 通用引用：`profile_id`、`action_set_id`。
- 技能：原始 `SkillList` 顺序、`SkillID`、`action_ref`、`SkillTriggerKey`、同 trigger key 技能组。
- 被动：`passive_mechanism_slot_ids`、AbilityNameList raw path、ability graph 绑定、startup admission、blocked 原因。
- AI：`ai_path`、AI task type 摘要、固定序列 admission 状态、复杂 AI blocked 原因。
- 行动序列：序列来源、序列下标、原始混淆字段、技能 ID、是否在 SkillList 内、技能定义是否存在。
- 参数块：`CustomValues`、`DynamicValues`、`OverrideSkillParams` 等保持 raw block，不解释混淆字段含义。
- 来源：每个关键段落必须能回到 TBGD source path、raw type、raw id、row index。
- 展示：中文/英文名、技能名、技能类型、技能标签、技能说明必须标记为 display-only，不得作为 runtime rule source。

## 第一版 AI admission

第一版只允许以下 AI 策略进入可审计固定序列：

- AI 文件包含 `RPG.GameCore.UseSequencedSkill`。
- AI 文件不包含 `UseSkill`、`SelectAISkillTarget`、随机、stepper、技能可用性轴等复杂决策任务。
- 行动序列来自 `MonsterConfig.OverrideAISkillSequence`，没有 override 时来自模板 `AISkillSequence`。
- 序列技能必须能在对应 `SkillList` 和怪物技能表中找到。

满足条件时，只表示固定序列来源已 admission；不表示敌方回合运行时已接通。敌方实际出手、目标选择和推演枚举后续单独实现。v0_280 允许测试 route 显式指定怪物动作和目标来验证普通怪物技能执行链路，但不能把这一步伪装成敌方 AI。

## 禁止项

- 禁止按怪物名、固定 MonsterID、固定 SkillID、固定 AIPath 白名单驱动 runtime。
- 禁止按 TextMap 名称、技能名、描述文本驱动 runtime。
- 禁止把复杂 AIPath 简化成固定序列执行。
- 禁止把技能 `ModifierList` 当作被动来源。
- 禁止让带事件 trigger 的被动状态在事件类被动 admission 前进入可触发状态。
- 禁止把混淆字段名改成自造语义后作为规则来源。
- 禁止用观测结果或旧 v7 行为补怪物技能、目标选择、倍率或 AI。
- 禁止在敌方自动行动未接通时产生怪物伤害 mutation；只有 route/命令明确指定动作和目标，且 action definition、ability binding、公式、目标、伤害/削韧 emission 全部来源审计通过时，才允许产生 mutation。
