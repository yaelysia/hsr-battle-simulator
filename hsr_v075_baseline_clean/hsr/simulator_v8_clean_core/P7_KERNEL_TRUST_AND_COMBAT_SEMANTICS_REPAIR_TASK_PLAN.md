# P7 内核可信执行与战斗语义回正任务计划

本文档同时承担两项职责：记录 2026-07 内核深度复审确认的问题，并把这些问题拆成可由无前文上下文的新执行线程逐阶段完成的修复计划。

P7 不是推倒重写，也不是角色卡、怪物卡、装备或关卡的全量扩面。P1-P6 已经建立了有价值的 Canonical IR、数据卡边界、Mutation、BattleTransition、replay、source audit、状态、召唤物和公式底座，这些结构应当保留。P7 要解决的是：现有验证能够证明若干纵切“跑通”，但还不能证明内核在所有已准入路径上都给出了完整、准确、可供推演器信任的战斗结果。

复审发现的问题不是来自旧文档推测，而是来自当前实际代码、调用链和轻量复现。问题集中在五个方面：

- 一个动作即使只执行了一部分，仍可能产生状态变化并被包装成可继续使用的 transition。
- 动作所有权、目标数量、行动窗口和调度决策还没有形成严格的查询与提交闭环。
- 回合阶段、控制、行动条、队列、伤害、护盾、状态概率和随机分支仍存在影响战斗结果的语义错误。
- 审计信息与 raw 表达式仍在部分 runtime 路径中承担规则输入职责，P6 的边界防线没有覆盖到“行为读取”。
- 当前验证偏重样例通过、replay 自洽和来源链存在，缺少能直接抓住上述错误的通用不变量。

P7 完成后，后续角色卡 / 怪物卡扩面和外部推演器才能建立在可信状态转移上，避免把内容规模扩大到一个仍会静默产生错误结果的内核上。

## 使用方式

本文档只有第 30 节是唯一可打标 checklist。问题表、阶段说明、验收口径和验证矩阵都不是第二套执行清单。

执行线程必须严格按 `P7-S0` 到 `P7-S19` 的顺序工作，一次只允许执行一个阶段。后续阶段只能作为依赖背景，不允许提前实现、提前报告或混入当前阶段 evidence。

每个阶段开始前，执行线程必须先提交阶段执行卡，等待规划 / 验收线程确认后才允许修改文件。执行线程最多只能提交 `ready_for_review`，不能自称 `done`，不能修改第 30 节 checklist，也不能把已知问题改写成“后续再看”后自行通过。

验收线程必须阅读真实代码，检查结构化证据并运行本阶段最小验证。`ok=true`、compileall 通过、replay 自洽或报告声称完成，都不能单独作为通过依据。验收通过后，由验收线程勾选对应阶段并建立代码检查点；纯文档调整不要求单独提交检查点。

## 0. 前因后果

项目的最终目标不是播放预先写好的战斗脚本，而是让外部推演器像玩家一样：读取当前状态，查询合法动作和目标，选择一个动作及可控随机分支，然后获得与游戏规则一致的新状态。内核因此必须同时满足三件事：

1. 给出的选择必须确实合法，且提交同一个选择时不能被另一套规则拒绝。
2. 一旦声称动作结算成功，所有被选中的机制必须完整执行，不能一半成功、一半缺失。
3. 新状态必须由可验证的原子 Mutation 得到，来源、随机和结算记录都能独立复核，而不是只在同一套错误实现中 replay 成功。

P1-P6 更偏重建立结构、来源链和机制纵切。此次复审说明，这些阶段的验收结论仍然有效地证明了相应“底座存在”，但不能外推为“战斗语义已经完整准确”。P7 不重写历史结论，而是补上历史验收没有覆盖到的可信执行层。

外部攻略站、游戏机制资料和实机现象只可用于发现矛盾和辅助语义核对。最终可执行规则仍必须诚实归类为 TBGD 结构化来源、数据卡来源或显式版本化的引擎规则；不能把外部文字或观测数值伪装成 TBGD 来源。

## 1. P7 总目标

P7 完成后，系统应达到以下状态：

- 每个 transition 都有机器可读且不可误解的可信结果类别。只有完整结算的结果才能成为推演器的下一状态；被阻断和诊断性结果不得伪装成成功。
- 一个被选中的动作要么完整、原子地提交全部状态变化，要么保持状态不变并给出明确原因；不允许部分 mutation 泄漏。
- Mutation 的前置值和操作语义会被 reducer 强制校验，旧计划不能静默覆盖新状态。
- 查询接口给出的每个动作和目标，在同一决策状态下都能原样提交；未被查询接口给出的命令会被拒绝。
- 行动者、动作类型、使用窗口、资源门、目标关系、目标数量和实际打击范围均由结构化规则决定。
- 回合阶段、行动条、控制、队列和波次事件形成显式状态机，不再依赖调用顺序碰巧正确。
- direct、DoT、击破、超击破、生命流失、削韧和护盾通过职责明确的通用管线结算。
- 状态施加正确区分增益、减益、控制、免疫、效果抵抗和特定抵抗，省略概率不会被错误地再次进行效果抵抗判定。
- 每个独立随机决策都有唯一身份和可重放选择，连续段、多目标和同类事件不会共用一个模糊结果。
- 召唤物、servant、后场单位和波次单位通过真实运行时事件进入统一生命周期，而不是只在 BattleSetup 中可用。
- runtime 不从 `source_trace`、审计 evidence、raw `$type`、raw postfix 表达式或路径文字中提取规则。
- 推演器可以使用紧凑、稳定的状态键进行搜索，同时按需取得完整 transition 和审计证据。

## 2. P7 明确不做

P7 不承担以下目标：

- 不批量制作全角色、全怪物、全光锥、全遗器或全关卡。
- 不实现外部搜索 / 推演算法。
- 不重做 Web UI。
- 不以旧 v7、旧 model pack、技能文本、固定答案或实机观测值作为 runtime 规则输入。
- 不为了形成正例而伪造当前数据库不存在的机制来源。
- 不承诺 P3/P4/P5 所有 admission / source gap 在 P7 内完成内容扩面。
- 不保留会污染 v8 内核的旧接口兼容层。若阶段会影响当前工作区外的真实调用者，执行卡必须先提出兼容决策；工作区内调用者应在同一阶段原子迁移。
- 不用大规模重写替代逐项修复。只有证据表明现有边界无法承载正确语义时，才允许在执行卡中提出结构性替换。

## 3. 全局红线

- `exact`、`blocked`、`diagnostic/untrusted` 等具体命名可由实现选择，但三类语义必须机器可辨，不能只写在日志文字中。
- 只有完整执行所选机制图、通过 Mutation 前置校验且 after state 可复核的 transition 才能被视为可信成功。
- 被阻断、unsupported、partial、audit-only、discovered-only 或诊断性路径最终都必须 state unchanged；中间计划可以存在，但不得向外提交部分新状态。
- 是否完整只针对本次实际选中的执行分支。条件为假、没有进入的分支不应无故阻断当前动作；被选中或被触发的 unsupported 分支则必须阻断整次原子提交。
- 动作查询、目标查询和动作提交必须共享同一套结构化判定，不能各自复制一份近似规则。
- 敌方 AI 不进入内核。真实来源规定的强制脚本或阶段约束可以限制合法动作集合，但最终选择和提交仍由外部控制器完成。
- 审计来源只回答“规则来自哪里”，不能回答“规则应该怎么算”。任何从审计字段、路径文字或 evidence payload 反查倍率、目标、状态、公式或动作的 runtime 行为都不允许保留。
- 缺少结构化规则时必须 blocked/state unchanged。不得用默认目标、默认倍率、默认可行动、默认可选中或默认召唤属性继续执行。
- 不允许用固定角色名、怪物名、技能名、固定 ID、固定文件、固定 hash 或固定数值答案驱动修复和验证。
- 每个修复阶段必须同时有正向不变量和负向不变量。只证明当前正例能跑，不能证明错误输入不会被接受。
- 已知缺陷不能用 `source_gap_blocked` 消失。只有 raw TBGD 真实缺源才可归类为 source gap；lowering、admission、runtime 或验证缺失必须进入相应修复类别。
- 新验证默认轻量、抽样、结构化，不写完整 Canonical IR、完整 RuleBook、全量 transition dump 或全数据库派生产物。

