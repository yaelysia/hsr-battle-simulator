# v8 Direct Damage Formula Checkpoint v0_209

## Scope

This checkpoint replaces the v0_208 temporary direct-damage amount with a structured formula path.

- Direct damage now resolves through formula input/result objects instead of executor-local `attack * ratio` code.
- Direct damage settlement includes formula result, crit resolution, and modifier ledger.
- Crit defaults to deterministic actual resolution with an RNG event; scenario metadata may force `crit` or `noncrit`.
- True damage and HP loss still bypass normal multipliers and do not emit direct-damage ledgers.

## Implemented

- Added direct formula contract objects: formula input/result, bucket, term, ledger, and crit resolution.
- Added direct buckets for crit, damage bonus, defense, resistance, damage taken, damage reduction, and toughness state.
- Executor now passes the action definition and crit metadata to `DamageSystem`; it no longer computes direct amount itself.
- Damage transition now carries `rng_events` from direct crit resolution.
- Resistance fallback is explicit: selected resistance is applied and non-selected fallback is skipped with reason.
- v0_208 taxonomy validation now permits unknown families only when they are not executable, while still banning follow-up as a damage family.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_203 --output-dir validation_outputs_v0_203
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_204 --output-dir validation_outputs_v0_204
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_205 --output-dir validation_outputs_v0_205
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_206 --output-dir validation_outputs_v0_206
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_207 --output-dir validation_outputs_v0_207
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_208 --output-dir validation_outputs_v0_208
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_209 --output-dir validation_outputs_v0_209
```

Results:

- v0_200 ok=true
- v0_203 ok=true
- v0_204 ok=true
- v0_205 ok=true
- v0_206 ok=true
- v0_207 ok=true
- v0_208 ok=true
- v0_209 ok=true
- v0_209 replay ok=true, mutations=7
- v0_209 settlement traceability ok=true, checked_records=10
- v0_209 forced crit/noncrit ok=true
- v0_209 deterministic RNG reproducibility ok=true

Key v0_209 sample:

- Direct formula final damage: `5552.704376470589`
- Direct buckets covered: crit, damage_bonus, defense, resistance, damage_taken, damage_reduction, toughness_state
- `v0_208_base_amount_only` absent from direct transition
- Static checks ok=true

## Current Distance

Minimum usable battle route is closer, but still not ready. v8 now has TBGD action identity, target/resource/timeline, direct damage formula, formula ledger, RNG crit event, and replayable HP mutation in one transition.

Approximate progress toward a minimal usable combat vertical slice: 26%.

Approximate progress toward game-faithful full combat replication: 8%-11%.

## Known Risks

- Direct damage is still single-hit only.
- Status modifiers are not yet a real runtime source for ledger terms.
- Target mode fan-out for blast/aoe/bounce is not implemented.
- Toughness reduction, break, DoT, super-break, turn end, kill, wave, and queue processing are still missing.
- Deterministic RNG is reproducible, but later RNG state advancement policy still needs to be formalized.
