# P1-1 UnitLifecycle 详细任务计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-1 UnitLifecycle 通用系统` 的实现级拆解。目标是让后续实现 agent 可以只围绕本文件完成 P1-1，不需要继承前序对话上下文。

P1-1 的核心结论：

```text
单位生命周期必须成为 v8 core 的通用底座。
死亡、退场、生成、复活预留、行动资格、目标资格、队列资格不能继续散落在 hp、target、timeline、queue、damage 各系统里。
```

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是播放固定流程，而是支持战斗推演和搜索：

```text
给定战斗配置、动作选择和随机分支
=> 得到可 replay、可 audit、尽量与游戏一致的完整战斗过程
```

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测伤害或手工答案作为规则输入。

当前第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。P1-0 已经完成动作权责边界：

- 外部推演器选择动作。
- core 暴露 action availability。
- core 不做敌方 AI。
- mandatory queue、selectable queue、enemy fixed-sequence candidate、summon blocked 已有可观测边界。

P1-1 紧接着要做 UnitLifecycle。原因是后续 WaveSystem、Summon/Assistant/Servant、状态控制、队列取消、目标系统都依赖统一单位生命周期。

### 0.2 为什么 P1-1 必须现在做

当前 v8 主要用 `hp <= 0` 表达死亡。这个做法已经支撑了一些伤害验证，但不足以成为完整模拟器底座。

星铁战斗中至少存在这些单位生命周期状态：

- 正常在场，可以被选中，可以行动。
- HP 到 0，被击败，但仍需要保留击杀归因和事件审计。
- 被退场或移除，不应再参与目标、行动轴、队列，但 replay 仍需要知道它曾经存在。
- 由波次或召唤生成，进入 battle state。
- 将来可能复活，或阶段切换后替换成新状态。

如果不先建立通用生命周期，后续系统会各自发明规则：

- target 只看 `hp > 0`。
- timeline 只跳过 `hp <= 0`。
- queue 只检查 actor id 是否存在。
- damage 只发 `unit.defeated` process event。
- wave 可能直接增删 `state.units`。
- summon 可能自己处理退场。

这会破坏 replay、source audit 和状态空间搜索。

### 0.3 P1-1 的一句话目标

P1-1 只回答一个问题：

```text
一个单位在 v8 BattleState 中如何出生、被击败、退场、保留审计痕迹，并一致影响 target、timeline、queue、action availability 和 damage？
```

### 0.4 当前代码事实

当前相关落点：

```text
core/model.py
core/reducer.py
systems/damage.py
systems/target.py
systems/timeline.py
systems/queue.py
systems/action_availability.py
systems/scheduler.py
systems/event_dispatch.py
```

当前事实：

- `UnitState` 没有显式 lifecycle 字段。
- `UnitState` 只有 `hp`，没有 `alive`、`defeated`、`removed` 独立语义。
- `BattleState.units` 是当前所有单位的 dict。
- snapshot teams 直接按 side 收集 `state.units` 中所有单位。
- reducer 目前只支持修改已有 unit 字段，不支持新增 unit 或移除/tombstone unit。
- damage 在 HP 从正数到 0 时生成 `unit.defeated` process event。
- damage 当前改变的是 `units/<id>/hp` mutation，不是 `UnitDefeat` mutation。
- target、timeline 当前主要用 `hp > 0` 或 `hp <= 0` 过滤。
- queue 对 actor 主要检查是否存在，不完整检查 actor 生命周期。
- action availability 依赖 timeline/queue/actor choices，还没有 lifecycle gating。

### 0.5 P1-1 非目标

P1-1 不做：

- 不做 WaveSystem。
- 不做完整 Summon/Assistant/Servant 行为。
- 不做复活机制 executable，除非有真实来源和通用语义。
- 不做敌方阶段切换全量实现。
- 不做状态系统叠层/刷新/控制全量实现。
- 不做完整 target sort/random/fetch 扩面。
- 不为了某个角色、某个怪物写 runtime 特判。

P1-1 只做通用生命周期底座和它对已有系统的最小一致影响。

## 1. 设计原则

### 1.1 生命周期不能只等于 HP

