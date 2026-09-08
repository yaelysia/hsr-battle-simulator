# P9-A2-P0 Action-window 状态 Callback 准入最终化执行卡

## 0. 状态与依赖

- 类型：P9-A2 的独立前置；STRICT。
- 规划来源：PR #11 在真实 `CombatExecutor.execute(ActionCommand)` Direct 中发现的生产前置遗漏。
- 固定 base：`master@bd1a4ac94ca394d2ea563d086eaf56e9ed45b285`。
- 本卡必须从该已合并 master 独立执行，不得读取、cherry-pick、复制或依赖尚未合并 PR #11 的生产实现。
- 依赖顺序修订为：

```text
A1 / PR #10 merged
  -> A2-P0 本卡：source-backed action-window status callback/task admission finalization
  -> A2 / PR #11：action-window status -> nested formal ability runtime transport/routing
  -> 恢复 PR #9 原 RandomConfig caller/RNG-ledger Direct
```

- PR #11 当前实现和原验收目标全部保留；本卡不替代 PR #11 的真实 Direct。A2-P0 合并后，PR #11 必须基于新的 merged master 复核并继续跑原卡未降低的 `CombatExecutor.execute(ActionCommand)` Direct。

## 1. 为什么需要本前置

PR #11 当前 head `b9b8e104de31c3d3aae5d857e7164acbfcee3b9c` 已证明其 A2 Fast 组件链成立：request-bound identity、七条 hook 通道、S8B5 continuation/active-stack/cycle/atomic rollback、A1 admission regression 全部通过；`weighted_selection` 已能在组件链抵达 AbilityTaskSystem-owned 的显式 PR9 deferred boundary，且不消费 RNG、不改变 state。

真实 Direct 仍无法进入该 runtime transport。独立诊断在 merged-master source-backed 分母中得到：

- action-window 相关 `mainline_avatar_ability` callback：238 条；
- 其中 `coverage_status=executable && admission_status=executable`：126 条；
- `OnAfterAttack` 同一事件族内同时存在 53 条已准入 callback 与 11 条 `status_callback_event_not_admitted:OnAfterAttack` callback；
- 当前真实 action-window `TriggerAbility` 分母只有一条，来源为银狼角色正式 ability 文件；其 typed standalone target 已存在，但 task 仍保留旧 `status_callback_event_not_admitted:OnAfterAttack` blocker；
- 相同 blocker 同时存在于聚焦生产 RuleBook 与既有 S8C1C source bundle，说明不是 PR #11 validator 人造状态；
- existing runtime producer map 已有 `OnAfterAttack -> action.window.after_attack`，所以不是缺 action-window producer；
- 现有 `_link_status_trigger_ability_graphs(...)` 负责补 typed nested target，但按 S8B5B 契约不会反向提升被阻断 parent callback/task；
- 当前 lowering 的 event blocker 在更早的 per-file callback/task admission 阶段冻结，后续只有“补 link / 加 blocker”，没有在最终 typed source facts 齐备后做一次来源驱动的 admission finalization。

以上数量仅是本次规划审计快照，**不是固定验收常量**。执行和验收必须重新动态计算当前分母。

## 2. 结论与唯一工作

这是 L0 lowering / Canonical IR 的 `admission_gap`，不是 PR #11 runtime 执行缺陷。

本卡唯一工作：在既有角色 status callback/task lowering、status event producer family、typed `TriggerAbility` link 等事实均已形成后，为 **source-backed action-window formal status callback/task** 增加一个最终准入裁决点，使“唯一阻塞原因只是过早冻结的 event admission、且现在生产事实已经完整证明可正式路由”的结构任务可以被重新判定；其余 blocker、来源范围、结构拓扑和 runtime 语义保持不变。

不得用“删字符串 blocker”“全局允许 OnAfterAttack”“按角色/技能名特判”实现。

## 3. 生产权威归属

### 3.1 本卡唯一生产权威

`hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py`

新增/收口一个 **post-link status callback/task admission finalization**。它只消费已经存在的 typed/source-backed facts，不新建第二套事件或图执行模型。

### 3.2 只读既有权威

以下事实必须复用，不得重新推断：

1. status event producer / runtime source：既有 `StatusEventFamilyIR` 及 lowering 中的 status event runtime-source mapping；
2. status callback/task raw/source identity：现有角色 ability lowering 结果；
3. `TriggerAbility` target identity：现有 `_link_status_trigger_ability_graphs(...)` 产出的 `linked_ability_phase_id` / `linked_standalone_graph_id`；
4. nested invocation role / catalog：既有 S8B5B/S8B4 task-graph materialization 契约；
5. runtime action-window/status/nested transport：PR #11，**本卡不可依赖也不可修改**；
6. RandomConfig weighted-selection caller/RNG authority：PR #9 deferred，本卡不可实现。

