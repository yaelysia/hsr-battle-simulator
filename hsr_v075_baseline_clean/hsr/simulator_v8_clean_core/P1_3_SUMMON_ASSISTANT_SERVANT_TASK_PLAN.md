# P1-3 Summon / Assistant / Servant 总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-3 Summon / Assistant / Servant 最小闭环` 的实现级拆解。目标是让后续实现 agent 可以只围绕本文件完成 P1-3，不需要继承前序对话上下文。

本计划按“总体性执行计划”标准编写：

```text
先定义它在完整模拟器中的位置和边界
再拆数据来源、IR、runtime 状态、系统接入、验证矩阵、回归和禁止事项
```

后续 P1 阶段计划也应沿用同一规格。每一项计划都不能只列局部代码改动，而要先回答：

- 这个阶段在完整模拟器中的职责是什么。
- 它承接了哪些既有系统，会影响哪些后续系统。
- 它的真实规则来源、runtime 边界、状态 mutation、source audit 和 replay 口径是什么。
- 哪些东西必须 executable，哪些东西必须 blocked/process-only/discovered-only。
- 如何证明没有引入硬编码、旧系统依赖、伪来源、默认 fallback 或验证专用路径。

也就是说，执行计划必须先保证方向正确，再拆具体任务；局部实现清单只是总体计划的落地部分。

P1-3 的核心结论：

```text
summon / assistant / servant 不是同一个机制。
P1-3 要先建立统一分类和来源 admission，再选择至少一条真实可执行纵切。
目录字段、文本命名、视觉召唤、旧经验都不能当作 runtime 规则来源。
```

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是在 core 中写敌方 AI，而是支持外部推演器搜索：

```text
给定战斗配置、动作选择和随机分支
=> core 判断合法性、执行规则、输出完整 transition
=> 外部推演器从可能路径中寻找达成目标的通关方式
```

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR 或 scenario/setup 层已经构造好的 runtime setup。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测伤害或手工答案作为规则输入。

### 0.2 P1-3 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

已经完成的前置阶段：

- P1-0 Action Boundary：core 不做敌方 AI，只暴露行动候选、合法性和 transition。
- P1-1 UnitLifecycle：单位 `active / defeated / removed` 统一进入 damage、target、timeline、queue、action availability；UnitSpawn/UnitRemove 已有通用 mutation/replay 底座。
- P1-2 WaveSystem：多波战斗通过 WaveDefinition、UnitSpawn、UnitRemove、wave_index mutation、wave events 推进；enemy summon 缺 admission 时默认阻塞 wave clear。

P1-3 是第一个真正触碰“非普通角色/非普通怪物实体”的阶段。它必须承接：

- P1-1 的 UnitSpawn/UnitRemove。
- P1-2 的 wave clear policy。
- P1-0 的外部动作选择边界。
- P1-5 未来的 queue/window 顺序。
- P1-6 未来的 summon/servant target 扩面。

### 0.3 星铁中的相关概念

星铁战斗里至少存在四类容易被混在一起的对象：

1. **battle unit summon**
   - 角色侧或队伍侧召唤到战斗系统中的单位。
   - 可能有行动轴、技能、HP、可被选中、可被治疗/攻击。
   - 也可能只是非战斗/场景跟随单位，不能直接当作 combat unit。

2. **summoned monster**
   - 敌方或关卡机制召唤出来的怪物。
   - 通常应使用 `side="enemy"`，并通过 summon metadata 标记 owner/summoner/source。
   - 是否计入 wave clear 必须由来源或 conservative policy 决定。

3. **assistant ability**
   - 通过队列/插入能力触发的协助能力。
   - 不一定有独立 UnitState。
   - 可能只是 owner/source actor 的一次附属 ability execution，但需要独立归因和 source audit。

4. **servant**
   - 可能是类似忆灵/从者的 owner-bound battle entity。
   - 有些 servant 可能有独立 HP、行动轴和技能；有些只是 owner 的机制组件。
   - 不能只因为文件路径含 `Servant` 就默认创建 UnitState。

P1-3 的重点不是一次性复刻所有这些机制，而是先把分类、来源、生命周期、目标、行动、归因和 blocked 策略定成通用框架，避免后续角色/怪物实现时各自写特例。

### 0.4 当前代码事实

当前相关落点：

```text
core/model.py
core/reducer.py
systems/unit_lifecycle.py
systems/wave.py
systems/timeline.py
systems/target.py
systems/action_availability.py
systems/queue.py
systems/scheduler.py
systems/ability_task.py
systems/effect.py
tbgd/lowering.py
tbgd/monster_cards.py
rules/ir.py
rules/rulebook.py
scenarios/schema.py
scenarios/identity.py
```

当前事实：

- `UnitSide = Literal["ally", "enemy", "summon"]`。
- snapshot 已有 `teams["summon"]` 和 `active_teams["summon"]`。
- `MutationReducer` 的 UnitSpawn payload 允许 `side in {"ally", "enemy", "summon"}`。
- `UnitLifecycleSystem` 已支持 spawn/remove/defeat/revive blocked。
- `TimelineSystem.plan_next_actor` 对 `side=="summon"` 要求 `flags["timeline_admitted"] is True`，否则 skipped reason 为 `summon_timeline_not_admitted`。
- `ActionAvailabilitySystem._choices_for_actor` 对 `side=="summon"` 当前只返回 `summon_action_admission_missing`。
- `TargetSystem` 当前在部分 group alias 中把 `summon` 纳入 light team，例如 `AllLightTeam`。
- `WaveSystem` 当前对 active enemy summon 默认阻塞 wave clear，除非 `wave_clear_policy="ignore"`。
- `MonsterDataCardIR.summon_refs` 来自 `MonsterConfig.SummonIDList`，当前只是数据卡字段，没有触发语义。
- `SummonUnitData.json` 已作为 `summon_unit` entity 来源进入基础 entities，但没有专门数据卡。
- TBGD 中 `Config/ConfigSummonUnit/*.json` 存在大量场景/跟随/视觉 summon 配置，其中部分含 `SkillConfig`，但不能默认视为战斗技能。
- TBGD 中存在 `RPG.GameCore.SummonMonster` opcode，主要分布在 Monster、Level、Activity、BattleEvent/GridFight 等来源。
- `TurnInsertAssistantAbility` 已被 lowering 识别为 queue intent opcode，但当前 admission/resolution/window 都明确 blocked。
- `Config/ConfigAbility/Servant/*.json` 存在 servant ability 文件，当前没有 servant 数据卡或 runtime component。

