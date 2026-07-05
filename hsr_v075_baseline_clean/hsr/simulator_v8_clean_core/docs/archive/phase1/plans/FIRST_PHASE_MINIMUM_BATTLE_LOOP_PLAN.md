# v8 第一阶段最小完整战斗闭环规划

本文档面向后续实现线程，用于把 v8 clean core 从当前 `v0_289 target expression sequence filter retarget` 推进到“外部推演器可驱动的最小完整战斗闭环”。

第一阶段不追求全角色、全怪物、全光锥、全遗器覆盖。第一阶段要先把《崩坏：星穹铁道》战斗系统中会改变状态空间的通用底座建立起来，让后续内容扩面和推演器搜索建立在正确的核心语义上。

## 0. 核心定位

### 0.1 第一阶段目标

第一阶段的目标是：

```text
外部推演器提供动作选择
+ v8 core 判断动作是否合法
+ v8 core 执行规则化状态转移
+ v8 core 输出可 replay、可 audit、可分支的 BattleTransition
```

换句话说，v8 core 在第一阶段应具备以下能力：

- 从最小战斗配置构建 battle state。
- 支持敌我双方显式动作输入。
- 支持队列中必须自动结算的动作。
- 支持多波战斗的单位生成和波次推进。
- 支持召唤物、assistant、servant 的最小生命周期和行动/队列语义。
- 支持状态叠层、刷新、持续时间、tick、概率、抵抗、免疫、驱散的通用底座。
- 支持行动轴、队列窗口、目标解析、RNG 事件和 replay。
- 所有状态变化都通过 `Mutation` 表达。
- 所有 executable mutation 都能通过 source audit 追溯到 Canonical IR / 数据卡 IR。

### 0.2 第一阶段非目标

第一阶段明确不做：

- 不做敌方 AI。
- 不做完整搜索器。
- 不做全角色机制覆盖。
- 不做全怪物机制覆盖。
- 不做全光锥、全遗器、全关卡机制覆盖。
- 不为了单个角色、单个怪物、单个关卡在 runtime 写特判。
- 不为了旧 v7、旧 CLI、旧 JSON、旧 model pack 做兼容。

敌方 AI 不是本项目目标。敌方动作最终由推演器控制。v8 core 只负责：

- 暴露敌方当前合法动作。
- 接收外部传入的敌方动作。
- 按真实规则执行敌方动作。
- 处理敌方技能、被动、阶段、召唤、波次、状态触发。
- 在缺少真实来源时 blocked/state unchanged。

### 0.3 事实来源边界

第一阶段必须继续遵守 v8 来源边界：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR。runtime 不能直接读取 TBGD raw schema、TextMap、旧 v7、旧 model pack。

blocked、audit_only、discovered_only、placeholder、derived process-only 不能产生状态 mutation。

## 1. 当前代码落点

本节记录第一阶段规划所依赖的当前实际代码状态。

### 1.1 已经存在的核心底座

- `rules/ir.py`
  - 已定义 `CanonicalIR`、`ActionDefinitionIR`、`EffectIR`、`TargetExpressionIR`、`StatusCallbackIR`、`QueueIntentIR`、`CharacterDataCardIR`、`MonsterDataCardIR` 等核心 IR。
- `rules/rulebook.py`
  - 已作为 runtime 查询 IR 的索引层。
- `core/model.py`
  - 已定义 `BattleState`、`UnitState`、`ActionCommand`、`Mutation`、`BattleTransition`。
  - `UnitSide` 已包含 `ally`、`enemy`、`summon`。
  - `BattleState` 已包含 `wave_index`，但还没有完整 WaveSystem。
- `core/executor.py`
  - `CombatExecutor.execute` 是动作执行入口，已经串联 target、resource、timeline、ability、effect、damage、event dispatch。
- `core/reducer.py`
  - 已支持 mutation replay。
- `core/source_audit.py`
  - 已支持 mutation 来源审计。
- `systems/damage.py`
  - 已有 direct、DoT、break、super-break、hp loss 等伤害路径的统一框架。
- `systems/target.py`
  - 已支持目标表达式的安全子集，包括 alias、明确群体、context target list、sequence、filter、deterministic retarget。
- `systems/queue.py`
  - 已有 queue family 概念，包括 follow_up、counter、ultimate、extra_turn、interrupt、immediate、insert_action、insert_ability、assistant、unknown。
- `systems/enemy_action.py`
  - 已有敌方行动候选和固定序列候选。它应继续作为“候选来源/规则输入”，不能演变成 AI。
- `systems/status.py`
  - 已有状态添加、移除、tick/expire 的框架，但叠层、刷新、概率等主体语义仍不完整。
- `systems/status_callbacks.py`
  - 已有 callback、predicate、retarget、list target、status damage、DoT、action delay、queue intent 等入口。
- `scenarios/schema.py` 与 `scenarios/build_state.py`
  - 已有显式 scenario 构建能力，但还不是完整战斗配置装配层。

### 1.2 当前特别需要补齐的缺口

