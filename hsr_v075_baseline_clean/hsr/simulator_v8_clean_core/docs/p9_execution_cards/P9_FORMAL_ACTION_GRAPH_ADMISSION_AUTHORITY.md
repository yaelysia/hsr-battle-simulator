# P9 Formal Action Graph Admission Authority

- stage: `P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY`
- mode: `STRICT`
- status: `ready_for_execution`
- planning base: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- route: `PR9 R2 Route A / dependency-first`
- prerequisite for: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER` (PR #9)
- dependency order: `A1 this card -> A2 action-window status/nested-ability transport -> resume PR #9`

## Why this prerequisite exists

PR #9 must retain its original mandatory real `CombatExecutor.execute(ActionCommand)` Direct. R2 planning proved that continuing to patch PR #9 gate-by-gate would mix unrelated deferred semantics and orchestration authorities into the RandomConfig caller card. The user therefore approved Route A: preserve PR #9 and its existing work, close independently mergeable prerequisites from merged `master`, then resume PR #9 without lowering Direct.

This card is the first prerequisite and is intentionally independent of all unmerged PR #9 commits.

### Authority audit from merged master

At `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`:

1. `ActionContractSystem.evaluate(...)` obtains the flat `ability_tasks_for_action(...)` set, calls `ability_task_runtime_blocked_reason(...)` for every bound task, and separately calls `_formal_action_task_graph_blocked_reasons(...)`.
2. `_formal_action_task_graph_blocked_reasons(...)` currently groups not only `action_root` but also `nested_only`, `standalone_root`, and `unbound_definition` phases and requires a formal graph for each group. It does not model the actual action-root execution closure.
3. `AbilityTaskSystem` formal action runtime does not execute that flat set. It starts only the existing admitted formal action roots and enters a `nested_only` phase only when an actually reachable formal `TriggerAbility` graph node resolves to that nested phase.
4. `TaskGraphExecutor` owns formal topology. It walks from `TaskGraphIR.root_node_ids`, follows branch children, and resolves nested graphs through the existing graph hook. A deferred node fails closed before its gameplay hook executes.
5. A formal process-only task is intentionally different from a gameplay task: the materializer can represent it as a materialized leaf while an audit-only definition reference remains unresolved, and `AbilityTaskSystem` intentionally does not reject unresolved graph references for `is_process_only_ability_task(...)`; it emits an audit/process record with no gameplay mutation. Therefore `TaskGraphIR.coverage_status == "lowered"` is **not** a correct one-line action-admission predicate.
6. The current flat action preflight is therefore broader than the actual formal action execution authority and can reject an action because of a bound definition that is not structurally reachable from any action root, or because a process-only audit reference is treated differently from the formal runtime path.

The correction must not replace this with a permissive shortcut. Formal action admission must become a deterministic, fail-closed projection of the actual formal task-graph execution closure.

## Route A dependency audit beyond this card

The second prerequisite is deliberately **not** included here.

Merged-master facts for A2:

- `EventDispatchSystem.dispatch_event(...)` already transports an optional `TaskGraphContinuation` together with optional `TaskGraphExecutionHooks`, and explicitly rejects hooks without a continuation (`task_graph_event_hooks_without_continuation`).
- Listener dispatch passes those values into `StatusCallbackSystem.execute(...)`; that system has the same paired transport invariant.
- `StatusCallbackSystem` already executes formal status callback task-graph roots and can route a child graph whose `entry_kind == "ability_phase_callback"` to supplied `nested_ability_hooks`.
- `TaskGraphExecutionHooks` on merged master already includes `weighted_selection`, but `StatusCallbackSystem._formal_status_hooks(...)` does not currently compose/route that channel.
- The top-level action-window path `CombatExecutor -> EventDispatchSystem.dispatch_action_window(...)` has no continuation/hooks input, so a status callback entered from a normal action window has no legal parent task-graph invocation context to carry into a nested formal ability.

A2 must therefore be planned after A1 as its own STRICT prerequisite around **action-window status callback -> nested formal ability transport/routing**. It may not be silently implemented in this card. PR #9 remains paused until A1 and A2 are accepted and merged.

## Goal

Make formal action submission use one coherent admission authority:

`action admission / target-selection context -> ActionContractSystem -> formal action-root task-graph closure -> existing static runtime-support checks`