### 0.5 一个必须先定清的来源原则

以下字段或文件不能直接当作“执行触发”：

- `MonsterConfig.SummonIDList`
  - 它更像 monster 可召唤对象目录。
  - 没有 action/ability/event 触发时，不能据此自动 spawn。

- `SummonUnitData.JsonPath`
  - 它描述 summon unit 配置入口。
  - 是否是战斗单位、是否可行动、何时生成，还需要真实来源。

- `ConfigSummonUnit.SkillConfig`
  - 很多是 adventure/custom skill 或跟随单位行为。
  - 不能默认映射为 combat action。

- 文件路径/名字含 `Servant`
  - 只能作为 discovery/categorization evidence。
  - 不能证明 servant 是独立 UnitState。

P1-3 的执行源必须来自结构化机制，例如：

- admitted `SummonMonster` task。
- admitted `TurnInsertAssistantAbility` queue intent + resolved assistant ability。
- admitted servant spawn/action source。
- scenario/setup 明确要求 initial summon，并标记为 setup source，而不是伪装成 TBGD 机制。

### 0.6 P1-3 的一句话目标

P1-3 只回答一个问题：

```text
一个 summon / assistant / servant 如何从真实来源进入 runtime，
如何表达 owner/source/lifetime/target/timeline/queue/wave-clear 语义，
并至少完成一条可 replay/source audit 的真实纵切？
```

### 0.7 P1-3 非目标

P1-3 不做：

- 不做敌方 AI。
- 不做完整 servant 全角色复刻。
- 不做完整 assistant queue/window 优先级，P1-5 再扩。
- 不做完整 summon/servant target expression，P1-6 再扩。
- 不做完整状态生命周期，P1-4 再扩。
- 不做关卡特殊玩法召唤全量实现。
- 不做非战斗场景跟随/寻宝 summon 行为。
- 不做视觉 summon、camera、anim、adventure AI。
- 不为了某个角色、某个怪物、某个 summon id 写 runtime 特判。

P1-3 只做通用分类、数据卡/IR admission、runtime 状态、最小 spawn/remove/action/assistant 纵切和验证。

## 1. 总体设计原则

### 1.1 分类优先，不能混成一个 summon

P1-3 必须先建立分类：

```text
battle_unit_summon
summoned_monster
assistant_ability
servant_unit
servant_component
visual_or_adventure_summon
unsupported_special_summon
```

推荐语义：

- `battle_unit_summon`
  - 使用 `side="summon"`。
  - 通过 `team_side="ally"` 或 `team_side="enemy"` 表达阵营关系。
  - 有独立 UnitState。

- `summoned_monster`
  - 使用 `side="enemy"`。
  - flags 中标记 `summon_kind="summoned_monster"`、`owner_id`、`summoner_id`、`wave_clear_policy`。
  - 复用 monster profile/card/action set。

- `assistant_ability`
  - 默认不是 UnitState。
  - 通过 queue item / ability execution metadata 表达 effective assistant source。
  - 如果 assistant 需要独立 stats，必须有 assistant unit/component source，否则 blocked。

- `servant_unit`
  - 有独立 HP/action/timeline/targetability 时使用 UnitState，推荐 `side="summon"` 并设置 `team_side`。

- `servant_component`
  - 没有独立单位资格时作为 owner-bound runtime component，不能进入 target/timeline。

- `visual_or_adventure_summon`
  - 只允许 discovery/audit，不能产生 combat mutation。

### 1.2 UnitSide 不等于战斗阵营

当前 `side="summon"` 不是 `ally` 也不是 `enemy`。如果 target/timeline/queue 继续直接比较 `unit.side`，会出错：

- `summon` actor 选 AllEnemy 时不能把 ally 当 enemy。
- `ally` 目标 AllLightTeam 应包含 ally + ally summon，但不应包含 enemy summon。
- enemy summoned monster 应作为 enemy，而不是 `side="summon"`。

P1-3 推荐引入统一 helper：

```text
systems/unit_relation.py
```

或放入 summon/lifecycle helper 中：

```python
combat_team_of(unit) -> Literal["ally", "enemy", "neutral"]
is_same_combat_team(a, b)
is_opposing_combat_team(a, b)
is_light_team(unit)
is_dark_team(unit)
```

读取规则：

- `side=="ally"` => team `ally`
- `side=="enemy"` => team `enemy`
- `side=="summon"` => 读取 `flags["team_side"]`
- 缺 `team_side` 的 summon 不能参与普通 team target resolution，必须 blocked 或 excluded。

### 1.3 出生/死亡/退场必须复用 UnitLifecycle

所有独立 UnitState 形式的 summon/servant/summoned monster 必须走：

```text
UnitSpawn
UnitDefeat
UnitRemove
UnitRevive blocked
```

