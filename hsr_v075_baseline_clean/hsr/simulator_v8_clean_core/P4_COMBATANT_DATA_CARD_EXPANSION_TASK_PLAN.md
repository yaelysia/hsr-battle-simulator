# P4 角色卡 / 怪物卡数据卡扩面分步计划

本文档是 P4 的执行计划，面向一个没有前文上下文的新执行线程，也面向夜间 goal 模式长时间自动推进。

P4 的核心任务不是重新发明角色卡或怪物卡底层，而是在现有 `CharacterDataCardIR`、`MonsterDataCardIR`、`CombatantProfileIR`、`CombatantActionSetIR`、`ActionDefinitionIR`、`SkillFormulaBindingIR` 等底座之上，做角色 / 怪物机制覆盖扩面、来源分类、admission 补全和验证闭环。

本阶段必须延续 P1 / P2 / P3 已经形成的严格口径：有真实来源且语义已通用化的路径才能 executable；缺来源、缺条件、缺目标、缺公式、缺动态值绑定、缺事件 payload、缺 action admission 时必须 blocked / process-only / state unchanged；不能用固定角色名、怪物名、技能 ID、文件名、hash、文本或观测答案凑正例。

## 使用方式

第 6.1 节和第 22 节是 P4 唯一执行清单。第 7 到第 19 节是各阶段的设计参考和验收参考，不是允许执行线程自行打勾的并行 checklist。

执行线程一次只能执行一个 P4-Sx 阶段。每个阶段开始前必须先提交“阶段执行卡”，等待规划 / 验收线程确认后才能改文件。执行卡必须具体到可执行动作，不能复述本文档条款。

执行线程最多只能提交 `ready_for_review`，不能自称 `done`，不能修改第 22 节 checklist，不能把 `[ ]` 改成 `[x]`。阶段完成标记只能由验收线程在复核代码、验证输出、矩阵/summary、source/audit evidence 后更新。

`ok=true` 不是完成证明。报告也不是完成证据本身，只能作为证据索引。验收时必须解释验证实际检查了什么、没检查什么、predicate 是否过宽、是否把 gap 用 executable 正例覆盖。

资源控制是限制峰值，不是跳过必要验证。必要长验证可以串行、低优先级、输出到 `/tmp` 运行；禁止并行重验证、默认写大产物或跑无关全量。

## 0. 背景和当前事实

P1 已完成最小战斗纵切：

- action boundary、ability task、effect、damage、resource、queue、timeline、target、BattleSetup、snapshot/replay/source audit 的基础骨架已经可用。
- P1-9 聚合通过，`phase1_minimum_battle_slice=true`。
- 敌方 AI 不进入 core；敌方、召唤怪物和 servant 的动作选择由外部推演器控制。

P2 已完成状态系统底座：

- 状态来源、普通生命周期、叠层/刷新/持续时间、概率/抵抗/免疫、驱散、DoT/状态伤害、callback queue、dynamic value 等底座已完成当前闭环。
- P2 聚合通过，implementation / lowering / admission / validation gap 为 0。
- P2 完成不等于全角色、全怪物、全装备、全关卡状态机制都已复刻。

P3 已完成召唤物 / 忆灵底座闭环：

- summoned monster source-backed spawn、runtime registry、fixed-sequence action availability、target relation、replay、source audit 已有正例。
- servant / 忆灵 definition、owner/stat/lifecycle、spawn/remove、action availability、status holder、BattleSetup initial setup 和 scenario route 已可验证。
- `SummonUnitData` / `ConfigSummonUnit` catalog 和非 battle 来源保持 boundary，不会自动 spawn。
- AssistantAvatar / `TurnInsertAssistantAbility` 已移出 P3 summon/servant 验收，作为独立 out-of-scope 记录。
- P3 当前是底座闭环验收通过，不是全正例完成：仍有 summon target / summoned monster intent 的 admission/source-gap backlog，需要在角色卡、怪物卡、target、dynamic/custom value 绑定扩面中持续收敛。

现有角色卡底座不是空白：

- `CharacterDataCardIR` 已存在。
- 已有角色卡边界、公式槽位、行迹/星魂通用接口。
- 加强版希儿示例卡已有普攻、战技、终结技、击杀额外回合、部分行迹 / 星魂机制纵切。
- 这不代表全角色机制已经解释或可执行。

现有怪物卡底座也不是空白：

- `MonsterDataCardIR` 和 `MONSTER_CARD_SPEC.md` 已存在。
- 普通怪物技能、ILBattle 怪物技能、固定序列行动候选、怪物技能附带状态已有纵切。
- P3 已让 summoned monster 可以接到怪物卡 profile/card、行动候选和 source audit。
- 这不代表全怪物技能、全怪物被动、阶段切换、特殊目标、动态值绑定都已完成。

## 1. P4 总目标

P4 的目标是把角色 / 怪物数据卡从“已有底层和少量纵切”扩成“可持续接入全角色 / 全怪物机制的稳定底座”。

具体目标：

- 建立角色卡 / 怪物卡来源总账本，覆盖 raw TBGD、Canonical IR、RuleBook、runtime admission、validation 五层。
- 把现有数据卡契约查清：哪些来源已经 executable，哪些只是 discovery / audit / boundary，哪些是 implementation / lowering / admission / validation gap。
- 补齐数据卡和通用系统之间的关键桥梁：action set、action availability、formula binding、dynamic/custom value、target admission、status listener、resource ownership、summon/servant 交叉引用。
- 让执行线程能按结构化谓词选择真实正例，而不是继续依赖希儿、某个怪物、某个技能或固定文件。
- 把 P3 暴露出的 summon target / summoned monster intent 缺口纳入 P4 backlog，但不能为了 P4 通过把它们改名隐藏。
- 为后续全角色、全怪物、光锥、遗器、关卡环境提供干净接入面。