- `BattleState.wave_index` 只是索引字段，不等于波次系统。
- summon side 存在，但缺少召唤物生成、退场、owner、lifetime、timeline admission、目标解析闭环。
- assistant queue family 存在，但缺少可执行窗口和 actor/ability/target admission。
- `OnWaveMonster` 等事件族已被识别，但缺少真实波次事件源。
- 状态系统对 stack、refresh、chance、resist、immunity、dispel 仍大量 partial/blocked。
- `TargetSort`、`TargetFetch`、random、adjacent、unique entity、summon/servant target 仍是关键阻塞。
- `TurnInsertAction`、`TurnInsertAbility`、`TurnInsertAssistantAbility`、`SummonMonster` 等仍主要停留在 audit_only 或 blocked。

## 2. 第一性原理拆分

星铁战斗模拟器的核心不是“执行一个技能”，而是维护一个可审计、可重放、可搜索的状态转移系统。第一阶段所有任务都应服务于下面这条等式：

```text
before snapshot
+ action input
+ Canonical IR / 数据卡 IR
+ deterministic choices / RNG events
+ mutations
== after snapshot
```

因此，第一阶段应优先建设会影响状态空间和搜索分支的底座：

1. 谁有权选择动作。
2. 哪些动作是合法输入。
3. 哪些动作是强制队列结算。
4. 单位如何出生、死亡、退场。
5. 波次如何推进。
6. 召唤物和 assistant 如何进入状态空间。
7. 状态如何添加、失败、刷新、tick、过期、驱散。
8. 行动轴和队列如何决定执行顺序。
9. 目标如何确定或 blocked。
10. RNG 如何记录、重放、分支。

## 3. 工作流 A：动作权责边界

### 3.1 目标

把“动作选择”和“规则执行”彻底分开。

推演器负责选择动作。v8 core 负责验证动作是否合法，并执行动作产生 `BattleTransition`。

### 3.2 当前基础

- `ActionCommand` 已存在。
- `CombatExecutor.execute` 已是统一动作入口。
- `systems/enemy_action.py` 已能给出敌方固定序列候选。
- queue 系统已经能表示部分强制或插队动作。

### 3.3 需要完成的设计

需要定义统一的行动上下文分类：

- `external_selectable`
  - 当前轮到某个单位，由外部推演器选择动作。
  - 包括我方普通行动、敌方普通行动、可能的 summon 独立行动。
- `queued_mandatory`
  - 规则已经产生队列动作，当前必须结算。
  - 包括追击、反击、部分插入能力、部分 assistant ability。
- `queued_selectable`
  - 规则产生了一个可选窗口，需要外部决定是否执行。
  - 典型例子是终结技插队窗口。
- `blocked`
  - 当前动作来源、目标、资源、条件或队列语义不足，不能执行。

### 3.4 需要实现的能力

- 增加或整理一个 action availability 查询能力。
  - 可命名为 `ActionAvailability`、`LegalActionView` 或同等结构。
  - 不要求第一阶段实现完整搜索器，只要能暴露当前动作边界。
- 对当前 state 判断：
  - 是否存在必须先结算的 queue item。
  - 是否轮到某个 actor 选择行动。
  - actor 有哪些 action definition 可用。
  - action 的资源是否满足。
  - action 的目标表达式是否可以解析。
  - action 是否因缺少 admission blocked。
- 敌方行动不再被描述为 AI。
  - `enemy_action.py` 可继续提供候选。
  - 候选只代表“规则上可用或数据中定义的敌方动作”，最终动作由外部传入。

### 3.5 验证用例

- 我方 actor 轮到行动时，legal action view 暴露可选 action。
- 敌方 actor 轮到行动时，legal action view 暴露敌方 action 候选，但不自动替推演器选择。
- 存在 mandatory queue item 时，普通行动不可输入。
- 传入资源不足动作时 state unchanged，并记录 blocked settlement。
- 传入不存在或无来源 action 时 state unchanged。

### 3.6 完成标准

- core 不主动决定敌人要放哪个技能。
- 外部传入 enemy action 可以完整执行。
- queue mandatory 与 external selectable 不混淆。
- 后续推演器可以基于 action availability 枚举动作空间。

## 4. 工作流 B：UnitLifecycle 通用系统

### 4.1 目标

统一角色、敌人、召唤物、assistant/servant 相关实体的出生、死亡、退场、不可选中、行动资格。

星铁战斗中，“死亡”“退场”“暂时不可选中”“阶段切换替换”“召唤物消失”不能混成一个布尔值。第一阶段至少要把通用生命周期语义定下来。

### 4.2 当前基础

- `UnitState` 已有 hp、alive、side、flags、resources、statuses 等字段。
- damage 系统已有击杀归因基础。
- reducer 已能 replay unit 字段 mutation。
- target resolver 已能过滤 alive/dead 的部分语义。

### 4.3 需要定义的生命周期事件

建议先定义以下 mutation 语义：

- `UnitSpawn`
  - 新单位进入 battle state。
  - 需要携带 unit id、side、profile/card ref、source trace、spawn reason。
- `UnitDefeat`
  - 单位 HP 到 0 或被规则击败。
  - 保留尸体状态，供击杀触发、结算、审计使用。
- `UnitRemove`
  - 单位从当前战斗可见单位集合中移除。
  - 用于波次结束清理、召唤物退场、阶段替换。
- `UnitRevive`
  - 单位从 defeated 回到 alive。
  - 第一阶段可先 blocked，除非有真实来源和通用语义。