### 3.3 明确禁止的新权威

- 不新增 event family registry；
- 不新增 callback allowlist；
- 不新增角色 ID/技能名/文件名 runtime 或 lowering 特判；
- 不从文本、日志、source trace、PR #11 结果反向构造准入；
- 不改变 `TaskGraphContinuation`、TaskGraphIR、RuleBook public contract；
- 不建立 synthetic producer 来让 Direct 变绿。

## 4. 最小生产调用链

执行前必须实际核对 merged master 上以下完整顺序，并把最终符号/调用位置写进报告；若顺序与本卡假设实质不符，不得硬套：

```text
raw character ability source
  -> per-file status callback/task lowering
  -> existing callback/task source + effect/task semantics
  -> existing status event family / runtime producer projection
  -> existing typed TriggerAbility link pass
  -> A2-P0 final admission projection
  -> existing formal status task-graph materialization/catalog
  -> CanonicalIR
  -> RuleBook
```

若当前实际构建顺序使 finalizer 必须在 task-graph catalog 之后才能可靠判断，可在 `lowering.py` 内复用既有 materializer 结果/既有构建步骤，但不得修改 materializer 语义。若必须修改 `task_graph_materializer.py`、`rules/**` 或 runtime 才能完成，返回 `NEEDS_REPLAN`；若需要改变公共 IR/continuation/event semantics，返回 `NEEDS_DECISION`。

## 5. 准入最终化的必要条件

一个 callback/task 只有同时满足下列条件，才允许从“旧 event admission blocker”重新裁决；不满足任一条必须保留 blocked：

### 5.1 来源与事件身份

- `source_mode == "mainline_avatar_ability"`；
- callback/task 来源属于当前角色正式 source graph，不是 synthetic、equipment、monster、global 或测试夹具；
- callback event 能由既有 `StatusEventFamilyIR` 明确映射到真实 action-window runtime producer；
- event family 自身已是 executable，且 runtime source identity 非空、唯一、与 callback event 对应；
- 当前 blocker 必须精确是该 event 的 `status_callback_event_not_admitted:<event>`，不能覆盖其他原因。

### 5.2 task 自身语义

- task 的 opcode/typed payload/source identity 已按既有 lowering 合法；
- 对结构任务，不能要求 legacy effect handler 执行它；必须尊重现有 task-graph structural ownership；
- 对 `TriggerAbility`，必须已经有且仅有一个 typed target：`linked_ability_phase_id` 或 `linked_standalone_graph_id`，不能两者同时存在、不能都缺失；
- linked target 必须对应现有正式 definition，且目标 invocation role/standalone ledger 与 S8B5B 契约一致；
- unresolved reference、source gap、unsupported target/condition/effect、queue blocker、deferred sibling 等任何其他独立 blocker 都不能被本 finalizer 消除。

### 5.3 graph / callback 闭包

- callback 的正式 root identity 必须仍由既有 callback/task ids 决定；finalizer 不改 graph/node/task id；
- 若现有 materialization 能在 finalizer 前提供 graph evidence，必须验证 selected formal graph 唯一且 source/task identity 一致；
- 若 graph 在 finalizer 后 materialize，则 validator 必须对最终 CanonicalIR 证明对应 formal status root resolved，并证明目标 nested-only ability graph/standalone target 可被现有 catalog 唯一选出；
- 不能因为一个 `TriggerAbility` 可链接就把同 callback 下无关 blocked sibling 自动提升；每个 task 仍按自己的 blocker/结构路径裁决；
- callback aggregate admission 只能通过现有 callback 聚合规则重新计算，禁止“只要有一个可执行 task 就直接 replace callback executable”之类旁路。

## 6. 允许改变的字段与不可变身份

### 可改变

只允许对本 finalizer 动态选中的精确 callback/task 行，按现有 IR 字段语义重新产生：

- `coverage_status`；
- `blocked_reason`；
- callback 的 `admission_status` / `blocking_dependency`（若当前 IR 将 event admission 分开记录）。

### 必须保持不变

- callback/task id；
- source path / json path / evidence identity；
- modifier/event/callback ownership；
- opcode；
- effect id；
- parent/child task topology；
- linked phase/standalone identity；
- ability phase/standalone graph ids；
- target/condition/effect definitions；
- event runtime-source mapping；
- non-gameplay/source dispositions；
- 任意 RandomConfig/weighted-selection/RNG 字段。

validator 必须逐项比较 finalizer 前后 identity，不能只看最终 count。

## 7. 明确非目标

