# P9-A2-P2 Process-only TriggerAbility admission identity

- dispatch id: `P9-NEXT-0e7b2c9ca75967c0`
- risk mode: `STRICT`
- role: Route A predecessor for existing PR #11 / A2
- exact planning base: `master@f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4`
- pinned TBGD: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- accepted prerequisite: PR #13 / A2-P1, squash merge `1df605fe7ef3b8fa74ee9b523e8b4e72be114541`, post-merge governance `f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4`
- dependent stage: existing Draft PR #11 / `P9-A2_ACTION_WINDOW_STATUS_NESTED_ABILITY_TRANSPORT`
- later stage: existing PR #9 remains paused until PR #11 is independently accepted and merged

本卡只闭合 A2 transport 之前、当前 merged master 上仍然存在的最早单一 authority blocker：
`ActionContractSystem` 对已经合法 lower 为 **process-only leaf** 的 `TriggerAbility` 再次按 opcode 推断 nested gameplay edge，产生
`ability_task_graph_nested_identity_mismatch`。本卡不得实现 S8C、S11 或其他 future-domain 语义，也不得降低 PR #11 原有真实 `CombatExecutor.execute(ActionCommand)` Direct。

## 1. 已确认事实

### 1.1 当前 merged-master blocker attribution

PR #13 最终 exact-head STRICT Direct（run `34333920090`）在 accepted A2-P1 修复后，从当前生产 action definition / lowering / formal graph / A1 admission 动态得到同 owner 普通 action representative：

```text
definition_id = action_def:avatar_skill:100101:1
action_id = avatar_skill:100101
action_level = 1
submission_mode = external_turn
```

A2-P1 已且只移除：

```text
process_only_task_effect_source_mismatch
```

当前仍保留：

```text
ability_task_graph_nested_identity_mismatch
task_graph_control_requires_domains:hit_random_sequence
task_graph_definition_not_admitted:effect:audit_only
effect_coverage_status:unsupported:FireProjectile
task_graph_definition_not_admitted:effect:unsupported
task_graph_control_requires_domains:damage_heal_shield
```

该 representative 只是当前证据，不得成为 production allowlist、固定角色选择或 validator 唯一硬编码入口。EXEC 必须从本卡 fixed base 的真实生产来源重新动态归因。

### 1.2 当前唯一冲突点

当前 `systems/action_contract.py::_formal_action_task_graph_projection(...)` 已先：

1. 从正式 action-root graph 闭包解析 canonical `TaskGraphIR` node；
2. 反查精确 `AbilityTaskIR`；
3. 调用既有 `ability_task_runtime_blocked_reason(..., topology_authority="task_graph")`；
4. 对 process-only task 跳过普通 unresolved gameplay-reference gate。

但随后它使用：

```text
node.node_kind == "ability_call" OR task.opcode == "TriggerAbility"
```

推断“这是 nested node”，并要求两侧同时成立；因此 `task.opcode == "TriggerAbility"` 但 canonical node 为 `leaf` 时产生：

```text
ability_task_graph_nested_identity_mismatch
```

### 1.3 canonical graph 与 runtime 已有 authority

当前 `tbgd/task_graph_materializer.py` 明确把所有合法 `execution_mode == "process_only"` task 物化为：

```text
node_kind = leaf
materialization_status = materialized
```

不会再按 control-role/opcode 把该 process-only task 物化为 `ability_call`。

当前 `systems/ability.py` 的 formal leaf runtime 先复用同一 `ability_task_runtime_blocked_reason(...)`；合法 process-only task 随后只返回 process/audit record，保持：

```text
state unchanged
mutations = 0
RNG = 0
```

它不会仅因为原 opcode 是 `TriggerAbility` 而从 leaf hook 转成 nested ability invocation。

因此当前 blocker 是 **A1 admission projection 对既有 canonical process-only leaf/runtime contract 的额外 opcode 推断**，不是需要新增 nested ability、RandomConfig、damage/heal/shield 或其他 future-domain support 的理由。

## 2. 唯一目标

让 formal action admission 与现有 canonical TaskGraph/runtime 在 process-only `TriggerAbility` 上保持同一 authority：

```text
formal action root graph
  -> canonical TaskGraph node identity
  -> exact AbilityTaskIR
  -> existing task runtime-support contract
  -> process-only leaf remains process-only leaf
  -> no opcode-only nested-edge inference
```

同时必须保持真实 gameplay nested edge 的严格 fail-closed：