P4 不要求一次完成全角色 / 全怪物所有机制。P4 要完成的是数据卡扩面底座和来源闭环，让后续批量接入可以稳定推进。

### 1.1 P4 必须预留但不完整实现的接入点

P4 需要把后续扩展入口做成真实预留，但不能把完整装备、关卡环境或推演器实现塞进本阶段。

“真实预留”不是加一个空字段，也不是口头说以后会接。合格预留必须同时满足：

- 有明确归属：知道未来由哪个数据卡、子卡或环境层负责。
- 有稳定 slot 或 hook：后续接入时不需要推翻当前 IR / RuleBook / runtime 边界。
- 有 admission 边界：当前未实现完整机制时能 blocked / process-only / state unchanged。
- 有负例验证：证明缺来源、缺构筑输入、缺环境来源、缺 owner、缺 action、缺 target 时不会假执行。
- 有 scope 记录：说明是 P4 boundary、后续阶段 backlog、还是 out_of_scope。

P4 至少要明确以下归属：

- 装备与构筑输入：预留为角色卡 / 怪物卡的装配输入。角色侧包括光锥、遗器、套装、等级、晋阶、行迹、星魂；怪物侧包括等级、模板、阶段和特殊覆盖，弱点、抗性、韧性等由怪物卡 / 关卡覆盖来源投影为结果字段，不能被设计成 UI 或推演器随手填写的普通输入。P4 不实现光锥 / 遗器 / 套装完整机制，但数据卡 assembly 不能被设计成只能接裸角色或裸怪物。
- 角色召唤物：归属角色卡。servant / 忆灵这类有独立属性、技能、行动和生命周期的单位，应预留角色卡下的子卡或派生 combatant card 入口；不能把它们当普通 buff，也不能塞进推演器逻辑。
- 怪物召唤物：优先复用已有怪物卡。召唤者负责 spawn intent、owner/summoner relation、生命周期和清理策略；被召唤单位自身的属性、技能、状态和行动仍来自怪物卡，不复制一套特殊子卡，除非 raw TBGD 证明它不是已有怪物。
- 动作查询：归属可行动单位的数据卡或子卡，例如角色、怪物、servant、召唤怪物。除特殊场地机制外，推演器不直接制造动作。
- 目标查询：归属 action definition。每个 action 应暴露自己的合法目标、目标选择规则和实际打击范围；推演器只选择目标，不解释目标规则。
- 关卡 / 环境 / 战斗事件：单独归属后续 stage/environment 层。P4 只记录它们对角色 / 怪物数据卡的影响入口和 out-of-scope 边界，不把环境规则伪装成角色或怪物机制。
- 推演器调用边界：推演器定位为“像玩家一样操作和看结果”的外部控制器。它可以查询合法动作、选择动作和目标、指定或枚举 RNG 分支、读取 transition，但不能负责技能可用性、目标解析、状态结算、伤害公式或敌方 AI。

当前 `turnbasedgamedata-main` 是 release data dump：包含角色、怪物、技能、状态、装备、遗器、召唤物、关卡和战斗事件等配置；目前没有发现可直接调用的完整 battle engine。因此 v8 仍必须把 TBGD 配置 lowering 成 Canonical IR，再由 runtime 执行可审计的状态转移。

## 2. P4 非目标

本阶段不做：

- 敌方 AI、自动选招策略、自动目标策略。core 只暴露合法动作和约束，动作选择由外部推演器控制。
- 光锥、遗器、内外圈套装、环境、关卡机制完整复刻。
- 推演器搜索、剪枝、评分函数、目标函数、路线发现或敌方策略。
- 全角色机制人工解释完成。
- 全怪物技能和全怪物被动全正例完成。
- 用 TextMap、技能描述、攻略、观测伤害或旧 v7 输出作为 runtime 规则来源。
- 把旧 model pack、旧 CLI、旧 JSON、旧 Python API 作为兼容目标。
- 在 core 里写角色名、怪物名、技能名、技能 ID、MonsterID、文件名、hash 特判。

如果 P4 过程中发现某机制其实属于光锥、遗器、关卡、环境、AssistantAvatar、推演器或特殊玩法，必须进入 `out_of_scope` 或后续阶段 backlog；不能为了当前阶段完成把它塞进角色/怪物卡 runtime。

## 3. 分类口径

P4 所有来源域、机制域和样例都必须使用以下分类，不能使用含糊的“已处理”“已覆盖”“可用”。

- `executable`：当前数据库有真实来源，lowering 已投影，RuleBook 可查，runtime 只读 IR/数据卡即可执行，mutation / settlement / replay / source audit 均通过。
- `boundary_only`：当前阶段只需要证明边界，runtime 必须 blocked / process-only / state unchanged，不能产生规则 mutation。
- `source_absent_not_required`：当前数据库没有对应战斗 runtime 结构化来源，且不属于 P4 必须执行路径。
- `source_gap_blocked`：raw / IR 指向的进一步来源不存在或缺失，例如 profile/card/stat/source file 缺失；runtime 必须 blocked，不能补默认值。
- `lowering_gap`：raw 有来源，但 lowering 没投影或投影丢字段。
- `admission_gap`：IR 有来源，但 RuleBook、admission 谓词或通用语义不够，暂不能 executable。
- `validation_gap`：runtime 语义已支持，但验证脚本选样、断言或审计不足。
- `implementation_missing`：有真实来源且应可执行，但 runtime 还没有正确执行语义。
- `out_of_scope`：不属于 P4 角色/怪物数据卡扩面范围，但必须记录 raw / IR / RuleBook 可见性和后续归属。

