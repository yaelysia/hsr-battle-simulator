# v8 ActionDefinition IR Checkpoint v0_206

## Scope

This checkpoint makes action level data a first-class Canonical IR source.
The executor no longer reads temporary scenario metadata for skill point or
energy changes. It resolves `action_id + action_level` through `RuleBook` and
derives action prelude resources from TBGD-lowered `ActionDefinitionIR`.

This checkpoint still does not implement direct damage, toughness damage,
break, statuses, trigger windows, queue insertion, or full turn close.

## Implemented

- Added `ActionDefinitionIR` to Canonical IR.
- Split action identity from action level data:
  - `RuleEntity` keeps identities such as `avatar_skill:101401`.
  - `ActionDefinitionIR` keeps level-specific definitions such as
    `action_def:avatar_skill:101401:10`.
- Added RuleBook action definition queries:
  - `action_definition`
  - `require_action_definition`
  - `action_levels`
  - `action_definition_source_trace`
- Made scenario route `action_level` explicit and required.
- Updated scenario identity validation to reject missing or unknown action
  definitions before state build.
- Updated executor resource prelude to derive:
  - `BPNeed > 0` as skill point cost.
  - `BPAdd > 0` as skill point gain.
  - `SPBase` as energy gain.
- Added action definition process-only settlement records.
- Added definition id and TBGD source trace to resource mutation metadata.
- Added `validate_v0_206`.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir validation_outputs_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir validation_outputs_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir validation_outputs_v0_206
```

Result:

- v0_200 validation: `ok=true`
- v0_203 validation: `ok=true`
- v0_204 validation: `ok=true`
- v0_205 validation: `ok=true`
- v0_206 validation: `ok=true`
- Snapshot completeness: `ok=true`
- Transition contract: `ok=true`
- Replay: `ok=true`
- Static checks: `ok=true`

v0_206 action definition checks:

- Canonical IR action definitions: `792`
- `avatar_skill:101401` levels: `1..10`
- Level 10 definition: `action_def:avatar_skill:101401:10`
- Source: `ExcelOutput/AvatarSkillConfigLD.json`
- Source row: `65`
- Level 10 `ParamList`: `{"Value": 1.4}`
- Resource mapping:
  - `BPNeed = -1.0`
  - `BPAdd = 1.0`
  - `SPBase = 20.0`
- Smoke action resource result:
  - skill points: `3 -> 4`
  - energy: `60 -> 80`

Negative checks:

- Missing `action_level` is rejected by scenario loading.
- `avatar_skill:101401` level `99` is rejected by identity validation.
- `avatar_skill:101402` level `10` at `0` skill points produces a resource
  failure and no skill point mutation.

TBGD / IR summary:

- Discovery files: `8667`
- Canonical IR entities: `2060`
- Canonical IR action definitions: `792`
- Canonical IR triggers: `1665`
- Canonical IR effects: `3503`
- Canonical IR conditions: `1309`
- Canonical IR formulas: `3151`
- Coverage opcode count: `1145`

Generated outputs:

- `validation_outputs_v0_206/canonical_ir_v0_206.json`
- `validation_outputs_v0_206/coverage_matrix_v0_206.json`
- `validation_outputs_v0_206/fidelity_matrix_v0_206.json`
- `validation_outputs_v0_206/sample_battle_state_v0_206.json`
- `validation_outputs_v0_206/sample_transition_v0_206.json`
- `validation_outputs_v0_206/validation_summary_v0_206.json`

## Progress

Current v8 status:

- Complete so far: TBGD discovery, Canonical IR skeleton, scenario identity,
  full transition/snapshot contract, action prelude, and rule-sourced action
  definitions.
- Distance to minimum usable battle slice: still needs direct damage, toughness
  damage, basic hit settlement, and action close. Rough progress: about `20%`.
- Distance to near game-fidelity simulator: still needs status/modifier system,
  trigger windows, queues/ult insertion, full turn timeline, break/DoT/super
  break, enemy AI, wave handling, equipment/relic/light cone, and extensive
  route replay. Rough progress: about `8%-10%`.

## Remaining Risk

- ActionDefinition resource mapping is now explicit and validated, but damage
  formula semantics are not yet executable.
- Target modes are lowered as coarse labels only; target expansion for
  single/blast/aoe/bounce is not implemented.
- Scenario panel stats are still user-provided initial state, not fully derived
  from TBGD promotion/equipment rules.
