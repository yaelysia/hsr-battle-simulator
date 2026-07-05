# P1-5 行动队列与窗口语义总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-5 行动队列与窗口语义` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-5 的实现、验证和阶段报告。

P1-5 的一句话目标：

```text
把追击、反击、终结技插队、额外回合、insert action、insert ability、assistant 等后续行动统一纳入 source-admitted、deterministic、mutation-backed、可 replay 的 queue/window 底座。
```

这不是“写一个优先级表”。星铁战斗里当前动作经常会打开后续窗口：有些必须立即结算，有些允许玩家/推演器选择，有些只在条件成立时入队。P1-5 要回答的是：

```text
当前 transition 结束后，外部推演器是否必须先结算 queue？
如果不是强制结算，是否存在 selectable window？
如果既不能结算也不能选择，原因是 source gap、条件不满足、目标无效、资源不足，还是 runtime 实现缺口？
```

P1-5 计划必须沿用 P1-3 之后的总体性计划规格，并吸收 P1-4 的来源缺口经验：每个小项都先做三态判断，不能为了勾选 checklist 合成 TBGD 中不存在的正例。

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是在 core 中写敌方 AI，而是支持外部推演器搜索：

```text
给定战斗配置、动作选择和随机分支
=> core 判断合法性、执行规则、输出完整 transition
=> 外部推演器从可能路径中寻找达成目标的通关方式
```

因此 P1-5 里所有“选择”都应暴露给外部推演器，core 只负责：

- 说明当前是否有强制队列必须结算。
- 说明当前是否打开了可选择窗口，例如终结技插队或额外回合路线选择。
- 校验外部输入是否合法。
- 按已承认来源执行队列动作。
- 对缺来源、缺目标、缺公式、缺资源、缺生命周期策略的情况返回 blocked/process-only settlement。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR 或 scenario/setup 层已经构造好的 runtime setup。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测伤害或手工答案作为规则输入。

### 0.2 P1-5 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

已经完成或已验收底座的前置阶段：

- P1-0 Action Boundary：core 不做敌方 AI，只暴露行动候选、合法性和 transition。
- P1-1 UnitLifecycle：单位 `active / defeated / removed` 统一进入 damage、target、timeline、queue、action availability。
- P1-2 WaveSystem：多波战斗通过 WaveDefinition、UnitSpawn、UnitRemove、wave_index mutation、wave events 推进。
- P1-3 Summon / Assistant / Servant：召唤物、assistant、servant 已建立分类、spawn/target/timeline/owner 互动的最小闭环，但 assistant queue 仍需要 P1-5 决定窗口边界。
- P1-4 StatusSystem：状态施加、tick、DoT、control gating、deterministic dispel 等已有通用底座；部分无真实来源机制保持 source gap，不允许合成正例。

P1-5 承接 P1-4 的 status callback，影响后续：

- P1-6 target：queue item 的 actor/target expression、相邻目标、排序、随机、retarget 需要更完整目标系统。
- P1-7 RNG：随机队列顺序、随机目标、随机触发需要统一 RNG ledger。
- P1-8 setup/route：推演器需要基于 queue/window view 选择下一步路线。
- 角色/怪物扩面：追击、反击、额外回合、召唤/assistant、怪物被动都会复用这个底座。

### 0.3 星铁中的 queue/window 概念

星铁中的后续行动至少包含这些容易混淆的形态：

1. **follow-up / 追击**
   - 由状态、天赋、技能、装备或怪物机制触发。
   - 通常是强制或条件触发的后续攻击。
   - 不是普通行动，也不应消耗普通行动轴。

2. **counter / 反击**
   - 通常由受击、被攻击、特定事件触发。
   - 与 follow-up 类似，但窗口来源、优先级、触发 payload 和目标多半不同。

3. **ultimate interrupt / 终结技插队**
   - 玩家可选择插入的 selectable window。
   - 不是普通 mandatory queue。core 不能擅自替玩家放终结技。
   - 需要暴露 energy/resource preflight、目标选择和外部 command 校验。

4. **extra turn / 额外回合**
   - 通常是 source-admitted 的额外行动窗口。
   - 与 timeline 的自然 AV 推进不同，可能需要 deferred turn end 和额外生命周期策略。
   - route/source 可能允许选择普通攻击、战技或终结技。

5. **insert action**
   - TBGD `TurnInsertAction` 降出的队列意图。
   - 可能是 fixed skill index，也可能是 route/source selected action。
   - 不能凭名字判断是追击、额外回合或内部连段。

6. **insert ability**
   - TBGD `TurnInsertAbility` 降出的队列意图。
   - 可能指向 standalone ability graph 或 ability phase。
   - 不能把 ability name 直接当作 action id。

7. **assistant**
   - `TurnInsertAssistantAbility` 当前 lowering 已识别，但 admission 明确 blocked。
   - P1-5 只能做结构化 source gap/blocked 或在找到真实可执行链路后接入，不能合成 assistant 正例。

P1-5 的重点不是一次性复刻所有角色/怪物队列机制，而是把这些形态放进统一的窗口、优先级、选择性、取消和审计模型中。

### 0.4 当前代码事实

以下结论来自当前代码实际状态，不是从文档倒推。

当前主要落点：

```text
systems/queue.py
systems/scheduler.py
systems/status_callbacks.py
systems/action_availability.py
systems/event_dispatch.py
systems/unit_lifecycle.py
systems/status.py
rules/ir.py
rules/rulebook.py
tbgd/lowering.py
tools/validate_v0_241.py
tools/validate_v0_243.py
tools/validate_v0_250.py
tools/validate_v0_255.py
tools/validate_v0_256.py
tools/validate_v0_265.py
tools/validate_v0_266.py
```

当前事实：

