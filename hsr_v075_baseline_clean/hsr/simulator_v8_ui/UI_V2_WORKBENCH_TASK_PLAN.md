# UI v2 Web 战斗工作台分步计划

本文档是 v8 UI 重做计划，面向后续执行线程。UI v2 的目标不是在底层尚未完整时伪造一个“看起来完整”的模拟器，而是先做接近最终产品形态的 Web 战斗工作台，并把每个功能入口的真实接入状态展示清楚。

UI v2 允许比底层进度更激进地设计页面、入口和交互，但所有规则结果必须来自 v8 core。UI 的提前设计是为了倒查内部接口缺口，不代表内核设计要完全跟随 UI。如果 UI 需求和内核干净度、通用性、来源审计发生冲突，优先保护内核质量；执行线程没有把握时必须停下询问用户决定方向。

## 使用方式

第 8 节是唯一执行清单。执行线程一次只执行一个 UI2-Sx 阶段；完成标记和第 11 节总 checklist 只能由验收线程更新。

第 5 节页面规划、第 6 节契约、第 10 节风险矩阵都是设计参考和查漏资料，不是并行执行清单。执行某一阶段时，只回看对应参考片段；如果参考段和第 8 节完成项发生冲突，以第 8 节为准，并记录需要修正文档的点。

## 0. 当前事实

现有 `simulator_v8_ui/` 是旧本地测试台：

- 后端使用 Python 标准库 HTTP server。
- 前端是原生 HTML / CSS / JS。
- 已支持加载 scenario、运行 route、追加路线、查看行动条、事件回放、伤害审计、blocked/source audit。
- 旧 UI 适合临时调试，不适合作为完整战斗工作台继续扩展。

UI v2 应作为新 Web SPA 起步。旧 UI 可以保留为 legacy testbench 和回归参考，但不作为新界面基础。

## 1. 总目标

UI v2 要形成三个主页面：

- 配置页：开战前配置队伍、敌人、构筑、波次、初始条件和环境入口。
- 战斗页：进战后像玩家一样操作，查询合法动作和目标，提交 action command，查看即时结果。
- 结算页：回顾本次路径，查看每一步 transition、审计、回放和缺口，并支持从任一步回溯。

UI v2 同时要成为机制接入状态仪表盘：

- 哪些入口已经 live 接入 core。
- 哪些入口只是 draft 配置，还未被 runtime 消费。
- 哪些入口被 core blocked。
- 哪些入口是 source gap、admission gap、validation gap 或 out_of_scope。
- 哪些入口只是 mock only，不能保存、不能导出 route、不能参与验收。

## 2. 非目标

UI v2 第一阶段不做：

- 推演器搜索、剪枝、评分函数或自动路线发现。
- 敌方 AI。
- UI 自行计算技能可用性、目标范围、伤害、状态、行动条、能量、装备效果。
- 用 mock 数据生成可验收 scenario 或 route。
- 为了 UI 体验让 core 增加硬编码、默认 fallback、无来源字段或旧接口兼容债。
- 完整光锥、遗器、套装、关卡环境、全角色、全怪物机制复刻。

## 3. 核心原则

### 3.1 UI 只做操作和观测

UI 的定位类似玩家和调试观察者：

- 读取当前局面。
- 查询合法动作。
- 查询合法目标。
- 选择动作、目标和可控 RNG 分支。
- 提交命令。
- 查看 transition、blocked reason、source audit、replay 和 settlement。

UI 不能成为规则来源。所有规则能力必须来自 Canonical IR、数据卡 IR、RuleBook 和 runtime。

UI/API 层只能消费 core 输出的事实与选择集，不能用“常见规则”补齐规则判断。例如战技点通常由普攻生成、战技消耗，但存在增强普攻、替代资源、个人资源、角色机制和特殊入口等例外；因此按钮可用性、资源消耗/生成、技能目标、行动条变化、状态变化和装备效果都必须来自 runtime 输出，不能由前端自行计算或静默修正。

### 3.1.1 派生单位归属和呈现边界

召唤物、servant、忆灵、后场机制实体和其他派生实体不能作为自由配置对象，也不能被 UI 按类型硬塞进固定区域。它们的归属必须来自 core/API 暴露的来源关系：

- 角色派生单位归属角色卡或角色构筑详情，例如 servant / 忆灵子卡、角色技能召唤物、角色特殊资源实体。
- 怪物派生单位归属怪物卡、波次或关卡机制；被召唤怪物自身规则优先来自已有怪物卡。
- 环境、关卡或战斗事件产生的实体归属环境 / 关卡 / BattleEvent，而不是伪装成角色或怪物配置。
- UI 可以展示“该角色 / 怪物 / 机制会产生哪些派生实体”，但不能允许用户把派生实体随意挂到任意角色、怪物或队伍槽位上。
- 是否在场、是否可行动、是否可选中、是否占战场槽位、是否只作为状态容器或机制源存在，都必须由 core/API 给出的 entity projection 决定。

行动队列同样不能把“召唤物 / 忆灵行动”做成独立队列系统。队列只展示 core 输出的行动实体和行动事件；UI 可以显示 entity type、owner、summoner、source、window type、insert reason 等标签，但不能用“是否召唤物/忆灵”自行判断队列规则。

### 3.2 UI 可以提前展示入口，但必须标 readiness

每个功能入口必须有接入状态：

- `live`：来自真实 core API，可执行，可审计，可 replay。
- `draft_only`：可配置并进入 draft，但 runtime 当前不消费。
- `blocked`：core 明确 blocked，并有 reason。
- `source_gap`：当前来源链缺失。
- `admission_gap`：有来源但未准入。
- `validation_gap`：runtime 可能支持，但 UI/API/验证尚未闭环。
- `out_of_scope`：不属于当前阶段。
- `mock_only`：仅用于视觉和交互设计，不参与保存、导出、验收。

没有 readiness 的入口不允许合入 UI v2 主流程。

### 3.3 Mock 和 live 严格隔离

mock mode 只用于视觉设计、布局评审和交互草稿。

mock only 数据禁止：

- 保存进正式 scenario。
- 导出 route。
- 参与 live run。
- 冒充 expected result。
- 作为底层规则补全依据。

