# P9-A2 Action-window status callback → nested formal ability transport

## 0. 执行身份

- dispatch id: `P9-A2-PLAN-INIT-20260907`
- risk mode: `STRICT`
- approved route: `A1 -> A2 -> resume PR9`
- exact merged base: `master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`
- hard prerequisite: PR #10 / A1 已 squash merge；不得读取或复用未合并 PR #9 的业务代码。
- this PR outcome: 只闭合 action-window 正式状态回调到 nested-only formal ability 的 runtime capability transport / routing。A2 合并前 PR #9 继续暂停。

本卡是本 PR 唯一任务权威。执行层不得按 PR #9 的旧实现、旧 validator 或未合并 diff 推断 A2 业务实现。

## 1. 已核实的 merged-master 事实

### 1.1 当前真实生产调用链

当前 `CombatExecutor.execute(ActionCommand)` 的 `trigger_window` 路径为：

```text
CombatExecutor.execute(ActionCommand)
  -> AbilityTaskSystem.execute_callback(... callback_kind=<window callback>)
       -> TaskGraphExecutor.execute(formal action graph)
  -> EventDispatchSystem.dispatch_action_window(...)
  -> EventDispatchSystem.dispatch_event(event=action-window event)
       -> matched status listener
       -> StatusCallbackSystem.execute(...)
       -> StatusCallbackSystem._execute_formal_callback(...)
       -> TaskGraphExecutor.execute(formal status_callback graph)
       -> Status TriggerAbility graph edge
       -> nested-only ability_phase_callback graph
```

A1 已只负责正式 action graph 的 admission authority；本卡不得修改 A1 authority，也不得重新打开 legacy whole-action pre-screen。

### 1.2 已存在且必须保留的 S8B5 契约

1. `TaskGraphContinuation` 的唯一合法铸造入口仍是 `TaskGraphContinuation.from_hook_request(TaskGraphHookRequest)`。
2. continuation 不得从 `GameEvent.payload`、`source_trace`、日志、action metadata、graph projection 或任意“最后一个 leaf”重建。
3. 已存在的真实 `ability leaf -> event -> status callback` child-entry 路径继续使用现有 continuation + nested hooks 成对运输；不得为 A2 全局放宽 `hooks_without_continuation`。
4. `StatusCallbackSystem._execute_formal_callback` 已能在没有 parent continuation 时为一个合法外部/窗口 listener 建立自己的 formal status root `TaskGraphExecutionContext`；这不等于允许其任意进入 `nested_only` ability。
5. status `TriggerAbility` 自身会产生真实 `TaskGraphHookRequest`。nested ability 的 graph/phase/task 身份必须绑定这条 request 与已有 typed linked ability reference；不能绑定外层 action ability 身份。
6. `StatusCallbackSystem._formal_status_hooks` 已按 graph `entry_kind` 区分 status graph 与 `ability_phase_callback`，但当前 routed hook set 没有运输 `weighted_selection`。
7. `AbilityTaskSystem._formal_task_graph_hooks` 当前也没有真实 `weighted_selection` RNG caller；该 caller、RNG draw、RNGEvent 与 whole-action ledger 仍归原 PR #9。

### 1.3 当前真实代表链

P9 既有审计已把真实代表定位到角色正式来源中的 action-window 状态链：

```text
MAvatar_Advanced_Silwolf_00_Passive / OnAfterAttack
  -> Retarget
  -> TriggerAbility(...)
  -> Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug
  -> formal nested-only ability graph
  -> RandomConfig / weighted selection boundary
```

`avatar_skill:1100601` 是既有审计中的一个动态代表，不得把该固定 ID 写进生产分支、通用 runtime 或“唯一正确样本”门禁。Direct 必须从 merged-master 的正式目录动态发现当前满足本卡条件的真实候选，并把完整 denominator 与所选代表写入 evidence。

## 2. 唯一目标

闭合以下 A2 runtime 纵切，同时不实现 PR #9 的 RandomConfig caller/RNG：

```text
real CombatExecutor.execute(ActionCommand)
  -> admitted action-window listener
  -> real formal status_callback root
  -> typed status TriggerAbility request
  -> request-bound nested-only ability hooks
  -> nested formal ability graph
  -> all hook channels route by child graph entry_kind
  -> weighted_selection reaches AbilityTaskSystem-owned A2 fail-closed boundary
     (or, if a dynamically discovered current real candidate does not require deferred RNG,
      it may execute through its existing admitted leaf semantics)
```