## 4. 问题分级和判定口径

本问题记录使用以下分类：

- `correctness_blocker`：会让可执行战斗得到错误状态，或让推演器无法可靠操作，P7-DONE 前必须修复。
- `architecture_debt`：当前路径可能在有限样例中工作，但职责或来源边界会阻碍后续扩展，P7-DONE 前必须回正。
- `integration_missing`：底座存在但未接入真实战斗生命周期，P7-DONE 前必须至少完成通用运行时闭环。
- `scalability_blocker`：不一定改变单次结果，但会让推演器大规模枚举不可用，P7-DONE 前必须建立可用接口和预算。
- `validation_gap`：现有验证无法抓住已确认错误，必须用通用不变量补齐。

问题状态只允许使用：`confirmed_open`、`ready_for_review`、`accepted_fixed`、`not_a_defect_with_evidence`。执行线程不能直接把问题标为后两种。若复核证明某项不是缺陷，必须给出当前代码语义、真实来源和反例验证，由验收线程决定是否关闭。

## 5. 当前问题总账

| 编号 | 分类 | 当前实际问题 | 直接后果 | 当前代码证据 | 修复阶段 |
|---|---|---|---|---|---|
| P7-I01 | correctness_blocker | transition 没有权威完整性门；部分或未实现路径仍可能产生 mutation 并被当成可继续使用的结果 | 推演器会把不完整战斗状态当成真实后继 | `core/action_plan.py`、`core/executor.py`、`core/transition_contract.py` | S1、S3 |
| P7-I02 | correctness_blocker | 动作查询没有严格约束动作所有者、动作角色和使用窗口，角色技能列表中的多种入口可能都暴露为普通行动 | 被动、秘技、终结技等可能在错误窗口被提交 | `systems/action_availability.py`、`core/executor.py` | S6 |
| P7-I03 | correctness_blocker | 查询动作和 scheduler 提交路径都可能推进到下一回合，形成重复 begin-turn | 查询后提交同一选择时，实际行动者或时间线发生变化 | `systems/action_availability.py`、`systems/scheduler.py`、`systems/timeline.py` | S8 |
| P7-I04 | architecture_debt | 敌方固定序列在 scheduler 内部直接选择动作，强制规则和 AI 选择没有分开 | 外部推演器无法统一控制敌我动作 | `systems/enemy_action.py`、`systems/scheduler.py` | S8 |
| P7-I05 | correctness_blocker | 单体目标策略可接受多个目标，目标敌我关系还会根据效果类型猜测 | 单体、扩散、群攻、弹射的选择范围和实际打击范围会混淆 | `systems/target.py`、`systems/action_preflight.py`；轻量复现中单体策略接受了两个目标 | S7 |
| P7-I06 | correctness_blocker | 回合开始、行动前、行动后、回合结束等阶段没有统一状态机；DoT 和状态生命周期主要在 actor 行动后结算，部分事件只记录不派发 | DoT、持续时间、回调和行动窗口顺序可能错误 | `systems/scheduler.py` | S9 |
| P7-I07 | correctness_blocker | 控制状态只阻止动作，没有稳定地消费 / 跳过受控回合和推进生命周期 | 同一受控单位可能反复成为当前行动者并卡死 | `systems/status.py`、`systems/scheduler.py` | S10 |
| P7-I08 | correctness_blocker | 速度变化没有按剩余行动值重算，平局用 unit id 决定，当前行动保护不足 | 速度增减、拉条、推条和同值顺序不符合结构化战斗规则 | `systems/timeline.py` | S10 |
| P7-I09 | correctness_blocker | 护盾被压缩成可累加资源，但伤害系统不消费护盾；不同护盾规则也没有实例级表达 | 有护盾单位仍直接损失生命，护盾 settlement 不可信 | `systems/effect.py`、`systems/damage.py`；轻量复现中 50 护盾未吸收 30 点伤害 | S13 |
| P7-I10 | correctness_blocker | DoT、击破和超击破把中间 amount 近似当成最终伤害，未稳定经过各自适用的防御、抗性、易伤和减伤阶段 | 伤害数值会系统性偏离游戏 | `systems/damage.py`、`systems/dot_formula.py`、`systems/break_system.py`、`systems/super_break.py` | S12 |
| P7-I11 | correctness_blocker | 部分伤害 / 削韧计算在 before-event 派发前完成，监听器改变状态后仍应用旧计划 | 同一事件窗口中的增减益无法影响应受影响的结算 | `core/executor.py` | S12 |
| P7-I12 | correctness_blocker | reducer 不核对 Mutation 声明的 before 值，也没有严格执行 op 语义 | 过时计划可静默覆盖新状态，replay 仍会自洽 | `core/reducer.py`；轻量复现中错误 before 值仍被接受 | S2 |
| P7-I13 | correctness_blocker | 状态施加把省略概率的来源先标为必定，又继续经过效果抵抗；增益和减益共用过宽概率路径；控制抵抗与普通效果抵抗没有正确分层 | 增益、必定状态、普通减益和控制的命中率错误 | `systems/status.py`；轻量复现中省略概率仍被效果抵抗降低 | S14 |
| P7-I14 | correctness_blocker | 某些 unsupported duration / property 会形成 active partial 状态并产生 mutation | 未完整理解的状态仍会污染战斗状态 | `systems/status.py` | S3、S14 |
| P7-I15 | correctness_blocker | 同一动作的多段、同目标暴击等随机事件身份可能碰撞，随机状态没有明确推进，宽泛 fallback 可替代精确选择 | 独立随机分支被错误绑定，推演结果不可枚举或不可重放 | `systems/damage_formula.py`、`systems/rng.py` | S15 |
| P7-I16 | architecture_debt | 部分 runtime 仍从 source/evidence/source_trace 中提取可执行信息 | 审计结构一变就改变战斗规则，来源边界名存实亡 | `systems/status_callbacks.py`、`systems/ability.py`、`core/executor.py`、`systems/scheduler.py`、`systems/dot_formula.py`、`rules/rulebook.py` | S4 |
| P7-I17 | architecture_debt | Canonical IR 仍夹带 raw target、raw condition 和 postfix 数值子语言，由 runtime 临时解析 | lowering 与 runtime 职责不清，未知表达式容易默认执行或各系统解释不一致 | `systems/target.py`、`rules/evaluator.py`、TBGD lowering 数值摘要路径 | S5 |
| P7-I18 | architecture_debt | 状态 definition 选择、持续时间模式和 dynamic binding 仍有按路径标记或“取第一个匹配项”的歧义 | 数据规模扩大后会绑定到错误状态或错误参数 | `systems/status.py`、`rules/evaluator.py` | S4、S5、S14 |
| P7-I19 | correctness_blocker | 队列头项 actor / target 无效或执行被阻断时，条目可能不出队 | 后续合法队列项永久无法执行 | `systems/scheduler.py`、`systems/queue.py` | S11 |
| P7-I20 | integration_missing | 召唤系统主要由 BattleSetup 调用，战斗中的 task/effect/callback 未稳定接入 spawn；后场和 targetable 标记没有贯穿生命周期 | 召唤物底座存在，但真实技能召唤和不可选中单位仍不可靠 | `scenarios/build_state.py`、`systems/summon.py`、`systems/unit_lifecycle.py` | S16 |
| P7-I21 | integration_missing | 波次生成与清理存在，但 wave start / monster enter 等事件没有统一走事件派发，相关监听仍缺运行时闭环 | 开波被动、入场状态和波次事件无法按来源触发 | `systems/wave.py`、`systems/scheduler.py` | S9、S17 |
| P7-I22 | architecture_debt | 行动值基数、击杀能量等基础常量以 engine convention 执行，但缺少统一、版本化、可审计的规则来源 | 基础规则难以核对和按版本演进 | TBGD lowering 的 timeline/resource convention、`systems/resource.py` | S4 |
| P7-I23 | scalability_blocker | BattleState、snapshot 和 transition 重复携带大量静态来源与状态明细 | 外部推演器扩展搜索树时内存、复制和哈希成本过高 | `core/model.py` 及状态详情 / provenance 结构 | S18 |
| P7-I24 | validation_gap | 静态检查偏向 token 和 import；缺少动作所有权、目标数量、护盾吸收、控制推进、DoT 顺序、独立 RNG、before 冲突和 partial 原子性的通用验证 | 现有聚合全绿仍可能漏掉基础语义错误 | `tools/static_checks.py` 及现有阶段聚合 | S0、S19 |

