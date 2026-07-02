# P1-6 目标系统关键缺口总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-6 目标系统关键缺口` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-6 的实现、验证和阶段报告。

P1-6 的一句话目标：

```text
在 v0_288/v0_289 已有目标表达式底座上，补齐第一阶段最影响通用战斗的 sort / fetch / adjacent / random / unique / summon / servant 目标解析，并保持缺来源或缺上下文时 blocked/state unchanged。
```

P1-6 不是“让所有目标表达式都能跑”。目标系统是战斗内核最容易引入错误 fallback 的地方：一旦缺目标时默认打当前目标、缺排序时默认 unit id 顺序、缺随机输入时偷偷用进程随机数，后续推演结果就会失真。因此本阶段的核心不是覆盖率数字，而是把目标解析的来源、候选池、筛选、排序、随机、选择和失败原因做成可审计契约。

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终目标不是在 core 中写敌方 AI，而是支持外部推演器搜索：

```text
给定战斗配置、动作选择和随机分支
=> core 判断合法性、执行规则、输出完整 transition
=> 外部推演器从可能路径中寻找达成目标的通关方式
```

目标系统在这个架构中的职责是：

- 根据 Canonical IR / 数据卡 IR / runtime event payload 解析合法目标。
- 产出完整 target resolution record。
- 在缺来源、缺 payload、unsupported sort/fetch/random/unique 时 blocked。
- 不做策略选择，不做敌方 AI，不从文本或旧模拟器推断目标。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR 或 scenario/setup 层已经构造好的 runtime setup。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测伤害或手工答案作为规则输入。

### 0.2 P1-6 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

前置阶段状态：

- P1-0 Action Boundary：core 暴露行动候选和 transition，不做 AI。
- P1-1 UnitLifecycle：`active / defeated / removed` 已进入 target、damage、timeline、queue。
- P1-2 WaveSystem：多波和 UnitSpawn/UnitRemove 已有通用 mutation。
- P1-3 Summon / Assistant / Servant：召唤物、assistant、servant 有最小分类和 summon runtime，但 servant 目标仍多为 source gap。
- P1-4 StatusSystem：状态施加、tick、DoT、control gating 等依赖目标表达式。
- P1-5 Queue/Window：queue item 已有 actor/target resolution、mandatory/selectable/blocked 语义；复杂 queue target 仍需要 P1-6 扩面。

已有目标表达式检查点：

- v0_288：`TargetExpressionIR`、简单 `TargetAlias`、明确群体、AddModifier runtime target expression source trace。
- v0_289：`TargetSequence`、`TargetConcat`、`TargetFilter`、确定性 `Retarget`、上下文目标列表、缺 payload blocked。

P1-6 承接 v0_289，支撑后续：

- P1-7 RNG：random target、random retarget、random fetch 需要统一 RNG/choice ledger。
- P1-8 BattleSetup：scenario 需要能配置 target context、summon runtime、deterministic choices。
- 角色/怪物扩面：大量状态、追击、反击、召唤物技能、关卡实体依赖 sort/fetch/adjacent/unique。

### 0.3 星铁目标系统相关概念

星铁目标语义至少包含这些形态：

1. **显式目标**
   - 玩家或推演器给出的 action target。
   - 已由 `TargetPolicy` / `resolve_action_targets` 覆盖一部分。

2. **上下文目标**
   - `Caster`、`ModifierOwnerEntity`、`ParamEntity`、`CurrentActionTarget`、`AbilityTargetEntity`、`SkillTargetEntityList`、事件 payload target list。
   - v0_288/v0_289 已支持安全子集。

3. **群体目标**
   - `AllEnemy`、`AllTeamMember`、`AllLightTeam`、`AllDarkTeam`、`TeamFormation` 等。
   - 已支持若干稳定群体，后续仍需区分 selectable、unselectable、dead/alive。

4. **排序目标**
   - 按 HP、HP ratio、toughness、position、speed、aggro 等排序后取前 N 个。
   - 当前 lowering 对 `TargetSort*` 全 blocked。

5. **fetch 目标**
   - 从 caster、owner、partner、unique entity、summon runtime、servant owner、event payload 取目标。
   - 当前 lowering 对 `TargetFetch*` 全 blocked。

