# P9-S8C RandomConfig Formal Action Caller / RNG Ledger

- stage: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER`
- parent: `P9-S8C`
- mode: `STRICT`
- status: `ready_for_execution`
- planning base: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`

## Fixed facts

- PR #5 / P9-S8C2 is accepted and squash-merged as `b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`; final CI run `34083526427` succeeded.
- The unique P9 checklist has S8C2 checked, while parent S8C remains unchecked.
- S8C2 already owns the shared `TaskGraphExecutor` weighted-selection hook/result contract, exact selection identity validation, selected-child-only traversal, and admission of one selection `RNGEvent`. It intentionally left real ability/status callers and RNG-ledger integration deferred.
- `AbilityTaskSystem` is a real formal `ability_phase_callback` consumer and currently builds task-graph hooks without the S8C2 weighted-selection hook.
- `StatusCallbackSystem` is a second independent formal consumer with separate hooks plus an older non-formal RandomConfig walker. Per workflow rules it is a separate STRICT stage, not part of this card.
- `systems/rng.py` is the existing RNG authority. `core/executor.py` already includes ability-task RNG events in whole-action `validate_rng_choice_ledger(...)`; this card must feed that authority, not replace it.
- No open PR for this same action-caller stage existed at planning time.

No successor number is invented: the checklist does not pre-authorize a numbered stage after S8C2, so this card uses the descriptive stage key above.

## Goal

Close one minimal complete production vertical slice:

`CombatExecutor.execute(ActionCommand)` -> formal ability phase dispatch -> `AbilityTaskSystem` -> existing shared `TaskGraphExecutor` -> S8C2 `weighted_selection` hook -> existing `resolve_rng_request(...)` -> exactly one selected RandomConfig child / RNG event -> existing ability-task event return -> existing whole-action RNG-ledger validation.

A current materialized formal action RandomConfig must therefore become executable with dynamic weights, stable choice identity, ledger/replay validation, selected-child-only semantics, and fail-closed invalid cases.

## Authorities and allowed writes

Read-only authorities to reuse:

- `simulator_v8_clean_core/systems/task_graph.py` — only graph walker / S8C2 selection contract;
- `simulator_v8_clean_core/rules/task_graph.py` — accepted weighted-selection IR and numeric definitions;
- `simulator_v8_clean_core/systems/rng.py` — only RNG request/choice/event authority;
- `simulator_v8_clean_core/core/executor.py` — existing whole-action RNG-ledger validator;
- existing S8C1 action-entry/materializer path — only formal source/materializer authority.

EXEC business/validation write set:

1. required production: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py`
2. required validator: `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c_random_config_action_caller.py`
3. required report: `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER_execution_report.md`
4. conditional CI-only: `.github/workflows/p9-s8c2-pr-validation.yml`

Reuse the existing S8C2 workflow. If its old path filter/commands/fixed base prevent this stage from running, EXEC may minimally adapt that same workflow: path filters, display name, checkout `submodules: true`, scoped commands/timeouts and diff base. Do not create a duplicate workflow when this one can be reused. Use only normal GitHub-hosted runners; no paid/self-hosted runner and no new dependency without approval. If edited, paths must also cover this card, the unique checklist and `hsr/CODEX_HANDOFF.md` so REVIEW governance-only final-head changes can trigger final CI.

Any required production change outside `systems/ability.py` is a planning boundary and triggers `[NEEDS_REPLAN]`.

## Implementation constraints

### 1. Preserve the shared executor as the only walker

Wire `AbilityTaskSystem._formal_task_graph_hooks(...)` to S8C2's existing weighted-selection callback/result contract. Do not manually traverse RandomConfig children and do not duplicate executor identity checks. Only the child selected by `TaskGraphExecutor` may execute.

### 2. Resolve weights only from accepted formal IR

For each `TaskGraphWeightedSelectionIR`, resolve every choice's `weight_definition_id` through its accepted `numeric_definitions` using the existing formal ability numeric-evaluation context. Runtime must not reread raw TBGD `OddsList`/JSON.

Preserve materialized choice order/ordinal plus exact `choice_id`, `graph_node_id`, `branch_id` and source identity. Unresolved, non-finite or negative weights fail closed. Zero weights are legal only when total selectable weight is > 0. Empty/all-zero/identity-incomplete selections fail closed without gameplay mutation.

If the existing ability numeric evaluator cannot consume the accepted numeric IR without changing IR/materializer/compiler/shared executor, stop with `[NEEDS_REPLAN]`.

### 3. Use the existing RNG authority and action metadata

Create one existing `RNGRequest` for one RandomConfig decision and resolve it through existing `resolve_rng_request(...)`. Consume existing action `rng_choices` / `rng_mode` metadata plumbing and existing RNG helper parsing; no hidden side channel or second RNG source.

Outcomes map 1:1 to materialized weighted choices and retain exact formal choice identity. Request identity must satisfy current RNG completeness rules with a stable decision scope, deterministic non-negative decision index, and sufficient existing action/task/graph/selection/invocation identity to distinguish repeated executions. Derive choice/event keys with existing helpers; do not add another identity algorithm.

Explicit/replay ledger mode must reject missing, unknown, stale, duplicate or identity-mismatched choices. Existing deterministic-seed mode keeps existing policy. Do not change global seed/generation/replay policy or `systems/rng.py`.

If current action invocation/metadata lacks stable identity required by existing `RNGRequest`, stop with `[NEEDS_REPLAN]` rather than changing another production authority.

### 4. One decision, one event, existing whole-action ledger

Successful selection returns S8C2's existing result type with exact selection/graph/choice/ordinal/branch identity and exactly one corresponding RNG event. Let `TaskGraphExecutor` admit it and let the existing ability/action return path carry it into existing `core/executor.py` whole-action ledger validation. Do not append another copy or add another ledger validator.

Invalid weights, malformed identity, invalid/stale ledger choice, unsupported RNG mode or S8C2 selection mismatch must block with no RandomConfig child/effect mutation and no silent first-child/implicit-random fallback. Existing non-RandomConfig action behavior remains unchanged.

## Focused validator

Create `validate_p9_s8c_random_config_action_caller.py` with:

### `--fast`

Exercise real `AbilityTaskSystem` + shared `TaskGraphExecutor` together, not the new hook alone. Cover at least:

- valid positive dynamic weights + ledger-specified branch -> exact S8C2 choice identity;
- exactly one admitted RNG event;
- unselected child cannot mutate state/emit gameplay effect;
- unresolved/non-finite/negative/all-zero weights and malformed/missing/stale explicit-ledger choices fail closed with unchanged gameplay state;
- repeated decision identity is stable and distinct when execution context is distinct;
- non-RandomConfig formal action regression remains green.

### `--direct`

Dynamically discover a current real formal action RandomConfig through the existing S8C1 action-entry/materializer path; do not hard-code one content ID as the denominator. Materialize the accepted IR and execute it through the production action transaction/formal ability route, not a validator-only walker.

Prove:

1. one valid current source reaches the new action weighted-selection hook;
2. a valid existing explicit RNG-ledger choice (or existing deterministic-seed mode where appropriate) selects exactly one child;
3. emitted RNG event identity is complete/stable and matches the formal selected choice;
4. existing whole-action ledger validation accepts/consumes that decision;
5. one stale/tampered explicit choice fails closed with no child mutation;
6. output records the dynamically discovered denominator/source and selected representative so REVIEW can reproduce it.

If every real source is blocked by unrelated unsupported production semantics, do not downgrade Direct to synthetic-only evidence: report `[BLOCKED]` for external/environmental blockage or `[NEEDS_REPLAN]` when the missing production support changes this card's authority/scope.

## Acceptance commands

Run from repository root; Direct validation requires the repository TBGD submodule to be present.

```bash
env PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c_random_config_action_caller.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c_random_config_action_caller --fast

