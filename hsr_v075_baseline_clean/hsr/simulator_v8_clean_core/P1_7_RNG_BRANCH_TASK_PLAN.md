# P1-7 RNG 与分支基础总体性执行计划

本文档是 `FIRST_PHASE_TASK_CHECKLIST.md` 中 `P1-7 RNG 与分支基础` 的实现级拆解。目标是让一个没有前序对话上下文的新实现线程，可以只依赖本文件、项目入口文档和当前代码完成 P1-7 的实现、验证和阶段报告。

P1-7 的一句话目标：

```text
把当前散落在 crit、bounce、target random、status chance、resist、random dispel 等路径里的随机和概率决策，收束成统一、可审计、可 replay、可由外部推演器枚举分支的 RNG ledger 基础。
```

P1-7 不是“做一个随机 AI”或“把所有概率自动抽完”。本项目最终目标是战斗推演，随机分支本质上是路线输入的一部分。内核应该：

- 发现当前动作会遇到哪些随机或概率决策。
- 告诉外部推演器合法 outcome、权重或概率。
- 在给定 explicit choice ledger 或明确 deterministic seed mode 时执行决策。
- 记录完整 `RNGEvent`，保证 replay 和 source audit。
- 缺少必要 choice 时 blocked/state unchanged，而不是偷偷替用户随机。

## 0. 给新实现线程的背景

### 0.1 项目背景

本项目正在构建《崩坏：星穹铁道》战斗模拟器 v8 clean core。最终使用方式不是让 core 自己做敌方 AI 或随机策略，而是：

```text
外部推演器枚举动作和随机分支
-> core 校验输入是否合法
-> core 执行规则并输出完整 BattleTransition
-> 外部推演器搜索达成目标的通关路线
```

因此 RNG 在 v8 中的职责不是“掷骰子决定命运”，而是“把随机分支变成可审计输入和可 replay 事件”。

v8 的事实来源固定为：

```text
turnbasedgamedata-main
-> TBGD compiler/lowering
-> Canonical IR / 数据卡 IR
-> Combat Core
```

runtime 只能读取 Canonical IR / 数据卡 IR 或 scenario/setup 层已经构造好的 runtime setup。runtime 不能直接读取 raw TBGD、TextMap、旧 v7、旧 model pack，也不能用观测答案或手工结果作为规则输入。

### 0.2 P1-7 的全局位置

第一阶段目标是“外部推演器驱动下的最小完整战斗闭环”。

前置阶段状态：

- P1-0 Action Boundary：core 暴露行动候选和 transition，不做 AI。
- P1-1 UnitLifecycle：`active / defeated / removed` 已进入 target、damage、timeline、queue。
- P1-2 WaveSystem：多波和 UnitSpawn/UnitRemove 已有通用 mutation。
- P1-3 Summon / Assistant / Servant：召唤物、assistant、servant 有最小分类和 runtime schema。
- P1-4 StatusSystem：状态生命周期、chance、resist、random dispel 已有部分路径和 source gap 记录。
- P1-5 Queue/Window：queue/window 传递 mutation、event、rng_events 的基础已存在。
- P1-6 TargetSystem：target random 已建立 explicit choice 和 `RNGEvent(rng_type="target_random")` 的第一版契约。

P1-7 承接 P1-6，把“目标随机”扩展成统一 RNG/branch 基础，支撑后续：

- P1-8 BattleSetup：scenario 可以配置 RNG ledger、seed mode、branch policy。
- 状态系统扩面：命中、抵抗、免疫、控制抵抗、随机驱散都能统一记录。
- 伤害扩面：暴击、随机 hit target、随机附加效果都能被推演器枚举。
- 未来搜索器：可以读取 `available_rng_outcomes` 或等价结构，生成下一批分支动作。

### 0.3 星铁 RNG 和概率相关概念

星铁战斗里影响状态变化的 RNG 至少包括：

1. **暴击**
   - 根据暴击率决定 crit / noncrit。
   - 当前 v8 `damage_formula.py` 已有 `rng_type="crit"` 事件和 `crit_mode` 强制模式。

2. **弹射随机目标**
   - Bounce hit 会从候选池选目标。
   - 当前 `TargetSystem.resolve_bounce_hit_target` 用 deterministic roll 生成 `rng_type="bounce_target"`。

3. **目标表达式随机**
   - `Retarget(ByRandom=True)`、`TargetShuffle` 等。
   - P1-6 已要求 `event_payload["target_random_choices"]` 显式 choice，缺 choice blocked。