6. **相邻目标**
   - 扩散伤害、blast、相邻状态、相邻召唤物或站位相关效果需要。
   - 当前普通 action 的 `blast` 是 action target group，不等于通用 target expression adjacent。

7. **随机目标**
   - 随机 debuff、随机 retarget、随机 bounce、随机召唤物/敌方目标。
   - 当前 bounce 有 deterministic `RNGEvent`，但通用 target expression random 仍未支持。

8. **unique entity / summon / servant target**
   - 特殊实体、owner summon、enemy summon、servant、assistant 行动目标。
   - P1-3 提供了 summon runtime 基础，但 P1-6 需要定义 target expression 如何读取它。

P1-6 的重点是把这些形态纳入统一解析记录和 source admission，不是一次性覆盖所有奇特玩法目标。

### 0.4 当前代码事实

当前主要落点：

```text
systems/target.py
systems/status.py
systems/status_callbacks.py
systems/effect.py
systems/action_availability.py
systems/queue.py
systems/unit_lifecycle.py
systems/unit_relation.py
rules/ir.py
rules/evaluator.py
rules/rulebook.py
tbgd/lowering.py
tools/validate_v0_288.py
tools/validate_v0_289.py
```

当前事实：

- `TargetExpressionIR` 字段包括 `target_expression_id`、`expression_kind`、`alias`、`payload`、`source`、`coverage_status`、`blocked_reason`、`admission_batch`、`runtime_scope`。
- `TargetSystem.resolve_target_expression` 返回 `TargetExpressionResult`，包含 `ok`、`target_ids`、`blocked_reason`、`expression_id`、`expression_kind`、`alias`、`metadata`。
- runtime 已支持 `TargetAlias` 安全子集，包括 `Caster`、`ModifierOwnerEntity`、`ParamEntity`、`CurrentActionTarget`、`AbilityTargetEntity`。
- runtime 已支持上下文列表：`SkillTargetEntityList`、`ParamEntitySkillTargetEntityList`、`ParamEntityList`。
- runtime 已支持群体别名：`AllEnemy`、`AllTeamMember`、`AllLightTeam`、`AllDarkTeam`、`AllTeammate`、`TeamFormation`、`AllEnemyWithUnSelectable` 的一部分。
- runtime 已支持 summon runtime 相关别名：`LastSummonMonsters`、`CasterSummonedMinions`；依赖 `global_flags["summon_runtime"].schema_version == "p1_3_summon_runtime_v1"`。
- runtime 已支持 `TargetConcat`、`TargetSequence`、`TargetFilter`、确定性 `Retarget`。
- `TargetFilter` 复用 `RuleEvaluator.evaluate_condition_result`，unsupported condition blocked。
- `Retarget` 当前 `ByRandom=True` 明确 blocked，`TargetType` 缺失 blocked，`MaxNumber` 只支持 fixed positive；动态 max number 仍 blocked。
- `TargetSystem.resolve_bounce_hit_target` 已有 deterministic bounce target `RNGEvent(rng_type="bounce_target")`，但这不是通用 random target expression。
- `tbgd/lowering.py` 已把 `TargetSort*` 标为 `blocked: target_sort_not_admitted:*`。
- `tbgd/lowering.py` 已把 `TargetFetch*` 标为 `blocked: target_fetch_not_admitted:*`。
- `validate_v0_289` 统计显示 target expression 已大量 lowered，其中 `TargetSequence=128`、`Retarget=823`、大量 `TargetAlias` executable；`TargetSort*` / `TargetFetch*` 仍 blocked。
- `QueueTargetResolver` 中有一套 queue 专用 alias 解析，和 `TargetSystem` 有重叠。P1-6 不一定要合并，但计划和验证必须避免两套系统语义越来越远。

当前最重要的风险：

```text
TargetExpressionIR 已有大量 executable，但关键缺口全部集中在 sort/fetch/random/unique/adjacent。
如果 P1-6 为了提高 coverage 而默认排序、默认随机、默认目标，模拟器会比 blocked 更危险。
```

### 0.5 来源缺口验收口径

P1-6 的每个子项必须按三态判断：

