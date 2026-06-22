# v8 Queue Intent Checkpoint v0_240

## Scope

This checkpoint adds the queue enqueue source chain for v8:

```text
TBGD Ability/Status Callback Task
-> QueueIntentIR
-> EventDispatchSystem / StatusCallbackSystem
-> QueueSystem.enqueue()
-> Mutation / Settlement / SourceAudit
```

This stage only admits queue insertion intent and pending queue state mutation. It does not drain queues, execute inserted actions, resolve ultimate priority, implement follow-up/counter actions, enemy AI, or bounce RNG.

## Implemented

- Added `QueueIntentIR` to Canonical IR and RuleBook indexes.
- Lowered `TurnInsertAbility`, `TurnInsertAction`, and `TurnInsertAssistantAbility` tasks into `QueueIntentIR`.
- Added queue intent coverage counts and blocked reason counts.
- Added structured `QueueEntry` JSON and made `QueueSystem.enqueue()` the only runtime queue mutation entry.
- Routed executable queue intent execution through status callback/event dispatch.
- Updated queue source audit policy so queue mutations must trace to executable `QueueIntentIR`.
- Added `validate_v0_240`.

## Validation Result

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_227 --output-dir /tmp/hsr_v8_regression_v0_227
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_235 --output-dir /tmp/hsr_v8_regression_v0_235
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_238 --output-dir /tmp/hsr_v8_regression_v0_238
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_240 --output-dir /tmp/hsr_v8_v0_240
git diff --check
```

Results:

- `compileall`: passed.
- `validate_v0_225`: `ok=True`.
- `validate_v0_227`: `ok=True`.
- `validate_v0_235`: `ok=True`.
- `validate_v0_238`: `ok=True`.
- `validate_v0_240`: `ok=True`.
- `git diff --check`: passed.

## Queue Coverage

- `QueueIntentIR` lowered: 1218.
- executable: 1.
- blocked: 1217.
- opcode counts:
  - `TurnInsertAbility`: 1149.
  - `TurnInsertAction`: 65.
  - `TurnInsertAssistantAbility`: 4.

Blocked reason counts:

- `queue_intent_source_mode_not_admitted`: 1205.
- `queue_actor_target_alias_not_admitted:missing`: 6.
- `queue_ability_target_alias_not_admitted:ModifierOwnerSkillTargetEntityList`: 3.
- `queue_abort_policy_not_admitted`: 2.
- `queue_insert_assistant_ability_not_admitted`: 1.

## Acceptance Notes

- A real mainline `TurnInsertAbility` intent is executable and creates a `queue_system` mutation through dispatcher/callback execution.
- The queue mutation includes `queue_intent_id`, source task id, opcode, target resolution, source trace, and a structured `QueueEntry`.
- Queue settlement is mutation-linked and source-audited.
- Blocked queue intent negative case leaves the after snapshot unchanged and produces no queue mutation.
- Pending queue entries are marked `drain_status=not_admitted`.

## Remaining Blocked Dependencies

- Queue drain remains blocked until action/ability resolution and priority ordering are admitted.
- Full inserted action execution remains blocked until drain ordering, inserted `ActionCommand` construction, and interrupt/ultimate priority semantics are admitted.
- `TurnInsertAction` dynamic `SkillIndex`, assistant ability resolution, unknown priority semantics, unsupported target aliases, and abort behavior remain blocked rather than guessed.