4. **状态施加命中**
   - AddModifier 的 `Chance` 加上效果命中和效果抵抗。
   - 当前 `StatusSystem` 已有 `_status_chance_check`，但 helper 仍是 status 内部私有 deterministic roll。

5. **效果抵抗 / 控制抵抗**
   - 普通 debuff 和控制类 debuff 可能走不同抵抗语义。
   - 当前 v8 主要以 `effect_resistance` 和 `control_kind` 元信息表达，还没有统一 RNG branch record。

6. **随机驱散**
   - `DispelStatus(Order=Random)` 需要随机选择可驱散状态。
   - P1-4 已指出当前数据库/IR 中没有可执行真实正例时必须保持 source gap；runtime 不能 synthetic 正例。

7. **后续随机机制**
   - 随机追加攻击、随机召唤、随机 buff/debuff、随机目标 fetch 等。
   - P1-7 不一次性覆盖，但要让接入方式清晰。

### 0.4 当前代码事实

当前主要落点：

```text
core/model.py
core/executor.py
systems/damage_formula.py
systems/target.py
systems/status.py
systems/effect.py
systems/ability.py
systems/event_dispatch.py
systems/status_callbacks.py
systems/scheduler.py
tbgd/lowering.py
tools/validate_v0_209.py
tools/validate_v0_264.py
tools/validate_p1_4_status_system.py
tools/validate_p1_6_target_system.py
```

当前事实：

- `core.model.RNGEvent` 已存在，字段为 `rng_type`、`source`、`result`、`event_id`、`before_state`、`after_state`、`metadata`。
- `BattleTransition` 已有 `rng_events`，executor 会聚合 damage、ability task、listener dispatch、target bounce 等结果里的 rng events。
- `BattleState.rng_state` 是字符串，snapshot contract 中已有 `rng_state` / `rng_events` 字段。
- `damage_formula._resolve_crit` 会创建 `RNGEvent(rng_type="crit")`，支持 `crit_mode=crit/noncrit/deterministic`，但不是统一 choice ledger。
- `TargetSystem.resolve_bounce_hit_target` 会创建 `RNGEvent(rng_type="bounce_target")`，使用 deterministic hash roll，不要求 external choice。
- `TargetSystem._select_random_targets` 会创建 `RNGEvent(rng_type="target_random")`，目前依赖 `event_payload["target_random_choices"]`，缺 choice 返回 `requires_rng_choice`。
- `StatusSystem._status_chance_check` 已经会为 `status_apply` 和 `status_resist` 创建 RNG event，但 helper 是 status 私有，使用 deterministic hash roll，不产出统一 `available_rng_outcomes`。
- `StatusSystem.apply_dispel_status` 有 `Order=Random` 分支和 `status_dispel` RNG event helper，但 P1-4 验证记录过当前缺真实 random dispel source 时只能 source gap。
- `tbgd/lowering.py` 会把 AddModifier `Chance` 解析成 numeric summary；DispelStatus 会解析 `Order` 和 `Numbers`。
- 当前没有中央 RNG/branch resolver；不同系统分别决定 event id、roll、choice、result shape、after_state。
- 当前没有统一的 missing choice blocked contract。P1-6 target random 有，crit/bounce/status chance/resist 暂无。
- 当前没有统一 `available_rng_outcomes` / probability weight record；外部推演器还不能直接从 transition 或 blocked result 读取分支集合。

当前最重要的风险：

```text
如果 P1-7 继续让各系统自己 hash roll，外部推演器无法可靠枚举分支。
如果 P1-7 强行把所有随机都改成必须 choice，又可能一次性打断大量旧验证。
所以本阶段需要明确两种模式：explicit ledger mode 和 deterministic seed mode，并把二者都记录进同一 RNGEvent schema。
```

### 0.5 三态验收口径

P1-7 每个随机机制必须先按三态判断：

- `executable`：当前 RuleBook / Canonical IR 中存在真实来源，runtime 能生成统一 RNG request、resolution、RNGEvent、settlement/source trace，replay 通过。
- `source_gap_blocked`：runtime 可以有 guarded path、blocked path 或未来预留字段，但当前 TBGD / IR 结构化扫描没有真实可执行来源；只能验证 coverage gap、blocked、state unchanged，不能合成正例 mutation。
- `implementation_missing`：当前存在真实来源，但 runtime 没有正确 admission / RNG event / settlement / replay，这才是需要编码修复的缺口。

