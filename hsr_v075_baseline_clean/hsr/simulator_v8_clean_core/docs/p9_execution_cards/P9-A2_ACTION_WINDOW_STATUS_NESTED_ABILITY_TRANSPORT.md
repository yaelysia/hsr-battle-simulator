# P9-A2 Action-window status callback → nested formal ability transport

## 0. 执行身份与恢复点

- dispatch id: `P9-NEXT-63a21d6f8bf6c64e`
- risk mode: `STRICT`
- approved route: `A1 -> A2-P0 -> A2 (this PR) -> resume existing PR #9`
- exact merged base: `master@770a0649926932794585fcd30589c6776892bc3b`
- merged prerequisite: PR #12 / A2-P0 已独立 REVIEW accepted 并 squash merge；验收评论 `https://github.com/yaelysia/hsr-battle-simulator/pull/12#issuecomment-5580454945`。
- preserved A2 implementation anchor before master sync: `b9b8e104de31c3d3aae5d857e7164acbfcee3b9c`。
- master sync merge commit: `ef7da5fce6696c37e87610175511aececb3ed385`；其双亲为上述 A2 implementation anchor 与 merged master。
- target PR: existing Draft PR #11；不得新建替代 A2 PR。
- PR #9 继续暂停；不得读取、搬运或复用其未合并业务实现。

本文件是 PR #11 当前唯一执行卡。它恢复既有 A2，而不是重新规划或重写既有实现。EXEC 必须保留已存在的 runtime 纵切，先在新 merged master 上复核，再只处理普通代码、validator、workflow、CI 或环境问题。任何真正需要扩大生产范围的前置缺口必须 `NEEDS_REPLAN`；任何需要改变 authority/public semantics、增加依赖、扩大权限或成本资源的事项必须 `NEEDS_DECISION`。

## 1. 已闭合前置与旧失败的解释

### 1.1 A1 已闭合

PR #10 / Route A A1 已建立 formal action graph admission authority。本卡不得修改 `systems/action_contract.py`，不得恢复 whole-action legacy pre-screen，也不得降低 A1 的 reachable blocker / cycle fail-closed 契约。

### 1.2 A2-P0 已闭合，但只属于 L0 admission prerequisite

PR #12 在 merged master 的 `tbgd/lowering.py` 中完成 action-window status callback admission finalization，并由 STRICT 证据证明真实 formal source -> pre-finalizer IR -> typed target/final graph -> production audit 的 exact closure。

A2-P0 **不等于**本卡 runtime transport/routing，也**不能**替代本卡真实：

```text
CombatExecutor.execute(ActionCommand)
```

Direct。本卡禁止修改 PR #12 的 lowering/finalizer 来规避 runtime 问题。

### 1.3 PR #11 已有实现必须保留

旧 A2 head `b9b8e104...` 已具备本卡的 runtime 实现与 Fast 回归。旧 CI run `34161465593` 中 scoped compile、Fast、A1/S8B5 回归和 fixed-base diff check 通过；真实 Direct 失败于：

```text
A2 real-source status->nested ability denominator is empty
```

该失败发生在 A2-P0 合并前，诊断明确定位到真实 action-window `TriggerAbility` 来源仍被 `status_callback_event_not_admitted:OnAfterAttack` 阻断。因此该结果是 PR #12 的前置证据，不是 PR #11 的最终验收结论。

恢复后必须从 `master@770a0649...` 重新动态求真实 denominator 并重跑原有 runtime Direct；不得把旧失败改写成 synthetic success，也不得把 PR #12 L0 validator 当作本卡 Direct。

## 2. 唯一目标

闭合以下 runtime 纵切，同时保持 RandomConfig caller/RNG ledger deferred 到原 PR #9：

