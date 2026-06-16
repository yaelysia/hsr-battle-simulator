# v8 Damage Taxonomy Checkpoint v0_207

## Scope

This checkpoint fixes the v8 damage taxonomy before implementing full damage formulas.

- Attack type and damage formula family are now separate axes.
- Follow-up is treated only as an attack type, never as a damage formula family.
- Elation damage is treated as a mainline 4.0 damage formula family, not as a Simulated Universe blessing.
- Simulated Universe, Divergent Universe, and Currency War mechanics remain out of scope for this checkpoint.

## Implemented

- `ActionDefinitionIR` now exposes `damage_kind`, `damage_formula_family`, `element_type`, and `source_mode`.
- TBGD lowering preserves raw `AttackType` and `StanceDamageType`, while assigning a separate formula family.
- Global TBGD Elation fields are lowered as mechanic evidence:
  - `ElationDamageAddedRatio`
  - `ElationPointMax`
  - `ElationEchoPoint`
  - `ElationTime` / priority entries
- Coverage and fidelity matrices now include `formula_status.elation_damage`.
- `DamagePacket` now carries `attack_type`, `damage_formula_family`, `element_type`, and `source_trace`.
- `DamageSystem` dispatches direct / true damage / hp loss as executable HP deltas and records DoT, break, super-break, and Elation as blocked families for now.
- Static checks reject `follow_up` being encoded as a damage formula family.

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
```

Results:

- v0_200 ok=true
- v0_203 ok=true
- v0_204 ok=true
- v0_205 ok=true
- v0_206 ok=true
- v0_207 ok=true
- v0_207 direct damage transition replay ok=true
- v0_207 settlement traceability ok=true
- `ElationDamageAddedRatio` discovered and reported under `formula_status.elation_damage`
- Elation damage status is blocked with reason, not silently skipped

## Current Distance

Minimum usable battle route is still not ready. The simulator now has clean scenario input, identity resolution, action definition prelude, target/resource/timeline mutation flow, and damage taxonomy. It still lacks the first real TBGD-driven damage execution path, toughness reduction, break, status, triggers, queue actions, turn end, and kill/wave handling.

Approximate progress toward a minimal usable combat vertical slice: 18%.

Approximate progress toward game-faithful full combat replication: 6%-9%.

## Known Risks

- Elation damage formula is intentionally not executable yet; only TBGD evidence and blocked status are recorded.
- Direct damage still applies a resolved amount packet; formula construction from TBGD effects and modifiers is not complete.
- Follow-up source detection is not yet lowered from all character mechanics; this checkpoint only prevents taxonomy corruption.