- `executable`：当前 RuleBook / Canonical IR 中存在真实来源，runtime resolution、settlement/source trace、replay 均通过。
- `source_gap_blocked`：runtime 可以有 guarded path、blocked path 或未来预留字段，但当前 TBGD / IR 结构化扫描没有真实可执行来源；验证只能证明 coverage gap、blocked、state unchanged，不能合成正例 mutation。
- `implementation_missing`：当前存在真实来源，但 runtime 没有正确 admission / resolution / record / replay，这才是需要继续编码修复的缺口。

高风险项：

- `TargetSort`：如果真实来源存在但排序 key 未 admission，是 implementation_missing；如果某 key 当前数据库没有样例，则只能 source gap。
- `TargetFetch partner / unique entity / servant`：必须先确认 raw/IR 中有结构化字段，不得按名字或路径推断。
- `random target`：P1-6 可建立 deterministic choice / blocked contract；完整 RNG 分支枚举属于 P1-7。若缺 choice，不得调用进程随机数。
- `adjacent target`：必须依赖站位/formation source 或 runtime unit position；缺 position 时 blocked。

## 1. 非目标

P1-6 不做以下内容：

- 不做敌方 AI 或自动目标策略。
- 不一次性覆盖全部目标表达式 opcode。
- 不用 TextMap、技能文本、角色名、怪物名、固定技能 ID、固定文件名、固定 hash 或观测结果决定目标。
- 不把 unit id 排序当作缺排序规则的 fallback；unit id 只能作为已 admission 后的 deterministic tie-breaker，并且必须写入 record。
- 不在缺 event payload 时默认使用 caster、owner、当前 action target 或第一个敌人。
- 不在缺 random choice 时使用 Python `random` 或不可审计的 hash。
- 不把 P1-3 summon runtime 目录字段自动解释成 servant/unique entity 目标。
- 不为旧 v7、旧 model pack、旧 CLI 或旧 JSON 做兼容。
- 不把 UI scenario 或测试 fixture 当规则来源。
- 不在 P1-6 实现完整 P1-7 branch enumeration；这里只建立 target random 的最小 replay/blocked 契约。

## 2. 总体实现原则

### 2.1 目标解析必须有完整 record

每次 target expression 解析至少应记录：

- `target_expression_id`
- `expression_kind`
- `source`
- `caster_id`
- `owner_id`
- `context target`
- `event_payload_keys`
- `candidate_pool_before`
- `candidate_pool_after_filter`
- `sort_key / sort_direction / tie_breaker`
- `random_choice / rng_event_id / candidate_pool`
- `selected_targets`
- `skipped_targets`
- `blocked_reason`
- `resolution_steps`

现有 `TargetExpressionResult.metadata["resolution_steps"]` 可以继续扩展；如果需要面向 transition 的标准 record，可新增小结构，但不要绕过 `TargetResolution` / settlement。

### 2.2 Admission 先于 runtime 解析

TargetSort/Fetch/Random/Adjacent/Unique 的执行必须先在 lowering / RuleBook 中得到可执行 admission：

```text
raw TBGD node
-> TargetExpressionIR normalized payload
-> admission_batch / coverage_status
-> runtime resolver
-> TargetExpressionResult
```

缺 admission 时 runtime 必须返回 blocked，不能在 runtime 直接识别 raw schema 并执行。

### 2.3 候选池和生命周期必须统一

所有目标候选必须通过 `UnitLifecycleSystem.can_target` 或明确的 allow defeated policy。P1-6 至少要区分：

- active target。
- defeated but still referenced target。
- removed target。
- summon side target。
- servant/assistant runtime target。
- unselectable target。

缺 alive/dead/unselectable source 时 blocked，而不是默认过滤。

### 2.4 random target 必须可 replay

P1-6 可以有两种可接受实现：

- 已有 deterministic `RNGEvent` 风格：类似 bounce target，用 stable event_id 和 candidate pool 生成 record。
- explicit choice ledger：外部 command / metadata 提供 choice，transition 记录 choice。

如果当前阶段无法完整接 P1-7 RNG ledger，则必须返回 `requires_rng_choice` 或 blocked/state unchanged。不能偷偷随机。

### 2.5 TargetSystem 与 QueueTargetResolver 边界

P1-5 之后 queue 已有 `QueueTargetResolver`。P1-6 不要求立即合并两套解析器，但必须做到：