验收必须覆盖 live mode 最小闭环。

### 3.4 不为 UI 牺牲内核

UI 的 view model 可以有适配层，但不能要求 core 为 UI 牺牲通用性、来源审计、数据卡归属或 runtime 干净度。

如果某个 UI 需求需要 core 增加字段或 API，执行线程必须先判断：

- 这个字段是否有真实来源。
- 是否属于通用 runtime / 数据卡 / RuleBook 契约。
- 是否只是 UI 展示便利字段。
- 是否会造成硬编码、默认 fallback、旧接口兼容债或伪来源。

判断不清时停止实现，记录问题并询问用户。

## 4. 技术路线

推荐路线：

- Web 起步：Vite + React + TypeScript。
- Python 本地后端继续提供 v8 API，后续可重构为更明确的 UI API 层。
- 前端和后端通过稳定 UI view model 通信，不直接绑定临时 report 内部结构。
- 后续如需要程序形式，再考虑 Tauri 包装同一套 Web 前端。

不建议第一阶段使用原生桌面 UI。原因是 UI v2 需要大量嵌套数据、表格、筛选、树形审计、diff、JSON/source trace 查看，Web 技术更适合。

## 5. 页面规划

### 5.1 配置页

配置页负责开战前输入和准入展示。它只保存用户草案和来源选择，不直接生成 runtime mutation。入口细节见 5.4.2；执行清单见 UI2-S3。

### 5.2 战斗页

战斗页负责进战后的玩家式操作：读取局面、查询合法动作和目标、提交 command、查看 transition。入口细节见 5.4.3；执行清单见 UI2-S4。

### 5.3 结算页

结算页负责 route 回顾、审计、replay 和 fork 回溯。它是开发工具级回顾页，不只是最终结果页。入口细节见 5.4.4；执行清单见 UI2-S5。

### 5.4 页面与功能入口总览

本节是实现时的防漏清单。UI2-S3 / S4 / S5 / S6 执行时，应逐项确认入口、展示方式、数据契约和 readiness，而不是只实现页面外壳。

#### 5.4.1 全局框架

所有页面共享：

- 顶部运行栏：当前模式、当前 case/session、live/mock 标记、readiness 汇总、保存状态、最后一次 core/API 错误。
- 主导航：配置、战斗、结算。数据与缺口浏览不单独作为第四主页面，优先作为配置页/结算页的侧栏、抽屉或标签页入口。
- 全局状态标记：live、draft_only、blocked、gap、mock_only 必须视觉上可区分。
- 全局来源入口：任意可见机制入口都能打开来源/缺口详情，至少显示 owner domain、readiness、reason。
- 全局禁止行为：页面不能因为展示便利自行补规则、补目标、补资源、补状态或补行动条。

#### 5.4.2 配置页功能拆解

推荐布局：

- 左侧：CatalogView 选择器和数据浏览入口。
- 中部：BattleSetupDraft 编辑区。
- 右侧：SetupAdmissionView、readiness/gap 面板、来源摘要。
- 底部或顶部固定操作区：保存草案、校验配置、开始战斗、导入/导出草案。

配置页必须有以下入口：

- Case 基本信息入口：名称、说明、目标、模式、版本、标签。
- 我方队伍入口：四个角色位、站位、等级、晋阶、星魂、行迹、技能等级、初始能量或导入快照资源。
- 角色构筑入口：光锥、叠影、等级、晋阶、遗器六件、主副词条、套装、面板预览、特殊资源。当前未实现的效果只允许 draft_only/gap；面板覆盖只能作为明确标记的调试/导入快照入口。
- 角色派生单位入口：在角色卡 / 角色构筑详情下展示 servant / 忆灵子卡、owner、来源、生命周期和 readiness；是否开局生成、HP、速度、行动值等生效结果只做 core 计算后的只读预览。
- 敌方入口：波次、敌人槽位、怪物卡、等级、模板、阶段、初始状态；弱点、抗性、韧性只做数据卡/关卡覆盖后的预览，或作为带来源的特殊覆盖入口。
- 怪物派生单位入口：在怪物卡、波次或关卡机制详情下展示 spawn intent、owner/summoner relation、被召唤怪物卡和生命周期绑定；不允许作为敌方配置里的自由挂载项。
- 关卡与环境入口：Stage、BattleEvent、环境机制、关卡倍率、胜负条件、轮次/周期设置。
- 初始局面入口：战技点、队伍资源、特殊资源、初始状态、开局行动序预览、预置 RNG seed/choice ledger。fresh battle 的行动值/行动条由 core 根据速度、构筑、技能、关卡和入场效果计算；只有导入 snapshot/fork 时才能携带既有行动值。
- 准入入口：校验配置、查看会被 core 消费的字段、查看被剥离字段、查看 blocked/gap。

展示规则：

- CatalogView 只展示可选项和来源，不展示“已生效”。
- BattleSetupDraft 只展示用户草案，不展示“已结算规则结果”。
- SetupAdmissionView 才能展示“哪些字段会进入 live session”。
- fresh battle 的普通输入应优先是来源选择，例如角色、构筑、敌人、关卡、技法或真实开局条件；派生结果由 core 计算后只读展示。
- 精确 HP、资源、状态、行动值等只允许作为导入 snapshot、fork、调试用例或带真实来源的高级初始条件，并必须经过 SetupAdmissionView 标明来源和 readiness。
- 光锥、遗器、环境、派生实体来源等未来入口必须有 readiness，不能因为 UI 上能选就显示为已生效。
- 初始行动值、行动条、速度、弱点、抗性、韧性、最终面板等派生结果默认只读展示；若出现手工输入，必须标为调试/导入快照/真实覆盖，并经过 SetupAdmissionView。
- 派生单位不作为队伍级或敌方槽位级自由配置对象；配置页只能在其来源对象详情中展示入口和预览，并通过 SetupAdmissionView 说明哪些派生入口会进入 live session。

#### 5.4.3 战斗页功能拆解

本节只列战斗页需要展示和操作的入口，不规定具体布局。战斗页视觉布局后续单独设计。

当前参考布局稿：

```text
hsr_battle_sim_ui_v10_toughness_fixed.html
```