总账中的文件位置是复审入口，不是要求执行线程按行号机械修改。每阶段执行卡必须重新读取相关调用链，确认问题仍存在、影响范围和最小正确边界。

## 6. 问题与阶段的完整映射

| 阶段 | 唯一核心目标 | 必须关闭的问题 |
|---|---|---|
| P7-S0 | 固化问题基线、复现不变量和验收矩阵 | P7-I24 的基线部分；确认 I01-I23 不遗漏 |
| P7-S1 | 建立 transition 可信结果契约 | P7-I01 的结果分类部分 |
| P7-S2 | 强制 Mutation 前置条件和操作语义 | P7-I12 |
| P7-S3 | 让所选执行图原子提交 | P7-I01 的部分执行、P7-I14 的 partial mutation |
| P7-S4 | 分离规则输入与审计来源 | P7-I16、P7-I18 的路径推断、P7-I22 |
| P7-S5 | 将可执行表达式完整 lower 为类型化 IR | P7-I17、P7-I18 的歧义 linking |
| P7-S6 | 建立动作所有权、角色和窗口契约 | P7-I02 |
| P7-S7 | 建立目标选择与实际作用范围契约 | P7-I05 |
| P7-S8 | 建立查询、决策和提交闭环 | P7-I03、P7-I04 |
| P7-S9 | 建立显式回合 / 事件阶段机 | P7-I06、P7-I21 的通用事件窗口 |
| P7-S10 | 回正行动条和控制回合语义 | P7-I07、P7-I08 |
| P7-S11 | 建立队列条目终态和前进保证 | P7-I19 |
| P7-S12 | 建立统一伤害与削韧结算管线 | P7-I10、P7-I11 |
| P7-S13 | 建立一等护盾与 HP 路由 | P7-I09 |
| P7-S14 | 回正状态施加、抵抗和完整准入 | P7-I13、P7-I14、P7-I18 的状态语义 |
| P7-S15 | 建立独立随机决策身份和重放 | P7-I15 |
| P7-S16 | 接通战斗中召唤物生命周期 | P7-I20 |
| P7-S17 | 接通波次生命周期和事件源 | P7-I21 的波次集成 |
| P7-S18 | 建立推演器可用的紧凑状态视图 | P7-I23 |
| P7-S19 | 建立最终不变量聚合和关闭总账 | P7-I24 的最终部分，复核 I01-I23 |

任何问题如果在归属阶段未关闭，必须保留在最终矩阵中并阻断 `P7-DONE`。不得把它悄悄移动到“后续角色卡扩面”或以某个旧聚合仍为绿色为理由消除。

## 7. 阶段执行卡规格

执行线程开始任一阶段前，必须提交包含以下内容的执行卡：

```text
阶段与对应问题编号：

当前事实：
  - 逐条说明问题当前如何发生。
  - 给出入口、关键调用链和当前可复现结果。
  - 区分确认缺陷、来源缺口和仍需判定的问题。

详细阶段目标：
  - 完成后系统对正常输入应如何工作。
  - 完成后系统对缺失、错误、过期或 unsupported 输入应如何工作。
  - 本阶段必须消除哪些旧职责或旧行为。

目标与证据映射：
  - 每条目标由哪处代码结构证明。
  - 由哪个正例、负例或不变量证明。
  - summary / matrix 中用什么机器可读字段表达。

本阶段只做：
本阶段不做：
拟改文件和符号：
需要迁移的工作区内调用者：
可能影响的接口及是否需要用户决定兼容：

验收标准：
  - 做到什么才允许通过。
  - 出现什么必须拒绝通过。
  - 不能只写“验证通过”或“回归无异常”。

gap / blocked / deferred 口径：
  - raw source gap、lowering gap、admission gap、implementation missing 分开记录。
  - 已确认内核缺陷不得归为 source gap。

验证命令：
  - 本阶段必跑最小集及每条命令证明的目标。
  - 直接回归集及触发原因。
  - 明确不跑的聚合和理由。
  - 资源预算、输出规模和限峰值措施。

ready_for_review evidence：
  - 代码 diff 摘要。
  - 目标到证据映射。
  - 结构化验证摘要与关键反例。
  - 尚未关闭的问题和真实 blocker。
```

执行卡不能只复述阶段标题。若没有写清“系统完成后会变成什么样”和“哪种错误结果会阻断验收”，规划 / 验收线程应直接退回。

## 8. P7-S0 问题基线与不变量矩阵

### 阶段目标

在不修改 runtime 行为的前提下，把 P7-I01 至 P7-I24 转换成可重复检查的基线。S0 完成后，后续任何阶段都能看到：问题原来如何发生、期望语义是什么、由哪个阶段关闭、修复后应由哪条轻量不变量防止复发。

S0 不是泛泛“再扫描项目”。它必须逐项验证本计划中的问题证据，并允许用更准确的代码事实修正描述，但不能遗漏、合并隐藏或自行关闭问题。

### 本阶段只做

- 建立机器可读问题矩阵，至少记录编号、分类、当前状态、复现入口、期望不变量、归属阶段和证据路径。
- 为能够低成本复现的问题建立轻量 probe，覆盖至少：partial transition、错误 Mutation.before、动作所有权、单体多目标、重复 begin-turn、护盾不吸收、控制卡死、状态必定命中仍受抵抗、随机身份碰撞、队列头阻塞。
- probe 只输出精简 summary 和少量必要样例；不得把当前错误行为写成长期“正确通过”的单元测试。
- 对无法在轻量内存 case 中复现的问题，给出调用链和结构化静态证据，并说明后续阶段需要的正反例。
- 记录现有 P1-P6 验证分别能证明什么、不能证明什么，禁止用旧 `ok=true` 覆盖问题矩阵。

### 本阶段不做

- 不修 runtime，不改变现有结果。
- 不跑 P1-P6 全量聚合。
- 不重新构建完整 TBGD coverage 或写大体积 Canonical IR。

### 允许验收通过

- P7-I01 至 P7-I24 每项都在矩阵中有且只有一行主记录，并能追到归属阶段。
- 所有已列轻量复现均有“当前观察值”和“目标不变量”，不能只有布尔 `ok`。
- 若某项被认为不是缺陷，S0 只能记录争议与证据，不能自行关闭；需由验收线程裁决。
- 输出明确表示 P7 尚未完成，不得因为 S0 报告生成成功而输出 `all_fixed=true`。

### 不允许验收通过

- 仅做文本搜索，没有阅读执行路径。
- 只记录字段名或文件名，没有说明错误状态如何产生。
- 用固定角色、怪物或技能 ID 作为问题是否存在的唯一判据。
- 为节省工作把多个问题折叠成一条无法独立关闭的宽泛记录。

### 最小证据与验证

- 本阶段轻量问题基线脚本。
- `git diff --check`。
- 不跑 compileall，除非新增了 Python probe；若新增则只 compile P7 新脚本及直接导入模块。

## 9. P7-S1 Transition 可信结果契约

### 阶段目标

让每个动作结果明确回答“这个 after state 能否被当成真实战斗后继”。完成后，外部调用者不需要阅读 coverage 文本、process event 或日志猜测结果是否完整。

可信结果至少要区分：完整且可提交的成功、明确阻断且状态不变、仅供诊断且不可作为下一状态。具体类型和字段名由执行卡设计，但语义必须稳定并进入 BattleTransition 契约、序列化和查询接口。

### 本阶段只做

