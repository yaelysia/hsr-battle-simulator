# v8 DynamicValueStore Checkpoint v0_216

## Scope

- Added stable `global_flags.dynamic_value_store` to snapshots and snapshot completeness validation.
- Added a runtime DynamicValueStore helper for replayable dynamic value writes and hash/name indexes.
- Extended `NumericEvaluationContext` with ordered binding sources:
  1. current explicit runtime bindings,
  2. status instance dynamic values,
  3. `global_flags.dynamic_value_store`.
- Standardized TBGD `SetDynamicValue` and `SetDynamicValueByModifierValue` into Canonical IR payloads.
- Registered runtime handlers for both opcodes. Handlers only emit `Mutation` + settlement records for dynamic value state; they do not directly change HP, energy, resources, damage, or status rules.
- Updated effect numeric evaluation so Heal/Shield/ModifySPNew/mechanism bar numeric fields use the same evaluator binding path.

## Coverage

From `validation_outputs_v0_216/coverage_matrix_v0_216.json`:

- `SetDynamicValue`: lowered `8406`, executable `5596`, blocked `2810`.
- `SetDynamicValueByModifierValue`: lowered `1169`, executable `991`, blocked `178`.
- `ModifySPNew`: lowered `538`, executable `192`.
- `InitShield`: lowered `64`, executable `49`.
- `HealHP`: lowered `264`, executable `33`.

The v0_216 main sample is selected by structured predicates: opcode, mainline source, standardized payload, supported target alias, and fixed or runtime-bindable numeric expression. It is not selected by role name, file name, fixed hash, or fixed formula result.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir /tmp/hsr_v8_regression_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir /tmp/hsr_v8_regression_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir /tmp/hsr_v8_regression_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir /tmp/hsr_v8_regression_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir /tmp/hsr_v8_regression_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir /tmp/hsr_v8_regression_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir /tmp/hsr_v8_regression_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir /tmp/hsr_v8_regression_v0_209
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_210 --output-dir /tmp/hsr_v8_regression_v0_210
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_211 --output-dir /tmp/hsr_v8_regression_v0_211
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_212 --output-dir /tmp/hsr_v8_regression_v0_212
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_213 --output-dir /tmp/hsr_v8_regression_v0_213
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_214 --output-dir /tmp/hsr_v8_regression_v0_214
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_216 --output-dir validation_outputs_v0_216
```

Result: all validations returned `ok=True`.

v0_216 checks:

- DynamicValueStore mutation replay: `ok=True`.
- Snapshot completeness: `ok=True`.
- Transition contract: `ok=True`.
- Settlement traceability: `ok=True`.
- Static checks: `ok=True`.
- Store-backed numeric evaluator binding: `ok=True`.
- Unbound dynamic hash and unsupported postfix remain blocked with explicit reasons.
- Direct damage, true damage, HP loss, and status modifier ledger regressions remain passing.

## Remaining Risks

- `DynamicKey` is often a TBGD string key, while many formulas read numeric dynamic hashes. v0_216 does not invent a string-to-hash mapping. It records both name and hash when available, and only resolves what the store can prove.
- `SetDynamicValueByModifierValue` currently supports structurally clear `Layer` and `LifeTime` source values. Other modifier value types remain blocked.
- Complex postfix expressions and unsupported formula families remain blocked; no formula guessing was added.
- This still does not implement full DoT, break, super-break, action queue, global listener, or complete status duration tick semantics.