```text
runtime-effect TriggerAbility
  <=> canonical ability_call node
  -> exact single ability reference
  -> exact linked phase / standalone identity
  -> nested_only formal graph
```

本卡成功只表示移除这一项错误 admission blocker；如果同一真实 action 仍被 S8C/S11/其他 future-domain blocker 拦住，这是预期结果，由下一轮 PLAN 重新归因。EXEC 不得顺手实现它们。

## 3. 唯一生产 authority 与正式消费者

### 3.1 唯一 production write authority

只允许修改：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
```

责任仅限 `_formal_action_task_graph_projection(...)` 对 canonical node / process-only / nested-edge identity 的静态 admission 投影。

### 3.2 必须保持只读的 authority

以下路径是本卡的现有生产事实，不得修改：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/rulebook.py
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/ir_types.py
```

PR #11 的 runtime transport 实现与 PR #9 的 RandomConfig caller/RNG-ledger 未合并业务代码均不得读取后复制、cherry-pick 或修改作为本卡实现依据。本卡只能从 merged master 建立生产证据。

### 3.3 正式消费者

本卡只改变普通 action submission 的 A1 static support projection：

```text
ActionContractSystem.evaluate(...)
  -> _formal_action_task_graph_projection(...)
```

它不改变 `AbilityTaskSystem`、`TaskGraphExecutor`、event/status callback、mutation、settlement 或 replay runtime 行为。

## 4. 允许写集合

生产：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py
```

验证/报告：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p2_process_only_trigger_ability_admission_identity.py
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P2_PROCESS_ONLY_TRIGGER_ABILITY_ADMISSION_IDENTITY_execution_report.md
.github/workflows/p9-a2-p2-pr-validation.yml
```

已有同域测试文件若直接覆盖该函数，可补最小断言；不得建立新测试框架或第二套 action admission 实现。

## 5. 必须保持的生产不变量

### 5.1 process-only 不等于 nested gameplay invocation

在 canonical graph node 与 exact task identity均已验证、且既有 `ability_task_runtime_blocked_reason(...)` 已接受该 task 后：

- 若 task 是 `process_only`，其 `TriggerAbility` 原 opcode **不能单独**把 canonical `leaf` 升格为 nested edge；
- 当前 materializer authority 下，合法 process-only `TriggerAbility` 必须以 materialized `leaf` 进入本卡正例；
- process-only contract 本身无效、effect 缺失/错配、source 不一致等，仍由既有 runtime-support contract fail-closed；
- 若 process-only task 与 canonical node identity 出现新的不一致形状，不得用“process-only”作为通用放行开关。

### 5.2 gameplay TriggerAbility 的 nested identity 不得放宽

对非 process-only / runtime gameplay task：

- `node.node_kind == "ability_call"` 与正式 `TriggerAbility` identity 必须继续严格一致；
- `TriggerAbility` 被错误物化为 leaf、普通 task 被错误物化为 ability_call，均必须 fail-closed；
- exact single ability reference、resolution status、linked phase/standalone identity、`nested_only` role、callback graph 唯一性、active-cycle 等既有检查全部保留；
- 不允许按 opcode 名、角色 ID、source path、固定 action、当前 blocker 列表或 validator 样例建立例外表。

### 5.3 A1 其他 admission 边界不变

不得改变：

- action ownership / `ActionAdmissionIR`；
- submission mode / window；
- target selection context 与 authorization seal；
- lifecycle / control / resource / binding / event gates；
- formal action-root graph closure；
- unrelated bound nested/standalone exclusion规则；
- reachable deferred / unsupported / unresolved gameplay blocker；
- `external_legacy` 现有 flat gate。

### 5.4 本卡不执行 runtime

ActionContract 仍是 static support/admission projection：不得执行 graph、条件、效果、RNG 或 mutation，不得新增第二个 graph walker。

## 6. 明确不做 / deferred

本卡禁止：

- 修改 `tbgd/task_graph_materializer.py` 来把 process-only `TriggerAbility` 重新标成 `ability_call`；
- 修改 lowering/source contract、A2-P0/A2-P1 accepted authority；
- 修改 `systems/ability_task_contract.py` 或放宽 process-only exact source/effect contract；
- 修改 `AbilityTaskSystem` / `TaskGraphExecutor` / event/status transport；
- 实现 `hit_random_sequence`、RandomConfig caller/RNG ledger、projectile、barrier、parallel、sequence-select；
- 实现 S11 damage/heal/shield 或其他 P9 downstream domain；
- 为 PR #11 提供 synthetic status、伪造 authorization、直接调用 StatusCallbackSystem 或降低真实 Direct；
- 闭合 `insert_window` caller；
- 修改或恢复 PR #11 / PR #9 分支；
- 新依赖、付费/self-hosted runner、secret 或扩大 workflow 权限；
- full/canonical 全量构建作为常规完成门。

