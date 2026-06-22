# v8 Queue Resolution Drain Gate Checkpoint v0_241

## Scope

This checkpoint adds the queue resolution and drain admission gate for v8:

```text
QueueEntry
-> QueueResolutionIR / QueueDrainPlan
-> QueueSystem.drain_admitted()
-> Mutation / Settlement / SourceAudit
```

This stage does not execute inserted actions. It only proves whether a pending queue entry can be resolved from Canonical IR and admitted for dequeue. Unresolved entries remain pending and produce process-only blocked records.

## Implemented

- Added `QueueResolutionIR` to Canonical IR and RuleBook indexes.
- Lowered one queue resolution record for each `QueueIntentIR`.
- Added queue resolution coverage counts, resolved kind counts, and blocked reason counts.
- Added `QueueEntry.queue_intent_id` so runtime queue entries can be traced back to their admitted source intent.
- Added `QueueDrainPlan` and `QueueSystem.plan_drain()` / `drain_admitted()`.
- Added source audit policy for queue dequeue mutations, requiring `QueueResolutionIR`.
- Added `validate_v0_241`.

## Validation Result

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_regression_v0_235
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_regression_v0_238
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_240 --output-dir /tmp/hsr_v8_regression_v0_240
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_241 --output-dir /tmp/hsr_v8_v0_241
git diff --check
```

Results:

- `compileall`: passed.
- `validate_v0_225`: `ok=True`.
- `validate_v0_227`: `ok=True`.
- `validate_v0_235`: `ok=True`.
- `validate_v0_238`: `ok=True`.
- `validate_v0_240`: `ok=True`.
- `validate_v0_241`: `ok=True`.
- `git diff --check`: passed.

## Queue Resolution Coverage

- `QueueResolutionIR` lowered: 1218.
- executable: 0.
- blocked: 1218.
- resolved kind counts:
  - `blocked_intent`: 1217.
  - `unresolved_ability_name`: 1.

Blocked reason counts:

- `queue_intent_not_executable:queue_intent_source_mode_not_admitted`: 1205.
- `queue_intent_not_executable:queue_actor_target_alias_not_admitted:missing`: 6.
- `queue_intent_not_executable:queue_ability_target_alias_not_admitted:ModifierOwnerSkillTargetEntityList`: 3.
- `queue_intent_not_executable:queue_abort_policy_not_admitted`: 2.
- `queue_intent_not_executable:queue_insert_assistant_ability_not_admitted`: 1.
- `queue_ability_graph_not_lowered_or_missing:Avatar_IceShield_Insert01_Phase01`: 1.

## Acceptance Notes

- v0_240 queue enqueue still works: the admitted `TurnInsertAbility` creates a pending `QueueEntry` with source audit.
- v0_241 drain gate does not dequeue that entry because its `AbilityName` has no admitted standalone ability graph in Canonical IR.
- The blocked drain record preserves the queue unchanged and keeps the after snapshot equal to before.
- No runtime path maps `AbilityName` strings by hand.
- Queue dequeue source audit is ready for the first future executable `QueueResolutionIR`.

## Trust Matrix

- `queue_enqueue`: `trusted_for_current_scope`.
- `queue_resolution`: `trusted_for_current_scope` for distinguishing admitted vs blocked resolution from Canonical IR.
- `queue_drain`: `blocked`, current dependency is `queue_ability_graph_not_lowered_or_missing:Avatar_IceShield_Insert01_Phase01`.
- `full_inserted_action_execution`: `blocked`, requires admitted queue drain plus inserted action or standalone ability execution semantics.

## Remaining Blocked Dependencies

- Standalone ability graph lowering for queue-only `AbilityName` values.
- Priority ordering admission for inserted queue entries.
- Inserted action command construction and execution.
- Assistant ability resolution.
- Dynamic `SkillIndex` resolution for `TurnInsertAction`.
