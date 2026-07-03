# P1-8 最小战斗配置入口总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-8 最小战斗配置入口` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-8 的实现、验证和阶段报告。

P1-8 的一句话目标：

```text
把第一阶段已经做出的单位生命周期、波次、召唤、状态、队列、目标和 RNG 底座，接到一个结构化、可验证、可审计的 BattleSetup / ScenarioSpec 配置入口上，让验证战斗不再依赖手写 BattleState。
```

P1-8 不是新规则系统，也不是 UI 表单工程。它是“初始战斗状态组装层”：

- 可以描述参战单位、当前波次、初始资源、初始 HP/能量、初始状态、初始召唤物、初始 timeline、RNG ledger 和目标元数据。
- 必须通过 RuleBook / Canonical IR / 数据卡 IR 校验机制引用。
- 不能把 scenario JSON 里的任意字段当成规则事实。
- 不能绕过 v8 core 的 mutation、source audit、blocked/state unchanged 口径。

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终使用方式不是让 core 自己做敌方 AI，而是：

```text
外部推演器枚举路线、目标和随机分支
-> v8 core 校验输入是否合法
-> v8 core 执行规则并输出完整 BattleTransition / snapshot / settlement / audit
-> 外部推演器搜索达成目标的通关路线
```

因此 P1-8 的配置入口要服务两类使用者：

1. 验证脚本和本地 UI：能方便构造第一阶段覆盖用例。
2. 未来推演器：能从结构化 setup 生成初始状态和 route command，不需要手写 Python `BattleState`。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

Scenario / BattleSetup 只描述“这场战斗的初始条件”和“路线输入”，不能定义技能、状态、召唤、敌人、伤害公式或机制语义。

### 0.2 P1-8 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

前置阶段状态：

- P1-0：Action Boundary 已能输出合法行动候选和 transition。
- P1-1：UnitLifecycle 已有 active / defeated / removed 语义。
- P1-2：WaveSystem 已能从真实 wave definition 生成当前波、推进下一波。
- P1-3：Summon / Assistant / Servant 已有最小分类和 runtime schema。
- P1-4：StatusSystem 已有状态生命周期、chance/resist、DoT、dispel、control gating 的底座和 source gap 口径。
- P1-5：Queue / Window 已有可审计的队列和窗口语义。
- P1-6：TargetSystem 已有目标表达式、random target、adjacent、fetch、unique 等第一阶段底座。
- P1-7：RNG branch 已有统一 RNG request / event schema，`rng_choices`、`rng_mode` 可通过 command metadata 传入。

P1-8 的职责是把这些能力接到 setup 层：

```text
Scenario JSON / dict
-> ScenarioLoader
-> ScenarioSpec / BattleSetupSpec
-> IdentityResolver + setup validator
-> ScenarioStateBuilder
-> BattleState + route ActionCommand + setup audit records
```

### 0.3 当前代码事实

当前主要文件：

```text
scenarios/schema.py
scenarios/loader.py
scenarios/identity.py
scenarios/build_state.py
scenarios/README.md
core/model.py
systems/status.py
systems/summon.py
systems/timeline.py
systems/rng.py
simulator_v8_ui/runner.py
simulator_v8_ui/report.py
tools/validate_v0_204.py
tools/validate_p1_2_wave_system.py
tools/validate_p1_3_summon_assistant_servant.py
tools/validate_p1_4_status_system.py
tools/validate_p1_7_rng_branch_system.py
```

当前已有能力：

- `ScenarioSpec` 已有 `units`、`route`、`skill_points`、`max_skill_points`、`wave_index`、`wave_definition_ref`、`stage_ref`、`rng_state`、`global_flags`。
- `ScenarioLoader` 可以从 JSON dict/path 构造 `ScenarioSpec`。
- `IdentityResolver` 会校验 unit entity_ref、route actor/target、action_ref/action_level。
- `ScenarioStateBuilder.build()` 已经是当前唯一的 v8 scenario -> `BattleState` 入口。
- `ScenarioStateBuilder` 已能从 `wave_definition_ref` / `stage_ref` 自动生成当前波敌人，并写入 `wave_runtime`。
- `ScenarioStateBuilder` 已能从角色数据卡/怪物卡应用部分 startup ability effect。
- `UnitSpec.panel` 已能表达 max_hp、hp、attack、defense、speed、energy、max_energy、toughness、action_value、resources、flags、statuses。
- UI runner 当前也使用 `ScenarioLoader` + `ScenarioStateBuilder`，所以 P1-8 应扩展这条链路，而不是另开旁路。
- `validate_v0_204` 是早期 scenario 验证，但它会全量 discovery/lowering 并默认写完整 `canonical_ir` / coverage / fidelity，不适合作为 P1-8 主验证。

当前缺口：

