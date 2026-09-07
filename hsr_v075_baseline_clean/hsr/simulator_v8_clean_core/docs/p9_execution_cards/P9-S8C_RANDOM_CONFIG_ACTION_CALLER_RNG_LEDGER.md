# P9-S8C RandomConfig Formal Action Caller / RNG Ledger

- stage: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER`
- parent: `P9-S8C`
- mode: `STRICT`
- status: `ready_for_execution`
- revision: `R1`
- planning base: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- R1 replan input head: `2c6cb7c44a6e9a4fde216631a653ad4f48ce18c9`
- R1 finding: `confirmed_planning_scope_omission`

## R1 finding disposition

EXEC correctly stopped at the original card boundary instead of weakening Direct evidence. Independent PLAN verification confirms the reported production boundary:

1. `tbgd/character_control_flow_contracts.py` assigns `RandomConfig.OddsList`, `RandomConfig.TaskList`, and the `random_branch` role to `p9_s8c`; the source contract therefore still carries the `hit_random_sequence` downstream obligation.
2. `tbgd/task_graph_materializer.py::_node_status(...)` turns a node with that open domain into `node_kind="deferred"`, `materialization_status="deferred"`, `owner_domains=("hit_random_sequence",)`.
3. `systems/task_graph.py::_TaskGraphRun.execute_node(...)` rejects a deferred node before branch dispatch, so a real formal action `RandomConfig` cannot reach the accepted S8C2 weighted-selection hook.
4. `core/executor.py` already carries `ability_task_rng_events` into the existing whole-action `validate_rng_choice_ledger(...)`; no new ledger authority is needed.
5. The green EXEC CI run `34088147702` proves the new ability hook and existing RNG authority work on synthetic/materialized runtime fixtures and separately proves a real signed-source RandomConfig is discoverable, but it does **not** satisfy this card's required real `CombatExecutor.execute(ActionCommand)` Direct route.

This is a missing prerequisite in the original PLAN write set, not an ordinary `ability.py` implementation or validator issue. R1 therefore preserves all existing PR work and adds only the minimum materializer authority needed to make the action-side formal RandomConfig position executable.

## Fixed facts and guardrails

- PR #5 / P9-S8C2 is accepted and squash-merged as `b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`; final CI run `34083526427` succeeded.
- The unique P9 checklist has S8C2 checked, while parent S8C remains unchecked.
- S8C2 remains the only shared task-graph walker / weighted-selection contract. This card must not add another walker.
- `systems/rng.py` remains the only RNG request/choice/event authority. This card must not add another RNG implementation.
- `core/executor.py` remains the existing whole-action RNG-ledger authority and is read-only in this stage.
- Existing EXEC changes in `systems/ability.py`, the focused validator, reused workflow, and execution report are retained and amended rather than reset.
- `StatusCallbackSystem` remains a second independent production consumer and is not admitted by R1.
- **Do not add `p9_s8c` to `character_control_flow_contracts.py::_COMPLETED_OWNERS` and do not globally reclassify `p9_s8c` as closed.** The same stage owns projectile, wait/barrier, parallel and other still-deferred S8C families; a global completion switch would incorrectly unlock sibling domains.

No successor number is invented. The descriptive stage key remains unchanged.

## Goal

Close one minimal complete production vertical slice:

`CombatExecutor.execute(ActionCommand)` -> real formal `ability_phase_callback` -> `AbilityTaskSystem` -> existing shared `TaskGraphExecutor` -> accepted S8C2 `weighted_selection` -> existing `resolve_rng_request(...)` -> exactly one selected RandomConfig child / RNG event -> existing ability-task event return -> existing whole-action RNG-ledger validation.

A dynamically discovered current formal **action** RandomConfig must execute through that exact production route with accepted formal dynamic weights, stable choice/event identity, selected-child-only semantics, replay/explicit-ledger consumption, and fail-closed stale/tampered evidence.

## Authorities and allowed writes

### Read-only authorities

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_control_flow_contracts.py` — source classification and broad P9 ownership authority; R1 must not globally close `p9_s8c`.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py` — accepted task-graph / weighted-selection IR invariants.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/task_graph.py` — only shared graph walker / S8C2 selection executor contract.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/rng.py` — only RNG request/choice/event authority.
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py` — existing whole-action RNG-ledger validator.

### Production write set

Only these production files are authorized:

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py` — preserve/amend the existing EXEC action weighted-selection hook implementation.
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py` — **R1 prerequisite addition**: admit only action-entry RandomConfig formal positions into executable task-graph ownership, with matching source-disposition closure.

No other production file is authorized.

### Validation / evidence write set

