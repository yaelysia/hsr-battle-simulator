# P9-S8C RandomConfig Formal Action Caller / RNG Ledger — EXEC R1 report

- role: `EXEC`
- stage: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER`
- revision: `R1`
- status: `needs_replan`
- planning base: `b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- PLAN R1 handoff head: `295eef6708abdc72ba9330b2acb701d1a177432f`
- report-predecessor head: `3637d246724be60af142cec8fc70c5ff8504a3ae`
- authoritative exact final head: recorded in the structured `[NEEDS_REPLAN]` PR comment posted after this report commit.

## R1 work completed

Existing EXEC caller/RNG work was preserved and extended only inside the R1 authorized production set.

### `systems/ability.py`

- keeps the formal `AbilityTaskSystem` `weighted_selection` hook wired to the accepted S8C2 shared `TaskGraphExecutor`;
- resolves each accepted `TaskGraphWeightedSelectionIR` weight through the existing formal numeric evaluator;
- builds the existing `RNGRequest`, using existing choice/event identity helpers and existing action `rng_choices` / `rng_mode` metadata;
- returns the accepted S8C2 weighted-selection result with exact selection/choice/ordinal/branch identity and exactly one RNG event;
- adds no second walker, RNG source, replay policy or ledger validator.

### `tbgd/task_graph_materializer.py` R1 prerequisite

- action-only admission is limited to `ability_phase_callback` `RandomConfig` weighted-selection positions;
- the accepted action RandomConfig position becomes executable `branch / task_graph_execution` only when branch children are already materialized and no unrelated deferred prerequisite is discarded;
- matching source disposition retirement is derived from actual formal action materialization links rather than a global `p9_s8c` completion flag;
- `status_callback`, `no_formal_producer`, and other S8C sibling ownership remain deferred;
- the structural RandomConfig task's exact legacy unsupported effect reference is allowed to remain as a formal identity reference while it no longer prevents the RandomConfig branch node itself from materializing. The reference is retained so `CanonicalIR` definition-reference closure remains exact.

### Validation/evidence

- focused validator now dynamically discovers real action RandomConfig candidates and attempts the required production `CombatExecutor.execute(ActionCommand)` route;
- S8C1B validator expectation was minimally advanced from action-side deferred to action-side materialized while retaining signed-source/weight/choice/status-side checks;
- S8C1C validator remained unchanged;
- the reused workflow was restored to standard `contents: read` hosted-runner validation after temporary scoped bootstrap/diagnostic use.

## Evidence that the R1 materializer prerequisite succeeded

S8C1B run `34096066179` is fully green on the current production implementation:

- compile: PASS;
- S8C1A upstream IR: PASS;
- S8C1B Fast: PASS;
- S8C1B real-source Direct: PASS;
- diff check: PASS.

The dynamically discovered representative is source-backed and action-only materialized. The earlier successful S8C1B Direct output identified:

- action: `avatar_skill:1100601`, level `1`;
- phase: `ability_phase:avatar_skill:1100601:1:2:Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug`;
- callback: `OnStart`;
- source: `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json`;
- RandomConfig source path: `$.AbilityList[8].OnStart[0].SuccessTaskList[0].SuccessTaskList[0].SuccessTaskList[0]`;
- denominator: `3` exact weighted choices;
- selection: `task_graph_weighted_selection:431ead4594e3e198cee890932d5c2853290ffb2dc90fdb0cfd186f67ba601428`.

S8C1C run `34096066165` is also fully green, including its unchanged real-source Direct and full catalog denominator validation. This confirms R1 did not corrupt remaining-entry/source-closure accounting or globally close sibling S8C domains.

## Required real `CombatExecutor.execute` Direct remains unreachable

Standard R1 run `34095437727` passed:

- scoped compile;
- focused `--fast`;
- all 9 accepted S8C2 executor tests.