- `rules.ir` 已有 `QueueIntentIR`、`QueueResolutionIR`、`QueuePriorityIR`、`QueueWindowIR`、`QueueLifecyclePolicyIR`、`ExtraActionPolicyIR`。
- `tbgd/lowering.py` 已把 `TurnInsertAbility`、`TurnInsertAction`、`TurnInsertAssistantAbility` 降成 `QueueIntentIR`。
- `TurnInsertAssistantAbility` 当前在 `_queue_intent_admission` 中明确 blocked，原因是 `queue_insert_assistant_ability_not_admitted`。
- `TurnInsertAction` 在 `PrepareAbilityName` 或可承认 `SkillType` / fixed `SkillIndex` 时可进入 executable intent；部分形态会被归为 `extra_turn` 或 `insert_action`。
- `TurnInsertAbility` 可以解析 ability name，并尝试降到 standalone ability graph 或 ability phase resolution。
- `QueueWindowIR` 的 window family 当前由 `_queue_window_family` 推出；结构化 `TurnInsertAssistantAbility` 为 `assistant`，`turn_insert_action` 为 `insert_action` 或 `extra_turn`，`turn_insert_ability` 为 `insert_ability`；文本 hint 只能导致 `unknown`，不能成为 executable family 来源。
- `systems/queue.py` 已有 `QueueEntry`、`QueueWindowPlan`、`QueueDrainPlan`，并已记录 entry id、queue kind、actor、action/ability ref、target ids、priority、source trace、queue window、window family、target resolution、status、drain_status。
- `QUEUE_WINDOW_FAMILY_ORDER` 当前存在：`follow_up/counter=0`、`ultimate/extra_turn=10`、`interrupt=20`、`immediate=50`、`insert_action=60`、`insert_ability=70`、`assistant=90`、`unknown=999`。这只是当前 runtime ordering convention，P1-5 必须审查它的来源与语义，不能把它伪装成 TBGD source。
- `QueueSystem._queue_window_plan` 会 blocked 缺 `queue_window_id/window_family`、target resolution 非 ok、未知 family、assistant family、缺 ordering admission、extra_turn 缺 lifecycle admission。
- `QueueTargetResolver` 已支持 `Caster`、`ModifierOwnerEntity`、`ParamEntity`、`CurrentActionTarget`、`AbilityTargetEntity`、`DamageAttackerEntity`、若干 target list、`AllEnemy`、`AllTeamMember`、`AllLightTeam`。
- `StatusCallbackSystem._execute_queue_intents` 只会对 executable intent + executable window + ok target resolution 生成 `queue_enqueue` mutation；task/intent/window blocked 时只出 blocked settlement，不入队。
- `StatusCallbackSystem` 已有 insert once precheck，即 `SameTagInsertUnusedCount` 可阻止重复入队。
- `CombatScheduler.step` 会优先尝试 `_try_queue_drain`，再处理 pending turn end、wave transition、natural turn。
- 普通 action 后若 `after_action` 有 pending queue，scheduler 会写 `pending_turn_end`，延迟自然 turn end，先让 queue drain。
- `queue_plan_requires_external_command` 当前把 `ultimate` 和部分 extra turn route choice 视为需要外部 command。
- `ActionAvailabilitySystem` 已能基于 next queue drain plan 产出 `SelectableWindow`，metadata 中包含 drain plan 和 queue resolution。
- `enqueue_manual_ultimate` 已存在，会创建 `manual_ultimate` queue entry，window family 为 `ultimate`，并在 drain 时校验 actor、action、target、energy。
- 旧验证 `validate_v0_241`、`validate_v0_243`、`validate_v0_250`、`validate_v0_265`、`validate_v0_266` 已覆盖部分 queue drain、scheduler bridge、extra turn lifecycle、kill-to-extra-turn、ultimate priority 行为，但有些回归样例偏角色特化。P1-5 主验证必须用结构化谓词选样，旧验证只能作回归参照。

当前最重要的风险：

```text
queue/window 字段和部分 runtime 路径已经存在，但 family 语义、mandatory/selectable 边界、source/convention 分离、取消策略和可推演器契约仍然不完整。
P1-5 不能把“已有 QueueEntry 可 enqueue/drain”当成“队列系统语义完整”。
```

### 0.5 来源缺口验收口径

P1-5 的每个子项必须按三态判断：

- `executable`：当前 RuleBook / Canonical IR 中存在真实来源，runtime mutation、settlement、source audit、replay 均通过。
- `source_gap_blocked`：runtime 可以有 guarded path、blocked path 或未来预留字段，但当前 TBGD / IR 结构化扫描没有真实可执行来源；验证只能证明 coverage gap、blocked、state unchanged，不能合成正例 mutation。
- `implementation_missing`：当前存在真实来源，但 runtime 没有正确 admission / mutation / settlement / replay，这才是需要继续编码修复的缺口。

P1-5 预计会遇到的高风险 source gap：

- `assistant`：当前 `TurnInsertAssistantAbility` 已发现，但 lowering admission 明确 blocked。
- `follow_up` / `counter`：当前 family 可能更多来自 priority key、ability ref、路径或文本 hint；如果没有结构化来源，不得把 text hint 当 executable family。
- `interrupt` / `immediate`：当前 order table 有 family，但不代表有 TBGD 真实 queue window source。
- 部分 `insert_ability`：resolution 可指向 standalone ability graph 或 ability phase，但 runner 是否能执行 standalone ability graph 需要逐条 admission。
- 部分 `extra_turn`：只有 extra turn lifecycle source、resolution、window policy 都 admitted 时才 executable。

如果某项没有真实来源，正确验收是：结构化扫描证明来源缺口，runtime 不会从伪来源产生 mutation，报告中把它列为 coverage gap。不能为了勾 `P1-5-DONE` 写 synthetic queue mutation。

## 1. 非目标

P1-5 不做以下内容：