高风险项：

- `random dispel`：如果当前 RuleBook 无 `Order=Random` 真实来源，只能 source gap，不能 synthetic 正例 mutation。
- `control resist`：如果当前控制类型和抵抗公式来源不完整，只能先把普通 resist 和 control resist 分层记录，不能硬编码特殊状态。
- `status chance`：有真实 AddModifier chance 来源时可以做 positive；缺 source 或公式不支持时 blocked。
- `crit`：已经有 runtime 正例，但要迁入统一 event schema 时不能破坏 v0_209 数值验证。
- `bounce`：已经有 deterministic RNG；P1-7 要补 explicit choice / available outcomes，但不能丢失 P1-6 的 bounce source trace。

## 1. 非目标

P1-7 不做以下内容：

- 不做敌方 AI、自动路线选择或 Monte Carlo 策略。
- 不做完整概率搜索器，只预留 branch enumeration 输入输出。
- 不把所有随机路径强行改成“自动掷骰”；显式分支输入优先。
- 不用 Python `random`、进程时间、全局 hash salt 或不可 replay 的随机源。
- 不用观测战斗结果倒推出 RNG outcome。
- 不为当前数据库没有真实来源的 random dispel/control resist 等机制构造 synthetic 正例 mutation。
- 不一次性补完整命中/抵抗官方公式之外的所有特殊角色机制。
- 不把 `crit_mode`、`target_random_choices` 等旧验证字段无限扩散成新主接口；P1-7 应定义统一主接口，并规划迁移。
- 不让 failed chance / resisted / missing choice 产生状态 mutation。
- 不把 probability weight 当作执行结果；权重只是分支元数据，实际 outcome 必须来自 choice 或 deterministic seed mode。

## 2. 总体实现原则

### 2.1 RNG 决策是 transition 输入，不是内核策略

同一个 action 在同一个 before snapshot 下，遇到随机分支时应该有两种合法执行模式：

1. `explicit_ledger`：
   - command/scenario/event payload 提供具体 choice。
   - core 校验 choice 是否在 available outcomes 中。
   - choice 缺失或非法时 blocked/state unchanged。
   - 这是外部推演器主路径。

2. `deterministic_seed`：
   - 明确声明用 seed/draw 规则执行。
   - core 使用稳定 event id 和 rng_state 生成 deterministic result。
   - RNGEvent 必须记录 roll、threshold、candidate pool、selected outcome。
   - 这是 smoke、回归、对照和单路径模拟可用模式。

默认不能落到进程随机。

### 2.2 统一 RNGEvent schema

P1-7 不一定要立刻改 `core.model.RNGEvent` dataclass 字段，但 `RNGEvent.result` / `metadata` 的内容必须统一。建议所有新路径至少记录：

- `decision_kind`：`probability` / `choice` / `forced`。
- `purpose`：例如 `crit`、`status_apply`、`status_resist`、`target_random`、`bounce_target`。
- `choice_key`：外部 ledger 用来指定 outcome 的 key。
- `choice_source`：`explicit_ledger` / `deterministic_seed` / `forced_command`。
- `outcomes`：候选 outcome id、payload、weight/probability。
- `selected_outcome_id`。
- `selected_value` 或 `selected_payload`。
- `probability` / `threshold` / `roll`，仅 probability/deterministic seed 需要。
- `candidate_pool`，目标或状态候选必须有。
- `source_trace`，能反查 IR / effect / action / target expression。
- `before_state` / `after_state`，同一规则下可 replay。

已有 `RNGEvent` 可以保留，新增 helper 负责规范 result/metadata。

### 2.3 Central helper 优先

建议新增轻量模块：

```text
systems/rng.py
```

候选结构：

```text
RNGOutcome
RNGRequest
RNGResolution
RNGLedger
resolve_rng_request(...)
```

不要一开始做复杂引擎。P1-7 只需要支撑：

- 二选一概率：success / fail。
- 抵抗概率：resisted / not_resisted。
- 目标/状态候选选择：select one from candidates。
- forced outcome：crit_mode 或验证强制分支。
- missing choice blocked：返回 available outcomes。

### 2.4 Admission 先于 runtime choice

RNG path 必须先确认来源：

```text
raw TBGD
-> Canonical IR standard payload / normalized payload
-> coverage/admission
-> RNGRequest
-> RNGResolution / blocked
-> RNGEvent / process-only settlement
```

缺来源时，runtime 不能只是因为有 helper 就执行。

