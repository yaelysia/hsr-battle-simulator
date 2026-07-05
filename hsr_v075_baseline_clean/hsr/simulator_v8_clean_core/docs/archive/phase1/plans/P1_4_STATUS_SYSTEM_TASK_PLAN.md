# P1-4 状态系统主体总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-4 状态系统主体` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-4。

本次计划特意改进一个问题：每个小项都必须有明确目标、实现要求、验收结果和禁止事项。不能只写“实现 stack”或“增加验证”，因为这种标题不足以约束实现方向，也不足以防止后续出现硬编码、假来源、验证专用路径或 partial 语义被误当作完整语义。

P1-4 的一句话目标：

```text
把当前 partial 的 AddModifier/RemoveModifier/status lifecycle 能力，提升为 source-admitted、mutation-backed、可 replay、可扩展的数据驱动状态系统底座。
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

### 0.2 P1-4 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

已经完成的前置阶段：

- P1-0 Action Boundary：core 不做敌方 AI，只暴露行动候选、合法性和 transition。
- P1-1 UnitLifecycle：单位 `active / defeated / removed` 统一进入 damage、target、timeline、queue、action availability；UnitSpawn/UnitRemove 已有通用 mutation/replay 底座。
- P1-2 WaveSystem：多波战斗通过 WaveDefinition、UnitSpawn、UnitRemove、wave_index mutation、wave events 推进。
- P1-3 Summon / Assistant / Servant：召唤物、assistant、servant 已建立分类、spawn/target/timeline/owner 互动的最小闭环。

P1-4 承接这些系统，并支撑后续：

- P1-5 queue/window：追击、反击、终结技插队、额外行动、assistant 行动都会通过状态 callback 和队列窗口触发。
- P1-6 target：状态施加、驱散、控制、DoT tick 都依赖目标解析和目标可用性。
- P1-7 RNG：状态命中、抵抗、随机驱散必须进入可 replay 的 RNG ledger。
- 角色/怪物/光锥/遗器扩面：大量机制最终都会落在 buff/debuff/control/DoT 的通用状态语义上。

因此 P1-4 不是“补几个状态字段”，而是要把状态系统变成后续机制可复用的底层基座。

## 1. 当前代码事实

以下结论来自当前代码实际状态，不是从文档倒推：

- `systems/status.py` 已有 `StatusInstance`，字段包括 `stacks`、`max_stacks`、`duration`、`remaining_duration`、`life_step_moment`、`duration_admission`、`stack_policy`、`refresh_policy`、`status_type`、`status_category`、`can_dispel`。
- `StatusSystem.apply_add_modifier` 已支持 `AddModifier` 的标准 payload、target expression/legacy alias、modifier definition、dynamic values、status metadata、duration admission、status lifecycle mutation 和 lifecycle events。
- 当前 `stacks` 固定为 `1`；`max_stacks` 只是被读取进 `StatusInstance`；`layer_add_when_stack`、`max_layer > 1` 会进入 `stack_unsupported:*`。
- 当前 refresh/reapply 只形成 `refresh_or_replace_partial` 或 `replace_partial`，不是完整的 refresh policy。
- `StatusSystem.apply_remove_modifier` 已支持 `RemoveModifier` / `RemoveSelfModifier` 的基础移除，但还没有通用 dispel admission、分类筛选、随机选择或 skipped/failed settlement。
- `plan_lifecycle_tick` / `apply_lifecycle_tick` 已支持 `ModifierPhase1End` 和 `ActionPhaseEnd` 的 duration tick/expire 基础路径；`CombatScheduler` 会在 turn end/action after 路径扫当前 actor 的 `status_details`。
- `status_callbacks.py` 已有 DoT/status damage 执行路径，DoT damage 会走 `DamageSourceFrame(source_kind="dot")`，但 DoT tick 和状态生命周期之间还没有形成统一 tick owner/payload/settlement 口径。
- `core.model.RNGEvent` 已存在，damage crit 和 bounce target 已有可参考事件结构；状态命中、抵抗、随机 dispel 还没有统一接入。
- `rules.evaluator` 已支持从 status detail 读取 `Layer`，但 stack mutation、stack cap、stack 对 dynamic value/formula 的一致读写还未形成完整闭环。
- `tbgd/lowering.py` 已把 `AddModifier` 中的 `LifeTime`、`LifeStepMoment`、`LayerAddWhenStack`、`MaxLayer`、`Chance` 降到 standardized payload；P1-4 应在这个边界上继续 admission，不允许 runtime 直接读 raw TBGD。

当前最重要的风险：

```text
很多字段已经存在，但语义仍是 partial。
P1-4 不能把“字段存在”当作“机制完整”。
```

### 1.1 来源缺口验收修正

P1-4 的验收必须是来源驱动的三态判断，而不是简单的“有代码路径就算完成”或“没有真实正例就算实现失败”：

- `executable`：当前 RuleBook / Canonical IR 中存在真实来源，runtime mutation、settlement、source audit、replay 均通过。
- `source_gap_blocked`：runtime 可以有通用 admission/blocked 分支或未来预留路径，但当前 TBGD / IR 结构化扫描没有真实可执行来源；验证只能证明 coverage gap、blocked、state unchanged，不能合成正例 mutation。
- `implementation_missing`：当前存在真实来源，但 runtime 没有正确 admission / mutation / settlement / replay，这才是需要继续编码修复的缺口。

当前执行层已经发现的典型 `source_gap_blocked`：

- `P1-4.11 stack + duration refresh`：runtime 已有 `stack_refresh` 路径，但当前 RuleBook 没有“同一个 AddModifier 同时 stackable 且 refresh-admitted”的真实来源。
- `P1-4.29 / P1-4.42 random dispel`：runtime 已有 random dispel RNG 分支，但当前 raw TBGD / IR 没找到 `DispelStatus Order=Random` 来源，只有 `Order=LastAdded`。

这些项不能用 synthetic case 勾成 executable。正确验收是：结构化扫描证明来源缺口，runtime 不会从伪来源产生 mutation，报告中把它们列为 coverage gap。若 checklist 的 `P1-4-DONE` 表示“所有列项都有真实正例可执行”，则在这些来源缺口消失前应保持未勾选；若项目管理需要继续推进后续阶段，应使用“P1-4 状态底座已验收，带来源缺口”的结论，而不是把 source gap 伪装成 DONE。

## 2. 非目标

P1-4 不做以下内容：

- 不做全角色、全怪物、全光锥、全遗器的人工解释。
- 不做敌方 AI。控制类状态只影响 action availability / timeline / queue 的规则化可用性，不负责选择敌方动作。
- 不做完整分支搜索器；只输出 RNG event 和 blocked/choice 边界。
- 不把 TextMap、技能文本、角色名、怪物名、固定技能 ID、固定验证样例当作 runtime 规则来源。
- 不为旧 v7、旧 model pack、旧 CLI 或旧 JSON 做兼容。
- 不把尚未 admission 的 status opcode、chance formula、control 规则、dispel 随机规则伪装成 executable。
- 不为了让 smoke case 跑通而使用默认 stack、默认 chance、默认 resist、默认 immunity、默认 dispel target。

## 3. 总体实现原则

### 3.1 三层语义必须分开

P1-4 必须明确区分：

- Source/IR 层：从 TBGD lowering 或数据卡 IR 得到的状态定义、AddModifier/RemoveModifier payload、status entity metadata、callback、status damage emission。
- Runtime instance 层：某个单位身上的状态实例，包括 owner、caster、source、stack、duration、category、trigger ids、source trace。
- Lifecycle event 层：状态 apply、stack、refresh、tick、expire、remove、dispel、chance failure、resisted、immunity、control gating 等过程事件。

这三层不能混写。尤其不能为了 runtime 方便，在 IR 里伪造 TBGD 不存在的规则事实。

### 3.2 Admission 先于 mutation

任何会改变状态的路径，都必须先有 admission 结果：

- source 是否真实。
- formula 是否可执行。
- target 是否可解析。
- chance/resist/immunity 是否有可 replay 的 RNG 或 deterministic choice。
- stack/refresh/duration/dispel/control policy 是否在支持范围内。

缺 admission 时必须 blocked/process-only，并保持 state unchanged。

### 3.3 Settlement 必须区分成功、跳过和失败

状态系统不能只记录 applied term。至少要有：

- `status_apply_success`
- `status_apply_failed`
- `status_resisted`
- `status_immunity`
- `status_lifecycle`
- `status_stack`
- `status_refresh`
- `status_tick`
- `status_expire`
- `status_dispel`
- `status_control_gate`
- `status_blocked`

具体 record type 可以按现有 `SettlementRecord` 风格微调，但语义必须可区分。

### 3.4 RNG 必须可 replay

状态命中、effect resist、control resist、随机 dispel 不能直接调用进程随机数。必须产生 `RNGEvent`：

- `rng_type`
- `source`
- `event_id`
- `before_state`
- `after_state`
- `result`
- `metadata.source_trace`

如果当前阶段不接入完整 seed/draw 模型，至少要使用 deterministic roll 或 explicit choice ledger，并在 validation 中证明同输入 replay 稳定。

### 3.5 控制状态只做规则化 gating

项目最终由外部推演器控制动作选择，所以 P1-4 的 control 不做 AI 策略。它只回答：

- 当前单位是否可行动。
- 当前 action/queue/timeline 是否被某类控制状态阻塞、延迟或跳过。
- 阻塞原因是什么，来源是哪条 status instance / IR source。

## 4. 建议代码落点

实际实现 agent 应先阅读当前代码再动手。优先落点：

- `systems/status.py`
  - `StatusInstance`
  - `StatusLifecyclePlan`
  - `StatusApplicationResult`
  - `apply_add_modifier`
  - `apply_remove_modifier`
  - `_application_semantics`
  - `_runtime_duration_admission`
  - `_runtime_modifiers`
  - `_status_lifecycle_events`
- `systems/status_callbacks.py`
  - DoT/status damage emission
  - callback execution after lifecycle events
- `systems/scheduler.py`
  - `_apply_status_lifecycle_tick`
  - `end_current_turn`
  - action after lifecycle hook
  - wave transition hook if needed
- `systems/action_availability.py`
  - control gating 的 action availability 入口
- `systems/event_dispatch.py`
  - lifecycle event -> status callback dispatch
- `rules/evaluator.py`
  - `Layer` / status detail value binding
- `tbgd/lowering.py`
  - 只补 lowering/admission payload，runtime 不读 raw TBGD
- `core/model.py`
  - `RNGEvent` 复用，除非现有结构无法承载状态事件
- `tools/`
  - 新增 `validate_p1_4_status_system.py`
  - 必要时扩展旧验证，但不要用旧验证替代 P1-4 主验证
- `live_validation_reports/`
  - 新增 P1-4 阶段报告

不建议一开始就新增大量抽象。优先复用当前 dataclass 和 `SettlementRecord` 风格；只有当 stack/refresh/chance/dispel/control 的 admission 结构重复到影响清晰度时，再抽出小 dataclass 或 helper。

## 5. 内部闸门

P1-4 是大阶段，必须按内部闸门推进。每个闸门都要能独立验证，不允许最后一次性补验证。

```text
Gate A: 当前状态系统审计和 admission matrix
Gate B: status instance identity / source stack
Gate C: stack / cap / reduce / formula binding
Gate D: refresh / replace / coexist
Gate E: duration owner / tick / expire / wave cleanup
Gate F: DoT tick lifecycle integration
Gate G: chance / resist / immunity / RNG
Gate H: dispel
Gate I: control gating
Gate J: source audit / replay / validation / report
```

Gate A-J 的验收必须按三态判断：有真实来源的机制必须做到 executable；没有真实来源的机制必须做到 `source_gap_blocked`，并用结构化扫描和 negative validation 证明没有伪 mutation。不能要求执行线程为当前数据库不存在的机制合成正例。

## 6. 详细任务清单

### P1-4.1 审查 status 当前实现

- 目标：产出当前状态系统真实能力边界，区分 executable、partial、blocked 和 discovered-only。
- 要做：审查 `systems/status.py`、`status_callbacks.py`、`scheduler.py`、`event_dispatch.py`、`rules/evaluator.py`、相关 validation；列出 AddModifier、RemoveModifier、duration tick、expire、DoT/status damage、callback、RNG 的现状。
- 验收结果：P1-4 阶段报告中有 `current_status_scope`，明确哪些 mutation 已可信，哪些字段只是 partial；新增 validation 断言 partial 不被当作完整语义。
- 禁止：不能只看验证脚本绿；不能按角色名、怪物名或固定技能 ID 选主样例。

### P1-4.2 定义 status instance identity 和 source stack

- 目标：确保同一状态实例、同源叠层、不同来源共存或替换都有稳定、可审计的 identity。
- 要做：明确 `instance_id`、`status_id`、`modifier_name`、`owner_id`、`caster_id`、`source_id`、`effect_id`、`source_stack_key` 的关系；定义什么时候匹配 existing detail，什么时候新建实例。
- 验收结果：同一 AddModifier 重复施加能稳定定位同一实例；不同来源不会误覆盖；settlement 能从 mutation metadata 反查 status detail 和 IR source。
- 禁止：不能只用 `modifier_name` 全局匹配；不能用显示名称、文本、路径片段或验证 fixture 名称决定实例归属。

### P1-4.3 实现 max stack admission

- 目标：让 `MaxLayer` / `max_layer` 从 payload 进入明确 stack policy，而不是只留下 `stack_unsupported:max_layer`。
- 要做：用 `RuleEvaluator` 解析 `max_layer`，只 admission fixed/dynamic/postfix 中当前可证明可执行的形态；非正数、未知公式、缺 source 均 blocked 或 partial process-only。
- 验收结果：支持 `max_stacks > 1` 的样例进入 executable stack policy；未知 max stack 不产生 stack mutation；source trace 指向 AddModifier payload 或 modifier definition。
- 禁止：不能把缺失 max stack 默认为某个大数；不能把所有状态都当作可叠层。

### P1-4.4 实现 add stack mutation

- 目标：重复施加同一可叠层状态时，以 mutation 更新 stack，而不是替换整个 status detail 或再造无关实例。
- 要做：新增或扩展 lifecycle operation，例如 `stack_add`；记录 `stacks_before`、`stack_delta`、`stacks_after`、`source_stack_key`；生成 `OnStack` / `OnModifierOnStack` 等已存在 callback event。
- 验收结果：stack 增加只改变目标 detail 的 stack 相关字段；status id 列表不重复；settlement record 可以定位这次叠层来源。
- 禁止：不能用直接修改 flags 的旁路；不能通过删除再添加模拟 stack。

### P1-4.5 实现 stack cap

- 目标：叠层达到上限时稳定 clamp，并记录 cap 发生。
- 要做：在 stack plan 中计算 uncapped/capped 值；达到上限时仍可根据规则刷新 duration，但 stack 不超过 `max_stacks`。
- 验收结果：重复施加超过上限后 `stacks == max_stacks`；settlement 记录 `stack_capped=true` 和被截断的 delta；replay 稳定。
- 禁止：不能让 stack 溢出；不能静默丢弃 cap 事实。

### P1-4.6 实现 stack reduce 和 stack 到 0 移除

- 目标：为后续消耗层数、状态自然减少、被驱散/特殊移除提供通用 stack reduce 底座。
- 要做：定义 `stack_reduce` plan，支持指定 delta；降到 0 时走统一 expire/remove mutation，并产生 remove/expire callback。
- 验收结果：stack 从 N 到 M 有单独 mutation；stack 到 0 后 status id 和 detail 都移除；缺 delta/source 时 blocked。
- 禁止：不能把 reduce 写成某个角色专属逻辑；不能让 stack 为负数。

### P1-4.7 实现 stack 影响 dynamic value/formula 的读取路径

- 目标：让公式里的 `Layer` 或等价 stack 读取当前 status detail，而不是固定读取初始值。
- 要做：审查并扩展 `rules/evaluator.py` status detail binding；确保 modifier ledger、DoT formula、callback formula 能读取最新 stack。
- 验收结果：stack 增加后，使用 `Layer` 的公式输出随 stack 改变；source audit 能追到 status detail mutation。
- 禁止：不能在 formula 里按 modifier 名硬编码层数；不能只在验证样例里手动传 dynamic value。

### P1-4.8 定义 refresh policy admission

- 目标：把 `is_refresh`、existing instance、duration、stack policy 组合成可解释的 refresh policy。
- 要做：定义最小支持集合：no refresh、duration refresh、stack-only refresh、stack+duration refresh、replace、coexist；不支持的组合 blocked/partial。
- 验收结果：`StatusLifecyclePlan` 中可见 refresh policy；validation 覆盖 supported 和 unsupported refresh。
- 禁止：不能继续把所有重复施加都称作 `refresh_or_replace_partial` 并产生完整 mutation。

### P1-4.9 实现 duration refresh

- 目标：重复施加时按 admitted policy 刷新剩余 duration。
- 要做：比较 `remaining_duration_before` 和新 duration；按 policy 选择 reset/max/add 等当前 admission 支持的最小集合。
- 验收结果：同一状态重复施加后 duration 变化符合 policy；settlement 记录 before/after 和 refresh source。
- 禁止：不能无条件重置 duration；不能在没有 refresh source 时刷新。

### P1-4.10 实现 stack-only refresh

- 目标：支持只叠层、不刷新持续时间的状态。
- 要做：在 stack plan 中保留原 `remaining_duration`；settlement 明确 duration unchanged。
- 验收结果：重复施加后 stack 增加但 duration 不变；replay 通过。
- 禁止：不能因为 stack mutation 顺手覆盖 duration。

### P1-4.11 实现 stack + duration refresh

- 目标：在存在真实来源时，支持同一次重复施加同时影响 stack 和 duration 的通用路径；在当前 RuleBook 没有这种来源时，诚实记录 source gap。
- 要做：先结构化扫描同一个 `AddModifier` 是否同时满足 stackable admission 和 refresh admission。若存在真实来源，将 stack delta 和 duration refresh 放进同一个 lifecycle plan 或稳定排序的两个 mutation，source trace 必须共享同一 AddModifier source。若不存在真实来源，只保留 runtime guarded path / blocked path，并在验证与报告中记录 coverage gap。
- 验收结果：有真实来源时，stack/duration 均改变且 settlement 能说明顺序，callback event 不重复或错序；没有真实来源时，验证输出 `source_gap_blocked`，没有 synthetic mutation，state unchanged。
- 禁止：不能让 stack 和 duration 分别走互不知情的路径，导致 replay 或 callback 顺序不稳定。

### P1-4.12 实现 replace/coexist 的最小可执行策略

- 目标：不同来源、同名状态、同类状态的替换/共存不再依赖偶然 instance id。
- 要做：定义 first-phase 最小策略：同 source stack key 默认叠层/刷新；不同 source 若无 coexist source 则 blocked 或明确 replace；coexist 需要 source admission。
- 验收结果：同源与异源样例行为不同且可审计；未 admission 的 coexist 不产生 mutation。
- 禁止：不能一律同名覆盖；不能一律允许共存。

### P1-4.13 定义 duration tick owner

- 目标：明确状态持续时间由谁的什么时点推进。
- 要做：把 holder turn、caster turn、action after、wave cleanup、permanent/unknown 分类写入 policy；基于 `LifeStepMoment` 和 source admission 决定支持范围。
- 验收结果：status detail 中能看到 tick owner/moment；unsupported moment blocked；永久状态不被误 tick。
- 禁止：不能只按当前 scheduler actor 扫所有状态；不能为缺失 moment 自造默认值，除非已有明确 admission 规则并写入 source trace。

### P1-4.14 实现 turn start duration tick

- 目标：支持需要在 turn start 推进的状态，或明确 blocked。
- 要做：审查 TBGD 是否有可 admission 的 turn start moment；若当前无来源，不实现 mutation，只在 report 和 validation 中标 blocked。
- 验收结果：有来源则 turn start tick 通过 transition/replay；无来源则 validation 证明不会假执行。
- 禁止：不能为了覆盖 checklist 强行把 turn end 复制成 turn start。

### P1-4.15 实现 turn end duration tick

- 目标：把已存在的 `ModifierPhase1End` tick/expire 扩展成明确 holder/caster owner policy。
- 要做：保留当前已验证能力，补齐 owner policy、source trace、negative cases 和 callback 顺序。
- 验收结果：holder turn end 状态稳定递减/过期；非 holder 状态不会被误 tick；source audit 通过。
- 禁止：不能破坏现有 `validate_v0_245` 能力。

### P1-4.16 实现 action after duration tick

- 目标：把已存在 `ActionPhaseEnd` action after hook 纳入统一 lifecycle policy。
- 要做：确认 scheduler action path 和 extra action / assistant action 的调用点；action 后 tick 只作用于 policy 指定 owner。
- 验收结果：action after 状态递减/过期；额外行动或 assistant 行动缺明确接入时 blocked 或不 tick，并有记录。
- 禁止：不能让所有单位在任意 action 后一起 tick。

### P1-4.17 实现 wave end status cleanup

- 目标：波次结束、单位 remove、召唤物消失时状态清理可审计。
- 要做：接入 P1-2/P1-3 的 wave/unit remove 事件；清理 removed unit 的 status detail；需要跨波保留的状态必须有 source admission。
- 验收结果：wave end 后 removed unit 不残留 active status detail；清理 mutation/source audit 通过；跨波保留缺来源时 blocked。
- 禁止：不能直接清空全局状态；不能让已 removed unit 的状态继续触发 callback。

### P1-4.18 实现 status expire mutation

- 目标：expire 语义完整，不只是从列表移除。
- 要做：保留并扩展当前 `_apply_expire_lifecycle_plan`；记录 expired detail、remaining_before、expire reason、callback events。
- 验收结果：expire mutation 包含 status id 和 detail 移除；OnDestroy/OnModifierRemove dispatch 可追踪；replay 通过。
- 禁止：不能只删 `statuses` 不删 `status_details`，也不能只删 detail 不删 status id。

### P1-4.19 将 DoT tick 接入状态生命周期

- 目标：DoT tick 不再只是 callback 里的独立伤害，而是状态生命周期事件触发的 status damage。
- 要做：定义 tick event payload，包括 status instance、caster、holder、tick moment、emission source；调用现有 `StatusCallbackSystem` DoT damage path。
- 验收结果：DoT tick transition 中同时可见 lifecycle event、status damage settlement、damage mutation；source trace 串联 status instance -> callback -> status damage emission。
- 禁止：不能把 DoT 当作普通 action damage；不能丢失 caster/holder 归因。

### P1-4.20 实现 tick 后 callback 触发

- 目标：状态 tick/expire/remove 后的 callback 统一通过 event dispatch，而不是系统间私调。
- 要做：让 lifecycle events 进入 `EventDispatchSystem`，并保持 mutation-backed event source；定义 tick 后可触发事件和顺序。
- 验收结果：OnDestroy/OnModifierRemove/OnStack/OnModifierDotAdd 等事件按 plan 触发；无匹配 listener 时有 skipped/process-only record。
- 禁止：不能在 status.py 中直接执行专属 callback task。

### P1-4.21 定义 chance admission

- 目标：把状态施加概率拆成 base chance、effect hit、effect resist、immunity 的明确公式链。
- 要做：读取 `Chance` payload；定义当前支持的 chance formula 形态；从 actor/target resources 或 status flags 读取 effect hit/resist；immunity 必须来自 source-admitted status/entity metadata。
- 验收结果：chance policy 中可见每个乘区/判断来源；缺任一必要 source 时 blocked 或 process-only failure。
- 禁止：不能把 chance 缺失默认为 100% 后继续执行，除非 TBGD/source 明确 guaranteed。

### P1-4.22 接入状态命中的 RNG event

- 目标：状态命中判定进入 transition rng_events。
- 要做：复用 `RNGEvent` 结构，定义 `rng_type="status_apply"` 或等价稳定名称；event_id 包含 event_index、caster、target、effect/status instance。
- 验收结果：同输入 replay 的 RNGEvent 完全一致；命中成功/失败 settlement 引用该 RNGEvent。
- 禁止：不能调用未记录的随机数；不能把 RNG 写进 global flags 后不进入 transition。

### P1-4.23 实现 status apply success settlement

- 目标：状态成功施加和生命周期 mutation 的结算语义清晰。
- 要做：新增/扩展 success record，包含 chance result、target、status instance、mutation ids、source trace。
- 验收结果：apply success 可从 settlement 找到 mutation，再找 status instance，再找 IR/TBGD source。
- 禁止：不能只保留旧 `record_type="status"` 而没有明确 success 语义。

### P1-4.24 实现 status apply failure settlement

- 目标：概率未命中不改变状态，但过程可审计。
- 要做：chance roll failed 时返回 ok 可按设计区分，但必须无 mutation、有 process-only settlement、有 RNGEvent。
- 验收结果：failure case state unchanged；transition 有失败记录和 RNGEvent；source audit 不报伪 mutation。
- 禁止：不能用异常或 unsupported 代替正常概率失败。

### P1-4.25 实现 resisted settlement

- 目标：抵抗和概率未命中分开记录。
- 要做：定义 effect resist/control resist 计算；resisted 时无状态 mutation，record 包含 resist value、roll、target source。
- 验收结果：resisted case settlement 与 chance failure 不同；RNGEvent 可 replay。
- 禁止：不能把 resisted 合并成 generic failure 丢失原因。

### P1-4.26 实现 immunity settlement

- 目标：免疫是来源明确的确定性失败，不应消耗不必要 RNG。
- 要做：从 status/entity metadata 或现有状态读取 immunity；若命中 immunity，直接 process-only settlement；是否仍记录 RNG 取决于规则顺序，必须固定。
- 验收结果：immunity case state unchanged；record 指向 immunity source；不会偷偷绕过 immunity。
- 禁止：不能用状态名文本判断免疫；不能把 unknown immunity 当作 false。

### P1-4.27 定义 dispellable、positive、negative、control 分类

- 目标：驱散和控制 gating 不靠名字，而靠 source-admitted 分类。
- 要做：扩展 `_status_metadata` 或 equivalent admission，读取 `StatusType`、`CanDispel`、control category、positive/negative 分类；无法分类则 blocked/skipped。
- 验收结果：status detail 中有 `status_category`、`can_dispel`、`control_kind` 等字段；分类来源可审计。
- 禁止：不能用 modifier_name 包含 Buff/Debuff/Control/Dot 判断。

### P1-4.28 实现确定性 dispel

- 目标：支持明确目标/明确筛选的驱散，不涉及随机选择。
- 要做：定义 dispel request/admission；按 category/can_dispel/filter 找可驱散 status；走统一 remove lifecycle plan。
- 验收结果：确定性 dispel 移除正确 status；不可驱散状态 skipped；settlement 区分 removed/skipped。
- 禁止：不能让 RemoveModifier 绕过 can_dispel 语义，除非它是 source-admitted direct remove 而不是 dispel。

### P1-4.29 实现随机 dispel 的 RNG 接入

- 目标：在存在真实 `DispelStatus Order=Random` 来源时，随机驱散选择可 replay；当前没有真实来源时，runtime 只能暴露 guarded/blocked 分支，不能产生 executable random dispel mutation。
- 要做：结构化扫描 `DispelStatus` order 来源。若发现 `Order=Random`，候选池排序稳定，使用 deterministic roll/choice，记录 `RNGEvent(rng_type="status_dispel")`；缺 choice/RNG source 时 blocked。若只发现 `Order=LastAdded` 或其他非随机 order，则 random dispel 标为 `source_gap_blocked`。
- 验收结果：有真实 random source 时，同输入 random dispel 选择一致，不同合法 choice 可由外部 RNG/branch 输入覆盖；没有真实 random source 时，验证证明 coverage gap、无 mutation、无伪 RNG 正例。
- 禁止：不能使用 Python `random`；不能依赖 dict/list 非稳定顺序。

### P1-4.30 实现 dispel skipped/failed settlement

- 目标：无可驱散目标、目标免疫驱散、筛选 unsupported 等都要显式记录。
- 要做：定义 `status_dispel_skipped` / `status_dispel_blocked` / `status_dispel_failed` 的 process-only record。
- 验收结果：no candidate 不产生 mutation；settlement 说明原因和候选池；source audit 通过。
- 禁止：不能静默无事发生。

### P1-4.31 定义 control 对 action availability 的 gating

- 目标：控制状态影响“是否可行动/可使用某类 action”，供外部推演器查询。
- 要做：在 `ActionAvailabilitySystem` 或同等入口加入 status control gate；输出 blocked reason、status instance id、control kind、source trace。
- 验收结果：被控制单位 action candidate 被标记 blocked/unavailable；非控制状态不影响 availability；removed/defeated gating 仍优先。
- 禁止：不能在 executor 深处才发现不可行动；不能靠敌方 AI 规避非法动作。

### P1-4.32 定义 control 对 timeline/queue 的最小影响

- 目标：控制状态对已在 timeline/queue 中的行动有规则化结果。
- 要做：定义第一阶段最小集合：skip current action、block queue drain、delay/AV change 如果无来源则 blocked；与 P1-5 queue/window 保持边界。
- 验收结果：control block transition 有 process event/settlement；不会执行被控制阻塞的 action mutation。
- 禁止：不能随意清空队列或重排 timeline；不能把所有控制都当成同一种效果。

### P1-4.33 增加 status apply success 验证

- 目标：证明成功施加状态完整走 admission -> mutation -> settlement -> source audit。
- 要做：结构化选择 guaranteed AddModifier 样例；执行 transition；检查 status id/detail、records、events、source audit、replay。
- 验收结果：`validate_p1_4_status_system` 中 success case ok。
- 禁止：不能固定角色名/状态名作为主选择条件。

### P1-4.34 增加 chance failure 验证

- 目标：证明概率失败不会产生状态 mutation。
- 要做：构造或选择 non-guaranteed chance 样例；用 deterministic RNG 令其失败。
- 验收结果：state unchanged；有 RNGEvent 和 failure settlement。
- 禁止：不能用 unsupported/error 冒充概率失败。

### P1-4.35 增加 resisted 验证

- 目标：证明 resist 与 chance failure 分开。
- 要做：构造 target effect_resistance 或 source-admitted resist；令 resist 分支触发。
- 验收结果：无状态 mutation；settlement record type/reason 是 resisted。
- 禁止：不能仅检查 ok=false。

### P1-4.36 增加 immunity 验证

- 目标：证明 immunity source 会阻止状态施加。
- 要做：选择或构造 source-admitted immunity 状态/entity；执行 AddModifier。
- 验收结果：无状态 mutation；settlement 指向 immunity source；RNG 消耗顺序符合 policy。
- 禁止：不能用名字匹配 immunity。

### P1-4.37 增加 stack cap 验证

- 目标：证明叠层和 cap 稳定。
- 要做：重复施加可叠层状态超过 max stack；检查 stack before/after/capped。
- 验收结果：stack 不超过 max；status id 不重复；replay/source audit 通过。
- 禁止：不能只检查最终状态，不检查 settlement。

### P1-4.38 增加 duration refresh 验证

- 目标：证明 refresh policy 对 duration 的影响可审计。
- 要做：先施加、tick 一次、再重复施加；检查 remaining duration 按 policy 变化。
- 验收结果：refresh mutation/record 包含 before/after/source。
- 禁止：不能跳过 tick 直接比较初始值。

### P1-4.39 增加 DoT tick 验证

- 目标：证明 DoT tick 是 lifecycle 驱动的 status damage。
- 要做：选择 status damage emission 可执行样例；触发 tick；检查 lifecycle event、DoT damage record、damage mutation、source trace。
- 验收结果：damage source kind 是 `dot`；caster/holder/status instance 归因正确。
- 禁止：不能用普通 action damage 假装 DoT。

### P1-4.40 增加 expire remove 验证

- 目标：证明状态过期移除完整。
- 要做：让 duration tick 到 0；检查 status id/detail 同时移除，callback event 出现。
- 验收结果：expire mutation 和 remove callback settlement 均可追溯。
- 禁止：不能只验证 `statuses` 列表。

### P1-4.41 增加 deterministic dispel 验证

- 目标：证明确定性驱散走分类和 can_dispel。
- 要做：准备可驱散/不可驱散状态；执行 dispel；检查候选池和移除结果。
- 验收结果：只移除 eligible status；不可驱散状态产生 skipped settlement。
- 禁止：不能直接用 RemoveModifier 指定固定 status id 代替 dispel 验证。

### P1-4.42 增加 random dispel replay 验证

- 目标：证明随机驱散在有真实来源时可 replay；当前无真实 random dispel 来源时，证明它被正确记录为 source gap。
- 要做：若结构化扫描找到 `DispelStatus Order=Random`，同输入运行两次，比较 RNGEvent、候选池和结果，必要时测试不同 explicit choice。若没有真实来源，验证必须输出 random dispel coverage gap，并证明 synthetic case 不会被接纳为 executable。
- 验收结果：有真实来源时，同输入完全一致，缺 RNG/choice 时 blocked；无真实来源时，只有 source-gap/blocked 结论，无 random dispel mutation 正例。
- 禁止：不能让验证依赖运行时随机状态。

### P1-4.43 增加 control blocks action 验证

- 目标：证明 control gating 影响 action availability 和执行前检查。
- 要做：给单位添加 control status；查询 action availability；尝试执行被阻塞 action。
- 验收结果：availability blocked；执行路径不产生 action effect mutation；settlement 指向 control status。
- 禁止：不能只测试 UI 或 scenario 层。

### P1-4.44 增加缺 chance/formula/source blocked 验证

- 目标：证明缺来源不会假执行。
- 要做：覆盖缺 chance formula、unsupported chance formula、缺 duration source、unsupported target、缺 immunity source 等 negative cases。
- 验收结果：state unchanged；process-only blocked record；无 mutation；source audit 通过。
- 禁止：不能把 negative case 写成抛异常后验证通过。

### P1-4.45 更新阶段报告

- 目标：把 P1-4 做到哪里、可信范围、blocked 范围和剩余完整复刻差距写清楚。
- 要做：新增 `live_validation_reports/v8_p1_4_status_system_checkpoint_*.md`；更新 checklist 勾选；说明验证命令、source audit、replay、negative validation。
- 验收结果：报告能回答当前最小可用战斗纵切还缺什么、距离完整复刻还缺哪些状态模块。
- 禁止：不能只写“验证通过”；必须说明通用性、扩展性和红线审查结果。

## 7. 新增验证矩阵

建议新增：

```text
python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_system
```

该验证至少包含：

- status apply success。
- chance failure。
- resisted。
- immunity。
- stack add。
- stack cap。
- stack reduce/remove。
- duration refresh。
- stack-only refresh。
- stack + duration refresh；若当前 RuleBook 无同源 stackable + refresh-admitted AddModifier，则必须记录为 source gap，不能合成正例。
- duration tick。
- expire remove。
- DoT tick。
- deterministic dispel。
- random dispel replay；若当前 TBGD / IR 无 `DispelStatus Order=Random` 来源，则必须记录为 source gap，不能合成正例。
- control blocks action availability。
- control blocks execution/queue drain 的最小路径。
- unsupported chance/formula/source/target blocked。
- partial/discovered-only/audit-only 不产生 mutation。
- mutation -> settlement -> source trace -> IR source audit。

回归命令建议：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_0_action_boundary --output-dir /tmp/hsr_v8_p1_0_action_boundary
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_1_unit_lifecycle --output-dir /tmp/hsr_v8_p1_1_unit_lifecycle
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_2_wave_system --output-dir /tmp/hsr_v8_p1_2_wave_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_status_system
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_status_duration_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_257 --output-dir /tmp/hsr_v8_damage_family_v0_257
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_bounce_rng_v0_264
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289
git diff --check
```