- 不做敌方 AI。敌方是否使用某个技能由外部推演器或 scenario command 输入决定；core 只暴露候选和校验。
- 不做完整分支搜索器。P1-5 只暴露 mandatory/selectable/conditional/blocked 边界。
- 不一次性实现全角色、全怪物、全光锥、全遗器的追击、反击或插队机制。
- 不用 TextMap、技能文本、角色名、怪物名、固定技能 ID、固定文件名、固定 hash、观测伤害决定 runtime 规则。
- 不把 `QUEUE_WINDOW_FAMILY_ORDER` 伪装成 TBGD 来源。它可以是 engine scheduling convention，但必须在 settlement/source audit 中区分。
- 不把 `discovered_only`、`audit_only`、`blocked`、text hint、placeholder 降成 executable queue item。
- 不为旧 v7、旧 model pack、旧 CLI 或旧 JSON 做兼容。
- 不在 P1-5 补齐 P1-6 才该解决的复杂目标排序、随机 target、adjacent target、unique entity、servant target。
- 不在 P1-5 补齐 P1-7 才该统一的随机队列选择；若当前需要随机顺序但无 RNG ledger，必须 blocked。
- 不靠 UI 测试台实现规则。`simulator_v8_ui/` 只能展示 scenario、审计和可视化。

## 2. 核心术语和边界

### 2.1 Event window 与 queue window

P1-5 必须区分两类窗口：

- **event window**
  - 事件发生时点，例如 battle start、turn start、after damage、after kill、after action、turn end、wave end。
  - 它回答“什么事件触发了 callback / queue intent”。

- **queue window**
  - 入队后的调度窗口，例如 follow_up、counter、ultimate、extra_turn、insert_action、insert_ability、assistant。
  - 它回答“这个 queue entry 何时、按什么优先级、是否需要外部选择来 drain”。

不能把 callback event 名称直接当作 queue family。`after kill` 触发的可能是 extra turn，也可能是 follow-up、resource gain 或普通状态处理。

### 2.2 IR 层对象

- `QueueIntentIR`
  - 表示 TBGD task 想插入行动或能力。
  - 必须保留 opcode、queue_kind、actor alias、target alias、priority source、abort policy、source trace、coverage status。

- `QueueResolutionIR`
  - 表示 queue intent 如何解析到 action、ability graph、ability phase 或 action set。
  - 没有 resolution 或 resolution blocked 时不能 drain。

- `QueuePriorityIR`
  - 表示 priority key 到数值的来源。
  - priority 表存在不等于 family 语义存在。

- `QueueWindowIR`
  - 表示 queue intent 的 window family、priority、window policy 和 admission。
  - 它是 P1-5 的核心来源对象之一。

- `QueueLifecyclePolicyIR`
  - 表示 extra turn 等特殊窗口对自然 turn end、duration tick、lifecycle 的影响。
  - 缺 lifecycle policy 时，extra turn 不能假执行。

- `ExtraActionPolicyIR`
  - 表示 extra turn 的 action selection kind、允许 action kind、fixed action ref 或 route choice。
  - route choice 必须暴露给外部推演器。

### 2.3 Runtime 层对象

- `QueueEntry`
  - 表示已经入队的 pending item。
  - 必须包含 id、queue name/kind、intent id、actor、action/ability ref、target ids、priority、source trace、window id/family/policy、target resolution、status、drain status。

- `QueueWindowPlan`
  - 表示某个 queue entry 的 window admission 结果。
  - 必须能说明 ok/blocked、window family、priority、target resolution、source trace。

- `QueueDrainPlan`
  - 表示 scheduler 下一次可 drain 或 blocked 的队列计划。
  - 必须能解释 resolved kind、drain order、resolved action id/level、blocked reason、queue window。

- `SelectableWindow`
  - 表示推演器可选择的窗口。
  - 第一阶段至少要覆盖 manual ultimate 和 route/source selected extra turn。

### 2.4 mandatory / selectable / conditional

P1-5 必须形成稳定分类：

- **mandatory queue**
  - 入队后，只要 actor/target/resource/control/lifecycle 仍合法，就必须在自然行动推进前 drain。
  - 推演器不能跳过。
  - 例：source-admitted follow-up/counter/insert ability，具体要以真实来源为准。

- **selectable queue**
  - 入队或窗口打开后，推演器可以选择执行或不执行，或选择 action/target。
  - 例：manual ultimate；部分 extra turn route choice。
  - scheduler 不能在缺外部 command 时擅自执行。

- **conditional queue**
  - 只有条件满足才入队或 drain。
  - 条件不可执行、payload 缺失、source 不足时 blocked/process-only，state unchanged。

分类必须写入 action availability / scheduler / settlement 的可观测输出，不能只存在于内部 if 分支。

### 2.5 source 与 engine convention

P1-5 允许存在 engine scheduling convention，例如：

- 同一窗口里按 priority value 排序。
- 同 priority 时按 drain order / entry id 稳定排序。
- 为了 replay 固定 tie-breaker。
- 在没有敌方 AI 的前提下，scheduler 只暴露候选，不自行选择普通行动。

但是 convention 不能伪装成 TBGD source。settlement/source audit 中必须区分：

- `queue_intent_source`
- `queue_resolution_source`
- `queue_priority_source`
- `queue_window_source`
- `queue_lifecycle_policy_source`
- `engine_scheduling_convention`

## 3. 总体实现原则

### 3.1 Admission 先于 enqueue，enqueue 先于 drain

任何 queue mutation 都必须满足：

```text
executable callback task
-> executable QueueIntentIR
-> executable QueueWindowIR
-> ok target resolution
-> queue_enqueue mutation
-> later QueueDrainPlan
-> queue_dequeue mutation + optional child action transition
```

blocked/audit-only/discovered-only/source gap 只能产生 process-only settlement，不能入队。

### 3.2 queue drain 必须 replayable

队列 drain 至少要能 replay：

```text
before snapshot
+ action input / external command if any
+ Canonical IR / RuleBook
+ queue entries
+ QueueDrainPlan
+ mutations
== after snapshot
```

如果 queue drain 执行了 child action，父 transition 必须记录 child transition 或足够的 parent/child source metadata。

### 3.3 外部推演器视图必须稳定

`ActionAvailabilitySystem.view(state)` 或等价入口必须能告诉推演器：

- 当前自然行动 actor 是谁。
- 当前是否有 pending mandatory queue。
- 当前是否有 selectable window。
- 当前 selectable window 的 actor、queue entry、action/target/resource preflight。
- 当前 blocked queue 的原因和 source trace。
- 当前是否需要先 drain queue 才能推进自然 turn。

不能让推演器只能通过执行失败来猜测有队列待结算。

