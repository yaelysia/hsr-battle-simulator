# P5 公式 / 动态值 / 参数绑定通用准入分步计划

本文档是 P5 的执行计划，面向一个没有前文上下文的新执行线程，也面向长时间自动推进的 goal 模式。

P5 的核心任务是把 P4 暴露出来的公式、参数、动态值、自定义值、运行时上下文绑定缺口，收敛成一套通用、可审计、可阻断、可复用的底座。P5 不是全角色卡、全怪物卡、全光锥、全遗器或全关卡机制制作阶段；它是让这些后续数据卡能稳定执行的数值绑定基础设施阶段。

## 使用方式

第 19 节是 P5 唯一可打标 checklist。第 6.1 节只是阶段执行卡模板；第 7 到第 17 节是各阶段的目标、边界和验收参考，不是允许执行线程自行打勾的并行清单。

执行线程只能顺序执行一个 P5-Sx 阶段。每个阶段开始前必须先提交“阶段执行卡”，等待规划 / 验收线程确认后才能改文件。执行卡必须具体到可执行动作，不能复述本文档条款。

执行线程最多只能提交 `ready_for_review`，不能自称 `done`，不能修改第 19 节 checklist，不能把 `[ ]` 改成 `[x]`。阶段完成标记只能由验收线程在复核代码、验证输出、矩阵/summary、source/audit evidence 后更新。

`ok=true` 不是完成证明。报告也不是完成证据本身，只能作为证据索引。验收时必须解释验证实际检查了什么、没检查什么、predicate 是否过宽、是否把 gap 用 executable 正例覆盖。

资源控制是限制峰值，不是跳过必要验证。P5 会触达 lowering、RuleBook、damage、resource、status、summon 和 action execution 的共享路径，必要长验证必须串行、低优先级、输出到 `/tmp` 运行；禁止并行重验证、默认写大产物或跑无关全量。

## 0. 背景和当前事实

P1 已完成最小战斗纵切，P2 已完成状态系统底座，P3 已完成召唤物 / servant 底座，P4 已完成角色卡 / 怪物卡数据卡扩面底座。当前 v8 的事实来源仍固定为：

```text
turnbasedgamedata-main -> TBGD compiler/lowering -> Canonical IR / data-card IR -> RuleBook -> Combat Core
```

P4 聚合验收通过，当前数据卡扩面底座闭环成立：

- `p4_combatant_data_card_substrate_complete=true`
- `p4_all_executable_complete=false`
- 不存在 `implementation_missing`、`lowering_gap`、`validation_gap` 或 `unclassified`
- 保留 gap 只允许是已归因的 `admission_gap` / `source_gap_blocked`

P4 暴露的最大未完成域集中在公式和动态值：

- 技能参数、伤害倍率、韧性削减、资源消耗 / 回复、治疗 / 护盾 / 生命变化等数值来源已经能被发现，但很多还不能稳定绑定到执行上下文。
- 角色行迹、星魂、强化技能、开局监听、状态回调、怪物技能、怪物被动、召唤怪参数都存在大量动态值读取和自定义值读取。
- 召唤怪、servant、状态监听和部分怪物技能经常需要从 owner、summoner、actor、target、modifier、event payload 或 combatant profile 中读取数值。
- 当前不能为了让样例跑通而默认 0、默认 1、默认技能等级、默认目标、默认 owner、默认 profile 或按 hash/name 猜测含义。

P5 的价值在于：先把“数值从哪里来、能否绑定、缺什么上下文、失败后如何 blocked”做成通用底座，再去批量做角色卡 / 怪物卡 / 装备 / 关卡，返工会少很多。

## 1. P5 总目标

P5 完成后，v8 应具备以下能力：

- 用一个通用 value binding / formula binding 体系表达和执行技能参数、动态值、自定义值、按等级缩放值、按上下文读取值。
- 角色、怪物、servant、召唤怪、状态、资源、伤害、韧性、治疗、护盾、生命变化都能复用同一套绑定入口。
- 每个可执行数值都能追溯到 Canonical IR / data-card IR，再追溯到真实 TBGD 来源。
- 每个绑定失败都要给出结构化 blocked reason，并保持 state unchanged 或 process-only，不产生假 mutation。
- P4 中 formula / dynamic / custom value 相关 admission gap 应被 P5 聚合继承并逐步收敛；不能被宽域 executable 正例覆盖。

P5 不要求一次完成所有复杂公式和所有动态读取模式。P5 要完成的是通用准入框架和一组真实来源正例，让后续角色 / 怪物 / 装备 / 关卡扩面能在同一底座上继续补。