- 没有独立的 `BattleSetupSpec` 或等价结构，setup 语义分散在 root 字段、unit panel、route metadata、global_flags。
- `panel.statuses` 只是字符串集合，不能表达 P1-4 的 `status_details`、instance identity、duration、stack、source audit。
- 初始 summon / servant 没有结构化配置入口，当前只能手写 `UnitState` 或让 action 过程中产生。
- `rng_choices` / `rng_mode` 只能在 route step metadata 里手写，没有 scenario-level setup。
- `objective` 只能塞进 `global_flags`，没有被识别为“给外部推演器使用、不参与规则执行”的元数据。
- setup 子对象缺少系统性 negative validation，例如 unknown status effect、unknown summon intent、invalid owner、invalid hp_ratio、invalid rng setup。
- 当前 loader 对新增复杂字段没有结构化类型校验。

## 1. P1-8 的非目标

P1-8 不做以下内容：

- 不做敌方 AI、自动行动策略或路线搜索。
- 不做完整 UI 表单重构；UI 原始 JSON 编辑器能 roundtrip 新字段即可。
- 不引入新依赖。
- 不从旧 v7、旧 model pack、旧 compiled case 或观测战斗结果读取规则。
- 不让 scenario JSON 定义技能效果、状态公式、召唤行为、敌方被动或行动逻辑。
- 不把 `global_flags` 当成任意机制注入入口；新增 setup 能力必须有结构化 schema 和 validator。
- 不为 source gap 机制伪造正例，例如 servant 仍无可执行来源时不能直接创建 servant runtime。
- 不要求 P1-8 解决完整角色面板装配、光锥、遗器、环境、关卡机制。
- 不运行高 IO 全量验证作为默认主验证。

## 2. 设计原则

### 2.1 Setup 是初始条件，不是规则来源

Setup 可以说：

- 本场战斗有这些单位。
- 当前从第几波开始。
- 某单位进入战斗时 HP 是多少。
- 某单位一开始已经有一个由真实 EffectIR / status source 生成的状态。
- 某个 owner 一开始已经通过真实 summon intent 产生了召唤怪。
- 本场 route 使用这些 RNG choices。
- 外部推演目标是击败敌人或保持某单位存活。

Setup 不能说：

- 这个状态提供 30% 攻击力，因为 scenario 写了一个 modifier。
- 这个召唤物会执行某个技能，因为 scenario 塞了一个 ability。
- 这个怪物有某个被动，因为 scenario 写了一个 flag。
- 这个 action 的伤害公式是某个手写表达式。

### 2.2 扩展现有 ScenarioSpec，不新开旁路

P1-8 应继续使用：

```text
ScenarioLoader -> ScenarioSpec -> ScenarioStateBuilder -> BattleState
```

可以新增 `BattleSetupSpec` / `RNGSetupSpec` / `InitialStatusSpec` 等 dataclass，但它们应挂在 `ScenarioSpec` 上。当前 root-level 字段作为 v8 现有 scenario 的兼容入口保留：

- `skill_points`
- `max_skill_points`
- `wave_index`
- `wave_definition_ref`
- `stage_ref`
- `rng_state`
- `global_flags`
- `units`
- `route`

新增推荐 JSON 可以使用一个结构化对象，例如：

```json
{
  "battle_setup": {
    "wave": {},
    "resources": {},
    "timeline": {},
    "rng": {},
    "initial_statuses": [],
    "initial_summons": [],
    "objective": {}
  }
}
```

实现时可以接受 `battle_setup` 或 `setup` 作为别名，但内部只保留一种 canonical dataclass。不要让多个字段长期并列成两套语义。

### 2.3 Setup build 也要可审计

建议扩展 `ScenarioBuildResult`，增加可选审计字段：

```python
setup_records: tuple[dict[str, JSONValue], ...] = ()
setup_mutations: tuple[Mutation, ...] = ()
setup_events: tuple[GameEvent, ...] = ()
setup_rng_events: tuple[RNGEvent, ...] = ()
blocked_setup: tuple[dict[str, JSONValue], ...] = ()
```

已有调用者只读取 `state`、`commands`、`source_traces`，新增字段应有默认值，避免破坏当前 v8 UI 和验证脚本。

凡是“从 base units 之后进一步改变状态”的 setup 操作，例如应用 initial status、spawn initial summon，应优先调用现有系统并通过 `MutationReducer` 应用 mutation，不要直接改 `flags["status_details"]` 或 `global_flags["summon_runtime"]`。

### 2.4 构建顺序必须固定

建议 P1-8 明确并验证以下顺序：