- 新增通用 target expression 能力优先进入 `TargetSystem`。
- queue 专用 alias 若复用同类语义，应保持 blocked reason 和 lifecycle filter 一致。
- 阶段报告说明两套解析入口的差异和后续是否需要收敛。

## 3. 建议代码落点

实际实现 agent 应先阅读当前代码再动手。优先落点：

- `systems/target.py`
  - `TargetExpressionResult`
  - `_resolve_inline_expression`
  - `_resolve_target_alias_ids`
  - `_resolve_filter_expression`
  - `_resolve_retarget_expression`
  - `resolve_bounce_hit_target`
  - 新增 sort/fetch/adjacent/random/unique helper

- `tbgd/lowering.py`
  - `_target_expression_admission`
  - `_target_expression_runtime_blocked_reason`
  - `_target_expression_normalized_payload`
  - `_target_expression_kind`
  - `TargetSort*` / `TargetFetch*` admission

- `rules/ir.py`
  - `TargetExpressionIR` 字段是否足够；优先通过 normalized payload 扩展，避免过早新增大 dataclass。

- `rules/evaluator.py`
  - dynamic max number、filter/sort 公式读取。

- `systems/status.py`
  - AddModifier / RemoveModifier target expression runtime integration。

- `systems/status_callbacks.py`
  - event payload target list、retarget/filter payload。

- `systems/effect.py`
  - EffectExecutionContext target expression 调用。

- `systems/action_availability.py`
  - action target enumeration 与 target expression 的差异说明。

- `systems/unit_lifecycle.py`
  - dead/alive/removed target gate。

- `systems/unit_relation.py`
  - ally/enemy/summon/servant 关系。

- `tools/`
  - 新增 `validate_p1_6_target_system.py`。
  - 扩展旧 v0_288/v0_289 只作为直接回归，不替代 P1-6 主验证。

- `live_validation_reports/`
  - 新增 P1-6 阶段报告。

不建议一开始新增完整 target AST。优先扩展当前 normalized payload 和 resolver steps；只有当 sort/fetch/random 的 normalized 结构重复到影响清晰度时，再引入小 dataclass/helper。

## 4. 内部闸门

P1-6 应按内部闸门推进：

```text
Gate A: 当前 TargetExpressionIR / TargetSystem / validation 范围审计
Gate B: target resolution record 标准化
Gate C: TargetSort admission 与 HP/HP ratio 正例
Gate D: toughness / position sort 或 source-gap blocked
Gate E: TargetFetch caster / owner / context / unique entity
Gate F: adjacent target 与 formation/position source
Gate G: random target deterministic choice / RNG event / blocked contract
Gate H: summon / servant target
Gate I: dynamic max number admission
Gate J: negative validation / source audit / layered regression / report
```

每个闸门都必须按三态验收；没有真实来源时只能 `source_gap_blocked`。

## 5. 详细任务清单

### P1-6.1 审查当前 target 实现和 admission

- 目标：产出当前目标系统真实能力边界。
- 要做：审查 `systems/target.py`、`tbgd/lowering.py`、`rules/ir.py`、`validate_v0_288.py`、`validate_v0_289.py`；统计 TargetExpressionIR kind/alias/coverage；列出 TargetSort/TargetFetch/Retarget random/unique/summon/servant 当前 blocked reason。
- 验收结果：阶段报告有 `current_target_scope`，明确 executable、source_gap_blocked、implementation_missing；验证输出 target source matrix。
- 禁止：不能只引用 v0_289 报告；必须根据当前代码和当前 RuleBook 重新扫描。

### P1-6.2 定义 target resolution record 完整字段

- 目标：让每次目标解析都有可审计 record，支持 transition/replay/source audit。
- 要做：扩展 `TargetExpressionResult.metadata["resolution_steps"]` 或新增轻量 record helper；统一记录 candidate pool、filter/sort/random/fetch/adjacent/unique 步骤、blocked reason、source trace、event payload keys。
- 验收结果：TargetAlias、TargetSequence、TargetFilter、Retarget、Sort/Fetch 新路径都输出一致结构；negative case 也有 blocked record。
- 禁止：不能只在日志中记录；不能只在成功路径记录。