For a formal task-graph action, the action contract must preflight exactly the statically possible formal execution closure beginning at the same action roots used by `AbilityTaskSystem`, conservatively including every structurally possible branch and every statically linked nested formal ability graph, while excluding bound phases/tasks that are not reachable from those roots.

This stage changes **admission projection only**. It does not execute an action, add gameplay semantics, materialize a new control family, or alter the shared task-graph executor.

## Authorities and allowed writes

### Required production write

Only one production file is authorized:

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py`

Any required production change outside that file is a planning boundary and must return `[NEEDS_REPLAN]`.

### Validation / evidence writes

2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py`
3. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9_FORMAL_ACTION_GRAPH_ADMISSION_AUTHORITY_execution_report.md`
4. `.github/workflows/p9-s8c1b-pr-validation.yml` — conditional CI-only reuse. Do not create a new workflow. If the existing workflow does not trigger for this card, minimally extend its path filter/compile/commands/timeout to run this validator **while retaining the existing accepted S8C1A/S8C1B regression commands** and its PR-base diff check.

Use only the normal GitHub-hosted runner. Do not add a paid/self-hosted runner or an unapproved dependency.

### Read-only authorities

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py` — existing task static runtime-support contract.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py` — actual formal action-root/nested ability runtime behavior; this stage must mirror it, not change it.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py` — only shared graph walker.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py` — formal graph/node/reference invariants.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py` — formal graph materialization authority.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py` — action transaction authority.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/event_dispatch.py` and `systems/status_callbacks.py` — A2 evidence only; no writes here.
- PR #9 branch and its unmerged files — evidence only. This prerequisite must build and validate from merged master without importing or cherry-picking PR #9 implementation.

## Required formal admission projection

### 1. Root set must match the formal action runtime

For formal/task-graph ownership, derive the root phases from the same existing phase facts used by `AbilityTaskSystem` formal action execution. Do not treat every phase returned by `ability_phases_for_action(...)` or every task returned by `ability_tasks_for_action(...)` as an action root.

The projection must distinguish at least:

- `action_root`: eligible formal roots when otherwise admitted by existing phase coverage/topology rules;
- `nested_only`: not a root; it enters the closure only through an admitted, structurally reachable formal nested-graph edge;
- `standalone_root` / `unbound_definition`: not part of ordinary action submission merely because they share an action/source definition;
- `external_legacy`: remains governed by the existing flat legacy task gate and must not be migrated by this card.

Do not broaden invocation roles or rewrite lowering data to make the projection easier.

### 2. Walk the static graph closure, not the flat task list

Starting from each admitted formal action root graph:

- resolve the exact existing `ability_phase_callback` graph identity through `RuleBook`;
- start from the graph's `root_node_ids`;
- follow all structural child edges that the shared executor could take. Admission is a support check, so every branch that could be selected at runtime is conservatively included; do **not** evaluate current-state branch predicates inside the action contract;
- for an admitted nested-graph node, follow only the existing explicit formal task link (`TriggerAbility` / linked ability phase identity) to the exact `nested_only` phase/callback graph that the current runtime graph hook would resolve;
- recursively continue with cycle/duplicate protection and stable deterministic ordering;
- never pull in a `nested_only` phase merely because it is present in `ability_tasks_for_action(...)`.

A missing/mismatched graph, formal task, phase, callback, owner, node identity, or nested link fails closed. Do not silently fall back to the flat formal task set.

### 3. Preflight must match static runtime support without becoming a second executor

This projection is an admission/support check only. It must not evaluate runtime conditions, choose branches, resolve RNG, mutate state, or manually execute nodes.

For every structurally reachable graph node:

- `materialization_status != "materialized"` is a real blocker; preserve the node's stable blocked/status reason when available;
- resolve the node's exact `formal_task_id` and verify phase/callback/graph identity;
- for a reachable **non-process-only** node, unresolved formal graph references remain fail-closed because the production runtime hook would require the referenced gameplay authority;
- for a reachable **process-only** task, mirror the existing formal runtime rule: validate its existing process-only/task contract with `ability_task_runtime_blocked_reason(..., topology_authority="task_graph")`, but do not reject it solely because an audit-only graph reference remains unresolved when `AbilityTaskSystem` would intentionally process it as a no-mutation audit record;
- for reachable gameplay leaf support, continue using the existing `ability_task_runtime_blocked_reason(..., topology_authority="task_graph")`; do not create a second opcode/effect/value-support table;
- formal control topology remains owned by `TaskGraphExecutor`; do not reimplement condition/branch/count/targets/graph execution in the action contract.