1. 解析 scenario JSON。
2. 解析 root-level legacy 字段和 `battle_setup` 字段，合成 canonical setup。
3. 根据 `wave_definition_ref` / `stage_ref` / `battle_setup.wave` 生成当前波单位。
4. 校验 unit/action/status/summon/wave 引用。
5. 构造基础 `UnitState` 和 `BattleState`。
6. 应用角色/怪物数据卡 startup effect。
7. 按 setup 声明顺序应用 initial statuses。
8. 按 setup 声明顺序应用 initial summons。
9. 应用 timeline setup 或标记由 runtime scheduler 初始化。
10. 应用 rng setup 到 `BattleState.rng_state`、route command metadata 和 setup audit。
11. 写入 objective metadata，但不影响规则执行。

如果某一步 blocked，必须明确记录 blocked reason。不能跳过失败后仍声称 setup 完整。

### 2.5 三态验收口径

P1-8 每个 setup 子机制也按三态判断：

- `executable`：当前 RuleBook / Canonical IR / 数据卡 IR 或纯 setup 初始条件足够，能构建 state，审计记录完整。
- `source_gap_blocked`：请求了需要真实来源的机制，但当前来源缺失或 admission blocked；只能记录 blocked，不创建 fake runtime entity / fake status / fake mutation。
- `implementation_missing`：真实来源存在，现有 builder 还不能接入，这才是 P1-8 需要编码补齐的缺口。

另有一类 `invalid_config`：

- JSON shape 错、引用不存在、unit_id 重复、target 不存在、hp_ratio 越界等属于配置错误。
- 这类应 fail fast，通常抛 `ValueError` 或返回 validation error，不能降级为默认值。

## 3. 建议 schema

具体命名允许执行线程按代码风格微调，但语义应保持稳定。

### 3.1 BattleSetupSpec

建议新增：

```python
@dataclass(frozen=True)
class BattleSetupSpec:
    resources: SetupResourceSpec = field(default_factory=SetupResourceSpec)
    wave: WaveSetupSpec | None = None
    timeline: TimelineSetupSpec | None = None
    rng: RNGSetupSpec | None = None
    initial_statuses: tuple[InitialStatusSpec, ...] = ()
    initial_summons: tuple[InitialSummonSpec, ...] = ()
    objective: ObjectiveSpec | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
```

`ScenarioSpec` 新增：

```python
battle_setup: BattleSetupSpec = field(default_factory=BattleSetupSpec)
```

root-level `skill_points`、`max_skill_points`、`wave_index`、`wave_definition_ref`、`stage_ref`、`rng_state` 继续保留，但 loader 应把它们同步进 canonical setup，或在 builder 中用统一 helper 读取，避免两套逻辑分叉。

### 3.2 Resource / panel setup

已有 `PanelInput` 可扩展：

```python
hp_ratio: float | None = None
energy_ratio: float | None = None
```

验收规则：

- `hp` 和 `hp_ratio` 同时出现时必须报错，避免歧义。
- `hp_ratio` 必须在 `[0, 1]`，构建后 `hp = max_hp * hp_ratio`。
- `energy` 和 `energy_ratio` 同时出现时必须报错。
- `energy_ratio` 必须在 `[0, 1]`，且需要 `max_energy > 0`。
- `skill_points` / `max_skill_points` 保持 battle-level 资源，不能塞进单位资源。
- `resources` 只能表示 runtime 初始资源数值，例如 `critical_chance`、`effect_resistance`、`shield`；不能表示状态 modifier 规则。

### 3.3 WaveSetupSpec

已有 root-level `wave_definition_ref` / `stage_ref`，loader 也支持 `wave_setup` 的旧 shape。P1-8 应 formalize：

```python
@dataclass(frozen=True)
class WaveSetupSpec:
    kind: Literal["none", "stage", "wave_definition"] = "none"
    stage_ref: str | None = None
    wave_definition_ref: str | None = None
    wave_index: int = 0
```

验收规则：

- `stage_ref` 必须能通过 `RuleBook.wave_definition_for_stage()` 找到 definition。
- `wave_definition_ref` 必须能通过 `RuleBook.wave_definition()` 找到 definition。
- 当前 wave 的 entries 如果不是 executable，应记录 blocked，不生成 fake enemies。
- 当前 wave 生成的 enemy unit 必须带 wave membership flags 和 source trace。
- 下一波单位初始时不应该出现在 `state.units`，只存在于 `wave_runtime` 可推进信息中。

### 3.4 InitialStatusSpec

建议新增：

```python
@dataclass(frozen=True)
class InitialStatusSpec:
    target_id: str
    source_id: str
    effect_ref: str | None = None
    owner_id: str | None = None
    caster_id: str | None = None
    param_entity_id: str | None = None
    current_action_target_id: str | None = None
    dynamic_values: dict[str, float] = field(default_factory=dict)
    rng_choices: dict[str, JSONValue] = field(default_factory=dict)
    rng_mode: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
```

P1-8 主路径只支持 source-backed initial status：

```text
InitialStatusSpec.effect_ref -> RuleBook.effect(effect_ref) -> StatusSystem.apply_add_modifier()
```

验收规则：

