# P9-A2-P1 Formal process-only task/effect source identity closure

## 0. 执行身份与路线

- dispatch id: `PR11-PLAN-ROUTE-A-5584645322`
- risk mode: `STRICT`
- exact base: `master@770a0649926932794585fcd30589c6776892bc3b`
- target: 本独立 predecessor PR；从 merged master 起步，**不依赖 PR #11 / PR #9 未合并代码**。
- approved route A: 用户已批准把“独立于 A2、直接解除 same-owner outer-action formal gate 的最早单一 authority 前置”逐张独立 STRICT PR 前移；不得把 S8C、S11 或其他责任域打包进本卡。
- downstream order: `A2-P1 -> 后续仍被真实 same-owner formal gate 暴露的下一单一-authority predecessor（如有） -> PR #11/A2 -> PR #9`。

本卡只修一个 merged-master 已存在的 formal-source identity 回归。PR #11 保持 Draft/暂停并保留既有 A2 runtime 实现；本卡不修改或验证其 action-window nested-ability transport。

## 1. 为什么这是第一张 predecessor

PR #11 exact-head run `34220340830` / job `102041714918` 已证明：scoped compile 与 A2 Fast 通过，但 same-owner basic / skill / ultimate 在进入任何 A2 action-window listener 前，都被现有 A1 `ActionContractSystem` 的正式 action-root 图支持投影阻断。其中三个真实 outer-action family 都出现：

```text
process_only_task_effect_source_mismatch
```

这不是 S8C/S11 语义本身，也不是 A2 transport 缺陷。merged master 的生产链已经能解释该 blocker 的确定性来源：

```text
TBGDLowering._lower_ability_task_tree(...)
  -> 为 task 与 EffectIR 生成同一初始 IRSource
  -> formal lowering 进入 TBGDLowering._lower_formal_ability_task_tree(...)
  -> parent task source 去除 parent_task_id / child_task_count 旧拓扑 evidence
  -> EffectIR.source 仍保留原 source
  -> ability_task_runtime_blocked_reason(... topology_authority="task_graph")
  -> process-only contract 要求 effect.source == task.source
  -> process_only_task_effect_source_mismatch
  -> A1 ActionContract fail-closed
```

现行 A1 已验收契约明确要求：process-only task 自身 contract 无效时仍必须阻断；因此不能在 `systems/action_contract.py` 或 `systems/ability_task_contract.py` 放宽该检查。正确修复点是更早的 formal lowering source identity，让同一 formal process-only task 与其 effect 从生产构造起共享同一 canonical source identity。

该修复独立于：

- S8C `hit_random_sequence` / barrier / RandomConfig caller；
- S11 damage/heal/shield；
- S9-S17 其他 future domain；
- A2 action-window status -> nested ability transport；
- PR #9 RandomConfig caller/RNG/RNGEvent/whole-action ledger。

因此它满足方案 A 的“最早、单一 authority、可独立合并”条件。

## 2. 唯一生产 authority

唯一生产 authority：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
```

精确起始符号：

```text
TBGDLowering._lower_ability_task_tree
TBGDLowering._lower_formal_ability_task_tree
```

只允许修复 **formal ability task 与该 task 自有 EffectIR 的 canonical IRSource identity 一致性**。不得新增 opcode 语义、不得改变 action admission 规则、不得把 deferred gameplay domain 改成 executable。

现有只读消费者/权威：

```text
systems/ability_task_contract.py::ability_task_runtime_blocked_reason
systems/action_contract.py::_formal_action_task_graph_projection
systems/action_contract.py::ActionContractSystem.evaluate
tbgd/task_graph_materializer.py
rules/task_graph.py
```

这些文件不属于本卡生产写集合。

## 3. 来源分母与闭合地图

STRICT denominator 从当前 pinned TBGD `14c1d18f91a8101d610e6c523447a7517de3fae1` 和 merged-master character formal lowering 动态得到，不按角色名、技能 ID、固定文件名选样。

分母定义：

1. 当前 P9 character formal `ability_phase_callback` 来源中，`execution_mode == "process_only"` 的 `AbilityTaskIR`；
2. task 具有非空 `effect_id` 且对应唯一 `EffectIR`；
3. task/effect 均来自同一 raw task occurrence；
4. formal lowering 对 task source 做过 canonical topology-evidence normalization；
5. 记录 task source、effect source、source path/json path/raw opcode/content fingerprint 与 mismatch 状态。

完成后必须满足：

```text
formal_process_only_task_effect_pair_count > 0
formal_process_only_task_effect_source_mismatch_count == 0
```

同时必须证明非 process-only gameplay task、status callback task、外部内容域与 source fingerprint 不被本卡重解释。

## 4. 允许写集合

生产仅允许：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
```