### 3.4 状态、生命周期、队列取消必须一致

actor defeated/removed、target defeated/removed、control gating、wave transition、summon removal 都可能影响 pending queue。P1-5 要至少定义：

- actor 不存在或不可行动时 queue blocked/cancelled。
- target 不存在或不可选时 queue blocked/cancelled。
- removed unit 不再执行 pending queue。
- defeated target 不应被 pending queue 默认攻击。
- cancel 是 mutation 还是 process-only skipped，必须根据队列是否从 state 中移除明确表达。

### 3.5 结构化选样优先

P1-5 主验证必须用结构化谓词选择样例，例如：

- `QueueIntentIR.opcode`
- `QueueIntentIR.coverage_status`
- `QueueWindowIR.window_family`
- `QueueWindowIR.coverage_status`
- `QueueResolutionIR.resolved_kind`
- `QueuePriorityIR.priority_table`
- `QueueLifecyclePolicyIR.coverage_status`
- `ExtraActionPolicyIR.action_selection_kind`

禁止用角色名、怪物名、固定技能 ID、固定 action id、固定文件名、固定 hash 或旧模拟器输出作为主样例选择条件。旧角色回归可以保留，但不能替代 P1-5 主验证。

## 4. 建议代码落点

实际实现 agent 应先阅读当前代码再动手。优先落点：

- `systems/queue.py`
  - `QueueEntry`
  - `QueueWindowPlan`
  - `QueueDrainPlan`
  - `QUEUE_WINDOW_FAMILY_ORDER`
  - `QueueTargetResolver`
  - `plan_next_drain`
  - `_queue_window_plan`
  - `_resolve_action_candidate`
  - `enqueue`
  - `dequeue`

- `systems/scheduler.py`
  - `CombatScheduler.step`
  - `_try_queue_drain`
  - `_drain_queue_action`
  - `_queue_action_preflight_reason`
  - `_queue_action_command_from_plan`
  - `_pending_turn_end_mutation`
  - `_complete_pending_turn_end`
  - `select_next_queue_drain_plan`
  - `queue_plan_requires_external_command`
  - `enqueue_manual_ultimate`

- `systems/status_callbacks.py`
  - `_execute_queue_intents`
  - `_precheck_selected_queue_group`
  - `_blocked_queue_intents`
  - `_queue_insert_precheck_blocked`

- `systems/action_availability.py`
  - `ActionAvailabilityView`
  - `SelectableWindow`
  - `_selectable_windows`
  - queue-derived action choices / blocked reasons

- `systems/unit_lifecycle.py`
  - `can_act`
  - `can_target`
  - defeated/removed gates

- `systems/status.py`
  - `status_control_gate_for_actor`
  - control gating interaction with queue drain

- `rules/ir.py`
  - queue IR dataclasses listed above

- `rules/rulebook.py`
  - queue lookup methods
  - queue windows/resolutions/lifecycle policies/action policies indexing

- `tbgd/lowering.py`
  - queue intent/window/resolution/lifecycle/action policy lowering
  - source/admission/discovery output only，runtime 不读 raw TBGD

- `tools/`
  - 新增 `validate_p1_5_queue_window_system.py`
  - 必要时扩展旧验证，但不要用旧验证替代 P1-5 主验证

- `live_validation_reports/`
  - 新增 P1-5 阶段报告

不建议一开始新增大抽象。优先把现有 IR/runtime dataclass 的语义补齐；只有当 mandatory/selectable/conditional、cancel policy、source audit 重复到影响清晰度时，再抽小 dataclass 或 helper。

## 5. 内部闸门

P1-5 应按内部闸门推进。每个闸门都要能独立验证，不能最后一次性补验证。

```text
Gate A: queue/window 当前实现和来源矩阵审计
Gate B: event window 与 queue window 术语、字段和 source/convention 边界
Gate C: QueueEntry / QueueDrainPlan / settlement / replay 契约
Gate D: scheduler mandatory drain、pending turn end、natural turn 关系
Gate E: selectable window 与 external command 契约
Gate F: family 语义，按 executable/source_gap_blocked/implementation_missing 分类
Gate G: actor/target death/remove/control 对 pending queue 的取消或 blocked 策略
Gate H: source audit、negative validation、回归验证和阶段报告
```

Gate A-H 的验收必须按三态判断：有真实来源的机制必须做到 executable；没有真实来源的机制必须做到 `source_gap_blocked`，并用结构化扫描和 negative validation 证明没有伪 mutation。

## 6. 详细任务清单

### P1-5.1 审查 queue/window 当前实现

- 目标：产出当前 queue/window 系统真实能力边界，区分 executable、partial、blocked、discovered-only 和 engine convention。
- 要做：审查 `systems/queue.py`、`systems/scheduler.py`、`systems/status_callbacks.py`、`systems/action_availability.py`、`rules/ir.py`、`rules/rulebook.py`、`tbgd/lowering.py` 和旧 queue 验证。列出 QueueIntent/Resolution/Priority/Window/Lifecycle/ExtraActionPolicy 的来源、字段、runtime 使用点和验证覆盖。
- 验收结果：P1-5 阶段报告中有 `current_queue_scope` 和 `queue_source_matrix`；明确哪些 queue family 有真实 executable 来源，哪些只是 text hint、engine convention 或 source gap；新增验证断言 blocked/audit-only/discovered-only 不入队。
- 禁止：不能只跑旧验证；不能只凭 `QUEUE_WINDOW_FAMILY_ORDER` 判断机制完成；不能按角色名或固定技能 ID 选主样例。

### P1-5.2 定义 event window 和 queue drain window

- 目标：统一 battle start、wave start、turn start、before action、before hit、after hit、after damage、after break、after kill、after action、turn end、wave end、ultimate interrupt、queue drain 等窗口命名和顺序边界。
- 要做：建立一个 P1-5 范围内的 window taxonomy。明确哪些是 event dispatch window，哪些是 queue window family，哪些暂时只是 reserved/blocked。把 `GameEvent.window`、status callback event、scheduler step、queue window plan 的关系写清楚。
- 验收结果：阶段报告和 validation 输出中能看到 `event_window_matrix`；已有 after kill / after action / pending turn end 路径归类明确；未知 event window 不会 fallback 到默认 queue family。
- 禁止：不能把 callback event 名称直接映射成 queue family；不能为缺 payload 的事件构造默认目标或默认 actor。