The resulting blocker set must be stable/deduplicated and source-auditable. Adding deterministic admission metadata for root graph IDs, reachable task IDs, excluded bound task IDs and blocker provenance is encouraged and may be required by the focused validator, but it must not become a gameplay input.

### 4. Preserve non-formal and upstream gates

This card must not bypass or weaken:

- action ownership / `ActionAdmissionIR` resolution;
- actual submission mode and allowed-window checks;
- actor lifecycle/control gates;
- target-selection-context identity or authorization seals;
- resource gates;
- action binding/action event admission;
- `external_legacy` task admission;
- any blocker belonging to a structurally reachable formal gameplay node.

A candidate that cannot satisfy target query/accept or upstream action admission is not valid Direct evidence for this card.

## Focused validator

Create `validate_p9_formal_action_graph_admission_authority.py` with `--fast` and `--direct`.

### `--fast`

Use bounded real production classes/IR, not a mock implementation of the action contract. Prove at minimum:

1. an `action_root` graph plus an unrelated bound `nested_only`/standalone definition with a legacy/static blocker: the unrelated definition is excluded from formal action admission;
2. a reachable `TriggerAbility -> nested_only` graph: the nested graph is included, and a blocker inside it still blocks;
3. a reachable deferred graph node blocks with stable provenance;
4. a reachable non-process-only node with an unresolved gameplay reference blocks;
5. a reachable process-only node with only an audit-only unresolved reference follows the existing formal runtime process-only rule and is not rejected solely for that reference;
6. a process-only task whose own existing process-only contract is invalid still blocks;
7. `external_legacy` tasks retain the existing flat admission behavior;
8. malformed/missing graph/task/phase/nested-link identity fails closed;
9. projection ordering/metadata are deterministic across repeated runs;
10. no state mutation, RNG decision, graph execution, or runtime branch evaluation occurs during admission.

### `--direct` — current real production denominator

Use the current TBGD submodule and existing merged production lowering/materialization path. Do not import any file from PR #9 and do not hard-code one action/character/path as the only denominator.

Dynamically scan current real formal actions and select reproducible representatives that satisfy the normal action ownership/admission and target query/accept path. Direct must show:

- at least one real formal action where the flat bound-task set is strictly broader than the action-root graph closure and contains one or more blocker-bearing tasks outside that closure; report the action/level, root phase/callback/graph IDs, excluded phase/task IDs and the old flat-only blocker evidence;
- after the new authority is used, those **out-of-closure only** blockers do not appear in `ActionContractSystem.evaluate(...)`;
- every blocker belonging to the selected action's structurally reachable formal closure remains present/fail-closed; Direct must include a real reachable-blocker representative when the first representative becomes otherwise clean;
- all graph roots/nested links are discovered from current production IR and exact identities, not from a hand-written list;
- action selection is performed through the existing `ActionTargetSelectionSystem.query(...)` / `accept(...)` path (or the exact current public equivalent) before evaluating the action contract; do not forge a selection fingerprint or bypass admission;
- an `external_legacy` representative/regression remains unchanged when one is present in the current denominator;
- output includes source/action identity, phase invocation roles, graph IDs, root node IDs, reachable task IDs, excluded bound task IDs, blocker provenance, target/admission status and the before-vs-after projection delta so REVIEW can reproduce it.

The Direct success condition is **correct action admission projection**, not a full successful `CombatExecutor` transaction. That full transaction remains the unchanged PR #9 Direct after A1 and A2 merge. This is not a Direct downgrade: it is a separate prerequisite with a different authority boundary.

If no current real formal action demonstrates a strict flat-set-vs-root-closure delta, or if proving the delta requires PR #9/unmerged code, stop with `[NEEDS_REPLAN]`; do not replace Direct with synthetic-only evidence.

## Acceptance commands

Run from repository root. `--direct` and the S8C1B regression require the TBGD submodule.

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/action_contract.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_formal_action_graph_admission_authority.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --fast

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_formal_action_graph_admission_authority --direct

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --direct