### 2.5 Settlement 必须区分 process-only 和 mutation

随机分支可能导致：

- 命中成功：继续生成状态 mutation。
- 命中失败：生成 process-only settlement，无状态 mutation。
- 被抵抗：生成 process-only settlement，无状态 mutation。
- 缺 choice：blocked/process-only，无状态 mutation。
- random target 缺 choice：blocked，无 action mutation。
- random dispel 无 source：source gap，不产生 mutation。

验证不能只看 `ok=True/False`，必须检查 mutation、settlement、rng_events、source_trace。

### 2.6 分支枚举先做数据契约

P1-7 不要求完成搜索器，但要输出足够数据让搜索器能做：

```text
event_id / choice_key
available outcomes
probability or weight
source trace
blocked reason if missing choice
```

建议在 blocked result、RNGEvent metadata 或 transition coverage 中统一放 `available_rng_outcomes`。

## 3. 建议代码落点

实际实现 agent 应先阅读当前代码再动手。优先落点：

- `core/model.py`
  - `RNGEvent` 是否需要新增 helper/to_json 约定。
  - 不建议随意改 dataclass 字段，优先规范 result/metadata。

- `systems/rng.py`
  - 新增统一 RNG request/resolution helper。
  - 负责 explicit ledger、deterministic seed、forced outcome、available outcomes。

- `core/executor.py`
  - 将 command metadata 中的 RNG ledger 传给 target/damage/status/effect 相关调用。
  - 聚合 `rng_events` 和 branch coverage。

- `systems/damage_formula.py`
  - 迁移 crit 到统一 helper。
  - 保留 `crit_mode` 正例或把它映射成 forced RNG choice。

- `systems/target.py`
  - 迁移 target random 和 bounce target 到统一 helper。
  - 保留 P1-6 的 missing choice blocked 和 candidate pool record。

- `systems/status.py`
  - 迁移 status apply chance、status resist、random dispel choice 到统一 helper。
  - 明确 control resist 是 executable 还是 source gap。

- `systems/effect.py`、`systems/ability.py`、`systems/event_dispatch.py`、`systems/status_callbacks.py`
  - 只负责透传 rng context 和 rng_events，不自己创建不统一的随机事件。

- `tbgd/lowering.py`
  - 扫描 chance、resist、random dispel、target random、bounce policy 的 source/admission。
  - 不为了 runtime 方便伪造来源。

- `tools/`
  - 新增 `validate_p1_7_rng_branch_system.py`。
  - 扩展旧验证只作为直接回归。

- `live_validation_reports/`
  - 新增 P1-7 阶段报告。

## 4. 内部闸门

P1-7 应按内部闸门推进：

```text
Gate A: 当前 RNG surface/source matrix 审计
Gate B: 统一 RNG request/event/outcome schema
Gate C: explicit choice ledger 和 deterministic seed mode
Gate D: crit 迁移与 forced outcome 映射
Gate E: target random 和 bounce target 迁移
Gate F: status chance / effect resist 迁移
Gate G: control resist 分层或 source-gap blocked
Gate H: random dispel 分层或 source-gap blocked
Gate I: available_rng_outcomes / probability weight record
Gate J: negative validation / replay / source audit / report
```

每个闸门都必须按三态验收；没有真实来源时只能 `source_gap_blocked`。

## 5. 详细任务清单

### P1-7.1 审查当前 RNG surface

- 目标：列出当前所有会产生或应该产生 RNGEvent 的 runtime 路径。
- 要做：审查 `RNGEvent`、`BattleTransition.rng_events`、executor 聚合、damage crit、bounce、target random、status chance/resist、random dispel、ability/effect/status callback rng 透传。
- 验收结果：阶段报告有 `rng_surface_matrix`，每个路径标记 `executable / source_gap_blocked / implementation_missing`。
- 禁止：不能只看 `rg RNGEvent`；还要检查有概率但当前不产 RNGEvent 的路径。

### P1-7.2 审查 RNG source/admission

- 目标：确认哪些概率/随机来源来自真实 TBGD/IR。
- 要做：扫描 AddModifier `Chance`、DispelStatus `Order=Random`、Retarget `ByRandom`、TargetShuffle、BouncePolicyIR、crit resource/command metadata。
- 验收结果：报告中区分真实来源、engine convention、validation forced choice、source gap。
- 禁止：不能把 validation synthetic effect 当 positive source。

### P1-7.3 定义统一 RNG request schema