禁止：

- 直接改 `state.units`。
- spawn 时缺 source_trace。
- remove 时删除单位丢审计。
- 用 process event 替代 mutation。

### 1.4 执行触发必须有真实 source

P1-3 不允许为了“至少一条可执行纵切”伪造触发。

可执行触发候选优先级：

1. admitted `SummonMonster` opcode。
2. admitted `TurnInsertAssistantAbility` queue intent + assistant ability resolution。
3. admitted servant spawn/action source。
4. explicit scenario/setup initial summon，只能作为 setup source，不可伪装成技能机制。

如果实现线程发现当前 TBGD 中没有满足 admission 的 executable 源：

```text
P1-3 不能假执行。
应输出 blocked validation 和报告，说明 P1-3-DONE 未满足，拆出 admission expansion。
```

### 1.5 没有速度/行动轴来源就不能行动

召唤物或 servant 要进入 timeline，必须有明确来源：

- speed。
- initial action value / base action gauge rule。
- action set / skill list。
- timeline admission。

缺任何关键项时：

```text
spawn 可以 blocked，或 spawn 后 timeline_admitted=False；
不能给默认 speed=100 / action_value=0 让它偷跑。
```

### 1.6 Assistant 默认不消耗 owner 普通行动

assistant ability 是 queue/window 语义，不是普通 actor turn。P1-3 只能实现最小执行路径：

- queue enqueue。
- queue drain。
- ability task execution。
- attribution metadata。
- replay/source audit。

完整窗口优先级、reentrant、duration tick、extra action 关系留给 P1-5。

### 1.7 Wave clear 必须保守

来自 P1-2 的策略继续有效：

- active enemy summon 默认阻塞 wave clear。
- 只有明确 `wave_clear_policy="ignore"` 或 `"counts"` 时，WaveSystem 才能按 policy 处理。
- 缺 source/admission 不得默认 ignore。

P1-3 要把 summon spawn 时的 wave clear policy 写清楚，不能留给 WaveSystem 猜。

### 1.8 外部推演器仍负责选择动作

如果 summon/servant 有独立可行动作：

- core 只暴露 `summon_action` 或等价 action choice。
- 外部推演器选择具体动作/目标。
- enemy summoned monster 也不由 core AI 决策，只暴露 fixed-sequence candidate 或 blocked。

## 2. 推荐数据结构

实现线程可以调整命名，但必须保留同等语义。

### 2.1 `SummonUnitDefinitionIR`

用于描述 `SummonUnitData` 和 `ConfigSummonUnit`。

建议：

```python
@dataclass(frozen=True)
class SummonUnitDefinitionIR:
    summon_definition_id: str
    summon_unit_id: str
    summon_kind: str
    config_path: str
    unique_group: str
    max_summon_count: int | None
    destroy_on_enter_battle: bool | None
    remove_maze_buff_on_destroy: bool | None
    battle_admission: dict[str, JSONValue]
    skill_config: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
```

分类建议：

- `battle_candidate`
- `visual_or_client_only`
- `adventure_follow_unit`
- `unknown`

注意：

- `DestroyOnEnterBattle=True` 的 summon 不应默认进入战斗。
- `IsClient=True` 的 summon 默认不 executable。
- `SkillConfig` 默认只做 discovery，不直接转 combat action。

### 2.2 `SummonMonsterIntentIR`

用于描述 `SummonMonster` opcode 的可执行意图。

建议：

```python
@dataclass(frozen=True)
class SummonMonsterIntentIR:
    summon_intent_id: str
    source_task_id: str
    owner_scope: str
    target_scope: str
    entries: tuple[SummonMonsterEntryIR, ...]
    source_event: str
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
```

`SummonMonsterEntryIR` 建议字段：

```python
entry_id: str
monster_entity_ref: str
monster_raw_id: str
position_policy: dict[str, JSONValue]
count: int
level_policy: dict[str, JSONValue]
wave_clear_policy: Literal["counts", "ignore", "blocked"]
source: IRSource
coverage_status: CoverageStatus
blocked_reason: str
```

要求：

- `SummonMonsterDataList` 必须结构化解析。
- monster id 必须能解析成 RuleEntity/CombatantProfileIR/MonsterDataCardIR。
- count/position/level 缺 source 时 blocked。
- 特殊玩法来源可 discovered/blocked，不得 executable。

### 2.3 `AssistantAbilityIntentIR`

当前已有 `QueueIntentIR` 覆盖 `TurnInsertAssistantAbility`，可以选择扩展它，也可以新增 assistant 专用 IR。

推荐最小方式：

- 保留 `QueueIntentIR` 作为触发来源。
- 新增或扩展 `QueueResolutionIR` 的 assistant resolution。
- 必要时新增：

```python
@dataclass(frozen=True)
class AssistantAbilityResolutionIR:
    assistant_resolution_id: str
    queue_intent_id: str
    assistant_ability_id: str
    owner_alias: str
    target_alias: str
    resolved_graph_id: str
    attribution_policy: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus
    blocked_reason: str
```

admission 条件：

- assistant actor identity 明确。
- assistant ability graph/action source 明确。
- target alias 可解析。
- priority/window/lifecycle policy 明确。
- damage/resource/status attribution 明确。

缺一项就 blocked。

### 2.4 `ServantDefinitionIR`

用于 servant 文件和角色/机制绑定之间的桥。

建议：