该 HTML 只作为战斗页信息架构参考，不是最终视觉实现，也不是 live 数据契约。它可以吸收的结构是：

- 顶部运行栏：展示当前波次、轮次/周期、模式、速度、保存、撤销、重算等 session 级操作。
- 左侧行动序：展示 core 输出的行动实体 / 行动事件、行动值、插入窗口和 ready/blocked 状态。
- 中部战场视图：优先展示当前可见、可交互、可选中的前场单位和目标槽位；单位卡内展示 HP、韧性、弱点、状态摘要。
- 右侧对象详情：展示当前选中对象的属性、状态、目标关系、来源摘要和进一步详情入口。
- 底部行动区：展示当前 actor、资源摘要、合法动作、插入窗口、预估摘要和确认/详情操作。
- 预估摘要：只展示 core preview / transition 返回的结果，例如伤害、韧性变化、资源变化、状态变化、blocked reason。

参考稿不能直接继承的点：

- 不能固定 `1440x900` 或依赖 `overflow:hidden` 裁切内容；真实页面必须支持响应式约束和可滚动/可折叠区域。
- 不能把示意图中的伤害、削韧、SP、推荐动作等 mock 文案当成 UI 计算结果。
- 不能把“召唤物 / 忆灵行动”作为独立队列类别；行动序只展示 core 输出的行动实体 / 行动事件。
- 不能假设所有派生实体都在主战场卡片中；后场实体、机制源、状态容器和不在场实体应通过实体关系视图、详情抽屉或审计入口展示。
- 不能假设敌方固定 4 个显示槽位；战场视图必须支持游戏槽位、召唤 / 退场 / 隐藏 / pending spawn 等 entity projection。
- 正式 UI 中不要保留版本号、修正版说明、布局说明等实现阶段文案。

战斗页必须有以下入口：

- 单位详情入口：HP、韧性、弱点、状态、护盾、能量、特殊资源、owner/召唤关系。
- 状态详情入口：状态类型、层数、持续时间、可否驱散、来源、下一次 tick/回合减少条件。
- 行动序入口：查看 core 输出的行动实体、行动事件、行动值、队列插入、额外行动和战斗事件窗口；每项可显示 actor/entity、owner、source、window type、insert reason、ready/blocked。
- 战场视图入口：展示当前可见、可交互、可选中的 combatant / target slot，包括前场单位、可选中派生单位和隐藏/退场提示。
- 实体关系入口：展示 owner、summoner、servant、派生单位、后场实体、状态容器、机制源和生命周期绑定。
- 动作选择入口：展示当前 actor 的合法动作候选，例如普攻、战技、终结技、天赋/追加/反击、怪物动作、派生实体动作、环境动作；候选来源和 blocked reason 均来自 core/API。
- 目标选择入口：合法目标、自动目标、实际打击范围预览、不可选 reason。
- RNG 选择入口：命中/抵抗、暴击、随机目标、随机弹射、随机效果；未接入时必须显示 gap。
- 命令提交入口：提交 command、查看 blocked、追加 route、撤销上一步。
- 即时结果入口：展示本步伤害、状态、资源、行动条、派生实体变化、结算和审计摘要。

展示规则：

- 所有按钮启用/禁用来自 BattleViewState / CommandChoiceView。
- 战技点、能量、特殊资源、目标范围、行动条、状态变化都只展示 runtime 输出。
- 敌方动作不由 UI 自动选择；UI 只展示 core 给出的候选，用户或未来推演器负责选择。
- target preview 只能展示 core 返回的目标解析结果，不能用站位或名称自行推断。
- 战斗页不能用“是否召唤物/忆灵”决定实体显示位置；必须使用 core/API 给出的 presentation role、visibility、targetability、actionability、slot relation、owner relation 和 lifecycle。
- 有些派生实体在后场，有些只作为机制源或状态容器，有些不在场上但仍有生命周期；这些实体应通过实体关系视图、详情抽屉或审计入口展示，不能强行塞进主战场卡片。

#### 5.4.4 结算页功能拆解

推荐布局：

- 顶部：run summary、胜负/目标达成、总步数、总伤害、总回合/周期、gap/audit/replay 汇总。
- 左侧：route timeline，按 step 展示 actor、action、targets、结果、blocked/gap。
- 中部：step detail，展示 before/after snapshot diff、transition、mutation、settlement。
- 右侧：source audit、replay、RNG ledger、gap 分类、fork 操作。
- 底部或抽屉：导出报告、导出 route、复制 fork 请求、返回战斗页继续。

结算页必须有以下入口：

- 路径总览入口：按步筛选成功、blocked、gap、RNG、状态变化、伤害、派生实体事件。
- Step 详情入口：before、after、command、target resolution、mutation、settlement、process event。
- 伤害拆解入口：direct、DoT、break、super-break、hp loss、true damage、blocked damage。
- 状态拆解入口：apply、refresh、stack、remove、dispel、tick、blocked、immune/resist。
- 资源拆解入口：战技点、能量、特殊资源、冷却、计数器。
- 时间线拆解入口：行动值、队列、额外行动、turn owner、pending turn end。
- RNG ledger 入口：choice key、event id、选项、结果、来源、是否用户指定。
- Source audit 入口：mutation -> settlement -> IR -> TBGD source。
- Replay 入口：before + command + mutations 是否复原 after。
- 回溯入口：从任一步 before 或 after 创建 fork session。

展示规则：

- 游戏内结算通常不需要这么细，但本模拟器的结算页必须是开发工具级回顾页。
- replay/source audit/traceability 失败必须醒目标记，不能用最终胜负掩盖。
- 回溯不能改写历史 route，只能创建带 fork metadata 的新 session。

#### 5.4.5 数据与缺口浏览入口

数据与缺口浏览不是独立主流程，但 UI2-S6 必须提供入口，避免用户只能靠命令行理解当前接入状态。

入口归属：

- 配置页：CatalogView 侧栏展示角色、怪物、装备、遗器、状态、派生实体来源、关卡、环境候选。
- 战斗页：当前 action、target、状态、派生实体、RNG、blocked reason 的来源详情抽屉。
- 结算页：按 step 查看 source audit、replay、gap matrix、transition contract。

必须支持：