标记 `source_absent_not_required`、`source_gap_blocked` 或 `out_of_scope` 前，必须先排除 lowering gap、admission gap 和 validation gap。不能把“脚本没扫到”当成“数据库没有来源”。

## 4. P4 完成口径

P4 必须拆成两层验收，禁止混用：

### 4.1 P4 底座闭环通过

允许 P4 底座闭环通过时，必须满足：

- P4-S0 到 P4-S12 的分步验证均通过。
- 所有角色 / 怪物数据卡相关来源域都有分类矩阵，`unclassified_count=0`。
- P4 必须预留的接入点都有明确归属、slot/hook、blocked 边界和负例验证；不能只写文档声明。
- 所有 final source/mechanism matrix 必须继承分步矩阵中的真实 gap；不能用宽域 executable 正例覆盖内部子项 gap。
- `implementation_missing=0`、`lowering_gap=0`、`validation_gap=0`、`unclassified=0`。
- 如果仍有 `admission_gap` 或 `source_gap_blocked`，必须进入 allowed gap evidence matrix，并说明：
  - raw 是否存在。
  - IR 是否投影。
  - RuleBook 是否可见。
  - 为什么当前不能 executable。
  - runtime blocked / process-only / state unchanged 证据。
  - 后续归属。
- 所有 executable 样例必须通过 source audit 和 replay。
- 所有 blocked 样例必须证明 state unchanged。
- 验证脚本默认只写 summary、matrix、抽样 case 和必要审计记录，不写完整 Canonical IR 或全量 transition dump。

P4 底座闭环通过不等于全角色 / 全怪物全正例完成。

### 4.2 P4 全正例完成

只有满足以下条件，才能宣称 P4 全正例完成：

- `p4_all_executable_complete=True`。
- `admission_gap=0`。
- `source_gap_blocked=0`。
- 每个当前数据库内角色 / 怪物数据卡相关来源都有 executable 正例，或被明确证明不属于战斗 runtime。

P4 初始执行不应把全正例完成作为默认目标。全正例更适合作为后续长线收敛目标。

## 5. 红线约束

P4 执行线程必须遵守：

- runtime 禁止读取 raw TBGD、TextMap、技能文本、旧 v7、旧 model pack。
- raw TBGD 只能在 lowering、discovery、审计工具层读取。
- 技能文本解释只能发生在数据卡构建层或人工机制槽位配置层，不能进入 runtime。
- 不允许用角色名、怪物名、技能名、固定 ID、固定 hash 作为 runtime 主路径。
- 不允许把“推演器以后会处理”当作 runtime 缺规则的理由；推演器只能选择合法操作和读取结果，不能补底层规则。
- 不允许把装备、构筑、召唤物或环境接入点做成无 admission、无负例、无后续归属的空占位。
- 验证样例必须优先按结构化谓词选择，例如 source kind、opcode、ability task、action kind、target alias kind、formula binding kind、coverage status、admission status。
- 不能为了让验证通过合成不存在的 TBGD 正例。
- 不能把 `engine_convention` 伪装成 TBGD 来源。
- 不能把 `audit_only`、`discovered_only`、`blocked`、placeholder 当成 executable。
- 不能只记录 applied term，不记录 skipped / blocked term。
- 不能只看字段完整或 replay 通过就宣布语义正确；必须审 source trace 指向的 IR 节点是否真实。
- 如果旧回归验证因为 P4 新语义而失败，先判断是否是旧断言过期；若是，修验证口径并记录原因，不能反向否定新机制。
- 如果 P4 新机制导致 P1/P2/P3 真实能力退化，必须修 runtime 或 lowering，不能通过改旧验证掩盖。

## 6. 阶段拆分

```text
P4-S0  角色 / 怪物数据卡来源总账本与范围定界
P4-S1  CharacterDataCard / MonsterDataCard / RuleBook 契约复核
P4-S2  Combatant action set 与 action availability 扩面
P4-S3  公式、技能参数、dynamic value / custom value 绑定总账
P4-S4  角色 / 怪物 target alias、TargetQuery、fetch/sort admission 扩面
P4-S5  怪物技能 action graph 覆盖扩面
P4-S6  怪物被动、监听、阶段、波次、召唤交叉边界
P4-S7  角色基础动作、天赋、秘技、强化形态机制槽位扩面
P4-S8  行迹、星魂、等级提升、开局机制与角色资源槽位扩面
P4-S9  数据卡状态、资源、伤害、击杀归因联动
P4-S10 P3 backlog 回收：summon target 与 summoned monster intent
P4-S11 未来外部推演器 action/query 调用契约样例，不实现推演器
P4-S12 P4 聚合验收、报告、交接和后续 backlog
```

### 6.1 阶段执行协议

阶段状态只允许五种：

- `not_started`：未开始。
- `in_progress`：当前唯一正在执行的阶段。
- `ready_for_review`：执行线程认为本阶段已可验收，但尚未由验收线程确认。
- `blocked`：本阶段因缺依赖、缺接口或方向不明无法继续，必须写明 blocker 和下一步归属。
- `done`：验收线程确认本阶段所有完成项均可打勾，且不触发本阶段红线。

每个 P4-Sx 阶段开始前，执行线程必须先提交阶段执行卡，并等待确认后再改文件：

```text
阶段：
目标产物：
本阶段只改哪些文件：
本阶段禁止改哪些文件：
将新增/修改哪些函数、类型、脚本或报告：
用哪些结构化谓词判断通过：
哪些情况必须判定为 blocked/gap/deferred：
要跑哪些验证，为什么这些验证足够：
哪些验证本阶段明确不跑，原因是什么：
预计资源风险和限峰值措施：
完成后提交哪些 evidence：
```