- 定义 transition 可信类别和形成条件。
- 汇总 action plan、effect、status callback、queue、target、formula 等执行结果的完整性信号，禁止最后由一个宽泛布尔值猜测。
- 规定推演器 / UI / route export 可消费哪些类别。
- 保持现有审计信息，但不让审计字段决定可信类别。
- 为“全部成功”“执行前被阻断”“内部出现 unsupported / partial”建立独立正反例。

### 本阶段不做

- 不在本阶段重写所有 partial 路径。
- 不修 Mutation.before。
- 不设计完整推演算法。

### 允许验收通过

- 可信类别是结构化契约，不是日志字符串。
- 完整动作的 transition 被标为可提交；执行前阻断的 transition 明确 state unchanged。
- 任一已选执行节点返回 unsupported / partial 时，结果不能标为可信成功，即使已有部分 mutation 计划。
- snapshot、settlement、source audit 和 replay 输出保留，并能与可信类别一致。

### 不允许验收通过

- 继续以 `action_enabled`、`ok` 或 mutation 非空单独代表完整成功。
- 让 UI 或未来推演器自行扫描 process event 判断是否可信。
- 为兼容旧样例把未知结果默认为成功。

### 最小证据与验证

- transition 契约轻量验证，至少覆盖三种结果类别。
- P7-S0 中 partial transition probe 的直接回归。
- `compileall` 仅覆盖 core 和本阶段验证脚本。
- `git diff --check`。

## 10. P7-S2 Mutation 前置条件与 reducer 冲突检测

### 阶段目标

让 Mutation 成为真正可验证的状态变更指令。每条 mutation 必须在应用前确认当前值与其声明的 before 一致，并按明确 op 语义得到 after；过期计划、同路径冲突和非法操作必须阻断原子提交。

### 本阶段只做

- 为 reducer 建立类型安全的 before 比较和 op 校验。
- 定义同一 transition 内多条 mutation 作用于相同路径时的合法顺序、组合方式和冲突条件。
- 让 reducer 返回结构化冲突，不得静默覆盖。
- 让 replay 独立检查 before 链，而不是只重放同一组 after 值。
- 迁移工作区内依赖宽松 reducer 的调用者和验证 fixture。

### 本阶段不做

- 不修动作完整性聚合。
- 不改变具体战斗公式。
- 不通过忽略 before 来兼容旧 mutation。

### 允许验收通过

- 正常连续 mutation 能按声明顺序应用。
- before 与真实状态不一致时，状态保持不变并产生可定位冲突。
- 非法 op、错误路径、同路径不兼容写入和 after 不符合 op 结果均被拒绝。
- replay 能发现被篡改的 before、顺序和 after。

### 不允许验收通过

- 只在 debug 模式或验证脚本中检查，生产 reducer 仍忽略 before。
- 使用模糊字符串比较导致数值、布尔、缺失值被误判相等。
- 冲突后仍提交其他 mutation。

### 最小证据与验证

- 纯内存 reducer 不变量：正常链、错误 before、重复路径、非法 op、篡改 replay。
- snapshot/replay 直接回归。
- `compileall` 和 `git diff --check`。

## 11. P7-S3 所选执行图原子提交

### 阶段目标

让一次动作中实际被选中、被触发的机制形成一张完整执行图。所有节点准入并成功后才能一次性提交 mutation；任何被选中节点缺目标、缺公式、unsupported、partial 或内部冲突时，整次动作都保持原状态。

这不要求未进入的条件分支也全部受支持。原子边界是“本次实际执行图”，不是整个技能定义文件。

### 本阶段只做

- 明确计划、预检、执行和提交的边界。
- 移除“主伤害失败但状态先加上”“状态只理解一半仍激活”“某个 callback 失败但前序 mutation 已提交”等部分成功路径。
- 将 P7-S1 的不可信结果与 P7-S2 的冲突结果接入统一提交门。
- settlement 和 process event 可以记录失败位置，但 after snapshot 必须等于 before。
- 建立多任务动作、监听器链和状态 partial 的原子性负例。

### 本阶段不做

- 不补齐每一种 unsupported opcode。
- 不用删除机制节点来制造“全部成功”。
- 不把所有失败都吞成普通 blocked；内部错误和来源缺失仍应可区分。

### 允许验收通过

- 完整选中图只提交一次，after 可由 mutation 严格得到。
- 任一选中节点失败时 mutation 提交数为零，after 与 before 语义相等。
- 失败节点、失败类别和真实 source trace 仍可审计。
- 未进入的条件分支不会无故阻断当前动作。

### 不允许验收通过

- 先 mutate BattleState，再在失败时尝试手工回滚。
- 仅把 transition 标为 untrusted，但仍向调用者暴露已改变 after state。
- 用 damage-only fallback 或跳过 unsupported task 形成可信成功。

### 最小证据与验证

- 多 task 中间失败、状态 partial、callback 中间失败、reducer 冲突四类原子负例。
- 至少一个多节点完整正例。
- S1、S2 直接回归，`compileall`，`git diff --check`。

## 12. P7-S4 规则输入与审计来源分离

### 阶段目标

让 runtime 的每个行为输入都来自明确的 Canonical IR / 数据卡 IR 字段或版本化引擎规则，而不是来自 `source_trace`、evidence、source path、文本提示或审计 payload。审计结构只负责解释和追溯，删除或裁剪审计详情不能改变战斗结果。

### 本阶段只做

- 逐条处理 P7-I16 记录的行为读取路径。
- 将确属规则的信息前移到 lowering / 数据卡构建并给予稳定类型字段。
- 将仅用于审计的信息从 runtime 判定中移除。
- 把行动值基数、击杀能量等暂未在 raw TBGD 找到直接来源的基础规则收敛到统一、版本化、显式标记的 engine rule registry；保留来源类别，不伪装成 TBGD。
- 增加静态和行为测试：裁剪 audit detail 后执行结果不变。

### 本阶段不做

- 不删除 source audit。
- 不把路径推断迁移到另一个 runtime helper。
- 不在本阶段完成所有 raw 表达式类型化，S5 负责表达式 IR。

### 允许验收通过

- P7-I16 所列入口均有代码级归属结论，行为读取已消失或迁移到结构化规则字段。
- 同一 IR 在完整审计和最小审计视图下产生相同可执行结果。
- engine convention 有稳定标识、版本、适用范围、明确来源类别和负例，不散落为魔法常量。
- 缺少规则字段时 blocked/state unchanged，不能回退到 evidence。

### 不允许验收通过

- 静态检查只禁用字段名，但换一个 helper 仍从审计信息取规则。
- 把 `engine_convention` 改名为 source-backed 而没有真实来源。
- 为减少 diff 保留“审计有值就执行”的兼容分支。

### 最小证据与验证

- 行为读取静态检查与审计裁剪等价性测试。
- engine rule registry 的来源、缺失和版本负例。
- P6 边界验证直接回归，`compileall`，`git diff --check`。

## 13. P7-S5 类型化可执行表达式 IR

### 阶段目标

让 target、numeric、condition 等可执行表达式在 lowering 阶段完成解析、类型检查和准入。runtime 只解释稳定 AST / IR 节点，不再解析 raw `$type`、raw postfix token、路径文字或结构不明的 payload。

### 本阶段只做

- 清点 runtime 仍解析的 raw 目标、数值和条件子语言。
- 为当前可执行子集建立类型化节点、明确 operand 和 unsupported 表达。
- 在 lowering 阶段完成引用解析，歧义匹配不得“取第一个”。
- 未支持表达式保留真实来源并 blocked，不能丢弃后继续执行。
- 保证序列化、source audit 和 replay 可以追到原始来源，但执行只读 typed IR。

### 本阶段不做

- 不要求一次支持 TBGD 所有表达式。
- 不在 runtime 读取 TextMap 或技能文本解释未知表达式。
- 不用字符串 alias fallback 代替类型化节点。

### 允许验收通过

- 当前 executable 正例不再经过 raw parser。
- raw 可识别、raw 未支持、引用缺失、引用歧义分别得到明确 lowering 结果。
- 引用歧义和未知表达式不得产生 runtime mutation。
- typed IR 的执行结果、来源和 replay 可验证。

### 不允许验收通过

