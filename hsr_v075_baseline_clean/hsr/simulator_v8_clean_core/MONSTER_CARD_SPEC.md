# v8 怪物卡规范 v0_289

怪物卡是 TBGD 到 Canonical IR 的数据卡层，不是运行时规则系统，也不是完整敌方 AI 执行器。

## 边界

- 怪物卡构建层可以读取 TBGD raw 表、`Config/ConfigCharacter/Monster`、`Config/ConfigAbility/Monster`、`Config/ConfigAI`。
- 怪物卡构建层可以读取 TextMap 生成展示名和说明，但这些字段只能用于 UI/审计展示。
- runtime 只能读取 Canonical IR 中的 `MonsterDataCardIR`、`CombatantProfileIR`、`CombatantActionSetIR`、`ActionDefinitionIR`、`PassiveMechanismSlotIR`、`StatusEventFamilyIR`、`TargetExpressionIR` 等结构。
- runtime 禁止读取 raw TBGD、TextMap、旧 v7、旧 model pack。
- runtime 禁止按展示名、中文名、英文名、技能文本或说明文字驱动任何规则、目标选择、伤害、AI 或 mutation。
- 怪物机制不能写进核心系统特判；怪物专属内容必须先进入怪物卡机制/数据槽位，再接通用系统。
- 缺模板、缺技能、缺序列、缺 action definition、缺 ability binding、缺 target expression、复杂 AI 未 admission 时必须 blocked 或 process-only。

## 来源

怪物卡当前 admission 以下来源：

- `ExcelOutput/MonsterConfig.json`：怪物实例、技能列表、弱点、抗性、召唤、覆盖参数、Override AI、AbilityNameList。
- `ExcelOutput/MonsterTemplateConfig.json` 与 `MonsterTemplateUniqueConfig.json`：模板、Rank、基础面板、JsonConfig、默认 AIPath、默认 AISkillSequence。
- `ExcelOutput/MonsterSkillConfig.json` 与 `MonsterSkillUniqueConfig.json`：普通怪物技能定义、trigger key、伤害类型、phase、参数。
- `Config/ConfigAI/*.json`：AI 结构审计；当前只 admission `UseSequencedSkill` 固定序列。
- `Config/ConfigCharacter/Monster/*.json`：技能 trigger key、目标信息、入口 ability 与技能 ability 列表。
- `Config/ConfigAbility/Monster/**/*.json`：怪物 ability phase、task、effect、动态值读取路径、AddModifier、状态监听来源。
- `StatusConfig` / `MonsterStatusConfig` / modifier definition：状态定义、modifier、callback/listener。

`MonsterSkill.ModifierList` 不作为怪物被动来源。它只能作为技能相关来源保留和审计，不能混入 `AbilityNameList` 被动槽位。

## 卡内容

`MonsterDataCardIR` 必须保留：

- 身份：`monster_id`、`template_id`、`rank`、`entity_ref`。
- 展示：中文/英文名、技能名、说明字段必须标记为 display-only。
- 通用引用：`profile_id`、`action_set_id`。
- 技能：原始 `SkillList` 顺序、`SkillID`、`action_ref`、`SkillTriggerKey`、同 trigger key 技能组。
- 被动与机制入口：`passive_mechanism_slot_ids`、AbilityNameList raw path、ability graph 绑定、startup admission、blocked 原因。
- AI：`ai_path`、AI task type 摘要、固定序列 admission 状态、复杂 AI blocked 原因。
- 行动序列：序列来源、序列下标、原始混淆字段、技能 ID、是否在 SkillList 内、技能定义是否存在。
- 参数块：`CustomValues`、`DynamicValues`、`OverrideSkillParams` 等保持 raw block，不解释混淆字段含义。
- 来源：每个关键段落必须能回到 TBGD source path、raw type、raw id、row index。

## 动作与技能执行边界

普通怪物技能与 ILBattle 怪物技能必须分命名空间：

- `monster_skill:<SkillID>` 只代表 `MonsterSkillConfig` / `MonsterSkillUniqueConfig`。
- `ilbattle_monster_skill:<ID>` 只代表 `ILBattleMonsterSkill`。
- 怪物 action set 只能引用同源普通怪物技能动作，不能因为 ID 相同借用 ILBattle action definition。

普通怪物技能可执行纵切 admission 以下链路：

- `MonsterConfig.SkillList -> SkillID -> monster_skill:<SkillID>`。
- `MonsterTemplate.JsonConfig -> ConfigCharacter/Monster -> SkillTriggerKey -> EntryAbility/SkillAbilityList`。
- ability name 通过结构化索引唯一定位 `ConfigAbility/Monster/**/*.json`；缺失或歧义必须 blocked。
- `DamageByAttackProperty.AttackProperty.DamagePercentage` 作为直接伤害倍率来源。
- `DynamicValues.Floats[*].ReadInfo.Type=SkillParam` 绑定到 `MonsterSkillConfig.ParamList[Index]`。
- `SPHitRatio * MonsterSkillConfig.SPHitBase` 作为削韧来源。
- `AddModifier` 可通过已 admission 的 target expression 给目标附带状态；带 listener 的状态必须先通过状态监听 admission。

