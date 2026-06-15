# v8 Snapshot & Fidelity Contract v0_203

## Scope

This checkpoint turns v8 snapshot completeness and source-fidelity expectations
into executable validation code. It does not implement combat mechanics yet.

## Implemented

- Added snapshot completeness validation.
- Added transition completeness validation.
- Added settlement traceability validation.
- Added mechanic fidelity matrix for discovered/lowered/executable/blocked
  TBGD mechanisms.
- Added stable IDs for mutations, events, and RNG events.
- Added explicit target resolution and RNG event fields to `BattleTransition`.
- Expanded v8 snapshots with stable empty structures for future mechanics.
- Strengthened runtime static checks against legacy and raw-source leakage.
- Added `validate_v0_203`.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
```

Result:

- v0_200 validation: `ok=true`
- v0_203 validation: `ok=true`
- Snapshot completeness: `ok=true`
- Transition contract: `ok=true`
- Settlement traceability: `ok=true`
- Replay: `ok=true`
- Static checks: `ok=true`

TBGD / IR summary:

- Discovery files: `8667`
- Canonical IR entities: `415`
- Canonical IR triggers: `1665`
- Canonical IR effects: `3503`
- Canonical IR conditions: `1309`
- Canonical IR formulas: `3151`
- Coverage opcode count: `1145`

Fidelity summary:

- Opcode lifecycle counts:
  - blocked: `861`
  - discovered_only: `60`
  - executable: `1`
  - lowered: `223`
- Event lifecycle counts:
  - discovered_only: `91`
  - lowered: `110`

Generated outputs:

- `validation_outputs_v0_203/tbgd_discovery_v0_203.json`
- `validation_outputs_v0_203/canonical_ir_v0_203.json`
- `validation_outputs_v0_203/coverage_matrix_v0_203.json`
- `validation_outputs_v0_203/fidelity_matrix_v0_203.json`
- `validation_outputs_v0_203/sample_transition_v0_203.json`
- `validation_outputs_v0_203/validation_summary_v0_203.json`

## Remaining Risk

- v0_203 proves the contract shape and validation gates, not combat accuracy.
- Most TBGD mechanisms remain blocked or lowered-only.
- The next stage should build scenario and identity resolution without weakening
  the snapshot and fidelity gates introduced here.