git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce...HEAD
```

Fast should remain bounded to about 30 seconds. Direct should use bounded discovery and target <= 120 seconds where practical; if current signed-source scanning needs a larger existing accepted budget, adjust only the reused workflow timeout with measured evidence. Keep peak memory <= 1 GiB.

## Success criteria

EXEC may hand off only when all are true:

- production diff for this prerequisite is confined to `systems/action_contract.py`;
- formal action admission begins from the same action-root role/coverage/topology facts as the current formal ability runtime;
- nested-only formal phases enter admission only through exact reachable graph links;
- unrelated bound nested/standalone/unbound definitions no longer block an ordinary action solely because they share the flat action task set;
- every structurally reachable possible branch remains conservatively preflighted;
- reachable deferred nodes, unresolved gameplay references, malformed identities and existing gameplay task-support blockers remain fail-closed;
- process-only behavior matches the existing formal runtime distinction and does not turn an unresolved audit-only reference into a false gameplay blocker;
- `external_legacy`, ownership/window/lifecycle/control/resource/binding/event/target-selection gates are unchanged;
- no task-graph walker, condition evaluator, RNG selector, mutation path or new support table is added to the action contract;
- new Fast and Direct are green, accepted S8C1B Direct is green, compile/diff checks are green, and final-head hosted-runner CI is green;
- execution report records exact final head, changed files, commands/results, CI run, real-source denominator, old flat projection vs new graph-closure evidence, preserved reachable blockers, deferred A2/PR9 work and `next=REVIEW`;
- EXEC posts `[HANDOFF:REVIEW]` and does not update P9 acceptance checklist/checkpoints or merge.

## Deferred / non-goals

Do not pull into this prerequisite:

- A2 action-window status callback -> nested formal ability continuation/hook transport or status hook composition;
- any `StatusCallbackSystem` RandomConfig/RNG implementation;
- PR #9 `AbilityTaskSystem` weighted-selection caller, RandomConfig materializer admission, RNG ledger Direct or validator changes;
- task-graph IR/executor/materializer changes;
- new control-flow families or broad `p9_s8c` completion;
- action target-relation lowering;
- projectile/flight/hit identity, target iteration or multi-hit;
- wait/barrier/custom-sync/timeline semantics;
- parallel/deterministic merge;
- sequence-select/target-cursor/random-target siblings;
- resource formula families such as unrelated `AddRatio` work;
- S8C aggregate acceptance, P9-S5D2 replay recheck, or S9+.

## Stop conditions

Return `[NEEDS_REPLAN]` rather than expanding scope if any of the following is required:

- a second production file outside `systems/action_contract.py`;
- changing `AbilityTaskSystem`, `TaskGraphExecutor`, task-graph IR/materializer, RuleBook storage semantics, event/status transport, RNG, or `CombatExecutor`;
- evaluating runtime branch predicates in the action contract to make Direct pass;
- admitting a nested phase without an exact existing formal graph link;
- bypassing target selection, ownership/window/resource admission, or an actually reachable gameplay blocker;
- using PR #9 unmerged code as a runtime dependency;
- a new dependency, paid/self-hosted runner, or another workflow.

`[BLOCKED]` is only for a genuine external/environmental obstacle that does not invalidate this plan. Ordinary implementation, validator and CI defects stay with EXEC.

## Handoff / acceptance protocol

A fresh EXEC implements this card on this prerequisite PR only. Preserve merged-master behavior outside the authorized authority change. On completion, post a top-level `[HANDOFF:REVIEW]` with `role=EXEC`, `status=ready_for_review`, stage, planning base, final head, changed files, exact Fast/Direct/regression results, hosted CI run, real denominator/projection delta, remaining/deferred, and `next=REVIEW`; then mark the PR ready for review.

A fresh REVIEW independently reproduces the critical projection and Direct evidence. Ordinary implementation/validation defects -> `[RETURN_FOR_FIX]`; a real authority/scope defect -> `[NEEDS_REPLAN]`. On acceptance REVIEW records the prerequisite checkpoint/governance as appropriate, verifies final-head CI, and squash-merges.

Only after this prerequisite is accepted and merged should PLAN create A2 from the new merged master. PR #9 remains Draft/paused until both A1 and A2 are merged; then PR #9 is reconciled onto the new master and its original real `CombatExecutor.execute(ActionCommand)` Direct resumes unchanged.