```python
@dataclass(frozen=True)
class ServantDefinitionIR:
    servant_definition_id: str
    servant_ref: str
    owner_entity_ref: str
    representation: Literal["unit", "component", "blocked"]
    ability_graph_ids: tuple[str, ...]
    action_set: dict[str, JSONValue]
    stat_source: dict[str, JSONValue]
    timeline_source: dict[str, JSONValue]
    lifecycle_source: dict[str, JSONValue]
    source: IRSource
    coverage_status: CoverageStatus = "blocked"
    blocked_reason: str = ""
```

P1-3 默认策略：

- 有独立 HP/timeline/action/stat source 才能 `representation="unit"`。
- 只有 owner-bound callback/ability 时 `representation="component"`。
- 来源不足时 `blocked`。

### 2.5 `SummonRuntimeState`

建议以 `global_flags["summon_runtime"]` 保存，schema version：

```text
p1_3_summon_runtime_v1
```

推荐字段：

```python
{
  "schema_version": "p1_3_summon_runtime_v1",
  "entities": {
    unit_id: {
      "summon_kind": "...",
      "owner_id": "...",
      "summoner_id": "...",
      "team_side": "ally|enemy",
      "source_intent_id": "...",
      "source_trace": {...},
      "lifetime": {...},
      "timeline_admitted": true|false,
      "targetability": {...},
      "wave_clear_policy": "counts|ignore|blocked",
      "unique_group": "...",
      "created_event_index": 0,
      "removed_event_index": null
    }
  },
  "by_owner": {owner_id: [unit_id]},
  "by_unique_group": {group_key: [unit_id]},
  "last_summon_monsters": [unit_id],
  "servants": {servant_id: {...}},
  "assistant_history": [...],
  "blocked": [...]
}
```

要求：

- 所有变更通过 mutation。
- 不把 `global_flags` 当自由垃圾袋；读写必须由 `SummonSystem` 统一封装。
- snapshot 可见。

### 2.6 `SummonTransitionPlan`

建议：

```python
@dataclass(frozen=True)
class SummonTransitionPlan:
    ok: bool
    operation: Literal[
        "spawn_summon",
        "spawn_summoned_monster",
        "remove_summon",
        "expire_summon",
        "owner_removed_cleanup",
        "assistant_enqueue",
        "assistant_execute",
        "servant_spawn",
        "servant_component_update",
        "blocked",
    ]
    actor_id: str = ""
    owner_id: str = ""
    unit_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
```

`SummonTransitionResult`：

```python
plan
mutations
events
records
```

events 建议：

- `summon.spawned`
- `summon.removed`
- `summon.expired`
- `summon.action.available`
- `assistant.enqueued`
- `assistant.executed`
- `servant.spawned`
- `servant.updated`

## 3. 数据来源与 admission 计划

### 3.1 SummonUnitData / ConfigSummonUnit

目标：

- 建 summon unit 数据卡，但不把视觉/场景召唤误当战斗单位。

需要做：

- [ ] 在 compiler/lowering 层读取 `ExcelOutput/SummonUnitData.json`。
- [ ] 读取 `JsonPath` 指向的 `Config/ConfigSummonUnit/*.json`。
- [ ] 解析 `IsClient`、`DestroyOnEnterBattle`、`MaxSummonCount`、`UniqueGroup`。
- [ ] discovery `SkillConfig`、`AIConfig`、`OnCreate`、`OnDestroy`。
- [ ] 将视觉/client/adventure-only summon 标记为 blocked/discovered_only。
- [ ] 只有具备战斗 admission 的 summon 才能 executable。

验收结果：

- [ ] 存在 `SummonUnitDefinitionIR` 或等价数据卡。
- [ ] `IsClient=True` 默认 blocked。
- [ ] `DestroyOnEnterBattle=True` 默认不作为 battle spawn。
- [ ] runtime 不读取 `SummonUnitData.json` 或 ConfigSummonUnit raw file。

### 3.2 Monster SummonIDList

目标：

- 把 `MonsterDataCardIR.summon_refs` 定义为目录，不当触发。

需要做：

- [ ] 在报告中明确 `SummonIDList` 是 catalog/source candidate。
- [ ] 可建立 `MonsterSummonCatalogIR` 或把 catalog 放入 monster data card。
- [ ] catalog entry 可验证 monster profile/card 是否存在。
- [ ] 没有 `SummonMonster` 或其他触发时不产生 mutation。

验收结果：

- [ ] 有 summon_refs 的 monster 不会在 battle start 自动 summon。
- [ ] 有 summon_refs 但缺触发时 validation blocked/state unchanged。

### 3.3 SummonMonster opcode

目标：

- 接入第一条真正的 monster summon 触发路径。

需要做：

- [ ] 在 `tbgd/lowering.py` 标准化 `RPG.GameCore.SummonMonster`。
- [ ] 提取 `SummonMonsterDataList`。
- [ ] 提取 monster id / count / position / target / level policy。
- [ ] source mode 按现有 policy 分类：
  - mainline monster/avatar source 可优先 admission。
  - Level/Activity/GridFight/BattleEvent 特殊玩法默认 blocked，除非当前阶段明确接纳。
- [ ] 生成 `SummonMonsterIntentIR`。
- [ ] 为 unsupported fields 生成 blocked reason。
- [ ] 不跳过未知字段后标 executable。

验收结果：

- [ ] 至少一个 executable intent，或报告说明没有符合 admission 的真实源。
- [ ] blocked intent 不产生 mutation。
- [ ] intent source trace 可反查到 ability task raw path。

### 3.4 Assistant ability

目标：

- 让 assistant queue 不再只是“family exists but always blocked”的黑盒。

需要做：

- [ ] 审查 `TurnInsertAssistantAbility` raw 出现范围。
- [ ] 审查当前 `QueueIntentIR`、`QueueResolutionIR`、`QueueWindowIR` 对 assistant 的 blocked 路径。
- [ ] 明确 assistant actor identity：
  - owner-bound assistant。
  - independent assistant unit。
  - source-only assistant。