- 目标：让各系统用同一种结构描述“需要一个随机决策”。
- 要做：设计轻量 `RNGRequest` 或 dict helper，至少包含 event id components、rng_type、purpose、decision_kind、outcomes、probability/weights、source_trace、choice_required。
- 验收结果：crit、target_random、bounce、status chance/resist 都能表达成同一 request 形状。
- 禁止：不能把 event id 拼接规则继续散落在各系统。

### P1-7.4 定义统一 RNGEvent result schema

- 目标：让 transition 里的 rng events 形状一致、可 replay、可审计。
- 要做：新增 helper 生成 `RNGEvent`，规范 result/metadata 字段。
- 验收结果：新增/迁移路径的 RNGEvent 都有 choice_key、choice_source、outcomes、selected_outcome_id、source_trace。
- 禁止：不能只把旧 event 原样包一层。

### P1-7.5 定义 explicit choice ledger 输入

- 目标：让外部推演器可以指定每个 RNG decision 的 outcome。
- 要做：定义 command/scenario/event payload 中统一字段，例如 `rng_choices`；支持按 choice_key/event_id 指定 outcome_id 或 selected index。
- 验收结果：同一 before snapshot + action + rng_choices 可稳定复现同一 after snapshot。
- 禁止：不能继续为每类机制发明互不兼容的字段。

### P1-7.6 定义 deterministic seed mode

- 目标：保留可重复单路径执行，但必须显式声明且完全记录。
- 要做：定义 `rng_mode="deterministic_seed"` 或等价入口；使用 stable event id + rng_state 产生 roll；记录 roll 和 outcome。
- 验收结果：同一 seed 同一 request 得到同一 event；不同 choice/seed 可产生不同合法 outcome。
- 禁止：不能默认用进程随机或未声明 deterministic 模式。

### P1-7.7 实现 available outcomes 记录

- 目标：让缺 choice 时外部推演器知道可以选什么。
- 要做：在 `RNGResolution`、blocked settlement、transition coverage 或 result metadata 中记录 `available_rng_outcomes`。
- 验收结果：target random、status apply chance、status resist、crit、bounce 都能输出合法 outcomes。
- 禁止：不能只返回 `requires_rng_choice` 字符串而没有候选细节。

### P1-7.8 增加统一 RNG resolver helper

- 目标：集中处理 explicit choice、forced outcome、deterministic roll、blocked。
- 要做：新增 `systems/rng.py`，实现 probability 和 choice 两类 request。
- 验收结果：helper 有独立验证，非法 choice、缺 choice、空候选、权重非法都 blocked。
- 禁止：不能引入新依赖。

### P1-7.9 迁移 crit RNG

- 目标：让暴击进入统一 RNG ledger，同时保持 v0_209 数值回归。
- 要做：把 `crit_mode=crit/noncrit` 映射为 forced outcome；deterministic crit 走统一 helper；记录 crit_rate、crit_damage、outcomes。
- 验收结果：forced crit/noncrit 和 deterministic crit 都有统一 RNGEvent；v0_209 通过。
- 禁止：不能破坏 direct damage formula settlement/source trace。

### P1-7.10 迁移 target random

- 目标：把 P1-6 target random 从 `target_random_choices` 迁到统一 ledger。
- 要做：支持统一 `rng_choices`；可短期兼容 P1-6 字段但主记录必须写 unified choice_source。
- 验收结果：缺 choice blocked，有 choice replay 稳定，invalid choice blocked，available outcomes 完整。
- 禁止：不能把缺 choice 改成 deterministic 默认执行。

### P1-7.11 迁移 bounce target RNG

- 目标：让弹射随机目标也可被外部推演器枚举。
- 要做：把 candidate pool、live/unhit priority、all defeated continuation 形成 choice outcomes；支持 explicit choice 和 deterministic seed mode。
- 验收结果：v0_264 通过；显式 choice 可以指定合法 bounce target；非法 target blocked。
- 禁止：不能丢失 previous_hit_targets、candidate_pool_reason、bounce_policy source trace。

### P1-7.12 迁移 status apply chance

- 目标：让状态施加命中/失败成为统一 probability decision。
- 要做：把 `base_success_probability` 形成 success/fail outcomes；有真实 AddModifier chance 来源时 positive；缺公式 blocked。
- 验收结果：成功分支产生 status mutation；失败分支 process-only，无 mutation；两者都有 settlement 和 RNGEvent。
- 禁止：不能用 synthetic chance 正例替代真实 AddModifier chance 来源。