- `effect_ref` 必须存在，且 effect opcode 必须是 `AddModifier`。
- effect coverage 必须 executable；否则 blocked/no mutation。
- status application 必须复用 `StatusSystem.apply_add_modifier()`，不能直接写 `flags["status_details"]`。
- 如果状态命中需要 RNG，必须走 P1-7 的 `rng_choices` / `rng_mode`，并记录 setup_rng_events。
- failed chance / resisted / immunity / blocked 不产生 status mutation。
- 构建结果中要能看到 status detail、status instance id、source_stack_key、duration/stack/source_trace。
- 不允许 scenario 直接写 arbitrary modifier term 当规则。

可以暂缓支持 direct status detail snapshot injection。如果必须支持，也只能作为 `setup_only_snapshot`，必须带 source trace，并明确不用于机制正例验收。

### 3.5 InitialSummonSpec

建议新增：

```python
@dataclass(frozen=True)
class InitialSummonSpec:
    kind: Literal["summoned_monster", "battle_unit_summon", "servant"] = "summoned_monster"
    owner_id: str
    summon_intent_ref: str | None = None
    unit_id: str | None = None
    entity_ref: str | None = None
    position: int | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
```

主路径：

- `summoned_monster`：必须通过 `SummonSystem.plan_spawn_summoned_monster()` + `apply_transition()`，来源来自 `SummonMonsterIntentIR`。
- `battle_unit_summon`：只有在 `summon_unit_definition` source/admission 足够时才创建；否则 blocked。
- `servant`：当前如果 servant definitions 仍 blocked，只能记录 source gap，不创建 fake unit/runtime component。

验收规则：

- owner 必须存在且 active。
- 召唤物 unit 必须带 owner_id、summon_kind、summon source trace、timeline admission 等 runtime flags。
- `summon_runtime` 必须能追踪 by_owner / active_summons / servants。
- source gap 不创建 UnitState，不写 fake summon_runtime。

### 3.6 TimelineSetupSpec

建议新增：

```python
@dataclass(frozen=True)
class TimelineSetupSpec:
    mode: Literal["runtime_initialize", "explicit_action_values"] = "runtime_initialize"
    global_av: float = 0.0
    turn_owner_id: str | None = None
    action_values: dict[str, float] = field(default_factory=dict)
    explicit_overrides: tuple[str, ...] = ()
```

验收规则：

- `runtime_initialize`：builder 不强行计算所有 AV，只记录 scheduler 应初始化；UI runner / scheduler 继续负责初始化。
- `explicit_action_values`：必须校验每个 unit_id 存在，action_value 非负，并写入 UnitState。
- 如果设置 `turn_owner_id`，必须是现有 active unit。
- 不能因为缺 timeline setup 就默认让召唤物可行动；召唤物 timeline admission 仍由 summon flags / systems 判断。

### 3.7 RNGSetupSpec

建议新增：

```python
@dataclass(frozen=True)
class RNGSetupSpec:
    rng_state: str = "deterministic"
    rng_mode: str | None = None
    rng_choices: dict[str, JSONValue] = field(default_factory=dict)
```

验收规则：

- `rng_state` 写入 `BattleState.rng_state`。
- `rng_mode` / `rng_choices` 默认注入 route `ActionCommand.metadata`，但 route step 自己的 metadata 可以覆盖。
- 主验证里的 `rng_choices` 应优先使用精确 `choice_key` 或 `event_id`，不要用 `default` 冒充具体分支。
- invalid `rng_mode` 不在 setup 阶段假装通过；可以由 runtime RNG resolver blocked，但 setup validation 应至少确认类型正确。
- scenario-level RNG 是 route input，不是规则来源。

### 3.8 ObjectiveSpec

建议新增：

```python
@dataclass(frozen=True)
class ObjectiveSpec:
    objective_id: str
    kind: str
    payload: dict[str, JSONValue] = field(default_factory=dict)
```

验收规则：

- objective 只写入 `global_flags["objective"]` 或 build report。
- objective 不影响 action availability、target resolution、damage、status、queue、wave。
- P1-8 不解释完整胜利条件，只为 P1-9 聚合报告和未来搜索器预留。

## 4. 实现任务拆解

### P1-8.1 审查现有 scenario 入口

- 目标：确认当前 `ScenarioSpec`、loader、identity、builder、UI runner 的真实能力和调用者。
- 要做：
  - 阅读 `scenarios/schema.py`、`loader.py`、`identity.py`、`build_state.py`。
  - 阅读 `simulator_v8_ui/runner.py` 和 `report.py` 中 scenario roundtrip 相关函数。
  - 记录 `validate_v0_204` 的资源风险，不能把它作为 P1-8 主验证。
- 验收结果：
  - P1-8 报告列出当前已有字段、缺口、调用者和兼容边界。
- 禁止：
  - 不新建绕过 `ScenarioStateBuilder` 的独立 builder。

