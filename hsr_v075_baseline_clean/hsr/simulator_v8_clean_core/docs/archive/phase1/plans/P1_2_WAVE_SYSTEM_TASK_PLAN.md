# P1-2 WaveSystem 详细任务计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-2 WaveSystem 最小骨架` 的实现级拆解。目标是让后续实现 agent 可以只围绕本文件完成 P1-2，不需要继承前序对话上下文。

P1-2 的核心结论：

```text
波次不是一个 wave_index 数字。
波次必须成为可 replay、可 audit、可被外部推演器观测的真实状态系统。
```

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是在 core 中写 AI，而是支持外部推演器搜索：

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

runtime 只能读取 Canonical IR / 数据卡 IR 或已经由 scenario/setup 层构造好的 runtime setup。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测伤害或手工答案作为规则输入。

当前第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

已经完成的前置阶段：

- P1-0 Action Boundary：core 只暴露行动候选、合法性和 transition，不替敌人做 AI。
- P1-1 UnitLifecycle：单位 `active / defeated / removed` 统一进入 damage、target、timeline、queue、action availability；UnitSpawn/UnitRemove 已有通用 mutation/replay 底座。

P1-2 要在 P1-1 基础上让多波战斗成为真实状态系统。

### 0.2 星铁战斗里的波次语义

从游戏规则出发，星铁的一场战斗可以有一波或多波敌人：

- 当前波敌人被全部击败或退场后，战斗不一定结束，可能进入下一波。
- 下一波敌人会生成到战场上，成为新的可选目标和行动轴候选。
- 角色方通常保留 HP、能量、战技点、行动轴上下文和大多数战斗内状态，除非具体规则有清理来源。
- 旧波敌人不应继续作为普通目标或行动 actor。
- 最后一波清空后才进入胜利结算。
- 如果我方全部失去可战斗单位，应进入失败或 blocked/end 状态。
- 召唤敌人、特殊实体、阶段切换可能影响清场，但 P1-2 只能先建立保守、可扩展的通用策略。

因为本项目最终用于推演搜索，WaveSystem 不能在内部决定“敌方下一步怎么打”。它只负责：

- 判断当前波是否已清。
- 判断是否允许推进到下一波或战斗结束。
- 生成下一波敌人。
- 发出波次事件和 mutation。
- 暴露 blocked 原因，让外部推演器知道当前状态为什么不能继续。

### 0.3 为什么 P1-2 现在做

当前 v8 只有 `BattleState.wave_index`：

```text
core/model.py: BattleState.wave_index: int = 0
core/reducer.py: 支持 wave_index scalar mutation
scenarios/schema.py: ScenarioSpec.wave_index
scenarios/build_state.py: 构造 BattleState 时直接写 wave_index
```

这还不是 WaveSystem，因为它没有回答：

- 当前 wave 的敌人是谁。
- 当前 wave 是否清场。
- 下一 wave 从哪里来。
- wave_index 何时、为何 mutation。
- 旧 wave 敌人如何退场。
- 新 wave 敌人如何 UnitSpawn。
- battle victory/defeat 何时产生。
- `OnWaveMonster` 什么时候有真实事件源。
- transition/replay/source audit 如何证明这些变化。

如果不先建立 WaveSystem，后续会出现结构债：

- P1-3 summon 自己判断是否阻塞清场。
- P1-4 status 自己处理跨波清理。
- P1-5 queue 自己处理波次边界。
- P1-8 scenario/UI 用自造字段推动下一波。
- `OnWaveMonster` 一直只能 blocked，无法接到真实事件源。

### 0.4 P1-2 的一句话目标

P1-2 只回答一个问题：

```text
当前波最后一个有效敌人被击败后，v8 core 如何通过真实来源、mutation、event、UnitSpawn/UnitRemove 和 replay 进入下一波或战斗结束？
```

### 0.5 当前代码事实

当前相关落点：

```text
core/model.py
core/reducer.py
systems/unit_lifecycle.py
systems/damage.py
systems/timeline.py
systems/action_availability.py
systems/scheduler.py
systems/event_dispatch.py
scenarios/schema.py
scenarios/loader.py
scenarios/build_state.py
rules/ir.py
rules/rulebook.py
tbgd/lowering.py
tools/validate_v0_285.py
tools/validate_v0_286.py
```

当前事实：

- `BattleState.wave_index` 已存在，默认 0。
- snapshot 同时输出 `battle.wave_index` 和顶层 `wave_index`。
- reducer 已支持 `("wave_index",)` scalar mutation。
- scenario loader/build_state 只读取 `wave_index`，没有 wave definition。
- P1-1 已支持 UnitSpawn：`("units", unit_id)` + `metadata.lifecycle_operation="unit_spawn"`。
- P1-1 已支持 UnitRemove：设置 `flags.lifecycle_status="removed"` 和 `removed_record`。
- target/timeline/action availability 已通过 UnitLifecycle 过滤 defeated/removed。
- `event_dispatch.py` 已有 `wave.monster -> OnWaveMonster` canonical alias，但当前 blocked dependency 是 `wave_system_not_implemented`。
- `tbgd/lowering.py` 的 status event family 中 `OnWaveMonster` 当前标记为 `event_source_missing:wave_system_not_implemented`。
- `validate_v0_285.py` 和 `validate_v0_286.py` 当前验证 `OnWaveMonster` 仍 blocked；P1-2 接通后这些旧验证需要更新预期或拆出兼容验证。
- TBGD `ExcelOutput/StageConfig.json` 中能看到波次来源候选：
  - `StageID`
  - `StageConfigData` 中的 `_Wave`
  - `MonsterList`，形态为 wave list，每个 wave 内有 `Monster0`、`Monster1` 等位置键。
  - `StageAbilityConfig`