### P1-5.3 定义 queue family 优先级并区分来源与 convention

- 目标：让同一 drain 时刻的 queue family 排序稳定、可审计，并明确哪些顺序来自 TBGD priority，哪些只是 runtime scheduling convention。
- 要做：审查 `QUEUE_WINDOW_FAMILY_ORDER`、`QueuePriorityIR` 和 `_queue_plan_sort_key`。保留或调整 family order 时，必须给每个 family 输出 `ordering_source_kind`，例如 `tbgd_priority_table`、`queue_window_policy`、`engine_scheduling_convention`、`source_gap_blocked`。同 priority tie-breaker 必须稳定。
- 验收结果：validation 覆盖至少两个 admitted queue entry 的排序；排序 settlement 或 drain plan 中能解释 priority key/value、family order 和 tie-breaker；source audit 不把 convention 当 TBGD source。
- 禁止：不能因为某个角色样例符合预期就固定 family 顺序；不能用 dict/list 当前遍历顺序作为 tie-breaker。

### P1-5.4 定义 mandatory queue

- 目标：让强制队列在自然行动推进前被 scheduler drain，并让推演器知道它不能跳过。
- 要做：定义 `control="mandatory"` 或等价字段/输出；审查 `CombatScheduler.step` 中 queue drain 优先级；确保 admitted mandatory queue 会阻止 natural turn advance 和 pending turn end 之前的错误推进。
- 验收结果：当 pending admitted mandatory queue 存在时，scheduler 第一步返回 queue drain transition；action availability 暴露 pending mandatory queue；无外部 command 时不推进自然 actor。
- 禁止：不能让 mandatory queue 因缺 command 被当 selectable；不能让自然 turn 先于 mandatory drain。

### P1-5.5 定义 selectable queue

- 目标：让终结技插队和 route/source selected extra turn 这类选择窗口稳定暴露给外部推演器。
- 要做：审查 `queue_plan_requires_external_command` 和 `ActionAvailabilitySystem._selectable_windows`。为 selectable window 明确 actor、entry id、queue name、window kind、drain plan、resolution、resource preflight、target policy、source trace。scheduler 缺 command 时应 process-only blocked 或等待，而不是擅自执行。
- 验收结果：manual ultimate 和 route choice extra turn 至少一种真实路径能在 action availability 中出现 selectable window；提交匹配 command 可 drain；不匹配 command state unchanged 且有 blocked settlement。
- 禁止：不能由 core 自动选择终结技；不能让 selectable window 靠 UI 层私有逻辑存在。

### P1-5.6 定义 conditional queue

- 目标：让条件触发的 queue 只在条件可执行且为真时入队；条件缺失或不可执行时不产生 queue mutation。
- 要做：审查 `PredicateTaskList`、`Retarget`、`_precheck_selected_queue_group`、`SameTagInsertUnusedCount` 和 trigger event payload。将 condition result、selected child ids、precheck result 写入 settlement。
- 验收结果：condition true 时 admitted queue 正常入队；condition false 时 no mutation 且 process-only record；condition unsupported/source missing 时 blocked/state unchanged；precheck blocked 时不会部分入队。
- 禁止：不能把 condition missing 当 true；不能让 predicate parent blocked 但 child queue 仍入队。

### P1-5.7 补齐 queue item 字段和状态契约

- 目标：确保每个 queue item 都有足够字段支持 replay、取消、source audit 和推演器展示。
- 要做：审查 `QueueEntry` 当前字段是否足够表达 id、family、priority、actor、owner/source、action/ability、target expression/resolution、source trace、expiration、cancel。缺字段时优先以通用 metadata/policy 补齐；如果需要新增字段，必须走 dataclass/to_json/replay/validation 全链路。
- 验收结果：validation 能从 queue enqueue mutation 找到 entry，再找 intent/window/resolution/source；queue entry 中 actor、target、priority、window、source trace 不缺失；cancel/expiration 语义若未有真实来源必须显式 blocked。
- 禁止：不能把 owner/source 混成 actor；不能用 action_or_ability_ref 的字符串猜 resolved action；不能只在 settlement 里保存字段而不进 mutation metadata。

### P1-5.8 实现 queue drain process event

- 目标：queue drain transition 不只表现为 dequeue + child action，还要有清晰 process event/settlement 表示 drain 开始、执行、跳过、blocked 或结束。
- 要做：审查 `_try_queue_drain`、`_drain_queue_action` 的 events/records。补齐 `queue.drain.begin`、`queue.drain.end`、`queue.drain.blocked`、`queue.drain.skipped` 或等价事件，payload 包含 drain plan、queue entry、window plan、resolution、external command。
- 验收结果：成功 drain 和 blocked drain 都有 process-only settlement；dequeue mutation 可从 settlement 反查；child action transition 有 parent queue metadata。
- 禁止：不能只靠 mutation path 推断 drain；不能从日志事后反推 settlement。

### P1-5.9 实现 follow-up 最小顺序

- 目标：在存在真实 follow-up 来源时，让 follow-up queue 进入 admitted family、稳定排序并可 drain；若只有 text hint 或无来源，则记录 source gap。
- 要做：结构化扫描 `QueueWindowIR.window_family == "follow_up"` 或可证明的 follow-up source。若当前没有 executable source，保留 runtime blocked/convention，不写正例 mutation。若有来源，接入 mandatory queue drain，并验证 target、source、priority、settlement。
- 验收结果：有真实来源时 follow-up 在同窗口排序稳定且可 replay；无真实来源时 validation 输出 `source_gap_blocked`，并证明 text hint 不会产生 executable queue。
- 禁止：不能用 ability name 包含 follow/追击 当 runtime 来源；不能固定某个角色卡作为唯一主证据。

### P1-5.10 实现 counter 最小顺序