### P1-8.2 定义 BattleSetup schema

- 目标：形成结构化 setup dataclass，收束 root-level 分散字段。
- 要做：
  - 在 `scenarios/schema.py` 增加 `BattleSetupSpec` 及子 spec。
  - `ScenarioSpec` 增加 `battle_setup` 字段。
  - 保留当前 root-level 字段作为现有 v8 scenario 输入，内部合成 canonical setup。
- 验收结果：
  - 旧 `identity_smoke_v0_204.json` 仍可加载。
  - 新 `battle_setup` JSON 可加载并 roundtrip 到 `ScenarioSpec`。
- 禁止：
  - 不要求用户一次性迁移所有现有 scenario JSON。

### P1-8.3 强化 loader 类型校验

- 目标：新增 setup 字段必须有明确类型错误，而不是被 `dict()` 或默认值吞掉。
- 要做：
  - 为 setup 子对象增加 `_optional_dict`、`_optional_float`、`_optional_str_dict` 等 helper。
  - 对 `hp_ratio`、`energy_ratio`、`rng_choices`、`initial_statuses`、`initial_summons` 做 shape validation。
- 验收结果：
  - invalid setup JSON 报具体字段路径，例如 `battle_setup.initial_statuses[0].effect_ref must be a string`。
- 禁止：
  - 不把错误字段静默丢弃后继续构建。

### P1-8.4 ally roster / enemy roster 配置

- 目标：明确现有 `units` 就是第一阶段 roster 配置入口，并补齐缺失的 ratio/resource 校验。
- 要做：
  - 支持 `PanelInput.hp_ratio` / `energy_ratio`。
  - 校验 entity_ref 类型和 side 匹配。
  - 校验 position 可选、level/eidolon 范围。
  - 保留 panel overrides 的 source trace 记录。
- 验收结果：
  - ally roster 正例能构建角色单位。
  - enemy roster 正例能从 combatant profile 补基础属性。
  - unknown entity、side/entity mismatch、hp/hp_ratio 同时出现均失败。
- 禁止：
  - 不用角色名、怪物名或固定 ID 写死主逻辑。

### P1-8.5 enemy waves 配置

- 目标：把 P1-2 wave setup 正式纳入 BattleSetup schema。
- 要做：
  - 支持 `battle_setup.wave.kind = "stage"` / `"wave_definition"`。
  - 复用 `_with_initial_wave_units()` 和 `_initial_wave_runtime()`。
  - 处理 root-level `wave_setup` 旧 shape 到新 schema 的映射。
- 验收结果：
  - two-wave TBGD source-backed setup 能生成当前波，下一波暂不在 `state.units`。
  - wave_runtime 包含 source_trace、current_wave_unit_ids、total_waves。
  - blocked wave entry 不生成 fake enemy。
- 禁止：
  - 不手写一套 scenario-only wave runtime 规则替代 `WaveSystem`。

### P1-8.6 battle resources 配置

- 目标：配置初始 SP、max SP、rng_state 等 battle-level 资源。
- 要做：
  - formalize `battle_setup.resources.skill_points/max_skill_points`。
  - root-level `skill_points/max_skill_points` 作为别名。
  - 校验 `0 <= skill_points <= max_skill_points`，除非未来明确支持 overcap。
- 验收结果：
  - 构建后的 `BattleState.skill_points` / `max_skill_points` 正确。
  - invalid SP 配置 fail fast。
- 禁止：
  - 不把 SP 写进某个 unit resource。

### P1-8.7 初始能量和 HP ratio

- 目标：支持常见验证场景直接写 HP 百分比和能量。
- 要做：
  - `hp_ratio` 在 max_hp/profile 解析之后计算 hp。
  - `energy_ratio` 在 max_energy 解析之后计算 energy。
  - 若 max_energy 缺失但写 energy_ratio，报错。
- 验收结果：
  - `hp_ratio=0.5` 的单位构建后 hp 为 max_hp 一半。
  - `energy_ratio=1.0` 的单位构建后 energy=max_energy。
  - 越界 ratio 和歧义字段失败。
- 禁止：
  - 不用默认 max_hp=1.0 掩盖怪物 profile 缺失。

### P1-8.8 initial statuses 配置

- 目标：能从配置给单位添加真实来源的初始状态。
- 要做：
  - 新增 `InitialStatusSpec` loader/schema。
  - 在 builder 中调用 `StatusSystem.apply_add_modifier()`。
  - 收集 setup mutations/events/rng_events/records/source traces。
  - 支持 per-status `rng_choices` / `rng_mode`，并可继承 scenario-level RNG setup。
- 验收结果：
  - 至少一个真实 AddModifier source-backed initial status 正例。
  - status detail 中有 instance_id、modifier_name、status_id、source_stack_key、duration/stack/source_trace。
  - failed chance/resisted/blocked 不产生 status mutation。
  - unknown effect_ref、non-AddModifier effect、blocked effect 均失败或 blocked，且不写状态。