3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c_random_config_action_caller.py`
4. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py` — minimal regression expectation update required because accepted S8C1B currently asserts the real action RandomConfig remains deferred.
5. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER_execution_report.md`
6. `.github/workflows/p9-s8c2-pr-validation.yml` — reuse the existing workflow only; minimal path/compile/command adaptation is allowed.

The accepted S8C1C validator is a read-only regression command in this card unless a validation-only compatibility defect is demonstrated. Any request to change its production/source denominator semantics is a new planning boundary.

Use only normal GitHub-hosted runners. No paid/self-hosted runner and no new dependency without approval.

## R1 prerequisite: action-only RandomConfig materializer admission

The materializer change must be narrowly scoped to the formal action consumer. It must **not** treat `hit_random_sequence` as globally completed.

### 1. Executable node kind

For a formally admitted RandomConfig position that passes the action-only admission below, materialize the existing `random_branch` control role as the existing executable task-graph `branch` kind so the shared executor reaches its already-accepted RandomConfig weighted-selection dispatch.

Do not add a RandomConfig walker or a new task-graph node kind.

### 2. Action-entry-only obligation retirement

The materializer may retire the `hit_random_sequence` obligation only when all of the following are true:

- the formal entry kind is exactly `ability_phase_callback`;
- the source control family is exactly `RandomConfig` / role `random_branch`;
- the node already has the accepted S8C1 weighted-selection attachment with exact branch/choice/weight/source identities;
- after already-closed domains are excluded, the only domain preventing execution is `hit_random_sequence` for this RandomConfig position;
- no unrelated deferred reference/termination/child-domain prerequisite is silently discarded.

For an admitted action RandomConfig node, the resulting formal graph must be consistent with the existing IR invariants: `node_kind="branch"`, `materialization_status="materialized"`, `owner_domains=("task_graph_execution",)`, and graph coverage must reflect only its remaining real obligations.

### 3. Matching source-disposition closure

`TaskGraphCatalogIR` requires node ownership to agree with the linked `TaskGraphSourceDispositionIR`; therefore R1 must also retire `hit_random_sequence` from the formal materialized source disposition for exactly the admitted action RandomConfig source record(s).

This retirement must be derived from the actual formal action materialization links, not from a global stage flag. It must preserve the complete source denominator and source fingerprints.

If one source record is shared in a way that cannot represent action-side retirement while a status/no-producer/sibling use still legitimately retains `hit_random_sequence`, fail closed and report `[NEEDS_REPLAN]`; do not globally erase the owner.

### 4. Required negative boundary

The focused validation must prove the R1 materializer change does **not** unlock:

- `status_callback` RandomConfig nodes: they remain `deferred / hit_random_sequence`;
- RandomConfig source records with `no_formal_producer`: they receive no synthetic entry/graph and retain their deferred owner;
- non-RandomConfig `p9_s8c` controls such as projectile, wait/barrier, parallel/template, target-cursor or other sibling families: their pre-existing deferred ownership remains unchanged.

The source-contract file remains read-only. A solution that adds `p9_s8c` to `_COMPLETED_OWNERS`, broadly adds `hit_random_sequence` to an already-closed-domain set, or otherwise changes the whole S8C denominator is out of scope.

## Action caller / RNG constraints

### 1. Preserve the shared executor as the only walker

Keep the existing PR implementation wiring `AbilityTaskSystem._formal_task_graph_hooks(...)` to S8C2's weighted-selection callback/result contract. Do not manually traverse RandomConfig children and do not duplicate executor identity checks. Only the child selected by `TaskGraphExecutor` may execute.

### 2. Resolve weights only from accepted formal IR

For each `TaskGraphWeightedSelectionIR`, resolve every choice's `weight_definition_id` through its accepted `numeric_definitions` using the existing formal ability numeric-evaluation context. Runtime must not reread raw TBGD `OddsList`/JSON.

Preserve choice order/ordinal plus exact `choice_id`, `graph_node_id`, `branch_id`, weight source and source fingerprint. Unresolved, non-finite or negative weights fail closed. Zero weights are legal only when total selectable weight is positive. Empty/all-zero/identity-incomplete selections fail closed without gameplay mutation.

### 3. Use the existing RNG authority and existing action metadata

Create one existing `RNGRequest` for one RandomConfig decision and resolve it through existing `resolve_rng_request(...)`. Consume existing `rng_choices` / `rng_mode` / ledger metadata plumbing. Outcomes map 1:1 to materialized weighted choices and retain exact formal choice identity.

Request identity must satisfy existing RNG completeness rules and distinguish repeated executions using existing action/task/graph/selection/invocation context. Derive choice/event keys with existing helpers; do not add another identity algorithm or RNG policy.

### 4. One decision, one event, existing whole-action ledger

Successful selection returns the accepted S8C2 result type with exact selection/graph/choice/ordinal/branch identity and exactly one corresponding RNG event. Let the existing task-graph/ability/action return path carry that event into the existing whole-action ledger validator. Do not append a second copy or add a second validator.

Invalid weights, malformed identity, missing/stale/tampered explicit choice, unsupported RNG mode or selection mismatch must block atomically with no RandomConfig child/effect mutation and no silent first-child/implicit-random fallback.

## Focused validator requirements

Amend `validate_p9_s8c_random_config_action_caller.py`; do not accept the current split proof (real source discovery + synthetic runtime) as Direct.

### `--fast`

Use real production `AbilityTaskSystem` + shared `TaskGraphExecutor` together and add a bounded materializer fixture proving the R1 admission boundary. Cover at least:

- action `RandomConfig` materializes as executable `branch / task_graph_execution` only under the R1 predicate;
- a comparable status RandomConfig remains `deferred / hit_random_sequence`;
- an unrelated non-RandomConfig `p9_s8c` control remains deferred;
- valid positive dynamic weights + supplied ledger branch -> exact S8C2 choice identity;
- exactly one admitted RNG event and selected-child-only execution;
- unresolved/non-finite/negative/all-zero weights and malformed/missing/stale/tampered explicit choices fail closed with unchanged gameplay state;
- repeated decision identity is stable and distinct when execution context is distinct;
- existing non-RandomConfig formal action behavior remains green.

### `--direct` — mandatory real end-to-end proof

Dynamically discover a current real formal action RandomConfig from the accepted source/action/materializer path. Do not hard-code a content ID, character, path, graph ID, phase ID or choice as the denominator.

Build/install the real production slice and execute the discovered action through **`CombatExecutor.execute(ActionCommand)`** with the normal existing action authorization/target-selection/preflight path. Calling the weighted hook directly, invoking `TaskGraphExecutor` directly, or combining a real materializer probe with a synthetic runtime graph does **not** satisfy Direct.

Direct must prove all of the following in one reproducible real route:

1. the discovered action RandomConfig source record and formal node are action-only materialized by R1 and reach the `AbilityTaskSystem` weighted-selection hook;
2. dynamic weights are evaluated from accepted formal numeric IR;
3. one valid existing RNG decision path selects exactly one formal child and emits exactly one complete/stable RandomConfig RNG event;
4. a complete explicit/replay ledger for the same real action is accepted by the existing whole-action `validate_rng_choice_ledger(...)`, with the RandomConfig choice key reported as consumed;
5. tampering/staling the RandomConfig key or choice in an otherwise complete required ledger causes the **same `CombatExecutor.execute(...)` route** to fail closed and leaves committed gameplay state unchanged;
6. the unselected RandomConfig children do not execute;
7. a real status RandomConfig remains deferred and no sibling S8C materializer domain is admitted;
8. output records the dynamically discovered source path/json path, action definition/level, phase/callback, graph/selection/choice identities, RNG choice key/event ID, whole-action consumed-ledger evidence, and the status/sibling deferral probes so REVIEW can reproduce it.

If the selected representative is blocked by an unrelated already-deferred sibling domain before reaching RandomConfig, dynamically try another current real formal action RandomConfig representative. If no current real action can reach RandomConfig without implementing another deferred domain, report `[NEEDS_REPLAN]`; do not add that sibling domain to this card and do not downgrade Direct.

## S8C1B / S8C1C regression handling

The accepted S8C1B Direct currently asserts `random_config_still_deferred=true`. R1 legitimately advances only the **action** runtime state, so EXEC may minimally update that validator to preserve all existing signed-source / OddsList / branch / weight-definition / choice-identity closure while expecting the real action representative to be materialized as an executable branch. It must additionally keep its status-side probe deferred. Do not delete or weaken source/identity checks.

Run the accepted S8C1C `--direct` unchanged as a source/formal-position denominator regression. Its source completeness and no-synthetic-producer claims must remain true.

## Acceptance commands

Run from repository root. Direct validation requires the TBGD submodule.

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c_random_config_action_caller.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c_random_config_action_caller --fast

python3 -m pytest -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_s8c2_random_config_runtime_executor.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c_random_config_action_caller --direct

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --direct

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --direct

git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce...HEAD
```