- [ ] 明确 assistant ability id 如何解析到 ability graph/action。
- [ ] 明确 assistant target alias。
- [ ] 明确 assistant attribution。
- [ ] 若缺任一项，保持 blocked。

验收结果：

- [ ] assistant blocked reason 从泛化 `not_admitted` 升级为具体缺口。
- [ ] 如果存在 admitted assistant source，至少完成 enqueue + drain + ability execution 正例。
- [ ] 如果没有 admitted source，validation 证明不会假执行。

### 3.5 Servant source

目标：

- 建 servant 分类，不用路径名硬创建 unit。

需要做：

- [ ] discovery `Config/ConfigAbility/Servant/*.json`。
- [ ] 找 owner/source 绑定。
- [ ] 找 stat/timeline/action/lifecycle source。
- [ ] 区分 `servant_unit` 和 `servant_component`。
- [ ] servant component 不进入 target/timeline。
- [ ] servant unit 必须有 UnitSpawn source。

验收结果：

- [ ] 有 servant source audit report。
- [ ] 缺 owner/stat/timeline/action source 时 blocked。
- [ ] 不因为文件名含 Servant 产生 mutation。

## 4. Runtime 系统设计

### 4.1 新增 `systems/summon.py`

推荐接口：

```python
SummonSystem(rules).view(state) -> SummonRuntimeView
SummonSystem(rules).plan_spawn_from_intent(state, intent, context) -> SummonTransitionPlan
SummonSystem(rules).apply_spawn(state, plan) -> SummonTransitionResult
SummonSystem(rules).plan_remove(state, unit_id, reason) -> SummonTransitionPlan
SummonSystem(rules).plan_owner_cleanup(state, owner_id) -> SummonTransitionPlan
SummonSystem(rules).plan_assistant_queue(state, intent, context) -> SummonTransitionPlan
SummonSystem(rules).blocked(...)
```

要求：

- `view` 纯查询。
- `plan_*` 纯查询。
- `apply_*` 只构造 mutation/event/records，不直接 mutate。
- 统一读写 `summon_runtime`。

### 4.2 Spawn 独立 summon unit

需要做：

- [ ] 从 intent/definition 构造 UnitState。
- [ ] 写 flags：
  - `summon_kind`
  - `team_side`
  - `owner_id`
  - `summoner_id`
  - `source_intent_id`
  - `summon_definition_id`
  - `timeline_admitted`
  - `targetable`
  - `wave_clear_policy`
  - `unique_group`
  - `source_trace`
- [ ] 使用 `UnitLifecycleSystem.spawn_mutation`。
- [ ] 写 `summon_runtime` mutation。
- [ ] 产生 `summon.spawned` event。
- [ ] settlement record 记录 spawn。

验收结果：

- [ ] spawn replay 通过。
- [ ] source audit 可从 UnitSpawn 反查到 intent/definition。
- [ ] 缺 source blocked/state unchanged。

### 4.3 Spawn enemy summoned monster

需要做：

- [ ] 使用 monster profile/card/action set 构造 UnitState。
- [ ] `side="enemy"`。
- [ ] flags：
  - `summon_kind="summoned_monster"`
  - `wave_member_kind="enemy_summon"`
  - `wave_clear_policy`
  - `owner_id`
  - `summoner_id`
  - `summon_intent_id`
  - source trace
- [ ] 如果 `wave_clear_policy` 缺失，默认 blocked，不 spawn 或 spawn 后阻塞 wave clear，策略必须报告。
- [ ] 不能把 summoned monster 加入 current wave ids，除非 source 明确它属于 wave。

验收结果：

- [ ] summoned monster targetable as enemy。
- [ ] wave clear policy 生效。
- [ ] owner/source 可审计。

### 4.4 Remove / expire / owner cleanup

需要做：

- [ ] 定义 lifetime：
  - permanent until removed。
  - turns。
  - action count。
  - owner life。
  - wave end。
  - explicit remove source。
- [ ] 缺 lifetime source 时默认不自动 expire。
- [ ] owner defeated/removed 时：
  - 有 `owner_death_policy=remove` 来源才 remove。
  - 缺来源时 summon action blocked，但不伪 remove。
- [ ] remove 使用 `UnitLifecycleSystem.remove_mutations`。
- [ ] 更新 `summon_runtime`。

验收结果：

- [ ] explicit remove replay 通过。
- [ ] owner death 缺 policy 不产生 remove mutation。
- [ ] removed summon 不可行动/不可普通 target。

### 4.5 Target relation 接入

需要做：

- [ ] 新增 combat team helper。
- [ ] target group alias 不再直接用 `unit.side` 判断 ally/enemy relation。
- [ ] summon/servant owner target：
  - `owner`
  - `summoner`
  - `last_summon_monsters`
  - `caster_summoned_minions`
  - `friend_servant_select`
- [ ] P1-3 只实现 admission 明确的最小别名。
- [ ] 其他 summon/servant target alias 继续 blocked/state unchanged。

验收结果：

- [ ] ally summon 不会把 ally 当 enemy。
- [ ] enemy summoned monster 按 enemy target。
- [ ] owner/summoner fetch 可用或明确 blocked。
- [ ] LastSummonMonsters 来源于 runtime state，不从名称猜。

### 4.6 Timeline / action availability

需要做：