- 禁止：
  - 不直接把 scenario JSON 里的 modifier dict 塞进 `status_details`。

### P1-8.9 initial summon / servant 配置

- 目标：能从配置设置第一阶段召唤相关初始状态，同时保持 source gap 诚实。
- 要做：
  - 新增 `InitialSummonSpec` loader/schema。
  - `summoned_monster` 复用 `SummonSystem` 和真实 summon intent。
  - `battle_unit_summon` / `servant` 按当前 source/admission 判断；无真实 executable 来源时 blocked/no unit。
  - 收集 setup mutations/events/records/source traces。
- 验收结果：
  - 真实 summon monster intent 正例能创建 summoned monster unit 和 summon_runtime。
  - owner missing / inactive owner / blocked summon source 不创建 fake unit。
  - servant 当前如仍 source gap，只记录 blocked，不标 executable。
- 禁止：
  - 不通过手写 flags 冒充 `summon_runtime`。

### P1-8.10 initial timeline 配置

- 目标：setup 能表达“由 runtime 初始化”或“显式 action value”两种模式。
- 要做：
  - 新增 `TimelineSetupSpec`。
  - `explicit_action_values` 写入 UnitState.action_value，并校验 unit_id。
  - `runtime_initialize` 只记录 setup policy，不提前伪造 scheduler result。
  - UI runner 的 `_explicit_action_value_unit_ids` 需要识别新 schema。
- 验收结果：
  - explicit AV 正例构建后 snapshot timeline.action_values 正确。
  - unknown unit_id / negative action value 失败。
  - 缺 timeline setup 时行为和当前 scenario 保持一致。
- 禁止：
  - 不给召唤物默认可行动资格。

### P1-8.11 deterministic RNG choices 配置

- 目标：scenario-level RNG setup 能进入 route command metadata。
- 要做：
  - 新增 `RNGSetupSpec`。
  - builder 构造 `ActionCommand` 时合并 scenario-level `rng_mode/rng_choices` 和 route-level metadata。
  - route-level metadata 优先级高于 scenario-level。
  - 记录 `scenario_rng_setup` 到 build records 或 global flags。
- 验收结果：
  - 通过 scenario-level `rng_choices` 可驱动 P1-7 target random / crit 等路径。
  - route-level override 生效。
  - invalid choice 在 runtime blocked，并带 available outcomes。
- 禁止：
  - 主验证不要用 `rng_choices.default` 冒充具体分支。

### P1-8.12 objective metadata 预留

- 目标：给未来推演器保存目标描述，但不影响规则执行。
- 要做：
  - 新增 `ObjectiveSpec`。
  - 写入 `global_flags["objective"]` 或 build report。
  - UI/report roundtrip 显示 objective。
- 验收结果：
  - objective 存在于 snapshot metadata/global_flags。
  - 同一 setup 去掉 objective 后，规则 transition 结果不变。
- 禁止：
  - P1-8 不解释 objective，也不让 objective 改 action availability。

### P1-8.13 确保配置入口不成为规则来源

- 目标：把“初始条件”和“机制规则”边界写进代码与验证。
- 要做：
  - 对 initial status / summon 只接受 source refs，不接受手写机制 payload。
  - build records 区分 `source_kind=scenario_initial_condition` 和真实 IR source。
  - 增加静态检查，确认 `scenarios/` 不读取 raw TBGD/TextMap/旧 model pack。
- 验收结果：
  - P1-8 validation 有 no-rule-injection checks。
  - README 明确 scenario 只能引用规则，不能定义规则。
- 禁止：
  - 不把 `engine_convention` 或 `scenario` 伪装成 TBGD 机制来源。

### P1-8.14 two-wave setup 验证

- 目标：证明配置入口能构建两波战斗起点。
- 要做：
  - 结构化选择真实 executable multi-wave `WaveDefinitionIR`。
  - 构造 scenario，使用 `battle_setup.wave`。
  - 检查当前波单位、下一波 absent、wave_runtime、source_trace。
- 验收结果：
  - `checks.two_wave_setup.ok == true`。
  - 选择策略按结构化谓词，不固定 stage ID。
- 禁止：
  - 不使用固定怪物名/固定 stage id 作为主样例选择。

### P1-8.15 initial statuses setup 验证

- 目标：证明配置入口能创建真实来源初始状态。
- 要做：
  - 结构化选择 executable AddModifier effect。
  - 构造 initial status setup。
  - 检查 status_details、mutation/source audit、blocked negative。
- 验收结果：
  - success status 有 source-backed detail。
  - invalid/non-AddModifier/blocked effect 不写状态。
- 禁止：
  - 不用 synthetic AddModifier 做正例 mutation。

### P1-8.16 initial summon setup 验证