阶段执行卡必须写成执行设计，不能复述本文档原文。比如 P4-S0 不能只说“建立来源账本”，必须说明 raw 层扫哪些结构化入口、IR 层查哪些容器、RuleBook 层查哪些 accessor、gap 如何分类、输出哪些 summary/matrix、哪些 predicate 失败会阻止 `ready_for_review`。

执行线程完成实现后，只能提交 `ready_for_review` 汇报，内容包括：

- 实际改动文件。
- 实际新增 / 修改的函数、脚本、报告。
- 实际运行命令和输出路径。
- 每个完成项对应的 evidence。
- 未完成项、gap、blocked、deferred。
- 验证盲区和没有运行的验证。

验收线程复核通过后，才允许更新第 22 节 checklist。任何阶段未 `done` 前，不允许开始下一个阶段的实现。P4-S12 聚合入口只能在 S0-S11 均已 `done` 后实现和运行；不能提前写聚合脚本来替代分步工作。

## 7. P4-S0 角色 / 怪物数据卡来源总账本与范围定界

### 目标

建立 P4 总账本。执行线程在改 runtime 或 lowering 前，必须知道当前数据库中哪些来源属于角色卡、怪物卡、通用 combatant profile、action set、ability graph、formula、dynamic/custom value、target、passive/listener、resource、summon/servant 交叉引用。

### 必须覆盖

- 角色基础配置：`AvatarConfig`、`AvatarConfigLD`、`AvatarConfigEnhanced`、`AvatarPromotionConfig`、`AvatarSkillConfig`、`CommonAvatarSkillConfig`。
- 角色机制配置：行迹、星魂、秘技、开局状态、强化形态、动态值读取、技能参数绑定、角色 ability/config 文件。
- servant / 忆灵与角色卡关系：只记录与 owner 角色卡相关的来源，不重做 P3。
- 怪物基础配置：`MonsterConfig`、`MonsterTemplateConfig`、怪物属性、弱点、抗性、技能列表、召唤引用。
- 怪物技能来源：普通怪物技能、ILBattle 怪物技能、怪物 ability/config 文件、固定行动序列。
- 怪物被动和监听：global modifier、startup、on enter battle、on wave、on death、on hit、phase/skill trigger。
- combatant action set：角色、怪物、servant 的 entity_ref 到 action_ref 映射。
- 公式和参数：skill formula binding、damage percentage、break/toughness、healing/shield/hp loss、resource cost/gain。
- dynamic/custom value：hash、read info、param list、skill tree param、monster custom values、modifier dynamic hashes。
- target 来源：角色/怪物专属 alias、组合 alias、TargetQuery、fetch/sort/filter/retarget。
- 未来构筑入口：角色装备/遗器/套装装配 hook，怪物等级/模板/阶段/覆盖输入 hook。
- 子单位归属：角色 servant / 忆灵子卡入口，怪物 summoned monster 到已有怪物卡的生命周期绑定入口。
- P3 backlog：summon target expression、summoned monster intent admission/source-gap。
- 明确 out-of-scope：光锥、遗器、关卡环境、AssistantAvatar、UI-only 展示、纯客户端/视觉配置。

### 阶段验收参考

- 输出轻量来源矩阵，至少包含 source domain、raw count、IR count、RuleBook visible count、executable count、blocked/gap count、sample source trace。
- 每个来源域都有分类，`unclassified_count=0`。
- 每个 gap 都有分层归因，不允许只写“未支持”。
- AssistantAvatar、光锥、遗器、关卡等非 P4 完整实现项必须有 out-of-scope 或 future hook 行，而不是直接忽略。
- 装备/构筑、角色召唤物、怪物召唤物、动作查询、目标查询、关卡环境至少有归属说明和 blocked 边界样例。
- 默认输出不得包含完整 Canonical IR、全量 TBGD dump 或全量 transition dump。

### 阶段红线

- 只统计角色，不统计怪物。
- 只统计怪物，不统计角色。
- 只统计 ExcelOutput，不扫 ability/config/global modifier 来源。
- 一个来源域里有 executable 正例，就把同域全部标 executable。
- 发现 P3 backlog 但没有纳入矩阵。

## 8. P4-S1 CharacterDataCard / MonsterDataCard / RuleBook 契约复核

### 目标

复核现有数据卡 IR 和 RuleBook 查询契约，确认 runtime 所需的所有规则事实都能从 Canonical IR / 数据卡 IR 查到。P4 不重建数据卡底层，而是查清现有契约缺口并补齐必要字段。

### 必须覆盖

- `CharacterDataCardIR`：card id、avatar/profile、action set、formula slots、mechanism slots、trace nodes、eidolon slots、dynamic value bindings、source traces。
- `MonsterDataCardIR`：card id、entity/template、profile、action sequence、skill list、passive slots、summon refs、attached status、fixed sequence admission、source traces。
- `CombatantProfileIR`：角色、怪物、servant 的基础属性来源、等级/晋阶/模板字段、缺字段 blocked 原因。
- `CombatantActionSetIR`：entity_ref、skill index、action_ref、level、source trace、skipped slots。
- 数据卡 assembly extension：装备/构筑输入 hook、角色 servant / 忆灵子卡 hook、怪物 summoned monster lifecycle hook、stage/environment influence hook。
- RuleBook API：按 card id、entity_ref、action_ref、profile id、mechanism slot id、formula binding id 可查。
- source audit 反查：mutation / settlement 必须能回到数据卡 slot，再回到 IR，再回到 TBGD source。

### 阶段验收参考

- 对每类 IR 给出 contract matrix，说明 raw -> IR -> RuleBook 是否完整。
- RuleBook 可见性缺口全部分类为 lowering/admission/validation/implementation/source gap。
- 所有 executable contract 都至少有一个 source audit 抽样。
- 所有 blocked contract 都有 state unchanged 或 process-only 证据。
- 预留 hook 缺输入时必须 blocked 或保持无效果，并能说明后续来源归属。
- 不引入 runtime raw 读取。