route/命令明确指定怪物动作和目标时，可以执行普通怪物技能。敌方自然回合不能自动猜目标。

## 固定序列行动候选

固定序列行动候选来自 `MonsterDataCardIR.action_sequence`：

- scheduler 轮到敌方自然回合时，`EnemyActionSystem` 可以生成只读 `EnemyActionCandidate`。
- 候选包含 actor、action_ref、action_level、sequence_index、target_mode、可选目标、source trace、blocked reason。
- 候选本身不产生 mutation，不代表 AI 已经选择目标。
- 外部用户、UI 或推演器选择目标后，生成标准 `ActionCommand`，继续走 `CombatExecutor`。
- 匹配候选的 command 成功执行后，才能推进 `enemy_action_sequence_cursor`。

blocked 情况包括：缺怪物卡、缺序列、缺 action definition、复杂 AIPath、目标模式未接通、无合法目标。

## 被动与状态监听边界

怪物机制入口分三类：

- `MonsterConfig.AbilityNameList`。
- `ConfigCharacter/Monster.SkillList` 中 `UseType=Passive` 的被动入口。
- 技能或状态挂载出的 modifier callback/listener。

`AbilityNameList` 只是怪物机制入口之一，不代表完整怪物被动。银鬃尉官反击已经证明真实链路可能是：

```text
技能挂状态 -> 状态监听受击事件 -> 条件判断 -> 插入反击 ability -> 反击执行
```

当前状态监听底座：

- `StatusEventFamilyIR` 覆盖 TBGD 中出现的 status callback event。
- mutation-backed 事件源已接 HP/治疗、护盾、SP、能量、韧性、状态生命周期、行动延后等已有底层 mutation。
- 只有事件源、事件 payload、条件、目标表达式、task、队列优先级全部 admission 时，listener 才能产生 mutation。
- 表现、镜头、音效、UI task 只能进入 coverage gap，不产生 mutation。
- `OnCustomEvent`、`OnWaveMonster`、特殊玩法、波次相关事件没有真实事件源时保持 blocked/process-only。

## 技能附带状态边界

怪物技能通过 `AddModifier` 附带状态时：

- 正例来源必须完整：`MonsterSkillConfig/MonsterSkillUniqueConfig -> ability task -> EffectIR(AddModifier) -> ModifierDefinition`。
- `AbilityTargetEntity`、明确群体目标、已 admission 的 `TargetExpressionIR` 可以解析为目标集合。
- 目标集合必须先完整解析；任一目标表达式 blocked 时整条 effect state unchanged。
- 缺 modifier、缺目标、缺动态值绑定、duration blocked、chance/stack/refresh 未 admission 时 blocked。
- modifier 自带 callback/listener 时，只有 listener 已 admission 才能挂成可触发状态；否则 blocked/process-only。

## 目标表达式边界

怪物技能、状态 callback、effect 消费目标时应优先使用 `target_expression_id`。

当前已接安全子集：

- 简单别名。
- 明确群体。
- `SkillTargetEntityList`。
- `ParamEntityList`。
- `TeamFormation`。
- `TargetSequence` / `TargetConcat`。
- 使用已 admission 条件的 `TargetFilter`。
- 确定性 `Retarget`。

仍 blocked：

- `TargetSort*`。
- `TargetFetch*`。
- 随机 retarget。
- 相邻目标。
- 召唤物/servant 目标。
- 唯一实体查询。
- 特殊玩法目标。
- 需要未实现状态语义的过滤条件。

`Retarget` 当前只影响本次 effect/callback 的目标解析，不改写整次 action 的主 target resolution。

## 第一版 AI admission

第一版只允许以下 AI 策略进入可审计固定序列：

- AI 文件包含 `RPG.GameCore.UseSequencedSkill`。
- AI 文件不包含 `UseSkill`、`SelectAISkillTarget`、随机、stepper、技能可用性轴等复杂决策任务。
- 行动序列来自 `MonsterConfig.OverrideAISkillSequence`，没有 override 时来自模板 `AISkillSequence`。
- 序列技能必须能在对应 `SkillList` 和怪物技能表中找到。

满足条件只表示固定序列来源已 admission；不表示完整敌方 AI 已完成。目标选择和分支推演由 UI/用户/推演器后续显式完成。

## 禁止项

- 禁止按怪物名、固定 MonsterID、固定 SkillID、固定 AIPath 白名单驱动 runtime。
- 禁止按 TextMap 名称、技能名、描述文本驱动 runtime。
- 禁止把复杂 AIPath 简化成固定序列执行。
- 禁止把技能 `ModifierList` 当作被动来源。
- 禁止把 `AbilityNameList` 当成完整被动系统。
- 禁止让带事件 trigger 的状态在 listener admission 不完整时进入可触发状态。
- 禁止把混淆字段名改成自造语义后作为规则来源。
- 禁止用观测结果或旧 v7 行为补怪物技能、目标选择、倍率或 AI。
- 禁止在敌方自动行动未接通时产生怪物伤害 mutation。
- 禁止候选生成时推进行动序列 cursor。
- 禁止 target expression 失败后 fallback 到默认目标继续挂状态或造成伤害。