### P1-7.13 迁移 effect resist

- 目标：让效果抵抗成为统一 probability decision。
- 要做：把 `resist_probability` 形成 resisted/not_resisted outcomes；命中成功后再判抵抗；记录顺序。
- 验收结果：resisted 分支 process-only，无 status mutation；not_resisted 分支继续生命周期。
- 禁止：不能把免疫当 RNG；免疫应是确定性 process-only。

### P1-7.14 明确 control resist 边界

- 目标：区分普通效果抵抗和控制抵抗。
- 要做：审查 `control_kind`、status metadata、monster/card resistance 字段；若来源/公式不足，标 `source_gap_blocked` 或 `implementation_missing`。
- 验收结果：有真实来源则 executable；无来源则报告 source gap，并验证不会用普通 resist 冒充控制抵抗。
- 禁止：不能按 modifier name 或文本硬判控制。

### P1-7.15 处理 random dispel

- 目标：保持 P1-4 红线，只有真实 `Order=Random` 来源才能 executable。
- 要做：扫描当前 RuleBook 是否存在 source-admitted random dispel；若没有，保留 source gap 和 blocked/no mutation 验证；若有，迁移到 unified choice helper。
- 验收结果：无真实来源时不勾 positive mutation；有真实来源时 RNGEvent + replay + source audit 通过。
- 禁止：不能为了 DONE 合成 random dispel 正例。

### P1-7.16 统一 missing choice blocked

- 目标：所有需要 explicit choice 的路径缺 choice 时都给出相同风格的 blocked result。
- 要做：定义 `requires_rng_choice` payload，包含 choice_key、rng_type、available outcomes、source trace。
- 验收结果：target random、bounce、crit、status chance/resist 均有 missing choice case。
- 禁止：不能缺 choice 时 fallback 到第一个 outcome。

### P1-7.17 统一 probability weight 记录

- 目标：让推演器能读取每个分支概率。
- 要做：probability request 记录 `success_probability`、`failure_probability`；choice request 记录候选权重，未知权重标 unknown。
- 验收结果：验证输出 probability matrix；权重缺失不阻止选择，但必须诚实记录 unknown。
- 禁止：不能把 unknown weight 写成 1.0。

### P1-7.18 统一 replay contract

- 目标：证明 RNG ledger 可 replay。
- 要做：同一 before snapshot + action + rng_choices 重跑两次，比较 after snapshot、mutations、rng_events；deterministic seed mode 也做稳定性验证。
- 验收结果：replay 校验通过；非法 ledger blocked。
- 禁止：不能只比较 selected outcome，不比较 after snapshot。

### P1-7.19 增加 no process random 静态检查

- 目标：防止 runtime 引入不可 replay 随机。
- 要做：扩展 static checks，禁止 core runtime 使用 `random.random`、`secrets`、时间戳随机等。
- 验收结果：P1-7 验证报告 static check 通过。
- 禁止：不要扫描整个仓库误伤工具脚本，范围限定 v8 runtime。

### P1-7.20 透传 rng context

- 目标：让 ability/effect/status callback/target/damage 都能读取同一个 ledger。
- 要做：从 `ActionCommand.metadata` 或 executor context 传递到 `event_payload` / effect context；避免每层自己发明字段。
- 验收结果：嵌套 ability task、status callback 产生的 RNGEvent 能命中 ledger。
- 禁止：不能把 command metadata 直接当规则来源；它只是分支输入。

### P1-7.21 settlement 和 source audit

- 目标：RNG 成功、失败、blocked 都能追踪来源。
- 要做：process-only record 引用 RNGEvent/event id；mutation source trace 引用 chance/resist/target expression/crit source。
- 验收结果：RuntimeSourceAuditor 对 RNG mutation 样例通过；失败分支无 mutation 但有 settlement record。
- 禁止：不能从日志事后反推 settlement。

### P1-7.22 新增主验证脚本

- 目标：形成 P1-7 的可重复验收入口。
- 要做：新增 `tools/validate_p1_7_rng_branch_system.py`。
- 验收结果：输出 matrix、positive cases、negative cases、replay、source audit、static checks。
- 禁止：不能只跑旧 v0_209/v0_264/P1-4/P1-6。

### P1-7.23 增加 crit 验证

- 目标：证明 crit 强制分支和 deterministic seed 都在统一 schema 下工作。
- 要做：用真实 direct damage source，构造 crit/noncrit/auto 或 ledger choice。
- 验收结果：crit/noncrit final damage 不同，RNGEvent schema 完整，v0_209 回归通过。
- 禁止：不能用观测伤害当输入。

