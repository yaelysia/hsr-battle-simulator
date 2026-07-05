# P1-0 动作权责边界详细任务计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-0 动作权责边界` 的实现级拆解。目标是让后续实现 agent 可以只围绕本文件完成 P1-0，不需要重新解释项目方向。

## 0. 给新实现线程的背景

本节用于让没有前序对话上下文的新线程理解项目来龙去脉。实现 P1-0 前，应先读完本节，再进入后面的任务清单。

### 0.1 这个项目要做什么

本工作区目标是构建一个严谨的《崩坏：星穹铁道》战斗模拟器。

最终成品不是一个只会播放固定流程的战斗复现器，而是一个可用于战斗推演和搜索的规则内核：

```text
给定敌我配置、战斗环境、初始状态、动作选择和随机分支
=> 产出尽可能与游戏一致的完整战斗过程、状态快照、结算和来源审计
```

这个目标决定了几个核心要求：

- 每次动作必须产生完整 `BattleTransition`。
- 每次状态变化必须通过 `Mutation` 表达。
- transition 必须可 replay。
- 规则执行必须可追溯来源。
- blocked、audit_only、discovered_only 机制不能伪执行。
- 所有随机和选择最终都要能被外部推演器枚举、记录和重放。

### 0.2 当前主线是什么

当前主线是 v8 clean core：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/
```

旧版 v7 曾经做过大量工程，但 v8 不是 v7 的兼容层。v7 只能作为参考和对照，不能作为 v8 runtime 依赖。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR。runtime 不能直接读取：

- TBGD raw schema。
- TextMap。
- 旧 v7。
- 旧 model pack。
- 技能文本解释。
- 观测伤害答案。

### 0.3 当前检查点

当前最近交接检查点是：

```text
v0_289 target expression sequence filter retarget
```

当前 v8 已经有一批底座：

- Canonical IR。
- RuleBook。
- snapshot/replay。
- settlement/source audit。
- `BattleState`、`UnitState`、`ActionCommand`、`Mutation`、`BattleTransition`。
- `CombatExecutor.execute` 动作执行入口。
- target/resource/timeline/ability/effect/status callback/queue/event dispatch 框架。
- direct、DoT、break、super-break、hp loss 等伤害纵切。
- 角色数据卡和怪物数据卡边界。
- 怪物固定序列行动候选。
- 目标表达式安全子集。
- queue family 和部分 queue drain。

但当前 v8 还缺少完整战斗闭环：

- 波次系统还没有真正 runtime 化。
- 召唤物/assistant/servant 还没有完整生命周期。
- 状态系统的叠层、刷新、概率、抵抗、驱散、tick 还不完整。
- 队列/window 语义还不够稳定。
- 目标系统还缺 sort/fetch/random/adjacent/unique/summon 等关键能力。
- 外部推演器还没有稳定动作边界。

P1-0 就是先解决最后这一点：**外部推演器到底如何知道现在能输入什么动作，以及 core 如何保证自己不替外部做决策**。

### 0.4 为什么不做敌方 AI

项目最终目标是战斗推演：从所有可能性中找到能达到目标的通关方式。

因此敌方 AI 不是目标。敌方动作应该被视为状态空间中的一种外部选择或规则候选，而不是由 core 主动策略决策。

正确边界是：

```text
core 暴露敌方可用动作候选
推演器选择敌方动作
core 验证动作是否合法
core 执行动作并输出 transition
```

错误方向是：

```text
core 根据敌方 AI 策略自动选择技能
```

这会破坏推演器枚举全部可能性的能力。

当前代码中仍存在一些历史命名，例如：

- `ActionCommand.source = "ai"`
- `enemy_ai_policy`
- `manual_route_command_or_ai_policy`

实现 P1-0 时要识别这些是历史命名债务。除非单独处理兼容，否则不要让新 API 继续扩散“AI 决策”语义。新文档、新结构、新 metadata 应使用：

- `external`
- `rule_candidate`
- `fixed_sequence_candidate`
- `selection_controller="external"`

### 0.5 P1-0 为什么排在第一阶段最前面

第一阶段总目标是“外部推演器驱动下的最小完整战斗闭环”。

后面 P1-1 到 P1-8 会陆续做：

- UnitLifecycle。
- WaveSystem。
- Summon / Assistant / Servant。
- 状态系统主体。
- Queue / Window。
- Target。
- RNG。
- 最小 BattleSetup。

这些系统都会影响“当前能不能行动”和“当前该不该先结算规则队列”。

如果不先定义动作边界，后续每个系统都容易各自发明一套输入规则：

- wave 可能自己决定下一步。
- summon 可能自己决定行动。
- queue 可能自己吞掉外部输入。
- enemy candidate 可能被误当 AI。
- ultimate window 可能被误当 mandatory queue。

P1-0 先建立一个通用的 action availability 视图，让后续系统都往这个视图扩展，而不是把选择逻辑散落到 executor、scheduler、UI、scenario 或验证脚本里。

### 0.6 P1-0 的一句话目标

P1-0 只回答一个问题：

```text
在当前 BattleState 下，外部推演器下一步能做什么，或者为什么什么都不能做？
```

这个回答必须是：

- 纯查询。
- 可 JSON 序列化。
- 不改变 state。
- 不消耗 RNG。
- 不执行动作。
- 不推进 timeline。
- 不 dequeue queue。
- 不替敌方做策略选择。

### 0.7 新线程开始时建议先读的文件

最小阅读集：

```text
hsr_v075_baseline_clean/hsr/CODEX_HANDOFF.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FORBIDDEN.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FIRST_PHASE_MINIMUM_BATTLE_LOOP_PLAN.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/FIRST_PHASE_TASK_CHECKLIST.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/P1_0_ACTION_BOUNDARY_TASK_PLAN.md
```

实现 P1-0 时重点查这些代码文件：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/model.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/scheduler.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/queue.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/enemy_action.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/target.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/resource.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/timeline.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/rulebook.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/ir.py
```