如某个旧验证因 P1-4 收紧来源边界而失败，优先升级验证输入到真实来源链路；禁止为了旧 smoke 保留假执行路径。

## 8. 完成口径

P1-4 的完成口径拆成两层，避免把“来源缺口”误判成“代码未完成”，也避免把 synthetic 正例误判成真实完成。

### 8.1 状态底座验收，带来源缺口

- stack、refresh、duration、tick、chance/resist/immunity、dispel、control gating 都有通用 admission 和明确 blocked 边界。
- 当前 RuleBook / Canonical IR 有真实来源的机制，都有 positive executable validation。
- 当前 TBGD / IR 没有真实来源的机制，必须有结构化 discovery/coverage gap 证据，并且验证证明不会产生 synthetic mutation。
- 所有状态变化都通过 `Mutation` 表达。
- 所有概率/随机路径都进入 `RNGEvent`，同输入 replay 稳定。
- 所有 mutation 都能追到 settlement，再追到 StatusInstance/source trace，再追到 Canonical IR/TBGD source。
- negative validation 证明缺 source、缺 formula、unsupported target、unsupported policy、missing RNG/choice 不会产生 mutation。
- P1-0 到 P1-3 的核心验证仍通过。
- 阶段报告明确说明当前可信范围和剩余 blocked 范围。