### 阶段红线

- 只确认 dataclass 字段存在，不确认 RuleBook 可查。
- 只确认 RuleBook 可查，不确认 source trace 真实。
- 为了 runtime 方便新增无来源字段，并把它伪装成 TBGD。
- 只加空字段或 placeholder，却没有 RuleBook 可见性、blocked reason 或负例验证。

## 9. P4-S2 Combatant action set 与 action availability 扩面

### 目标

统一角色、怪物、servant 的行动入口。动作查询归属可行动单位的数据卡或子卡；外部推演器只能查询和选择，core 不能自动替玩家或敌人选招。

### 必须覆盖

- 角色普攻、战技、终结技、秘技、强化/替换动作。
- 怪物固定序列动作候选、ILBattle 怪物动作、召唤怪物动作。
- servant / 忆灵动作与 owner 关系，来源归属角色卡子卡或派生 combatant card。
- 动作等级、行迹/星魂等级提升、怪物技能等级。
- 资源门：能量、战技点、特殊资源、冷却、禁用动作。
- 目标门：缺目标、非法目标、缺 target expression、unsupported target query。
- 时间线/队列门：行动单位是否轮到、额外行动、插队、反击/追击。

### 阶段验收参考

- action availability 对角色、怪物、servant 都能产出结构化 choice 或 blocked reason。
- action choice 能反查到对应单位卡 / 子卡和 action definition。
- 怪物 action candidate 仍由外部推演器选择，不引入敌方 AI。
- 缺 action set、缺 action definition、缺 resource source、缺 target source、缺 runtime entity 时 blocked/state unchanged。
- 至少有角色、普通怪物、召唤怪物、servant 各一个直接回归样例，或明确 source gap / out-of-scope。
- 旧 P1-0 / P1-3 / P3-S6 相关回归通过或被合理迁移。

### 阶段红线

- 通过 side 名称或 flag 单点放行动作。
- 没有 source trace 的 action choice。
- 自动选择怪物动作或目标。
- 推演器或 route 输入自行制造 action choice。
- route 输入绕过 action availability。

## 10. P4-S3 公式、技能参数、dynamic value / custom value 绑定总账

### 目标

建立数据卡公式和参数绑定的通用 admission。P3 剩余 summoned monster intent 缺口中，大量卡在 custom value hash、dynamic monster id、dynamic value binding、profile/stat source；这些不能在 summon 系统里写特判，必须在数据卡 / formula binding / dynamic value 层通用解决。

### 必须覆盖

- 角色技能倍率、段数、附加倍率、治疗/护盾/真伤/生命消耗。
- 怪物技能倍率、削韧、特殊公式、ILBattle 公式。
- 行迹 / 星魂 / 怪物被动对公式参数的修改。
- `DynamicValues`、`ReadInfo`、`ParamList`、`SkillTreeParam`、modifier dynamic hashes。
- monster custom values、dynamic monster id、custom value hash -> name/value 绑定。
- 数据卡 stat source：攻击、防御、生命、速度、等级、模板、晋阶。
- 负例：hash 未绑定、param index 越界、source file 缺失、profile stat 缺字段、dynamic request 无来源。

### 阶段验收参考

- 输出 formula/dynamic/custom value binding matrix。
- 每类可执行绑定都有 source trace 和至少一个 runtime 使用正例。
- 每类未准入绑定都有具体 blocked reason，不允许只写 unknown。
- P3 summoned monster intent 中因 dynamic/custom value 造成的 gap 必须被重新归因：已解决、仍 admission_gap、仍 source_gap_blocked 或 out_of_scope。
- 不用固定 hash 表或手工常量冒充来源。

### 阶段红线

- 把 hash 直接硬编码成名字或数值。
- 只为某个角色/怪物写一次性解析。
- 用观测伤害反推倍率。
- 缺 profile/stat source 时默认取 0、1、owner stat 或 engine convention。

## 11. P4-S4 角色 / 怪物 target alias、TargetQuery、fetch/sort admission 扩面

### 目标

扩展目标系统对角色 / 怪物专属目标表达式的支持，并回收 P3 中 summon target expression 的 admission gap。目标查询归属 action definition：每个 action 必须声明合法目标、目标选择规则和实际打击范围。目标系统必须继续遵守“缺 registry / 缺 payload / 缺 source 不 fallback”。

### 必须覆盖

- 角色专属 target alias。
- 怪物专属 target alias。
- summon / servant 相关 alias。
- 组合 alias、dot alias、TargetOperationConfig 组合。
- `TargetQuery`、fetch、sort、filter、retarget、adjacent、unique entity。
- 随机目标只建立可审计 RNG choice ledger，不使用默认随机。
- 负例：缺 key、错 key、默认 registry 存在但命名来源缺失、removed/untargetable entity、缺 owner、缺 caster。

### 阶段验收参考

- 输出 target backlog matrix，按 alias/operation/query 子类型拆行。
- 每个新增 executable target 都有正例和负例。
- 每个 executable action 的 target choices 都能反查到该 action 的 target source，不由推演器或 UI 推断。
- P3 summon target expression gap 被拆成更细子行，不能继续只用一个大 admission_gap 表示。
- 旧 P1-6 / v0_288 / v0_289 直接回归通过或完成口径迁移。

### 阶段红线

- fallback 到 caster、默认目标、名称匹配或列表第一个目标。
- 只支持一个样例，却把整个 alias family 标 executable。
- 让外部推演器解释目标规则、实际打击范围或目标 fallback。
- 让 target resolver 读取 raw TBGD 或 TextMap。

## 12. P4-S5 怪物技能 action graph 覆盖扩面

### 目标

