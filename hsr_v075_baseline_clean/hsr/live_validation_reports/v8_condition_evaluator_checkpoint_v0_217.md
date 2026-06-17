# v8 Condition Evaluator Checkpoint v0_217

## Scope

- Added structured `ConditionEvaluationResult` for condition execution.
- Trigger windows now record condition `ok/result/reason/details/source_trace` instead of only bool/None.
- Condition evaluation context now carries runtime state, owner/status detail, actor/target ids, event payload, and numeric binding sources.
- Runtime support added for these generic TBGD predicates:
  - `ByCurrentSkillType`
  - `ByAttackType`
  - `ByTargetTeam`
  - `ByIsContainModifier`
  - `ByCompareHPRatio`
  - `ByCompareDynamicValue`
  - `ByCompareModifierValue`
  - `ByCompareTarget`
  - `ByAnd`
  - `ByAny`
  - `ByNot`
- `Inverse=true` is handled once at the common condition entrypoint.
- TBGD lowering now marks a condition executable only when the predicate payload is structurally supported. Unknown or complex predicates remain blocked/audit-only.

## Coverage

From `validation_outputs_v0_217/coverage_matrix_v0_217.json`:

- `ByCurrentSkillType`: lowered `465`, executable `419`
- `ByAttackType`: lowered `625`, executable `625`
- `ByTargetTeam`: lowered `2843`, executable `2828`
- `ByIsContainModifier`: lowered `1862`, executable `1219`
- `ByCompareHPRatio`: lowered `267`, executable `251`
- `ByCompareDynamicValue`: lowered `4445`, executable `1102`
- `ByCompareModifierValue`: lowered `236`, executable `155`
- `ByCompareTarget`: lowered `254`, executable `119`
- `ByAnd`: lowered `3687`, executable `682`
- `ByAny`: lowered `823`, executable `172`
- `ByNot`: lowered `51`, executable `23`

Validation samples are selected by opcode, mainline source, executable coverage, and payload shape. They are not selected by role name, file name, fixed hash, or fixed formula result.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_216 --output-dir /tmp/hsr_v8_regression_v0_216
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_217 --output-dir validation_outputs_v0_217
```

Result: all validations returned `ok=True`.

v0_217 checks:

- Real mainline condition samples for all supported predicate opcodes evaluated with structured results.
- A blocked mainline condition remains non-executable with explicit reason.
- Status modifier ledger, direct damage, true damage, and HP loss regressions remain passing.
- Static checks and snapshot completeness remain passing.

## Remaining Risks

- `ByTargetTeam` currently maps `TeamLight` to ally/summon and `TeamDark` to enemy. This is explicit and audited, but still needs confirmation against more game event contexts.
- Complex predicate families remain blocked: random chance, rank activation, monster phase/id/rank, behavior flags, custom strings, full target lists, and ability-property comparisons.
- `ByCompareDynamicValue` can only evaluate when the DynamicValueStore/status bindings can prove the value. Missing bindings stay blocked.
- Compound predicates only execute when every child predicate is structurally supported.