- 仅用一个 `raw_payload` 字段包住原结构后改名为 IR。
- runtime 继续根据 `$type`、PostfixExpr、路径片段或字典形状分支。
- 选择第一个同名 / 同路径候选作为默认 linking。

### 最小证据与验证

- target、numeric、condition 各至少一个 typed 正例和一个 unsupported / ambiguous 负例。
- P5 参数绑定、目标 IR 和 P6 边界直接回归。
- `compileall`、`git diff --check`。

## 14. P7-S6 动作所有权、角色与窗口契约

### 阶段目标

让动作查询只暴露当前单位在当前战斗窗口真正可主动提交的动作。动作必须明确属于谁、扮演什么角色、在哪些窗口可用、消耗和门控是什么；被动、秘技、终结技、追加攻击、强化形态和强制脚本不能因为都在技能列表中而被当成普通回合动作。

### 本阶段只做

- 建立动作所有权和动作角色的结构化契约。
- 让角色卡、怪物卡、servant 子卡和未来装备 / 环境动作通过同一 admission 入口声明动作。
- 动作查询和 executor 共享所有权、窗口、资源与状态门控。
- 明确普通回合、任意时点可插入动作、队列触发动作、被动触发和场景外动作的区别。
- 对错误 actor、错误 action、错误窗口、被动直提和资源不足建立负例。

### 本阶段不做

- 不决定复杂目标范围，S7 负责。
- 不重做 scheduler 决策循环，S8 负责。
- 不批量补全所有角色动作分类；当前真实来源能确定的必须正确，缺失部分要诚实 blocked。

### 允许验收通过

- 查询结果中的每个动作都有明确 owner、角色和合法窗口。
- executor 从同一决策状态提交查询结果时不会因另一套所有权 / 窗口规则被拒绝。
- 未被查询出的动作、其他单位动作和被动入口直接提交时会被拒绝且 state unchanged。
- 角色原始 SkillList 不再等同于普通可选动作集合。

### 不允许验收通过

- 用技能名称或固定技能 ID 猜动作类型。
- 查询端过滤但 executor 仍允许绕过。
- 为未知动作默认赋予普通攻击 / 普通回合角色。

### 最小证据与验证

- 动作角色矩阵：普通、技能、终结技 / 插入窗口、被动 / 触发、错误 owner、错误窗口。
- 至少一个角色卡、一个怪物卡和一个 servant 数据卡结构化正例。
- action availability / preflight 直接回归，`compileall`，`git diff --check`。

## 15. P7-S7 目标选择与实际作用范围契约

### 阶段目标

把“玩家可以选择谁”和“动作最终作用到谁”分开表达。单体动作只能提交一个合法主目标；扩散、群攻、弹射和随机目标由 action definition 根据主目标与规则生成实际影响组，不能让调用者直接塞入任意目标列表。

### 本阶段只做

- 为目标关系、选择基数、主目标、影响组和顺序建立结构化契约。
- 明确 ally、enemy、self、owner、summoner、召唤物、场上、后场、不可选中等关系。
- 让 target query 与 action submit 共用同一解析结果。
- 对单体多选、敌我关系错误、重复目标、死亡目标、离场目标、不可选中目标和无主目标建立负例。
- 保持 bounce / retarget 等随机或派生选择与 S15 的 RNG 接口兼容，但本阶段不实现随机账本。

### 本阶段不做

- 不批量支持所有特殊玩法目标表达式。
- 不根据伤害 / 治疗效果类型猜敌我关系。
- 不把召唤物后场生命周期全部放进本阶段，S16 负责其状态来源。

### 允许验收通过

- 单体选择严格接受一个主目标；扩散 / 群攻的额外目标由规则产生。
- 查询返回的目标在状态未变化时可原样提交。
- 关系、基数或可选中性不明时 blocked，不使用默认敌方或默认第一目标。
- target resolution 明确记录 selectable targets、chosen primary 和 resolved impact group。

### 不允许验收通过

- 用目标数量自动猜单体 / 群体动作。
- 仍允许调用者直接提交“单体动作 + 多目标列表”。
- 通过过滤掉非法目标后继续执行剩余目标来伪装成功。

### 最小证据与验证

- 单体、扩散、群攻、弹射前置结构、关系错误和不可选中六类轻量不变量。
- 目标 IR 直接回归，`compileall`，`git diff --check`。

## 16. P7-S8 查询、决策与提交闭环

### 阶段目标

建立唯一的“推进到决策点 -> 查询合法动作 / 目标 -> 提交选择 -> 结算到下一个决策点”流程。只读查询不得推进时间或重复触发 turn begin；提交必须绑定查询时的决策状态，防止过期选择作用到新的行动者。

敌方与我方都通过同一决策接口交给外部控制器。怪物固定序列只能作为有真实来源的合法动作约束，不能由 scheduler 充当 AI 自动选择。

### 本阶段只做

- 定义可序列化的 decision token / state revision 或等价过期检测。
- 分离“推进到决策点”和“读取当前决策”，重复查询保持幂等。
- 提交查询结果时不再二次 advance 到下一回合。
- 让敌方动作候选进入相同查询 / 提交流程。
- 审计怪物固定序列：真实强制规则限制候选集合；非强制偏好不得进入 core 自动选择。

### 本阶段不做

- 不实现敌方 AI。
- 不实现搜索算法或路线评分。
- 不在本阶段修完整回合阶段顺序，S9 负责。

### 允许验收通过

- 同一决策状态连续查询不会改变 snapshot、事件计数或当前行动者。
- 查询返回的每个动作 / 目标组合在同一 token 下可提交；过期 token 被拒绝且 state unchanged。
- 一次提交只消费一次决策并只发生一次 turn begin。
- scheduler 不再替敌人选择普通动作；强制脚本必须有真实来源和结构化约束证据。

### 不允许验收通过

- 用 UI 缓存或调用约定掩盖查询会改变状态。
- 保留“敌方默认取序列下一技能”作为无来源自动逻辑。
- 查询和 submit 各自重算并可能得到不同动作集合。

### 最小证据与验证

- 查询幂等、query-submit round trip、过期 token、敌我同接口、强制规则来源五类不变量。
- scheduler / enemy action 直接回归，`compileall`，`git diff --check`。

## 17. P7-S9 显式回合与事件阶段机

### 阶段目标

把当前依赖函数调用顺序的回合流程变成显式阶段机。系统必须能确定当前处于推进时间线、回合开始、行动前结算、等待决策、动作执行、行动后结算、回合结束还是波次转换，并只在规定阶段派发对应事件。

### 本阶段只做

- 定义阶段、合法迁移和每个阶段允许的 mutation / queue 行为。
- 把 turn begin、pre-action、post-action、turn end 事件接入统一 dispatcher。
- 把 DoT、控制判定、状态持续时间和 callback 的触发点放入明确阶段；具体概率公式由 S14 负责。
- 为额外行动、终结技插入和反击保留清晰窗口，不把它们都当普通新回合。
- 建立 wave event 接入点，具体波次来源和 spawn 在 S17 完成。

### 本阶段不做

- 不修速度重算，S10 负责。
- 不修队列失效策略，S11 负责。
- 不批量实现所有 custom event。

### 允许验收通过

- 每个 transition / decision 能说明当前阶段及合法下一阶段。
- turn begin 事件实际派发，不只是写日志；DoT 和状态 tick 顺序由阶段机决定。
- 额外行动 / 插入动作不会错误重复普通回合开始与结束。
- 非法阶段提交动作或派发事件会被拒绝且 state unchanged。

### 不允许验收通过

- 继续靠“哪个函数先被调用”隐式表达阶段。
- 为通过旧验证在多个位置重复派发同一事件。
- 只新增 phase 字段，但现有系统不根据它约束行为。

### 最小证据与验证

- 普通回合完整事件顺序、DoT before-action、额外行动不重复 turn、非法迁移四类事件序列验证。
- event/status/scheduler 直接回归，`compileall`，`git diff --check`。

## 18. P7-S10 行动条与控制回合语义

### 阶段目标

让速度变化、拉条、推条、立即行动、回合平局和控制状态都通过统一时间线规则推进。受控单位不能把 scheduler 卡在同一决策点；速度变化必须基于已经经过的时间和剩余进度重新计算，而不是重置整个行动值。