- 目标：在存在真实 counter 来源时，让反击 queue 进入 admitted family、稳定排序并可 drain；若只有 text hint 或无来源，则记录 source gap。
- 要做：结构化扫描 `QueueWindowIR.window_family == "counter"` 或可证明的 counter source。审查 after hit/after damage payload 是否包含 attacker/defender/target。若来源或 payload 不足，blocked/state unchanged。
- 验收结果：有真实来源时 counter 相对 follow-up/extra_turn/ultimate 的顺序被验证；无真实来源时 validation 输出 coverage gap；缺 attacker/target payload 不入队。
- 禁止：不能用状态/技能文本判断反击；不能缺攻击者时默认攻击当前目标。

### P1-5.11 实现 extra turn 与 timeline 的关系

- 目标：让 source-admitted extra turn 不推进自然 AV，不提前结束原 turn，并正确处理 action lifecycle tick。
- 要做：审查 `QueueLifecyclePolicyIR`、`ExtraActionPolicyIR`、`_pending_turn_end_mutation`、`_complete_pending_turn_end`、`extra_turn.begin/end` events。确保 extra turn drain 前后与 natural turn end、ActionPhaseEnd、pending turn end 的顺序稳定。
- 验收结果：extra turn 可执行路径中，scheduler 先 drain extra turn，再完成 deferred turn end；duration tick 不重复、不漏；action availability 能暴露 route choice；source audit 指向 extra turn source/lifecycle policy。
- 禁止：不能把 extra turn 当普通 timeline turn；不能缺 lifecycle policy 时执行 extra turn。

### P1-5.12 实现 insert action 最小语义或 blocked 策略

- 目标：让 `TurnInsertAction` 在可解析 action selection 时进入可执行路径，否则明确 blocked。
- 要做：审查 `PrepareAbilityName`、`SkillType`、`SkillIndex` lowering；确认 resolution 能映射到 combatant action set 或 action definition；执行时校验 actor、target、resource、control。对 internal continuation 或无法定位 action 的来源保持 blocked。
- 验收结果：有真实 executable insert action 时可 enqueue/drain/replay；缺 action id、level、target、action event、resource policy 时 blocked/state unchanged；settlement 能解释 `resolved_kind`。
- 禁止：不能把 `PrepareAbilityName` 直接当 action id；不能用 actor template 的固定 skill index 旁路 RuleBook resolution。

### P1-5.13 实现 insert ability 最小语义或 blocked 策略

- 目标：让 `TurnInsertAbility` 在 resolution 指向可执行 ability graph/action segment 时执行，否则保持 blocked。
- 要做：审查 `QueueResolutionIR.resolved_kind`：standalone ability graph、ability phase、ambiguous graph、missing ability。定义第一阶段可执行 runner 范围；无法通过现有 AbilityTaskSystem 安全执行的 resolution 必须 blocked/process-only。
- 验收结果：有真实 executable insert ability source 时可 drain，并生成 child effect/status/damage transition 或明确 process event；无 runner 或 ambiguous graph 时 blocked，不 dequeue 或按 cancel policy 处理。
- 禁止：不能把 ability name 字符串当 action id 执行；不能复活旧 adapter 或 legacy effects。

### P1-5.14 实现 assistant family 最小顺序

- 目标：对 assistant family 做真实来源审计；若当前 `TurnInsertAssistantAbility` 仍无 admitted runner，则保持 source gap/blocked，不合成正例。
- 要做：结构化统计 `TurnInsertAssistantAbility` intent、window、resolution 的 coverage_status 和 blocked_reason。若找到真实可执行链路，定义 assistant 是否需要独立 actor、owner actor、ability runner 和 target resolution；否则在 report/validation 中标 `source_gap_blocked`。
- 验收结果：当前无来源时，assistant queue 不会 executable 入队；若未来有来源，assistant drain 顺序、owner/source、child ability、settlement、source audit 完整。
- 禁止：不能因为 P1-3 有 assistant 分类就自动允许 P1-5 assistant queue；不能用文件路径含 Assistant 当 runtime source。

### P1-5.15 实现 ultimate selectable window 暴露

- 目标：让手动终结技插队作为 selectable window 被推演器稳定看到和选择。
- 要做：审查 `enqueue_manual_ultimate`、manual ultimate queue entry、energy preflight、target resolution、`queue_plan_requires_external_command`、action availability。明确 ultimate window 不自动 drain，必须匹配外部 command。
- 验收结果：能构造 actor energy 满的 manual ultimate selectable window；action availability 输出 window；匹配 command drain 并扣能量；actor/action/target/energy 不匹配时 blocked/state unchanged。
- 禁止：不能在无 command 时自动释放终结技；不能绕过 ultimate energy cost rule。

### P1-5.16 实现 actor death/remove 时 pending queue 处理

- 目标：pending queue 的 actor 或 target defeated/removed 后，系统有稳定的 cancel/blocked/skipped 语义。
- 要做：使用 `UnitLifecycleSystem.can_act/can_target` 和 P1-1/P1-2/P1-3 的 remove/wave transition 语义。定义：actor removed 是否 dequeue+cancel mutation，actor defeated 是否 blocked，target removed 是否 retarget 或 blocked。retarget 缺真实来源时 blocked。
- 验收结果：actor removed queue 不会执行 child action；target removed queue 不会攻击无效目标；state 中 pending queue 的去留有 mutation 或 process-only blocked record；source audit 可解释。
- 禁止：不能让 removed actor 执行 queue；不能默认 retarget 到随机敌人；不能静默丢弃 queue entry。

### P1-5.17 实现 unknown queue family blocked

- 目标：未知 family、text-only hint、缺 window、缺 priority、缺 lifecycle policy 都不能 executable。
- 要做：审查 `_queue_window_family`、`_queue_window_plan`、`_queue_window_policy`。补齐 validation，证明 unknown/assistant/text hint/source blocked 的 queue intent 不入队或不 drain。
- 验收结果：unknown family 的 drain plan `ok=false`，blocked_reason 明确；state unchanged；settlement/source audit 不报告 mutation。
- 禁止：不能 fallback 到 `insert_action` 或 `immediate`；不能按 priority key 的文本 hint 直接 admitted。