```text
real CombatExecutor.execute(ActionCommand)
  -> admitted action-window listener
  -> real formal status_callback root
  -> typed status TriggerAbility request
  -> request-bound nested-only ability capability/hooks
  -> nested formal ability graph
  -> leaf / condition / branch / count / targets / graph / weighted_selection
     按 child graph entry_kind 完整路由
  -> weighted_selection reaches AbilityTaskSystem-owned explicit deferred boundary
```

如果动态发现的真实代表不需要 deferred weighted selection，则允许走既有已准入 leaf semantics；但不得为了得到 success 而跳过 RandomConfig、固定 branch、伪造候选或扩大支持范围。

## 3. 必须保持的生产 authority

| 责任 | 唯一 authority | 本卡允许 | 本卡禁止 |
|---|---|---|---|
| continuation provenance / active stack | `systems/task_graph.py` / `TaskGraphContinuation.from_hook_request` | 只消费既有类型 | 新 continuation factory、payload/source_trace 重建、改变 cycle semantics |
| action-window orchestration | `core/executor.py` | 将正式 nested-ability capability 交给真实 listener 路径 | 解析 TriggerAbility、选择 child ability、实现 RNG |
| event/listener transport | `systems/event_dispatch.py` | 运输并 fail-closed 校验 formal-root capability；保留既有 continuation pair | 成为 ability 语义 authority、按名称/固定 ID 路由 |
| formal status graph / TriggerAbility resolver | `systems/status_callbacks.py` | 绑定真实 status request；按 entry_kind 路由全部 7 channels | 伪造 child invocation、自己执行 ability/RNG |
| nested formal ability semantics/hooks | `systems/ability.py` | request-bound child invocation/hook provider；weighted hook 仅显式 deferred | RandomConfig 选择、RNG draw/RNGEvent、whole-action RNG ledger |
| action admission | `systems/action_contract.py` | 只回归 | 修改 A1 authority |
| source/lowering/catalog | `tbgd/**`, `rules/**` | 只读取 merged-master 结果与回归 | 为 A2 重写来源、admission finalizer、materializer 或 public IR |

Action-window status callback 可以作为既有 formal status root，但进入 `nested_only` ability 的能力必须是显式、类型化、request-bound 的 capability；不得把 status root 假装成外层 action graph child，也不得把 outer `ActionCommand.actor_id` 当作 status owner。

## 4. 允许写集合

业务/runtime 仅允许：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/event_dispatch.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status_callbacks.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py
```

验证/报告/本 PR workflow 仅允许：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_action_window_status_nested_ability_transport.py
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2_ACTION_WINDOW_STATUS_NESTED_ABILITY_TRANSPORT_execution_report.md
.github/workflows/p9-a2-pr-validation.yml
```

若已有同域测试文件直接覆盖上述 runtime，可补最小断言；不得铺新测试框架。