### 本阶段只做

- 定义时间线时钟、剩余进度、速度变化和行动值更新的不变量。
- 将 tie break 从 unit id 偶然排序改为结构化、稳定、可审计的优先级规则；缺规则时不得伪造随机顺序。
- 控制门在正确阶段消费 / 跳过回合，并允许状态生命周期推进和解除。
- 统一 advance、delay、immediate action 与额外行动对时间线的影响。
- 保证死亡、离场、后场和不可行动单位不会被选为当前 actor。

### 本阶段不做

- 不在本阶段决定状态命中概率。
- 不把所有控制类型写成同一效果；具体类型由结构化状态规则决定。
- 不使用角色名或特殊怪物 ID 修顺序。

### 允许验收通过

- 速度中途改变时，剩余进度按明确公式连续变化，不重置已走时间。
- 同行动值单位顺序由结构化规则或显式选择决定，unit id 不承担游戏语义。
- 受控单位正确跳过 / 消费本回合，时间线继续，控制持续时间按阶段推进。
- 拉条、推条、立即行动和普通推进都有边界与 replay 正例。

### 不允许验收通过

- 被控制后只返回 blocked，当前 actor 不变。
- 用固定二级排序冒充来源明确的行动优先级。
- 速度变化直接把剩余行动值重算为完整基础行动值。

### 最小证据与验证

- 中途加速 / 减速、同值顺序、控制跳过并解除、拉条 / 推条、立即行动五类纯时间线不变量。
- scheduler/status 直接回归，`compileall`，`git diff --check`。

## 19. P7-S11 队列条目终态与前进保证

### 阶段目标

让每个进入队列的条目最终都能到达明确终态：执行完成、按真实规则重定向、被取消、被阻断并移出，或转入等待特定窗口。无效头项不能永久挡住后续合法条目。

### 本阶段只做

- 定义队列条目状态和合法迁移。
- 为 actor 死亡 / 离场、目标死亡 / 不可选、来源状态移除、窗口过期、执行图 blocked 建立结构化处理策略。
- 只有存在真实 retarget / retry 来源时才允许重定向或等待；否则取消并记录 settlement。
- 保证 drain 有单调前进不变量和有限步预算。
- 将队列处理接入 S9 阶段机和 S3 原子提交。

### 本阶段不做

- 不把所有失效条目统一改成换目标。
- 不实现没有真实来源的新队列 family。
- 不用无限 retry 规避失败。

### 允许验收通过

- 无效头项处理后，队列长度、头指针或等待窗口至少有一个可证明的合法进展。
- 取消 / 重定向 / blocked 的原因和来源可审计。
- 后续合法条目能够继续执行。
- 队列执行失败不会泄漏部分 mutation。

### 不允许验收通过

- catch exception 后保留原头项并继续循环。
- 无来源地默认换到第一个存活目标。
- 只给 drain 设置最大次数但不解决条目状态。

### 最小证据与验证

- 无效 actor、无效 target、来源状态消失、窗口过期、后续项继续五类轻量队列验证。
- queue/counter/extra-action 直接回归，`compileall`，`git diff --check`。

## 20. P7-S12 统一伤害与削韧结算管线

### 阶段目标

让不同伤害家族共享可复用但不混淆的结算阶段：各自的基础值生产器只负责生成该家族基础量，统一管线再按规则声明应用防御、抗性、易伤、减伤、暴击、击破专属倍率和其他 modifier。变量必须说明是基础量、中间量还是最终量，不能继续用模糊 amount 贯穿全程。

### 本阶段只做

- 明确 direct、DoT、break、super-break、hp loss 和 toughness 的适用阶段矩阵。
- 让 DoT、击破和超击破使用真实结构化公式输入，并经过各自应适用的共享乘区。
- 回正 before-hit / before-toughness 事件与计算顺序：事件改变状态后，受影响阶段必须读取更新后的快照或形成合法增量。
- 统一 modifier ledger，记录 applied 和 skipped 项及原因。
- 保持 source frame、击杀归因、多段和 replay 能力。

### 本阶段不做

- 不批量解释所有角色专属附加伤害。
- 不把 hp loss 当普通伤害吸收；其具体路由与 S13 协调。
- 不用网上公式常数直接写入 runtime；必须先确认 TBGD / 数据卡 / engine rule 归属。

### 允许验收通过

- 各伤害家族的基础值、适用乘区和最终值在 settlement 中可区分。
- DoT、击破、超击破不再把基础 packet 直接当最终伤害。
- before-event 改变相关状态时，本次结算反映新状态；不相关变化不重复计算整个动作。
- 每个适用乘区同时有 applied 与 skipped 结构化证据。

### 不允许验收通过

- 为一个样例调常数或硬编码角色 / 怪物。
- 把所有伤害强行走完全相同公式。
- 只让最终数值接近观测答案，却无法解释每个阶段来源。

### 最小证据与验证

- 每个伤害家族至少一个结构化正例；防御 / 抗性 / 易伤 / 减伤 applied 与 skipped 负例。
- before-event 影响当前结算的顺序验证。
- damage/source-frame/replay 直接回归，`compileall`，`git diff --check`。
- 只有改到全局公式 schema 且轻量验证不足时，才串行运行相关重验证；不得默认运行 `validate_v0_209`。

## 21. P7-S13 一等护盾与 HP 路由

### 阶段目标

把护盾从一个普通累计资源改为可参与伤害路由的一等战斗状态。系统必须知道每个护盾实例的来源、剩余值、叠加 / 替换规则、优先级、消失事件和可吸收范围，并在伤害 settlement 中明确记录护盾吸收与 HP 变化。

### 本阶段只做

- 建立护盾实例或等价的来源可区分结构。
- 将结构化 Add/Set/Replace/Remove 语义映射到真实护盾规则，不能把多个 opcode 无条件求和。
- 让普通伤害先按规则经过护盾；生命流失、穿透或特殊伤害仅在真实来源声明时绕过。
- 护盾耗尽触发 mutation-backed 事件，并可供状态监听使用。
- 迁移现有 aggregate shield 读取者，保留必要的 UI 汇总视图。

### 本阶段不做

- 不实现所有角色专属护盾特例。
- 不从技能文本猜叠加方式。
- 不让 UI 自己计算护盾吸收。

### 允许验收通过

- 有护盾时，可吸收伤害先减少护盾，再减少剩余 HP；完全吸收时 HP 不变。
- 多护盾替换 / 叠加行为由结构化来源决定，来源缺失时 blocked。
- hp loss 等不适用护盾的来源按明确路由执行。
- settlement、mutation、事件、replay 对护盾和 HP 的变化一致。

### 不允许验收通过

- 继续只维护一个 shield 数字而没有来源和规则。
- 对所有伤害都吸收或都不吸收。
- 护盾扣除只写日志，不形成 mutation。

### 最小证据与验证

- 完全吸收、部分吸收、多护盾策略、护盾耗尽事件、明确绕过五类验证。
- damage/status event/replay 直接回归，`compileall`，`git diff --check`。

## 22. P7-S14 状态施加、抵抗与完整准入

### 阶段目标

让所有状态先按结构化类别决定是否需要概率判定，再按对应抵抗与免疫规则形成一个明确的最终施加决策。增益、必定施加、普通减益、控制、特殊减益不能继续共用一条模糊路径；只有 duration、stack、property、target 和生命周期均可执行时才允许创建状态实例。

### 本阶段只做

- 区分不需要命中判定的状态和需要命中判定的负面状态。
- 对需要判定的来源组合基础概率、效果命中、效果抵抗、控制 / 特定抵抗和免疫，明确 clamp 与计算顺序。
- 省略概率的语义必须来自结构化来源：若表示必定施加，不得再次被普通效果抵抗降低；若来源不明则 blocked。
- 消除 definition 选择、持续时间模式和 dynamic binding 的路径猜测 / 首项匹配。
- 状态任何必需语义 unsupported 时，整次施加不产生 active partial mutation。

### 本阶段不做

- 不批量覆盖全角色和全怪物状态。
- 不把控制抵抗等同于普通效果抵抗。
- 不用文本关键词在 runtime 判断 buff / debuff / control。