### P1-5.18 增加 follow-up order 验证

- 目标：证明 follow-up ordering 在有真实来源时可执行，无真实来源时被诚实记录为 source gap。
- 要做：在 `validate_p1_5_queue_window_system.py` 中结构化选择 `window_family == "follow_up"` 的 executable 样例。若没有，输出 `source_gap_blocked`，并验证 text hint/discovered-only 不产生 mutation。
- 验收结果：验证输出包含 `follow_up_order` case，结果三态明确；有正例时检查排序、drain、replay、source audit。
- 禁止：不能固定某个角色名或技能名作为 follow-up 主样例。

### P1-5.19 增加 counter order 验证

- 目标：证明 counter ordering 在有真实来源时可执行，无真实来源时被诚实记录为 source gap。
- 要做：结构化选择 `window_family == "counter"` 的 executable 样例；检查 trigger payload 中 attacker/defender/target 是否可审计。无来源则输出 source gap。
- 验收结果：验证输出包含 `counter_order` case；有正例时排序和 source audit 通过；无来源时 no mutation。
- 禁止：不能用受击文本文案或旧模拟器结果推断 counter。

### P1-5.20 增加 after kill callback 验证

- 目标：证明击杀事件可以触发 queue intent，并且 queue source、kill attribution、pending turn end 顺序正确。
- 要做：复用 P1-4 damage/status callback 和旧 v0_255/v0_256/v0_265 的 kill attribution 思路，但主样例按结构化谓词选择：source frame can continue、after kill event、queue intent executable、window executable。检查 lethal damage 后的 queue enqueue、drain、child source。
- 验收结果：after kill 触发 queue 的正例或 source gap 明确；有正例时 queue parent 指向具体 damage source/kill event；无来源时只记录 process-only gap。
- 禁止：不能把 actor kill 后固定给某角色额外回合；不能只检查最终行动次数。

### P1-5.21 增加 extra turn order 验证

- 目标：证明 extra turn 在 queue drain、ultimate/selectable、pending turn end、timeline 之间的顺序稳定。
- 要做：选择 `window_family == "extra_turn"` 且 lifecycle/action policy executable 的样例。执行 action 后触发 extra turn，检查 scheduler 先 drain extra turn，再完成 pending turn end；如果需要 route command，测试缺 command blocked 与匹配 command success。
- 验收结果：验证输出包含 extra turn begin/end event、dequeue mutation、child action transition、pending turn end clear；replay/source audit 通过。
- 禁止：不能缺 lifecycle source 时用旧 extra turn smoke 正例通过。

### P1-5.22 增加 ultimate selectable window 验证

- 目标：证明终结技插队是 selectable，不是 mandatory。
- 要做：构造或选择 actor energy ready 的 manual ultimate queue entry；检查 action availability 的 selectable window；执行 matching command 和 mismatch command。
- 验收结果：无 command 时不自动 drain；matching command 成功扣能量并执行；mismatch command blocked/state unchanged；records 包含 energy rule、queue window、resolution。
- 禁止：不能用普通 action availability 代替 ultimate window 验证。

### P1-5.23 增加 assistant family order 验证

- 目标：证明 assistant family 当前真实状态，不因为 checklist 要求而伪造 executable。
- 要做：结构化扫描 `TurnInsertAssistantAbility`、`window_family == "assistant"`、assistant window blocked reason。若无 admitted source，输出 `source_gap_blocked` 并验证 no mutation。若未来 admitted，则验证 assistant 与其他 family 的排序和 owner/source。
- 验收结果：当前预期大概率是 source gap/blocked；validation 必须把 gap 作为 ok 的诚实结果，而不是失败或 synthetic pass。
- 禁止：不能把 P1-3 assistant unit/spec 当作 P1-5 assistant queue 正例。

### P1-5.24 增加 actor removed queue cancel/blocked 验证

- 目标：证明 pending queue 在 actor/target lifecycle 改变后不会执行非法动作。
- 要做：准备 admitted queue entry 后，通过 UnitRemove/defeat/wave transition 改变 actor 或 target 状态；再让 scheduler 尝试 drain。覆盖 actor removed、actor defeated、target removed、target defeated 至少两类。
- 验收结果：非法 queue 不产生 child action mutation；有 cancel/dequeue mutation 或 blocked process record；state 中 pending queue 处理符合 policy；source audit 通过。
- 禁止：不能用异常退出当验证通过；不能默默忽略 pending queue。

### P1-5.25 增加 unknown family blocked 验证

- 目标：证明未知 family、text hint、缺 priority/window/source 不会 fallback 执行。
- 要做：选择或构造 RuleBook 中 coverage_status 为 blocked/discovered-only 的 queue intent/window；或使用真实 text hint source。执行 status callback/scheduler path，检查 state unchanged。
- 验收结果：blocked reason 包含 `queue_window_family_unknown`、`queue_window_family_not_admitted`、`queue_priority_not_admitted` 或具体来源缺口；无 enqueue/drain mutation。
- 禁止：不能用 runtime synthetic unknown entry 绕过 IR admission；不能让 unknown 按最低优先级执行。

### P1-5.26 更新阶段报告

- 目标：把 P1-5 做到哪里、可信范围、blocked/source gap 范围和剩余完整复刻差距写清楚。
- 要做：新增 `live_validation_reports/v8_p1_5_queue_window_system_checkpoint.md` 或带版本后缀的阶段报告；更新 `FIRST_PHASE_TASK_CHECKLIST.md`；列出验证命令、source audit、replay、negative validation、P1-0 到 P1-4 回归结果。
- 验收结果：报告能回答当前最小可用战斗纵切还缺什么、推演器目前能看到哪些 queue/window 边界、距离完整复刻还缺哪些 queue family 和来源。
- 禁止：不能只写“验证通过”；必须说明通用性、扩展性、source/convention 分离和红线审查结果。

## 7. 新增验证矩阵

建议新增：

```text
python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_window_system
```

该验证至少包含：

