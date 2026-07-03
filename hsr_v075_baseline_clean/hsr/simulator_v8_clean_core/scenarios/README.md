# v8 scenarios

v8 scenarios are intentionally separate from the old compiled case format.

A scenario may hand-write battle setup and route commands, but character,
enemy, skill, status, equipment, and mechanism references must point to TBGD
IDs or Canonical IR IDs. Old model-pack records are not valid v8 rule inputs.

Minimal examples live under `examples/` and are validated by
`simulator_v8_clean_core.tools.validate_v0_204`.

## P1-8 battle setup

`ScenarioLoader -> ScenarioSpec -> ScenarioStateBuilder` is the only supported
scenario entry for v8. P1-8 adds a canonical `battle_setup` object while keeping
the existing root-level fields as legacy aliases:

```json
{
  "battle_setup": {
    "resources": {"skill_points": 2, "max_skill_points": 5},
    "wave": {"kind": "wave_definition", "wave_definition_ref": "...", "wave_index": 0},
    "timeline": {"mode": "explicit_action_values", "action_values": {"ally:actor": 0.0}},
    "rng": {"rng_state": "seed:case", "rng_mode": "explicit_ledger", "rng_choices": {}},
    "initial_statuses": [],
    "initial_summons": [],
    "objective": {"objective_id": "case_goal", "kind": "defeat_units", "payload": {}}
  }
}
```

Setup describes initial conditions and route inputs only. It may reference
RuleBook / Canonical IR sources such as `EffectIR` AddModifier effects,
`SummonMonsterIntentIR`, stage wave definitions, and entity refs. It must not
define modifier terms, formulas, skill behavior, summon behavior, passives, or
enemy AI.

State-changing setup operations reuse core systems:

- `initial_statuses[*].effect_ref` must point to a real executable
  `AddModifier` effect and is applied through `StatusSystem.apply_add_modifier`.
- `initial_summons[*].kind == "summoned_monster"` must point to a real
  `SummonMonsterIntentIR` and is applied through `SummonSystem`.
- `battle_unit_summon` and `servant` remain source-gap blocked unless a future
  executable source/admission path exists.
- `hp_ratio` and `energy_ratio` are panel convenience inputs; they cannot be
  combined with `hp` / `energy`.
- Scenario-level RNG setup is merged into route command metadata; per-route
  metadata overrides scenario defaults.
- `objective` is search/report metadata and does not affect rule execution.

`examples/p1_8_battle_setup_smoke.json` is a small load/build smoke. The
source-backed status/summon positive samples are selected dynamically by
`simulator_v8_clean_core.tools.validate_p1_8_battle_setup` to avoid fixed
stage, monster, or skill IDs as validation drivers.