The focused Direct is the required runtime proof. S8C1B/S8C1C Direct are upstream/source-regression guards and do not substitute for it. Keep standard hosted-runner CI green at the final implementation head.

The reused `.github/workflows/p9-s8c2-pr-validation.yml` must minimally cover the new materializer path and these commands. It may adjust timeout/path filters/compile inputs accordingly, but must not create a duplicate workflow or add an unapproved dependency.

## Success criteria

EXEC may hand off only when all are true:

- a dynamically discovered real formal **action** RandomConfig is materialized through the R1 action-only materializer rule and executes through `CombatExecutor.execute(ActionCommand)` -> `AbilityTaskSystem` -> shared S8C2 executor;
- the admitted action node/source disposition are mutually consistent and no global `p9_s8c` completion shortcut exists;
- status RandomConfig, no-formal-producer RandomConfig and unrelated S8C families remain deferred/not synthesized as applicable;
- dynamic weights come from accepted formal numeric IR, not raw source payload at runtime;
- existing `systems/rng.py` is the only RNG decision authority;
- valid real explicit/replay ledger evidence selects the exact formal branch, produces exactly one stable/complete RNG event, and is consumed by the existing whole-action ledger;
- stale/tampered real ledger evidence fails closed through the same CombatExecutor route with committed gameplay state unchanged;
- only the selected child executes;
- existing non-RandomConfig behavior, S8C2 executor tests, S8C1B source closure and S8C1C source/formal-position closure remain green;
- new Fast/Direct, S8C1B Direct, S8C1C Direct, compile, diff check and PR CI are green;
- production diff for this stage is confined to `systems/ability.py` and `tbgd/task_graph_materializer.py`;
- no changes are made to `character_control_flow_contracts.py`, `rules/task_graph.py`, `systems/task_graph.py`, `systems/rng.py`, `core/executor.py`, or `StatusCallbackSystem` production authority;
- execution report + `[HANDOFF:REVIEW]` include final head, exact changed files/commands/results, CI run, dynamically discovered real source/action/denominator, materializer admission evidence, RNG identity/whole-action ledger evidence, negative deferral probes, deferred/remaining, and `next=REVIEW`;
- parent `P9-S8C` remains unchecked.

