# v8 Architecture Boundary Contract

本文档定义 v8 战斗模拟器的长期分层边界。它不是阶段计划，也不是完成清单；后续 P6+ 计划、验收和代码审查都应以这里的边界为前置约束。

## 1. 核心原则

v8 的核心架构原则是：

```text
内容卡不是机制执行层，而是机制装配层。
内核不是内容解释层，而是通用机制执行层。
UI / 推演器不是规则层，而是外部操作层。
TBGD lowering / 数据卡构建不是 runtime，而是事实来源编译层。
```

角色卡、怪物卡、召唤物子卡、装备和关卡可以让游戏内容变得个性化，但个性化应来自“选择哪些通用机制、填哪些参数、绑定哪些来源、组合哪些触发关系”，不能来自“在内容卡里执行一套专属规则”。

如果真实机制无法用现有通用内核表达，正确做法是先判断：

1. 是否只是已有机制缺字段。
2. 是否只是已有机制缺组合方式。
3. 是否确实缺一种新的通用机制类型。

只有第三种才扩展内核机制类型。不能为了让某张卡先跑起来，把规则执行写进内容卡，也不能让内核按角色名、怪物名、技能名或数据卡私有字段分支。

## 2. 分层总览

```text
L3 外部操作层
UI / 推演器 / CLI / 调试工作台
只查询、选择、提交、展示，不推导规则

        ↓ 消费公开查询与 transition

L2 内容装配层
角色卡 / 怪物卡 / 召唤物子卡 / 装备 / 构筑 / 关卡 / 环境
声明机制组合、参数、来源、触发关系，不执行机制

        ↓ 产出结构化内容 IR / 机制声明

L1 机制执行层
Combat Core / RuleBook consumer / reducer / systems
执行目标、行动、状态、资源、伤害、队列、召唤、波次、结算

        ↑ 只读取 Canonical IR / 数据卡 IR / Runtime State

L0 来源编译层
TBGD raw / discovery / lowering / 数据卡构建 / 文本解释
把事实来源编译成 Canonical IR / 数据卡 IR

横切约束：source audit / settlement / replay / coverage / gap attribution
```

依赖方向只能向下游消费稳定契约，不能反向解释上层私有语义：

```text
UI / 推演器 -> Core public query / transition
内容卡 -> Core mechanism contract
Core -> Canonical IR / 数据卡 IR / RuleBook / BattleState
Lowering -> TBGD raw
```

runtime 不允许直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不允许把审计字段当成主要规则输入。

## 3. L0 来源编译层

### 职责

L0 负责把事实来源转成结构化事实：

- 从 `turnbasedgamedata-main` 读取 raw TBGD。
- 做 discovery、lowering、source ledger、coverage 统计。
- 构建 Canonical IR、数据卡 IR、机制 slot、参数绑定和 source trace。
- 在允许范围内读取技能文本或外部资料，用于数据卡解释、展示或人工审查。

### 允许

- 读取 raw TBGD schema。
- 读取 TextMap 或文本资料，用于数据卡构建和 UI 展示。
- 输出 `source_trace`、coverage、gap、blocked reason、audit-only 记录。
- 把 raw 中的结构化事实投影到 Canonical IR / 数据卡 IR。

### 禁止

- 把 raw TBGD schema 暴露给 runtime。
- 为了 runtime 方便伪造 TBGD 中不存在的规则事实。
- 把 `engine_convention` 伪装成 TBGD 来源。
- 用观测伤害、旧模拟器输出、固定答案补规则。
- 因验证脚本扫不到正例，就直接断言 raw 没来源；必须先区分 raw source gap、lowering gap、admission gap 和 validation gap。

## 4. L1 机制执行层

### 职责

L1 负责通用战斗结算：

- action availability、action execution、action command admission。
- target expression、target legality、实际打击范围、retarget、target group。
- damage、toughness、break、super-break、DoT、hp loss、heal、shield。
- status lifecycle、stack、duration、chance、resist、immunity、dispel、callback。
- resource、energy、skill point、custom resource、value binding。
- queue、timeline、extra action、follow-up、counter、ultimate window、turn lifecycle。
- summon、servant、summoned monster、owner/summoner relation、cleanup。
- wave、stage、environment、battle setup。
- mutation、settlement、source audit、replay、coverage、blocked/process-only。

### 允许

内核可以认识稳定机制契约，例如：

- `ActionDefinitionIR`
- `TargetExpressionIR`
- `DamageEmissionIR`
- `ToughnessEmissionIR`
- `StatusDefinitionIR`
- `StatusCallbackIR`
- `QueueIntentIR`
- `ResourceRuleIR`
- `SummonIntentIR`
- `ValueBinding`
- `CombatantProfileIR`
- `BattleSetupIR`
- `WaveIR` / `StageIR` / `EnvironmentIR`

### 禁止

- 按角色名、怪物名、技能名、固定 ID、固定 hash、固定文件名执行规则。
- 直接理解角色卡文本、怪物卡特殊字段或 raw parameter block。
- 从 UI 或推演器接收“已推导好的规则结果”。
- 从 `source_trace` 递归挖运行所需参数作为长期主路径。
- 遇到缺来源、缺目标、缺上下文、缺参数时 fallback 到默认执行。
- 让 `blocked`、`audit_only`、`discovered_only`、placeholder 产生 mutation。

## 5. L2 内容装配层

### 职责

L2 负责把通用机制实例化到具体内容上：