HP 是战斗资源，生命周期是单位参与战斗的资格状态。二者相关，但不是同一个概念。

推荐建立显式生命周期状态：

```text
active
defeated
removed
```

含义：

- `active`：在场，可能可行动，可能可被选中。
- `defeated`：被击败，通常 HP 为 0，不能普通行动，不能作为普通 alive target，但仍保留在 state 中用于事件、结算、审计。
- `removed`：已退场，不参与普通 target/timeline/queue/action availability，但仍保留 tombstone 或 equivalent audit record。

实现线程可以选择字段形态：

- 新增 `UnitState.lifecycle_status`。
- 或先用 `UnitState.flags["lifecycle_status"]`。
- 或新增 `BattleState.lifecycle` 映射。

但必须满足：

- snapshot 能稳定表达。
- reducer 能 replay。
- target/timeline/queue/action availability 能一致读取。
- 不能只散落检查 `hp <= 0`。

### 1.2 退场不能破坏 replay

UnitRemove 不应简单 `del state.units[unit_id]` 后丢失全部信息。否则 replay 和 source audit 很难说明：

- 这个单位是谁。
- 为什么退场。
- 退场前状态是什么。
- 哪个来源导致退场。
- 后续 queue/target 为什么跳过它。

推荐策略：

```text
UnitRemove => lifecycle_status="removed" + removed metadata/tombstone
```

如果实现线程决定真的从 `BattleState.units` 删除单位，必须同时设计 tombstone 存储，并证明 replay/snapshot/source audit 不丢信息。

### 1.3 生命周期变化必须通过 Mutation

所有生命周期变化必须通过 mutation：

- UnitSpawn。
- UnitDefeat。
- UnitRemove。
- UnitRevive blocked 或预留。

不能只发 process event。

`unit.defeated` 事件可以继续存在，但它必须由 lifecycle mutation 或 damage mutation 的结果触发，不能替代状态变化。

### 1.4 来源边界

生命周期 mutation 必须有来源：

- damage defeat 来源于 damage emission / status damage emission / break emission / hp loss source。
- spawn 来源于 wave definition、summon effect、scenario setup 或数据卡 IR。
- remove 来源于 wave transition、summon lifetime、owner death rule、phase switch rule。
- revive 来源于真实状态/技能/机制来源；P1-1 默认 blocked。

没有来源时：

```text
blocked / process-only / state unchanged
```

### 1.5 通用性和简洁性

P1-1 禁止：

- 固定角色名。
- 固定怪物名。
- 固定召唤物名。
- 固定 action id。
- 按验证文件名或 scenario 名写逻辑。
- 用旧 v7 的 `alive` 语义直接搬进 v8。
- 为 wave 或 summon 单独写一套生灭逻辑。

P1-1 应该新增一个小而清晰的生命周期服务，供后续系统复用。

推荐模块：

```text
systems/unit_lifecycle.py
```

## 2. 推荐数据结构

实现线程可调整命名，但应保留同等语义。

### 2.1 `UnitLifecycleStatus`

建议：

```python
UnitLifecycleStatus = Literal["active", "defeated", "removed"]
```

读取规则：

- 如果新字段存在，读取新字段。
- 如果为了兼容暂放在 flags，读取 `flags["lifecycle_status"]`。
- 旧 state 缺字段时：
  - `hp > 0` 可视为 `active`。
  - `hp <= 0` 可视为 `defeated`。
  - 这个兼容推断必须集中在 helper 中，不要散落各系统。

### 2.2 `UnitLifecycleView`

建议纯查询结构：

```python
unit_id: str
status: UnitLifecycleStatus
hp: float
is_present: bool
is_active: bool
is_defeated: bool
is_removed: bool
can_be_action_actor: bool
can_be_targeted_alive: bool
can_receive_damage: bool
can_keep_queue_entries: bool
blocked_reason: str
metadata: dict[str, JSONValue]
```

用途：

- target resolver 判断目标资格。
- timeline 判断行动资格。
- queue 判断 actor/target 是否还有效。
- action availability 判断 actor 是否可输入动作。
- damage 判断 dead target skip / continuation。

### 2.3 `UnitLifecycleSystem`

推荐接口：