- 按 domain 查看 live / draft_only / blocked / source_gap / admission_gap / validation_gap / mock_only。
- 查看每个 gap 的 owner、reason、后续阶段归属。
- 从 UI 暴露“缺哪个 core/API 契约”，但不能在 UI 里补规则。

## 6. UI View Model 契约

UI v2 不应直接贴着当前临时 report 结构写页面。需要定义稳定 view model，并由后端适配当前 core 输出。

契约设计必须先区分四类事实：

- 游戏展示事实：玩家在游戏内能看到的局面信息，例如单位、血量、韧性、弱点、状态、行动序、战技点、能量、派生实体、技能按钮和目标选择。
- 用户输入事实：配置页输入队伍、敌人、构筑、波次、环境和初始条件；战斗页输入动作、目标、终结技窗口和可控 RNG 分支；结算页输入回溯位置。
- 数据目录事实：TBGD / lowering / 数据卡能提供哪些角色、怪物、装备、遗器、状态、派生实体来源、关卡和战斗事件候选项，以及这些候选项当前是否能被 core 消费。
- runtime 事实：当前战斗状态、合法动作、合法目标、资源门、blocked reason、transition、settlement、source audit 和 replay 结果。

UI view model 是显示和操作适配层，不是 core 契约本身。目录事实不能冒充 runtime 事实，游戏展示文本不能冒充规则来源，配置草案不能冒充已生效状态。

第一阶段建议按以下契约分层定义。

### 6.1 FeatureReadiness

每个可见功能入口都应携带 readiness：

```text
status: live | draft_only | blocked | source_gap | admission_gap | validation_gap | out_of_scope | mock_only
label: string
reason: string
source_trace?: object
owner_domain: setup | battle | settlement | data
blocks_export: bool
blocks_live_run: bool
```

### 6.2 CatalogView

目录页和配置页共用的候选项来源。它负责告诉 UI “可以选择什么”，不负责告诉 UI “规则会发生什么”。

必须覆盖：

- 角色、怪物、派生实体来源、servant / 忆灵子卡、光锥、遗器、状态、关卡、波次、战斗事件、环境入口。
- 每个候选项的来源、显示名、图标/类型、基础分类和 readiness。
- 候选项是否只是目录可见，还是已经能进入 setup validation、session start 或 live runtime。

### 6.3 BattleSetupDraft

配置页的主对象。它保存用户想要开战的草案，不代表已经通过 core 准入。

必须覆盖：

- 我方队伍、角色等级/晋阶/星魂/行迹/技能等级入口。
- 光锥、遗器、套装、属性预览和未来构筑输入入口；属性覆盖只能作为调试、导入快照或带真实来源的特殊覆盖。
- 角色派生单位子卡入口只能挂在角色卡 / 构筑详情下；配置草案不能把派生实体作为队伍级自由槽位。
- 敌方怪物、等级、模板、阶段和派生单位来源入口；弱点、抗性、韧性默认是数据卡/关卡覆盖后的只读预览。
- 怪物派生单位入口只能挂在怪物卡、波次或关卡机制详情下；配置草案不能把被召唤怪物自由挂到任意召唤者。
- 波次、关卡、环境、战斗事件、初始状态和初始资源入口。
- 每个配置块的 readiness、来源、是否阻止 live run、是否允许只保存 draft。

### 6.4 SetupAdmissionView

开战准入结果。它负责告诉 UI “这份配置现在能不能开战，以及哪些部分没有生效”。

必须覆盖：

- 可开战、不可开战、仅草案、部分接入、blocked/gap 的明确状态。
- 每个配置块的准入结果和 reason。
- 被剥离的 mock_only / draft_only 字段清单。
- session start 会实际提交给 core 的最小输入摘要。

### 6.5 BattleViewState

战斗页的主对象。它只描述当前状态和 core 给出的可操作 choices，不携带规则计算逻辑。

必须覆盖：

- 当前实体投影，包括前场单位、友方、敌方、可选中派生单位、后场实体、状态容器、机制源和战斗事件实体。
- HP、韧性、弱点、状态、护盾、能量、战技点、特殊资源、行动序和当前窗口。
- presentation role、visibility、targetability、actionability、slot relation、owner/summoner relation 和 lifecycle。
- 当前可选动作、资源门、目标门、blocked reason、可控 RNG 分支。
- 上一步 transition 摘要和 replay/source audit 状态。

### 6.6 CommandChoiceView

战斗页提交命令前使用的选择集。它负责把 core 允许的操作暴露给用户或未来推演器。

必须覆盖：

- 当前窗口允许哪些动作。
- 每个动作允许哪些目标。
- 是否需要 RNG choice、是否允许枚举分支、缺 choice 时如何 blocked。
- command 提交后对应的 transition id / blocked id。

### 6.7 SettlementReviewView

结算页和回溯页的主对象。它比游戏内结算更详细，属于模拟器开发工具增强视图。

必须覆盖：

- route step、before/after snapshot、transition、mutation、settlement、process event、rng event。
- source audit、replay、blocked/gap 分类、可回溯 fork 点。
- 从任一步 before/after 创建新分支的请求与来源记录。

### 6.8 GameDisplayProjection

面向类游戏 UI 的显示投影。它负责把 runtime 事实转成适合页面呈现的形态，例如图标、标签、排序、折叠层级和提示文本。

显示边界：

- 显示名、图标、颜色、分组、tooltip、紧凑摘要。
- 把同一个 runtime 事实投影到配置页、战斗页或结算页的不同展示形态。
- 展示 TextMap 或外部资料作为说明文本，但必须标明它只用于展示，不进入 runtime。

## 7. API 规划

第一阶段可先由现有 Python server 扩展 API，不急着替换全部后端。

建议 API：

- `GET /api/v2/health`
- `GET /api/v2/catalog`
- `GET /api/v2/readiness`
- `GET /api/v2/cases`
- `GET /api/v2/cases/{id}`
- `PUT /api/v2/cases/{id}`
- `POST /api/v2/setup/validate`
- `POST /api/v2/session/start`
- `GET /api/v2/session/{id}`
- `POST /api/v2/session/{id}/command`
- `POST /api/v2/session/{id}/undo`
- `POST /api/v2/session/{id}/fork`
- `GET /api/v2/session/{id}/settlement`