注意：这些 raw schema 只能在 compiler/lowering/discovery/验证选择层读取，不能进入 runtime。

### 0.6 P1-2 非目标

P1-2 不做：

- 不做敌方 AI。
- 不做路线搜索。
- 不做完整关卡机制、环境、StageAbility 全量执行。
- 不做无限波、特殊玩法、混沌/虚构/末日/模拟宇宙等模式完整规则。
- 不做怪物阶段切换完整实现。
- 不做 summon/assistant/servant 完整实现。
- 不做状态跨波清理全量规则。
- 不做队列/窗口完整优先级。
- 不做角色、敌人、关卡 ID 特判。

P1-2 只做通用 WaveSystem 最小骨架：

- wave definition admission。
- current wave tracking。
- wave clear。
- old wave enemy remove。
- next wave UnitSpawn。
- wave_index mutation。
- wave event source。
- final victory/defeat 状态。

## 1. 设计原则

### 1.1 波次推进必须是状态变化，不是事后解释

WaveSystem 不能只在 snapshot 里显示 `wave_index + 1`。它必须产生 mutation：

- `wave_index` mutation。
- old wave enemy UnitRemove mutation。
- next wave enemy UnitSpawn mutation。
- battle phase/outcome mutation。
- 必要的 wave runtime metadata mutation。

所有 mutation 必须 replay。

### 1.2 runtime 不读取 raw StageConfig

允许读取 raw TBGD 的位置：

- `tbgd/lowering.py`
- `tbgd/discovery.py`
- 只读审计工具
- validation selection 工具

runtime 禁止：

- 直接 open/read `StageConfig.json`。
- 直接解析 `StageConfigData` 的 `_Wave`。
- 直接解析 `MonsterList`。
- 通过固定 StageID 或文件名决定主路径。

P1-2 应新增 Canonical IR 或等价 setup 结构，让 runtime 只读：

```text
WaveDefinitionIR / BattleStageDefinitionIR / ScenarioWaveSetup
```

### 1.3 波次生成必须复用 UnitSpawn

P1-2 不能绕过 P1-1 自己插入单位。

下一波敌人生成必须走：

```text
WaveDefinition entry
-> UnitState 构造
-> UnitLifecycleSystem.spawn_mutation
-> MutationReducer replay
```

spawn 后的单位必须：

- `side="enemy"`。
- `flags.lifecycle_status="active"`。
- 有 wave membership metadata。
- 有 template/profile/card/source trace。
- 有 position。
- 有初始 action value 或明确 blocked。

### 1.4 旧波敌人退场必须复用 UnitRemove

当前波清场后，旧波敌人不应继续作为普通目标或 timeline actor。

推荐策略：

```text
clear wave
-> 对当前 wave 的 defeated enemy 生成 UnitRemove mutation
-> 保留 tombstone
```

如果实现线程决定不 remove defeated old wave enemies，必须证明：

- target 不会选到旧波 defeated 敌人。
- timeline 不会选到旧波 defeated 敌人。
- snapshot 能区分历史波敌人和当前波敌人。
- 后续 wave clear 不会重复统计旧波敌人。

默认仍建议 UnitRemove，因为 P1-1 已经提供 tombstone 语义。

### 1.5 清场不能忽略未知 active enemy

保守策略：

```text
只要战场上存在 active enemy，且没有明确来源证明它不参与 wave clear，
WaveSystem 不应推进到下一波。
```

P1-2 推荐分类：

- `stage_wave_enemy`：来自 Stage/WaveDefinition，计入当前 wave clear。
- `enemy_summon`：P1-3 才完整 admission；P1-2 默认阻塞 wave clear，除非有明确 `wave_clear_policy="ignore"` 来源。
- `unknown_enemy`：active enemy 但缺 wave membership，阻塞 wave clear，reason 为 `active_enemy_without_wave_membership` 或等价稳定原因。

这比错误提前进入下一波更安全。

### 1.6 跨波保留默认不清理

从星铁规则和工程边界看，P1-2 不应在缺少明确来源时清理我方状态或资源。

P1-2 默认策略：

- 保留 ally HP。
- 保留 ally energy。
- 保留 skill points。
- 保留 action value/global AV，除非 timeline rule 或 wave rule 有明确 reset 来源。
- 保留 statuses/modifiers，除非状态系统 P1-4 后有明确 wave cleanup policy。
- 不清理队列；如果队列仍有 pending item，P1-2 先 blocked/waiting，不自动推进。

这样做的原则是：

```text
没有来源时不做额外 mutation。
```