- 目标：证明配置入口能创建真实来源召唤怪，且 servant source gap 诚实。
- 要做：
  - 结构化选择 executable SummonMonsterIntentIR。
  - 构造 owner 和 initial summon setup。
  - 检查 UnitSpawn / summon_runtime / source trace。
  - 若 servant 仍无 executable source，记录 source gap negative。
- 验收结果：
  - summon monster 正例通过。
  - blocked source/no owner 不创建 unit。
- 禁止：
  - 不手写 summoned unit flags 作为正例。

### P1-8.17 deterministic rng setup 验证

- 目标：证明 scenario-level RNG setup 能驱动 action command。
- 要做：
  - 构造带 `rng_mode` / `rng_choices` 的 scenario。
  - 选择一个轻量随机路径，例如 P1-7 target random 或 crit contract。
  - 执行同一 before + command 两次，验证 replay 稳定。
- 验收结果：
  - command metadata 包含合并后的 RNG setup。
  - transition rng_events 有统一 schema。
  - missing/invalid choice blocked 且 available outcomes 存在。
- 禁止：
  - 不使用进程随机。

### P1-8.18 不存在 card/profile/source 构建失败或 blocked 验证

- 目标：坏配置不能被默认值掩盖。
- 要做：
  - unknown unit entity_ref。
  - monster profile required stat missing。
  - unknown status effect_ref。
  - unknown summon intent。
  - invalid wave reference。
  - invalid hp_ratio / energy_ratio。
- 验收结果：
  - 每类都有明确错误或 blocked record。
  - state unchanged 或 build failed；不能产生部分 fake state 后继续声称 ok。
- 禁止：
  - 不 fallback 到默认 monster stats / default status / default summon。

### P1-8.19 更新文档和阶段报告

- 目标：让后续线程知道 P1-8 的边界和使用方法。
- 要做：
  - 更新 `scenarios/README.md`。
  - 新增 `live_validation_reports/v8_p1_8_battle_setup_checkpoint.md`。
  - 报告说明完成范围、source gap、资源验证范围、距离第一阶段闭环剩余内容。
- 验收结果：
  - 文档包含 JSON 示例、禁止事项、source/admission 口径。
- 禁止：
  - 不只写“验证通过”。

### P1-8.20 UI runner/report 最小 roundtrip

- 目标：当前本地 UI 测试台不会因为新增字段丢失 setup 信息。
- 要做：
  - 更新 `simulator_v8_ui/report.py::scenario_to_json()` 输出新增 setup 字段。
  - `runner.py` 使用新 ScenarioSpec，不绕过 builder。
  - 不需要做复杂表单控件；raw JSON 能编辑即可。
- 验收结果：
  - UI validation 仍能加载旧 case。
  - 新 setup 字段不会在 report roundtrip 中丢失。
- 禁止：
  - 不让 UI 成为规则来源。

### P1-8.21 新增 P1-8 主验证脚本

- 目标：提供资源受控的专项验证入口。
- 要做：
  - 新增 `tools/validate_p1_8_battle_setup.py`。
  - 输出 summary、case matrix、少量 sample state，不写完整 canonical IR / coverage / fidelity。
  - 使用结构化谓词选择真实 wave/status/summon source。
- 验收结果：
  - `validation_summary_p1_8_battle_setup.json` 中所有直接 case ok。
  - 输出文件数量和体积受控。
- 禁止：
  - 不复制 `validate_v0_204` 的全量写盘模式。

## 5. 验证矩阵

P1-8 主验证建议输出：

```text
validation_summary_p1_8_battle_setup.json
battle_setup_schema_cases_p1_8.json
battle_setup_wave_cases_p1_8.json
battle_setup_roster_resource_cases_p1_8.json
battle_setup_status_cases_p1_8.json
battle_setup_summon_cases_p1_8.json
battle_setup_timeline_rng_objective_cases_p1_8.json
battle_setup_negative_cases_p1_8.json
```

主验证 case：

| Case | 目的 | 关键断言 |
|---|---|---|
| schema_load_legacy | 旧 v8 scenario 仍可加载 | `identity_smoke_v0_204` build ok |
| schema_load_battle_setup | 新 setup shape 可加载 | dataclass 字段正确 |
| roster_resources | ally/enemy roster + SP/HP/energy | hp_ratio、energy_ratio、SP 正确 |
| two_wave_setup | wave source-backed setup | 当前波 spawned，下一波 absent |
| initial_status | source-backed AddModifier setup | status_details + source_trace |
| initial_summon | source-backed summon monster setup | unit + summon_runtime |
| servant_source_gap | servant 缺 executable source | blocked/no unit |
| timeline_setup | explicit AV / runtime initialize | action_values 正确 |
| rng_setup | scenario-level rng 注入 command | rng_events schema/replay |
| objective_metadata | objective 不影响规则执行 | with/without objective transition 相同 |
| bad_refs | unknown source/config negative | fail fast or blocked/no mutation |
| static_boundary | no raw TBGD/TextMap/v7/model pack | static checks 通过 |