- queue current scope audit。
- QueueIntentIR / QueueResolutionIR / QueueWindowIR / QueueLifecyclePolicyIR / ExtraActionPolicyIR 三态统计。
- blocked/audit-only/discovered-only queue intent 不入队。
- text-only queue window hint 不 executable。
- family priority / ordering source matrix。
- mandatory queue drain before natural turn。
- pending queue defers natural turn end。
- queue drain process event / settlement / mutation trace。
- selectable ultimate window。
- selectable extra turn route choice，若真实来源存在；否则 source gap。
- conditional queue true/false/unsupported/precheck blocked。
- follow-up order，有真实来源时 positive；否则 source gap。
- counter order，有真实来源时 positive；否则 source gap。
- after kill callback queue enqueue/drain，有真实来源时 positive；否则 source gap。
- extra turn timeline/pending turn end/lifecycle。
- insert action executable 或 blocked。
- insert ability executable 或 blocked。
- assistant family executable 或 source gap blocked；当前不得合成正例。
- actor removed / defeated pending queue cancel 或 blocked。
- target removed / defeated pending queue cancel 或 blocked。
- unknown family blocked/state unchanged。
- manual ultimate command mismatch blocked/state unchanged。
- mutation -> settlement -> source trace -> IR source audit。
- before snapshot + queue command + RuleBook + RNG/choice events + mutations == after snapshot。

验证输出建议包含：

```text
validation_summary_p1_5_queue_window_system.json
queue_source_matrix_p1_5.json
queue_window_order_matrix_p1_5.json
queue_mandatory_drain_case_p1_5.json
queue_selectable_ultimate_case_p1_5.json
queue_extra_turn_case_p1_5.json
queue_family_source_gaps_p1_5.json
queue_actor_removed_case_p1_5.json
queue_unknown_family_blocked_case_p1_5.json
```

主验证的 selection policy 必须写入输出：

```json
{
  "mode": "structured_predicate",
  "fixed_entity_skill_file_or_observation_used": false,
  "predicates": [
    "QueueIntentIR.coverage_status",
    "QueueWindowIR.window_family",
    "QueueWindowIR.coverage_status",
    "QueueResolutionIR.resolved_kind",
    "QueueLifecyclePolicyIR.coverage_status",
    "ExtraActionPolicyIR.action_selection_kind"
  ]
}
```

## 8. 回归命令

P1-5 完成后建议运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_unit_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_queue_window_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_241 --output-dir /tmp/hsr_v8_queue_v0_241
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_243 --output-dir /tmp/hsr_v8_scheduler_v0_243
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_250 --output-dir /tmp/hsr_v8_extra_turn_v0_250
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_255 --output-dir /tmp/hsr_v8_kill_attr_v0_255
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_256 --output-dir /tmp/hsr_v8_damage_source_v0_256
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_265 --output-dir /tmp/hsr_v8_card_contract_v0_265
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_266 --output-dir /tmp/hsr_v8_extra_turn_priority_v0_266
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
git diff --check
```

如果某个旧验证因 P1-5 收紧来源边界而失败，优先升级验证输入到真实来源链路；禁止为了旧 smoke 保留假执行路径。

## 9. 完成口径

P1-5 的完成口径拆成两层，避免把“来源缺口”误判成“代码未完成”，也避免把 synthetic 正例误判成真实完成。

### 9.1 队列/窗口底座验收，带来源缺口

满足以下条件时，可以给出“P1-5 队列/窗口底座已验收，带来源缺口”的工程结论，并继续规划后续阶段：

- QueueIntent/Resolution/Priority/Window/Lifecycle/ExtraActionPolicy 的 source matrix 已输出。
- 当前 RuleBook / Canonical IR 有真实来源的 queue family，都有 positive executable validation。
- 当前 TBGD / IR 没有真实来源的 family 或机制，必须有结构化 discovery/coverage gap 证据，并且验证证明不会产生 synthetic mutation。
- mandatory/selectable/conditional 的 runtime 行为和 action availability 输出稳定。
- scheduler 能在 natural turn 之前 drain mandatory queue。
- selectable window 缺 command 时不会擅自执行。
- queue drain、blocked、skipped、cancel 都有 settlement/process event。
- queue enqueue/dequeue/cancel 等状态变化都通过 `Mutation` 表达。
- actor/target defeated/removed/control gating 不会产生非法 child action。
- 所有 mutation 都能追到 settlement，再追到 QueueEntry/source trace，再追到 Canonical IR/TBGD source 或明确 engine convention。
- negative validation 证明缺 source、缺 target、unsupported family、missing resolution、missing lifecycle、missing command 不会产生 mutation。
- P1-0 到 P1-4 的核心验证仍通过。
- 阶段报告明确说明当前可信范围、source gap 和剩余完整复刻差距。

这个结论不等同于所有 checklist 子项都有真实正例。

### 9.2 P1-5-DONE 全正例完成

```text
P1-5-DONE 队列顺序确定，mandatory/selectable 可区分，queue drain 可 replay，推演器能知道当前是否必须先结算队列。
```

如果 `P1-5-DONE` 被定义为“所有列出的 family 和窗口都有真实正例 executable”，则必须等 follow-up、counter、assistant、insert ability 等来源缺口都得到真实 TBGD / IR 来源并通过正例验证后才能勾选。当前更现实的第一阶段目标是先达到 `P1-5-SUBSTRATE-ACCEPTED`。

## 10. 后续影响

P1-5 完成后，后续阶段可以复用：

- P1-6 target：queue item 的 target expression、sort/fetch/random/retarget 会有稳定调用点。
- P1-7 RNG：queue 随机顺序、随机目标、随机触发可以纳入统一 branch ledger。
- P1-8 setup/route：推演器可以基于 action availability 和 selectable window 做路线搜索。
- wave/summon/assistant 扩面：召唤物和 assistant 行动不需要各自重写调度。
- 角色/怪物卡扩面：追击、反击、额外回合、插队能力都进入通用 queue/window 系统。

P1-5 做完后仍不会得到“完整复刻全部队列机制”的模拟器。它的价值是把队列、窗口、选择性、调度、取消和来源审计的底层契约做正，使后续扩面不再把每个角色或怪物的后续行动写成 core 特判。