### 1.7 WaveSystem 不替代 Queue/Window

P1-2 只能在安全窗口推进波次。

推荐最小安全窗口：

```text
after action fully settled
AND no mandatory queue pending
AND no selectable queue pending that blocks wave transition
AND current wave clear
```

如果队列仍有待处理项：

```text
WaveTransitionPlan.status = "blocked" / "waiting"
blocked_reason = "pending_queue_before_wave_transition"
state unchanged
```

P1-5 再扩展精确窗口顺序。

### 1.8 OnWaveMonster 只能由真实 wave event 接通

`OnWaveMonster` 不能因为 P1-2 新增了 WaveSystem 就直接无条件 executable。

接通条件：

- `wave.monster` event 由 WaveSystem 在 wave start / monster spawn 时产生。
- event payload 包含 wave index、spawned unit id、monster entry source。
- status event family 能把 `OnWaveMonster` 映射到该 runtime event。
- downstream callback 仍按已有 callback admission 判断是否 executable。

如果只是存在 `OnWaveMonster` family 但没有 WaveSystem event，仍必须 blocked/state unchanged。

## 2. 推荐数据结构

实现线程可以调整命名，但必须保留同等语义。

### 2.1 `WaveMonsterEntryIR`

建议新增到 `rules/ir.py`：

```python
@dataclass(frozen=True)
class WaveMonsterEntryIR:
    entry_id: str
    stage_id: str
    wave_index: int
    position: int
    monster_entity_ref: str
    monster_raw_id: str
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
```

要求：

- `wave_index` runtime 使用 0-based。
- `position` 来自 `Monster0`、`Monster1` 等键。
- `monster_entity_ref` 必须能被 RuleBook 解析为 monster 或 monster_template entity。
- source.evidence 记录 raw StageConfig path、StageID、MonsterList index、Monster key、monster id。

### 2.2 `WaveDefinitionIR`

建议：

```python
@dataclass(frozen=True)
class WaveDefinitionIR:
    wave_definition_id: str
    stage_id: str
    wave_count: int
    entries: tuple[WaveMonsterEntryIR, ...]
    stage_ability_refs: tuple[str, ...]
    source: IRSource
    coverage_status: CoverageStatus = "executable"
    blocked_reason: str = ""
```

如果实现线程认为 `BattleStageDefinitionIR` 更合适，也可以用：

```text
BattleStageDefinitionIR
  - stage_id
  - wave_definitions
  - stage ability refs
```

但 runtime 入口必须能按 battle setup 找到当前波和下一波 entries。

### 2.3 `BattleWaveRuntimeState`

建议以 snapshot 可见的结构表达当前 battle 的 wave runtime：

```python
@dataclass(frozen=True)
class BattleWaveRuntimeState:
    wave_definition_id: str
    current_wave_index: int
    total_waves: int
    started_wave_indices: tuple[int, ...]
    cleared_wave_indices: tuple[int, ...]
    current_wave_unit_ids: tuple[str, ...]
    spawned_unit_ids_by_wave: dict[int, tuple[str, ...]]
    removed_unit_ids_by_wave: dict[int, tuple[str, ...]]
    status: Literal["not_configured", "active", "between_waves", "victory", "defeat", "blocked"]
    blocked_reason: str = ""
```

存储位置有两种可选方案：

1. 在 `BattleState` 新增显式 `wave_runtime` 字段。
2. 放在 `state.global_flags["wave_runtime"]`。

工程上更干净的是显式字段，但会影响 dataclass/reducer/snapshot。为了 P1-2 最小改动，可以先用 `global_flags["wave_runtime"]`，但必须满足：

- 所有变更通过 mutation。
- snapshot 稳定输出。
- 字段 schema 有 version。
- 不把 global_flags 当自由垃圾袋，WaveSystem 统一读写。

推荐 schema version：

```text
p1_2_wave_runtime_v1
```

### 2.4 `WaveTransitionPlan`

建议：

```python
@dataclass(frozen=True)
class WaveTransitionPlan:
    ok: bool
    status: Literal[
        "no_change",
        "current_wave_cleared",
        "advance_to_next_wave",
        "battle_victory",
        "battle_defeat",
        "blocked",
    ]
    wave_definition_id: str = ""
    current_wave_index: int = 0
    next_wave_index: int | None = None
    cleared_unit_ids: tuple[str, ...] = ()
    blocking_unit_ids: tuple[str, ...] = ()
    spawn_entries: tuple[WaveMonsterEntryIR, ...] = ()
    remove_unit_ids: tuple[str, ...] = ()
    blocked_reason: str = ""
    source_trace: dict[str, JSONValue] = field(default_factory=dict)
```

要求：

- 纯查询计划不能 mutate。
- blocked plan 必须 state unchanged。
- plan 要能进入 transition records，供 UI/推演器观测。

### 2.5 `WaveTransitionResult`

建议：

```python
@dataclass(frozen=True)
class WaveTransitionResult:
    plan: WaveTransitionPlan
    mutations: tuple[Mutation, ...]
    events: tuple[GameEvent, ...]
    records: tuple[dict[str, JSONValue], ...]
```