API 约束：

- API 可以返回 UI view model，但不能伪造 runtime 结果。
- API 不得让 UI 直接读取 raw TBGD。
- API 不得把 mock mode 和 live session 混在同一 session id。
- API 返回 blocked/gap 时必须结构化。

## 8. 分步计划

### 8.0 执行协议

本计划必须按 UI2-S0 到 UI2-S8 顺序执行。任一执行线程一次只执行一个阶段；后续阶段只能作为背景阅读，不能提前实现、提前打勾或把后续目标混进当前阶段。

阶段状态只允许五种：

- `not_started`：未开始。
- `in_progress`：当前唯一正在执行的阶段。
- `ready_for_review`：执行线程认为本阶段已可验收，但尚未由验收线程确认。
- `blocked`：本阶段因缺依赖、缺接口或方向不明无法继续，必须写明 blocker 和下一步归属。
- `done`：验收线程确认本阶段所有完成项均可打勾，且不触发本阶段“不允许打勾”的情况。

执行线程不能自认完成。执行线程最多只能把阶段交付为 `ready_for_review`，并提交代码、验证输出、报告和剩余 gap；`done`、完成标记 `[x]`、第 11 节总 checklist 只能由验收线程更新。

每个阶段开始前，执行线程必须先提交本阶段执行卡，等待确认后才能改文件。执行卡必须具体到可执行动作，不能复述本计划条款：

```text
阶段：
目标产物：
本阶段只改哪些文件：
本阶段禁止改哪些文件：
将新增/修改哪些函数、类型、脚本或页面：
用哪些结构化谓词判断通过：
哪些情况必须判定为 blocked/gap/deferred：
要跑哪些验证，为什么这些验证足够：
哪些验证本阶段明确不跑，原因是什么：
预计资源风险和限峰值措施：
完成后提交哪些 evidence：
```

执行线程每次开始一个阶段时，只读以下范围作为主上下文：

- 当前阶段小节。
- 第 3 节核心原则。
- 第 5.4 节中与当前阶段对应的功能入口。
- 第 6 节中与当前阶段对应的契约。
- 第 9 节验证策略。

不要把整个 UI v2 计划当成一次性实现清单。第 5.4 节是防漏索引，不代表当前阶段要把所有入口都做完。

打勾规则：

- 只有完成项对应的代码、页面、契约或验证真实存在，并由验收线程确认，才允许把 `[ ]` 改成 `[x]`。
- 执行线程不能修改 checklist，不能自称 `done`，不能把报告当作完成证据；执行线程只能提交 `ready_for_review`。
- 未完成项不能用“后续会补”打勾；应保留 `[ ]`，并在阶段汇报中说明 blocker / gap / deferred。
- 一个阶段未 `done` 前，不允许开始下一个阶段的实现。
- 如果为了当前阶段需要创建后续阶段的占位，必须标为 `deferred` / `draft_only` / `mock_only`，不能实现成假 live。
- `ok=true` 不是完成证明。验收时必须说明该验证检查了什么、没检查什么、是否存在过宽 predicate、是否把 gap 用 executable 正例覆盖。
- 报告不是证据本身。报告必须引用真实代码改动、真实验证输出、真实矩阵/summary 或可反查的 source/audit。
- 资源控制是限制峰值，不是跳过必要验证。必要长验证可以串行、低优先级、输出到 `/tmp` 运行；禁止并行重验证、默认写大产物或跑无关全量。

### UI2-S0 范围定界和旧 UI 冻结

阶段状态：`not_started`

一句话目标：把旧 UI 和 UI v2 的工程边界切开，避免后续在旧测试台上继续堆功能。

本阶段只做：

- 旧 UI legacy 边界。
- UI v2 目录、命名、启动和依赖策略。
- 最小文档入口。

本阶段不做：

- 不实现页面功能。
- 不接 core API。
- 不设计完整视觉。

完成标记：

- [ ] UI2-S0.1 文档说明旧 UI 只作 legacy testbench，不作为 UI v2 主实现。
- [ ] UI2-S0.2 UI v2 目录、命名和运行边界明确。
- [ ] UI2-S0.3 UI v2 不复用旧 `static/app.js` 作为主实现。
- [ ] UI2-S0.4 依赖列表、启动方式、构建方式有记录；新依赖已获用户接受。
- [ ] UI2-S0.5 新旧 UI 不共用混乱状态文件。

不允许打勾：

- 在旧 UI 上继续堆大功能。
- 旧 UI 和 UI v2 的 session、case、route 状态混在一起。

最小验证：

- `git diff --check`
- 如已创建新前端目录，运行对应 package 的最小安装/启动说明检查，不要求完整构建。

### UI2-S1 技术骨架和页面路由

阶段状态：`not_started`

一句话目标：建立可运行的 Web SPA 壳子和三页面路由，但不实现规则和业务功能。

本阶段只做：

- 前端工程骨架。
- 配置、战斗、结算三条路由。
- 全局导航、loading、error、empty、blocked/gap 基础状态容器。

本阶段不做：

- 不接 live core API。
- 不实现完整配置表单、战斗操作或结算回溯。
- 不写前端规则计算。

完成标记：

- [ ] UI2-S1.1 `npm run dev` 或等价命令能启动。
- [ ] UI2-S1.2 三个主页面都有稳定可访问路径。
- [ ] UI2-S1.3 全局导航能在配置、战斗、结算之间切换。
- [ ] UI2-S1.4 loading、error、empty、blocked/gap 占位状态存在。
- [ ] UI2-S1.5 页面不依赖 mock 规则结果才能渲染。
- [ ] UI2-S1.6 TypeScript 类型检查通过。

不允许打勾：

- 做成单页塞满配置、战斗、结算。
- 页面需要假 battle result 才能打开。
- 缺错误态或空态。

最小验证：

- `npm run typecheck`
- `npm run build`，若本阶段尚未配置 build，必须说明替代验证。
- `git diff --check`

### UI2-S2 View Model 和 readiness 契约

阶段状态：`not_started`

一句话目标：先定义 UI 能消费什么事实和选择集，再允许页面实现细节。

本阶段只做：

- 第 6 节的 view model 类型。
- readiness 状态和展示规范。
- mock/live 数据隔离。
- 最小 mock fixture 和最小 live adapter 边界。