A2 完成意味着“action-window status -> nested formal ability”的 transport/routing 已完整，不能只修 `dispatch_event` 的第一个 transport gate，也不能只让 catalog resolver 找到 child graph。

## 3. 本卡架构裁决

### 3.1 continuation authority 不变

A2 **不得**新增第二种 `TaskGraphContinuation` 构造方式，也不得修改 `systems/task_graph.py` 来伪造 action-window parent node。

Action-window status callback 不是任意 action leaf 的 child。若执行发现必须从 action callback 完成结果、event payload、projection 或“最后完成节点”合成 continuation 才能工作，立即 `NEEDS_REPLAN`；若确实需要改变 S8B5A 的 continuation provenance/public semantics，则升级 `NEEDS_DECISION`。

### 3.2 action-window 的正式状态图是合法 root，但 nested ability capability 必须类型化准入

当前 `StatusCallbackSystem` 已有无 parent continuation 的 formal status root 语义，本卡复用它；不得把 status root 假装成 action graph child。

但是，action-window 入口要进入 `nested_only` ability，必须新增/复用一个**显式、类型化、request-bound 的 nested ability capability transport**：

- capability 由 `AbilityTaskSystem` 的正式 ability runtime authority 提供；
- `EventDispatchSystem` 只运输/准入，不解析 nested ability 语义；
- `StatusCallbackSystem` 只在已准入的 formal status `TriggerAbility` request 上消费；
- child actor/source identity 来自 typed status instance owner + linked phase/standalone reference + hook request/target scope；不得默认等于外层 `ActionCommand.actor_id`；
- child phase 必须仍为 `nested_only`，不能通过该 capability 成为 root；
- capability 必须按每个 child `TaskGraphHookRequest` 校验 graph/phase/task/owner/target 身份，不能把一个外层 action 的 pre-bound `_FormalAbilityInvocation` 直接复用给不同 nested ability。

实现形式可以是最小的 typed hook provider/factory 或等价不可变 capability；不得用 `Any` payload、全局变量、线程本地栈、闭包中的未验证 action id、source trace 或名称扫描代替身份契约。

### 3.3 现有 continuation 路径不能被 A2 放宽

`ability leaf -> event -> status` 现有 continuation + hooks 成对运输仍必须原样成立。A2 若新增 action-window root transport，必须是显式区分的 formal-root admission，而不是把 `_task_graph_transport_reason` 改成“hooks 可以无条件无 continuation”。

负例必须证明：普通无 admission 的外部 listener 即使拿到 hooks/capability 也不能进入角色 `nested_only` formal ability。

### 3.4 weighted_selection 通道必须完整运输，但 RNG caller 仍 deferred

A2 必须把 `TaskGraphExecutionHooks.weighted_selection` 纳入：

1. status hook router 的完整 channel routing；
2. blocked hook-result helper / type dispatch（若当前 helper 尚不支持）；
3. AbilityTaskSystem 的 A2 边界。

A2 边界只允许提供**显式 fail-closed 的 deferred hook**，用于证明真实 weighted-selection request 已经到达 AbilityTaskSystem authority，例如稳定 reason code：

```text
ability_task_weighted_selection_caller_deferred_to_pr9
```

实际 reason 名可以遵循仓库现有命名，但必须是 AbilityTaskSystem-owned、稳定、可独立断言且与“status router 丢失 channel”可区分的 blocker。

该 A2 hook 必须：

- 不选 branch；
- 不消耗 RNG；
- 不创建 RNGEvent；
- 不产生 mutation/event/settlement；
- 不改变 whole-action RNG ledger；
- 不复制 PR #9 的 weighted choice/weight evaluation/atomic RNG logic。

## 4. 生产权威归属