### P1-6.3 实现 TargetSort admission

- 目标：让 `TargetSort*` 不再全量 blocked，而是按 sort key/source 分三态。
- 要做：解析 raw `TargetSort*` 的 kind、source candidate、sort key、direction、max number、filter；支持当前能证明的 key；未知 key blocked 并保留 source trace。
- 验收结果：RuleBook 中至少一种真实 `TargetSort*` 进入 executable，或结构化扫描证明当前无可执行 key 并输出 source gap；blocked sort 不产生 mutation。
- 禁止：不能缺 key 时默认按 unit id 或 HP 排序。

### P1-6.4 实现按 HP / HP ratio 排序

- 目标：支持最常见的生命值排序目标。
- 要做：从 UnitState 读取 `hp`、`max_hp`；定义 ascending/descending；处理 max_hp <= 0 blocked；tie-breaker 使用明确 engine convention 并记录。
- 验收结果：多个候选按 HP 或 HP ratio 选中正确目标；resolution_steps 包含候选池、key 值、方向、tie-breaker；source audit 通过。
- 禁止：不能用当前输入顺序当排序；不能缺 direction 时猜测方向，除非 source 明确默认。

### P1-6.5 实现按 toughness 排序或明确 blocked

- 目标：处理韧性相关排序。
- 要做：审查 UnitState / break system 是否有可用 toughness 字段和来源；若字段/source 不足，保持 `source_gap_blocked` 或 `implementation_missing`，并验证 state unchanged。
- 验收结果：有真实来源和字段时可执行；否则阶段报告说明 blocking dependency，验证 blocked。
- 禁止：不能用 `max_toughness`、break damage 或旧经验猜当前 toughness。

### P1-6.6 实现按 position 排序或明确 blocked

- 目标：处理站位排序和后续 adjacent 的基础。
- 要做：审查 UnitState flags、team order、active_teams 是否可作为 position source；定义 ally/enemy/summon 队列中的 stable position；缺来源时 blocked。
- 验收结果：有 position source 时可按 position 排序；缺 source 时 missing position blocked；tie-breaker 记录。
- 禁止：不能默认用 unit_id 字典序当站位。

### P1-6.7 实现 TargetFetch caster

- 目标：让结构化 TargetFetch caster 进入可执行来源。
- 要做：识别 TargetFetch 中指向 caster 的真实 raw/normalized 字段；runtime 返回 caster_id，且校验 caster 存在和生命周期。
- 验收结果：真实 TargetFetch caster 样例解析成功；缺 caster blocked；source trace 指向 TargetExpressionIR。
- 禁止：不能把所有 unknown fetch 都 fallback 到 caster。

### P1-6.8 实现 TargetFetch owner

- 目标：让 owner-based fetch 可用于状态、召唤物、servant 后续机制。
- 要做：从 `owner_id`、status detail、summon runtime 或 event payload 读取 owner；缺 owner blocked。
- 验收结果：真实 owner fetch 样例成功；owner missing / removed blocked。
- 禁止：不能 owner 缺失时默认 caster。

### P1-6.9 实现 TargetFetch partner 或明确 blocked

- 目标：处理 partner/linked unit 目标。
- 要做：结构化扫描 TargetFetch partner 来源；若当前没有 partner runtime/source，记录 source gap；若有，定义 partner source 字段和 lifecycle。
- 验收结果：有真实来源则 executable；无来源则 source_gap_blocked 且无 mutation。
- 禁止：不能按相邻站位或同队第一个单位冒充 partner。

### P1-6.10 实现 TargetFetch unique entity

- 目标：支持唯一实体目标，或在找不到唯一实体时明确 blocked。
- 要做：定义 unique key 来源、runtime registry 位置、候选池唯一性；0 个或多个候选都 blocked；source trace 记录 key。
- 验收结果：唯一实体存在时解析成功；不存在或多于一个时 blocked/state unchanged。
- 禁止：不能按名字文本或路径片段匹配唯一实体。

### P1-6.11 实现 adjacent target

- 目标：为 blast/相邻状态提供通用相邻目标解析。
- 要做：基于 admitted position source 获取 primary target 左右相邻；区分同侧敌方队列、我方队列、summon side；removed/defeated 过滤策略必须有来源。
- 验收结果：primary target 两侧相邻解析稳定；边缘位置只返回存在的一侧；缺 primary/position blocked。
- 禁止：不能把 active_teams 字典序直接当相邻规则，除非明确 position source。

