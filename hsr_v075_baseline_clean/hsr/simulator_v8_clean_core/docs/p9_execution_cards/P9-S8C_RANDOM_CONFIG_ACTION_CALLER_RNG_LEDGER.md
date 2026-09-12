# P9-S8C RandomConfig Formal Action Caller / RNG Ledger

- stage: `P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER`
- parent: `P9-S8C`
- mode: `STRICT`
- status: `needs_decision`
- revision: `R2`
- planning base: `master@b01e813bd194b5e5bc7bcd6ba65d8ba0ee0e44ce`
- R1 PLAN head: `295eef6708abdc72ba9330b2acb701d1a177432f`
- R2 replan input head: `df4136800adb3420b288664a07b725c126d67984`
- R2 finding: `no_proven_action_to_randomconfig_route_without_cross_authority_or_sibling_deferred_work`

## R2 disposition

R1 correctly closed the first materializer prerequisite, but that was not the full production prerequisite chain. Independent PLAN tracing from `CombatExecutor.execute(ActionCommand)` through the existing whole-action RNG ledger confirms that the current repository has **no proven dynamically discovered formal action RandomConfig route that completes this card's required Direct without crossing another authority/deferred boundary**.

Therefore R2 does **not** authorize another incremental EXEC expansion. Existing R1/EXEC work is preserved in this Draft PR, but implementation is paused pending an explicit architecture/scope decision.

The acceptance target is unchanged and is not weakened:

`CombatExecutor.execute(ActionCommand)` -> normal target/admission/preflight -> real action/status/nested-ability production topology as applicable -> `AbilityTaskSystem` -> shared `TaskGraphExecutor` -> S8C2 `weighted_selection` -> existing `systems/rng.py` -> emitted ability-task RNG event -> existing `core/executor.py::validate_rng_choice_ledger(...)`.

Synthetic materialized graphs, direct hook calls, direct `TaskGraphExecutor` calls, manually invoking a nested ability, manually invoking the ledger validator, or bypassing action admission do not satisfy Direct.

## Retained R1 result

The current PR already contains useful, retained work:

- `systems/ability.py` wires the accepted shared weighted-selection hook for formal action ability graphs and uses the existing RNG authority/identity helpers.
- `tbgd/task_graph_materializer.py` narrowly retires `hit_random_sequence` only for eligible `ability_phase_callback` RandomConfig formal positions; it does not globally close `p9_s8c`.
- S8C1B real-source validation proves a representative action RandomConfig can now be `branch / materialized / task_graph_execution` with exact weighted-selection/child closure.
- S8C1C source/formal-position regression remains green and confirms sibling/source denominators were not globally reclassified.
- the focused Fast/S8C2 runtime tests remain green.

R1 validation evidence includes successful S8C1B run `34096066179` and S8C1C run `34096066165`. These prove materialization/source closure only; they do not prove the required CombatExecutor route.

Do not revert or overwrite these existing changes merely because R2 is paused.

## Full production prerequisite trace

### 1. Action admission occurs before formal task-graph execution

`CombatExecutor.execute(...)` first resolves target context and calls `ActionContractSystem.evaluate(...)`. If the action contract blocks, the formal ability graph is never executed and no RandomConfig RNG event can reach the whole-action ledger.

`ActionContractSystem.evaluate(...)` currently obtains **all** `rules.ability_tasks_for_action(action_id, level)` and runs the legacy `ability_task_runtime_blocked_reason(...)` over that complete action slice before formal graph execution.

This admission denominator is broader than the actual path later traversed by `AbilityTaskSystem`/`TaskGraphExecutor`. Current real candidates therefore fail on tasks that may be structural, presentation/process-only, nested-only, or otherwise not the exact runtime path to the selected RandomConfig.

Observed blockers for the otherwise useful `avatar_skill:1100601` candidate include:

- `process_only_task_effect_source_mismatch`
- `effect_coverage_status:unsupported:SetEntityVisible`
- `effect_coverage_status:unsupported:RandomConfig`