```python
UnitLifecycleSystem.view(state, unit_id) -> UnitLifecycleView
UnitLifecycleSystem.status_of(unit) -> UnitLifecycleStatus
UnitLifecycleSystem.can_act(state, unit_id) -> tuple[bool, str]
UnitLifecycleSystem.can_target(state, unit_id, *, allow_defeated=False) -> tuple[bool, str]
UnitLifecycleSystem.can_receive_damage(state, unit_id) -> tuple[bool, str]
UnitLifecycleSystem.spawn_mutation(...)
UnitLifecycleSystem.defeat_mutations(...)
UnitLifecycleSystem.remove_mutations(...)
UnitLifecycleSystem.revive_blocked(...)
```

注意：

- 查询接口不能产生 mutation。
- mutation 构造接口只构造 mutation，不 apply。
- reducer 仍负责 apply。

### 2.4 mutation 语义

P1-1 建议先不强行新增复杂 mutation class，而是在现有 `Mutation` 框架中使用稳定 metadata 表达 lifecycle operation。

推荐 metadata：

```python
{
  "lifecycle_operation": "unit_defeat",
  "lifecycle_status_before": "active",
  "lifecycle_status_after": "defeated",
  "reason": "...",
  "source_trace": {...}
}
```

建议 mutation paths：

- Defeat:
  - `("units", unit_id, "hp")` -> `0.0`
  - `("units", unit_id, "flags", "lifecycle_status")` -> `"defeated"`
  - `("units", unit_id, "flags", "defeat_record")` -> payload
- Remove:
  - `("units", unit_id, "flags", "lifecycle_status")` -> `"removed"`
  - `("units", unit_id, "flags", "removed_record")` -> payload
  - 可选清理 action/timeline flags。
- Spawn:
  - 当前 reducer 不支持新增 unit。P1-1 必须扩展 reducer 支持 unit-level insertion，或先定义 SpawnPlan 并 blocked。
  - 推荐支持 `("units", unit_id)` 插入完整 `UnitState` JSON / structured payload，然后 reducer 重建 UnitState。

这里需要实现线程做最终工程判断。如果新增 unit-level reducer 支持范围过大，可拆成：

1. P1-1a: Defeat/Remove/tombstone。
2. P1-1b: Spawn insertion。

但最终 `P1-1-DONE` 必须包含 spawn replay。

## 3. 详细任务清单

### P1-1-A 当前生命周期审查

目标：

- 明确当前 hp/death/target/timeline/queue/damage 行为，不误改已有可信纵切。

需要做：

- [ ] 阅读 `core/model.py` 的 `UnitState`、`BattleState.snapshot`。
- [ ] 阅读 `core/reducer.py` 的 unit mutation apply。
- [ ] 阅读 `systems/damage.py` 的 HP mutation、`unit.defeated` event、kill attribution。
- [ ] 阅读 `systems/target.py` 的 action target enumeration/resolution 和 alive/dead filter。
- [ ] 阅读 `systems/timeline.py` 的 `plan_next_actor`。
- [ ] 阅读 `systems/queue.py` 的 actor/target resolution。
- [ ] 阅读 `systems/action_availability.py` 的 actor gating。
- [ ] 阅读 `systems/scheduler.py` 的 queue drain 和 turn begin。
- [ ] 查找已有验证中 dead target、defeat、bounce continuation 相关 case。

验收结果：

- [ ] 实现报告列出当前行为和改动范围。
- [ ] 没有读取旧 v7 作为 runtime 依据。
- [ ] 没有把 P1-2 wave 或 P1-3 summon 行为混进本阶段。

### P1-1-B 定义生命周期状态与读取 helper

目标：

- 建立统一 lifecycle status 读取入口，替代散落的 `hp <= 0` 判定。

需要做：

- [ ] 新增 `systems/unit_lifecycle.py` 或等价模块。
- [ ] 定义 `UnitLifecycleStatus`。
- [ ] 定义 `UnitLifecycleView`。
- [ ] 定义 `UnitLifecycleSystem.status_of(unit)`。
- [ ] 兼容旧 state：缺显式 lifecycle 时由 HP 推断。
- [ ] 定义 `is_active`、`is_defeated`、`is_removed`。
- [ ] 定义 `can_be_action_actor`。
- [ ] 定义 `can_be_targeted_alive`。
- [ ] 定义 `can_receive_damage`。
- [ ] 定义 `can_keep_queue_entries`。
- [ ] 为 view 提供 `to_json()`。