### P1-6.12 实现 random target deterministic choice 接入

- 目标：让通用 random target 在缺 choice 时不偷偷随机，在有 deterministic choice 时可解析。
- 要做：定义 target expression random 的 candidate pool、choice id、外部 choice metadata 或 deterministic roll 输入；缺 choice 返回 blocked 或 `requires_rng_choice`。
- 验收结果：同一 choice 解析同一目标；候选池变化会使 invalid choice blocked；缺 choice state unchanged。
- 禁止：不能使用 Python `random`；不能用 hash 随机但不记录。

### P1-6.13 实现 random target RNG event 记录

- 目标：random target 结果进入 transition 可 replay 记录。
- 要做：复用 `RNGEvent` 风格，定义 `rng_type="target_random"`；记录 candidate pool、selected index/id、source trace、event id。若完整 transition rng_events 需要 P1-7 扩展，P1-6 至少输出 process result 并标明 P1-7 dependency。
- 验收结果：random target replay case 能比较 RNGEvent/result；缺 RNG choice blocked。
- 禁止：不能只把随机结果写进 metadata 而不进入可 replay 记录。

### P1-6.14 实现 summon target

- 目标：让 owner summon / last summon / all summon 等目标通过 P1-3 summon runtime 安全解析。
- 要做：复用 `LastSummonMonsters`、`CasterSummonedMinions`，扩展必要 alias/fetch；校验 summon runtime schema、owner、lifecycle、side/team。
- 验收结果：真实 summon target 样例解析成功；summon runtime missing、owner missing、summon removed blocked。
- 禁止：不能读取 raw summon config；不能按 side=="summon" 全量返回而不看 source。

### P1-6.15 实现 servant target 或明确 blocked

- 目标：处理 servant 目标的第一阶段边界。
- 要做：结构化扫描 servant target/fetch 来源；若 runtime 没有 servant entity registry，标 `source_gap_blocked` 或 `implementation_missing`；若已有 owner-bound servant，则定义 fetch source。
- 验收结果：当前无真实来源时有 source gap 验证；有来源时 servant target 解析成功且 source audit 完整。
- 禁止：不能因为文件路径含 Servant 就返回 summon 或 owner。

### P1-6.16 实现 dynamic max number admission

- 目标：让 Retarget/Sort/Fetch 的 MaxNumber 能从可执行动态值读取。
- 要做：复用 `RuleEvaluator.evaluate_numeric` 和 binding_sources；只 admission fixed positive、admitted dynamic value、可证明公式；未知公式 blocked。
- 验收结果：dynamic max number 正例按运行时值截断目标；缺 binding blocked。
- 禁止：不能把 dynamic max number 缺失默认为 1 或 all。

### P1-6.17 明确缺排序规则 blocked

- 目标：证明缺 sort key/direction/source 不会 fallback。
- 要做：覆盖 TargetSort 缺 key、unknown key、missing direction、unsupported formula。
- 验收结果：blocked reason 具体，state unchanged，无 mutation。
- 禁止：不能让 sort fallback 到 unit id 或输入顺序。

### P1-6.18 明确缺 payload blocked

- 目标：证明上下文目标必须有 event payload 或 target resolution。
- 要做：覆盖 `ParamEntityList`、`SkillTargetEntityList`、Retarget TargetType、Adjacent primary target、Fetch owner 等缺 payload。
- 验收结果：blocked reason 具体，state unchanged。
- 禁止：不能 fallback 到 caster/current target。

### P1-6.19 明确 unique entity 找不到 blocked

- 目标：证明 unique entity 0 个或多个候选都不会假执行。
- 要做：构造 missing unique key、duplicate unique key case；检查 no mutation。
- 验收结果：`unique_entity_missing` / `unique_entity_ambiguous` 或等价 reason。
- 禁止：不能取第一个候选。

### P1-6.20 明确 random 缺 RNG choice blocked 或返回需要 choice