本阶段不做：

- 不实现完整配置页。
- 不实现战斗 live loop。
- 不把临时 raw report 深层字段绑定成长期 UI API。

完成标记：

- [ ] UI2-S2.1 定义 `FeatureReadiness`，包含 status、reason、owner domain、blocks_export、blocks_live_run。
- [ ] UI2-S2.2 定义 `CatalogView`，并明确只提供候选项和来源，不冒充 runtime 事实。
- [ ] UI2-S2.3 定义 `BattleSetupDraft` 和 `SetupAdmissionView`，配置草案必须经过准入才可进入 live session。
- [ ] UI2-S2.4 定义 `BattleViewState` 和 `CommandChoiceView`，按钮、目标、资源门都来自 core/API。
- [ ] UI2-S2.5 定义 `SettlementReviewView`，能承载 step-level transition、audit、replay 和 fork。
- [ ] UI2-S2.6 定义 `GameDisplayProjection`，只做显示适配，不覆盖 runtime 事实。
- [ ] UI2-S2.7 mock/live 数据有明确模式和来源标记。
- [ ] UI2-S2.8 mock only 数据不能保存为正式 scenario，不能导出 route。

不允许打勾：

- 组件直接依赖临时 raw report 深层字段。
- 组件直接读取 raw TBGD 或 TextMap 作为规则来源。
- UI 把目录项、配置草案或显示投影当成已生效 runtime 状态。
- UI 自行推导按钮可用性、资源变化、目标范围、行动条或状态变化。

最小验证：

- `npm run typecheck`
- 可选：view model schema/unit 测试。
- `git diff --check`

### UI2-S3 配置页第一版

阶段状态：`not_started`

一句话目标：做出可创建、编辑、保存、校验的配置页，但不让未接入机制假装生效。

本阶段只做：

- 对照 5.4.2 实现配置页入口。
- `BattleSetupDraft` 创建、编辑、保存。
- `SetupAdmissionView` 准入摘要。
- readiness/gap 显示。

本阶段不做：

- 不实现战斗 live loop。
- 不把光锥、遗器、环境等 draft_only 效果折算进 runtime 状态。
- 不手工配置 fresh battle 的初始行动值、行动条、速度、弱点、抗性、韧性或最终面板。

完成标记：

- [ ] UI2-S3.1 Case 基本信息入口可编辑。
- [ ] UI2-S3.2 我方队伍入口可编辑，包含角色位、站位、等级、晋阶、星魂、行迹、技能等级、初始能量或导入快照资源。
- [ ] UI2-S3.3 角色构筑入口存在，未接入效果显示 draft_only/gap，不伪装成 live。
- [ ] UI2-S3.4 角色派生单位入口只存在于角色卡 / 构筑详情下，owner、来源、生命周期预览有 readiness，不作为队伍级自由配置。
- [ ] UI2-S3.5 敌方与波次入口存在，弱点、抗性、韧性只做来源预览或真实覆盖结果展示。
- [ ] UI2-S3.6 关卡、环境、战斗事件入口存在，当前只做真实预留和 readiness。
- [ ] UI2-S3.7 初始局面入口存在，派生行动序只读预览；snapshot/fork 才可携带既有行动值。
- [ ] UI2-S3.8 setup validation summary 清楚列出哪些字段会被 runtime 消费、哪些被剥离、哪些 blocked/gap。
- [ ] UI2-S3.9 可保存 draft；正式 scenario 拒绝或剥离 mock_only 字段。

不允许打勾：

- UI 直接把装备、遗器、环境效果落成 runtime 状态。
- 未实现配置项静默丢弃且不提示。
- 配置页生成 runtime mutation。

最小验证：

- `npm run typecheck`
- 配置页 DOM smoke 或组件测试。
- `git diff --check`

### UI2-S4 战斗页第一版 live loop

阶段状态：`not_started`

一句话目标：让战斗页通过真实 core/API 完成最小“看局面、选动作、选目标、提交、看 transition”闭环。

本阶段只做：

- 对照 5.4.3 实现战斗页入口。
- `BattleViewState` 渲染。
- `CommandChoiceView` 驱动动作、目标、RNG 选择。
- command submit、route append、undo、blocked reason 和当前 step transition 摘要。

本阶段不做：

- 不做结算页完整回顾。
- 不做推演器搜索。
- 不自动替敌方选择动作。
- 不手写 route JSON 作为主流程。

完成标记：

- [ ] UI2-S4.1 能加载现有最小 live scenario 并进入战斗页。
- [ ] UI2-S4.2 战斗页按参考布局稿的信息分区组织顶部运行栏、行动序、战场视图、对象详情、底部行动区，但不固定视觉尺寸。
- [ ] UI2-S4.3 单位 / 实体投影、HP、韧性、弱点、状态、能量、战技点、行动序来自 BattleViewState。
- [ ] UI2-S4.4 action choices 来自 core/API，不由 UI 推导技能可用性。
- [ ] UI2-S4.5 target choices 来自 core/API，不由 UI 推导目标范围。
- [ ] UI2-S4.6 RNG choice 入口存在；缺 choice 时由 core blocked。
- [ ] UI2-S4.7 可提交合法 command 并追加 route。
- [ ] UI2-S4.8 非法动作、非法目标、缺来源时展示 core blocked reason。
- [ ] UI2-S4.9 当前 step transition 摘要可见。
- [ ] UI2-S4.10 undo 或回退当前 session 状态可用，且不改写历史 transition。

不允许打勾：

- 通过手写 route JSON 作为主交互闭环。
- UI 自动选敌方动作。
- UI 静默修正非法命令。
- UI 自行计算技能可用性、目标范围、战技点、能量、行动条、状态或伤害。

最小验证：

- `npm run typecheck`
- 最小 live loop 验证：load scenario -> start session -> get battle view -> submit command -> see transition。
- `git diff --check`

### UI2-S5 结算页和回溯

阶段状态：`not_started`

一句话目标：让用户能逐步回顾 route，并从任一步 before/after fork 出新分支。

本阶段只做：

- 对照 5.4.4 实现结算页入口。
- route timeline。
- step detail。
- audit/replay/settlement traceability。
- before/after fork。