### P1-7.24 增加 target random 验证

- 目标：证明 P1-6 target random 迁移后仍安全。
- 要做：有真实 random target source 时跑 explicit choice、missing choice、invalid choice、available outcomes。
- 验收结果：`validate_p1_6_target_system` 仍通过。
- 禁止：不能让 P1-6 的 `requires_rng_choice` 退化。

### P1-7.25 增加 bounce 验证

- 目标：证明 bounce target 可 replay 且可显式选择。
- 要做：复用 v0_264 多敌人样例，增加 explicit choice / invalid choice / deterministic seed。
- 验收结果：bounce RNGEvent schema 完整，candidate pool 和 previous hits 记录完整。
- 禁止：不能按固定怪物 ID 选主样例；选择仍按结构化 bounce policy。

### P1-7.26 增加 status chance/resist 验证

- 目标：证明状态命中成功、失败、抵抗三类 outcome。
- 要做：结构化选择真实 AddModifier chance source；若缺 source，记录 source gap；有 source 时构造 ledger outcomes。
- 验收结果：成功有 mutation；失败/抵抗 process-only；source audit/replay 通过。
- 禁止：不能用 synthetic AddModifier 做 positive mutation。

### P1-7.27 增加 random dispel 验证

- 目标：证明 random dispel 不再处于“看起来支持但来源不明”的状态。
- 要做：若有真实 `Order=Random`，跑正例；若没有，验证 source gap、blocked/no mutation。
- 验收结果：P1-4 中 random dispel 的 source gap 口径保持诚实。
- 禁止：不能为 checklist 勾选造 fake random dispel。

### P1-7.28 更新阶段报告

- 目标：记录 P1-7 可信范围、source gap、验证和后续分支枚举差距。
- 要做：新增 `live_validation_reports/v8_p1_7_rng_branch_checkpoint.md`；更新 checklist。
- 验收结果：报告能回答当前做到哪里、距离最小可用战斗纵切还缺什么、距离完整复刻还缺哪些 RNG/branch 模块。
- 禁止：不能只写“验证通过”。

## 6. 新增验证矩阵

建议新增：

```text
tools/validate_p1_7_rng_branch_system.py
```

输出文件建议：

```text
validation_summary_p1_7_rng_branch_system.json
rng_surface_matrix_p1_7.json
rng_schema_cases_p1_7.json
rng_choice_ledger_cases_p1_7.json
rng_crit_cases_p1_7.json
rng_target_random_cases_p1_7.json
rng_bounce_cases_p1_7.json
rng_status_chance_cases_p1_7.json
rng_status_resist_cases_p1_7.json
rng_random_dispel_cases_p1_7.json
rng_replay_cases_p1_7.json
rng_source_audit_p1_7.json
```

资源预算要求：

- 默认只写 summary、matrix、抽样正例/负例、replay/source audit 必要片段。
- 禁止默认写完整 `CanonicalIR.to_json()`、完整 coverage/fidelity、完整 RuleBook 派生大对象或全量 transition dump。
- 如果执行线程确实需要归档大产物，必须增加显式开关，例如 `--write-large-artifacts`，默认关闭，并在报告里说明为什么需要。
- 主验证应按结构化谓词选择少量真实来源样例，例如 opcode、coverage_status、rng_type、choice_required、source_mode；不要为了覆盖率把全数据库序列化到输出目录。
- P1-7 主验证不得成为类似 `validate_v0_209` 的全量 canonical/coverage/fidelity 写盘脚本。

核心断言：

- 所有新增 RNGEvent 都符合统一 schema。
- missing choice blocked 且包含 available outcomes。
- invalid choice blocked。
- explicit choice replay 稳定。
- deterministic seed replay 稳定。
- failed chance / resisted / missing choice 不产生 mutation。
- success chance 产生 mutation 且 source audit 通过。
- random dispel 没有真实来源时只记录 source gap。
- runtime 不使用进程随机。

## 7. 分层验证范围

### 7.1 必跑最小集

在 `hsr_v075_baseline_clean/hsr` 下运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
```

目的：确认新增 RNG helper、迁移后的 target/status/damage/executor 代码语法正确。

触发条件：每次 P1-7 实现或验收必跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_7_rng_branch_system --output-dir /tmp/hsr_v8_p1_7_rng_branch_system
```