### 允许验收通过

- 增益、必定施加、普通减益、控制、免疫分别有可解释的结构化路径。
- 每次需要概率的施加只形成一个最终随机决策，S15 将负责其全局身份。
- definition 或 binding 歧义会在 lowering / admission 阶段被阻断。
- unsupported duration/property/stack 不产生状态 mutation，after 与 before 相同。
- 状态成功后生命周期、source audit 和 replay 保持完整。

### 不允许验收通过

- 继续对所有 AddModifier 一律套效果抵抗。
- 用路径含 `Advanced`、文件顺序或第一个匹配项选 definition。
- 先创建 partial 状态，指望后续阶段补属性。

### 最小证据与验证

- 五类施加路径、控制 / 特定抵抗、免疫、歧义 linking、partial no-mutation 验证。
- P2 状态主验证的直接子集、S3 原子性和 S5 typed IR 回归。
- `compileall`、`git diff --check`。

## 23. P7-S15 随机决策身份与重放

### 阶段目标

让每一个逻辑独立的随机判断都有稳定唯一身份。身份必须足以区分动作、task、phase、hit、目标、状态施加和派生事件；外部推演器可以精确枚举或指定该决策，replay 也能证明没有复用、遗漏或多消费随机选择。

### 本阶段只做

- 定义 deterministic choice identity 和决策顺序。
- 让多段同目标暴击、多目标命中、状态施加、弹射 / 随机目标等独立事件不会碰撞。
- 明确 RNG ledger 是外部显式选择账本还是带状态推进的生成器；无论实现方式，都必须可序列化、可复现、可检测多余 / 缺失选择。
- 推演器主路径只接受精确 choice key / event id；宽泛 rng_type / default 不能冒充具体来源。
- settlement 记录每个选择如何影响结果。

### 本阶段不做

- 不实现推演搜索策略。
- 不用真实随机掩盖 choice identity 缺失。
- 不要求无随机来源的确定性动作生成 RNG event。

### 允许验收通过

- 同一输入与同一 ledger 得到相同事件序列、mutation 和 after snapshot。
- 多段同目标产生独立且稳定的决策身份。
- 缺选择、多余选择、重复 key 和错误 key 都有明确失败，不能 fallback 到默认成功。
- 外部控制器能够逐个枚举独立分支。

### 不允许验收通过

- 只按 `rng_type` 或目标 id 区分多段事件。
- 所有未指定选择都静默取固定默认值并标 exact。
- replay 不检查 ledger 是否被完整且仅消费一次。

### 最小证据与验证

- 多段同目标、多目标、状态命中、随机目标、缺 / 多 / 重复选择、确定性 replay 验证。
- damage/status/target RNG 直接回归，`compileall`，`git diff --check`。

## 24. P7-S16 战斗中召唤物生命周期接入

### 阶段目标

让召唤物、servant 和由怪物召唤的单位不只在 BattleSetup 中存在，而能由真实 action task / effect / callback 在战斗中生成、进入正确 presence、时间线、动作查询和清理流程。可选中性、前场 / 后场和 owner / summoner 关系必须来自出生模板与生命周期规则。

### 本阶段只做

- 将真实召唤 intent 接入 S3 原子执行图和统一 spawn consumer。
- 让出生模板的 presence、targetable、actionable、timeline admission、owner / summoner relation 和 cleanup policy 贯穿 UnitLifecycle。
- 角色召唤物继续归属角色卡 / 子卡；怪物召唤物复用已有怪物卡，召唤者只提供关系和生命周期绑定。
- owner 死亡 / 离场、召唤物死亡、替换和显式 remove 均形成可审计生命周期事件。
- 对缺模板、模板不完整、篡改绑定、后场目标和默认 targetable 建立负例。

### 本阶段不做

- 不批量实现所有忆灵和召唤怪。
- 不用召唤系统临时理解角色卡或怪物卡内部结构。
- 不让后场单位仅靠 UI 隐藏来模拟不可选中。

### 允许验收通过

- 至少一个真实结构化 action/task 来源可在战斗中生成单位并进入正确生命周期。
- 后场 / 不在场 / 不可选中单位不会进入普通目标集合，除非 action definition 明确允许。
- summon action availability 与其 own card / subcard 一致。
- 清理、替换、owner relation、source audit 和 replay 均有正反例。

### 不允许验收通过

- 只增加 synthetic spawn command 或继续只测 BattleSetup。
- targetable 缺失时默认为 true。
- owner 死亡后依赖手工 scenario cleanup。

### 最小证据与验证

- 战斗中 spawn、后场不可选、召唤物行动、owner cleanup、缺 / 篡改模板五类验证。
- P3 召唤底座直接回归，target/action/timeline 相关轻量回归。
- `compileall`、`git diff --check`。

## 25. P7-S17 波次生命周期与事件源接入

### 阶段目标

让波次切换成为显式战斗生命周期，而不是只生成下一批单位。波次开始、单位进入、当前波次清理、下一波准备和战斗结束必须通过统一阶段机和事件 dispatcher，使真实来源的入场被动、开波状态、环境效果和 `OnWaveMonster` 类监听能够正确触发。

### 本阶段只做

- 定义波次状态和阶段迁移。
- 将 wave start、monster enter、wave clear、next wave、battle complete 等当前真实事件源接入 dispatcher。
- 复用 P6 UnitBirthTemplateIR 和 S16 生命周期，不重复拼装怪物单位。
- 明确召唤物、残留状态、队列和时间线在换波时的保留 / 清理来源。
- 缺 stage / wave / birth / event payload 时 blocked/state unchanged，不能生成半个波次。

### 本阶段不做

- 不实现所有关卡环境和特殊模式。
- 不把环境规则塞入怪物卡。
- 不为当前数据库无来源的 custom event 造正例。

### 允许验收通过

- 至少一个真实两波场景完成：清场、切换、生成、事件派发、时间线恢复和结束判定。
- wave / monster enter 监听只有真实 payload 和条件准入时才执行。
- 换波期间无重复 birth、重复 turn begin 或遗留无主队列项。
- source audit、Mutation replay 和波次 settlement 可完整追踪。

### 不允许验收通过

- 只把事件名写入 process log，不经过 dispatcher。
- 每个波次系统自行拼 UnitState，绕过出生模板。
- 以“后续关卡扩面”掩盖当前通用换波状态机缺失。

### 最小证据与验证

- 真实两波纵切、入场事件、缺 payload 负例、残留清理、战斗完成五类验证。
- P1 two-wave、P3 summon 和 P6 birth template 直接回归。
- `compileall`、`git diff --check`。

## 26. P7-S18 推演器紧凑状态与审计分离

### 阶段目标

在不改变任何战斗语义的前提下，为未来推演器提供紧凑、稳定、可哈希的战斗状态视图。静态 RuleBook、来源图和完整审计详情不应在搜索树的每个节点重复复制；完整 transition 和 provenance 仍可按需取得。

### 本阶段只做

- 区分影响未来战斗结果的动态状态、仅影响展示的派生视图和静态 provenance。
- 建立 canonical state key / compact snapshot 或等价接口。
- 对状态、队列、时间线、RNG ledger、波次、召唤关系和 decision phase 的语义字段进行完整纳入。
- 让审计详情按引用或惰性方式访问，不改变 source audit 能力。
- 建立语义等价与非等价状态测试，并记录复制、序列化和内存预算。

### 本阶段不做

- 不实现搜索算法、剪枝或目标函数。
- 不为了压缩丢失会影响未来结算的状态。
- 不把 compact view 变成第二套可修改 BattleState。

### 允许验收通过

- 战斗语义相同但审计展开程度不同的状态得到相同 key。
- 任一会影响未来动作、随机、状态、队列、波次或时间线的字段变化都会改变 key。
- compact state 只读或不可变，提交仍经过正式 core API。
- 给出可重复的轻量预算对比，证明不再复制完整来源图；不得只声称“更快”。

### 不允许验收通过

- 用 snapshot JSON 全文 hash 冒充紧凑状态。
- 为减小 key 忽略动态值、队列窗口、RNG 消费或召唤关系。
- 在审计关闭时改变战斗结果。