验收结果：

- [ ] HP > 0 且无 lifecycle flag 的单位视为 active。
- [ ] HP <= 0 且无 lifecycle flag 的单位视为 defeated。
- [ ] lifecycle_status=removed 的单位即使 HP > 0 也不能行动/普通目标。
- [ ] 所有判断集中在 lifecycle helper 中。

### P1-1-C 扩展 snapshot 表达

目标：

- 让 snapshot 明确表达单位 lifecycle，便于 replay、UI 和推演器读取。

需要做：

- [ ] 在 `UnitState.to_snapshot()` 输出 lifecycle status。
- [ ] 输出 `defeated` / `removed` 派生布尔或 metadata。
- [ ] 确认 teams 是否包含 removed unit。
- [ ] 推荐 teams 仍按 side 表示历史/当前单位，同时新增 active team 视图或 targetable team 视图。
- [ ] 如果改变 teams 语义，必须在报告中说明兼容影响。

验收结果：

- [ ] snapshot 中每个 unit 有 lifecycle status。
- [ ] removed unit 的 snapshot 可解释为什么不可行动/不可选中。
- [ ] replay 后 snapshot 一致。

### P1-1-D reducer 支持 UnitSpawn / UnitRemove

目标：

- reducer 能 replay 单位生成和退场。

需要做：

- [ ] 设计 unit-level mutation path。
- [ ] 支持插入新 unit，或定义清晰的 spawn blocked 策略。
- [ ] 支持 removed/tombstone 状态 mutation。
- [ ] 不破坏已有 `("units", unit_id, field)` mutation。
- [ ] 对未知 unit 的非 spawn mutation 仍应报错。
- [ ] 对重复 spawn 已存在 unit blocked 或报错。
- [ ] 对 remove missing unit blocked 或报错。

推荐：

- `("units", unit_id)` with operation metadata `unit_spawn` 用于插入。
- `UnitRemove` 默认不删除 dict，而是设置 lifecycle_status=removed。

验收结果：

- [ ] UnitSpawn 可 replay。
- [ ] UnitRemove 可 replay。
- [ ] 未知 unit 字段 mutation 仍被拒绝。
- [ ] 不影响已有 replay 验证。

### P1-1-E UnitDefeat 接入 damage

目标：

- HP 从正数到 0 时，不只发 `unit.defeated` event，还要产生 lifecycle defeat mutation。

需要做：

- [ ] 找出 direct/dot/break/super_break/hp_loss 所有 HP mutation 生成点。
- [ ] 在 HP 正数 -> 0 时追加 lifecycle_status=defeated mutation。
- [ ] 添加 defeat_record metadata。
- [ ] 保留现有 `unit.defeated` event。
- [ ] 确保同一 action 内不重复 defeat 同一单位。
- [ ] 确保已 defeated target 的后续伤害 skipped 或按已有 dead_target_continuation 记录。
- [ ] kill attribution 使用具体 damage source frame，不退化成 actor id。

验收结果：

- [ ] damage defeat 产生 HP mutation 和 lifecycle defeat mutation。
- [ ] `unit.defeated` event 与 lifecycle mutation 可关联。
- [ ] 同一单位不重复 defeat。
- [ ] replay 通过。
- [ ] source audit 能从 defeat mutation 追到 damage emission/source trace。

### P1-1-F target 系统接入 lifecycle

目标：

- target resolver 不再直接散落依赖 `hp > 0`，而是通过 lifecycle 判断目标资格。

需要做：

- [ ] `enumerate_action_targets` 使用 lifecycle helper。
- [ ] `resolve_action_targets` / `resolve_explicit_targets` 使用 lifecycle helper。
- [ ] `enemies_of` 使用 lifecycle helper。
- [ ] target expression group alias 使用 lifecycle helper。
- [ ] `allow_defeated=True` 时允许 defeated，但不允许 removed，除非后续有明确来源。
- [ ] removed unit 不进入普通 target candidates。
- [ ] target rejected reason 中区分 defeated 和 removed。