events 建议：

- `wave.cleared`
- `wave.started`
- `wave.monster`
- `battle.victory`
- `battle.defeat`

这些 event 是否触发 callback，要由 `event_dispatch.py` 和 status callback admission 决定。

## 3. WaveDefinition 来源链路

### 3.1 TBGD lowering

目标：

- 从 TBGD StageConfig 降出 canonical wave definition。

需要做：

- [ ] 在 `tbgd/lowering.py` 或等价 compiler 层读取 `ExcelOutput/StageConfig.json`。
- [ ] 解析 `StageID`。
- [ ] 解析 `StageConfigData` 中的 `_Wave`。
- [ ] 解析 `MonsterList`。
- [ ] 对每个 wave entry 解析 `Monster0`、`Monster1` 等位置键。
- [ ] 把 monster id 映射为当前项目已有 entity ref 形式，例如 `monster:<id>`。
- [ ] 对空值、0、未知 monster、缺 profile/card 的 entry 标记 blocked，不允许伪造默认怪物。
- [ ] 记录 `StageAbilityConfig`，但 P1-2 不执行 stage ability；缺执行 admission 时 process-only/blocked。
- [ ] 将结果写入 `CanonicalIR`。

验收结果：

- [ ] `RuleBook` 可按 stage/wave definition id 查询 WaveDefinition。
- [ ] source trace 可从 WaveDefinition entry 反查到 StageConfig source path、StageID、MonsterList wave index、Monster key。
- [ ] runtime 不读取 raw StageConfig。
- [ ] unknown monster entry 不会生成 executable spawn。

### 3.2 RuleBook API

建议新增：

```python
RuleBook.wave_definition(wave_definition_id) -> WaveDefinitionIR | None
RuleBook.wave_definitions() -> tuple[WaveDefinitionIR, ...]
RuleBook.wave_definition_for_stage(stage_id) -> WaveDefinitionIR | None
RuleBook.wave_entries_for_wave(wave_definition_id, wave_index) -> tuple[WaveMonsterEntryIR, ...]
```

验收结果：

- [ ] API 返回排序稳定。
- [ ] 不按固定 StageID 写主路径。
- [ ] validation 可按结构谓词选择一个多波 stage。

### 3.3 Scenario/setup 接入

当前 `ScenarioSpec` 没有 wave definition 字段。P1-2 需要给 battle state 一个 wave setup 来源。

推荐添加可选字段：

```python
ScenarioSpec.wave_definition_ref: str | None = None
ScenarioSpec.stage_ref: str | None = None
```

或等价 JSON：

```json
{
  "wave_setup": {
    "kind": "tbgd_stage",
    "stage_id": "310049"
  }
}
```

要求：

- 旧 scenario 不带 wave setup 时仍可加载。
- 旧单波验证不应被强行要求 wave definition。
- 有 wave setup 时，builder 必须写入 `global_flags["wave_runtime"]` 初始结构。
- 初始 state 中只应 spawn/包含 current wave 的敌人；后续 wave 敌人不应提前作为 active target 出现。
- 如果 validation 为了构造最小 synthetic wave setup，必须明确标记为 validation setup，且不作为 runtime 规则来源。

验收结果：

- [ ] 旧 scenario 兼容。
- [ ] 新 wave scenario 可加载。
- [ ] 初始 snapshot 能看到 wave runtime。
- [ ] current wave enemy flags 有 wave membership。

## 4. WaveSystem 详细任务清单

### P1-2-A 当前波次审查

目标：

- 明确当前 wave 相关代码事实，不误把旧 `wave_index` 当 WaveSystem。

需要做：

- [ ] 阅读 `core/model.py` 的 `BattleState.wave_index` 和 snapshot。
- [ ] 阅读 `core/reducer.py` 的 scalar `wave_index` mutation。
- [ ] 阅读 `scenarios/schema.py`、`loader.py`、`build_state.py` 的 `wave_index` 构造。
- [ ] 阅读 `systems/event_dispatch.py` 中 `wave.monster -> OnWaveMonster` 映射。
- [ ] 阅读 `tbgd/lowering.py` 中 `OnWaveMonster` blocked dependency。
- [ ] 阅读 `validate_v0_285.py`、`validate_v0_286.py` 中 wave event blocked 旧预期。
- [ ] 阅读 P1-1 `systems/unit_lifecycle.py` 的 UnitSpawn/UnitRemove 接口。
- [ ] 抽样确认 TBGD `StageConfig` 的 `_Wave`、`MonsterList` 结构。

验收结果：

- [ ] 实现报告列出当前行为和 P1-2 改动范围。
- [ ] 明确哪些旧验证需要更新预期。
- [ ] 没有读取旧 v7 作为 runtime 依据。

### P1-2-B Canonical WaveDefinition

目标：

- 让 runtime 有可追溯的 wave definition 输入。

需要做：

- [ ] 在 `rules/ir.py` 新增 WaveDefinition/entry IR，或等价 canonical 结构。
- [ ] 在 `CanonicalIR` 中加入 wave definitions。
- [ ] 在 `tbgd/lowering.py` 降 StageConfig wave data。
- [ ] 在 `RuleBook` 建索引。
- [ ] source trace 记录 raw evidence。
- [ ] blocked entry 不进入 executable spawn。