- 角色卡声明基础面板、技能、行迹、星魂、特殊资源、角色召唤物入口。
- 怪物卡声明面板、技能、弱点、抗性、被动、阶段、召唤怪入口。
- 召唤物 / 忆灵子卡声明独立属性、技能、行动、生命周期和 owner 关系。
- 装备 / 构筑输入声明光锥、遗器、套装、属性覆盖和 build 配置。
- 关卡 / 环境声明波次、敌人组、环境事件、倍率和特殊规则入口。
- 所有内容声明都必须能追溯到来源或明确标记为 blocked / deferred / manual interpretation。

### 内容卡可以表达

- 我有哪些动作。
- 动作有哪些合法目标和实际打击范围。
- 动作产生哪些 mechanism intent。
- 状态监听哪些事件。
- 召唤物属于谁、生命周期如何绑定。
- 特殊资源如何接入。
- 参数绑定到哪个技能等级、数据卡等级、动态值或上下文。
- 哪些机制当前无法准入，blocked reason 是什么。

### 内容卡不能表达

- 自己结算伤害。
- 自己判定目标是否合法。
- 自己插队、推进时间线或执行额外行动。
- 自己推进状态生命周期。
- 自己绕过资源、目标、概率、抵抗、免疫、source audit 或 replay。
- 自己读取 runtime raw TBGD 或 TextMap。
- 自己把“后续会补”当成 executable。

### 专属 slot 的边界

内容卡可以有专属 slot，但 slot 只能声明机制，不能执行机制。

例如“希儿击杀后获得额外行动”应表达为：

```text
内容卡声明：
- 监听事件：OnDefeat / OnKillCredit
- 条件：击杀归因属于自己
- 动作：插入额外行动窗口
- 限制：每回合触发次数
- 来源：天赋 / 行迹 / 星魂对应 IR 节点

内核执行：
- 事件派发
- 条件判定
- 次数限制
- 队列插入
- settlement / mutation / replay / source audit
```

不能表达为：

```text
executor 判断 template_id == Seele
角色卡自己执行“击杀后插队”
验证脚本用固定角色名证明机制完成
```

## 6. L3 外部操作层

### 职责

L3 包含 UI、推演器、CLI 和调试工作台。它们的职责类似玩家：

- 查询当前状态。
- 查询合法动作。
- 查询合法目标。
- 选择 action command。
- 指定或枚举可控 RNG 分支。
- 读取 transition、settlement、source audit 和 replay。
- 展示战斗过程、路径和结算。

### 禁止

- 自己判断技能可用性。
- 自己判断目标范围。
- 自己结算状态、伤害、资源、行动条或队列。
- 自己推导战技点、能量、特殊资源和装备效果。
- 用 mock 结果写入正式 scenario、route 或验收样例。
- 为了 UI 展示方便要求 core 引入非通用字段或伪来源。

UI 可以提前设计最终入口，用来倒查 core/API 缺口；但 UI 需求不能成为牺牲内核通用性、来源追溯和 replay 的理由。推演器也一样，它只负责搜索选择，不负责替内核思考规则。

## 7. 横切审计层

source audit、settlement、replay、coverage 和 gap attribution 不是可选功能，而是贯穿所有层的长期约束。

每个状态变化都必须能回答：

- 谁声明了这个机制。
- 哪个内核机制执行了它。
- 产生了哪些 mutation。
- settlement 是否能追到 mutation，或明确 process-only。
- before snapshot + action input + IR + RNG events + mutations 是否能 replay 成 after snapshot。
- source audit 是否能追到 Canonical IR / 数据卡 IR / TBGD source。
- 失败时是否有 blocked reason 且 state unchanged。

每个新增机制至少需要：

- 真实来源正例。
- 缺来源 / 缺上下文 / 缺目标 / 缺 payload / unsupported condition 的负例。
- mutation → settlement → source audit → replay 链路。
- gap 分类：`executable`、`source_gap_blocked`、`lowering_gap`、`admission_gap`、`validation_gap`、`implementation_missing` 或 `out_of_scope`。

## 8. 当前架构债

以下是当前已知债，不影响 P5 底座验收，但后续应逐步收敛：

- P5 后仍有部分 runtime 路径从 `source_trace` 寻找运行所需绑定信息。这是过渡方案，后续应迁移成显式字段，例如 `value_binding_ref`、`param_binding_id`、`source_emission_id`。
- 内容卡和内核之间的契约还不够硬，后续需要把 action、target、value binding、status callback、summon intent、wave/stage event 等收敛成稳定机制声明。
- 数据卡扩面前必须建立“内容卡不能执行机制”的验收红线。
- UI 当前独立性相对较好，但 mock / view model 不能反向定义 core 字段。
- P3/P4/P5 中保留的 admission/source gap 不能被后续聚合脚本清零；只能通过真实来源、真实 admission、真实 runtime consumer 和真实验证逐项回收。

## 9. 后续阶段约束

后续 P6+ 阶段计划必须显式引用本契约，并在验收时回答：

- 本阶段改动属于哪一层。
- 是否引入了跨层反向依赖。
- 内容卡是否只声明机制，没有执行机制。
- 内核是否只消费稳定 IR / 数据卡 IR，没有读取内容私有语义。
- UI / 推演器是否只查询和提交，没有推导规则。
- source trace 是否只作为审计证据，或是否存在需要后续迁移的临时 runtime 输入。
- 新增 gap 是否继承到聚合矩阵。

如果某项机制需要打破这些边界，执行线程必须暂停并要求规划 / 用户确认，不能自行把例外写进 runtime。