如果需要理解已有 enemy candidate 验证，读：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_v0_283.py
```

不要为了 P1-0 去扫描全量 TBGD 或旧 v7。

### 0.8 新线程的工作方式

实现线程应按以下方式推进：

1. 用 CodeGraph 查结构和调用关系。
2. 只读取 P1-0 相关文件。
3. 先新增纯查询数据结构。
4. 再接入 queue / timeline / enemy candidate / ally action set。
5. 再补 target/resource preflight。
6. 再写 validation。
7. 最后更新 report 和 checklist。

P1-0 不是一次性大重构。正确实现应该是小而稳定的新增边界，复用现有系统，避免把 scheduler/executor 复制一遍。

### 0.9 P1-0 完成后应交接什么

完成 P1-0 后，交接给后续阶段的信息至少包括：

- action availability API 名称和路径。
- 输出 JSON schema version。
- 当前支持哪些 mode。
- 当前支持哪些 choice kind。
- queue mandatory/selectable 如何表达。
- enemy fixed-sequence candidate 如何表达。
- ally action set 如何枚举。
- summon action 当前如何 blocked。
- ultimate selectable window 当前支持到什么程度。
- `ActionCommand.source="ai"` 是否仍保留，兼容策略是什么。
- 哪些 blocked 是 P1-1 到 P1-8 后续要解决的。

P1-0 的核心结论：

```text
外部推演器负责选择动作。
v8 core 负责暴露可选动作、判断输入是否合法、执行规则、输出 BattleTransition。
敌方 AI 不在 core 中实现。
```

## 1. P1-0 总目标

### 1.1 要解决的问题

当前 v8 已有：

- `ActionCommand`
- `CombatExecutor.execute`
- `CombatScheduler.step`
- queue drain
- enemy fixed-sequence candidate
- target enumeration
- resource preflight

但这些能力还没有形成一个清晰的“外部推演器动作边界”：

- 外部推演器不知道当前是否必须先结算队列。
- 外部推演器不知道当前是否可以输入普通行动。
- 敌方行动候选当前名字上仍有 `ai` 残留，容易误导成敌方 AI。
- scheduler 能执行 command，但没有稳定的纯查询接口告诉外部“现在能输入什么”。
- queue mandatory、ultimate selectable、normal external action 的边界还没有统一输出格式。

P1-0 要补的是这个边界，不是补完整战斗内容。

### 1.2 最终效果

P1-0 完成后，外部推演器应该可以按以下流程驱动 core：

```text
availability = ActionAvailabilitySystem.view(state)

if availability.mode == queued_mandatory:
    scheduler.step(state)

elif availability.mode == queued_selectable:
    推演器选择是否输入对应 queued command
    scheduler.step(state, command)

elif availability.mode == external_selectable:
    推演器从 choices 中选择 command
    scheduler.step(state, command)

elif availability.mode == blocked:
    记录 blocked reason，不产生状态 mutation