## 2. P5 不做什么

P5 明确不做：

- 不批量解释全角色卡。
- 不批量解释全怪物卡。
- 不实现光锥、遗器、套装完整机制。
- 不实现关卡环境、波次系统和特殊玩法完整机制。
- 不实现外部推演器。
- 不让 UI、scenario、route、推演器自行计算公式、目标、资源或技能可用性。
- 不把技能文本、TextMap、观测伤害、旧 v7 输出或 model pack 当作 runtime 规则来源。
- 不为当前数据库没有真实来源的机制构造 synthetic executable 正例。

## 3. 关键设计约束

- runtime 只读 Canonical IR / data-card IR / RuleBook，不直接读取 raw TBGD schema。
- lowering 可以读取 raw TBGD，但必须诚实投影来源；不能为了 runtime 方便制造不存在的规则事实。
- value binding 不能靠固定角色名、怪物名、技能 ID、文件名、hash 或观测答案运转。
- hash / custom value / dynamic value 只能在有结构化来源和绑定上下文时执行；无法绑定时必须 blocked。
- 缺 actor、target、owner、summoner、modifier instance、event payload、action definition、skill level、profile、resource source 时，不能 fallback 到默认值。
- 可执行正例必须至少抽样验证 source audit / replay / settlement traceability；blocked 负例必须证明 state unchanged 或 process-only。
- P5 新增验证脚本默认只写 summary、matrix、抽样 case 和必要审计记录；禁止默认写完整 Canonical IR、完整 RuleBook、完整 transition dump 或全量 TBGD dump。

## 4. 术语口径

- `formula binding`：把技能参数、等级缩放、伤害/韧性/资源/治疗等数值来源绑定到 IR 和 runtime consumer 的关系。
- `dynamic value`：需要在运行时根据上下文读取或计算的值，例如按 actor/target/profile/status/event payload/owner/summoner 变化的值。
- `custom value`：TBGD 中配置的自定义数值块或哈希键，只有能找到真实定义和读取语义时才能执行。
- `value context`：一次数值求值允许读取的上下文集合，例如 actor、target、action、hit、status、modifier、summon intent、event payload、combatant profile。
- `bound`：来源和上下文都足够，能求出数值，并可审计。
- `unbound`：来源存在但上下文或语义不足，必须 blocked。

## 5. P5 阶段总览

```text
P5-S0  公式 / 动态值 / 自定义值来源总账本与 P4 gap 继承
P5-S1  ValueBindingIR / RuleBook / runtime consumer 契约审计
P5-S2  静态参数与等级缩放绑定准入
P5-S3  动态值 / 自定义值定义与读取位点投影
P5-S4  通用 ValueContext / ValueResolver admission
P5-S5  伤害、韧性、治疗、护盾、生命变化 consumer 接入
P5-S6  资源、状态数值、callback queue 数值 consumer 接入
P5-S7  怪物 custom value 与召唤怪参数绑定回收
P5-S8  角色行迹 / 星魂 / 强化形态数值绑定回收
P5-S9  负例、source audit、replay、旧验证迁移
P5-S10 P5 聚合验收、报告、交接和后续 backlog
```

### 6.1 阶段执行协议

阶段状态只允许五种：

- `not_started`：未开始。
- `in_progress`：当前唯一正在执行的阶段。
- `ready_for_review`：执行线程认为本阶段已可验收，但尚未由验收线程确认。
- `blocked`：本阶段因缺依赖、缺接口或方向不明无法继续，必须写明 blocker 和下一步归属。
- `done`：验收线程确认本阶段所有完成项均可打勾，且不触发本阶段红线。

每个 P5-Sx 阶段开始前，执行线程必须先提交阶段执行卡，并等待确认后再改文件：

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

阶段执行卡必须写成执行设计，不能复述本文档原文。比如 P5-S3 不能只说“投影动态值”，必须说明 raw 层扫哪些结构化入口、IR 层新增或复用哪些容器、RuleBook 层查哪些 accessor、哪些读取位点可执行、哪些读取位点必须 blocked、输出哪些 summary/matrix。

执行线程完成实现后，只能提交 `ready_for_review` 汇报，内容包括：

- 实际改动文件。
- 实际新增 / 修改的函数、脚本、报告。
- 实际运行命令和输出路径。
- 每个完成项对应的 evidence。
- 未完成项、gap、blocked、deferred。
- 验证盲区和没有运行的验证。