验证/报告/CI 仅允许：

```text
hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_a2_p1_formal_process_only_source_identity.py
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-A2-P1_FORMAL_PROCESS_ONLY_SOURCE_IDENTITY_execution_report.md
.github/workflows/p9-a2-p1-pr-validation.yml
```

规划卡本身允许保留本文件。

显式禁止修改：

```text
systems/action_contract.py
systems/ability_task_contract.py
systems/task_graph.py
systems/ability.py
core/executor.py
tbgd/task_graph_materializer.py
rules/**
PR #11 branch/files
PR #9 branch/unmerged files
```

若必须修改上述生产域才能消除 source mismatch，立即 `[NEEDS_REPLAN]`。

## 5. 生产实现要求

1. canonical source identity 必须由真实 formal raw occurrence/source context 派生，不能按 opcode、角色、技能、task ID 特判。
2. 当 formal parent task source 去除旧拓扑 evidence 时，同一 task 自有 `EffectIR.source` 必须同步到同一 canonical source；不得用 `source_trace` 或验证器后处理替代生产 IR 修复。
3. source path、raw type/id、json path、source opcode、content fingerprint 等来源事实不得丢失或伪造。
4. 不改变 `effect_id` / `task_id`、execution mode、coverage status、materialization status、downstream owner domains 或 task-graph topology。
5. 不把 `task_graph_control_requires_domains:*`、`effect_coverage_status:*`、`ability_task_graph_nested_identity_mismatch` 等**其他真实 blocker**顺手清掉；这些由后续 Route-A predecessor 各自归责。
6. non-formal/external-content lowering 行为不变。
7. 失败或来源冲突必须 fail-closed；本卡不产生 battle mutation/event/RNG。

## 6. Fast