本阶段不做：

- 不补规则结果。
- 不从日志反推 settlement。
- 不做完整数据目录浏览。

完成标记：

- [ ] UI2-S5.1 route step list 可按成功、blocked、gap、RNG、状态变化、伤害、派生实体事件浏览。
- [ ] UI2-S5.2 每步可查看 before/after snapshot、command、target resolution、mutation、settlement、process event。
- [ ] UI2-S5.3 伤害、状态、资源、时间线、RNG 分组可见。
- [ ] UI2-S5.4 source audit 可见，至少能展示 mutation -> settlement -> IR -> source 的链路摘要。
- [ ] UI2-S5.5 replay 结果可见，失败时醒目标记。
- [ ] UI2-S5.6 可以从任一步 before snapshot fork。
- [ ] UI2-S5.7 可以从任一步 after snapshot fork。
- [ ] UI2-S5.8 fork 保留 fork_from_run_id、fork_from_step、fork_point。
- [ ] UI2-S5.9 原历史 route 不被改写。

不允许打勾：

- 回溯修改原 route。
- 结算页不展示 source audit/replay。
- 用日志反推 settlement。
- 只展示最终结果，不支持 step-level 回顾。

最小验证：

- `npm run typecheck`
- route review + fork smoke。
- `git diff --check`

### UI2-S6 数据和缺口浏览

阶段状态：`not_started`

一句话目标：把当前可用能力和缺口在 UI 里结构化展示，帮助倒查 core/API 缺口，但不让 UI 补规则。

本阶段只做：

- 对照 5.4.5 实现跨页面数据与缺口入口。
- catalog summary。
- readiness / coverage matrix。
- gap owner / reason / 后续归属。

本阶段不做：

- 不单独扩成第四主流程。
- 不读取 raw TBGD 给 runtime 用。
- 不用 UI 数据页人工补规则。

完成标记：

- [ ] UI2-S6.1 配置页有 CatalogView 入口，可查看角色、怪物、装备、遗器、状态、派生实体来源、关卡、环境候选。
- [ ] UI2-S6.2 战斗页有当前 action、target、状态、派生实体、RNG、blocked reason 的来源详情入口。
- [ ] UI2-S6.3 结算页有 source audit、replay、gap matrix、transition contract 入口。
- [ ] UI2-S6.4 能按 domain 查看 live、draft_only、blocked、source_gap、admission_gap、validation_gap、mock_only。
- [ ] UI2-S6.5 每个 gap 有 owner、reason 和后续阶段归属。
- [ ] UI2-S6.6 数据浏览不读取 raw TBGD 作为 UI 规则来源。

不允许打勾：

- 数据页展示 TextMap 后让 runtime 使用。
- 用 UI 数据页人工补规则。
- gap 只显示人类文本，没有结构化分类和 owner。

最小验证：

- `npm run typecheck`
- readiness/gap browse smoke。
- `git diff --check`

### UI2-S7 视觉和交互打磨

阶段状态：`not_started`

一句话目标：在关键契约和 live loop 已通过后，把三页打磨成长期可用的工作台。

本阶段前置门禁：

- UI2-S2 必须 done。
- UI2-S4 必须 done。
- UI2-S5 必须 done。

本阶段只做：

- 信息层级、密度、可读性、状态 badge、筛选、折叠、详情抽屉、键盘/鼠标操作体验。
- 桌面视口和必要移动/窄屏降级。

本阶段不做：

- 不用视觉打磨替代 live loop。
- 不新增 core 规则。
- 不扩大功能范围到全角色、全怪物、全构筑机制。

完成标记：

- [ ] UI2-S7.1 配置页分区清楚，draft/live/gap 状态易识别。
- [ ] UI2-S7.2 战斗页吸收参考布局稿的信息层级，动作、目标、blocked reason、transition 摘要不拥挤。
- [ ] UI2-S7.3 结算页 step 回顾、审计分组、diff、回溯入口清楚。
- [ ] UI2-S7.4 loading、error、empty、blocked、gap 常见状态都有设计。
- [ ] UI2-S7.5 桌面视口关键文本不重叠，核心操作不依赖打开 JSON 编辑器。

不允许打勾：

- 只做视觉，不接 live loop。
- 页面拥挤到无法定位动作、目标和审计。
- 在 UI2-S2、UI2-S4、UI2-S5 未通过前，把视觉打磨当成 UI v2 完成。

最小验证：

- `npm run typecheck`
- `npm run build`
- 关键页面 DOM smoke 或截图检查。
- `git diff --check`

### UI2-S8 验收、报告和交接

阶段状态：`not_started`

一句话目标：用最小必要验证证明 UI v2 没有绕过 core、没有 mock/live 混淆，并留下交接报告。

本阶段只做：

- 聚合验收。
- 验证报告。
- 剩余 gap 和后续接口需求记录。

本阶段不做：

- 不新增 UI 功能。
- 不用验收阶段临时补规则。
- 不为了报告改 core 行为。

完成标记：

- [ ] UI2-S8.1 前端类型检查通过。
- [ ] UI2-S8.2 前端构建通过。
- [ ] UI2-S8.3 后端 compileall 通过。
- [ ] UI2-S8.4 UI live loop 验证通过，且使用真实 core/API。
- [ ] UI2-S8.5 mock/live 隔离验证通过，mock_only 不进入正式 scenario/route。
- [ ] UI2-S8.6 readiness 展示验证通过。
- [ ] UI2-S8.7 关键页面 DOM smoke 或截图检查通过。
- [ ] UI2-S8.8 报告记录剩余 gap、blocked 项、后续 core/API 需求。

不允许打勾：

- 只靠 mock 截图验收。
- 没有检查 UI 是否绕过 core admission。
- 没有记录未接入功能。

最小验证：

- `PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui`
- `npm run typecheck`
- `npm run build`
- 最小 live loop 验证。
- mock/live 隔离验证。
- readiness 展示验证。
- `git diff --check`

## 9. 验证策略

最小验证：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

如果引入前端工程：

```bash
npm run typecheck
npm run build
```

UI live loop 验证应覆盖：