验收线程复核通过后，才允许更新第 19 节 checklist。任何阶段未 `done` 前，不允许开始下一个阶段的实现。P5-S10 聚合入口只能在 S0-S9 均已 `done` 后实现和运行；不能提前写聚合脚本来替代分步工作。

## 7. P5-S0 公式 / 动态值 / 自定义值来源总账本与 P4 gap 继承

### 目标

建立 P5 总账本。执行线程在改 runtime 或 lowering 前，必须知道当前数据库、Canonical IR、RuleBook、P4 聚合中哪些来源属于公式、技能参数、动态值、自定义值、资源数值、状态数值、召唤参数和 runtime consumer。

### 本阶段只做

- 读取当前 P4 聚合矩阵，继承 formula / dynamic / custom value 相关 gap。
- 建立 P5 source-family matrix，覆盖角色技能、怪物技能、servant 技能、召唤怪 intent、状态 callback、资源规则、伤害/韧性/治疗/护盾/生命变化 consumer。
- 区分 `executable`、`admission_gap`、`source_gap_blocked`、`out_of_scope`、`boundary_only`。
- 输出轻量 summary、matrix、sample source trace 和 gap attribution。

### 本阶段不做

- 不改 runtime 求值。
- 不新增公式解释器。
- 不把 P4 gap 直接清零。
- 不构造 synthetic positive case。

### 阶段验收参考

- 每个 P5 source family 都有 raw / IR / RuleBook / consumer 计数和分类。
- P4 formula/dynamic/custom gap 全部被继承到 P5 矩阵，不能丢失。
- `unclassified=0`。
- `implementation_missing/lowering_gap/validation_gap` 如存在必须明确记录，不能被 admission gap 覆盖。
- 输出不包含完整 Canonical IR 或全量 TBGD dump。

### 阶段红线

- 只统计技能 ParamList，不统计 dynamic/custom/hash 读取。
- 只统计角色，不统计怪物、servant、召唤怪和状态 callback。
- 把一个 executable 公式正例当成整个 source family 完成。
- 把 P4 gap 重新命名后丢失。

## 8. P5-S1 ValueBindingIR / RuleBook / runtime consumer 契约审计

### 目标

复核当前 IR、RuleBook 和 runtime consumer 是否具备承载通用数值绑定的稳定契约，并明确哪些字段需要补齐。

### 本阶段只做

- 审计已有 `SkillFormulaBindingIR`、damage/toughness emission、resource rule、status numeric、summon intent、data-card mechanism slot 等容器。
- 审计 RuleBook 是否能按 binding id、action id、effect/task id、consumer id、data-card id、source trace 查询。
- 审计 runtime consumer 当前从哪里取数，哪些路径仍在直接读字段或默认值。
- 设计或补齐最小 ValueBinding contract，但只做契约层，不做大规模求值。

### 本阶段不做

- 不实现复杂动态求值。
- 不批量改所有 damage/resource/status consumer。
- 不引入 UI 或推演器输入。

### 阶段验收参考

- 形成 contract matrix：每类 consumer 是否能找到 source-backed binding。
- 缺 binding、缺 query、缺 source trace 的项有明确 gap attribution。
- RuleBook 新增 accessor 如有，必须只读 IR，不读 raw TBGD。
- runtime consumer 不能因为审计而新增默认值 fallback。

### 阶段红线

- 把字段存在当成可执行绑定。
- 为了验证方便新增固定角色/技能查询接口。
- 把缺 binding 的 consumer 标成 executable。

## 9. P5-S2 静态参数与等级缩放绑定准入

### 目标

先把最稳定的一类数值打通：来源明确、只依赖技能等级或配置等级的静态参数与等级缩放值。

### 本阶段只做

- 支持从真实 IR binding 读取静态参数。
- 支持按 action level / skill level / data-card level 选择对应数值。
- 将一组真实 damage/toughness/resource 正例接到统一静态参数 resolver。
- 缺等级、缺参数索引、缺 binding、越界时 blocked。

### 本阶段不做

- 不处理 hash/custom value。
- 不处理需要 actor/target/event payload 的动态值。
- 不处理装备/遗器/关卡加成。

### 阶段验收参考

- 静态参数正例来自结构化 IR binding，不靠固定技能名。
- 至少覆盖角色技能和怪物技能各一类真实来源。
- 越界、缺等级、缺 binding 负例 state unchanged。
- source audit / replay 可从 mutation 或 settlement 反查到 binding source。

### 阶段红线