Its required real `CombatExecutor.execute(ActionCommand)` Direct then failed after dynamically exhausting the current real action RandomConfig candidates. This is not the old materializer deferral: the action RandomConfig graph is now materialized and installable in `CanonicalIR`.

A separate read-only dynamic diagnostic run `34096066174` confirmed the current candidate denominator is:

- `avatar_skill:1100601`
- `avatar_skill:120402`
- `avatar_skill:130402`
- `avatar_skill:130403`

For the first dynamically ranked representative, `avatar_skill:1100601`, levels 1–4:

- real target query: `resolved`;
- real target acceptance: `accepted`;
- external-turn admission exists for `idle`, `turn_active`, and `turn_action`;
- `CombatExecutor` action contract blocks before formal ability execution with the same production reasons at every tested level/window:
  - `process_only_task_effect_source_mismatch`;
  - `effect_coverage_status:unsupported:SetEntityVisible`;
  - `effect_coverage_status:unsupported:RandomConfig`.

The focused Direct then continued to the other current candidates. The remaining candidates were blocked by already-deferred production semantics such as action-target relation/resource/effect coverage, or had no external-turn admission. No current real formal action RandomConfig reaches the weighted-selection hook through the complete production action transaction.

Critically, the `unsupported:RandomConfig` blocker is now a **task/action admission-layer legacy coverage gate**, not a task-graph materialization blocker. `ActionContractSystem` evaluates the original `AbilityTaskIR` coverage before `AbilityTaskSystem` executes. R1's materializer can make the formal RandomConfig graph node executable, but it cannot change that action/task admission authority.

## Why this is a new `NEEDS_REPLAN` boundary

R1 authorizes production changes only in:

- `systems/ability.py`;
- `tbgd/task_graph_materializer.py`.

Making the real action transaction trust the newly materialized formal RandomConfig structural position requires changing an upstream action/task admission authority (for example `systems/action_contract.py` / `systems/ability_task_contract.py` or another PLAN-selected equivalent) so the formal task-graph authority can supersede the legacy unsupported structural-task coverage at the correct boundary. Resolving the other candidate-specific sibling blockers would likewise expand beyond this card.

The R1 card explicitly requires `[NEEDS_REPLAN]` if no current real action reaches RandomConfig without another deferred domain. EXEC therefore does not:

- weaken Direct to source+synthetic stitching;
- forge/patch `AbilityTaskIR` coverage in the validator;
- bypass `CombatExecutor.execute` or its action contract;
- modify an unapproved action/task admission production authority;
- pull `StatusCallbackSystem` or other S8C siblings into this PR.

## Validation summary

- R1 action materializer prerequisite: PASS.
- focused Fast: PASS.
- accepted S8C2 shared-executor tests: `9 passed`.
- S8C1B real-source Direct: PASS (`34096066179`).
- S8C1C unchanged Direct + catalog: PASS (`34096066165`).
- required focused real `CombatExecutor.execute` Direct: **FAIL at a newly exposed production admission boundary** (`34095437727`).
- dynamic blocker diagnostic: PASS / evidence captured (`34096066174`).
- standard workflow restored with `permissions: contents: read`.

## Remaining / deferred

PLAN must decide the minimal action/task admission prerequisite that lets a task-graph-materialized action RandomConfig structural task pass the existing action contract without globally admitting unsupported effects or sibling domains. After that prerequisite, rerun the same mandatory Direct through `CombatExecutor.execute(ActionCommand)` and prove real RNG selection, whole-action explicit/replay ledger consumption, stale/tampered atomic failure and unselected-child exclusion.

Still deferred and unchanged:

- `StatusCallbackSystem` RandomConfig caller;
- RandomConfig `no_formal_producer` positions;
- projectile / wait / barrier / parallel / target-cursor and other S8C sibling families;
- S8C aggregate acceptance;
- parent `P9-S8C` checklist remains unchecked.

EXEC has not self-accepted, checked governance items, marked the PR ready, or merged.