`SetEntityVisible` is classified by the source compiler as `presentation_only`; `RandomConfig` is a structural control-flow family now owned at runtime by the formal task graph. Treating these legacy coverage blockers as sufficient evidence that the whole action must be rejected is an authority-overlap question, not a validator-only defect.

PLAN must not simply delete these checks. A valid authority change must specify which formal task-graph obligations supersede legacy per-task admission, preserve fail-closed behavior for true runtime leaves, and prove non-formal/legacy actions are unchanged.

### 2. Formal graph execution has its own fail-closed gates

Once action admission succeeds, `AbilityTaskSystem` executes only admitted formal callback roots through `TaskGraphExecutor`. The shared executor rejects every node whose `materialization_status != "materialized"` or `node_kind == "deferred"` before dispatch.

R1 solved this only for the RandomConfig node itself and its selected child closure. R1 did **not** prove that every real action-root -> RandomConfig ancestor path is free of sibling deferred nodes.

Examples of sibling families that remain intentionally deferred include wait/barrier/timeline, target-cursor/random-target, projectile/multi-hit and parallel/sequence semantics. They must not be implicitly admitted merely to make this card green.

### 3. The best current 1100601 source is not a direct action-root RandomConfig

Pinned TBGD source `Config/ConfigAbility/Avatar/Advanced/Avatar_Advanced_Silwolf_00_Ability.json` shows that `Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug` is triggered from status/modifier callbacks, including:

`MAvatar_Advanced_Silwolf_00_Passive / OnAfterAttack -> Retarget -> TriggerAbility(Avatar_Advanced_Silwolf_00_PassiveSkill_RandomBug)`.

Inside `PassiveSkill_RandomBug`, predicate branches eventually reach the real RandomConfig and its AddModifier children.

Thus the action-slice association discovered for `avatar_skill:1100601` is not by itself a runtime path. A faithful CombatExecutor proof must traverse the real action listener/status callback -> `TriggerAbility` -> nested ability graph bridge before it can reach that RandomConfig.

### 4. Top-level action-window status -> nested ability transport is not currently closed

`core/executor.py` dispatches each action trigger window twice:

1. `EventDispatchSystem.dispatch_action_window(...)` for the legacy trigger-window path; and
2. `EventDispatchSystem.dispatch_event(...)` for the listener/status-callback path.

The second call currently supplies no `task_graph_continuation` and no `nested_ability_hooks`.

`EventDispatchSystem` and `StatusCallbackSystem` both explicitly reject a hooks transport when hooks are supplied without a `TaskGraphContinuation`. A continuation cannot be fabricated directly; `TaskGraphContinuation` is intentionally derived from an existing task-graph hook request.

`StatusCallbackSystem` can route a nested `ability_phase_callback` graph when legitimate nested hooks are present, but its routed hook set currently contains `leaf/condition/branch/count/targets/graph` and does **not** forward `weighted_selection`.

Therefore the real 1100601 route exposes a second, independent architecture prerequisite: define how a top-level action-window status callback legally enters a nested formal ability graph with the correct action context/continuation and with the accepted weighted-selection hook. This is broader than the original action-caller-only write set.

### 5. Whole-action RNG ledger is already sufficient

No R2 evidence requires a new RNG or ledger authority. `core/executor.py` already includes `ability_task_rng_events` in the RNG event set passed to `validate_rng_choice_ledger(command.metadata, ...)`.

If a real RandomConfig RNG event reaches the end of the CombatExecutor transaction, the existing ledger is the intended authority. `systems/rng.py` and the ledger algorithm remain out of scope unless later independent evidence proves a defect.

## Dynamic candidate denominator

The R1 diagnostic dynamically discovered exactly these current action candidates:

- `avatar_skill:1100601`
- `avatar_skill:120402`
- `avatar_skill:130402`
- `avatar_skill:130403`

The focused Direct exhausts its dynamically discovered candidate/level set and returns success only if one real `CombatExecutor.execute(...)` transaction reaches and consumes the RandomConfig RNG decision. Current runs found none.