- 缺参数时默认 0 或 1。
- 技能等级缺失时默认满级或 1 级。
- 用观测伤害倒推倍率。

## 10. P5-S3 动态值 / 自定义值定义与读取位点投影

### 目标

把 dynamic/custom/hash 类来源诚实投影到 IR 或 data-card 绑定层，先让“定义在哪里、读取在哪里、能否绑定”可审计。

### 本阶段只做

- 扫描并投影动态值定义、custom value 定义、hash-like key、read info、读取位点。
- 建立 definition -> read site -> consumer 的 source trace。
- 对无法确定语义或缺上下文的读取位点标记为 blocked / admission gap。
- 输出 dynamic/custom binding matrix。

### 本阶段不做

- 不对所有 hash 猜含义。
- 不把 hash key 映射成手写名字表。
- 不执行缺上下文的读取。

### 阶段验收参考

- 每个可见 read site 都有 source trace 或 blocked reason。
- 定义存在但读取上下文不足时是 admission gap，不是 executable。
- 当前没有真实 definition 的路径必须 source-gap/boundary，不合成定义。
- 负例证明缺 definition / 缺 read payload / 错 key 不会 fallback。

### 阶段红线

- 用 hash 字符串、文件名、技能名硬编码含义。
- 缺 definition 时读取默认值。
- 把 discovery-only source 当成 runtime mutation 来源。

## 11. P5-S4 通用 ValueContext / ValueResolver admission

### 目标

建立 runtime 通用求值入口，让数值求值显式声明能读取哪些上下文，不能读取时统一 blocked。

### 本阶段只做

- 设计并实现 ValueContext 的最小字段：actor、target、owner、summoner、action、hit、status/modifier、event payload、combatant profile、data-card source。
- 实现 ValueResolver admission：只执行已支持的 binding kind，未知 binding kind blocked。
- 输出 resolution ledger：成功值、失败原因、source trace、context keys。
- 将 S2 的静态参数路径迁移到 ValueResolver。

### 本阶段不做

- 不一次接入所有 consumer。
- 不补目标系统缺口。
- 不补波次/关卡上下文。

### 阶段验收参考

- resolver 成功正例有 value、source trace、context trace。
- 缺 actor/target/owner/event payload/profile 的负例 blocked 且 state unchanged。
- unknown binding kind 不能跳过后继续 executable。
- resolution ledger 可被 settlement/source audit 引用。

### 阶段红线

- resolver 内部直接读 raw TBGD。
- resolver 缺上下文时猜默认值。
- consumer 绕过 resolver 自己解释同类 binding。

## 12. P5-S5 伤害、韧性、治疗、护盾、生命变化 consumer 接入

### 目标

把最核心的数值 consumer 接入 ValueResolver，并保留现有 P1/P2 行为不回退。

### 本阶段只做

- 接入 direct damage、DoT/status damage、break/super-break 之外的 formula-bound damage 正例。
- 接入 toughness emission 的 source-backed formula binding。
- 接入 heal / shield / hp loss 当前真实来源中的可执行样例。
- 缺 binding 或 resolver blocked 时不产生对应 mutation。

### 本阶段不做

- 不重写完整伤害公式系统。
- 不做装备/遗器/关卡乘区。
- 不处理所有角色专属伤害特例。

### 阶段验收参考

- 每类接入 consumer 至少有一条真实来源正例，除非当前 P5-S0 明确无来源。
- mutation -> settlement -> binding -> IR -> TBGD source 可追踪。
- blocked 正例不得产生 damage/heal/shield/hp mutation。
- P1/P2 damage/status 直接回归通过或有明确旧验证口径迁移说明。

### 阶段红线

- 用固定倍率替代 binding。
- 旧 damage 正例通过但新 source audit 丢失。
- blocked formula 仍产生 mutation。

## 13. P5-S6 资源、状态数值、callback queue 数值 consumer 接入

### 目标

把资源变化、状态层数/持续时间/数值、callback queue 中依赖数值的路径接入 ValueResolver。

### 本阶段只做

- 接入 skill point / energy / custom resource 的 source-backed formula binding 正例。
- 接入状态数值字段，例如层数变化、持续时间、DoT 参数、状态提供的数值修正。
- 接入 callback queue 中需要数值判断或数值写入的可执行正例。
- 缺 event payload、缺 modifier instance、缺 status owner 时 blocked。

### 本阶段不做

- 不完整实现所有事件族。
- 不补波次系统。
- 不把状态文本解释放进 runtime。

### 阶段验收参考

