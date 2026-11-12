# v8 Architecture Boundary Contract

本文档定义 v8 战斗模拟器的长期分层边界。它不是阶段计划，也不是完成清单；后续计划、验收和代码审查都应以这里的边界为前置约束。

2026-11-10 按[方向矫正](PROJECT_GOALS.md#2026-11-10-方向矫正)修订了三处：内容层可以携带专属处理器
（第 1、5 节）；来源审计从长期约束降为可开关的调试与测试能力（第 7 节）；遇到通用机制表达不了的
内容不再停工等待裁决，而是按成本选择接入方式（第 9 节）。四层结构和依赖方向不变。

## 1. 核心原则

v8 的核心架构原则是：

```text
内容卡是机制装配层：声明通用机制的组合，并可携带本卡专属的处理器；不另建结算逻辑。
内核是通用机制执行层：提供通用结算和公共挂点，不解释具体内容。
UI / 推演器不是规则层，而是外部操作层。
TBGD lowering / 数据卡构建不是 runtime，而是事实来源编译层。
```

角色卡、怪物卡、召唤物子卡、装备和关卡的个性化首先来自“选择哪些通用机制、填哪些参数、绑定哪些来源、组合哪些触发关系”。通用机制表达不了的专属行为，由该内容卡的专属处理器实现，而不是把通用编译器和内核扩展到能表达每一个特例。

真实机制无法用现有通用内核直接表达时，按成本依次判断：

1. 是否只是已有机制缺字段或缺组合方式：补字段或组合。
2. 是否有多个 v1 名单内容共用这一行为：扩展一种通用机制，核对各消费者。
3. 是否只有一个内容使用：写该内容卡的专属处理器；出现第二个使用者时再提升为通用机制。

不预先为假想的复用做抽象。内核仍不得按角色名、怪物名、技能名、固定 ID 或数据卡私有字段分支；专属行为只能经装配挂载进入执行。

### 1.1 成品范围

v8 的成品范围是战斗模拟，不是完整游戏复刻。判断一项真实数据或游戏功能是否必须实现，
以它是否改变合法战斗输入、战斗内决策空间、状态转移或结算结果为准。

角色、敌人、光锥、遗器、召唤物、关卡环境最终带入战斗的属性和机制属于范围；获取、
掉落、定向生成、合成、背包、商店、养成操作、展示和服务端管理流程默认不属于范围。
非战斗流程产生的结果若会进入战斗，装配层只接收来源真实、结构合法的最终构筑输入，
不复刻其生成过程。

当前版本只做用户确定的 v1 名单；名单外内容在准入时明确拒绝，不是缺陷。
raw 目录中的特殊模式不能仅因存在就获得正式 admission，也不因存在而成为任务；
不得为追求目录“全兼容”扩张通用内核。

2026-10-08 用户明确以实际战斗行为还原为目标。原生引擎的任务组织和内部调用协议不要求
一一复制；需要保留的是会影响合法动作、目标、状态、资源、结算或后续触发的语义与顺序。
2026-10-12 用户明确可靠攻略、数据网站和条件明确的实测结论可直接作为规则依据，不要求
再从 TBGD 或原生内部协议重复证明。规则经 L0 编译/注册，由 L1 通用执行，注明实际来源；
runtime 不直接解释网页、视频记录或审计字段。阻断按实际配置及行为依赖定位；
只有已证明无战斗影响的表现或不可达分支才可排除，必需被动与来源完整性错误仍不得绕过。

## 2. 分层总览

```text
L3 外部操作层
UI / 推演器 / CLI / 调试工作台
只查询、选择、提交、展示，不推导规则

        ↓ 消费公开查询与 transition

L2 内容装配层
角色卡 / 怪物卡 / 召唤物子卡 / 装备 / 构筑 / 关卡 / 环境
声明机制组合、参数、来源、触发关系；专属行为由本卡处理器实现

        ↓ 产出结构化内容 IR / 机制声明 / 已装配处理器

L1 机制执行层
Combat Core / RuleBook consumer / reducer / systems
执行目标、行动、状态、资源、伤害、队列、召唤、波次、结算

        ↑ 只读取 Canonical IR / 数据卡 IR / 已装配处理器 / Runtime State

L0 来源编译层
TBGD / 已采纳机制资料 / discovery / lowering / 数据卡构建 / 规则注册
把事实来源转为 Canonical IR / 数据卡 IR / RuleBook

复盘与调试：结算明细 / replay / 可开关的 source audit
```

依赖方向只能向下游消费稳定契约，不能反向解释上层私有语义：

```text
UI / 推演器 -> Core public query / transition
内容卡与专属处理器 -> Core mechanism contract / 公共挂点与通用结算函数
Core -> Canonical IR / 数据卡 IR / RuleBook / BattleState
Lowering / 规则注册 -> TBGD raw / 已采纳机制资料
```

runtime 不允许直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不允许把审计字段当成主要规则输入。

## 3. L0 来源编译层

### 职责

L0 负责把事实来源转成结构化事实：

- 从 `turnbasedgamedata-main` 读取 raw TBGD。首要产出是参数：面板、倍率、韧性、能量、等级表。
- 做 discovery、lowering、source ledger、coverage 统计。原生任务图的编译在已可用的内容上继续使用；
  新内容是否走编译由成本决定，编译覆盖率和任务类型闭合不是目标。
- 构建 Canonical IR、数据卡 IR、机制 slot、参数绑定和 source trace。
- 从可靠攻略、数据网站和实测资料整理公式、参数、条件与时序，注册正式规则并保留来源。

### 允许

- 读取 raw TBGD schema。
- 读取 TextMap 或文本资料，用于数据卡构建和 UI 展示。
- 输出 `source_trace`、coverage、gap、blocked reason、audit-only 记录。
- 把 raw 中的结构化事实投影到 Canonical IR / 数据卡 IR。
- 把已采纳的研究结论直接注册为类型化规则；复用已有入口，不强制开发网页导入器或新证据框架。

### 禁止

- 把 raw TBGD schema 暴露给 runtime。
- 把外部研究结论伪装成 TBGD 字段或 raw 节点。
- 把 `engine_convention` 伪装成 TBGD 来源。
- 用孤立观测值、旧模拟器输出或固定结算答案代替规则；条件明确的机制研究不属于此禁令。
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
- mutation、原子提交、结算明细、replay、确定性 RNG。
- 供内容专属处理器使用的公共挂点（动作执行、事件监听、生命周期节点等）和通用结算函数。

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

- 按角色名、怪物名、技能名、固定 ID、固定 hash、固定文件名执行规则。调用单位已装配的处理器
  属于通用分派，不在此列；为某个处理器在内核里开只有它能用的后门则属于此列。
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
- 通用机制表达不了、且只有本内容使用的行为，由本卡的专属处理器实现。
- 内容声明和处理器在定义处注明实际来源，或明确标记为 blocked / deferred。

### 装备与角色构筑的边界

角色卡、光锥卡和遗器卡是并列内容来源，不是互相嵌套的规则容器：

```text
角色卡 + 光锥卡 + 遗器卡 + 玩家构筑输入
                    ↓
               构筑装配器
                    ↓
       静态属性贡献 + 已启用机制 + 来源账本
                    ↓
                战斗单位
```

- 角色卡只声明角色自身成长、技能、行迹、星魂和专属机制。
- 光锥卡声明基础生命 / 攻击 / 防御、战斗命途、叠影参数、静态属性和动态能力。
- 遗器卡声明模板、部位、词条分组和套装归属；具体主副词条属于玩家遗器实例。
- 玩家构筑输入只声明选择，不提交最终面板、套装激活结果或被动是否生效。
- 构筑装配器负责合法性、静态属性聚合、套装门槛和机制选择，但不执行状态、伤害、资源、事件或时间线。
- runtime 只消费装配结果和类型化机制，不读取 raw 装备表、TextMap 或构筑内部结构。

静态贡献可以聚合为最终面板，但必须保留逐项来源；条件效果和动态效果必须继续以通用 ability / modifier / callback / condition / effect 图执行，不能提前压平成常驻面板。字符串式 boundary、空字段和 future-owner 说明不构成正式装备接口。

### 内容卡可以表达

- 我有哪些动作。
- 动作有哪些合法目标和实际打击范围。
- 动作产生哪些 mechanism intent。
- 状态监听哪些事件。
- 召唤物属于谁、生命周期如何绑定。
- 特殊资源如何接入。
- 参数绑定到哪个技能等级、数据卡等级、动态值或上下文。
- 哪些机制当前无法准入，blocked reason 是什么。

### 内容专属处理器

处理器是属于某一张内容卡的代码，用来实现通用机制表达不了、且目前只有该内容使用的行为。
它与卡一起装配，只在该卡的单位或装备在场时生效。

处理器可以：

- 经内核公共挂点被调用：动作执行、事件监听、生命周期节点等；
- 决定本内容专属的流程：何时触发、作用于谁、消耗和产生什么专属资源、派生单位何时出现和离场；
- 调用内核通用函数完成伤害、治疗、护盾、削韧、状态施加、队列插入等结算；
- 读取本卡的数据卡参数和 runtime state。

处理器不能：

- 直接修改 `BattleState`；所有变化经类型化 mutation 进入同一原子提交；
- 另写伤害、治疗、护盾等公式，或绕过目标合法性、资源、概率、抵抗、免疫和确定性 RNG；
- 在代码里写死倍率等数值；数值取自数据卡参数，来源是已采纳资料时在定义处注明；
- 读取 raw TBGD、TextMap 或其它内容卡的私有状态；
- 用观测答案或固定结算结果充当规则；
- 要求内核为它增加只有它能用的分支。

每个处理器在定义处注明依据（TBGD 能力名或资料链接、适用版本与条件）。第二个内容需要同样行为时，
把共同部分提升为通用机制，两处改为复用。

### 挂载接口与书写约定（2026-11-11 M1-3 对照实验确立）

实验结论与投入对比见[对照实验报告](docs/archive/completed_tasks/CONTENT_PROCESSOR_EXPERIMENT_REPORT.md)：单内容专属行为
默认走处理器路径。

挂载接口：

- 装配：`content_processors/` 目录是 L2 数据（键为内容身份 entity_ref）；`mount_catalog` 只挂载
  IR 中实际存在的内容，`build_battle_rulebook` 末尾统一装配；RuleBook 携带按 content_id 排序的
  MountedProcessor（content_id + version）。
- 公共挂点：H1 动作执行（通用 preflight 之后、执行计划的**效果阶段**——首个 damage 步或首个
  post-before 窗口；前窗口回调与事件先于处理器效果，后窗口与共享通知链照常；`takeover=False`
  为前置清理，编译图继续执行；`takeover=True` 替换根效果图（OnStart）与 damage_plan，处理器伤害
  命中接回 action_hit_targets 与 post-action notice）；H2 事件监听（监听器分派后，同一 dispatch
  通道与去重规则，重入深度上限 8）；H4 可用性过滤。生命周期节点由 H2 事件覆盖。
- 处理器数值解析：倍率经正式技能参数绑定（L1 binding source，servant 配置 ReadInfo 链）；
  削韧经 L1 ToughnessSystem（compiled emission canonical 表达式优先，action definition 形式
  show_stance_list 回退），随后经 BreakSystem 完成击破与多层溢出；不得按 ParamList 位置猜测
  辅助动作倍率，不得绕过 L1 削韧/击破通路。
- H1 的 ProcessorServices 接收攻击前窗口的类型化增伤贡献，仅合并到当前行动者的伤害包；
  保留包自身贡献，同一贡献只应用一次，HP 消耗不应用增伤。
- 分派：按单位自身 template_id 字典查找（与 action_set 同构），在场门禁；内核不按名称/固定 ID 分支。
- 图覆盖旁路：处理器 `claims_action` 命中的动作，仅跳过 `GRAPH_COVERAGE_BLOCK_PREFIXES` 枚举的
  编译图覆盖类阻断（task_graph_* / effect_coverage_* / bounce_not_executable / condition_not_executable /
  damage_emission_scaling_ratio_not_runtime_bound / process_only_task_coverage_mismatch）；
  availability 与 executor 共用同一枚举。目标、资源、生命周期、控制、身份门禁一律照常，不得绕过。
- 输出与结算：HookResult 携带类型化 mutations/events/rng_events/records，以及内部已派发事件身份与
  归一化结果；外层不得重新派发已消费事件，内部事件沿用原重入深度。ProcessorServices 门面包装
  L1 系统（召唤/状态/伤害/RNG/队列/MutationReducer），内部候选 state 推进；失败零 mutation 零 RNG，
  经既有原子边界整事务拒绝。
- 版本身份：挂载记录进 setup_records（content_id + version，排序确定性）；语义变更必须升版本；
  replay 经 setup_audit 比对拒绝版本漂移；不进 rules_fingerprint。

书写约定：

- 一个内容一个文件（`content_processors/<content>.py`），类注明 content_id、version 与逐行为依据
  （TBGD 能力名 + 固定提交，或资料链接 + 适用版本/条件）。
- 数值一律读数据卡参数；禁止写死倍率/层数/速度；参数缺失 fail-closed，不猜。
- 只经 services 产生 mutation；禁止直接改 state、私写公式、绕过目标/资源/概率/抵抗/免疫/RNG。
- 不读 raw TBGD/TextMap/其它内容卡私有状态；跨卡影响只经公共事件与通用系统。
- 不持有跨调用可变状态；持久信息进类型化 state 字段。
- 最小介入：已可用且语义正确的声明式行为不接管；接管清单与理由逐项记录。
- 第二个内容需要同样行为时，把共同部分提升为通用机制，两处改复用。

### 声明式与处理器的选择

现有通用机制能表达的行为继续用声明。例如“希儿击杀后获得额外行动”已有通用实现，表达为：

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

无论声明还是处理器，都不能表达为：

```text
executor 判断 template_id == Seele
处理器自己改写队列或 HP，而不经 mutation 与通用结算
验证脚本用固定角色名证明机制完成
```

反过来，如果一个行为需要为它单独改动 lowering、IR 和多个 system 才能声明出来，而名单内只有
一个内容使用它，就写处理器，不扩展通用路径。

## 6. L3 外部操作层

### 职责

L3 包含 UI、推演器、CLI 和调试工作台。它们的职责类似玩家：

- 查询当前状态。
- 查询合法动作。
- 查询合法目标。
- 选择 action command。
- 指定或枚举可控 RNG 分支。
- 读取 transition、结算明细和 replay；需要时开启 source audit。
- 展示战斗过程、路径和结算。

### 禁止

- 自己判断技能可用性。
- 自己判断目标范围。
- 自己结算状态、伤害、资源、行动条或队列。
- 自己推导战技点、能量、特殊资源和装备效果。
- 用 mock 结果写入正式 scenario、route 或验收样例。
- 为了 UI 展示方便要求 core 引入非通用字段或伪来源。

UI 可以提前设计最终入口，用来倒查 core/API 缺口；但 UI 需求不能成为牺牲内核通用性和 replay 的理由。推演器也一样，它只负责搜索选择，不负责替内核思考规则。推演器对速度和状态分支的需求是内核的正式需求，见
[性能预算](PROJECT_GOALS.md#性能预算)。

## 7. 复盘、调试与正确性

确定性和可重放是长期约束，对所有层生效：

- 状态变化经类型化 mutation 原子提交；失败时状态、队列和 RNG 不变，并给出原因。
- before snapshot + 命令 + RNG 事件 + mutation 能 replay 成 after snapshot。
- 伤害、治疗、护盾、削韧等结算保留可读的计算明细，供用户和推演器理解结果。

来源审计是可开关的调试与测试能力：

- 规则和处理器在定义处注明实际来源，这是来源可查的全部要求。
- 逐事务来源审计、原生 settlement 与规则定义的互校不是执行路径的必经环节，也不是内容验收的前提；
  需要追查具体问题时显式开启。
- 新功能不以先补齐审计生产者为完成条件；不为审计证据的缺失、替换或篡改新增防伪检查或反例矩阵。
- 已有审计代码不主动扩展。它妨碍性能预算或名单内容接入时，可以改为按需生成、简化或关闭，
  但不得因此放宽原子提交和确定性。

内容是否正确由游戏数值对照判定，见 [PROJECT_GOALS.md](PROJECT_GOALS.md#数值一致)。replay 自洽和审计通过
都不能代替对照。验证选择统一遵循
[本地执行与验证约定](docs/AGENT_WORKFLOW_AND_VALIDATION.md#验证选择)。

## 8. 架构审查

本文件只保存稳定边界，不维护随阶段变化的“当前架构债”。实际债务和后续 owner 应写入当前总计划、
执行卡或 gap 账本，当前进度只写入 `CODEX_HANDOFF.md`。

跨层改动在规划和验收时必须回答：

- 本阶段改动属于哪一层。
- 是否引入了跨层反向依赖。
- 专属行为是否走了成本最低的方式；处理器是否只经 mutation 和通用结算函数产生变化。
- 内核是否只消费稳定 IR / 数据卡 IR 和已装配处理器，没有按内容名称或 ID 分支。
- UI / 推演器是否只查询和提交，没有推导规则。
- source trace 是否只作为审计证据，没有成为 runtime 行为输入。
- 改动是否服务于某个 v1 名单条目；执行热点改动后性能基准是否退化。

## 9. 例外裁决

通用机制表达不了某个名单内容时不需要停工：按第 1 节的顺序选择接入方式，默认写专属处理器并继续。

以下情况先停止实现并交用户裁决：

- 需要改变原子提交、确定性、公开查询或命令契约等公共规则；
- 处理器无法在第 5 节的边界内实现，必须直接改状态或另写结算；
- 规则依据不足或资料互相冲突，且影响当前行为；
- 需要增减 v1 名单、新增依赖或升级来源。

说明该内容在战斗中的作用、现有边界为何不够、最小改动和代价。不得把临时例外、名称特判或验证
fixture 写进内核。