验收结果：

- [ ] 至少能从 TBGD 中选出一个 `wave_count >= 2` 的 stage definition。
- [ ] wave entries 数量与 MonsterList 结构一致。
- [ ] 每个 executable entry 有 monster entity/profile/card 来源。
- [ ] 缺 monster/profile/card 的 entry 被 blocked。

### P1-2-C Wave runtime state

目标：

- 让 battle state 能表达当前波次运行状态。

需要做：

- [ ] 定义 wave runtime schema。
- [ ] 保存 wave definition id / stage id。
- [ ] 保存 current wave index。
- [ ] 保存 total wave count。
- [ ] 保存 current wave unit ids。
- [ ] 保存 started/cleared wave indices。
- [ ] 保存 spawned/removed unit ids。
- [ ] 保存 status 和 blocked reason。
- [ ] snapshot 输出 wave runtime。
- [ ] 所有更新通过 mutation。

验收结果：

- [ ] 初始 state snapshot 有 `wave_runtime` 或等价字段。
- [ ] replay 后 wave runtime 一致。
- [ ] 没有在多个系统散落维护 wave metadata。

### P1-2-D 初始 current wave setup

目标：

- 有 wave definition 的战斗只把当前波敌人放入 active battlefield。

需要做：

- [ ] scenario/setup 层根据 wave definition 构造 current wave units。
- [ ] 复用现有 profile/card 构造逻辑，避免复制整套 monster panel 组装。
- [ ] 给每个 current wave enemy 写入 flags：
  - `wave_definition_id`
  - `wave_index`
  - `wave_position`
  - `wave_entry_id`
  - `wave_member_kind="stage_wave_enemy"`
  - `wave_clear_policy="counts"`
  - source trace
- [ ] 不提前生成后续 wave 敌人，或若为了审计保存 definition，也必须 lifecycle 不 active 且不可 target。
- [ ] 初始化 action_value，优先使用 `TimelineSystem.full_action_value(unit.speed, rules.default_timeline_rule())`。
- [ ] 若 timeline rule 缺失，不得用默认 0 伪造行动轴 admission，应 blocked 或记录 timeline admission missing。

验收结果：

- [ ] current wave enemy 出现在 active enemy team。
- [ ] next wave enemy 不出现在普通 target candidates。
- [ ] current wave unit 可追溯到 wave entry source。
- [ ] 初始 action_value 来源可审计。

### P1-2-E WaveSystem 纯查询

目标：

- 提供不改变 state 的 wave transition 判断入口。

建议新增：

```text
systems/wave.py
```

推荐接口：

```python
WaveSystem(rules).view(state) -> WaveRuntimeView
WaveSystem(rules).plan_transition(state) -> WaveTransitionPlan
WaveSystem(rules).apply_transition(state, plan) -> WaveTransitionResult
WaveSystem(rules).blocked(...) -> WaveTransitionResult
```

需要做：

- [ ] `view` 输出 current wave、active wave enemies、blocking enemies、status。
- [ ] `plan_transition` 不产生 mutation。
- [ ] 当前 wave 未清时返回 `no_change`。
- [ ] 当前 wave 清且有 next wave 时返回 `advance_to_next_wave`。
- [ ] 当前 wave 清且无 next wave 时返回 `battle_victory`。
- [ ] ally 全部 defeated/removed 时返回 `battle_defeat`。
- [ ] 缺 wave definition 时返回 blocked 或 `not_configured`，不能 fallback 到猜测。
- [ ] active enemy 缺 wave membership 时 blocked。
- [ ] pending queue 存在时 blocked/waiting，不自动清理。

验收结果：

- [ ] 纯查询前后 snapshot hash 一致。
- [ ] blocked plan state unchanged。
- [ ] plan JSON 稳定。

### P1-2-F Wave clear 判定

目标：

- 正确判断当前 wave 是否已清。

需要做：

- [ ] 从 wave runtime 找 current wave unit ids。
- [ ] 使用 UnitLifecycle 判断 active/defeated/removed。
- [ ] current wave entries 全部 defeated/removed 才 clear。
- [ ] 如果存在 active `enemy` 且没有 wave membership，blocked。
- [ ] 如果存在 active enemy summon，默认 blocked，除非有明确 source/admission 证明 ignore。
- [ ] defeated 但未 removed 的 old wave enemy 不阻塞下一波，但进入 remove list。
- [ ] removed enemy 不阻塞。
- [ ] ally defeated 不影响 wave clear，但会影响 battle defeat。

验收结果：

- [ ] current wave 有 active enemy 时不 advance。
- [ ] current wave 全 defeated 时可 clear。
- [ ] active unknown enemy 阻塞 clear。
- [ ] active summon enemy 阻塞 clear 或按明确 policy 处理。

### P1-2-G Wave transition mutation

目标：

- 通过 mutation 推进 wave。

当前 wave 清且有下一波时，建议 mutation 顺序：