```

这里的 `ActionAvailabilitySystem` 是推荐命名，实现线程可选择等价名称，但必须提供同等能力。

### 1.3 非目标

P1-0 不做：

- 不做敌方 AI。
- 不做搜索器。
- 不做完整队列/window 重构。
- 不做完整 summon 行动语义。
- 不做完整状态控制 gating。
- 不做完整目标系统扩面。
- 不做 wave、unit lifecycle、RNG 分支。
- 不做角色/怪物/光锥/遗器内容扩面。

P1-0 只做动作输入边界和可观察性。后续 P1-1 到 P1-8 再补具体机制。

## 2. 当前代码事实

实现前应先确认这些落点。不要全项目扫，围绕这些文件展开即可。

### 2.1 `ActionCommand`

位置：

```text
simulator_v8_clean_core/core/model.py
```

当前字段：

```python
actor_id: str
action_id: str
action_level: int
target_ids: tuple[str, ...] = ()
source: Literal["manual", "ai", "queue"] = "manual"
queue_name: str | None = None
metadata: dict[str, JSONValue] = field(default_factory=dict)
```

注意：

- `source="ai"` 是历史命名债务。
- 项目目标不做敌方 AI。
- P1-0 不应新增依赖 `source="ai"` 的策略判断。
- 是否把 `"ai"` 改名为 `"external"` 属于接口兼容问题，不能在实现线程里静默破坏旧验证。

推荐做法：

- P1-0 新增的结构使用 `controller="external"`、`selection_kind="external_command"`、`actor_side="enemy"` 等明确字段。
- `ActionCommand.source` 暂时只作为兼容字段。
- 如果实现线程决定修改 `ActionCommand.source` 的 Literal，必须先确认兼容策略。

### 2.2 `CombatScheduler.step`

位置：

```text
simulator_v8_clean_core/systems/scheduler.py
```

当前行为：

- 先尝试 `_try_queue_drain`。
- 如果有 queue step，优先返回 queue drain。
- 如果有 `pending_turn_end`，先完成 turn end。
- 否则 `advance_to_next_turn`。
- 如果没有 command，只做 turn begin，并记录 `blocking_dependency="manual_route_command_or_ai_policy"`。
- 如果有 command，要求 command actor 与当前 turn actor 匹配。
- 如果 actor 是 enemy，会用 `EnemyActionSystem.next_candidate` 校验固定序列候选。
- enemy command 必须与 candidate 的 action_ref/action_level 匹配。
- enemy command target 必须满足 candidate target 约束。
- 然后调用 `CombatExecutor.execute`。

P1-0 要把这些隐含规则变成外部可查询的 view。

### 2.3 queue drain

位置：

```text
simulator_v8_clean_core/systems/queue.py
simulator_v8_clean_core/systems/scheduler.py
```

当前行为：

- `_try_queue_drain` 会遍历 `state.queues`。
- 每个 queue 使用 `QueueSystem.plan_next_drain`。
- 根据 `QUEUE_WINDOW_FAMILY_ORDER`、priority、drain_order、entry_id 选一个 plan。
- action_definition 或 extra_turn action choice 会做 preflight。
- queue drain 可生成 action command，source 为 `"queue"`。

P1-0 要做：

- 在不 dequeue、不 apply mutation 的情况下暴露当前 queue drain 状态。
- 区分 mandatory queue 和 selectable queue。
- 明确普通 external command 是否被 queue 阻塞。

### 2.4 enemy action candidate

位置：

```text
simulator_v8_clean_core/systems/enemy_action.py
```

当前行为：

- `next_candidate(state, actor_id)` 从 monster data card 的 fixed sequence 找下一步。
- 它依赖 `monster_data_card_id`、`ai_policy.admission_status`、`action_sequence`、action definition、action event、target enumeration。
- 它返回 `EnemyActionCandidate`，包含 selectable/auto targets 和 source trace。
- `command_from_candidate` 当前会生成 `source="ai"` 的 `ActionCommand`。

P1-0 要保留 fixed-sequence candidate 作为规则候选来源，但不能让它承担策略选择。

## 3. 设计原则

### 3.1 通用性

P1-0 的实现必须是通用动作边界，不允许：

- 按角色名判断。
- 按怪物名判断。
- 按 action id 固定判断。
- 按技能槽位名硬编码普攻/战技/终结技。
- 按 UI 路由或 scenario 文件名判断。
- 用 TextMap 或技能文本补规则。
- 从旧 v7 或旧 model pack 补规则。

动作集合必须来自：

- `RuleBook`
- `CharacterDataCardIR`
- `MonsterDataCardIR`
- `CombatantActionSetIR`
- `ActionDefinitionIR`
- `ActionEventIR`
- queue IR / queue runtime entry
- 已存在的 target/resource/timeline 系统

### 3.2 简洁性

P1-0 不允许引入大型新调度框架。

推荐只新增一个纯查询层：

```text
systems/action_availability.py
```

它复用已有系统：

- `TimelineSystem`
- `QueueSystem`
- `EnemyActionSystem`
- `TargetSystem`
- `ResourceSystem`
- `RuleBook`

它不应复制 `CombatExecutor` 的执行逻辑。

### 3.3 纯查询

Action availability 查询必须是纯查询：

- 不修改 `BattleState`。
- 不调用 reducer apply。
- 不 dequeue queue。
- 不 advance timeline。
- 不 begin/end turn。
- 不写入 global_flags。
- 不消耗 RNG。

允许调用：

- `timeline.plan_next_actor`
- `queue.plan_next_drain`
- `target.enumerate_action_targets`
- `resource.plan_action_resources`
- `enemy_actions.next_candidate`
- `rules.*` 查询方法

如果某个现有 helper 会产生 mutation，availability 层不能直接调用它。

### 3.4 与 scheduler 一致

availability 视图和 scheduler 执行必须一致：

- availability 说 `queued_mandatory` 时，普通 command 应被 scheduler 拒绝。
- availability 说某个 external command 可输入时，scheduler 不应因 actor mismatch、enemy candidate mismatch、queue priority 等动作边界原因拒绝。
- availability 说 blocked 时，对应 command 不能产生状态 mutation。
- availability 只负责动作边界；action 内部机制仍可能因为目标、资源、unsupported formula 等被 executor blocked，但这些 blocked 必须可解释。

### 3.5 来源边界

新增 executable 结论必须能解释来源：

- action definition 来源。
- action event 来源。
- monster data card / character data card 来源。
- queue intent / resolution / window 来源。
- target enumeration 来源。
- resource preflight 来源。

没有来源时，输出 blocked，不生成可执行 choice。

## 4. 推荐数据结构

实现线程可调整命名，但应保留同等语义。

### 4.1 `ActionAvailabilityMode`

建议枚举：

```python
ActionAvailabilityMode = Literal[
    "queued_mandatory",
    "queued_selectable",
    "external_selectable",
    "scheduler_required",
    "blocked",
    "idle",
]
```

说明：

- `queued_mandatory`：必须先结算队列。
- `queued_selectable`：存在可选队列窗口，外部需要选择。
- `external_selectable`：当前可输入普通外部动作。
- `scheduler_required`：当前没有 active turn，需要 scheduler 先推进 turn begin，或 view 提供 preview command。
- `blocked`：当前规则不足，不能产生动作。
- `idle`：战斗结束或无可行动对象。P1-0 可先少用，后续 wave/battle end 再完善。

如果实现线程希望严格沿用总清单的四类，可以把 `scheduler_required` 和 `idle` 表达为 `blocked` 的细分 payload。但文档建议保留独立 mode，便于推演器区分“需要推进调度器”和“规则错误”。

### 4.2 `ActionAvailabilityView`

建议字段：

```python
schema_version: str
mode: ActionAvailabilityMode
state_phase: str
current_window: str
turn_owner_id: str
requires_scheduler_step: bool
ordinary_input_blocked: bool
ordinary_input_blocked_reason: str
queue: QueueAvailability | None
actor: ActorAvailability | None
choices: tuple[ActionChoice, ...]
selectable_windows: tuple[SelectableWindow, ...]
blocked: tuple[BlockedActionReason, ...]
coverage: dict[str, JSONValue]
source_trace: dict[str, JSONValue]
```

要求：

- 必须 `to_json()`。
- 输出顺序稳定。
- 不包含不可序列化对象。
- blocked reason 使用稳定字符串。
- 不把 Python exception 文本当作规则输出。

### 4.3 `ActionChoice`

建议字段：

```python
choice_id: str
choice_kind: Literal["normal_action", "enemy_fixed_sequence", "queue_action", "ultimate_window", "summon_action"]
control: Literal["external", "mandatory", "selectable"]
actor_id: str
actor_side: str
action_id: str
action_level: int
command_template: dict[str, JSONValue]
auto_target_ids: tuple[str, ...]
selectable_target_ids: tuple[str, ...]
target_policy: dict[str, JSONValue]
target_status: Literal["ok", "blocked"]
target_blocked_reason: str
resource_status: Literal["ok", "blocked", "not_checked"]
resource_blocked_reason: str
coverage_status: str
blocked_reason: str
source_trace: dict[str, JSONValue]
metadata: dict[str, JSONValue]
```

要求：

- `choice_id` 稳定，建议由 actor/action/level/control/queue id/source trace 生成。
- `command_template` 应足以构造 `ActionCommand`，但不能代替真正执行。
- target/resource blocked 时，choice 可以出现在 blocked 列表，不应伪装成可执行 choice。

### 4.4 `QueueAvailability`

建议字段：

```python
has_queue_entries: bool
selected_plan: dict[str, JSONValue]
mode: Literal["mandatory", "selectable", "blocked", "none"]
queue_name: str
queue_entry_id: str
window_family: str
priority_key: str
priority_value: float | None
drain_order: int | None
blocked_reason: str
source_trace: dict[str, JSONValue]
```

要求：

- 使用 `QueueSystem.plan_next_drain` 的 plan，不要自己重排 queue。
- 排序规则必须与 scheduler `_try_queue_drain` 一致。
- unknown family 不得默认执行。

### 4.5 `ActorAvailability`

建议字段：

```python
actor_id: str
actor_side: str
turn_state: Literal["active", "preview_next_actor", "blocked"]
timeline_plan: dict[str, JSONValue]
can_accept_external_command: bool
blocked_reason: str
```

说明：

- 如果 state 已有 active turn，则 actor 是 active turn owner。
- 如果 state 没有 active turn，可以用 `timeline.plan_next_actor` 生成 preview，但不能 apply timeline mutation。
- preview 只能说明 scheduler 下一步会轮到谁，不能写 state。

## 5. 详细任务清单

### P1-0-A 代码边界审查

目标：

- 确认 P1-0 只触碰动作边界相关模块。

需要做：

- [ ] 阅读 `core/model.py` 中 `ActionCommand`、`BattleState.snapshot`。
- [ ] 阅读 `systems/scheduler.py` 中 `step`、`advance_to_next_turn`、`_try_queue_drain`、`_queue_action_preflight_reason`、`_queue_action_command_from_plan`。
- [ ] 阅读 `systems/queue.py` 中 `QueueDrainPlan`、`QueueWindowPlan`、`QueueSystem.plan_next_drain`。
- [ ] 阅读 `systems/enemy_action.py` 中 `EnemyActionCandidate`、`next_candidate`、`command_from_candidate`。
- [ ] 阅读 `systems/target.py` 中 `enumerate_action_targets`。
- [ ] 阅读 `systems/resource.py` 中 `plan_action_resources`。
- [ ] 阅读 `rules/rulebook.py` 中 action/data card/action set 查询方法。
- [ ] 记录当前 validation `validate_v0_283` 覆盖了哪些 enemy action / queue 行为。

验收结果：

- [ ] 实现说明中列出实际触碰文件。
- [ ] 没有读取或依赖旧 v7、旧 model pack、TextMap。
- [ ] 没有把 P1-1 之后的机制混进 P1-0。

### P1-0-B 定义 action availability 数据模型

目标：

- 提供推演器可消费的动作可用性视图。

需要做：

- [ ] 新增 `systems/action_availability.py` 或等价模块。
- [ ] 定义 `ActionAvailabilityView`。
- [ ] 定义 `ActionChoice`。
- [ ] 定义 `QueueAvailability`。
- [ ] 定义 `ActorAvailability`。
- [ ] 定义 `BlockedActionReason` 或等价 blocked payload。
- [ ] 每个结构提供 `to_json()`。
- [ ] 所有 tuple/list/dict 输出排序稳定。
- [ ] 字段只使用 `JSONValue` 可序列化内容。
- [ ] 加入 schema version，例如 `p1_0_action_availability_v1`。

验收结果：

- [ ] 可以对空 state、普通 turn state、queue state 输出 JSON。
- [ ] 输出中有 mode、choices、blocked reasons、coverage。
- [ ] 没有 mutation。
- [ ] 没有调用 executor。

### P1-0-C 实现纯查询入口

目标：

- 提供一个统一入口，让外部推演器查询当前状态能做什么。

推荐接口：

```python
ActionAvailabilitySystem(rules: RuleBook).view(state: BattleState) -> ActionAvailabilityView
```

需要做：

- [ ] 初始化复用 `TimelineSystem`。
- [ ] 初始化复用 `QueueSystem`。
- [ ] 初始化复用 `EnemyActionSystem`。
- [ ] 初始化复用 `TargetSystem`。
- [ ] 初始化复用 `ResourceSystem`。
- [ ] `view(state)` 不修改 state。
- [ ] `view(state)` 先判断 queue。
- [ ] queue 不阻塞时判断 pending turn end。
- [ ] 再判断 active turn owner 或 preview next actor。
- [ ] 最后生成 actor choices。

验收结果：

- [ ] 同一个 state 调用两次 `view`，snapshot 完全一致。
- [ ] `view` 不产生 mutation、event、rng event。
- [ ] `view` 输出可被 JSON 序列化。

### P1-0-D queue 优先边界

目标：

- 明确存在 queue 时，普通外部动作是否被阻塞。

需要做：

- [ ] 使用与 scheduler `_try_queue_drain` 相同的 queue plan 选择逻辑。
- [ ] 若存在可执行 mandatory queue，`mode="queued_mandatory"`。
- [ ] 若存在 selectable queue window，`mode="queued_selectable"`。
- [ ] 若 queue 存在但 resolution 缺失，`mode="blocked"`，blocked reason 为 `queue_resolution_missing` 或现有稳定 reason。
- [ ] 若 queue family unknown，blocked，不默认执行。
- [ ] 若 queue plan 是 action_definition，生成 queue action choice 或 blocked payload。
- [ ] 若 queue plan 是 standalone ability，记录 mandatory drain。
- [ ] 若普通 command 因 queue 被阻塞，输出 `ordinary_input_blocked=True`。

验收结果：

- [ ] 有 mandatory queue 时，availability 不暴露普通 actor choices。
- [ ] 有 mandatory queue 时，scheduler 收到普通 command 会 blocked。
- [ ] queue view 的 selected plan 与 scheduler 实际 drain plan 一致。
- [ ] queue blocked 不产生 mutation。

### P1-0-E pending turn end 边界

目标：

- 明确 action 后 pending queue 导致 turn end deferred 时，外部不能随意输入普通行动。

需要做：

- [ ] 检测 `state.global_flags["pending_turn_end"]`。
- [ ] 若 pending turn end 存在且无 queue，输出 `scheduler_required` 或 blocked 细分。
- [ ] payload 中包含 pending actor、child action、需要完成 turn end 的原因。
- [ ] 不在 availability 中直接完成 turn end。

验收结果：

- [ ] pending turn end state 下，普通 command 不被 availability 标成可输入。
- [ ] 调用 scheduler step 可以完成 pending turn end。
- [ ] availability 查询本身 state unchanged。

### P1-0-F 当前 actor / next actor 边界

目标：

- 给外部推演器明确“当前是谁可以行动”，或“需要先推进 scheduler 才能进入行动”。

需要做：

- [ ] 如果 state 有 active turn owner，使用它作为 actor。
- [ ] 如果 state 没有 active turn owner，调用 `timeline.plan_next_actor` 做 preview。
- [ ] preview actor 不写入 state。
- [ ] preview 输出 `requires_scheduler_step=True`。
- [ ] timeline plan blocked 时，输出 blocked reason。
- [ ] actor 不存在、死亡、退场等情况先按现有字段处理；P1-1 会补完整 lifecycle。

验收结果：

- [ ] setup/idle state 可以 preview next actor。
- [ ] active turn state 可以暴露当前 actor。
- [ ] timeline blocked 时不产生 choices。
- [ ] preview 与 scheduler `advance_to_next_turn` 选出的 actor 一致。

### P1-0-G ally 普通行动 choices

目标：

- 为 ally actor 暴露普通外部动作候选。

需要做：

- [ ] 从角色数据卡或 `CombatantActionSetIR` 读取动作集合。
- [ ] 不用固定 action id。
- [ ] 不用角色名。
- [ ] 不用技能文本。
- [ ] 对每个 action 读取 action levels。
- [ ] 选择可执行 level 的策略必须有来源；缺来源时 blocked。
- [ ] 对每个 action 查询 `ActionDefinitionIR`。
- [ ] 对每个 action 查询 `ActionEventIR`。
- [ ] 对每个 action 做 target enumeration。
- [ ] 对每个 action 做 resource preflight。
- [ ] 生成 `ActionChoice`。
- [ ] target/resource/action event 任一 blocked 时，不把 choice 标成 executable。

验收结果：

- [ ] ally actor 至少能暴露来自数据卡/action set 的 action choices。
- [ ] 缺 character data card 或 action set 时 blocked。
- [ ] 缺 action definition 时 blocked。
- [ ] 缺 action event 时 blocked。
- [ ] target candidates empty 时 blocked。
- [ ] SP 不足时 blocked。

### P1-0-H enemy 普通行动 choices

目标：

- 将敌方 fixed sequence 作为规则候选暴露给外部推演器，而不是让 core 做 AI。

需要做：

- [ ] 使用 `EnemyActionSystem.next_candidate`。
- [ ] candidate available 时生成 `ActionChoice`。
- [ ] choice_kind 建议为 `enemy_fixed_sequence`。
- [ ] control 必须是 `external`，不是 `ai`。
- [ ] command template 可兼容现有 `ActionCommand`，但 metadata 必须写明 `selection_controller="external"`.
- [ ] 保留 candidate 的 `source_trace`。
- [ ] 保留 selectable_target_ids 和 auto_target_ids。
- [ ] candidate blocked 时输出 blocked reason。
- [ ] 不在 availability 中 advance enemy sequence cursor。
- [ ] 不在 availability 中自动选择 target。
- [ ] 不在 availability 中自动执行 command。

验收结果：

- [ ] enemy actor 可暴露 fixed-sequence candidate。
- [ ] enemy candidate 不会自动执行。
- [ ] enemy candidate cursor 不会因 availability 查询前进。
- [ ] command 与 candidate 不匹配时 scheduler blocked。
- [ ] target 与 candidate 不匹配时 scheduler blocked。
- [ ] 文档和报告明确“enemy candidate 不是 AI”。

### P1-0-I summon 行动边界预留

目标：

- 为 P1-3 summon 行动保留边界，但不在 P1-0 伪实现 summon 行动。

需要做：

- [ ] 如果 actor side 是 `summon`，检查是否有明确 timeline/action admission。
- [ ] 有真实 action source 时可生成 `summon_action` choice。
- [ ] 缺 source 时 blocked，reason 稳定为 summon action admission missing 类原因。
- [ ] 不给 summon 默认速度、默认 action、默认 target。
- [ ] 不把 summon 当 ally 或 enemy 偷偷复用普通动作集合。

验收结果：

- [ ] summon actor 缺 admission 时 blocked。
- [ ] P1-0 不产生假 summon action。
- [ ] 后续 P1-3 可以在同一 view 中接入 summon choices。

### P1-0-J ultimate selectable window 边界

目标：

- 让终结技插队窗口作为可选动作窗口暴露给外部，而不是 mandatory queue 或自动执行。

需要做：

- [ ] 审查现有 `enqueue_manual_ultimate` 和 manual ultimate queue entry。
- [ ] 为可选 ultimate queue 输出 `mode="queued_selectable"` 或 selectable window。
- [ ] payload 中包含 actor、action、energy cost、target candidates。
- [ ] 不自动消耗能量。
- [ ] 不自动执行终结技。
- [ ] 若 ultimate source 或 energy rule 缺失，blocked。

验收结果：

- [ ] ultimate 可选窗口能被 availability 观测。
- [ ] 外部不输入 ultimate command 时不会自动执行。
- [ ] 外部输入不匹配 ultimate command 时 blocked。
- [ ] 能量不足时 blocked。

### P1-0-K resource preflight

目标：

- availability 中的 action choice 不能忽略 SP/energy 等基础资源合法性。

需要做：

- [ ] 复用 `ResourceSystem.plan_action_resources`。
- [ ] 普通 action 计算 skill point delta 与 energy gain 时，不复制一份散落逻辑。
- [ ] 如果需要复用 executor 私有 helper，应优先抽到共享纯函数模块，而不是跨模块 import 私有函数。
- [ ] queue action 遵守 queue resource policy。
- [ ] ultimate action 检查 energy cost。
- [ ] resource blocked reason 输出稳定字符串。

验收结果：

- [ ] SP 不足 action 不出现在 executable choices。
- [ ] ultimate energy 不足 action blocked。
- [ ] queue ignore resource policy 与 scheduler 执行一致。
- [ ] resource preflight 不 apply mutation。

### P1-0-L target preflight

目标：

- availability 中的 action choice 必须暴露可选目标和自动目标。

需要做：

- [ ] 复用 `TargetSystem.enumerate_action_targets`。
- [ ] 复用 action definition / action event 的 target mode。
- [ ] enemy candidate 直接使用 candidate target enumeration。
- [ ] queue action 使用 queue plan target resolution。
- [ ] target blocked reason 输出稳定字符串。
- [ ] 缺目标不 fallback 到默认目标。
- [ ] 缺 target mode 不 fallback。
- [ ] dead/alive 细节先按现有 target system；P1-1 再补完整 lifecycle。

验收结果：

- [ ] single/blast/bounce/self_or_team 可暴露 selectable targets。
- [ ] aoe 可暴露 auto targets。
- [ ] target candidates empty 时 blocked。
- [ ] unsupported target mode 时 blocked。
- [ ] availability target 结果与 scheduler/executor 执行目标边界一致。

### P1-0-M scheduler 集成

目标：

- scheduler 能使用或至少对齐 action availability 的结论。

需要做：

- [ ] 不要求 scheduler 全量重构。
- [ ] 至少让 validation 能比较 availability 与 scheduler step 的结果。
- [ ] 可选：在 `CombatScheduler` 上提供 `action_availability(state)` 便捷方法。
- [ ] scheduler blocked coverage 中补充 availability mode 或 blocker。
- [ ] 删除或替换新代码中的 `manual_route_command_or_ai_policy` 这类 AI 表述；若保留旧文本，必须在报告中标注 legacy wording。

验收结果：

- [ ] availability 与 scheduler queue priority 一致。
- [ ] availability 与 scheduler actor mismatch 检查一致。
- [ ] availability 与 scheduler enemy candidate mismatch 检查一致。
- [ ] scheduler 不因为 availability 引入额外 mutation。

### P1-0-N 接口兼容与命名债务

目标：

- 处理 `source="ai"` 的历史命名，避免继续扩散 AI 概念。

需要做：

- [ ] 搜索 v8 中 `source="ai"`、`manual_route_command_or_ai_policy`、`enemy_ai_policy` 相关使用。
- [ ] 区分数据来源字段和策略 AI 字段。
- [ ] 新增输出统一使用 `external` / `fixed_sequence_candidate` / `rule_candidate` 语义。
- [ ] 不新增任何“AI 决策”接口。
- [ ] 如果要修改 `ActionCommand.source` Literal，必须记录兼容影响，并按项目规则向用户确认是否兼容旧接口。
- [ ] 如果暂不改 Literal，必须在 P1-0 report 中记录这是 legacy naming debt。

验收结果：

- [ ] 新增 P1-0 API 不暴露 `ai` 作为策略概念。
- [ ] 旧验证不因命名调整无意义破坏。
- [ ] 文档明确敌方动作由外部推演器选择。

### P1-0-O 验证矩阵

目标：

- 用正例和负例证明动作边界可用。

建议新增：

```text
simulator_v8_clean_core/tools/validate_p1_0_action_boundary.py
```

或延续版本号命名。命名由实现线程决定。

需要覆盖：

- [ ] empty/no actor state blocked。
- [ ] no active turn state 可 preview next actor。
- [ ] active ally turn 暴露 ally choices。
- [ ] ally action SP 足够 executable。
- [ ] ally action SP 不足 blocked。
- [ ] ally action target empty blocked。
- [ ] active enemy turn 暴露 enemy fixed-sequence candidate。
- [ ] enemy candidate command 执行通过。
- [ ] enemy mismatched action command blocked。
- [ ] enemy mismatched target command blocked。
- [ ] enemy missing monster data card blocked。
- [ ] queue mandatory 优先于普通行动。
- [ ] mandatory queue 下普通 command blocked。
- [ ] queue selectable window 可观测。
- [ ] pending turn end 不暴露普通 action。
- [ ] summon actor 缺 admission blocked。
- [ ] availability 查询前后 snapshot 一致。
- [ ] availability 输出 JSON 稳定。
- [ ] blocked/audit_only/discovered_only 不产生 mutation。

验收结果：

- [ ] 新 validation 输出 `ok=true`。
- [ ] 每个子 case 输出 before/after snapshot hash 或等价 replay 证据。
- [ ] 每个 blocked case 证明 state unchanged。
- [ ] 每个 executable case 能用 scheduler/executor 完成对应动作。

### P1-0-P 文档和报告

目标：

- 让后续线程知道 P1-0 的边界和剩余问题。

需要做：

- [ ] 新增或更新 live validation report。
- [ ] 报告中说明当前做到哪里。
- [ ] 报告中说明 P1-0 仍不解决哪些问题。
- [ ] 报告中说明敌方 AI 不在 core 中实现。
- [ ] 报告中说明 `source="ai"` 是否仍为 legacy naming debt。
- [ ] 如新增 action availability API，更新相关 README 或交接摘要。
- [ ] 勾选 `FIRST_PHASE_TASK_CHECKLIST.md` 中已完成的 P1-0 子项。

验收结果：

- [ ] 后续 agent 可以从报告中知道如何查询动作。
- [ ] 后续 agent 不会把 enemy candidate 误当 AI。
- [ ] 总清单 P1-0 子项状态与实际实现一致。

## 6. P1-0 最终验收

P1-0 只有在以下全部满足时才能勾选 `P1-0-DONE`：

- [ ] 存在稳定的 action availability 查询入口。
- [ ] 查询入口是纯查询，不改变 state。
- [ ] 查询入口可输出 JSON。
- [ ] 有 queue 时，能区分 mandatory / selectable / blocked。
- [ ] mandatory queue 会阻止普通 external command。
- [ ] pending turn end 不会暴露普通 external command。
- [ ] 无 active turn 时，能 preview next actor 或明确要求 scheduler step。
- [ ] active ally turn 能暴露来自数据卡/action set 的 action choices。
- [ ] active enemy turn 能暴露 fixed-sequence candidate，但不自动选择或执行。
- [ ] summon actor 缺 admission 时 blocked，不伪造默认动作。
- [ ] target preflight 使用现有 target system。
- [ ] resource preflight 使用现有 resource system 或抽出的共享纯函数。
- [ ] availability 认为可输入的 command，scheduler 不因动作边界原因拒绝。
- [ ] availability 认为 blocked 的 command，不产生状态 mutation。
- [ ] 新增验证包含正例和负例。
- [ ] snapshot replay 通过。
- [ ] source audit 通过。
- [ ] static checks 通过。
- [ ] 未引入 raw TBGD/TextMap/旧 v7/旧 model pack runtime 依赖。
- [ ] 未引入角色名、怪物名、固定 action id、固定文件名等硬编码主路径。
- [ ] 报告明确敌方 AI 不做。

## 7. 建议实现顺序

推荐按以下顺序实现，避免一次性改太多：

1. 新增 action availability 数据结构，只做 JSON 输出。
2. 实现纯查询入口，先返回 blocked/idle。
3. 接入 queue plan，只输出 queue availability。
4. 接入 pending turn end 和 next actor preview。
5. 接入 enemy fixed-sequence candidate。
6. 接入 ally action set 枚举。
7. 接入 target preflight。
8. 接入 resource preflight。
9. 接入 scheduler 对齐验证。
10. 处理 `ai` 命名债务的最小兼容方案。
11. 新增 validation。
12. 更新 report 和总 checklist。

每一步都应保持验证可跑，不要攒到最后一次性修。

## 8. 禁止事项

P1-0 实现中明确禁止：

- 禁止新增敌方策略选择器。
- 禁止根据敌人名字决定动作。
- 禁止根据角色名字决定动作。
- 禁止固定某几个 action id 作为普攻/战技/终结技。
- 禁止缺目标时默认选第一个敌人。
- 禁止缺 target mode 时 fallback。
- 禁止缺 action set 时从 TextMap 或技能文本猜。
- 禁止 availability 查询中 apply mutation。
- 禁止 availability 查询中消耗 RNG。
- 禁止把 queue unknown family 默认当 follow-up 或 immediate。
- 禁止为了 UI 方便改变 core source boundary。
- 禁止用旧 v7/model pack 补规则。

## 9. P1-0 之后的交接点

P1-0 完成后，后续阶段应接着做：

- P1-1 UnitLifecycle：补死亡、退场、spawn 对 action availability 的影响。
- P1-2 WaveSystem：补 battle end / next wave 对 availability 的影响。
- P1-3 Summon/Assistant/Servant：把 summon blocked 预留接成真实动作。
- P1-4 状态系统：把控制、禁用、沉默等状态接入 action gating。
- P1-5 Queue/Window：完善 selectable window 和 queue family 优先级。
- P1-6 Target：扩展 sort/fetch/random/adjacent 后，availability target preflight 自动受益。
- P1-7 RNG：让随机 target/probability choice 进入可分支输出。

P1-0 不要求解决这些后续问题，但必须留下清晰扩展点，不能把后续机制写死在当前动作边界里。