在现有 `MonsterDataCardIR` 基础上扩展怪物技能 action graph 覆盖，不重做怪物卡底层。重点是让更多怪物技能的 action definition、ability binding、effect chain、target、status、damage、resource、queue intent 可审计、可执行或明确 blocked。

### 必须覆盖

- 普通怪物技能。
- ILBattle 怪物技能。
- 怪物技能多段、弹射、群体、随机、附加伤害、状态附加、削韧。
- 怪物技能内的 SummonMonster、SetDynamicValue、AddModifier、RemoveModifier、action delay、queue insert。
- fixed sequence action candidate 与 action definition 的 source trace。
- 怪物技能不能执行时的分层原因：缺 action definition、缺 target、缺 formula、缺 status source、缺 dynamic value、缺 profile/card。

### 阶段验收参考

- 至少按结构化谓词选出多个怪物技能 family 的 executable 正例，而不是固定怪物名。
- 每个正例 transition 有 mutation / settlement / replay / source audit。
- 每个 blocked family 有 state unchanged 或 process-only 证据。
- 怪物 fixed sequence 仍只产出候选，不自动选招。
- P3 summoned monster action availability 正例不退化。

### 阶段红线

- 把怪物 AI 路径当成 runtime 自动执行。
- 用 MonsterID 或怪物名特判技能。
- 只验证一个怪物技能就宣称怪物技能完成。

## 13. P4-S6 怪物被动、监听、阶段、波次、召唤交叉边界

### 目标

把怪物被动和事件监听来源接入数据卡机制槽位，明确哪些可以 executable，哪些需要等 wave/stage/environment 后续阶段。

### 必须覆盖

- startup / on enter battle。
- on turn start / end。
- on hit / after hit / before hit。
- on death / phase change。
- on wave monster / wave transition。
- global modifier 与 monster passive slot。
- summon refs、summoned monster lifecycle、owner cleanup、wave clear。怪物召唤物自身必须优先绑定已有 `MonsterDataCardIR`；召唤者只提供 spawn intent、owner/summoner relation 和生命周期约束。
- stage/environment 相关来源必须分类，不得塞进怪物卡 runtime。

### 阶段验收参考

- 输出 monster passive/listener matrix。
- 已有真实 event source、payload、condition、target、task 的监听可以 executable。
- 缺事件源、缺 payload、缺 wave/stage 系统的监听必须 blocked/process-only。
- 与 P2 状态 callback、P3 summon lifecycle 的直接回归通过。

### 阶段红线

- 用怪物名或技能文本识别被动。
- 没有事件源就执行 callback。
- 为怪物召唤物复制一套脱离怪物卡的特殊技能/属性系统，除非 raw 来源证明它不是已有怪物。
- 把 stage/environment 机制伪装成怪物被动。

## 14. P4-S7 角色基础动作、天赋、秘技、强化形态机制槽位扩面

### 目标

扩展 `CharacterDataCardIR` 的角色机制槽位，让更多角色动作和基础机制能按通用系统执行或 blocked。P4 不是要一口气写完所有角色，而是要把角色卡接入模式稳固下来。

### 必须覆盖

- 普攻、战技、终结技。
- 天赋和被动监听。
- 秘技、开局状态、战斗开始效果。
- 强化形态、动作替换、技能组切换。
- 多段、弹射、追加攻击、反击、额外行动、再行动。
- 角色专属资源与资源上限。
- 角色召唤物入口：servant / 忆灵子卡或派生 combatant card 的 owner、属性、技能、行动、状态持有、生命周期连接。
- 与状态、target、formula、dynamic value 的连接。

### 阶段验收参考

- 除希儿外，至少按结构化谓词选出若干角色机制 family 样例；如果暂不做全正例，必须有来源矩阵和 blocked 边界。
- 每个角色机制槽位有明确 source trace 和 slot kind。
- servant / 忆灵这类角色召唤物必须能说明归属角色卡还是独立子卡；缺 owner、缺 stat、缺 action、缺 target 时 blocked。
- runtime 不出现角色名特判。
- 旧希儿示例卡回归通过或完成口径迁移。

### 阶段红线

- 把角色专属机制写进 core if/else。
- 把 servant / 忆灵当成普通 buff 或普通怪物直接套用，导致 owner、属性、技能或生命周期来源丢失。
- 只复制希儿模式，不处理其他角色来源族。
- 用技能文本直接驱动 runtime。

## 15. P4-S8 行迹、星魂、等级提升、开局机制与角色资源槽位扩面

### 目标

把角色成长与开关机制做成通用数据卡 assembly 输入，避免每个角色单独在 scenario 或 runtime 中补 flag。

### 必须覆盖

- 行迹静态属性加成。
- 行迹启动能力、开局状态、状态监听。
- 星魂技能等级提升。
- 星魂机制槽位、状态、监听、资源变化。
- 技能等级、终结技等级、天赋等级、普攻等级。
- 角色特殊资源、能量、战技点、冷却或计数器。
- 未来角色构筑输入 hook：光锥、遗器、套装和外部构筑参数只能通过数据卡 assembly 影响属性、状态、监听、公式参数或 action availability。

### 阶段验收参考

- trace/eidolon/resource slot matrix 完整分类。
- 已执行的行迹/星魂效果有 source audit。
- 未支持的行迹/星魂明确 blocked，不会产生 mutation。
- scenario build 只能启用数据卡提供的 slot，不能手写机制结果。
- 构筑输入 hook 缺来源时不会产生任何装备/遗器规则 mutation。

### 阶段红线

- 在 scenario 里直接注入角色专属结果。
- 在 runtime 里直接读取或解释光锥/遗器/套装规则。
- 用星魂等级硬编码效果。
- 旧版/加强版角色来源混用但无 source trace。

## 16. P4-S9 数据卡状态、资源、伤害、击杀归因联动