1. 对旧 wave 敌人 UnitRemove。
2. 更新 wave runtime：cleared current wave。
3. 更新 `wave_index` 到 next index。
4. UnitSpawn 下一波敌人。
5. 更新 wave runtime：started next wave、current wave unit ids。
6. 更新 phase/current_window。

需要做：

- [ ] 构造 UnitRemove mutations。
- [ ] 构造 `("wave_index",)` mutation。
- [ ] 构造 wave runtime metadata mutation。
- [ ] 构造 UnitSpawn mutations。
- [ ] 为新敌人写入 position/wave flags。
- [ ] 为新敌人写入 action_value。
- [ ] 为每个 mutation 写 source trace。
- [ ] settlement/process records 记录 wave transition。

验收结果：

- [ ] replay 后 old wave enemies lifecycle 为 removed。
- [ ] replay 后 wave_index 增加。
- [ ] replay 后 next wave enemies active。
- [ ] replay 后 snapshot 与 after snapshot 一致。
- [ ] settlement 可从 wave mutation 反查到 WaveDefinitionIR/StageConfig evidence。

### P1-2-H Battle victory / defeat

目标：

- 最后一波清空后能进入战斗结束状态。

需要做：

- [ ] final wave clear 时不再尝试 spawn。
- [ ] 设置 battle outcome，例如 `global_flags["battle_outcome"]="victory"`。
- [ ] 设置 phase/current_window，例如 `phase="ended"`、`current_window="battle_end"`。
- [ ] 产生 `battle.victory` process event。
- [ ] ally active count 为 0 时设置 defeat，除非已有更高优先级规则。
- [ ] battle ended 后 action availability 不暴露普通 action choices。
- [ ] battle ended 后 scheduler 不推进 timeline。

验收结果：

- [ ] final wave clear -> victory mutation/replay。
- [ ] all allies defeated -> defeat mutation/replay。
- [ ] battle ended 状态下普通 action blocked/state unchanged。

### P1-2-I Wave events and OnWaveMonster

目标：

- 给 `OnWaveMonster` 一个真实 runtime event source，但不伪执行 callback。

需要做：

- [ ] WaveSystem 在新 wave start 时产生 `wave.started` event。
- [ ] WaveSystem 对每个 spawned monster 产生 `wave.monster` event。
- [ ] event payload 包含 wave_definition_id、wave_index、unit_id、entry_id、position、source_trace。
- [ ] `event_dispatch.py` 中 `wave.monster -> OnWaveMonster` 的 alias 不再因 wave system missing 被 canonical blocked。
- [ ] `tbgd/lowering.py` 中 `OnWaveMonster` 的 runtime event source 改为 `("wave.monster",)`。
- [ ] downstream callback 是否 executable 仍由 status callback/ability task admission 决定。
- [ ] 缺 event payload、缺 source trace、缺 entry id 时 blocked/state unchanged。

验收结果：

- [ ] WaveSystem 生成的 `wave.monster` 可被 event dispatch 识别。
- [ ] `OnWaveMonster` family 不再因为 wave_system_missing 被整体 blocked。
- [ ] 未由 WaveSystem 产生的手写 `wave.monster` 缺 payload 时仍 blocked。
- [ ] 若 callback downstream 仍 unsupported，只产生 process-only blocked record，不产生假 mutation。

### P1-2-J Queue/window 边界

目标：

- P1-2 不抢 P1-5 的队列语义，但不能在 pending queue 未结算时推进波次。

需要做：

- [ ] WaveSystem 检查 state.queues。
- [ ] 如有 mandatory/selectable/unknown queue pending，transition plan 返回 blocked/waiting。
- [ ] 不自动删除 queue。
- [ ] 不自动执行 queue。
- [ ] 报告中说明 queue cleanup 留给 P1-5。

验收结果：

- [ ] pending queue 时 wave transition state unchanged。
- [ ] blocked reason 稳定。
- [ ] 无 pending queue 时 wave transition 可推进。

### P1-2-K Cross-wave carry policy

目标：

- 明确跨波保留/清理策略，避免实现线程凭感觉改状态。

P1-2 默认：

- [ ] 保留 ally HP。
- [ ] 保留 ally energy。
- [ ] 保留 skill points / max skill points。
- [ ] 保留 ally statuses/modifiers。
- [ ] 保留 ally resources。
- [ ] 保留 global AV / turn sequence，除非实现线程能证明 timeline rule 要求重置。
- [ ] 不清理 summon，active enemy summon 默认阻塞 wave transition。
- [ ] 不清理 queue，pending queue 默认阻塞 wave transition。

验收结果：

- [ ] wave transition 不产生无来源的 ally resource/status mutation。
- [ ] report 写清楚哪些跨波行为仍 blocked 或留给后续阶段。

### P1-2-L Action availability / scheduler 接入

目标：

- 外部推演器能看到当前需要先推进 wave，还是战斗已结束。

需要做：

- [ ] 在 action availability view 中暴露 wave transition 状态或 blocked reason。
- [ ] 当前 wave clear 且可 advance 时，普通 action choices 不应继续暴露旧波敌人 target。
- [ ] 如果设计为 executor 自动追加 wave transition，availability 至少要在 after state 反映新 wave。
- [ ] battle ended 时 availability status 为 blocked/ended，不暴露 action choices。
- [ ] no actor 且 wave 可推进时，不应只报 `no_admitted_actor`，要能提示 wave transition。