- `UnitPhaseReplace`
  - 敌人阶段切换导致 profile/action/status 变化。
  - 第一阶段可先作为 WaveSystem 或 UnitLifecycle 的扩展点，不急于全量实现。

### 4.4 需要补齐的规则

- 死亡单位：
  - 不能作为普通 target。
  - 不能按 timeline 继续行动。
  - 已在 queue 中的动作需要判断是否取消、保留或 blocked。
  - 仍可作为部分“尸体/击杀来源/最近目标”审计对象。
- 退场单位：
  - 不应再出现在普通 target set。
  - 不应参与 action availability。
  - 对 replay 来说应能通过 mutation 重建。
- 新生成单位：
  - 必须有来源。
  - 必须有初始 profile。
  - 必须明确是否进入 timeline。
  - 必须明确是否可被选中。

### 4.5 验证用例

- 伤害击杀敌人后产生 defeat mutation。
- 死亡敌人不能再被普通 alive target 选中。
- 死亡 actor 的普通行动输入 blocked。
- 已死亡 target 上的派生伤害被跳过并记录 skipped settlement。
- spawn 出来的单位出现在 snapshot、target resolver、timeline eligibility 中。
- remove 后单位不再进入目标和行动候选。

### 4.6 完成标准

- 所有单位生灭都通过 mutation。
- target、timeline、queue、damage 对死亡和退场语义一致。
- summon、wave、phase 后续可以复用同一生命周期底座。

## 5. 工作流 C：WaveSystem 最小骨架

### 5.1 目标

让多波战斗成为真实规则系统，而不是一个孤立的 `wave_index` 字段。

星铁战斗常见多波敌人、波次刷新、波次开始触发、波次结束触发、关卡倍率或环境效果。推演器要搜索完整战斗，就必须能跨波推进。

### 5.2 当前基础

- `BattleState.wave_index` 已存在。
- reducer 已能处理 `wave_index` 相关 mutation 路径。
- `OnWaveMonster` 等事件族已在状态监听矩阵中被识别，但目前缺少真实事件源。
- scenario 当前可以手工放入敌方单位，但这不是完整波次系统。

### 5.3 需要新增的结构

建议新增或扩展以下数据结构：

- `WaveDefinitionIR`
  - wave id。
  - enemy entries。
  - spawn profile/card refs。
  - level/elite/boss/phase metadata。
  - source trace。
- `BattleWaveRuntimeState`
  - current wave index。
  - active spawned unit ids。
  - cleared wave ids。
  - pending spawn events。
- `WaveTransitionPlan`
  - wave clear 检测结果。
  - despawn/remove 列表。
  - spawn 列表。
  - event dispatch 列表。

第一阶段可以先不追求名字完全如此，但需要有等价能力。

### 5.4 Wave clear 规则

第一阶段建议先支持确定性 wave clear：

```text
当前 wave 中所有 enemy side 的 required alive enemy 都 defeat/remove
=> current wave cleared
=> 进入下一 wave 或 battle end
```

需要注意：

- summon enemy 是否计入 wave clear 必须由 wave/summon metadata 决定。
- 已退场敌人不应阻塞 wave clear。
- phase 替换不是 wave clear，不能混淆。
- 波次推进必须产生 mutation 和 process event。

### 5.5 跨波保留规则

第一阶段必须明确默认策略：

- 我方 HP 保留。
- 我方能量保留。
- SP 保留。
- 我方常规状态是否保留取决于状态定义。
- 敌方状态随敌方单位退场清理。
- queue 默认应清理与已退场单位相关的队列项。
- summon 是否跨波保留必须由 summon metadata 决定；缺来源时 blocked 或按 process-only 记录。
- action timeline 是否重排必须明确记录。

### 5.6 事件源

至少需要提供：

- `OnWaveStart`
- `OnWaveEnd`
- `OnWaveMonster`
- `OnUnitSpawn`
- `OnUnitRemove`

如果当前 IR 只有 `OnWaveMonster`，runtime 可以先只接通真实存在的事件族，其他事件作为内部 process event 使用，但不能伪装成 TBGD 来源。

### 5.7 验证用例

- 击杀当前 wave 最后一个 enemy 后进入下一 wave。
- 下一 wave enemy 通过 spawn mutation 进入 state。
- wave_index 通过 mutation 更新。
- wave start event 可以驱动已有 listener。
- 缺少 wave definition 时不能自动推进。
- summon enemy 是否阻塞 wave clear 有明确规则。

### 5.8 完成标准

- 多波战斗不需要把所有敌人预先手工塞入 state。
- 波次推进可 replay。
- wave event 有真实事件源或明确 process-only。
- `OnWaveMonster` 不再只是被识别但无触发来源。

## 6. 工作流 D：Summon / Assistant / Servant 最小闭环

### 6.1 目标

把当前 summon/assistant/servant 的预留变成可执行的战斗实体或队列语义。

星铁里不同机制的“召唤物”并不完全等价：

- 有些是可行动、可被选中、在行动轴上存在的单位。
- 有些是角色绑定的 servant 或机制条表现。
- 有些是 assistant ability，本质是队列中触发的一次能力。
- 有些是敌方召唤出的普通怪物或阶段单位。