## 7. 最小完整纵切

EXEC 先形成以下最小生产修改，不要先扩 validator：

1. 保留现有 node/task/materialization/runtime-support 验证顺序；
2. 只修正 process-only task 通过 support contract 后的 nested-edge identity 判定；
3. process-only `TriggerAbility` canonical leaf 不进入 nested reference/graph traversal；
4. non-process-only gameplay `TriggerAbility` 的 `ability_call` + exact reference/link/nested graph 规则原样保持；
5. 其它 blocker provenance、reachable task identity 与 graph root identity不得因本卡被重排或删除。

如果实现需要第二个 production 文件，立即 `NEEDS_REPLAN`；不得把“方便统一”作为扩大 authority 的理由。

## 8. Fast

新增聚焦 validator：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p2_process_only_trigger_ability_admission_identity.py
```

Fast 必须直接调用当前生产 `_formal_action_task_graph_projection(...)` / `ActionContractSystem` 所依赖的真实类型，不复制 admission 实现。至少证明：

1. valid process-only `TriggerAbility` + canonical materialized `leaf`：不再产生 `ability_task_graph_nested_identity_mismatch`，不解析/执行 nested ability；
2. 同形状 process-only task 的 source/effect/process-only contract 无效：仍由既有 `ability_task_runtime_blocked_reason(...)` fail-closed；
3. non-process-only `TriggerAbility` + `leaf`：仍产生 nested identity blocker；
4. non-process-only 普通 task + `ability_call`：仍产生 nested identity blocker；
5. 合法 gameplay `TriggerAbility` + `ability_call`：仍必须通过 exact single ability reference、linked identity、`nested_only` graph；nested graph 内 blocker 仍能阻断 outer action；
6. missing/ambiguous/unresolved ability reference、linked phase/standalone mismatch 仍 fail-closed；
7. reachable deferred/unsupported gameplay node blocker不变；
8. process-only leaf 不因 unresolved audit-only reference被额外拒绝，但 invalid process-only contract不能借此放行；
9. repeated projection 的 root graph IDs、reachable task IDs、excluded task IDs、blocker provenance 顺序稳定；
10. admission 期间无 state mutation、RNG draw、condition evaluation、graph execution或 effect execution；
11. 既有 A1 focused Fast regression保持通过，尤其 `reachable_trigger_nested_blocker_preserved`、cycle、deferred、unresolved gameplay reference、external-legacy、process-only invalid contract 等边界。

建议 Fast 命令：

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p2_process_only_trigger_ability_admission_identity.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_a2_p2_process_only_trigger_ability_admission_identity --fast

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --fast
```

## 9. STRICT Direct — merged-master real-source blocker delta

Direct 只证明本卡的 A1 admission authority；它**不是** PR #11 的 runtime Direct 替代品。

必须从 pinned TBGD + current merged production lowering/action-definition/formal graph/materializer 动态选择真实 formal ordinary action，不得导入 PR #11/PR #9 未合并代码，不得把 `avatar_skill:100101` 或任何角色 ID 写成唯一 denominator。

Direct 必须：

1. 重新得到至少一个 normal `external_turn` candidate，且通过现有 production action definition、target query/accept、ActionAdmission 与 formal action-root graph projection；
2. 在 fixed base `f6ea5d2e...` 的 blocker provenance 中，证明 `ability_task_graph_nested_identity_mismatch` 对应的 reachable task 是：
   - `opcode == TriggerAbility`；
   - `execution_mode == process_only`；
   - canonical graph node 为 materialized `leaf`；
   - 既有 process-only source/effect contract 本身可通过；