验收结果：

- [ ] current wave active enemy 存在时 availability 正常。
- [ ] wave clear waiting transition 时 availability 可观测。
- [ ] battle victory/defeat 时 availability 不暴露普通动作。

### P1-2-M Source audit / settlement

目标：

- wave transition 的每个 state mutation 都能追溯来源。

需要做：

- [ ] 为 wave_index mutation 写 source_trace。
- [ ] 为 UnitRemove mutation 写 wave transition source_trace。
- [ ] 为 UnitSpawn mutation 写 wave entry source_trace。
- [ ] settlement record 记录 `record_type="wave_transition"` 或等价类型。
- [ ] process-only blocked cases 记录 skipped/blocked record。
- [ ] source audit 能识别 WaveDefinitionIR/entry/source evidence。

验收结果：

- [ ] 从 UnitSpawn mutation 可反查到 WaveMonsterEntryIR。
- [ ] 从 wave_index mutation 可反查到 WaveDefinitionIR。
- [ ] 从 `wave.monster` event 可反查到 spawned unit 和 source entry。
- [ ] blocked/audit_only/discovered_only 不产生 mutation。

### P1-2-N 验证矩阵

目标：

- 覆盖正例、负例、replay、source audit、旧回归。

建议新增：

```text
simulator_v8_clean_core/tools/validate_p1_2_wave_system.py
```

需要覆盖：

- [ ] WaveDefinition lowering 正例。
- [ ] 结构化选择一个 `wave_count >= 2` 且 monster entries 可 executable 的 stage，不按固定 StageID。
- [ ] initial current wave setup。
- [ ] pure query no mutation。
- [ ] current wave 未清不推进。
- [ ] current wave clear 正例。
- [ ] old wave UnitRemove replay。
- [ ] wave_index mutation replay。
- [ ] next wave UnitSpawn replay。
- [ ] next wave monsters targetable。
- [ ] next wave monsters timeline eligible，且 action_value 来源可审计。
- [ ] final wave clear -> battle victory。
- [ ] all allies defeated -> battle defeat。
- [ ] missing wave definition blocked/state unchanged。
- [ ] blocked wave entry 不 spawn。
- [ ] active unknown enemy blocks clear。
- [ ] active enemy summon blocks clear 或按明确 policy 处理。
- [ ] pending queue blocks wave transition/state unchanged。
- [ ] `wave.monster` event payload 完整。
- [ ] `OnWaveMonster` 由 WaveSystem event 接通。
- [ ] fake/incomplete `wave.monster` event blocked。
- [ ] source audit。
- [ ] static checks。

验收结果：

- [ ] 新 validation 输出 `ok=true`。
- [ ] 每个 mutation case replay 通过。
- [ ] 每个 blocked case state unchanged。
- [ ] 每个 executable mutation source audit 通过。
- [ ] selection policy 明确没有按固定角色名/怪物名/StageID 选择主样例。

### P1-2-O 回归验证

目标：

- 确保 P1-2 不破坏已通过底座。