### `avatar_skill:1100601`

- action target query/accept and external-turn admission are available for tested levels/windows;
- ActionContract currently blocks before runtime on legacy task admission (`process_only_task_effect_source_mismatch`, unsupported presentation `SetEntityVisible`, unsupported structural `RandomConfig`);
- the representative RandomConfig-bearing nested ability is actually reached from `OnAfterAttack` status callback -> `Retarget` -> `TriggerAbility`, so a faithful route additionally needs the top-level status -> nested ability transport described above;
- source abilities also contain `WaitAnimState`; those remain sibling sequence/barrier semantics and may not be globally admitted by this card.

Conclusion: not a clean action-only candidate under current authorities.

### `avatar_skill:120402`

- dynamically discovered by the same source/action denominator;
- the exhaustive current Direct did not produce a successful CombatExecutor transaction for it;
- the R1 execution report records the remaining candidates as blocked by existing action-target/effect/resource/admission prerequisites rather than by the RandomConfig materializer itself.

R2 does not treat absence of a successful route as permission to relax those prerequisites. Before this candidate could be selected for implementation, a new diagnostic must emit its complete action/level/window blocker set and prove that every required prerequisite belongs to this stage rather than a sibling deferred domain.

### `avatar_skill:130402`

Current Direct evidence shows tested levels are blocked by multiple independent existing domains, including:

- `action_target_relation_not_lowered`
- `effect_coverage_status:unsupported:RemoveEffect`
- `effect_coverage_status:unsupported:TriggerEffect`
- `effect_coverage_status:unsupported:WaitTimelineFinish`
- `effect_coverage_status:unsupported:IncludeTaskListTemplate`
- `effect_coverage_status:unsupported:Retarget`
- `unsupported_modifier_value_type:CurrentShield`
- `effect_coverage_status:unsupported:LoopTargetList`
- `effect_coverage_status:unsupported:GoNextTargetInList`
- `resource_formula_type_not_supported:AddRatio`
- plus legacy RandomConfig/process-only admission blockers.

This candidate plainly crosses target/resource/timeline/control-flow sibling work and cannot be pulled into PR9 without an explicit cross-domain scope decision.

### `avatar_skill:130403`

Current materialized weighted graphs have no executable `external_turn` action admission for tested levels (`no_external_turn_admission`). Creating or bypassing an admission solely for validation would violate this card.

Conclusion: not a current external-action Direct candidate.

## R2 conclusion

There is **no currently proven non-sibling-deferred acceptance path** for the exact Direct required by this stage.

This is not solved safely by authorizing one more file. At minimum, the cleanest 1100601 route raises two distinct authority decisions:

1. how formal task-graph ownership interacts with the legacy whole-action per-task admission gate; and
2. how top-level action-window status callbacks legally invoke nested formal ability graphs, including transport of `weighted_selection` and action/RNG identity context.

Other candidates additionally require sibling target/resource/timeline/control-flow semantics or lack action admission.

Accordingly, **no new production write path is authorized in R2 before a decision**.

## Decision routes

### Route A — dependency-first, keep PR9 narrow (recommended)

Keep PR9 Draft and preserve all current R1 work. Close prerequisite authority slices separately before resuming this card:

1. define/reconcile formal task-graph vs legacy `ability_task_runtime_blocked_reason` admission ownership with strict regressions;
2. define the top-level action-window status-callback -> nested formal ability transport contract, including valid context/continuation semantics and routing of all required hooks such as `weighted_selection`;
3. close any candidate-specific sibling domain only in its own planned stage if still required;
4. return to PR9 and rerun the unchanged real CombatExecutor Direct.

Impact: smallest audit surface and preserves the existing staged P9 ownership model, but PR9 cannot complete until prerequisites land.

### Route B — explicitly broaden PR9 into a cross-authority vertical integration

If the desired architecture is to finish the first real action RandomConfig in this same PR, PLAN would need explicit permission to redesign/modify the relevant admission and action-listener/nested-ability transport authorities. Likely touched authorities include some subset of:

- `systems/action_contract.py` and/or `systems/ability_task_contract.py`
- `core/executor.py`
- `systems/event_dispatch.py`
- `systems/status_callbacks.py`
- `systems/ability.py`

and, only if the chosen real candidate proves unavoidable, additional sibling target/resource/sequence authorities.

This route must not be interpreted as blanket permission to mark unsupported/deferred opcodes executable. Every added authority requires its own exact source/runtime invariant and negative regressions.

Impact: substantially larger production blast radius, mixes action admission, event orchestration and nested ability semantics into a RandomConfig card, and makes independent review more difficult.

### Route C — redefine the stage/Direct producer

A deliberate product/planning decision could change the stage from “external action -> whole-action ledger” to a different real producer such as a directly-invoked nested ability or status-callback RandomConfig consumer.

That would change the current stage goal and would no longer prove the originally required `CombatExecutor.execute(ActionCommand)` admission path. It is not an acceptable implicit workaround and requires explicit approval/replanning.

## Explicitly rejected workarounds

Regardless of route, do not:

- skip or monkeypatch `ActionContractSystem` in Direct;
- hand-construct a materialized production graph as acceptance evidence;
- call the weighted-selection hook or `TaskGraphExecutor` directly for Direct;
- manually call `PassiveSkill_RandomBug` instead of following its real caller;
- forge a `TaskGraphContinuation` or weaken its type/identity checks just for validation;
- mark `p9_s8c`, `hit_random_sequence`, target/resource/timeline or status domains globally complete;
- convert unsupported presentation/structural tasks to executable effects merely to pass admission;
- accept real-source discovery + synthetic runtime as end-to-end proof;
- validate the RandomConfig ledger outside the real CombatExecutor transaction as a substitute for whole-action consumption.

## Existing validation contract remains the future acceptance bar

After a decision and prerequisite closure, this stage still requires all of the following on one dynamically discovered real action route:

1. normal action target/admission/preflight succeeds without bypass;
2. the real production caller path reaches a materialized formal RandomConfig node;
3. weights are evaluated from accepted formal numeric IR;
4. shared S8C2 executor selects exactly one child;
5. existing `systems/rng.py` emits exactly one stable/complete RandomConfig RNG event;
6. the existing whole-action ledger reports the real choice key consumed;
7. explicit/replay rerun reproduces the same choice and result through the same CombatExecutor route;
8. stale/tampered choice on the otherwise complete ledger fails closed with no committed gameplay mutation;
9. unselected RandomConfig children do not execute;
10. status/no-formal-producer and unrelated S8C sibling domains remain deferred unless separately accepted before the rerun;
11. S8C1B/S8C1C source/materializer closure and S8C2 shared-executor regressions remain green.

The current focused command remains conceptually authoritative and must not be weakened:

```bash
env PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c_random_config_action_caller --direct
```

A future PLAN revision must list every newly authorized production file and exact prerequisite-specific regression command before handing work back to EXEC.

## Current write authority while `needs_decision`

No new business implementation is authorized.

Retained PR production changes may remain in:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`

Retained validation/evidence changes may remain in:

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c_random_config_action_caller.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py`
- `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C_RANDOM_CONFIG_ACTION_CALLER_RNG_LEDGER_execution_report.md`
- `.github/workflows/p9-s8c2-pr-validation.yml`

This R2 card update is planning-only. EXEC must not start modifying `action_contract.py`, `ability_task_contract.py`, `core/executor.py`, `event_dispatch.py`, `status_callbacks.py`, target/resource/timeline authorities, or any other production file until PLAN resolves one of the decision routes.

## State / next

- PR remains Draft/open.
- Existing R1 implementation is preserved.
- Parent `P9-S8C` remains unchecked.
- No `[HANDOFF:EXEC]` is valid under R2 while `status=needs_decision`.
- PLAN resumes only after the scope/architecture route is chosen; the next PLAN revision must convert this card back to `ready_for_execution` with a complete, finite write set and exact real Direct regressions.