第一阶段不需要完全覆盖所有差异，但必须建立分类和最小可执行路径。

### 6.2 当前基础

- `UnitSide` 已有 `summon`。
- snapshot teams 已包含 summon。
- `MonsterDataCardIR` 已保留 `summon_refs`。
- target resolver 已在部分群体中考虑 ally + summon。
- timeline 对 summon 有 admission 检查。
- queue family 已包含 assistant。
- `SummonMonster`、`TurnInsertAssistantAbility` 等 opcode 已被发现，但当前主要为 audit_only。

### 6.3 建议分类

第一阶段建议采用以下分类：

- `battle_unit_summon`
  - 进入 `BattleState.units`。
  - 可有 HP、status、targetability。
  - 可选择性进入 timeline。
- `assistant_ability`
  - 不作为常驻 unit。
  - 表达为 queue item 或 ability execution frame。
  - 需要 actor/source/owner。
- `servant`
  - 与 owner 绑定。
  - 可能有独立行动轴，也可能只提供被动触发。
  - 第一阶段可先支持最小 owner-bound timeline unit。
- `summoned_monster`
  - 敌方召唤出的 enemy unit。
  - 应进入 wave/unit lifecycle。

### 6.4 必须补齐的字段

无论最终字段名称如何，都需要表达：

- `owner_unit_id`
- `summoner_unit_id`
- `source_action_id` 或 `source_ability_id`
- `source_trace`
- `summon_kind`
- `lifetime_policy`
- `timeline_policy`
- `targetability_policy`
- `wave_persistence_policy`

### 6.5 timeline 接入

需要明确：

- summon 是否进入行动轴。
- summon 初始 AV 如何计算。
- summon 的速度来源是什么。
- summon 行动后是否重新排轴。
- owner 死亡时 summon 是否退场。
- wave 切换时 summon 是否保留。

缺少来源时，不能默认给速度或 AV。应 blocked 或 admission 为不可行动 summon。

### 6.6 target 接入

需要支持：

- 选择所有 ally + summon。
- 选择 owner 的 summon。
- 选择 enemy summon。
- 选择 unique summon/servant。
- 召唤物死亡后不再进入 alive target。
- summon target 缺少 owner/source 时 blocked。

### 6.7 queue 接入

assistant ability 第一阶段可以不作为单位，但必须进入统一 queue/window：

- queue item 需要记录 owner、assistant source、ability ref、target expression。
- actor frame 需要能表达“这次 ability 的执行者是谁，归因给谁”。
- damage/heal/status mutation 需要能追溯到 assistant source。

### 6.8 验证用例

- TBGD 来源的 summon monster 生成 enemy unit。
- summon unit 可以被 target resolver 选中。
- summon death 产生 UnitDefeat。
- owner 死亡导致 summon 退场或 blocked，取决于来源。
- assistant ability 作为 queue item 执行一次 ability。
- 缺少 summon profile/source 的 summon opcode 不产生 mutation。

### 6.9 完成标准

- 至少一条真实 summon 或 assistant 机制可以从 IR admission 到 runtime mutation。
- summon/assistant 的伤害、状态、资源变化可 source audit。
- unsupported summon 类型保持 blocked，不用默认值补齐。

## 7. 工作流 E：状态系统主体

### 7.1 目标

把状态系统从“能挂一部分 modifier”推进为星铁战斗的通用 buff/debuff/control/DoT 底座。

状态系统是第一阶段最重要的核心之一。角色、怪物、光锥、遗器、环境机制大量通过状态表达。如果状态语义不完整，后续内容扩面会把特殊逻辑散落到各个系统。

### 7.2 当前基础

- `systems/status.py` 已有状态添加、移除、tick、expire 的框架。
- `AddModifier`、`RemoveModifier`、`RemoveSelfModifier` 已有部分 executable 覆盖。
- `systems/status_callbacks.py` 已有状态监听、callback task、status damage 等入口。
- damage 系统已有 DoT/status damage 的处理路径。

### 7.3 叠层语义

需要支持：

- `max_layer`
- 当前层数读取。
- 添加层数。
- 层数达到上限后的处理。
- 按层数影响 dynamic value/formula。
- 层数减少。
- 层数归零时移除状态。

需要避免：

- 仅修改展示层数，不产生 mutation。
- 层数超过上限。
- 缺少 max layer 时默认无限叠。

### 7.4 刷新语义

需要支持：

- 重新应用同一状态时刷新 duration。
- 重新应用时只增加 stack，不刷新 duration。
- 重新应用时 stack 和 duration 都刷新。
- 新旧来源 coexist。
- 强制 replace。
- 刷新失败或来源不足时 blocked。

关键是不能只用一个 `is_refresh` 布尔值吞掉差异。需要 admission 出可执行的 refresh policy。

### 7.5 持续时间语义

需要区分：

- 按持有者回合减少。
- 按施加者回合减少。
- 按 action 次数减少。
- 按 tick/window 减少。
- 按 wave 结束清理。
- 永久状态。

第一阶段至少要支持最常见的：

- turn start。
- turn end。
- action after。
- wave end。
- permanent。

### 7.6 tick 语义

需要支持：

- DoT tick。
- turn start tick。
- turn end tick。
- delayed damage/heal tick。
- tick 后 duration 更新。
- tick 触发 callback。
- target dead 时 skipped settlement。