3. 不用固定样例替代 denominator；输出本轮扫描的 candidate/occurrence counts、selected representative、task/node/source identity 与 provenance；
4. 修改后只移除由上述 process-only-leaf 矛盾产生的 nested-identity provenance；
5. root graph IDs、reachable task IDs、excluded bound task IDs 与所有非本卡 blocker provenance保持一致；
6. `ActionContractSystem.evaluate(...)` 仍因其它真实 future-domain blocker fail-closed 时，明确报告为 expected，而不是伪造 success；
7. 对真实 non-process-only `TriggerAbility -> ability_call -> nested_only` reachable edge，现有 nested identity/ref/link/graph fail-closed 契约不变；若当前 denominator 有该类正例/负例，纳入 regression；
8. runtime mutation count、RNG draw count、graph execution count均为 0；
9. 不运行 `CombatExecutor.execute(ActionCommand)` 来冒充本 predecessor 的 completion；PR #11 合并前仍必须原样运行其真实 Direct。

推荐 Direct 命令：

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_a2_p2_process_only_trigger_ability_admission_identity --direct

git diff --check f6ea5d2e2d067cb8cecb82bb28faf14beb2a29b4...HEAD
```

若 current real Direct 证明 nested-identity provenance 并非 process-only `TriggerAbility` leaf，或必须修改 materializer/lowering/runtime 才能解释，立即 `NEEDS_REPLAN`；不得根据本卡假设强行修 ActionContract。

## 10. CI / 资源预算

新增本 PR 专用 read-only workflow：

```text
.github/workflows/p9-a2-p2-pr-validation.yml
```

要求：

- GitHub-hosted `ubuntu-latest`；
- `permissions: contents: read`；
- exact PR-head checkout，`fetch-depth: 0`，recursive submodule，`persist-credentials: false`；
- 显式打印并断言 expected/actual head 与 pinned submodule；
- scoped compile；
- P2 Fast；
- A1 Fast regression；
- P2 real-source Direct；
- fixed-base `git diff --check`；
- 不运行 full / Node / package install / 新环境搭建。

预算：

```text
Fast <= 30 s
Direct target <= 120 s
peak RSS <= 1 GiB
workflow timeout <= 20 min
artifact/output <= 10 MiB
```

达到约 70% 预算时先收窄 source/action candidate discovery；不得通过增加缓存框架、CLI mode 或降低 Direct 语义绕过预算。

## 11. 生产完成条件

只有全部满足才可 `ready_for_review`：

- production diff 只有 `systems/action_contract.py`；
- valid process-only `TriggerAbility` canonical leaf 不再被 opcode-only nested-edge inference 拒绝；
- process-only source/effect contract、materialized node identity与 fail-closed 仍严格；
- gameplay `TriggerAbility` 的 canonical `ability_call` / reference / linked phase / nested graph contract未放宽；
- current merged-source Direct 动态复现 fixed-base nested-identity root cause并证明修改后只移除本卡 provenance；
- 其它 S8C/S11/future-domain blockers完整保留；
- admission 无 state/RNG/mutation/graph/effect execution；
- P2 Fast、A1 Fast regression、P2 Direct、compile、diff check 全绿；
- final committed-head hosted CI 全绿；
- execution report记录 exact final head、changed paths、真实 denominator/provenance delta、命令/结果、CI run、资源、remaining blockers；
- PR #11 仍保持 paused，未用其未合并代码作为完成证据。

完成 P2 **不代表** PR #11 可以自动恢复。REVIEW accepted+squash merge 后，下一轮 PLAN 必须从新的 merged master 再次运行 same-owner outer-action blocker attribution；只有 predecessor 链清空后，才更新现有 PR #11 并原样重跑其 Fast + 真实 `CombatExecutor.execute(ActionCommand)` Direct。

## 12. 停止条件

### `NEEDS_REPLAN`

出现任一项立即停止并在本 PR 记录精确证据：

- current real provenance 不是 process-only `TriggerAbility` canonical leaf；
- 修复必须改第二个 production 文件；
- 必须修改 materializer、lowering、AbilityTaskSystem、TaskGraphExecutor 或 process-only contract；
- 实际需要闭合 S8C/S11/insert-window/其他独立 consumer 才能完成本卡；
- 发现第二个独立 authority blocker被误打包进本卡；
- Direct 无法从 current merged source得到非空真实 denominator。

### `NEEDS_DECISION`

出现任一项需要用户裁决：

- 需要改变 process-only 的公共语义，使其实际触发 nested ability；
- 需要改变 TaskGraph node-kind/public IR/continuation 语义；
- 新依赖、付费 runner、secret、扩大 workflow 权限或显著增加成本；
- 需要降低 PR #11 的真实 Direct / A1 fail-closed 边界。

普通 validator、测试、workflow、CI、GitHub-hosted runner 排障由 EXEC 自行处理，不得据此 `NEEDS_REPLAN`。
