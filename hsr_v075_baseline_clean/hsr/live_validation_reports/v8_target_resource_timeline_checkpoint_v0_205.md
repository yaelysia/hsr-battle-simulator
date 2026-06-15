# v8 Target / Resource / Timeline Checkpoint v0_205

## Scope

This checkpoint turns the v8 executor from an empty transaction shell into the
first executable action prelude. It resolves explicit targets, opens the action
window, applies resource mutations, records settlement traceability, and keeps
snapshot replay deterministic.

This checkpoint still does not implement direct damage, toughness damage,
break, statuses, trigger windows, or queue insertion.

## Implemented

- Added structured target resolution through `TargetSystem`:
  - selected/legal/rejected targets are recorded in `TargetResolution`.
  - unknown, defeated, same-side, and unknown-actor failures are explicit.
- Added `ResourcePlan` / `ResourcePlanResult`:
  - supports skill point delta and actor energy gain.
  - insufficient skill points fail without generating a silent clamp mutation.
- Added `TimelinePlan` / `TimelinePlanResult`:
  - opens action window.
  - increments `event_index`.
  - writes `global_flags.current_window` and `global_flags.turn_owner_id`.
  - can reset actor AV through a mutation.
- Upgraded `CombatExecutor.execute()` to orchestrate target, resource, and
  timeline systems into one mutation-backed transition.
- Extended the identity smoke scenario route metadata with temporary v0_205
  prelude inputs:
  - `skill_point_delta`
  - `energy_gain`
  - `reset_actor_av`
- Added `validate_v0_205` with positive and negative checks.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir validation_outputs_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir validation_outputs_v0_205
```

Result:

- v0_200 validation: `ok=true`
- v0_203 validation: `ok=true`
- v0_204 validation: `ok=true`
- v0_205 validation: `ok=true`
- Snapshot completeness: `ok=true`
- Transition contract: `ok=true`
- Replay: `ok=true`
- Static checks: `ok=true`

v0_205 action prelude:

- Mutation count: `5`
- Settlement record count: `7`
- Target records: `1`
- Timeline mutation-linked records: `4`
- Resource mutation-linked records: `1`
- Selected target: `enemy:target`
- Rejected target negative case: `enemy:missing`
- Insufficient skill point negative case: no skill point mutation generated

TBGD / IR summary:

- Discovery files: `8667`
- Canonical IR entities: `2643`
- Canonical IR triggers: `1665`
- Canonical IR effects: `3503`
- Canonical IR conditions: `1309`
- Canonical IR formulas: `3151`
- Coverage opcode count: `1145`

Generated outputs:

- `validation_outputs_v0_205/canonical_ir_v0_205.json`
- `validation_outputs_v0_205/coverage_matrix_v0_205.json`
- `validation_outputs_v0_205/fidelity_matrix_v0_205.json`
- `validation_outputs_v0_205/sample_battle_state_v0_205.json`
- `validation_outputs_v0_205/sample_transition_v0_205.json`
- `validation_outputs_v0_205/validation_summary_v0_205.json`

## Remaining Risk

- v0_205 action cost and energy gain are scenario metadata inputs, not yet
  lowered from Canonical IR action definitions.
- Target legality is still basic and does not yet model blast/bounce/aoe target
  modes, taunt, lock-on, weakness lock, or summon ownership.
- Timeline only opens an action window; full AV scheduling, turn close, extra
  turns, ult insertion, and queue drain remain future work.