DoT 应由状态生命周期驱动，而不是由某个伤害路径孤立触发。

### 7.7 概率、抵抗、免疫

需要完整表达：

- base chance。
- effect hit rate。
- effect resist。
- control resist。
- debuff resist。
- immunity。
- success branch。
- failure branch。
- blocked branch。

第一阶段不要求覆盖所有复杂角色修正，但必须建立 RNG 和 settlement 结构：

```text
attempt status application
-> compute admitted chance
-> consume deterministic RNG choice
-> success or failure
-> mutation only on success
-> process settlement always recorded
```

没有 RNG choice 或公式来源不足时，不能偷偷使用不可追踪随机数。

### 7.8 驱散语义

需要支持：

- 状态是否可驱散。
- buff/debuff/control 分类。
- positive/negative target。
- 驱散数量。
- 驱散优先级。
- 随机驱散。
- 驱散失败 settlement。

第一阶段可先支持确定性优先级和显式 target 的驱散。随机驱散必须接入 RNG ledger。

### 7.9 控制状态

控制状态第一阶段需要建立通用影响：

- actor 是否能普通行动。
- actor 是否能终结技。
- actor 是否能触发追击/反击。
- actor 在 timeline 上是否跳过或延后。
- 控制解除后如何恢复。

freeze、imprison、entangle 等细分可以后续逐步 admission，但不能把控制写成角色特判。

### 7.10 验证用例

- 状态成功添加，产生 mutation。
- 状态添加因概率失败，不产生 mutation，但有 settlement。
- 状态添加因免疫失败，不产生 mutation。
- 状态叠层到上限后不超过上限。
- 状态刷新 duration。
- 状态 tick 造成 DoT。
- 状态过期移除。
- 驱散一个 debuff。
- 随机驱散记录 RNG event。
- 控制状态阻止 actor 行动。
- 缺少 chance/formula/source 的状态应用 blocked。

### 7.11 完成标准

- 状态成功、失败、跳过、blocked 都有清晰 settlement。
- 状态 stack、refresh、tick、expire、dispel 全部通过 mutation。
- DoT 与状态生命周期连通。
- 概率与抵抗进入 RNG ledger。

## 8. 工作流 F：行动队列与窗口语义

### 8.1 目标

让追击、反击、终结技插队、额外回合、assistant、insert action/ability 共享一套确定的窗口和优先级。

星铁中很多战斗结果并不是由当前 action 直接结束，而是由 action 触发的一串队列继续结算。推演器必须知道哪些队列是强制的，哪些窗口允许选择。

### 8.2 当前基础

- `systems/queue.py` 已有 queue family。
- `QueueIntentIR` 已能表达 opcode、queue_kind、actor alias、action/ability ref、target alias 等。
- status callback 已能生成部分 queue intent。
- executor 已有部分队列处理入口。

### 8.3 需要定义的窗口

至少需要以下窗口：

- battle start。
- wave start。
- turn start。
- before action。
- before hit。
- after hit。
- after damage。
- after break。
- after kill。
- after action。
- turn end。
- wave end。
- ultimate interrupt window。
- queue drain window。

不是所有窗口都必须第一阶段支持完整内容，但命名、顺序、blocked 策略要先统一。

### 8.4 queue family 优先级

需要明确同一窗口内的排序：

- interrupt。
- ultimate。
- immediate。
- counter。
- follow_up。
- extra_turn。
- insert_action。
- insert_ability。
- assistant。
- unknown blocked。

具体顺序应以 TBGD/现有 queue family 发现为准；如果没有真实来源，不能把 engine convention 伪装成 TBGD 来源。可以作为 runtime scheduling convention 记录，但 settlement/source audit 必须区分。

### 8.5 mandatory 与 selectable

必须区分：

- mandatory queue
  - 规则触发后必须结算。
  - 推演器不能跳过。
- selectable queue
  - 规则打开选择窗口。
  - 推演器可选择执行或不执行。
- conditional queue
  - 条件满足时进入队列。
  - 条件不支持时 blocked。

终结技窗口尤其要谨慎。终结技不是简单 queue item，它是玩家可选择插队的动作窗口。第一阶段可以先提供窗口表达和外部输入，不必实现完整 UI 决策。

### 8.6 queue item 字段

queue item 至少需要：

- queue id。
- family。
- priority。
- actor ref。
- owner/source ref。
- action ref 或 ability ref。
- target expression。
- creation event。
- source trace。
- expiration rule。
- cancel rule。
- mandatory/selectable flag。

### 8.7 timeline 关系

需要明确：

- extra turn 是否插入 timeline。
- insert action 是否消耗当前 actor 正常行动。
- follow-up/counter 是否影响 AV。
- summon 行动是否按 timeline 重排。
- queue drain 期间是否允许新的 interrupt。

### 8.8 验证用例

- action 后触发 follow-up，follow-up 在普通下一行动前结算。
- 受击后触发 counter。
- 击杀后触发 kill callback，再触发后续队列。
- extra turn 不错误推进到其他 actor。
- ultimate window 暴露为 selectable。
- assistant queue 能执行一次 ability。
- actor 死亡时其 pending queue 被取消或 blocked。
- unknown queue family 不产生 mutation。

