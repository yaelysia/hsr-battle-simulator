# v8 P6-S4/S5 Boundary Static Guards - ready_for_review

## Scope

P6-S4/S5 adds lightweight boundary guards for the remaining S0 risk areas:

- Dynamic value binding no longer reads `card.source.evidence` directly from `systems/dynamic_values.py`.
- RuleBook now exposes a narrow `character_dynamic_value_bindings_for_card()` accessor.
- S1 damage/toughness trace-mining fixes are guarded statically.
- S2/S3 birth-plan apply boundaries are guarded statically.
- Action availability remains query/source-context only.
- Saved UI scenario inputs are checked for derived combat-rule result fields.

This stage does not split the whole `RuleBook`, rewrite content cards, remove source audit fields, or claim that dynamic binding source evidence has become a first-class projected IR field.

## Changed Files

- `simulator_v8_clean_core/rules/rulebook.py`
  - Added `character_dynamic_value_bindings_for_card()`.
  - Added JSON copy helper for accessor output.
  - This accessor is a transitional boundary: systems no longer mine card evidence directly, but RuleBook still bridges from `CharacterDataCardIR.source.evidence["character_config_dynamic_value_bindings"]`.

- `simulator_v8_clean_core/systems/dynamic_values.py`
  - `character_skill_param_binding_source()` now consumes the RuleBook accessor instead of reading `card.source.evidence`.

- `simulator_v8_clean_core/tools/validate_p6_s4_s5_boundary_static.py`
  - New lightweight P6 boundary static matrix.

## Evidence

Commands run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/rulebook.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/dynamic_values.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p6_s4_s5_boundary_static.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p6_s4_s5_boundary_static --output-dir /tmp/hsr_v8_p6_s4_s5_current
PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s3_dynamic_custom_binding_projection --output-dir /tmp/hsr_v8_p6_s5_p5_s3_current
```

Observed results:

```text
v8 p6_s4_s5_boundary_static ok=True rows=6 classifications={'audit_only': 1, 'boundary_guard': 5}
v8 p5_s3_dynamic_custom_binding_projection ok=True rows=7 classifications={'admission_gap': 3, 'boundary_only': 1, 'executable': 3} gap_counts={'admission_gap': 16767}
```

S4/S5 matrix rows:

- `existing_runtime_static_checks`: boundary guard.
- `dynamic_value_rulebook_accessor_boundary`: boundary guard.
- `damage_toughness_trace_mining_boundary`: boundary guard.
- `unit_spawn_apply_birth_plan_boundary`: boundary guard.
- `action_availability_query_only_boundary`: audit only.
- `ui_scenario_no_formal_rule_write_boundary`: boundary guard.

## Remaining Scope

P5-S3 still reports admission gaps; S4/S5 does not convert those to executable. The purpose here is boundary containment and regression protection, not dynamic/custom value full coverage.

The dynamic binding accessor is not a full source-evidence elimination. A later phase should project character config dynamic bindings into an explicit data-card / RuleBook index instead of reading them from card source evidence inside the accessor.

S4/S5 are ready for review, but checklist completion is left to the acceptance thread.