- resource mutation 和 status mutation 都能追溯 value resolution。
- callback queue 的数值读取有 event/context source。
- 缺 payload 负例 state unchanged。
- P2 聚合通过或旧断言迁移有报告。

### 阶段红线

- 资源不足或资源公式缺失时仍允许动作。
- 状态层数/持续时间缺 binding 时默认刷新或默认 1。
- callback 缺 payload 时照常执行。

## 14. P5-S7 怪物 custom value 与召唤怪参数绑定回收

### 目标

优先回收 P4/P3 中与怪物 custom value、召唤怪 profile/card、summon intent 参数有关的 gap。

### 本阶段只做

- 将 MonsterConfig / MonsterTemplate / SummonMonsterIntent 中真实可绑定的参数接入 ValueResolver。
- 让召唤怪 level/profile/card source 能在有真实来源时绑定。
- 对仍缺 monster profile/card source 的 intent 保持 source_gap_blocked，并继承到 P5 聚合。
- 验证召唤怪不会因缺 profile/default level 而假生成。

### 本阶段不做

- 不批量实现全怪物技能。
- 不补完整波次/关卡 override。
- 不为缺 profile 的召唤怪手写数据卡。

### 阶段验收参考

- 至少一条 summon monster intent 参数绑定正例来自真实来源。
- P3 summon 聚合通过，且 inherited gap 没被隐藏。
- 缺 profile/card/level source 的召唤 intent 保持 blocked。
- source_gap_blocked 数量变化必须有解释：是被真实来源解决，还是重新分类。

### 阶段红线

- 给召唤怪默认怪物卡或默认等级。
- 把召唤者怪物卡复制给被召唤单位。
- 为通过 P3 回归删掉 inherited gap。

## 15. P5-S8 角色行迹 / 星魂 / 强化形态数值绑定回收

### 目标

回收 P4 中角色机制槽位、行迹、星魂、强化形态里因数值绑定不足造成的 admission gap。

### 本阶段只做

- 将真实可绑定的 trace/eidolon/skill-tree parameter 接入 ValueResolver。
- 选择结构化正例，不依赖固定角色名作为主路径；如使用希儿等样例，必须说明是 source-backed sample，不是硬编码规则。
- 对文本缩放依据、缺事件源、缺目标源、缺动态 binding 的项保留 gap。
- 迁移旧验证中“全部 blocked”之类过时断言。

### 本阶段不做

- 不全量完成所有角色卡。
- 不解释技能文本。
- 不补装备和遗器。

### 阶段验收参考

- 角色机制槽位的 executable / blocked 分类更精确。
- 至少一条 trace/eidolon 数值绑定正例通过 source audit / replay。
- 缺文本解释或缺事件源时 blocked，不产生 flag/buff/damage 假 mutation。
- P4 action/query 和 P2 status 回归通过或有明确迁移报告。

### 阶段红线

- 用角色名特判进入 core。
- 把技能文本解释放进 runtime。
- 缺绑定时仍应用 buff、flag 或额外伤害。

## 16. P5-S9 负例、source audit、replay、旧验证迁移

### 目标

统一收口 P5 新增求值路径的负例、安全边界、source audit、replay 和旧验证口径迁移。

### 本阶段只做

- 建立 P5 blocked/state-unchanged matrix。
- 建立 P5 value resolution source audit matrix。
- 建立 P5 replay matrix，确保 before + command + IR + RNG + mutations == after。
- 修正因 P5 新语义导致过时的旧验证断言，并在报告中说明。

### 本阶段不做

- 不新增业务机制。
- 不为了让旧验证绿而保留假执行路径。
- 不修改 P5-S10 聚合入口。

### 阶段验收参考

- 缺 binding、缺 context、缺 target、缺 owner、缺 event payload、未知 binding kind 均有负例。
- executable value mutation 至少抽样反查到 settlement、IR、TBGD source。
- 旧验证迁移必须说明旧断言为什么过期，新断言检查了什么。
- P1/P2/P3/P4 触达回归按范围通过。

### 阶段红线

- 只跑 P5 主验证，不看旧验证是否被破坏。
- 把旧验证失败直接豁免。
- 没有 source audit / replay 正例就标完成。

## 17. P5-S10 P5 聚合验收、报告、交接和后续 backlog

### 目标

在 S0-S9 均由验收线程确认后，实现 P5 聚合验证和最终报告，证明 P5 底座闭环通过，并诚实保留未完成 gap。

### 本阶段只做