- 不修改 PR #11 的 `core/executor.py`、`systems/event_dispatch.py`、`systems/status_callbacks.py`、`systems/ability.py`；
- 不实现 action-window runtime transport；
- 不实现 RandomConfig caller、weighted-selection RNG、整行动 RNG ledger；
- 不扩大到全部 P9-S9/P9-S10 callback/event/status 生命周期；
- 不把所有 `OnAfterAttack` / `OnBeforeAttack` / skill-use callback 一次性放开；
- 不修复其他 target/condition/effect/resource/queue/deferred blocker；
- 不修改 S8B5B 的规则：“typed link 的存在本身不得在该 link pass 内提升 blocked parent”；本卡是独立的后置 finalization；
- 不把 S8C1C source bundle 当 runtime admission authority；
- 不用 synthetic callback/graph/status instance 替代真实 source denominator。

## 8. 允许写集合

生产：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
```

验证/治理：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py
.github/workflows/p9-a2-p0-pr-validation.yml
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION.md
```

若普通 CI/runner 需要最小修正本 workflow，可在同一 workflow 内处理；不得改共享 Actions runner policy、付费 runner 或新增依赖。

任何其他生产路径必须先 `NEEDS_REPLAN`，不得自行扩权。

## 9. Fast 验证要求

Fast 可以使用最小构造 IR 来证明 finalizer 的 fail-closed 逻辑，但不得把它当真实 Direct。至少独立断言：

1. producer-backed action-window event + exact stale event blocker + typed unique TriggerAbility target 可以进入 finalizer；
2. 同事件、但存在另一独立 blocker 的 task 保持 blocked；
3. linked target missing / duplicate / ambiguous 保持 blocked；
4. wrong `source_mode`、external content、synthetic source 不得被提升；
5. event family 缺 producer、producer identity 不匹配或 family blocked 时保持 blocked；
6. unrelated callback sibling 不被连带提升；
7. finalizer 不改变 callback/task/source/link/topology stable identity；
8. S8B5B link pass 单独运行时仍不提升 blocked parent；只有后置 finalizer 可做重新裁决；
9. A1 action graph admission authority 输出不变；
10. runtime files 与 `systems/task_graph.py` 未改；
11. RandomConfig/weighted-selection/RNG 无新实现。

Fast 必须输出每个 negative reason，而不是只有布尔总结果。

## 10. 真实 Direct / source denominator 验证

本前置的 Direct 只验证 **merged-master L0 -> final CanonicalIR/RuleBook admission**，因为它必须完全独立于未合并 PR #11。它不能声称完成 A2 runtime Direct。

### 10.1 独立来源分母

validator 必须从 pinned TBGD + 当前角色 source graph 动态得到所有：

```text
mainline_avatar_ability
∩ callback event 有真实 action-window producer
∩ formal status callback/task source-backed
∩ 含 TriggerAbility typed source shape
```

然后与生产 lowering 输出逐条对账：source path、callback id、task id、event、current coverage/admission、blocker、typed linked target、formal graph identity。

不得写死角色 ID、callback ID、银狼文件名或固定分母数量作为通过条件。可以在报告中记录动态代表。

### 10.2 必须证明的真实正例

最终 production CanonicalIR/RuleBook 中至少动态发现一条：

- action-window producer-backed；
- callback `coverage_status/admission_status` 已按现有语义 executable；
- `TriggerAbility` task executable；
- typed linked phase/standalone target 唯一；
- formal status root graph resolved；
- nested target definition 可由既有 catalog 唯一定位；
- 该行在 finalizer 前的唯一控制 blocker 是 stale `status_callback_event_not_admitted:<event>`；
- 没有借 synthetic、手工 replace RuleBook、validator patch production result 或固定 ID 造正例。

当前规划审计代表是银狼 `MAvatar_Advanced_Silwolf_00_Passive / OnAfterAttack -> TriggerAbility -> ...PassiveSkill_RandomBug`，但执行必须动态重选，不能把该名字写进门禁。

### 10.3 必须证明的真实负面分母

对所有同 action-window event 的 blocked callback/task 重新统计 reason transition：

- 只有满足本卡全部必要条件的行可以从 stale event blocker 转为 executable；
- 任何存在独立 target/condition/effect/queue/deferred/source blocker 的行仍必须 blocked；
- 不要求当前 11 条 OnAfterAttack blocked 全部留下或全部消失；要求每一条 transition 都有来源/typed-fact 解释；
- 统计 before/after reason histogram 与 promoted row ledger；数量是 evidence，不是 hard-coded gate。

## 11. PR #11 回验契约

A2-P0 REVIEW accepted 并 merge 后：