显式禁止修改：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/**
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/**
PR #9 branch / PR #9 unmerged files
```

注意：PR #12 已合并的 `tbgd/lowering.py` 是**基线**，不属于本卡允许写集合。

## 5. 恢复执行顺序

1. 核实 PR #11 仍为 Draft/open，且当前分支包含 `master@770a0649...` 与 preserved implementation anchor `b9b8e104...`。
2. 以新 master 为固定 base 检查实际 PR diff；不得删除或回退已有 A2 runtime 实现来“重新开始”。
3. 从 merged-master 正式来源重新动态枚举 action-window status `TriggerAbility` denominator；不得硬编码 `avatar_skill:1100601`、Silverwolf 名称或固定 source path 作为唯一通过样本。
4. 运行原 Fast。普通实现/validator/workflow 错误由 EXEC 在允许写集合内自行修复。
5. 运行**不变语义**的真实 Direct：唯一入口必须是 `CombatExecutor.execute(ActionCommand)`，并走真实生产状态附着/监听、action window、formal status root、typed TriggerAbility、nested ability routing。
6. 若代表包含 weighted selection，预期终点仍是 `AbilityTaskSystem` owned 的显式 deferred boundary；必须保持零 RNG draw、零 RNGEvent、零 mutation/event/settlement side effect。
7. 提交完整 execution report，在最终 committed head 上重跑 Fast + Direct + fixed-base diff check + GitHub Actions。
8. 只有最终 committed head 的真实 Direct 和 CI 都通过后，才能 `[HANDOFF:REVIEW]`；不得用 workflow 临时 patch 后的未提交 validator 结果冒充最终 committed-head 证据。

## 6. Direct 的真实边界

以下都**不是**本卡 Direct：

```text
PR #12 / A2-P0 L0 lowering Direct
StatusCallbackSystem.execute(...) 直接调用
StatusCallbackSystem._execute_formal_callback(...) 直接调用
TaskGraphExecutor.execute(synthetic graph, ...)
validator 直接调用 nested hook
手工构造 callback/phase/task graph 后调用 runtime
手塞 status_detail / callback instance 冒充生产状态附着
```

真实 Direct 必须有序证明：

```text
action admission accepted
-> CombatExecutor.execute(ActionCommand)
-> action-window event actually dispatched
-> listener matched a real production-attached status instance
-> formal status_callback graph started as admitted root
-> real TriggerAbility node executed
-> typed linked nested_only ability graph selected
-> nested ability hook request reached AbilityTaskSystem authority
-> weighted_selection channel, if present, reached A2 deferred hook
```

动态 representative 的 source/phase/callback/task/graph/owner/target identity 与完整 denominator 都必须写入 evidence。

## 7. Fast / Direct / CI

从 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core` 运行。

### Fast

```text
python -m compileall core/executor.py systems/event_dispatch.py systems/status_callbacks.py systems/ability.py tools/validate_p9_a2_action_window_status_nested_ability_transport.py
python tools/validate_p9_a2_action_window_status_nested_ability_transport.py --fast
git diff --check 770a0649926932794585fcd30589c6776892bc3b HEAD
```

Fast 至少保持：request-bound identity、7-channel routing、wrong owner/entry-kind/provider、no admission、atomic rollback、S8B5 continuation pair/active stack/cycle 回归、A1 admission 回归。

### Direct

```text
python tools/validate_p9_a2_action_window_status_nested_ability_transport.py --direct
```

Direct 的入口语义不得变化，仍必须实际命中 `CombatExecutor.execute(ActionCommand)`。A2-P0 的 L0 Direct、synthetic callback、validator-only hook invocation 均不能替代。

### Catalog / Full

本卡不改 source/lowering/public index，不默认要求 Catalog；不改 TaskGraphIR/stage/release，不默认要求 Full。若 EXEC 认为必须修改这些域才能通过，停止并 `NEEDS_REPLAN`，不得自行扩门或扩生产范围。

### GitHub Actions

`.github/workflows/p9-a2-pr-validation.yml` 使用标准免费 runner、只读权限和既有依赖方式，最终至少执行 scoped compile、Fast、真实 A2 Direct、`git diff --check 770a0649... HEAD`。workflow/validator 的普通诊断或 CI 排障由 EXEC 自行处理，但最终验收必须基于 PR 最终 committed head；不得依赖 workflow 在运行时临时改写 validator 后才成立的业务结论。

## 8. 必须独立断言的负例与回归

1. `TaskGraphContinuation.from_hook_request` 仍是唯一合法 continuation 铸造路径；`systems/task_graph.py` 相对新 master diff 为零。
2. action-window formal status root 不携带伪造 parent continuation。
3. hooks/capability 缺失、错误类型、错误 entry kind、错误 child phase/task identity，在 mutation/RNG/event 前 fail closed。
4. 普通无 formal-root admission 的外部 status listener 不能借 capability 进入 `nested_only` ability。
5. status TriggerAbility 只能进入 RuleBook typed linked `nested_only` phase/standalone graph；missing/duplicate/ambiguous link fail closed。
6. child actor 来自真实 status owner；必须保留 outer action actor != status owner 的负例。
7. target scope 来自真实 hook request/status context，不从 source_trace 或固定 target id 重建。
8. `leaf / condition / branch / count / targets / graph / weighted_selection` 七通道各自可观测，特别证明 weighted selection 不再在 StatusCallbackSystem 丢失。
9. weighted-selection deferred hook 被调用时 state identity 不变，RNG draw=0，RNGEvent=0，mutation/event/settlement=0；blocker 必须属于 AbilityTaskSystem authority。
10. A1 admission、S8B5 continuation pair、active-stack/cycle guard、atomic rollback 均保持。
11. PR #12 admission finalizer 作为基线发挥作用，但本卡不能通过修改 lowering 或把 L0 evidence 替代 runtime evidence。
12. 失败的 nested execution 不得留下成功 projection 或半提交 side effect。

## 9. 完成条件

只有全部成立，EXEC 才可交 REVIEW：

```text
exact_base_is_770a0649926932794585fcd30589c6776892bc3b=true
pr12_a2_p0_prerequisite_present=true
preserved_pr11_runtime_implementation_not_discarded=true
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
l0_direct_substituted_for_runtime_direct=false
a1_admission_regression_pass=true
s8b5_continuation_pair_regression_pass=true
fast_pass=true
direct_pass=true
git_diff_check_pass=true
ci_pass=true
final_committed_head_validated=true
execution_report_complete=true
```

## 10. 执行报告

写入：

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2_ACTION_WINDOW_STATUS_NESTED_ABILITY_TRANSPORT_execution_report.md
```

至少记录：

- exact base `770a0649...`、preserved implementation anchor 与 actual final head；
- 最终 diff 文件清单及允许写集合说明；
- PR #12 prerequisite 已进入 ancestry 的证据；
- merged-master 动态 real-source denominator 与 representative 的 source/phase/callback/task/graph/owner/target identity；
- Fast / Direct / diff-check 命令、exit code、关键 predicates；
- 真实 `CombatExecutor.execute(ActionCommand)` 有序证据链；
- weighted-selection blocker authority 与零 RNG/零副作用证据；
- continuation factory、`systems/task_graph.py`、A1 authority 未改证明；
- A1 / S8B5 / atomic rollback 回归；
- 最终 committed-head GitHub Actions run URL/id/status；
- `remaining`: 原 PR #9 RandomConfig caller/RNG ledger 仍 deferred；本卡不得声称其闭合。

## 11. 立即停止 / 正式返回

以下属于真实范围问题，`NEEDS_REPLAN`：

- merged master 后仍存在一个**独立、source-backed、且逻辑上早于 A2 runtime transport** 的 blocker，使真实 Direct 只能靠修改本卡禁止域才能获得候选；
- 必须修改 `systems/task_graph.py`、A1 authority、lowering/catalog/public IR 或 PR #9 caller/RNG 才能实现本卡；
- 当前真实 status instance 没有生产附着路径，Direct 只能手塞 callback/detail；
- nested ability identity 只能依靠名称、固定 ID、source trace 或 outer action identity 推断。

以下属于真实决策，`NEEDS_DECISION`：

- 需要改变 continuation/public semantics 或 authority ownership；
- 需要新依赖、额外 GitHub 权限、付费 runner 或其他成本资源。

普通代码、测试、validator、workflow、Actions、环境与 CI 排障不属于上述情况，由 EXEC 在允许写集合内自行完成。

## 12. 下游边界

只有 PR #11 / A2 通过独立 REVIEW 并合并后，PLAN 才能恢复**现有** PR #9。恢复 PR #9 时其真实 Direct 仍必须是既定 `CombatExecutor.execute(ActionCommand)`；本卡不得替 PR #9 实现 RandomConfig weighted caller、RNGEvent、whole-action RNG ledger 或其他 S8C sibling deferred 语义。
