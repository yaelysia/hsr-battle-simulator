# v8 P6-S1 Damage / Toughness Calculation Entry - ready_for_review

## Scope

P6-S1 only addresses the damage/toughness boundary rows from S0:

- Runtime damage value resolution no longer mines `hit_source_trace` for `SkillFormulaBindingIR`.
- Runtime toughness value resolution no longer mines `source_trace` for numeric binding sources.
- Toughness no longer falls back from unresolved dynamic hash to `ActionDefinitionIR.show_stance_list`.
- `DamagePlan` and `ToughnessPlan` now carry explicit `value_request` data generated during action plan construction.
- Damage value requests now require a structured `param_index` projected into `HitProfileIR.multiplier_source`; action plan construction no longer parses `ParamList[...]` from raw path text.
- Source trace remains available for settlement/source audit/replay, but not for choosing the runtime calculation rule.

This stage does not expand formula semantics, summon generation, or content-card mechanisms.

## Changed Files

- `simulator_v8_clean_core/core/action_plan.py`
  - Added explicit `value_request` / `value_context` fields to `DamagePlan`.
  - Added explicit `value_request` / `value_context` / `value_binding_sources` fields to `ToughnessPlan`.
  - Builds damage value requests from `HitProfileIR.multiplier_source` / `multiplier_expr`.
  - Blocks skill-formula value requests when structured `param_index` is missing.
  - Builds toughness value requests from `ToughnessEmissionIR.toughness_amount_expr`.
  - Binding-source expression traversal skips `source_trace`.

- `simulator_v8_clean_core/tbgd/lowering.py`
  - Projects `param_index` into skill-formula multiplier sources as a structured field.

- `simulator_v8_clean_core/core/executor.py`
  - `_damage_value_resolution` now consumes `DamagePlan.value_request`.
  - `_toughness_value_resolution` now consumes `ToughnessPlan.value_request`.
  - Removed executor-side trace mining helpers.
  - Removed `show_stance_list` fallback from toughness resolution.

- `simulator_v8_clean_core/tools/validate_p6_s1_damage_toughness_calculation_entry.py`
  - New S1 validation matrix.
  - Uses a structural predicate: executable fixed toughness emission with damage emission.
  - Checks damage/toughness positive value-resolution paths, missing-entry negatives, executor trace-mining guard, and action-plan raw path parsing guard.

- `simulator_v8_clean_core/tools/validate_p5_s5_damage_toughness_value_resolver_consumers.py`
  - Updated runtime sample selection to use the same structural predicate instead of availability-order sampling.

## Evidence

Commands run from `/home/zhangjinhao/code/hsr` or `/home/zhangjinhao/code/hsr/hsr_v075_baseline_clean/hsr`:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/action_plan.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s5_damage_toughness_value_resolver_consumers.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p6_s1_damage_toughness_calculation_entry.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_s1_damage_toughness_calculation_entry --output-dir /tmp/hsr_v8_p6_s1_fix
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s5_damage_toughness_value_resolver_consumers --output-dir /tmp/hsr_v8_p6_fix_p5_s5
```

Observed results:

```text
v8 p6_s1_damage_toughness_calculation_entry ok=True rows=5 classifications={'boundary_guard': 3, 'executable': 2}
v8 p5_s5_damage_toughness_value_resolver_consumers ok=True rows=5 classifications={'executable': 4, 'source_absent_not_required': 1} gap_counts={}
```

S1 aggregate checks from `/tmp/hsr_v8_p6_s1_fix`:

- `plan_no_raw_param_path_parsing=true`.
- `damage_positive_uses_plan_entry=true`.
- `toughness_positive_uses_plan_entry=true`.
- `negative_no_mutations=true`.

S1 validation matrix summary:

- `damage_explicit_calculation_entry`: executable.
- `toughness_explicit_calculation_entry`: executable.
- `damage_missing_entry_blocked_no_mutation`: boundary guard.
- `toughness_missing_entry_blocked_no_mutation`: boundary guard.
- `executor_trace_mining_static_guard`: boundary guard.

Runtime sample:

- Selection predicate: `executable_fixed_toughness_emission_with_damage_emission`.
- Damage value resolution: `skill_formula_param`.
- Toughness value resolution: `fixed_numeric_expression`.
- Replay: ok.
- Source audit: ok.

## Remaining Scope

S1 does not claim all damage/toughness formulas are complete. Dynamic toughness entries without explicit binding sources remain blocked instead of falling back to `show_stance_list`; that is the intended boundary behavior for this stage.

S1 is ready for review, but checklist completion is left to the acceptance thread.
