# P9-S8C RandomConfig Formal Action Caller / RNG Ledger — EXEC report

- role: `EXEC`
- stage: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER`
- status: `needs_replan`
- planning base: `b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- planning handoff head: `b7694b80d2df7d50d18e4687adb9300d92b48ad9`
- implementation head before this report: `53859e6ea6d3f78ced8b2b1e2a7ead57e71f4463`
- final PR head: recorded in the structured `[NEEDS_REPLAN]` PR comment because committing this report necessarily advances the branch head.

## Work performed

The scoped caller implementation was added only in the card-authorized production file `simulator_v8_clean_core/systems/ability.py`:

- wired the existing S8C2 `weighted_selection` hook into `AbilityTaskSystem._formal_task_graph_hooks(...)`;
- evaluates accepted `TaskGraphWeightedSelectionIR.numeric_definitions` through the existing formal ability numeric evaluator;
- preserves materialized choice / branch / source identity;
- constructs the existing `RNGRequest` and derives `choice_key` / `event_id` with the existing RNG helpers;
- consumes existing action `rng_choices` / `rng_mode` metadata through `resolve_rng_request(...)`;
- returns one existing `TaskGraphWeightedSelectionResult` with one RNG event and does not add another walker, RNG source or ledger validator.

Validation-only changes were added to `tools/validate_p9_s8c_random_config_action_caller.py`, and the existing `.github/workflows/p9-s8c2-pr-validation.yml` was minimally adapted to run the card commands on a normal `ubuntu-latest` runner with the TBGD submodule.

`StatusCallbackSystem`, `systems/rng.py`, `systems/task_graph.py`, `rules/task_graph.py`, `core/executor.py`, compiler/materializer code and all other production authorities were not modified.

## Validation reached before the scope boundary

GitHub Actions run `34088147702` on head `53859e6ea6d3f78ced8b2b1e2a7ead57e71f4463` completed successfully:

- `compileall` for `systems/ability.py` + the focused validator: PASS;
- focused `--fast`: PASS;
- `test_p9_s8c2_random_config_runtime_executor.py`: PASS;
- current focused `--direct`: PASS as a combination of real signed-source/materializer discovery plus synthetic production-hook runtime;
- existing S8C1B `--direct`: PASS;
- `git diff --check b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce...HEAD`: PASS.

Run: `https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34088147702`

Earlier ordinary validator/tooling failures were repaired in-PR:

- run `34087576499`: validator imported a nonexistent private bootstrap helper; production compilation passed;
- run `34087810409`: validator called a keyword-only formal-hook argument positionally; production compilation passed.

Neither earlier failure was a production or scope blocker.

## Replan boundary discovered by strengthening Direct to the card's required production route

The card requires `--direct` to dynamically discover a real formal action RandomConfig and execute it through:

`CombatExecutor.execute(ActionCommand) -> formal ability phase -> AbilityTaskSystem -> shared TaskGraphExecutor -> weighted_selection hook -> existing RNG authority -> whole-action RNG ledger`.

That route is not reachable with the card's allowed production write set.

Repository facts establishing the boundary:

1. `tbgd/character_control_flow_contracts.py` assigns both RandomConfig gameplay fields to stage `p9_s8c`:
   - `OddsList` -> `numeric_contract / p9_s8c`;
   - `TaskList` -> `child_graph / p9_s8c`.
2. The same source-contract authority does not list `p9_s8c` in `_COMPLETED_OWNERS`.
3. `tbgd/task_graph_materializer.py` maps `p9_s8c` to owner domain `hit_random_sequence` and leaves source dispositions with remaining downstream domains deferred.
4. The accepted S8C1B real-source Direct validator explicitly requires its dynamically discovered formal action RandomConfig node to remain `materialization_status == "deferred"` with `owner_domains == ("hit_random_sequence",)`; that assertion is green on current head.
5. `systems/task_graph.py::_TaskGraphRun.execute_node(...)` rejects any node whose `materialization_status != "materialized"` or `node_kind == "deferred"` before dispatching by node kind. Therefore the real RandomConfig node is rejected before `_execute_branch(...)` can call the newly wired weighted-selection hook.

Consequently, the currently green focused `--direct` is not valid card acceptance evidence: it proves real signed-source/materializer closure and production hook behavior separately, but it cannot prove the required real `CombatExecutor` action transaction because the real node is still intentionally deferred upstream.

## Why this is `NEEDS_REPLAN`

Closing the real production vertical slice requires first changing the RandomConfig materialization/source-ownership authority so an accepted real action RandomConfig node becomes `materialized` and executable. That necessarily requires a production change outside `systems/ability.py` (for example the control-flow/materializer authority), which the card explicitly defines as a planning boundary and stop condition.

EXEC therefore did not weaken Direct, did not mark the synthetic+source split proof as accepted, and did not modify the forbidden upstream authorities.

## Remaining / deferred

- PLAN must decide the prerequisite/materialization closure and authorize the exact production owner(s) needed to retire the `hit_random_sequence` deferral for the intended RandomConfig slice, or split that prerequisite into a preceding STRICT card.
- After replanning, rerun a real dynamically discovered action through `CombatExecutor.execute(ActionCommand)` and prove one valid whole-action ledger decision plus stale/tampered fail-closed behavior.
- `StatusCallbackSystem` remains separately deferred as required.
- Parent `P9-S8C` remains unchecked.
- EXEC has not self-accepted, updated governance/checklists, marked the PR ready, or merged.