### 目标

确认角色/怪物数据卡产生的状态、资源、伤害和击杀归因都接入 P1/P2/P3 通用底座，而不是走数据卡私有路径。

### 必须覆盖

- 数据卡技能造成 direct / DoT / hp loss / break / super-break / true damage。
- 数据卡技能施加、刷新、移除状态。
- 数据卡监听产生 queue、action delay、extra action、resource mutation。
- 击杀归因区分 actor、owner、source frame、summon/servant。
- removed/defeated/untargetable 单位负例。

### 阶段验收参考

- 每类 mutation 都有 settlement 和 source audit。
- replay 能复原 after snapshot。
- blocked 状态不产生 mutation。
- P2 状态聚合和 P3 summon/source audit 直接回归通过。

### 阶段红线

- 数据卡绕过状态系统、伤害系统、资源系统或 MutationReducer。
- 从日志事后反推 settlement。
- 击杀归因只记 actor，不记具体 source frame。

## 17. P4-S10 P3 backlog 回收：summon target 与 summoned monster intent

### 目标

把 P3 允许保留的 admission/source-gap 作为 P4 明确输入，而不是遗忘在报告里。P4 不要求一次清零，但必须把缺口拆细到可执行 work package。

### 必须覆盖

- `summon_target_expression` admission gap。
- `summoned_monster_intent` admission gap。
- `summoned_monster_intent` source_gap_blocked。
- target alias / TargetQuery / custom value hash / dynamic monster id / profile card source / location type。
- AssistantAvatar out_of_scope 继续保持独立，不混入 P4 summon backlog，除非用户明确启动 AssistantAvatar 阶段。

### 阶段验收参考

- 每个 P3 inherited gap 行在 P4 中有对应子矩阵。
- 能修的 lowering/admission/validation 缺口已修，并有回归。
- 不能修的保留明确 reason、evidence 和后续归属。
- P3 聚合仍通过底座闭环，且不能新增 implementation/lowering/validation/unclassified gap。

### 阶段红线

- 把 P3 backlog 从报告中移除但不解决。
- 用 out_of_scope 掩盖实际属于 summon/monster/target 的缺口。
- 宽域正例覆盖子项 gap。

## 18. P4-S11 未来外部推演器 action/query 调用契约样例，不实现推演器

### 目标

让 P4 产出的数据卡能力有一个稳定的 core 调用边界，证明未来外部推演器可以消费这些能力。

本步不实现推演器，不做搜索、规划、回溯、评分函数、路线选择或敌方 AI。这里的“可被外部推演器消费”只表示：core 能通过普通调用方可用的 action/query contract 暴露合法动作、目标、资源状态、blocked reason 和 transition audit，而不是要求现在存在一个完整推演器。

推演器的定位是“像玩家一样操作和看结果”。它只查询当前局面、选择合法动作和目标、指定或枚举可控 RNG 分支、读取 transition；它不能解释角色/怪物/状态/目标/伤害规则，也不能绕过 blocked reason。

### 必须覆盖

- 用本地验证脚本或薄样例客户端查询当前所有可行动单位。
- 用同一套 contract 查询某单位可选 action choices。
- 用同一套 contract 查询某 action 的 target choices / target policy。
- 用同一套 contract 提交外部给定的 action command。
- action choices 必须来自单位卡 / 子卡的 action availability；target choices 必须来自 action definition。
- 获得 `BattleTransition`：before / after / target resolution / mutations / process events / rng events / settlement / source audit / replay metadata。
- 敌方动作由外部传入，不由 core 自动选择。
- blocked command 返回结构化原因，并保持 state unchanged。

### 阶段验收参考

- 至少一个角色动作、一个怪物动作、一个 servant 或 summoned monster 动作样例可由统一 contract 执行。
- 至少一个非法 command 样例 blocked/state unchanged。
- transition 输出不依赖 raw TBGD、TextMap、UI 私有结构或内部临时对象。
- contract 样例只证明调用边界稳定，不包含推演算法。
- 样例能证明推演器不拥有底层规则：非法动作、非法目标、缺 RNG choice 或缺来源都由 core blocked。
- 不引入新依赖或服务。

### 阶段红线

- 新增搜索器、规划器、评分器或自动路线选择逻辑，并把它当成 S11 目标。
- 推演器样例自行判断技能可用性、目标范围、状态结算或伤害公式。
- 推演器接口绕过 action availability。
- UI 提供规则事实。
- core 自动补目标或自动选敌方动作。

## 19. P4-S12 P4 聚合验收、报告、交接和后续 backlog

### 目标

用一个 P4 聚合入口证明当前数据卡扩面底座达到可依赖状态，并把未清零项诚实留给后续阶段。

### 必须产出

- `validate_p4_combatant_data_card_expansion.py` 或等价聚合入口。
- 角色/怪物来源总矩阵。
- 数据卡契约矩阵。
- action availability 矩阵。
- formula/dynamic/custom value binding 矩阵。
- target backlog 矩阵。
- monster action/passive 矩阵。
- character action/trace/eidolon/resource 矩阵。
- P3 backlog 回收矩阵。
- 正例样本集。
- blocked/state unchanged 样本集。
- source audit / replay 样本集。
- allowed gap evidence matrix。
- scope exclusion matrix。
- resource budget 报告。
- P4 最终报告和交接更新。

### 阶段验收参考

P4 底座闭环 summary 至少包含：

```text
ok=True
validation_gate_ok=True
p4_combatant_data_card_phase_complete=True
p4_combatant_data_card_substrate_complete=True
p4_all_executable_complete=False
p4_sources_classified=True
p4_implementation_missing_count=0
p4_lowering_gap_count=0
p4_validation_gap_count=0
p4_unclassified_count=0
allowed_gap_evidence_summary.all_evidence_ok=True
allowed_gap_evidence_summary.disallowed_gap_count=0
```