- 新增 `validate_p5_formula_dynamic_param_binding` 或等价聚合入口。
- 聚合 S0-S9 子矩阵，继承所有 gap。
- 输出 P5 final summary、source matrix、mechanism matrix、allowed gap evidence、blocked samples、positive samples、source audit/replay samples。
- 更新 P5 checkpoint 报告和交接摘要。

### 本阶段不做

- 不在聚合层修实现。
- 不用聚合脚本替代分步验证。
- 不清空尚未解决的 admission/source gap。

### 阶段验收参考

- S0-S9 stage checks 全部通过。
- `implementation_missing/lowering_gap/validation_gap/unclassified` 为 0，或若非 0 则 P5 不能验收。
- 保留 gap 只允许是已归因、带 evidence 的 `admission_gap` / `source_gap_blocked`。
- `p5_formula_dynamic_param_binding_substrate_complete=true`。
- `p5_all_executable_complete=false` 可以成立，但必须解释剩余 gap。
- P1/P2/P3/P4 聚合回归按触达范围串行通过。

### 阶段红线

- 聚合脚本提前实现。
- 聚合主行显示 gap=0，但分步矩阵仍有内部 gap。
- 把 allowed gap 当成全正例完成。
- 报告只贴 `ok=true`，不解释验证范围和盲区。

## 18. 验证范围和资源预算

### 必跑最小集

每个子阶段至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

还必须运行本子阶段新增或修改的主验证脚本。若新增文件仍未跟踪，普通 `git diff --check` 不覆盖未跟踪文件，必须额外跑相关文件的行尾空白检查。

### 直接回归集

- 改 formula binding / ValueResolver：跑本阶段验证、P1-9、P2 聚合、P4 聚合。
- 改 damage / toughness / heal / shield / hp loss consumer：跑 P1-9、P2 聚合、相关 damage/status 验证。
- 改 resource consumer：跑 P1-9、P4 action/query 相关验证。
- 改 status numeric / callback queue：跑 P2 聚合、P4-S6/S9 相关验证。
- 改 summon intent / monster custom value：跑 P3 聚合、P4 聚合。
- 改 RuleBook / lowering schema：跑 P1-9、P2、P3、P4，以及本阶段聚合。

### P5-S10 阶段验收集

P5-S10 阶段验收至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_formula_dynamic_param_binding --output-dir /tmp/hsr_v8_p5_formula_dynamic_param_binding
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p2_status_system_complete --output-dir /tmp/hsr_v8_p2_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_p5_regression
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_combatant_data_card_expansion --output-dir /tmp/hsr_v8_p4_p5_regression
git diff --check
```

如果某个旧回归因为 P5 新语义失败，必须先判断：

- 新语义是否有真实来源、source audit、replay 和负例。
- 旧断言是否写死了过去未完成时期的 blocked 口径。
- 如果旧断言过期，修验证口径并在报告说明；不能把过期验证失败算作 P5 功能失败。
- 如果旧验证揭示真实退化，必须修实现，不能豁免。

### 资源预算

- P5 聚合是重验证，默认只在阶段验收或用户要求时运行。
- 所有需要 lowering / RuleBook / P1-P4 聚合的验证都串行运行。
- 验证输出默认写 `/tmp`。
- 新增验证脚本默认不写完整 IR、完整 RuleBook、全量 transition dump 或大体积 JSON。
- 需要大产物时必须加显式开关，默认关闭，并在阶段执行卡中说明。

## 19. Checklist

本 checklist 只由验收线程更新。执行线程完成某阶段后只能提交 `ready_for_review` 证据包，不能自行勾选。

- [x] P5-S0 公式 / 动态值 / 自定义值来源总账本与 P4 gap 继承完成。
- [x] P5-S1 ValueBindingIR / RuleBook / runtime consumer 契约审计完成。
- [x] P5-S2 静态参数与等级缩放绑定准入完成。
- [x] P5-S3 动态值 / 自定义值定义与读取位点投影完成。
- [x] P5-S4 通用 ValueContext / ValueResolver admission 完成。
- [x] P5-S5 伤害、韧性、治疗、护盾、生命变化 consumer 接入完成。
- [x] P5-S6 资源、状态数值、callback queue 数值 consumer 接入完成。
- [x] P5-S7 怪物 custom value 与召唤怪参数绑定回收完成。
- [x] P5-S8 角色行迹 / 星魂 / 强化形态数值绑定回收完成。
- [x] P5-S9 负例、source audit、replay、旧验证迁移完成。
- [x] P5-S10 P5 聚合验收、报告、交接和后续 backlog 完成。
