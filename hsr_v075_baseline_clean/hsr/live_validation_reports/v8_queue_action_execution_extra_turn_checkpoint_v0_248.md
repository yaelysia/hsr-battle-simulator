# v8 v0_248 Queue Action Execution and Extra-Turn Closure Checkpoint

## Summary

This checkpoint moves the queue/window family from classification and enqueue into admitted execution for the currently provable scope.

Implemented:

- Manual ultimate request can enqueue, drain, and execute through `CombatExecutor.execute(source="queue")`.
- Manual ultimate drain now has runtime route-input queue resolution without pretending it is TBGD Canonical IR.
- Queue child action transitions retain parent queue entry, queue intent, queue resolution, priority, window plan, and target resolution.
- Manual ultimate negative cases keep state unchanged: insufficient energy at enqueue, insufficient energy at drain, invalid target, and non-ultimate action.
- Counter/follow-up/extra-turn sources are still handled honestly: admitted child execution is required for trusted status; otherwise validation reports concrete blockers.

Not implemented:

- No synthetic follow-up or extra-turn positive case was added.
- Current TBGD lowering has no admitted `extra_turn` window source.
- Current counter/follow-up windows did not enqueue under admitted listener execution in the validation context, so execution remains blocked with source-specific blockers.
- Ultimate energy spend mutation is not implemented because the energy cost mutation source is not yet admitted; current scope performs source-audited energy preflight.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_242 --output-dir /tmp/hsr_v8_regression_v0_242
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_245 --output-dir /tmp/hsr_v8_regression_v0_245
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_247 --output-dir /tmp/hsr_v8_regression_v0_247
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_248 --output-dir /tmp/hsr_v8_v0_248
git diff --check
```

Results:

- v0_225: `ok=True`
- v0_242: `ok=True`
- v0_245: `ok=True`
- v0_247: `ok=True`
- v0_248: `ok=True`
- `git diff --check`: pass

v0_248 key checks:

- `manual_ultimate_execution.ok=True`
- `enqueue_source_audit=True`
- `drain_source_audit=True`
- `child_action_transition_present=True`
- `child_action_source_queue=True`
- `child_action_has_queue_parent=True`

Queue window family counts:

- `assistant`: 4
- `counter`: 7
- `immediate`: 1
- `insert_ability`: 1124
- `insert_action`: 65
- `ultimate`: 17

Executable family counts:

- `counter`: 6
- `insert_ability`: 156
- `ultimate`: 2

## Trust Status

- `queue_ultimate_execution`: trusted for current scope.
- `queue_enqueue / queue_priority / queue_resolution / queue_window`: no regression.
- `queue_counter_execution`: blocked; executable counter windows exist, but the admitted listener validation context did not enqueue.
- `queue_follow_up_execution`: blocked; no admitted follow-up child action execution sample in current TBGD scope.
- `extra_turn_execution`: blocked; no mainline queue source classified as extra-turn by admitted QueueWindowIR evidence.

## Remaining Risks

- Full automatic ultimate interrupt ordering still needs source admission beyond manual route input.
- Ultimate energy spend needs a real energy-cost mutation source; current scope only proves energy preflight.
- Counter/follow-up execution needs admitted listener event context and downstream action resolution, not manual queue fabrication.
- Extra-turn remains dependent on discovering or lowering a real mainline extra-turn source.