- 目标：证明 random target 没有可 replay choice 时不会执行。
- 要做：执行 random target expression，缺 choice 返回 blocked 或 `requires_rng_choice`；验证没有 target mutation/status mutation。
- 验收结果：blocked/process-only record 包含 candidate pool 和 choice requirement。
- 禁止：不能静默使用 deterministic hash 后还说没有 RNG event。

### P1-6.21 增加 HP ratio sort 验证

- 目标：证明 HP ratio sort 正例完整。
- 要做：结构化选择真实 HP ratio sort 来源；若没有，输出 source gap；有来源时构造多目标不同 hp ratio。
- 验收结果：目标顺序/选择正确，record/source audit/replay 通过。
- 禁止：不能 synthetic 改 IR 伪造 TargetSort 来源。

### P1-6.22 增加 adjacent target 验证

- 目标：证明相邻目标依赖 position source。
- 要做：准备带 admitted position 的队列；测试中间、边缘、removed neighbor。
- 验收结果：相邻目标集合稳定；缺 position blocked。
- 禁止：不能只测试 unit id 邻近。

### P1-6.23 增加 random target replay 验证

- 目标：证明 random target 可 replay 或诚实 blocked。
- 要做：有真实 random source 时跑同输入两次比较 RNGEvent/selected；缺 choice 时 blocked；无真实 random source 时 source gap。
- 验收结果：同输入同结果；候选池和 selected index 记录完整。
- 禁止：不能用运行时随机结果作为预期答案。

### P1-6.24 增加 unique summon target 验证

- 目标：证明 summon runtime target 可用于 unique/fetch。
- 要做：基于 P1-3 summon runtime 构造 owner summon 或 last summon；使用真实 alias/fetch 来源；检查 removed summon 被过滤。
- 验收结果：unique summon target 成功或 source gap；缺 runtime blocked。
- 禁止：不能把手写 summon id 当规则来源。

### P1-6.25 增加 dead/alive filter 验证

- 目标：证明 lifecycle filter 进入 target expression。
- 要做：构造 active/defeated/removed 候选；测试 allow_defeated source 和默认 filter。
- 验收结果：dead/alive 行为符合 source；缺 source blocked。
- 禁止：不能默认所有 defeated 都可选或都不可选而不记录。

### P1-6.26 增加 missing sort blocked 验证

- 目标：证明 sort negative case 不产生 mutation。
- 要做：选择真实 blocked TargetSort 或 synthetic boundary expression 只用于 negative；验证 `coverage_status != executable` 不执行。
- 验收结果：blocked reason 与 source trace 可见。
- 禁止：不能用 negative synthetic 当 positive。

### P1-6.27 增加 missing payload blocked 验证

- 目标：证明缺 event payload/context 不 fallback。
- 要做：覆盖 target list、fetch owner、adjacent primary、unique key、random choice 缺失。
- 验收结果：每类缺口 state unchanged，record 完整。
- 禁止：不能只检查 ok=false；必须检查没有 mutation。

### P1-6.28 更新阶段报告

- 目标：记录 P1-6 可信范围、source gap、验证和剩余差距。
- 要做：新增 `live_validation_reports/v8_p1_6_target_system_checkpoint.md`；更新 checklist；说明 target expression coverage、source/convention 边界、random 与 P1-7 边界。
- 验收结果：报告能回答当前做到哪里、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些目标模块。
- 禁止：不能只写“验证通过”。

## 6. 新增验证矩阵

建议新增：

```text
python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_target_system
```

该验证至少包含：

- target current scope matrix。
- TargetSort source matrix。
- TargetFetch source matrix。
- target resolution record completeness。
- HP / HP ratio sort positive 或 source gap。
- toughness sort positive 或 blocked/source gap。
- position sort positive 或 blocked/source gap。
- fetch caster。
- fetch owner。
- fetch partner 或 source gap。
- unique entity success / missing / ambiguous。
- adjacent target success / missing position blocked。
- random target deterministic choice / missing choice blocked。
- random target RNGEvent 或 P1-7 dependency record。
- summon target success / missing summon runtime blocked。
- servant target success 或 source gap。
- dynamic max number positive / missing binding blocked。
- dead/alive filter。
- missing sort blocked。
- missing payload blocked。
- blocked/audit-only/discovered-only target expression 不产生 mutation。
- mutation -> settlement/source trace -> TargetExpressionIR -> TBGD source audit。