### 8.9 完成标准

- 队列顺序确定。
- 队列 drain 可 replay。
- 推演器能观察当前是否必须结算队列。
- assistant、insert ability 不再只停留在 audit_only。

## 9. 工作流 G：目标系统关键缺口

### 9.1 目标

补齐第一阶段最影响通用战斗的目标表达式，避免角色/怪物机制因目标解析不足大量 blocked。

### 9.2 当前基础

- 已支持 TargetAlias。
- 已支持明确群体。
- 已支持 context target list。
- 已支持 TargetSequence。
- 已支持 TargetFilter。
- 已支持确定性 Retarget。
- 缺少随机、排序、fetch、相邻、unique entity、summon/servant 等关键语义。

### 9.3 优先目标表达式

第一阶段建议优先补：

- `TargetSort`
  - 按 HP、HP ratio、toughness、position、speed、aggro 等排序。
- `TargetFetch`
  - 从上下文、caster、owner、partner、unique entity 等取目标。
- adjacent target
  - 扩散伤害和相邻效果必需。
- random target
  - 弹射、随机 debuff、随机驱散必需。
- unique entity
  - servant、特殊召唤物、关卡实体必需。
- summon/servant target
  - owner summon、enemy summon、all summons。
- dynamic max number
  - 需要从 dynamic value 或 formula 取数量。

### 9.4 blocked 策略

目标系统必须继续遵守：

- 缺目标不 fallback 到默认目标。
- 缺排序规则不 fallback 到 unit id 顺序。
- 缺 payload 不 fallback 到 caster 或 selected target。
- random 没有 RNG choice 不偷偷随机。
- unique entity 找不到时 blocked/state unchanged。
- dead/alive 条件不明确时 blocked。

### 9.5 target resolution record

每次目标解析应记录：

- 输入 target expression id。
- caster。
- context target。
- candidate list。
- filter/sort/random 步骤。
- selected targets。
- skipped targets。
- blocked reason。
- source trace。

### 9.6 验证用例

- 按 HP ratio 排序选择目标。
- 选择相邻目标。
- random target 消耗 RNG event。
- unique summon target 解析成功。
- dead target 被过滤。
- 缺排序规则 blocked。
- 缺 RNG choice blocked 或由外部 deterministic choice 提供。
- target resolution record 可在 transition 中审计。

### 9.7 完成标准

- 第一阶段常见群体、随机、相邻、召唤物目标可用。
- 目标失败不产生 mutation。
- 随机目标可 replay。

## 10. 工作流 H：RNG 与分支基础

### 10.1 目标

第一阶段不实现完整搜索器，但必须让 core 不再产生不可追踪随机性。

所有随机行为必须满足：

```text
同一 before snapshot
+ 同一 action input
+ 同一 IR
+ 同一 RNG events
=> 同一 after snapshot
```

### 10.2 RNG 事件范围

第一阶段至少覆盖：

- 状态命中。
- effect resist。
- control resist。
- random target。
- random bounce。
- random dispel。
- random queue target。

### 10.3 deterministic choice 输入

executor 应允许外部传入 deterministic choices：

- 可以是 rng seed + draw index。
- 也可以是 explicit choice list。
- 具体形式可以沿用现有 `rng_state`，但必须能被 transition 记录。

### 10.4 branch enumeration 预留

第一阶段不做搜索器，但应为后续保留接口：

- `requires_rng_choice`
- `available_rng_outcomes`
- `probability_weight`
- `choice_id`
- `replay_value`

如果当前 runtime 需要随机但没有 choice，应 blocked 或返回需要 choice 的 transition plan，不能调用不可审计随机数。

### 10.5 验证用例

- 同一 rng event replay 得到同一结果。
- 不同 rng event 得到不同合法结果。
- 状态命中成功和失败都有 settlement。
- random target 没有 choice 时不产生 mutation。
- RNG event 出现在 transition。

### 10.6 完成标准

- 第一阶段所有概率和随机目标都可记录。
- replay 不依赖进程内随机状态。
- 后续推演器可以枚举随机分支。

## 11. 工作流 I：最小战斗配置入口

### 11.1 目标

提供一个足够表达第一阶段测试战斗的配置入口，避免只能手写 `BattleState`。

这不是完整装配系统。第一阶段只要求能表达多波、有状态、有召唤、有显式敌方动作的测试战斗。

### 11.2 当前基础

- `scenarios/schema.py` 已有 `ScenarioSpec`。
- `scenarios/build_state.py` 已能从 scenario 构造 state。
- 角色数据卡、怪物数据卡已能参与部分构建。

### 11.3 需要补齐的配置概念

建议新增或扩展：

- battle setup id。
- ally roster。
- enemy waves。
- initial SP。
- initial energy。
- initial HP ratio。
- initial statuses。
- initial summon/servant。
- initial timeline。
- rng seed or deterministic choices。
- objective metadata。

第一阶段可以允许显式 profile/card ref，不要求从完整角色养成配置自动装配。

### 11.4 需要避免的方向

- 不把 UI scenario 当成规则来源。
- 不在 scenario 中硬写 runtime 特判。
- 不用旧 model pack 作为 v8 规则输入。
- 不用 TextMap 技能文本补 runtime 规则。