## 6. 分层验证范围

所有命令在 `hsr_v075_baseline_clean/hsr` 下运行。

### 6.1 必跑最小集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
```

目的：语法和 import 基础检查。

触发条件：每次 P1-8 实现或修正后必跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup
```

目的：P1-8 主验证，覆盖 schema、loader、builder、wave/status/summon/timeline/rng/objective 和 negative cases。

触发条件：每次 P1-8 实现或修正后必跑。

```bash
git diff --check
```

目的：空白和补丁格式检查。

触发条件：每次提交前必跑。

### 6.2 直接回归集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_after_p1_8
```

目的：P1-8 改 wave setup 时确认 P1-2 wave runtime 未回退。

触发条件：改 `build_state.py` wave 生成、wave setup schema、wave runtime 字段时跑。该脚本会构建 RuleBook，串行运行。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_after_p1_8
```

目的：P1-8 改 summon setup 时确认 P1-3 summon/source gap 语义未回退。

触发条件：改 initial summon、summon_runtime、summon flags 时跑。串行运行。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_after_p1_8
```

目的：P1-8 改 initial status 时确认 P1-4 status lifecycle、chance/resist、blocked/no mutation 未回退。

触发条件：改 initial statuses、StatusSystem 调用、status detail 构建时跑。该脚本相对较重，串行运行。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_rng_after_p1_8
```

目的：P1-8 改 scenario-level RNG setup 时确认 P1-7 RNG contract 未回退。

触发条件：改 rng setup、route command metadata 合并、RNG choice 传递时跑。

### 6.3 条件触发集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_v0_204_after_p1_8
```

目的：早期 scenario identity/build 全链路回归。

触发条件：只有改动 loader/schema/build_state 造成现有 UI case 兼容风险，且 P1-8 主验证无法覆盖时才跑。该脚本默认会写完整 canonical/coverage/fidelity，是高 IO 脚本，必须串行运行，禁止和其他重验证并行。若执行线程能先改造它增加轻量模式，可以优先使用轻量模式。

### 6.4 全量验证集

全量验证只在以下情况运行：

- P1-8 完成后准备进入 P1-9 聚合验收。
- 改动破坏 shared reducer、snapshot/replay、source audit、RuleBook lowering 等底座。
- 用户明确要求全量。

默认不为 P1-8 小修补运行全量旧验证。

## 7. 阶段完成口径

满足以下条件，可以勾 `P1-8-DONE`：

- `ScenarioSpec` / `BattleSetupSpec` 能表达两波、有状态、有召唤、有 deterministic RNG 的第一阶段验证战斗。
- 旧 v8 scenario JSON 仍能通过当前入口加载和构建。
- ally roster、enemy wave、SP、energy、HP ratio、initial statuses、initial summon、timeline、rng、objective 都有明确 schema 和 validation。
- 所有机制引用都能追到 RuleBook / Canonical IR / 数据卡 IR，或明确 source gap/blocked。
- initial status / summon 等会改变 state 的 setup 操作通过现有系统和 mutation/reducer，不直接写 fake runtime details。
- source gap 的 servant/random/blocked setup 不产生 fake unit/status/mutation。
- P1-8 主验证通过，必跑最小集通过。
- 直接触达的 P1-2/P1-3/P1-4/P1-7 回归按触发条件通过或明确说明未跑理由。
- `scenarios/README.md` 和 live validation report 更新。

不能勾 `P1-8-DONE` 的情况：

- 只能手写 Python `BattleState` 才能表达两波/状态/召唤/RNG。
- scenario 能通过 arbitrary flags 注入状态或召唤机制正例。
- unknown card/profile/effect/summon source 被默认值掩盖。
- P1-8 主验证依赖固定角色名、固定怪物名、固定 stage id 或固定文件 hash 选择主样例。
- 主验证默认写完整 canonical/coverage/fidelity 大产物。

## 8. 交付文件

预期新增或修改：

```text
simulator_v8_clean_core/scenarios/schema.py
simulator_v8_clean_core/scenarios/loader.py
simulator_v8_clean_core/scenarios/identity.py
simulator_v8_clean_core/scenarios/build_state.py
simulator_v8_clean_core/scenarios/README.md
simulator_v8_clean_core/scenarios/examples/p1_8_battle_setup_smoke.json
simulator_v8_clean_core/tools/validate_p1_8_battle_setup.py
simulator_v8_ui/runner.py
simulator_v8_ui/report.py
live_validation_reports/v8_p1_8_battle_setup_checkpoint.md
FIRST_PHASE_TASK_CHECKLIST.md
```

如果执行中发现无需修改 UI runner/report，也必须在报告中说明为什么新增 setup 字段不会被 UI roundtrip 丢失。