### 最小证据与验证

- 语义相等 / 不相等键测试、audit detail 等价性、序列化 round trip、只读边界和预算对比。
- snapshot/replay/source audit 直接回归，`compileall`，`git diff --check`。

## 27. P7-S19 最终不变量聚合、报告与文档收口

### 阶段目标

建立 P7 的最终可信度聚合。它必须逐行继承 S0 问题矩阵和 S1-S18 的验收结果，证明 24 项问题没有在阶段间消失、改名或被宽泛 `ok=true` 覆盖，并确认 P1-P6 的底座能力没有因内核回正而退化。

### 本阶段只做

- 建立轻量 P7 invariant aggregate，优先复用单次构建和阶段 summary，不重复全量 lowering。
- 将 P7-I01 至 P7-I24 每项映射到 accepted evidence、代码位置和负例。
- 区分 P7 内核修复完成与全角色 / 全怪物 / 全装备 / 全关卡正例完成。
- 串行运行必要的 P1-P6 聚合回归，并审查过时口径：旧验证若把已修能力预期为 blocked，应升级验证，不得为旧断言恢复错误行为。
- 更新 CODEX_HANDOFF、DOCUMENTATION_INDEX、AGENTS 长期状态和最终 checkpoint 报告。

### 本阶段不做

- 不新增机制来让聚合变绿。
- 不把未修问题重新分类成来源缺口。
- 不默认写全量 Canonical IR 或 transition dump。

### 允许验收通过

- P7-I01 至 P7-I24 均为验收线程认可的 `accepted_fixed` 或 `not_a_defect_with_evidence`，不存在 confirmed_open、implementation_missing、lowering_gap、admission_gap、validation_gap 或 unclassified。
- transition 可信门、原子提交、严格 reducer、query-submit、动作 / 目标、阶段机、timeline / control、queue、damage、shield、status、RNG、summon、wave 和 compact state 的核心不变量全部通过。
- 所有被阻断或不可信结果 state unchanged；所有可信结果 replay/source audit 通过且 selected execution graph 完整。
- P1-P6 聚合在更新后的正确口径下通过；保留的内容 coverage gap 被原样继承，不冒充 P7 内核缺陷，也不被写成全正例完成。
- 静态检查能阻止 runtime 从 audit/source evidence 和 raw expression 提取行为。

### 不允许验收通过

- 总表行数少于 S0，或问题只在正文中说“已处理”没有 evidence。
- 某个机制有一个正例就把整个域标为完成。
- 只跑最终聚合脚本而不检查代码、predicate、样例和矩阵继承。
- 任何 partial / blocked transition 仍能被推演器接口当成正式后继。

### 最小证据与验证

- `compileall`。
- P7 最终轻量 invariant aggregate。
- 按调用链触达范围串行运行 P1、P2、P3、P4、P5、P6 聚合；每项结束后检查 summary，再运行下一项。
- static checks、snapshot replay、source audit、`git diff --check`。
- 所有重验证使用 `ionice -c3 nice -n 15`，输出到 `/tmp`，不得并行，不得默认生成大产物。

## 28. 分层验证与资源预算

每个阶段默认验证层级如下：

- 必跑最小集：本阶段新不变量、直接修改模块的 compileall、`git diff --check`。
- 直接回归集：只运行与改动有实际调用链或数据契约关系的旧验证。
- 条件触发集：改到 shared reducer、transition、snapshot/replay、source audit、target、RNG、damage、status lifecycle、timeline、queue、summon、wave 时，运行对应跨系统轻量回归。
- 全量聚合集：默认只在 P7-S19 和最终验收运行。某阶段若发生结构性大改，必须在执行卡中解释为何提前运行。

验证脚本必须优先使用纯内存 fixture、最小 RuleBook slice 或按结构化谓词抽取的真实来源样例。需要 TBGD 的正例应尽量共享一次 lowering / RuleBook 构建。禁止为了一个 reducer、target 或 timeline 不变量全量序列化数据库。

任何会全量读取 TBGD、构建完整 RuleBook、执行阶段聚合或写较大 `/tmp` 产物的命令都属于重验证：一次只运行一个；使用低 IO / 低 CPU 优先级；默认只写 summary、matrix 和必要抽样；预计明显占满内存或磁盘 IO 时，执行线程必须先说明并等待用户确认。

`validate_v0_209` 继续不作为普通直接回归。只有 P7-S12 或 P7-S15 改到 direct damage / crit / RNGEvent schema，且本阶段轻量不变量与 P1 主验证无法覆盖风险时，才允许串行运行，并且默认不写完整产物。

## 29. 兼容与迁移口径

v8 旧 Python API、旧 JSON、旧 CLI 和旧 compiled case 不是兼容目标。P7 不得为了保留错误语义增加永久兼容分支。

若一个阶段改变工作区内 core API，执行线程必须在同一阶段列出并迁移全部当前调用者、验证和 UI adapter。若发现工作区外确有用户正在依赖的接口，执行卡必须暂停并请求用户决定是否做临时迁移层；未经确认不得擅自增加兼容包袱。

旧验证失败时先判断：

- 它是否依赖了已确认错误行为。
- 它是否只验证了 replay 自洽，没有验证语义。
- 它是否把当时未完成的机制固定成永久 blocked。
- 它是否用固定内容、默认 fallback 或过宽 predicate 选择样例。

只有验证目标仍正确时才修实现；验证口径过时则升级验证，并在 evidence 中说明原因。

## 30. 唯一执行 Checklist

- [x] P7-S0 已建立 P7-I01 至 P7-I24 的问题基线、轻量复现和唯一归属矩阵，未修改 runtime 行为。
- [ ] P7-S1 已建立机器可读的 transition 可信结果契约，不完整结果不能冒充可提交成功。
- [ ] P7-S2 已强制 Mutation before、op 和同路径冲突校验，过期计划不能静默覆盖状态。
- [ ] P7-S3 已实现所选执行图原子提交，任一选中节点失败时 state unchanged。
- [ ] P7-S4 已彻底分离规则输入与审计来源，并收敛版本化 engine rule 来源。
- [ ] P7-S5 已将当前可执行 target / numeric / condition 子集 lower 为类型化 IR，runtime 不再解析 raw 子语言。
- [ ] P7-S6 已建立动作所有权、动作角色、使用窗口和资源门的统一查询 / 提交契约。
- [ ] P7-S7 已建立目标关系、选择基数、主目标和实际作用范围契约。
- [ ] P7-S8 已建立幂等查询、决策 token、一次提交一次推进和敌我统一外部控制流程。
- [ ] P7-S9 已建立显式回合 / 事件阶段机，并回正 turn、DoT、状态 tick 和插入动作窗口。
- [ ] P7-S10 已回正速度变化、行动值、同值顺序、控制跳过和时间线推进语义。
- [ ] P7-S11 已建立队列条目终态和前进保证，无效头项不再永久阻塞。
- [ ] P7-S12 已建立统一且分家族适用的伤害 / 削韧管线，并回正 before-event 计算顺序。
- [ ] P7-S13 已建立一等护盾实例、吸收 / 替换语义和 HP 路由。
- [ ] P7-S14 已回正状态施加、命中 / 抵抗 / 免疫、definition linking 和 partial no-mutation。
- [ ] P7-S15 已建立独立随机决策身份、精确选择账本和严格 replay 消费。
- [ ] P7-S16 已接通真实战斗中的召唤物 / servant spawn、presence、targetability、行动和清理生命周期。
- [ ] P7-S17 已接通波次状态机、单位入场、wave event、清理和结束判定。
- [ ] P7-S18 已建立推演器可用的紧凑只读状态键，并将静态 provenance / 审计详情移出搜索节点复制路径。
- [ ] P7-S19 已完成问题总账继承、不变量聚合、P1-P6 串行回归、报告和长期文档收口。
- [ ] P7-DONE：P7-I01 至 P7-I24 均经独立验收关闭，内核只对完整原子结果给出可信后继；P7 内容覆盖边界与全角色 / 全怪物 / 全装备 / 全关卡完成度已被诚实区分。
