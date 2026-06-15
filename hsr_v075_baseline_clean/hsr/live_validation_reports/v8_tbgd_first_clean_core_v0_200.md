# v8 TBGD-First Clean Core Baseline v0_200

## Scope

This checkpoint starts a new independent rewrite line under
`simulator_v8_clean_core/`. The old v7 simulator and old model pack are not used
as v8 rule inputs. v7 remains only as a reference baseline for future numeric
regression.

The v8 source of truth is:

```text
turnbasedgamedata-main -> TBGD compiler -> Canonical IR -> Combat Core
```

## Implemented

- Added v8 package skeleton with explicit `core`, `rules`, `systems`, `tbgd`,
  `tools`, `scenarios`, and `tests` boundaries.
- Added `BattleState`, `UnitState`, `ActionCommand`, `ActionTransaction`,
  `Mutation`, `BattleTransition`, and `ActionSettlement`.
- Added `MutationReducer` and snapshot replay validation.
- Added Canonical IR dataclasses with `source_path`, `raw_type`, `raw_id`, and
  `evidence` on every lowered rule object.
- Added TBGD discovery for default domains:
  `ExcelOutput`, `Config/ConfigAbility`, `Config/ConfigGlobalModifier`,
  `Config/ConfigSummonUnit`, `Config/ConfigCharacter`, and `Config/ConfigAI`.
- Added conservative TBGD lowering from selected combat Excel tables and ability
  callbacks.
- Added coverage matrix with explicit status categories:
  `executable`, `supported_alias`, `audit_only`, `unsupported`, and
  `skipped_with_reason`.
- Added static checks to keep v8 runtime isolated from legacy simulator runtime.

## Validation

Commands:

```bash
python3 -m compileall -q simulator_v8_clean_core
python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

Result:

- Validation ok: `true`
- TBGD discovery files: `8667`
- Canonical IR entities: `415`
- Canonical IR triggers: `1665`
- Canonical IR effects: `3503`
- Canonical IR conditions: `1309`
- Canonical IR formulas: `3151`
- Coverage opcode count: `1145`
- Static checks: `ok`
- Snapshot replay: `ok`

Generated outputs:

- `validation_outputs_v0_200/tbgd_discovery_v0_200.json`
- `validation_outputs_v0_200/canonical_ir_v0_200.json`
- `validation_outputs_v0_200/coverage_matrix_v0_200.json`
- `validation_outputs_v0_200/validation_summary_v0_200.json`

## Current Limitations

- v0_200 is a clean structural baseline, not a complete HSR combat
  implementation.
- Most GameCore opcodes are still `audit_only` or `unsupported`; this is
  intentional until their mechanics are implemented explicitly.
- Route replay and C0-C8 numeric recovery are not part of this checkpoint.
- Formula lowering records postfix expressions but does not yet execute them
  except simple fixed values in the evaluator.

## Next Step

Implement the first executable HSR action slice in v8: action command ->
target resolution -> skill point/energy mutation -> direct damage mutation ->
settlement -> snapshot replay.