| 责任 | 唯一权威 | A2 允许做什么 | A2 禁止做什么 |
|---|---|---|---|
| continuation provenance / active stack | `systems/task_graph.py` / `TaskGraphContinuation.from_hook_request` | 只消费既有类型 | 新 factory、payload 重建、改变 cycle semantics |
| action-window orchestration | `core/executor.py` | 只把正式 nested-ability capability 交给现有 action-window listener 调用 | 解析 TriggerAbility、选择 child ability、实现 RNG |
| event/listener transport | `systems/event_dispatch.py` | 运输并 fail-closed 校验 action-window formal-root capability；保留现有 continuation pair | 成为 ability 语义 authority、按名称/ID路由 |
| formal status graph / TriggerAbility resolver | `systems/status_callbacks.py` | 绑定真实 status request；按 entry_kind 路由全部 hooks，含 `weighted_selection` | 伪造 child invocation、自己执行 ability/RNG |
| nested formal ability semantics/hooks | `systems/ability.py` | request-bound child invocation/hook provider；A2 weighted hook 仅显式 deferred blocker | RandomConfig 选择、RNG draw/RNGEvent、PR9 caller/ledger |
| action admission | `systems/action_contract.py` | 只回归 | 修改 A1 authority |
| Canonical IR/lowering/catalog | `rules/**`, `tbgd/**` | 只读取/回归 | 为 A2 重写来源或 materializer |

## 5. 最小允许修改路径

业务/runtime 只允许：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/event_dispatch.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status_callbacks.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py
```

验证/报告只允许新增或最小修改：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_action_window_status_nested_ability_transport.py
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2_ACTION_WINDOW_STATUS_NESTED_ABILITY_TRANSPORT_execution_report.md
.github/workflows/p9-a2-pr-validation.yml
```

若现有测试模块中已有直接覆盖上述四个 runtime 文件的聚焦测试，允许在**现有同域 test 文件**补最小断言；不得借机新铺测试框架。

