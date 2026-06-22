# v8 Scheduler Loop Turn Lifecycle Checkpoint v0_244

## Summary

v0_244 extends the v0_243 timeline scheduler from separate one-step helpers into a single `CombatScheduler.step()` lifecycle boundary.

The scheduler now coordinates:

```text
queue drain priority -> natural AV advance -> turn begin -> admitted manual action -> turn end/reset
```

Action mechanics still belong to `CombatExecutor`; the scheduler only owns turn ordering, lifecycle records, and blocked paths.

## Implemented

- Added `CombatScheduler.step(state, command=None)`.
- Added queue-first scheduling through the existing admitted queue drain path.
- Added manual/route action execution only when `command.actor_id` matches the current turn owner.
- Added process-only blocked transition for manual actor mismatch, leaving the snapshot unchanged.
- Preserved enemy turns without admitted AI as process-only blocked, leaving the snapshot unchanged.
- Added combined scheduler transition for regular manual turns, with child turn begin, action, and turn end transitions.
- Added parent scheduler metadata to child action commands.
- Added explicit unsupported lifecycle hook records for duration tick, extra turn, ultimate, and interrupt.
- Added `validate_v0_244`.

## Validation Results

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_243 --output-dir /tmp/hsr_v8_regression_v0_243
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_244 --output-dir /tmp/hsr_v8_v0_244
git diff --check
```

All checks passed.

v0_244 checked:

- Multi-unit state can run through `CombatScheduler.step()` to select the actor, execute a matching manual command, end the turn, and reset AV.
- Manual command actor mismatch does not execute the action and leaves the snapshot unchanged.
- Enemy turn without AI policy stays blocked and leaves the snapshot unchanged.
- Admitted queue entry is processed before natural AV advance.
- Scheduler, child action, and queue transitions pass settlement traceability, snapshot replay, and source audit.
- Unsupported duration tick, extra turn, ultimate, and interrupt hooks are process-only blocked.

## Remaining Boundaries

- `enemy_ai_action` remains blocked until enemy AI action and target selection are admitted.
- `extra_turn`, `ultimate`, and `interrupt` remain blocked until their queue/window priority semantics are admitted.
- Full status duration decrement/expire remains blocked until lifecycle source admission is complete.
- Follow-up, counter, full inserted action ordering, waves, and bounce RNG are not part of this checkpoint.
