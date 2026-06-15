# v8 Scenario & Identity Checkpoint v0_204

## Scope

This checkpoint adds the first v8 scenario entrypoint. Users can describe a
minimal battle setup and route command in a v8-only JSON scenario, and the
runtime validates all entity/action references through Canonical IR.

This checkpoint does not implement real damage or restore C0-C8 replay.

## Implemented

- Expanded TBGD lowering with avatar, avatar skill, avatar promotion, monster,
  monster template, and monster skill entities.
- Added v8 scenario schema, JSON loader, identity resolver, and state builder.
- Added a minimal scenario using real TBGD/IR references:
  - `avatar:1014`
  - `avatar_skill:101401`
  - `monster:1002011`
- Added RuleBook helpers for entity type checks and source traces.
- Added `validate_v0_204`.
- Added positive and negative identity checks:
  - missing entity reference is rejected.
  - wrong action type is rejected.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir validation_outputs_v0_204
```

Result:

- v0_200 validation: `ok=true`
- v0_203 validation: `ok=true`
- v0_204 validation: `ok=true`
- Scenario identity: `ok=true`
- Snapshot completeness: `ok=true`
- Transition contract: `ok=true`
- Replay: `ok=true`
- Static checks: `ok=true`

TBGD / IR summary:

- Discovery files: `8667`
- Canonical IR entities: `2643`
- Canonical IR triggers: `1665`
- Canonical IR effects: `3503`
- Canonical IR conditions: `1309`
- Canonical IR formulas: `3151`
- Coverage opcode count: `1145`

Generated outputs:

- `validation_outputs_v0_204/canonical_ir_v0_204.json`
- `validation_outputs_v0_204/coverage_matrix_v0_204.json`
- `validation_outputs_v0_204/fidelity_matrix_v0_204.json`
- `validation_outputs_v0_204/sample_battle_state_v0_204.json`
- `validation_outputs_v0_204/sample_transition_v0_204.json`
- `validation_outputs_v0_204/validation_summary_v0_204.json`

## Remaining Risk

- Scenario panel values are accepted as user-provided initial state, not derived
  fully from game formulas yet.
- Direct damage and real action lifecycle mechanics are still not implemented.
- The next stage should implement target/resource/timeline basics while keeping
  scenario identity and snapshot contracts green.