- 加载最小 scenario。
- setup validation。
- start session。
- 查询 battle view。
- 选择 live action / target。
- 提交 command。
- 查看 transition。
- fork 到某一步继续。
- mock only 不可保存/导出。

高负载限制：

- UI 验证默认不触发全量 TBGD 大产物输出。
- 后端启动可以缓存 RuleBook，但验证脚本不得重复并行构建多个完整 RuleBook。
- 截图或端到端验证只跑必要页面，不做全量组合爆炸。

## 10. 风险控制矩阵

本节把 UI 提前设计的主要劣势转成硬约束。验收时必须逐项检查，不能只看页面是否能打开。

### 10.1 范围膨胀

风险：

- 配置、战斗、结算、数据浏览、审计、构筑、环境入口全部铺开后，UI 工作量失控。

规避：

- UI v2 固定按 UI2-S0 到 UI2-S8 分步推进。
- 配置、战斗、结算分三个页面，不做单页全塞。
- 第一轮只要求最小 live loop 和 readiness，不要求全角色、全怪物、全构筑机制可用。
- 视觉打磨不能替代 live loop、readiness 和结算回溯。

风险红线：

- 没有完成当前子阶段验收，却用“整体 UI 还在做”模糊通过。
- 新增大功能入口但没有 readiness、gap 归属和后续阶段记录。

### 10.2 假可用感

风险：

- 页面看起来像游戏完整界面，实际底层未接入，用户误以为机制已经生效。

规避：

- 每个入口必须携带 `FeatureReadiness`。
- `draft_only`、`blocked`、`source_gap`、`admission_gap`、`mock_only` 必须视觉上区别于 `live`。
- 配置页进入战斗页前必须显示 setup validation summary。
- 结算页必须展示 blocked/gap/audit/replay 状态。

风险红线：

- 未接入功能显示成普通可用态。
- replay/source audit/settlement traceability 失败仍显示正常完成。

### 10.3 UI 污染规则

风险：

- 为了让按钮亮、页面顺滑或 demo 好看，在 UI/API/core 中补默认值、硬编码、伪来源或 fallback。

规避：

- UI 只展示 core/API 返回的 action choices、target choices、blocked reason 和 transition。
- UI 不能自行计算技能可用性、目标范围、伤害、状态、战技点、能量、行动条、资源消耗/生成或装备效果。
- UI/API 不能因为某条游戏“常见规则”看起来成立，就绕过 runtime 推导结果；所有例外都由 core admission 和 settlement 负责。
- API 可以做 view model 适配，但不能伪造 runtime 结果。
- 任何 UI 需求要求 core 新增字段时，必须先审来源、归属和通用性。

风险红线：

- UI 根据名称、位置、显示文本或列表顺序 fallback 目标。
- UI 自己让按钮亮起/禁用，或自己补战技点、能量、状态、行动条变化。
- UI 静默修正非法 command。
- core 为 UI 增加无来源字段、默认目标、默认动作或角色/怪物特判。

### 10.4 契约过早固化

风险：

- UI view model 过早绑定当前临时 report 或尚未稳定的 core 字段，后续为了兼容 UI 牺牲内核演进。

规避：

- UI view model 是适配层，不是 core 契约本身。
- 前端不直接依赖当前 raw report 深层字段。
- view model 必须带 schema version，允许在阶段边界做 breaking change。
- core / IR / RuleBook / runtime 不为 UI 兼容债保留旧结构。

风险红线：

- 把临时 report 字段当长期 UI API。
- 为了保持 UI 旧字段不变而污染内核模型。
- 需求拿不准时继续实现，而不是暂停询问用户。

### 10.5 Mock 变成事实来源

风险：

- mock 数据从视觉草稿滑入 scenario、route、expected result 或底层规则补全。

规避：

- mock/live 必须有明确模式和来源标记。
- mock only 不能保存进正式 scenario，不能导出 route，不能参与 live run。
- UI2-S8 必须验证 mock only 不进入正式 scenario/route。

风险红线：

- mock 数据无标记。
- mock 截图替代 live loop 验收。
- mock 数值作为 expected result 或规则依据。

### 10.6 验证成本上升

风险：

- UI 引入前端构建、端到端、截图、后端 API 验证，导致每次都跑重验证。

规避：

- UI 验证分层：类型检查、构建、最小 live loop、必要 DOM smoke。
- 默认不触发全量 TBGD 大产物输出。
- 只在 UI2-S8、结构大改或用户要求时跑完整 UI 验收。

风险红线：

- UI 验证脚本并行构建多个完整 RuleBook。
- 为了 UI 小改默认跑全量高负载验证。

### 10.7 信息密度失控

风险：

- 配置、战斗、结算、审计、缺口全部展示后，页面拥挤到无法使用。

规避：

- 三页面分离：配置页只处理开战前，战斗页只处理操作，结算页只处理回顾和回溯。
- 复杂信息通过详情抽屉、分组、筛选、折叠和 step drilldown 展示。
- 核心操作不能依赖打开 JSON 编辑器。

风险红线：

- 一个页面塞满配置、战斗和结算。
- 关键文本、按钮、状态 badge 重叠或难以定位。

### 10.8 开发优先级偏移

风险：

- 花太多时间做视觉和交互动效，拖慢 P4、状态、数据卡、目标系统等底层主线。

规避：

- UI2 的第一验收目标是契约、readiness、live loop 和结算回溯，不是全量美化。
- 视觉打磨放在 UI2-S7，必须在关键契约和 live loop 之后。
- UI 发现底层缺口时记录为后续 core/backlog，不在 UI 里硬补。

风险红线：

- 只做漂亮界面但没有 live loop。
- 因 UI 演示压力在 core 里补临时规则。

## 11. Checklist

- [ ] UI2-S0 范围定界和旧 UI 冻结完成。
- [ ] UI2-S1 技术骨架和页面路由完成。
- [ ] UI2-S2 View Model 和 readiness 契约完成。
- [ ] UI2-S3 配置页第一版完成。
- [ ] UI2-S4 战斗页第一版 live loop 完成。
- [ ] UI2-S5 结算页和回溯完成。
- [ ] UI2-S6 数据和缺口浏览完成。
- [ ] UI2-S7 视觉和交互打磨完成。
- [ ] UI2-S8 验收、报告和交接完成。