1. PR #11 仍使用现有 branch/实现，不丢弃当前工作；
2. 将 PR #11 更新到新的 merged master；
3. PR #11 原 Fast 断言全部原样保留；
4. PR #11 原真实 Direct 仍只能从 `CombatExecutor.execute(ActionCommand)` 进入；
5. Direct 仍动态发现真实 action-window status `TriggerAbility` candidate；
6. 若代表含 RandomConfig，A2 成功仍只要求抵达 `ability_task_weighted_selection_caller_deferred_to_pr9`，且 state/mutation/event/settlement/RNG 不因该 deferred caller 被错误提交；
7. 不得把本前置 L0 Direct 当作 PR #11 Direct 的替代品。

若 A2-P0 merge 后 PR #11 Direct 暴露新的 **独立、source-backed 且早于 A2 transport** 的 blocker，EXEC 应提供完整 denominator 后再次 `NEEDS_REPLAN`，不能绕过。

## 12. CI

新增：

```text
.github/workflows/p9-a2-p0-pr-validation.yml
```

至少包含：

```bash
python -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --fast

python hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p0_action_window_status_callback_admission_finalization.py --direct

git diff --check bd1a4ac94ca394d2ea563d086eaf56e9ed45b285 HEAD
```

STRICT 要求：

- Fast 与 Direct 分开报告；
- Direct 必须 checkout pinned source submodule；
- workflow 不得用临时 patch 改生产代码或 validator 后再宣称正式 PASS；诊断 patch 可用于失败调查，但最终验收 run 必须直接执行 committed head；
- 不新增第三方依赖；
- 记录 wall time、peak RSS 和主要 denominator evidence；
- 若全量 source build 超出现有 runner 预算，优先复用现有 focused source/context builder，但必须覆盖当前角色正式 source denominator，不能用 synthetic 缩成假 Direct。

## 13. 报告要求

执行报告：

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P0_ACTION_WINDOW_STATUS_CALLBACK_ADMISSION_FINALIZATION_execution_report.md
```

必须包含：

- base / 实际 final head；
- 精确 production diff；
- finalizer 在真实 build 中的调用位置及前后权威；
- 独立 source denominator 构造方式；
- before/after callback/task reason histogram；
- promoted row ledger（source/callback/task/event/old reason/new status/typed target/formal graph）；
- 未提升 blocked rows 的主要原因分布；
- Fast 命令/结果；
- Direct 命令/结果；
- CI run URL/id；
- fixed-base `git diff --check`；
- 未修改 PR #11/runtime/PR9 RNG 的证明；
- remaining：A2-P0 只闭 L0 prerequisite，PR #11 仍须完成原真实 Direct。

## 14. 风险与停止条件

立即 `NEEDS_REPLAN`：

- 需要修改 `task_graph_materializer.py`、`rules/**`、`systems/**`、`core/**` 才能完成；
- 需要重写 S8B5B typed-link ownership；
- 真实正例除 stale event admission 外还存在另一个尚未规划的 L0 blocker；
- 需要把全 P9-S9/S10 事件/状态域一起实现；
- finalizer 无法用 typed/source facts 区分“真正 stale event blocker”和“仍缺语义的 blocker”。

立即 `NEEDS_DECISION`：

- 需要改变公共 Canonical IR schema / TaskGraphIR / continuation contract；
- 需要改变 action-window 事件语义或 producer ownership，而非消费现有 producer mapping；
- 需要新的外部依赖、付费服务/runner；
- 需要选择两套不可兼容的长期 admission authority。

普通 validator、CI、submodule、runner、路径或资源预算问题由 EXEC 自行排障，不升级。

## 15. 完成条件

全部满足才可 `[HANDOFF:REVIEW]`：

- [ ] 只增加一个 L0 post-link admission finalization authority；
- [ ] 真实 action-window status TriggerAbility 分母动态重算并逐条对账；
- [ ] 至少一条真实 source-backed candidate 在最终 CanonicalIR/RuleBook 中形成 executable callback + executable TriggerAbility + unique typed nested target + resolved formal root；
- [ ] 同事件不相关 blocked rows 未被 blanket promote；
- [ ] 所有 promoted row 只移除了精确 stale event admission blocker，stable identity 与 typed links 不变；
- [ ] S8B5B “link pass 本身不提升 blocked parent”仍成立；
- [ ] A1 admission regression 不变；
- [ ] runtime、TaskGraphContinuation、PR9 RNG 未改；
- [ ] Fast PASS；
- [ ] 真实 L0 Direct PASS；
- [ ] 最终 committed-head CI PASS；
- [ ] 报告完整；
- [ ] PR #11 原真实 `CombatExecutor.execute(ActionCommand)` Direct 明确保留为下一步，不被本卡证据替代。