## Deferred / non-goals

Do not pull into this PR:

- formal `StatusCallbackSystem` RandomConfig/RNG-ledger caller integration or retirement of its legacy RandomConfig walker;
- global `p9_s8c` source-contract completion or changes to `_COMPLETED_OWNERS`;
- broad retirement of `hit_random_sequence` ownership outside the admitted formal action RandomConfig positions;
- changes to shared executor/weighted-selection IR, RNG policy or whole-action ledger authority;
- projectile/flight/hit identity, target iteration or multi-hit identity;
- wait/barrier/custom-sync semantics;
- parallel/deterministic merge;
- sequence-select/timeline-wait;
- target-cursor/random-target sibling semantics;
- S8C aggregate acceptance;
- P9-S5D2 replay recheck (after S8C aggregate);
- S9+;
- unrelated workflow cleanup/new dependencies/paid runners.

## Stop conditions

Post `[NEEDS_REPLAN]` rather than scope-creeping if:

- action-only RandomConfig materialization/source-disposition retirement cannot be represented in `tbgd/task_graph_materializer.py` without changing the broad source contract or shared task-graph IR/executor invariants;
- a source-record sharing pattern requires globally retiring `hit_random_sequence` for status/no-producer/sibling uses;
- stable RNG identity/weight evaluation cannot be achieved with the existing ability/RNG contracts;
- no current real formal action RandomConfig can complete the required CombatExecutor Direct without implementing another deferred S8C domain;
- another production authority outside the two authorized production files is required.

`[BLOCKED]` is only for external/environmental obstacles that do not invalidate the plan. Ordinary implementation/test/validator/CI defects remain EXEC responsibility.

## Handoff / acceptance protocol

EXEC continues on this same Draft PR/branch and **preserves the existing implementation**. Implement only the R1 prerequisite/amendments above, update the focused evidence/report/workflow as needed, and do not self-accept.

On completion, post a top-level `[HANDOFF:REVIEW]` containing `role=EXEC`, `status=ready_for_review`, this stage key, planning base, R1 execution-card head lineage, final head, changed files, exact validation results, CI run, real Direct source/action/materializer/RNG/ledger evidence, negative deferral evidence, deferred/remaining and `next=REVIEW`; then mark the PR ready for review.

A fresh REVIEW independently reproduces critical Fast/Direct evidence and audits the diff. Ordinary defects -> `[RETURN_FOR_FIX]` to EXEC; scope/authority/planning defects -> `[NEEDS_REPLAN]` to PLAN. On acceptance REVIEW updates this card, the unique P9 checklist (record this exact descriptive child as accepted but keep parent S8C unchecked) and `hsr/CODEX_HANDOFF.md`, verifies final-head CI success, then squash-merges with expected head SHA.

After acceptance, the next remaining S8C source must again be selected from repository facts; do not auto-close S8C.
