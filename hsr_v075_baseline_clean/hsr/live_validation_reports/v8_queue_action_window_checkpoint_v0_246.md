# v8 Queue Action Window Checkpoint v0_246

## Summary

v0_246 closes the next queue/runtime boundary after v0_245. It adds the runtime path needed for queued action execution, but keeps the admission rule strict:

```text
QueueEntry
-> QueueResolutionIR
-> QueueWindowPlan
-> QueueSystem.drain_admitted()
-> CombatExecutor.execute(source="queue")
-> mutation / settlement / replay / source audit
```

The current TBGD set does not contain an admitted mainline `TurnInsertAction` fixed `SkillIndex` sample that passes source, target alias, priority, and action-set admission together. Because of that, `queue_action_drain` remains blocked with a concrete dependency instead of using a synthetic positive case.

## Implemented

- Added `QueueWindowPlan` to make queue window admission explicit.
- Extended `QueueDrainPlan` with:
  - `queue_window`
  - `resolved_action_id`
  - `resolved_action_level`
- Changed `TurnInsertAction` lowering so fixed `SkillIndex` can resolve through `CombatantActionSetIR` when the queue intent itself is executable.
- Added `QueueSystem` action-definition drain planning:
  - actor must exist
  - actor `template_id` must match a `CombatantActionSetIR` candidate
  - target ids must be present
  - queue window must be admitted
- Added scheduler preflight for queue action drain before dequeue:
  - action definition exists
  - action event exists and is not blocked
  - target ids are present
  - skill point cost can be paid
  - queue window is admitted
- Added queue child action execution path:
  - dequeue first
  - construct `ActionCommand(source="queue")`
  - call `CombatExecutor.execute()`
  - preserve parent queue metadata in the child command
- Extended queue dequeue metadata and source audit with `queue_window_plan`.
- Updated scheduler unsupported hook coverage so extra turn / ultimate / interrupt have distinct blocking dependencies.
- Added `validate_v0_246`.

## Validation Results

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_regression_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_246 --output-dir /tmp/hsr_v8_v0_246
git diff --check
```

All checks passed.

v0_246 checked:

- Existing `TurnInsertAbility -> StandaloneAbilityGraphIR -> dequeue -> standalone task` still passes replay, settlement traceability, and source audit.
- Queue dequeue mutations now include admitted `queue_window_plan`.
- `TurnInsertAction` is discovered in TBGD, but no admitted action-definition positive case exists in the current source set.
- Dynamic `SkillIndex`, assistant ability, and blocked action source/priority negative cases do not mutate state.
- The action drain gap matrix records the dominant blocker as `queue_intent_source_mode_not_admitted`, with additional blockers for target alias, abort policy, and priority.

## Current Trust Status

- `queue_enqueue`: trusted for current scope.
- `queue_priority`: trusted for current scope.
- `queue_resolution`: trusted for current scope.
- `queue_window_admission`: trusted for current scope.
- `standalone_ability_queue_drain`: trusted for current scope.
- `queue_action_drain`: blocked in current TBGD scope because no admitted `TurnInsertAction` fixed `SkillIndex` source reaches action-definition resolution.

## Remaining Boundaries

- `TurnInsertAction` action drain will become executable as soon as a queue intent reaches all admission gates: mainline source, supported target aliases, admitted priority, fixed or bound `SkillIndex`, and matching `CombatantActionSetIR`.
- `TurnInsertAssistantAbility` remains blocked until assistant actor identity, assistant ability/action graph, target, and priority can all be resolved from Canonical IR.
- Full ultimate / interrupt / immediate queue ordering remains blocked until the total ordering semantics are admitted.
- This checkpoint does not implement enemy AI, full character profile construction, follow-up/counter semantics, wave flow, bounce RNG, or complete ultimate interrupt ordering.