验收结果：

- [ ] active target 可选。
- [ ] defeated target 默认不可选。
- [ ] allow_defeated 可以选 defeated。
- [ ] removed target 不可选。
- [ ] target resolution record 有稳定 rejected reason。

### P1-1-G timeline 接入 lifecycle

目标：

- 行动轴只选择生命周期允许行动的单位。

需要做：

- [ ] `TimelineSystem.plan_next_actor` 使用 lifecycle helper。
- [ ] defeated unit skipped reason 稳定。
- [ ] removed unit skipped reason 稳定。
- [ ] action_disabled 仍保留为状态/控制 gating，不与 lifecycle 混淆。
- [ ] summon timeline admission 仍保留，P1-3 再扩。
- [ ] active_turn actor 如果变 defeated/removed，scheduler/action availability 能 blocked 或清理。

验收结果：

- [ ] defeated actor 不会被 plan_next_actor 选中。
- [ ] removed actor 不会被 plan_next_actor 选中。
- [ ] skipped_units 记录 reason。
- [ ] no admitted actor 时 blocked reason 稳定。

### P1-1-H action availability 接入 lifecycle

目标：

- P1-0 的 action availability 视图反映 lifecycle。

需要做：

- [ ] active turn owner defeated 时，availability blocked。
- [ ] active turn owner removed 时，availability blocked。
- [ ] preview next actor 跳过 defeated/removed。
- [ ] summon blocked 逻辑继续保留，但先通过 lifecycle gating。
- [ ] blocked reason 区分 `actor_defeated` / `actor_removed` / `no_admitted_actor`。

验收结果：

- [ ] defeated active actor 不暴露 action choices。
- [ ] removed active actor 不暴露 action choices。
- [ ] preview 不选 defeated/removed actor。
- [ ] state unchanged。

### P1-1-I queue 接入 lifecycle

目标：

- pending queue item 的 actor/target 生命周期变化时，有一致处理。

需要做：

- [ ] queue plan 检查 actor lifecycle。
- [ ] actor defeated 时 queue item blocked、skipped 或 canceled，策略必须统一。
- [ ] actor removed 时 queue item canceled 或 blocked，策略必须统一。
- [ ] target defeated 时按 queue/action 语义决定 skipped 或 blocked；P1-1 可先对普通 action target blocked。
- [ ] target removed 时 blocked/canceled。
- [ ] 产生 queue lifecycle process record。
- [ ] 如果清理 queue，需要通过 queue mutation。

推荐 P1-1 最小策略：

```text
actor defeated/removed => pending queue item blocked/state unchanged
actor removed with cleanup policy admitted => dequeue/cancel mutation
target removed => blocked
target defeated => blocked unless plan explicitly allows defeated
```

验收结果：

- [ ] actor defeated queue action 不执行。
- [ ] actor removed queue action 不执行。
- [ ] target removed queue action 不执行。
- [ ] blocked 不产生非 queue-cleanup mutation。
- [ ] 如执行 cancel，replay/source audit 通过。

### P1-1-J UnitRemove 最小语义

目标：

- 建立退场语义，供 P1-2 wave 和 P1-3 summon 复用。

需要做：

- [ ] 定义 remove reason。
- [ ] 定义 removed_record。
- [ ] UnitRemove 设置 lifecycle_status=removed。
- [ ] removed unit 从 target/timeline/action availability 排除。
- [ ] removed unit 的 queue item 策略明确。
- [ ] removed unit 不应被 damage 普通命中。
- [ ] removed unit 保留 snapshot/tombstone。

验收结果：

- [ ] UnitRemove mutation replay 通过。
- [ ] removed unit 不可行动。
- [ ] removed unit 不可普通选中。
- [ ] removed unit 的历史信息仍可审计。

### P1-1-K UnitSpawn 最小语义

目标：

- 建立单位生成的通用入口，供 P1-2 wave 和 P1-3 summon 复用。

需要做：