- [ ] summon/servant unit 必须有 `timeline_admitted=True` 才能进入 `TimelineSystem`。
- [ ] 缺 timeline source 保持 skipped `summon_timeline_not_admitted` 或更具体 reason。
- [ ] 有 action set/source 时，`ActionAvailabilitySystem` 暴露 `choice_kind="summon_action"`。
- [ ] summon action command template 仍由外部推演器选择/提交。
- [ ] enemy summoned monster 不由 core AI 控制，仍暴露 fixed sequence candidate 或 blocked。

验收结果：

- [ ] summon timeline admitted 正例。
- [ ] summon timeline missing blocked/skipped。
- [ ] summon action availability 正例或具体 blocked。
- [ ] external selection boundary 不变。

### 4.7 Assistant queue execution

需要做：

- [ ] `TurnInsertAssistantAbility` 的 `QueueIntentIR` 不再一律泛化 blocked；先解析出具体缺口。
- [ ] 如果 source admission 足够：
  - enqueue assistant queue entry。
  - queue window family 为 `assistant`。
  - drain via scheduler。
  - 执行 standalone ability graph 或 admitted ability phase。
  - 记录 attribution。
- [ ] 如果 assistant damage/status/resource 需要 assistant stats 且 stats 缺 source，blocked。
- [ ] 如果 assistant 只是 owner-bound ability，actor_id 可为 owner，但 metadata 必须记录 effective assistant source，不能冒充普通 owner action。

验收结果：

- [ ] assistant enqueue replay。
- [ ] assistant drain replay。
- [ ] assistant ability mutation/source audit。
- [ ] unsupported assistant state unchanged。

### 4.8 Servant runtime

需要做：

- [ ] 根据 `ServantDefinitionIR.representation` 选择 unit 或 component。
- [ ] servant unit 使用 UnitSpawn。
- [ ] servant component 写入 `summon_runtime["servants"]` 或 owner flags。
- [ ] servant action/timeline/target 必须有 source。
- [ ] servant target alias 缺 source blocked。

验收结果：

- [ ] servant source 不足不产生 UnitSpawn。
- [ ] servant component 不进入 target/timeline。
- [ ] servant unit 如果 admitted，可 target/timeline/replay。

### 4.9 Wave integration

需要做：

- [ ] enemy summoned monster spawn 时写 `wave_clear_policy`。
- [ ] ally summon 不影响 enemy wave clear。
- [ ] enemy summon policy:
  - `counts`：阻塞 wave clear 直到 defeated/removed。
  - `ignore`：不阻塞 wave clear。
  - missing/blocked：WaveSystem blocked。
- [ ] wave transition 时 summon persistence：
  - 缺 source 默认保留 active summon，但 enemy summon 可能阻塞。
  - 有 wave_end_remove source 才 UnitRemove。

验收结果：

- [ ] active enemy summon counts 阻塞 clear。
- [ ] ignored enemy summon 不阻塞 clear。
- [ ] missing policy blocked。
- [ ] wave transition 不无来源清理 summon。

## 5. 详细任务清单

### P1-3-A 当前实现审查

目标：

- 明确 summon/assistant/servant 当前散落点和 blocked 路径。

需要做：

- [ ] 阅读 `core/model.py` 的 `UnitSide`、snapshot teams。
- [ ] 阅读 `systems/unit_lifecycle.py` 的 UnitSpawn/Remove。
- [ ] 阅读 `systems/timeline.py` 的 summon timeline gating。
- [ ] 阅读 `systems/action_availability.py` 的 summon action blocked。
- [ ] 阅读 `systems/target.py` 的 summon/light team alias。
- [ ] 阅读 `systems/wave.py` 的 enemy summon clear policy。
- [ ] 阅读 `systems/queue.py` 的 assistant family blocked。
- [ ] 阅读 `tbgd/lowering.py` 的 `TurnInsertAssistantAbility`、queue window family、target fetch blocked summon aliases。
- [ ] 阅读 `tbgd/monster_cards.py` 的 `summon_refs`。
- [ ] 抽样 `SummonUnitData`、`ConfigSummonUnit`、`ConfigAbility/Servant`、`SummonMonster` source。

验收结果：

- [ ] 实现报告列出当前事实和改动范围。
- [ ] 明确哪些是 catalog、哪些是 trigger、哪些只是 visual/adventure。

### P1-3-B 分类与 IR

目标：

- 建立 summon/assistant/servant 分类和 canonical input。

需要做：

- [ ] 新增 `SummonUnitDefinitionIR` 或等价数据卡。
- [ ] 新增 `SummonMonsterIntentIR` 或等价 intent。
- [ ] 新增/扩展 assistant ability resolution。
- [ ] 新增 `ServantDefinitionIR` 或等价 source audit structure。
- [ ] 加入 `CanonicalIR`。
- [ ] 加入 `RuleBook` 查询 API。

验收结果：

- [ ] RuleBook 可查询 summon definitions/intents。
- [ ] source trace 可反查 raw TBGD。
- [ ] blocked source 不标 executable。

### P1-3-C SummonSystem runtime state

目标：

- 让 summon/assistant/servant 有统一 runtime state。

需要做：

- [ ] 新增 `systems/summon.py`。
- [ ] 定义 `p1_3_summon_runtime_v1`。
- [ ] 定义 view/plan/result。
- [ ] 统一读写 `global_flags["summon_runtime"]` 或显式 state 字段。
- [ ] 所有 runtime state 更新通过 mutation。

验收结果：

- [ ] view 纯查询 state unchanged。
- [ ] summon runtime snapshot 可见。
- [ ] replay 一致。

### P1-3-D Source admission discovery

目标：

- 选择第一条真实可执行纵切。

需要做：