### 11.5 验证用例

- scenario 构建一场两波战斗。
- scenario 构建一个已有初始状态的角色。
- scenario 构建一个初始 summon。
- scenario 提供 deterministic rng choices。
- scenario 中引用不存在 card/profile 时 blocked 或构建失败。

### 11.6 完成标准

- 实现线程可以用配置文件构造第一阶段验证场景。
- 配置入口不污染 runtime 来源边界。
- UI 仍只是编排和展示层。

## 12. 工作流 J：第一阶段验证矩阵

### 12.1 验证原则

每个新增 executable 机制必须有：

- 正例。
- 负例。
- replay 验证。
- source audit 验证。
- blocked/audit-only 不产生 mutation 验证。

验证不能依赖：

- 固定角色名。
- 固定怪物名。
- 固定文件名。
- 固定 hash。
- 观测伤害答案。
- 旧 v7 输出作为规则来源。

样例选择应优先使用结构化谓词：

- opcode。
- coverage_status。
- target expression kind。
- callback event type。
- queue family。
- formula support status。
- source mode。

### 12.2 必备验证项

动作边界：

- ally legal action。
- enemy legal action。
- mandatory queue blocks normal action input。
- enemy action explicit command execution。
- enemy action no source blocked。

UnitLifecycle：

- damage defeat。
- dead target skipped。
- dead actor action blocked。
- unit spawn。
- unit remove。
- queue item canceled when actor removed。

WaveSystem：

- current wave clear。
- next wave spawn。
- wave_index mutation。
- wave start process event。
- OnWaveMonster callback。
- missing wave definition blocked。

Summon/Assistant/Servant：

- summon monster spawn。
- summon targetable。
- summon acts or explicitly blocked by timeline policy。
- summon death。
- owner death interaction。
- assistant queue ability execution。
- unsupported summon blocked。

状态系统：

- status apply success。
- status apply chance failure。
- status apply resisted。
- status immune。
- stack add。
- stack cap。
- duration refresh。
- tick damage。
- expire remove。
- dispel deterministic。
- dispel random with RNG。
- control blocks action。

Queue/Window：

- follow-up order。
- counter order。
- after kill callback。
- extra turn order。
- ultimate selectable window。
- assistant family order。
- unknown family blocked。

目标系统：

- sort target。
- fetch caster/owner/unique。
- adjacent target。
- random target replay。
- summon target。
- dead/alive filter。
- missing payload blocked。

RNG：

- deterministic replay。
- branch outcome record。
- missing rng choice blocked。
- probability settlement success/failure。

配置入口：

- two-wave setup。
- initial statuses。
- initial summon。
- deterministic rng setup。

### 12.3 验证输出

验证输出应继续放在 `/tmp` 或版本化输出目录，不能污染仓库运行目录。