- [ ] 定义 spawn source payload。
- [ ] 定义 spawn profile/card/source trace 要求。
- [ ] 支持从已构造 `UnitState` spawn。
- [ ] 支持 reducer replay 插入 unit。
- [ ] 重复 unit id spawn blocked。
- [ ] 缺 source trace 或 profile/card 时 blocked，除非是 validation synthetic process-only。
- [ ] spawn 后 unit lifecycle_status=active。
- [ ] spawn 后 target/timeline/action availability 可观察。

验收结果：

- [ ] UnitSpawn replay 通过。
- [ ] spawn unit 出现在 snapshot。
- [ ] spawn active enemy 可被 target resolver 选中。
- [ ] spawn active actor 可被 timeline 选中。
- [ ] 缺 source blocked/state unchanged。

### P1-1-L UnitRevive 预留

目标：

- 不实现伪复活，但预留统一 blocked 语义。

需要做：

- [ ] 定义 revive operation 名称。
- [ ] 缺真实来源时 blocked。
- [ ] defeated -> active 的 mutation 仅允许真实来源路径。
- [ ] removed -> active 默认 blocked，除非后续机制明确。

验收结果：

- [ ] UnitRevive 当前没有真实来源时不产生 mutation。
- [ ] validation 证明 revive placeholder blocked/state unchanged。

### P1-1-M event dispatch 与 source audit

目标：

- lifecycle mutation、event、settlement 可以互相追溯。

需要做：

- [ ] `unit.defeated` event payload 关联 defeat mutation id。
- [ ] settlement record 记录 lifecycle operation。
- [ ] source audit 支持 lifecycle mutation source metadata。
- [ ] process-only event 不替代 mutation。
- [ ] skipped queue/target/damage lifecycle reason 进入 settlement/process records。

验收结果：

- [ ] 从 defeat mutation 可追到 settlement record。
- [ ] 从 settlement 可追到 damage/source IR。
- [ ] 从 `unit.defeated` event 可追到 mutation 或 damage source。
- [ ] source audit 通过。

### P1-1-N 验证矩阵

目标：

- 覆盖正例、负例、replay、source audit。

建议新增：

```text
simulator_v8_clean_core/tools/validate_p1_1_unit_lifecycle.py
```

需要覆盖：

- [ ] lifecycle view active/defeated/removed。
- [ ] HP <= 0 旧 state 推断 defeated。
- [ ] explicit removed 覆盖 HP > 0。
- [ ] damage defeat 正例。
- [ ] damage defeat 不重复。
- [ ] dead target skipped。
- [ ] defeated target 默认不可选。
- [ ] allow_defeated 可选 defeated。
- [ ] removed target 不可选。
- [ ] defeated actor 不进 timeline。
- [ ] removed actor 不进 timeline。
- [ ] defeated active actor action availability blocked。
- [ ] removed active actor action availability blocked。
- [ ] actor defeated queue blocked。
- [ ] actor removed queue blocked/canceled。
- [ ] UnitSpawn replay。
- [ ] UnitRemove replay。
- [ ] UnitRevive blocked/state unchanged。
- [ ] source audit。
- [ ] static checks。

验收结果：

- [ ] 新 validation 输出 `ok=true`。
- [ ] 每个 blocked case state unchanged。
- [ ] 每个 mutation case replay 通过。
- [ ] 每个 executable lifecycle mutation source audit 通过。

### P1-1-O 回归验证

目标：

- 确保 P1-1 不破坏已通过底座。