- [ ] 统计 `SummonMonster` source candidates。
- [ ] 统计 `TurnInsertAssistantAbility` source candidates。
- [ ] 统计 servant source candidates。
- [ ] 按结构谓词选择候选，不按固定角色/怪物/id。
- [ ] 至少选择一个 executable 候选；如果没有，报告 blocked 原因。

推荐优先级：

1. mainline `SummonMonster` intent。
2. admitted assistant ability queue intent。
3. admitted servant unit source。
4. explicit scenario/setup initial summon 作为 setup-only fallback，不能算技能机制。

验收结果：

- [ ] validation selection policy 不含固定 id。
- [ ] executable source 或 blocked source 缺口如实记录。

### P1-3-E Summon spawn

目标：

- 独立 summon/servant/summoned monster 能通过 UnitSpawn 进入 state。

需要做：

- [ ] 从 intent 构造 UnitState。
- [ ] 写 owner/summoner/team/lifetime/wave/source flags。
- [ ] 调用 UnitLifecycle spawn mutation。
- [ ] 写 summon_runtime mutation。
- [ ] 产生 summon.spawned event。
- [ ] settlement/source audit。

验收结果：

- [ ] UnitSpawn replay。
- [ ] target/timeline/action availability 可观察。
- [ ] 缺 source blocked/state unchanged。

### P1-3-F Summon remove/expire

目标：

- 独立 summon/servant/summoned monster 能按来源退场。

需要做：

- [ ] 定义 remove reason。
- [ ] 定义 expire reason。
- [ ] 接 UnitRemove。
- [ ] 更新 summon_runtime。
- [ ] owner death 缺 policy blocked。

验收结果：

- [ ] remove replay。
- [ ] removed summon 不可行动/不可普通 target。
- [ ] owner death 缺 policy 不产生假 remove。

### P1-3-G Target relation

目标：

- summon/servant 不破坏 ally/enemy target relation。

需要做：

- [ ] 引入 combat team helper。
- [ ] target group alias 使用 team helper。
- [ ] 实现 owner/summoner fetch 的最小 admitted path。
- [ ] 实现 LastSummonMonsters / CasterSummonedMinions 的 runtime-source path 或 blocked。
- [ ] FriendServantSelect 缺 source blocked。

验收结果：

- [ ] ally summon 与 ally 同队。
- [ ] summoned monster 与 enemy 同队。
- [ ] summon actor 不把 owner 当 enemy。
- [ ] unsupported summon target blocked/state unchanged。

### P1-3-H Timeline/action availability

目标：

- 可行动 summon/servant 进入外部选择模型。

需要做：

- [ ] `timeline_admitted=True` 才进 timeline。
- [ ] 有 action source 才暴露 `summon_action`。
- [ ] 缺 action source 继续 blocked。
- [ ] enemy summoned monster 走 enemy candidate 外部选择边界。
- [ ] action availability 输出 source trace。

验收结果：

- [ ] summon action choice 正例或具体 blocked。
- [ ] summon timeline 缺 source skipped。
- [ ] 外部推演器选择边界不变。

### P1-3-I Assistant queue

目标：

- assistant queue 形成最小可执行或清晰 blocked。

需要做：

- [ ] 解析 assistant ability id。
- [ ] 解析 assistant owner/effective actor。
- [ ] 解析 target。
- [ ] 接 queue enqueue/drain。
- [ ] 接 ability execution。
- [ ] 记录 damage/status/resource attribution。
- [ ] 缺 source/stats/target/window 时 blocked。

验收结果：

- [ ] assistant executable case replay/source audit。
- [ ] unsupported assistant no mutation。
- [ ] queue family 不再只有泛化 blocked。

### P1-3-J Servant minimal path

目标：

- servant 不再只是路径名 discovery。

需要做：

- [ ] 建 servant source catalog。
- [ ] 区分 unit/component。
- [ ] component 写 owner-bound runtime state。
- [ ] unit 接 UnitSpawn。
- [ ] action/timeline/source 缺失 blocked。

验收结果：

- [ ] servant source classification report。
- [ ] no fake unit spawn from path name。

### P1-3-K Wave integration

目标：

- P1-2 wave clear 与 P1-3 summon 一致。

需要做：

- [ ] summoned monster 写 `wave_member_kind="enemy_summon"`。
- [ ] 写 `wave_clear_policy`。
- [ ] 验证 counts/ignore/blocked 三类。
- [ ] wave transition 不无来源 remove summon。

验收结果：

- [ ] enemy summon blocks clear when counts/missing。
- [ ] ignore policy 可推进。
- [ ] source audit。

### P1-3-L Source audit / settlement

目标：

- 每个 summon/assistant/servant mutation 可追溯。

需要做：

- [ ] UnitSpawn mutation metadata 指向 summon intent/definition。
- [ ] UnitRemove mutation metadata 指向 lifetime/remove source。
- [ ] assistant queue mutation metadata 指向 QueueIntentIR/ResolutionIR。
- [ ] ability execution settlement 记录 assistant attribution。
- [ ] process-only blocked record 记录 skipped reason。

验收结果：

- [ ] mutation -> settlement -> IR -> TBGD source 可追。
- [ ] blocked/audit_only/discovered_only 不产生 mutation。

### P1-3-M 验证矩阵

建议新增：

```text
simulator_v8_clean_core/tools/validate_p1_3_summon_assistant_servant.py
```

需要覆盖：