目的：P1-7 主验证，覆盖统一 RNG schema、choice ledger、replay、source gap、negative cases。

触发条件：每次 P1-7 实现或验收必跑。

```bash
git diff --check
```

目的：检查 whitespace 和 patch 卫生。

触发条件：每次 P1-7 实现或验收必跑。

### 7.2 直接回归集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_264 --output-dir /tmp/hsr_v8_v0_264_after_p1_7
```

目的：bounce target RNG 回归。

触发条件：改 bounce target、target RNG helper、candidate pool 时跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_after_p1_7
```

目的：target random、missing choice、target resolution 回归。

触发条件：改 `TargetSystem`、target random ledger、target RNGEvent 时跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_4_status_system --output-dir /tmp/hsr_v8_p1_4_after_p1_7
```

目的：status chance、resist、random dispel、status lifecycle 回归。

触发条件：改 `StatusSystem` chance/resist/dispel/lifecycle record 时跑。

### 7.3 条件触发集

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_v0_209_after_p1_7
```

目的：crit/direct damage formula 和 RNGEvent 高风险回归。

触发条件：只有改到 `damage_formula.py`、direct damage formula、crit mode、`RNGEvent` 公共 schema，且 P1-7 主验证的 focused crit case 不能覆盖风险时才跑。该脚本会全量 discovery/lowering 并写出完整 `canonical_ir_v0_209.json`、coverage、fidelity，磁盘 IO 和内存压力大，必须串行运行，禁止和其他 RuleBook 重验证并行。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_286 --output-dir /tmp/hsr_v8_v0_286_after_p1_7
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_287 --output-dir /tmp/hsr_v8_v0_287_after_p1_7
```

目的：mutation-backed event、source audit、status target audit 回归。

触发条件：改 settlement、source audit、mutation metadata、status target trace 时跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_289 --output-dir /tmp/hsr_v8_v0_289_after_p1_7
```

目的：target expression sequence/filter/retarget 回归。

触发条件：改 target expression lowering/runtime payload 时跑。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_5_queue_window_system --output-dir /tmp/hsr_v8_p1_5_after_p1_7
```

目的：queue/window 中 rng_events 透传回归。

触发条件：改 scheduler、queue、window、executor command metadata 传递时跑。

### 7.4 全量验证集

全量只在以下情况运行：

- P1-7 阶段最终验收。
- 改了 `core/model.py` 的公共 dataclass 字段。
- 改了 executor 的 transition 构建。
- 改了 reducer/snapshot/replay/source audit 共享底座。
- 用户明确要求全量。

不应在每个小修补中无脑全量跑。

## 8. 完成口径

P1-7 的完成口径拆成两层。

### 8.1 RNG 分支底座验收，带来源缺口

满足以下条件时，可以给出 `P1-7-SUBSTRATE-ACCEPTED`：

- 当前已存在真实来源的 RNG 路径进入统一 RNG request/event schema。
- 当前无真实来源的 random dispel/control resist 等路径记录为 source gap，且 no synthetic mutation。
- explicit choice ledger 可驱动至少 crit、target random、bounce、status chance/resist 的第一阶段关键子集。
- deterministic seed mode 仍可 replay，并且 event 明确记录 choice_source。
- missing choice blocked 且包含 available outcomes。
- failed chance / resisted / missing choice 都是 process-only，无状态 mutation。
- source audit 和 replay 对至少一个 mutation 正例通过。
- 阶段报告说明当前可信范围、source gap、后续 branch enumerator 差距。

### 8.2 P1-7-DONE 第一阶段随机路径完成

```text
P1-7-DONE 第一阶段所有已有随机和概率路径都进入统一 RNG event，replay 不依赖进程随机状态。
```

如果某条机制当前数据库没有真实来源，只能标 source gap，不阻塞底座验收；但不能把它当正例完成。

## 9. 后续影响

P1-7 完成后，后续阶段可以复用：

- P1-8 BattleSetup：统一配置 `rng_choices`、seed mode、branch policy。
- 推演器：读取 available outcomes 并扩展搜索树。
- 状态扩面：命中、抵抗、控制抵抗、随机驱散共用同一分支接口。
- 目标扩面：random fetch、random target、bounce target 共用同一分支接口。
- 伤害扩面：crit、随机附加伤害、随机多段等共用同一分支接口。

P1-7 做完后仍不会得到完整概率搜索器。完整复刻仍需要更多角色/怪物机制、完整控制/抵抗公式、完整随机玩法目标、以及外部 branch enumerator。
