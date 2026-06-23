# v8 v0_254 - Kill Listener Extra-Turn Chain

## What Changed

- Added a real-source validation for the Seele-style extra-turn chain:
  `OnTriggerDeath -> SetDynamicValue(InsertAction) -> OnAfterSkillUse -> TurnInsertAction queue -> extra-turn action`.
- Fixed status callback dispatch so a runtime status instance only executes callback ids declared in its own `trigger_ids_by_event`; same-named modifiers from another ability file no longer leak into the current instance.
- Admitted the currently supported mainline death/after-skill callback pieces needed by this chain: `SetDynamicValue`, `AddModifier`, and the condition family around `ByAnd/ByAny/ByIsCurrentSkillActive/ByHaveEnemyAlive/ByIsInsertAction`.
- Fixed inverse handling for `ByIsCurrentSkillActive`, `ByIsInsertAction`, and `ByHaveEnemyAlive`.

## Validation Result

- `validate_v0_254`: `ok=true`.
- The death listener writes the `InsertAction` dynamic value from real TBGD source.
- The after-skill listener enqueues an `extra_turn` queue entry from real `TurnInsertAction + PrepareAbilityName` evidence.
- The scheduler drains that queue before natural AV advance and executes a route-selected non-ultimate action through `CombatExecutor(source="queue")`.
- Extra turn emits `extra_turn.begin` and `extra_turn.end`, but does not emit ordinary `turn.begin` / `turn.end`.
- A guard status with normal `ActionPhaseEnd` duration remains unchanged, proving this extra turn did not consume ordinary buff duration.
- Death listener, after-skill listener, scheduler transition, and child action transition all pass replay, settlement traceability, and source audit.

## Still Blocked

- The selected source still contains non-essential subtasks that remain blocked:
  - dynamic AddModifier formula/lifetime pieces on the death listener.
  - energy-bar related after-skill subtasks.
- These are process-only blockers in this validation and do not prevent or fake the extra-turn queue/action lifecycle.
- Some actions from the same source do not yet have admitted damage emission; the extra turn can execute the action transition, but damage still depends on the existing damage-emission admission rules.

## Progress

- Extra-turn lifecycle is now validated end-to-end for a real kill-listener source in the current admitted scope.
- Remaining larger gaps are not in this chain itself: full character-specific effect formulas, all damage emission coverage, and future automatic event publication for every possible kill path.