至少运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_after_p1_1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_unit_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_v0_264_after_p1_1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_283 --output-dir /tmp/hsr_v8_v0_283_after_p1_1
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p1_1
git diff --check
```

验收结果：

- [ ] compileall 通过。
- [ ] P1-0 回归通过。
- [ ] P1-1 新验证通过。
- [ ] v0_264 defeat/bounce 相关回归通过。
- [ ] v0_283 enemy/queue 回归通过。
- [ ] v0_289 target 回归通过。
- [ ] static checks 通过。

### P1-1-P 文档和 checklist

目标：

- 让后续阶段知道生命周期底座怎么用。

需要做：

- [ ] 新增 live validation report。
- [ ] 报告说明当前做到哪里。
- [ ] 报告说明 UnitSpawn/UnitRemove/UnitDefeat/UnitRevive 支持状态。
- [ ] 报告说明 removed/tombstone 策略。
- [ ] 报告说明 target/timeline/queue/action availability 影响。
- [ ] 报告说明剩余 blocked 范围。
- [ ] 勾选 `FIRST_PHASE_TASK_CHECKLIST.md` 中 P1-1 已完成项。

验收结果：

- [ ] 后续 P1-2/P1-3 可以直接复用 UnitLifecycle。
- [ ] 总清单状态和实际实现一致。

## 4. 建议实现顺序

推荐顺序：

1. 新增 `unit_lifecycle.py` 纯查询 helper。
2. 接入 snapshot lifecycle 输出。
3. 接入 target/timeline/action availability 只读 gating。
4. 接入 damage defeat mutation。
5. 接入 queue actor/target gating。
6. 扩展 reducer 支持 UnitSpawn。
7. 实现 UnitRemove tombstone。
8. 预留 UnitRevive blocked。
9. 写 P1-1 validation。
10. 跑 P1-0/v0_264/v0_283/v0_289 回归。
11. 更新 report 和 checklist。

建议先做 defeat/remove 的状态统一，再做 spawn。spawn 牵涉 reducer 插入完整 `UnitState`，工程风险比 defeated gating 更高。

## 5. P1-1 最终验收

只有以下全部满足，才能勾选 `P1-1-DONE`：

- [ ] 存在统一 UnitLifecycle 查询入口。
- [ ] lifecycle status 可在 snapshot 中观察。
- [ ] HP <= 0 兼容推断 defeated，但新逻辑不再散落依赖 `hp <= 0`。
- [ ] UnitDefeat 通过 mutation 表达。
- [ ] damage defeat event 与 lifecycle mutation 可关联。
- [ ] UnitRemove 通过 mutation 表达，并保留 tombstone 或等价审计信息。
- [ ] UnitSpawn 可 replay。
- [ ] UnitRevive 没有真实来源时 blocked/state unchanged。
- [ ] target resolver 使用 lifecycle gating。
- [ ] timeline 使用 lifecycle gating。
- [ ] queue 使用 lifecycle gating。
- [ ] action availability 使用 lifecycle gating。
- [ ] defeated/removed actor 不能普通行动。
- [ ] defeated/removed target 不会被普通 alive target 选中。
- [ ] queue 中 actor/target 生命周期失效时不会错误执行。
- [ ] replay 通过。
- [ ] source audit 通过。
- [ ] blocked/audit_only/discovered_only 不产生 lifecycle mutation。
- [ ] 没有引入 raw TBGD/TextMap/旧 v7/旧 model pack runtime 依赖。
- [ ] 没有角色名、怪物名、固定 action id、固定文件名主路径硬编码。

## 6. 禁止事项

P1-1 实现中明确禁止：

- 禁止直接照搬 v7 `alive` 模型作为 v8 事实来源。
- 禁止在 target/timeline/queue/action availability 各自写不同死亡判断。
- 禁止 UnitRemove 直接丢失审计信息。
- 禁止 spawn 使用默认 profile 或默认来源。
- 禁止复活 placeholder 产生 mutation。
- 禁止为了验证样例按固定角色名、怪物名、action id 写 runtime 逻辑。
- 禁止让 wave 或 summon 自己实现生灭旁路。
- 禁止从日志事后反推 lifecycle settlement。
- 禁止 process-only `unit.defeated` event 替代 mutation。

## 7. P1-1 之后的交接点

P1-1 完成后，后续阶段应接着做：

- P1-2 WaveSystem：用 UnitSpawn/UnitRemove 推进波次。
- P1-3 Summon/Assistant/Servant：用 UnitSpawn/UnitRemove 管召唤物生灭。
- P1-4 状态系统：用 lifecycle gating 处理控制、持续状态和死亡清理。
- P1-5 Queue/Window：用 lifecycle 状态处理 pending queue 取消、跳过、保留。
- P1-6 Target：在 lifecycle 基础上扩展 sort/fetch/random/adjacent。

P1-1 的核心不是把所有生灭机制一次做完，而是把“单位是否在场、是否被击败、是否已退场、是否还能参与规则”定成一个所有系统共享的底座。