满足以上条件时，可以给出“P1-4 状态底座已验收，带来源缺口”的工程结论，并继续规划后续阶段。这个结论不等同于所有 checklist 子项都有真实正例。

### 8.2 P1-4-DONE 全正例完成

```text
P1-4-DONE 状态 stack、refresh、duration、tick、chance/resist/immunity、dispel、control gating 形成通用底座并通过验证。
```

如果 `P1-4-DONE` 被定义为“所有列项都有真实正例 executable”，则必须等 `P1-4.11 stack + duration refresh` 和 `P1-4.29 / P1-4.42 random dispel` 找到真实 TBGD / IR 来源后才能勾选。当前只能把它们记录为 source gap，不能因为 runtime 有 guarded path 就标 DONE。

## 9. 后续影响

P1-4 完成后，后续阶段可以复用：

- P1-5 queue/window：状态 callback、control block、extra action、counter/follow-up 的窗口语义。
- P1-6 target：状态施加/驱散/random target 的稳定目标解析与 RNG 事件。
- P1-7 RNG：已有 status RNG event 可以纳入统一 branch enumeration。
- P1-8 battle setup：可配置有状态、有召唤、有 deterministic RNG 的最小战斗。
- 角色/怪物/光锥/遗器扩面：专属机制进入数据卡/IR，runtime 只走通用状态系统。

P1-4 做完后仍不会得到“完整复刻全部状态”的模拟器。它的价值是把状态机制的底层接口、来源审计、生命周期和失败边界做正，使后续扩面不再把每个角色或怪物状态写成 core 特判。