从 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core` 运行：

```text
python -m compileall tbgd/lowering.py tools/validate_p9_a2_p1_formal_process_only_source_identity.py
python tools/validate_p9_a2_p1_formal_process_only_source_identity.py --fast
git diff --check 770a0649926932794585fcd30589c6776892bc3b HEAD
```

Fast 至少覆盖：

- formal process-only task/effect 初始同源，task canonicalization 后 effect 同步保持 exact source equality；
- 非 process-only pair 不被改写；
- 不同 raw occurrence 不会因相同 opcode/effect shape 被错误合并；
- source path/json path/fingerprint 冲突 fail-closed；
- task/effect identity 不变；
- no state mutation / RNG / event execution；
- A1 process-only contract 的 valid/invalid 最小负例仍保持：合法 pair 不因 source mismatch 被拒，真实无效 contract 仍阻断。

## 7. STRICT Direct

```text
python tools/validate_p9_a2_p1_formal_process_only_source_identity.py --direct
```

Direct 必须使用 pinned TBGD + merged-master production character formal lowering/materialization；不读取 PR #11/PR #9 实现，不手工 replace task/effect/source。

必须动态证明：

1. 修改前语义基线存在至少一个真实 formal process-only task/effect pair，其 mismatch 可由“task source canonicalized、effect source 未同步”唯一解释；
2. 修改后完整 scoped denominator 中 `process_only_task_effect_source_mismatch_count == 0`；
3. 选取 current same-owner ordinary action representative 时，通过生产 target query/accept + 现有 A1 `ActionContractSystem.evaluate(...)` 重新计算 blocker provenance；`process_only_task_effect_source_mismatch` 从该 action 的 reachable formal blocker 集消失；
4. 该 action 上仍属于 S8C/S11/其他 future-domain 的 blocker 必须原样保留并继续 fail-closed；**本卡 Direct 不要求 action 成为 executable**；
5. `ActionContractSystem`、task-graph materializer/runtime、A2 transport、RNG 均零生产改动；
6. full Canonical IR build 不是必要条件，优先沿既有 character focused production projection；不得为验证方便制造 synthetic gameplay world。

推荐将 PR #11 run `34220340830` 的 same-owner blocker family 作为复核导航，但正式 denominator/representative 必须从当前 merged production source 动态发现，不能硬编码 Silver Wolf/`1100601`/`1100602`/`1100603`。

## 8. 回归与负例

必须证明：

```text
a1_authority_changed=false
formal_task_graph_topology_changed=false
process_only_contract_weakened=false
future_domain_blockers_removed_count=0
non_process_only_effect_source_rewritten_count=0
pr11_code_used=false
pr9_unmerged_code_used=false
runtime_mutation_count=0
runtime_rng_draw_count=0
```

若 source mismatch 实际是公共 IRSource equality 语义需要改变，而非 lowering 构造不一致，属于 authority/public semantics 变化，停止并 `[NEEDS_DECISION]`，不得改 equality 契约。

## 9. CI

允许新增本 PR 专用 read-only workflow：

```text
.github/workflows/p9-a2-p1-pr-validation.yml
```

要求：

- GitHub-hosted free runner；
- `permissions: contents: read`；
- checkout exact PR head + pinned submodule；
- scoped compile -> Fast -> Direct -> fixed-base `git diff --check`；
- 不在 workflow 运行时 patch validator/生产代码；
- 不新增依赖、不扩大权限、不使用付费/self-hosted runner。

最终验收只认最终 committed head 的实际 CI。

## 10. 完成条件

```text
exact_base_is_770a0649926932794585fcd30589c6776892bc3b=true
production_write_authority_is_lowering_only=true
formal_process_only_pair_denominator_nonempty=true
formal_process_only_task_effect_source_mismatch_count=0
same_owner_a1_process_only_mismatch_blocker_removed=true
other_reachable_blockers_preserved=true
process_only_contract_weakened=false
a1_authority_changed=false
task_graph_materializer_changed=false
runtime_changed=false
pr11_code_used=false
pr9_unmerged_code_used=false
fast_pass=true
direct_pass=true
git_diff_check_pass=true
ci_pass=true
execution_report_complete=true
```

只有这些成立，EXEC 才可 `[HANDOFF:REVIEW]`。

本 PR accepted+merged 后，PLAN 必须从新的 merged master 重新运行 same-owner outer-action formal blocker attribution。若仍有阻断，只按**下一最早单一 authority**再创建一张独立 predecessor；不得预先把 S8C/S11 多域塞进本卡。

## 11. Stop conditions

`[NEEDS_REPLAN]`：

- 消除 mismatch 必须修改 lowering 之外的生产 authority；
- mismatch 并非 formal task/effect source canonicalization 导致；
- source identity 修复必然同时改变 task-graph materialization或领域语义；
- scoped real denominator 为空或无法从 merged master/pinned source复现。

`[NEEDS_DECISION]`：

- 需要改变公共 `IRSource` equality/source semantics；
- 需要扩大 GitHub 权限、新依赖、付费资源；
- 需要改变 A1 authority、真实 Direct 标准或用户已批准 Route-A 边界。

普通 validator/workflow/CI 工程问题由 EXEC 在允许写集合内自行处理。

## 12. 估时

- `exec_minutes=45`：生产修复限定一个 lowering authority，主要工作是 source-backed denominator、最小 canonicalization 修复、Fast/Direct 与最终 CI；预留普通 validator/CI 排障缓冲。
- `review_minutes=30`：REVIEW 需独立核 source equality 根因、真实 denominator、same-owner A1 blocker delta、其他 blocker 保留、固定 base 与 final-head CI。