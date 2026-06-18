# v8 HP Loss Effect Checkpoint v0_226

## Scope

v0_226 closes the pending validation slimming work and promotes one real HP loss path from structural smoke to a trusted current-scope mechanism:

```text
LoseHPByRatio -> EffectIR.standard(kind=hp_loss_ratio) -> EffectRegistry -> DamagePacket(hp_loss) -> DamageSystem -> Mutation/Settlement
```

This stage does not add true damage, DoT, break, super-break, queues, per-hit triggers, or full floor rounding.

## Implemented

- `LoseHPByRatio` lowering now emits a standard hp-loss payload with `target_alias`, `ratio`, `ratio_type`, `floor`, raw formula fields, and source trace.
- Runtime executes only fixed or bound dynamic ratios for `RatioType in {"MaxHP", "CurrentHP"}`.
- HP loss is applied through `DamageSystem`, not by directly mutating HP in the effect handler.
- HP loss settlement is marked `bypasses_normal_multipliers=true` and carries no direct damage multiplier ledger terms.
- Mutation metadata includes effect source, opcode, ratio type, numeric evaluation result, and damage formula family for source audit.
- `RuntimeSourceAuditor` accepts effect-origin `hp_loss` only when the mutation can trace back to executable `EffectIR` source.
- `validate_v0_225` keeps default output light; full diagnostics and matrices are opt-in with `--write-diagnostics --write-matrices`.

## Real Source Sample

The v0_226 positive sample is selected by structured predicates, not by role name, fixed action id, fixed file name, or fixed hash.

```json
{
  "opcode": "LoseHPByRatio",
  "coverage_status": "executable",
  "ratio_kind": "fixed",
  "ratio_type": "MaxHP",
  "target_alias": "Caster",
  "source_path": "Config/ConfigAbility/Monster/Monster_W2_Lycan_01_Ability.json",
  "raw_id": "MMonster_W2_Lycan_01_MainStoryModuRevive"
}
```

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_215 --output-dir /tmp/hsr_v8_regression_v0_215
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_225 --output-dir /tmp/hsr_v8_regression_v0_225_diag --write-diagnostics --write-matrices
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_226 --output-dir validation_outputs_v0_226
git diff --check
```

Results:

- compileall: passed
- v0_215: `ok=true`
- v0_225 default slim validation: `ok=true`
- v0_225 diagnostics/matrices validation: `ok=true`
- v0_226: `ok=true`
- `git diff --check`: passed

## v0_226 Trust Matrix

- `hp_loss`: `trusted_for_current_scope`
  - Scope: `LoseHPByRatio` with fixed or bound dynamic `MaxHP` / `CurrentHP` ratio.
  - Source audit covered: yes.
  - Negative cases covered: dynamic hash unbound, `Floor=true`, unknown ratio type, unsupported target alias.
- `true_damage`: `structural_only`
  - Bypass semantics are preserved, but v0_226 still has no admitted executable TBGD true-damage source.

## Remaining Risks

- `Floor=true` remains blocked until rounding semantics are proven from source.
- Dynamic hash HP loss is executable only when the binding is present; unbound hashes block and leave state unchanged.
- Unknown ratio types and unsupported target aliases block and leave state unchanged.
- HP loss does not imply DoT, break, super-break, true damage, queues, or per-hit trigger support.