主验证 selection policy 必须写入输出：

```json
{
  "mode": "structured_predicate",
  "fixed_entity_skill_file_or_observation_used": false,
  "predicates": [
    "TargetExpressionIR.expression_kind",
    "TargetExpressionIR.alias",
    "TargetExpressionIR.coverage_status",
    "TargetExpressionIR.admission_batch",
    "EffectIR opcode AddModifier for mutation integration samples",
    "source_path family only for source-mode filtering, not fixed file"
  ]
}
```

## 7. 分层验证范围

后续执行 P1-6 时不要默认全量验证。按改动范围选择：

### 7.1 必跑最小集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_target_system
git diff --check
```

目的：

- 编译检查。
- P1-6 主功能和 source-gap 验证。
- 静态空白/patch 检查。

### 7.2 直接回归集

只要改到 `systems/target.py`、target lowering、AddModifier target expression 或 event payload 传递，必须跑：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_288 --output-dir /tmp/hsr_v8_target_expression_v0_288_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_target_expression_v0_289_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p1_6
```

目的：

- v0_288/v0_289 防止目标表达式既有安全子集回退。
- P1-4 防止状态施加目标表达式和 DoT/status callback 目标上下文回退。

### 7.3 条件触发集

按改动触发：

- 改 `QueueTargetResolver` 或 queue target context：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_241 --output-dir /tmp/hsr_v8_queue_v0_241_after_p1_6
```

- 改 summon runtime target：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_after_p1_6
```

- 改 RNG event / random target ledger：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_bounce_rng_v0_264_after_p1_6
```

- 改 snapshot/replay/source audit/shared reducer：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_mutation_events_v0_286_after_p1_6
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_status_target_audit_v0_287_after_p1_6
```

### 7.4 全量验证集

只有以下情况才跑全量：

- P1-6 阶段验收。
- 结构性大改影响 target、status、queue、RNG、snapshot/replay 多个共享底座。
- 提交前高风险检查。
- 用户明确要求。

全量时可以在报告中列出 P1-0 到 P1-6 主验证和关键 v0 回归，但不要在普通执行小项中无脑全量跑。

## 8. 完成口径

P1-6 的完成口径拆成两层。

### 8.1 目标系统底座验收，带来源缺口

满足以下条件时，可以给出 `P1-6-SUBSTRATE-ACCEPTED`：

- 当前 RuleBook / Canonical IR 有真实来源的 sort/fetch/adjacent/random/unique/summon target，都有 positive executable validation。
- 当前无真实来源的项有结构化 source-gap/blocked 证据，并证明不会产生 synthetic mutation。
- target resolution record 完整，成功和失败都可审计。
- 缺排序规则、缺 payload、缺 RNG choice、unique not found、target removed/defeated 均 blocked/state unchanged。
- random target 不依赖进程随机。
- P1-4 状态目标表达式、P1-5 queue target context 没有回退。
- 阶段报告说明当前可信范围、source gap、P1-7 RNG 依赖和后续缺口。

### 8.2 P1-6-DONE 全正例完成

```text
P1-6-DONE sort/fetch/adjacent/random/unique/summon target 的第一阶段关键子集可用，目标失败不产生 mutation。
```

如果 `P1-6-DONE` 被定义为“所有列出的 sort/fetch/adjacent/random/unique/summon/servant 关键子集都有真实来源正例”，则必须等真实来源、runtime context、RNG/choice ledger 都具备后才能勾选。当前计划更现实的阶段目标是先达到 `P1-6-SUBSTRATE-ACCEPTED`。

## 9. 后续影响

P1-6 完成后，后续阶段可以复用：

- P1-7 RNG：random target 已有候选池/choice/RNG event 入口。
- P1-8 setup：可配置 event payload、target context、summon runtime、deterministic choices。
- 角色/怪物卡扩面：sort/fetch/adjacent/unique 不再写 core 特判。
- 光锥/遗器/关卡机制：目标表达式统一走 Canonical IR -> TargetSystem。

P1-6 做完后仍不会得到完整目标系统。完整复刻仍需要更多特殊玩法 target、servant runtime、unique entity registry、完整随机分支枚举和更多角色/怪物数据卡验证。