如果全正例清零，则还必须包含：

```text
p4_all_executable_complete=True
p4_admission_gap_count=0
p4_source_gap_blocked_count=0
```

### 阶段红线

- 聚合 `ok=True` 但没有继承分步矩阵 gap。
- 报告只列已支持样例，不列缺口。
- 未运行直接相关 P1/P2/P3 回归。
- 没有资源预算说明。
- 没有更新交接文档。

## 20. 验证范围和资源预算

### 必跑最小集

每个子阶段至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

还必须运行本子阶段新增或修改的主验证脚本。

### 直接回归集

- 改 action availability：跑 P1-0、P1-3、P3-S6。
- 改 target：跑 P1-6、v0_288、v0_289、P3-S8。
- 改 BattleSetup / scenario：跑 P1-8、P1-9。
- 改 status / listener：跑 P2 聚合。
- 改 summon / servant / summoned monster：跑 P3 聚合。
- 改 damage / formula / resource：跑 P1-9、P2 聚合、相关 damage/resource 验证。
- 改 RuleBook / lowering schema：跑本阶段聚合、P1-9、P2 聚合、P3 聚合。

### 阶段验收集

P4-S12 阶段验收至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_combatant_data_card_expansion
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_p4_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_p4_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_p4_regression
git diff --check
```

如果某个旧回归因为 P4 新语义失败，必须先判断：

- 新语义是否有真实来源、source audit、replay 和负例。
- 旧断言是否写死了过去未完成时期的 blocked 口径。
- 如果旧断言过期，修验证口径并在报告说明；不能把过期验证失败算作 P4 功能失败。
- 如果旧验证揭示真实退化，必须修实现，不能豁免。

### 高负载限制

- P4 聚合、P1/P2/P3 聚合、全量 TBGD discovery/lowering 都按重验证处理。
- 一次只跑一个重验证，轻易不跑重验证，如果要跑也要做出限制，防止大io把内存和磁盘打爆。
- 输出目录放 `/tmp`。
- 默认不写完整 IR、完整 coverage、完整 transition dump。
- 确需大产物时必须加显式开关，例如 `--write-large-artifacts`，默认关闭。

## 21. 执行记录格式

每完成一个子阶段，执行线程只能提交 `ready_for_review` 证据包，不能更新本文件 checklist，不能把 `[ ]` 改成 `[x]`，不能自称 `done`。证据包必须包含：

- 本阶段执行卡。
- 本步目标。
- 实际改动文件。
- 实际新增 / 修改的函数、类型、脚本或报告。
- 本步完成了什么，每个完成项对应哪个 evidence。
- 本步没有完成什么，哪些项是 blocker / gap / deferred。
- 新增或修正的来源分类。
- 正例如何按结构化谓词选择。
- 负例覆盖哪些 blocked / state unchanged。
- source audit / replay / settlement traceability 结果。
- 跑了哪些验证，以及为什么没有跑无关验证。
- 每个 `ok=true` 验证实际检查了什么、没有检查什么、是否可能 predicate 过宽。
- 是否还有 implementation_missing / lowering_gap / admission_gap / validation_gap / source_gap_blocked / out_of_scope。
- 是否影响 P1/P2/P3 既有完成口径。

验收线程复核证据包后，才允许更新第 22 节 checklist，并按协作约定决定是否提交检查点。

## 22. Checklist

本 checklist 只由验收线程更新。执行线程完成某阶段后只能提交 `ready_for_review` 证据包，不能自行勾选。

- [x] P4-S0 角色 / 怪物数据卡来源总账本与范围定界完成。
- [ ] P4-S1 CharacterDataCard / MonsterDataCard / RuleBook 契约复核完成。
- [ ] P4-S2 Combatant action set 与 action availability 扩面完成。
- [ ] P4-S3 公式、技能参数、dynamic value / custom value 绑定总账完成。
- [ ] P4-S4 角色 / 怪物 target alias、TargetQuery、fetch/sort admission 扩面完成。
- [ ] P4-S5 怪物技能 action graph 覆盖扩面完成。
- [ ] P4-S6 怪物被动、监听、阶段、波次、召唤交叉边界完成。
- [ ] P4-S7 角色基础动作、天赋、秘技、强化形态机制槽位扩面完成。
- [ ] P4-S8 行迹、星魂、等级提升、开局机制与角色资源槽位扩面完成。
- [ ] P4-S9 数据卡状态、资源、伤害、击杀归因联动完成。
- [ ] P4-S10 P3 backlog 回收：summon target 与 summoned monster intent 完成。
- [ ] P4-S11 未来外部推演器 action/query 调用契约样例完成，不实现推演器。
- [ ] P4-S12 P4 聚合验收、报告、交接和后续 backlog 完成。

## 23. 夜间 goal 模式建议

适合 goal 模式自动推进的优先顺序：

1. 先做 P4-S0 / P4-S1，只产出矩阵和报告，不急着大改 runtime。
2. 再做 P4-S3 / P4-S4，因为 P3 backlog 很多卡在 dynamic/custom value 和 target admission。
3. 然后做 P4-S5 / P4-S6，扩怪物 action/passive。
4. 再做 P4-S7 / P4-S8，扩角色机制槽位。
5. 最后做 P4-S9 / P4-S10 / P4-S11 / P4-S12 聚合收口。

goal 模式执行时应优先减少人工介入，但不能牺牲验收口径：

- 遇到旧验证失败，先判断口径是否过期。
- 遇到来源不明，保留 blocked/source gap，不要猜。
- 遇到需要外部资料、文本解释或设计选择，暂停并记录问题，不要硬补 runtime。
- 每个可验证结构阶段完成后再提交检查点。