- [ ] SummonUnitDefinition lowering/discovery。
- [ ] visual/client/adventure summon blocked。
- [ ] Monster summon_refs catalog 不自动 spawn。
- [ ] SummonMonster intent lowering。
- [ ] executable summon spawn 正例，或无 executable source 的 honest blocked report。
- [ ] UnitSpawn replay。
- [ ] UnitRemove replay。
- [ ] owner death interaction。
- [ ] target relation：ally summon、enemy summoned monster。
- [ ] summon action availability or specific blocked.
- [ ] summon timeline admitted/missing。
- [ ] enemy summon wave clear counts/ignore/blocked。
- [ ] assistant intent lowering。
- [ ] assistant executable or detailed blocked.
- [ ] servant source classification。
- [ ] unsupported servant no mutation。
- [ ] source audit。
- [ ] static checks。

### P1-3-N 回归验证

至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_240 --output-dir /tmp/hsr_v8_v0_240_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_v0_242_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_246 --output-dir /tmp/hsr_v8_v0_246_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_247 --output-dir /tmp/hsr_v8_v0_247_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_v0_287_after_p1_3
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p1_3
git diff --check
```

注意：

- P1-1 验收时 `validate_v0_264` 已存在既有失败豁免。P1-3 实现线程应继续记录，不要误判为 P1-3 新回归。
- 如果 P1-3 使 assistant family 从 blocked 变为 executable，v0_247 等旧验证需要升级预期，而不是保留旧 blocked 断言。

### P1-3-O 文档和 checklist

需要做：

- [ ] 新增 live validation report。
- [ ] 报告说明分类。
- [ ] 报告说明第一条 executable 或 honest blocked。
- [ ] 报告说明 source/admission。
- [ ] 报告说明 runtime schema。
- [ ] 报告说明 wave/target/timeline/queue 接入。
- [ ] 报告说明 assistant/servant 未支持范围。
- [ ] 勾选 `FIRST_PHASE_TASK_CHECKLIST.md` 中 P1-3 项。

## 6. 建议实现顺序

推荐顺序：

1. 审查并输出 source discovery summary。
2. 新增 summon/assistant/servant 分类 IR。
3. RuleBook 建索引。
4. 新增 `systems/summon.py` 和 runtime schema。
5. 做 pure view/plan，不产生 mutation。
6. 接 SummonUnitData/ConfigSummonUnit discovery。
7. 接 SummonMonster intent lowering。
8. 接第一条 executable summon spawn，或明确 blocked。
9. 接 UnitSpawn/UnitRemove + summon_runtime mutation。
10. 接 target relation helper。
11. 接 timeline/action availability。
12. 接 wave clear policy。
13. 接 assistant resolution，能 executable 则做 enqueue/drain，不能则输出细粒度 blocked。
14. 接 servant classification，能 unit/component 则做最小 runtime，否则 blocked。
15. 写 P1-3 validation。
16. 跑 P1-0/P1-1/P1-2/P1-3 和 queue/target 回归。
17. 更新 report/checklist。

不要先从某个角色名或怪物名写 runtime 特例。先让 source/admission 和 runtime schema 成形，再选择结构化正例。

## 7. P1-3 最终验收

只有以下全部满足，才能勾选 `P1-3-DONE`：

- [ ] summon/assistant/servant 分类明确。
- [ ] catalog 与 trigger 区分明确。
- [ ] runtime 不读取 raw TBGD/TextMap/旧 v7/model pack。
- [ ] 存在 SummonSystem 或等价统一 runtime 管理。
- [ ] 独立 summon/servant/summoned monster 生灭复用 UnitLifecycle。
- [ ] source trace 可追溯到 IR/TBGD。
- [ ] 至少一种 summon 或 assistant 机制真实 executable，或报告说明因缺真实 admission 不能勾 DONE。
- [ ] target relation 不因 `side="summon"` 出错。
- [ ] timeline/action availability 不给 summon 默认行动。
- [ ] assistant queue 不伪造 actor/stats/target。
- [ ] servant 不因路径名直接 spawn。
- [ ] enemy summon wave clear policy 明确。
- [ ] replay 通过。
- [ ] source audit 通过。
- [ ] blocked/audit_only/discovered_only 不产生 mutation。
- [ ] 没有角色名、怪物名、summon id、servant 名、固定文件名主路径硬编码。

## 8. 禁止事项

P1-3 实现中明确禁止：

- 禁止把 `SummonIDList` 当成自动召唤触发。
- 禁止把 `SummonUnitData` 当成战斗 spawn trigger。
- 禁止把 ConfigSummonUnit 的 adventure skill 当成 combat action。
- 禁止因为路径含 `Servant` 就创建 UnitState。
- 禁止给 summon 默认 speed/action_value/action set。
- 禁止 owner death 时无来源自动 remove summon。
- 禁止 enemy summon 默认不阻塞 wave clear。
- 禁止 assistant 用 owner 普通行动伪装执行，除非 metadata 明确 assistant attribution 且规则允许。
- 禁止 runtime 直接读 raw ConfigSummonUnit/StageConfig/ability JSON。
- 禁止旧 v7/model pack/文本解释进入 runtime。
- 禁止为了验证按固定角色、怪物、summon id 写主路径。

## 9. P1-3 之后的交接点

P1-3 完成后，后续阶段应接着做：

- P1-4 状态系统：summon/servant 的 duration、buff/debuff、owner-bound status、死亡清理。
- P1-5 Queue/Window：assistant、insert action/ability、extra turn、ultimate/follow-up/counter 的正式顺序。
- P1-6 Target：完整 summon/servant target alias、unique entity、random/fetch/sort。
- P1-8 Scenario/UI：initial summon/servant setup 和审计展示。
- P1-9 Phase acceptance：把 summon/assistant/servant 纳入最小完整闭环。

P1-3 的价值不是一次性做完所有 summon，而是把“非普通单位和协助能力如何进入战斗系统”定成可扩展、可审计、可 replay 的统一入口。