显式禁止修改：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/**
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/**
PR #9 branch / PR #9 unmerged files
```

若真实实现必须越过这些边界，先 `NEEDS_REPLAN`；新依赖、付费 runner、权限扩大或 continuation/public semantics 改变则 `NEEDS_DECISION`。

## 6. 实施顺序（同一 PR 内，不拆第二张卡）

### A2.1 request-bound nested ability capability

1. 在 AbilityTaskSystem 建立最小正式 nested-only hook capability/provider。
2. 每次 hook 调用从真实 child `TaskGraphHookRequest` + RuleBook typed phase/task identity + status owner/target context 建立/验证 child invocation；不能复用外层 action ability identity。
3. 对现有 leaf/condition/branch/count/targets/graph 复用同一生产 handler；不得复制 handler。
4. `weighted_selection` 只接 A2 deferred blocker。

### A2.2 action-window transport admission

1. `CombatExecutor` 只在真实 action-window listener 路径交付该 capability。
2. `EventDispatchSystem` 将其原样运输到匹配的 `StatusCallbackSystem` 调用，并校验调用形态。
3. 不改变 trigger-system action-window 语义，不把所有普通 event dispatch 自动升级为 formal-root capability。
4. 已有 continuation + hooks pair 路径继续通过原 contract，不回退。

### A2.3 status routing closure

1. `StatusCallbackSystem` 只能在 `mainline_avatar_ability`、已准入 formal status graph、typed TriggerAbility child 上消费 capability。
2. route 必须覆盖 `leaf / condition / branch / count / targets / graph / weighted_selection` 全通道。
3. status graph 请求永远使用 status hooks；`ability_phase_callback` 请求使用 nested ability capability；其他 `entry_kind` fail-closed。
4. child graph cycle/identity/projection/atomicity继续由共享 TaskGraphExecutor 与既有结果合并契约负责，不复制第二套机制。

## 7. 必须独立断言的负例与回归

至少包含以下独立断言，不能只看一个最终 reason 字符串：

1. `TaskGraphContinuation.from_hook_request` 仍是唯一 continuation 构造路径；`systems/task_graph.py` diff 为零。
2. action-window formal status root 不携带伪造 parent continuation。
3. hooks/capability 缺失、错误类型、错误 entry kind、错误 child phase/task identity 都在 mutation/RNG/event 前 blocked。
4. 普通无 formal-root admission 的外部 status listener 不能借 A2 capability 进入 `nested_only` ability。
5. status TriggerAbility 只能进入 RuleBook typed linked `nested_only` phase/standalone graph；缺失、重复、歧义 fail-closed。
6. child actor 由真实 status owner 绑定；构造一个“action actor != status owner”的负例，证明不能偷用 outer command actor。
7. target scope 取真实 hook request/status context；不能从 source trace 或固定 target id 重建。
8. route 七个 hook channel 均有独立哨兵断言，特别证明 `weighted_selection` 不再在 StatusCallbackSystem 丢失。
9. A2 weighted-selection deferred hook 被调用时：state identity 不变；mutation/event/RNGEvent/settlement 为零；reason 属于 AbilityTaskSystem authority，而不是 `status_nested_ability_weighted_selection_context_missing` / generic hook-missing。
10. 既有 `ability leaf -> event -> status` continuation 路径仍要求 continuation + hooks 成对，并保持 active graph stack/cycle guard。
11. A1 action admission 回归：formal action graph admission authority 不回退；legacy whole-action blocker 不恢复。
12. PR9 RNG 权威回归：A2 不产生新的 weighted RNGEvent，不修改 whole-action RNG ledger 聚合。
13. 任一 nested execution failure 不发布成功 child projection，不提交部分 mutation；status callback group atomic rollback 保持。

合成微型 graph/哨兵只允许用于 2-13 的组件负例/路由断言，**不得**作为 Direct 或阶段完成的替代。

## 8. 真实生产 Direct（阶段完成硬门）

Direct 必须从 merged master 的正式生产构建/RuleBook/角色来源出发，不手造 `StatusCallbackIR`、`TaskGraphIR`、nested phase、RandomConfig graph 或假 callback detail。

### 8.1 动态 denominator

validator 先从正式目录动态计算：

```text
mainline_avatar_ability formal status callbacks
  ∩ action-window reachable callback events
  ∩ executable typed TriggerAbility tasks
  ∩ uniquely linked nested_only ability graph
```

并对其中能继续到 `weighted_selection` 的当前真实来源单列 denominator。不得用固定角色 ID、固定文件名或 validator 自建 graph 作为筛选规则；固定 ID 只可出现在打印出的 evidence 示例中。

### 8.2 真实调用

至少选择一个当前动态代表，通过生产接口建立/取得真实可监听 status instance、合法 ActionCommand、action target resolution 和 action-window event，随后**唯一业务入口**必须是：

```text
CombatExecutor.execute(ActionCommand)
```

禁止把以下调用作为 Direct：

```text
StatusCallbackSystem.execute(...)
StatusCallbackSystem._execute_formal_callback(...)
TaskGraphExecutor.execute(synthetic graph, ...)
validator 自己调用 nested hook
手工 new callback/phase/task graph 后调用 runtime
```

状态若不能通过当前生产构筑/状态准入路径真实附着，不能在 validator 里手塞 `status_detail` 冒充 Direct；这说明仍有真实前置遗漏，必须 `NEEDS_REPLAN` 并报告具体 producer gap。

### 8.3 Direct 必须证明的有序链

Evidence 必须能独立证明：

```text
action admission accepted
-> action-window event actually dispatched
-> listener matched a real status instance
-> formal status_callback graph started as admitted root
-> real TriggerAbility node executed
-> typed linked nested_only ability graph selected
-> nested ability hook request reached AbilityTaskSystem authority
-> weighted_selection channel (if present on chosen representative) reached A2 deferred hook
```

若动态代表包含 RandomConfig，**A2 的预期终点就是 PR9-owned caller 前的显式 fail-closed boundary**；不得为了把整个 action 标成 success 而实现 RNG、跳过 RandomConfig、选固定 branch 或把 blocker 改 warning。

若当前 denominator 同时存在不依赖 deferred RNG 的真实 status->nested ability 候选，validator 还必须动态选择至少一个并证明现有 leaf semantics 成功执行；不存在时只记录 denominator=0，不为此造 synthetic Direct。

## 9. Fast / Direct / CI

从 `<core>` 运行，具体 Python 可遵循仓库现有 runner：

### Fast

```text
python -m compileall core/executor.py systems/event_dispatch.py systems/status_callbacks.py systems/ability.py tools/validate_p9_a2_action_window_status_nested_ability_transport.py
python tools/validate_p9_a2_action_window_status_nested_ability_transport.py --fast
git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

Fast 至少含 request-bound identity、七通道路由、错误 owner/entry-kind、无 admission、原子回滚、S8B5 continuation pair 回归、A1 admission 回归。

### Direct

```text
python tools/validate_p9_a2_action_window_status_nested_ability_transport.py --direct
```

Direct 只能走第 8 节真实生产入口。若 validator 需要真实 CanonicalIR 构建，允许按现有生产构建入口执行一次；禁止建立第二套构建器或缓存语义。

### Catalog / Full

- 本卡不改 source/lowering/public index，默认 **不要求 Catalog**。
- 本卡不改 TaskGraphIR/stage/release，默认 **不要求 Full**。
- 若 EXEC 实际触碰这些域，先 `NEEDS_REPLAN`，不能自行把门禁扩大后宣称完成。

### GitHub Actions

新增最小 `.github/workflows/p9-a2-pr-validation.yml`，使用仓库现有免费/标准 runner 与既有依赖安装方式，只运行 scoped compile、A2 Fast、A2 Direct、`git diff --check <base> <head>`。禁止付费 runner、新依赖或弱化既有 workflow。

建议资源预算：Fast 30s / 512MiB；Direct 120s / 1.5GiB；evidence 256KiB。若 merged-master 的现有生产构建本身超过预算，记录实测，不通过删门/改 synthetic 解决。

## 10. 报告要求

执行报告必须写入：

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2_ACTION_WINDOW_STATUS_NESTED_ABILITY_TRANSPORT_execution_report.md
```

至少包含：

- exact base 与 actual final head；
- 实际 diff 文件列表，以及逐项说明为何均在允许写集合；
- action-window 当前调用链与最终实现后的 transport/routing 链；
- 动态 real-source denominator、代表来源/phase/callback/task/graph identity；
- Fast/Direct 命令、exit code、关键断言；
- 真实 Direct 的有序证据链；
- weighted-selection 最终 blocker 的 authority、零 RNG/零副作用证据；
- continuation factory/`systems/task_graph.py` 未改证明；
- A1 admission、S8B5 continuation pair、atomic rollback 回归；
- GitHub Actions run URL/id 与最终状态；
- `remaining`: 原 PR #9 RandomConfig caller/RNG ledger 仍 deferred，A2 不声称闭合；
- 任何真实生产者缺失、source gap、deferred sibling 必须诚实列出。

## 11. 完成条件

只有同时满足以下条件，EXEC 才能交 `ready_for_review`：

```text
base_is_exact_merged_a1_master=true
unmerged_pr9_code_used=false
action_window_listener_uses_explicit_formal_root_nested_ability_capability=true
fake_action_parent_continuation_count=0
continuation_authority_changed=false
status_trigger_ability_request_is_typed_authority=true
nested_only_root_escape_count=0
status_hook_router_covers_all_7_channels=true
weighted_selection_reaches_ability_owned_deferred_boundary=true
weighted_selection_rng_draw_count=0
weighted_selection_rng_event_count=0
failed_nested_execution_state_change_count=0
failed_nested_execution_success_projection_count=0
real_direct_entry_is_combat_executor_execute=true
synthetic_direct_count=0
a1_admission_regression_pass=true
s8b5_continuation_pair_regression_pass=true
fast_pass=true
direct_pass=true
git_diff_check_pass=true
ci_pass=true
execution_report_complete=true
```

### 立即停止 / 交回规划

以下任一项出现即不得自行扩权：

- 需要第二种 continuation factory 或修改 `systems/task_graph.py` 才能给 action-window 伪造 parent；
- 当前真实 status instance 没有生产附着路径，Direct 只能手塞 callback/detail；
- nested ability identity 只能靠名称、固定 ID、source trace 或 outer action ability 推断；
- 需要修改 A1 action authority、lowering/catalog、PR #9 caller/RNG 或其他 deferred domain；
- 需要新依赖、付费 runner、额外权限；
- 为通过 Direct 必须跳过 RandomConfig、固定选 branch、降低 blocker 或把 synthetic 当真实来源。

普通代码、validator、Actions workflow 和环境排障由 EXEC 在本卡写集合内自行解决，不因此 `BLOCKED`。

## 12. 下游边界

A2 通过独立 REVIEW 并合并后，PLAN 才能从新的 merged master 恢复原 PR #9。恢复 PR #9 时其真实 Direct 仍必须是原先要求的 `CombatExecutor.execute(ActionCommand)`；A2 不得替 PR #9 实现 RandomConfig weighted caller、RNGEvent、whole-action RNG ledger 或任何 sibling deferred 语义。
