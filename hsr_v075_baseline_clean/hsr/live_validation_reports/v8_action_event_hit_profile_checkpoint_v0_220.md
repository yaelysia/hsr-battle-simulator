# v8 Action Event IR and Hit Profile Checkpoint v0_220

## Scope

- Added Canonical IR execution structures:
  - `ActionEventIR` for action phase steps, target profile, hit profile references, source trace, and derived status.
  - `HitProfileIR` for hit index, target group, multiplier expression/source, stance evidence, damage formula family, element, coverage, and numeric fidelity status.
- TBGD lowering now emits `ActionEventIR` and `HitProfileIR` from action rows using `ParamList`, `ShowDamageList`, `ShowStanceList`, `SkillEffect`, `AttackType`, and `StanceDamageType`.
- `RuleBook` now exposes `action_event()`, `require_action_event()`, and `hit_profiles_for_action()`.
- `CombatExecutor` now builds `ActionExecutionPlan` from `ActionEventIR + HitProfileIR + TargetResolution`.
- `DamagePacket` now carries `hit_profile_id`, `scaling_ratio`, and `hit_source_trace`; direct damage formula consumes packet scaling instead of reading action definition `ParamList`.
- Runtime static checks now guard core/rules/systems from direct `param_list[0]` and runtime `ShowDamage/ShowStance` inference.
- Existing validation fixtures that manually constructed minimal IR or direct damage packets were upgraded to provide the new IR/hit profile contract instead of adding runtime fallback.

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
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_217 --output-dir /tmp/hsr_v8_regression_v0_217
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_218 --output-dir /tmp/hsr_v8_regression_v0_218
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_219 --output-dir /tmp/hsr_v8_regression_v0_219
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_220 --output-dir validation_outputs_v0_220
```

Result: all validations returned `ok=True`.

v0_220 summary:

- TBGD discovery files: `8683`.
- Canonical IR action definitions: `6949`.
- Canonical IR action events: `6949`.
- Canonical IR hit profiles: `5132`.
- `sampled.ability_files=false`, `sampled.entity_tables=false`.
- `action_event_ir`, `hit_profile_ir`, `runtime_hit_profile_path`, `preflight_commit_gate`, transition contract, settlement traceability, replay, and static checks all passed.

## Remaining Risks

- `ActionEventIR` is still derived from action row fields; it is a cleaner IR boundary, not yet proven to be the complete native game action event schema.
- `ShowDamageList` and `ShowStanceList` are lowered as evidence only. They are not treated as executable numeric truth until their semantics are confirmed.
- Multi-param action rows and multi-hit routing are represented structurally, but full multi-hit execution is not implemented.
- AOE/blast multi-target packets remain `numeric_fidelity_status=structural_only`; target-group multipliers are not final.
- Trigger execution remains actor/primary-target local; per-hit trigger context is still not implemented.
- Bounce RNG, toughness damage, break, DoT, super-break, and full queue/turn lifecycle remain future work.