建议第一阶段最终新增一个聚合验证命令，例如：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_phase1_minimum_loop --output-dir /tmp/hsr_v8_phase1_minimum_loop
```

具体命名可由实现线程决定。

## 13. 建议实施顺序

### 13.1 P1-0：术语和接口边界

产出：

- action availability 设计。
- queue mandatory/selectable 分类。
- enemy action 不做 AI 的接口约束。
- 第一阶段验证计划骨架。

不做：

- 不改大量 runtime 行为。
- 不引入内容扩面。

### 13.2 P1-1：UnitLifecycle

产出：

- UnitSpawn / UnitDefeat / UnitRemove mutation 语义。
- dead/remove 对 target、timeline、queue 的统一处理。
- 击杀归因与 skipped settlement 补强。

原因：

波次、召唤物、阶段切换都依赖单位生命周期。先做生命周期，可以避免后续各系统各自发明生灭语义。

### 13.3 P1-2：WaveSystem

产出：

- wave definition/runtime state。
- wave clear 检测。
- wave spawn/remove mutation。
- wave event source。
- 两波验证场景。

原因：

完整战斗推演必须跨波。没有 wave，战斗终止条件和敌人生成都不完整。

### 13.4 P1-3：Summon / Assistant / Servant

产出：

- summon 分类。
- owner/source/lifetime/timeline/targetability 策略。
- summon spawn 或 assistant queue 的第一条真实 executable 纵切。
- summon target 验证。

原因：

召唤物既影响目标空间，也影响行动轴和波次清理。必须在状态系统大规模扩面前接入。

### 13.5 P1-4：状态系统主体

产出：

- stack。
- refresh。
- duration。
- tick。
- chance/resist/immunity。
- dispel。
- control gating。

原因：

这是角色、怪物、光锥、遗器机制的最大公因数。越晚做，越容易出现 runtime 特判。

### 13.6 P1-5：Queue/Window

产出：

- window 顺序。
- queue family 优先级。
- mandatory/selectable queue。
- extra turn、follow-up、counter、assistant 最小闭环。

原因：

状态 callback 和召唤物会不断产生队列动作。队列语义必须在内容扩面前稳定。

### 13.7 P1-6：Target/RNG

产出：

- TargetSort。
- TargetFetch。
- adjacent。
- random。
- unique summon/servant。
- deterministic RNG event。
- branch enumeration 预留。

原因：

目标和 RNG 是推演器分支的入口。它们必须以可 replay 的形式进入 transition。

### 13.8 P1-7：最小战斗配置入口

产出：

- two-wave setup。
- initial statuses。
- initial summon。
- deterministic rng choices。
- objective metadata 预留。

原因：

第一阶段验证不能一直靠手写 state。需要稳定配置入口给 UI、验证和推演器共享。

### 13.9 P1-8：阶段验收聚合

产出：

- 聚合 validation。
- source audit 抽样报告。
- replay 报告。
- live validation report。
- 第一阶段剩余 blocked 清单。

原因：

第一阶段完成标准不是“某个场景能跑”，而是核心状态转移底座可审计、可重放、可扩展。

## 14. 设计决策待锁定

以下问题在实现前应尽快定稿：

1. action availability 是直接放进 core，还是作为 systems 层查询服务。
2. queue selectable window 如何表达给外部推演器。
3. wave definition 是新增 IR，还是先作为 scenario/runtime setup 数据卡。
4. UnitRemove 后是否保留 tombstone 用于 replay 和审计。
5. summon side 是否继续使用 `summon`，敌方召唤物是否仍为 `enemy` side 加 summon metadata。
6. servant 是独立 unit，还是 owner-bound runtime component。
7. RNG choice 是 seed/draw 模型，还是 explicit choice ledger 模型。
8. 状态 duration 默认按谁的回合减少，没有来源时是否一律 blocked。
9. ultimate window 在第一阶段是否只暴露 selectable，不自动执行。
10. engine scheduling convention 如何和 TBGD source trace 分开记录。

这些问题不需要用户每项拍板，但实现线程必须在对应 patch 中把决策写清楚，并用验证保护。

## 15. 主要风险

### 15.1 把 enemy action 候选误做成 AI

风险：

- core 开始替敌人选择动作。
- 推演器无法枚举全部可能性。
- 搜索目标被破坏。

控制方式：

- 所有 enemy action 选择必须来自外部 command 或明确 queue mandatory。
- `enemy_action.py` 只保留候选和数据来源，不做策略。

### 15.2 用默认值补来源缺口

风险：

- 缺速度时默认 100。
- 缺目标时默认 selected target。
- 缺排序时默认 unit id。
- 缺 RNG 时直接 random。

控制方式：

- 缺来源 blocked/state unchanged。
- validation 必须覆盖缺来源负例。

### 15.3 状态系统过早按角色特判

风险：

- 每个角色机制都写一套状态逻辑。
- 后续光锥、遗器、怪物无法复用。

控制方式：

- stack、refresh、duration、tick、chance、dispel 先做通用 admission。
- 专属内容进入数据卡机制槽位。

### 15.4 wave、summon、unit lifecycle 各自实现生灭

风险：

- wave spawn 一套逻辑。
- summon spawn 一套逻辑。
- phase replace 一套逻辑。
- replay 和 source audit 难以统一。

控制方式：

- 先实现 UnitLifecycle。
- wave、summon、phase 都复用 UnitSpawn/UnitRemove/UnitDefeat。

### 15.5 queue/window 顺序不稳定

风险：

- 追击、反击、额外回合、终结技窗口顺序不可重复。
- 推演器分支不可控。

控制方式：

- queue family priority 进入 transition。
- queue drain 每一步有 process event。
- unknown family blocked。

## 16. 第一阶段完成定义

第一阶段可以认为完成，当且仅当：

- 外部可以显式驱动 ally/enemy/summon 的合法动作。
- core 不做敌方 AI。
- 多波战斗可以通过 wave system 推进。
- 单位 spawn、defeat、remove 可 replay。
- 至少一种 summon 或 assistant 机制能真实执行。
- 状态 stack、refresh、duration、tick、chance/resist/immunity、dispel 有通用底座。
- follow-up、counter、extra turn、assistant、ultimate window 有清晰队列/window 语义。
- sort/fetch/adjacent/random/unique/summon target 的关键子集可用。
- RNG 事件进入 transition，不能出现不可追踪随机。
- 最小 battle setup 能构建两波、有状态、有召唤、有 deterministic RNG 的验证场景。
- 聚合 validation 通过。
- snapshot replay 通过。
- source audit 通过。
- blocked/audit-only/discovered-only 不产生 mutation。
- runtime 不引用旧 simulator、旧 model pack、TextMap、raw TBGD。

## 17. 给实现线程的工作方式

每个实现线程建议按以下格式推进：

1. 先读本计划对应工作流。
2. 用 CodeGraph 查对应 symbols 和 callers。
3. 只读取与当前工作流直接相关的文件。
4. 先补 IR/admission/source 边界。
5. 再补 runtime mutation。
6. 再补 replay/source audit。
7. 再补 positive 和 negative validation。
8. 最后更新 live validation report。

每个 patch 结束时都应回答：

- 当前机制真实来源是什么。
- 新增 mutation 如何追溯到 IR。
- 缺来源时如何 blocked。
- replay 如何证明。
- source audit 如何证明。
- 是否引入了 runtime 特判。
- 是否影响旧接口，是否需要兼容。

第一阶段的关键不是一次写完所有内容，而是把状态空间的骨架定稳。骨架定稳之后，角色、怪物、光锥、遗器、关卡机制才适合批量扩面。