python3 -m pytest -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_p9_s8c2_random_config_runtime_executor.py

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c_random_config_action_caller --direct

env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --direct

git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce...HEAD
```

The existing S8C1B Direct command is only an upstream source/materializer regression guard; it does not replace the new production-runtime Direct proof. No Catalog/Full run is required unless a discovered boundary requires replan. Target budget: Fast <= 2 min; Direct total <= 4 min; peak memory <= 1 GiB.

## Success criteria

EXEC may hand off only when all are true:

- a real formal action RandomConfig executes through `AbilityTaskSystem` and the shared S8C2 executor;
- dynamic weights come from formal numeric IR, not raw source payload;
- existing `systems/rng.py` is the only RNG decision authority;
- a valid supplied choice selects the exact formal branch and produces exactly one stable/complete RNG event;
- existing whole-action RNG-ledger validation accepts/consumes it;
- only selected child executes; invalid/tampered cases fail closed without state mutation;
- existing non-RandomConfig behavior and S8C2 executor tests stay green;
- new Fast/Direct, S8C1B Direct, compile, diff check and PR CI are green;
- production diff is confined to `systems/ability.py`;
- report + `[HANDOFF:REVIEW]` include final head, changed files, exact commands/results, CI run, discovered real source/denominator, RNG identity/ledger evidence, deferred and `next=REVIEW`;
- parent `P9-S8C` remains unchecked.

## Deferred / non-goals

Do not pull into this PR:

- formal `StatusCallbackSystem` RandomConfig/RNG-ledger caller integration or retirement of its legacy RandomConfig walker;
- changes to shared executor/weighted-selection IR, RNG policy or whole-action ledger authority;
- projectile/flight/hit identity, target iteration or multi-hit identity;
- barrier;
- parallel/deterministic merge;
- sequence-select/timeline-wait;
- S8C aggregate acceptance;
- P9-S5D2 replay recheck (after S8C aggregate);
- S9+;
- unrelated workflow cleanup/new dependencies/paid runners.

## Stop conditions

Post `[NEEDS_REPLAN]` rather than scope-creeping if implementation needs another production file/authority (`status_callbacks.py`, `systems/rng.py`, `systems/task_graph.py`, `rules/task_graph.py`, `core/executor.py`, compiler/materializer, etc.), a second independent consumer, a new RNG policy/dependency, or stable identity/weight evaluation cannot be achieved with existing contracts. `[BLOCKED]` is for external/environmental obstacles that do not invalidate the plan. Ordinary implementation/test/validator/CI defects remain EXEC responsibility.

## Handoff / acceptance protocol

EXEC works in this same Draft PR. On completion, post a top-level comment beginning `[HANDOFF:REVIEW]` with `role=EXEC`, `status=ready_for_review`, this stage key, planning base, final head, changed files, exact validation results, CI run, direct-source evidence, RNG/ledger evidence, deferred/remaining and `next=REVIEW`; then mark ready for review. EXEC does not check acceptance items, write accepted checkpoint governance or merge.

A fresh REVIEW independently reproduces critical Fast/Direct evidence and audits the diff. Ordinary defects -> `[RETURN_FOR_FIX]` to EXEC; scope/authority/planning defects -> `[NEEDS_REPLAN]` to PLAN. On acceptance REVIEW updates this card, the unique P9 checklist (record this exact descriptive child as accepted but keep parent S8C unchecked) and `hsr/CODEX_HANDOFF.md`, verifies final-head CI success, then squash-merges with expected head SHA.

After acceptance, the next remaining S8C source must again be selected from repository facts; do not auto-close S8C.