至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_285 --output-dir /tmp/hsr_v8_v0_285_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_v0_286_after_p1_2
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p1_2
git diff --check
```

注意：

- P1-1 验收时 `validate_v0_264` 已存在既有失败豁免。P1-2 实现线程应继续记录它，不要把该失败误判为 P1-2 新回归。
- `validate_v0_285` / `validate_v0_286` 之前断言 `OnWaveMonster` blocked。P1-2 接通真实 wave source 后，旧断言需要升级：
  - 无 WaveSystem payload 的 fake event 仍 blocked。
  - WaveSystem 产生的完整 `wave.monster` event 可作为 `OnWaveMonster` source。

验收结果：

- [ ] compileall 通过。
- [ ] P1-0 回归通过。
- [ ] P1-1 回归通过。
- [ ] P1-2 新验证通过。
- [ ] v0_283 回归通过。
- [ ] v0_285/v0_286 预期已正确更新。
- [ ] v0_289 回归通过。
- [ ] static checks 通过。
- [ ] v0_264 既有失败状态被如实记录。

### P1-2-P 文档和 checklist

目标：

- 让后续阶段知道 WaveSystem 已支持什么、还不能做什么。

需要做：

- [ ] 新增 live validation report。
- [ ] 报告说明 WaveDefinition 来源。
- [ ] 报告说明 runtime 不读取 raw StageConfig。
- [ ] 报告说明 wave runtime schema。
- [ ] 报告说明 UnitSpawn/UnitRemove 如何用于 wave transition。
- [ ] 报告说明 OnWaveMonster 接通范围。
- [ ] 报告说明 cross-wave carry policy。
- [ ] 报告说明 pending queue/summon/status 的 blocked 范围。
- [ ] 勾选 `FIRST_PHASE_TASK_CHECKLIST.md` 中 P1-2 已完成项。

验收结果：

- [ ] 后续 P1-3 可以复用 wave membership 和 clear policy。
- [ ] 后续 P1-4 可以基于 wave event 做状态清理/tick。
- [ ] 后续 P1-5 可以基于 wave transition waiting reason 做 queue/window 扩展。
- [ ] 总清单状态和实际实现一致。

## 5. 建议实现顺序

推荐顺序：

1. 做 WaveDefinition IR 和 RuleBook API。
2. 做 StageConfig -> WaveDefinition lowering。
3. 做 wave runtime schema 和 snapshot 输出。
4. 扩展 scenario/setup，让初始 current wave units 带 wave membership。
5. 新增 `systems/wave.py` 纯查询 view/plan。
6. 实现 current wave clear 判定。
7. 实现 old wave UnitRemove + wave_index mutation。
8. 实现 next wave UnitSpawn。
9. 给 spawned units 初始化 action_value。
10. 实现 final victory/defeat。
11. 生成 `wave.started` / `wave.monster` events。
12. 接通 `OnWaveMonster` runtime event source。
13. 接入 action availability/scheduler 的 wave 状态观测。
14. 写 `validate_p1_2_wave_system.py`。
15. 更新 v0_285/v0_286 中 wave event blocked 旧预期。
16. 跑 P1-0/P1-1/P1-2/v0_283/v0_285/v0_286/v0_289 回归。
17. 更新 live validation report 和 checklist。

不要先写 executor 自动推进再补来源。先把 pure plan/source/replay 做稳，再接执行入口。

## 6. P1-2 最终验收

只有以下全部满足，才能勾选 `P1-2-DONE`：

- [ ] 存在 WaveDefinition IR 或等价 canonical setup。
- [ ] WaveDefinition 来源可追溯到 TBGD StageConfig evidence。
- [ ] runtime 不读取 raw StageConfig/TextMap/旧 v7/旧 model pack。
- [ ] BattleState snapshot 能表达 wave runtime。
- [ ] current wave enemy 有 wave membership。
- [ ] WaveSystem pure query 不改变 state。
- [ ] current wave clear 判定使用 UnitLifecycle。
- [ ] active unknown enemy 不会被忽略。
- [ ] active enemy summon 缺 admission 时阻塞 wave clear 或按明确 policy 处理。
- [ ] pending queue 不会被 WaveSystem 擅自清理或跳过。
- [ ] old wave enemies 通过 UnitRemove 或等价 tombstone 退场。
- [ ] wave_index 通过 mutation 改变。
- [ ] next wave enemies 通过 UnitSpawn 生成。
- [ ] next wave enemies 有 profile/card/source trace。
- [ ] next wave enemies 初始 action_value 来源可审计，不能靠默认 0 偷跑。
- [ ] final wave clear 产生 battle victory。
- [ ] all allies defeated 产生 battle defeat 或明确 blocked/end 策略。
- [ ] `wave.monster` event 由 WaveSystem 产生。
- [ ] `OnWaveMonster` 只在真实 wave event source 下接通。
- [ ] fake/incomplete wave event blocked/state unchanged。
- [ ] replay 通过。
- [ ] source audit 通过。
- [ ] blocked/audit_only/discovered_only 不产生 mutation。
- [ ] 没有角色名、怪物名、StageID、固定文件名主路径硬编码。
- [ ] 新增/更新验证报告。

## 7. 禁止事项

P1-2 实现中明确禁止：

- 禁止 runtime 直接读取 `StageConfig.json`。
- 禁止把 `_Wave`、`MonsterList` raw schema 解析写进 runtime。
- 禁止按固定 StageID、怪物 ID、文件名选择主验证路径。
- 禁止没有 WaveDefinition source 就生成下一波。
- 禁止 spawn 怪物使用默认 profile/card/source。
- 禁止新波怪物 action_value 默认为 0 后直接参与行动轴，除非有明确 timeline source。
- 禁止忽略 active unknown enemy 后提前进入下一波。
- 禁止把 enemy summon 当作已支持完整规则，除非 P1-3 admission 已完成。
- 禁止 WaveSystem 擅自清空 queue。
- 禁止无来源清理 ally status/resource。
- 禁止只发 `wave.monster` process event，不产生必要 wave/spawn mutation。
- 禁止把 `OnWaveMonster` callback 无条件标成 executable。
- 禁止从日志事后反推 wave settlement。

## 8. P1-2 之后的交接点

P1-2 完成后，后续阶段应接着做：

- P1-3 Summon/Assistant/Servant：复用 wave membership 和 clear policy，解决 enemy summon 是否计入清场、owner death、lifetime。
- P1-4 状态系统：基于 `wave.started` / `wave.cleared` / `battle.end` 做状态 duration/tick/cleanup。
- P1-5 Queue/Window：把 wave transition 放进正式窗口顺序，处理 pending queue cancel/drain。
- P1-8 Scenario/UI：让 UI 能选择 stage/wave setup，并展示 wave audit。
- P1-9 phase acceptance：把多波战斗纳入最小完整闭环验收。

P1-2 的核心不是一次复刻所有关卡机制，而是把“当前波是谁、何时清场、如何生成下一波、如何结束战斗”变成干净、可追溯、可 replay 的通用系统。
