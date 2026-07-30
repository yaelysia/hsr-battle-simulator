# P8-S12 Relic Sub-Affix Rolls

Status: `ready_for_review`

Baseline: `84bef6dba47cd4ed033941fb605c0e87504d90b3`

## Production changes

- Added typed finished-relic sub-affix roll inputs and exact `Decimal` computation
  from canonical affix definitions plus integer `count` and `step`.
- Added generic fail-closed admission for group membership, count/step bounds,
  affix/property uniqueness, and main/sub property conflicts.
- `admit_relic_sub_affixes` first resolves the unique canonical template from
  RuleBook using the instance template identity. It rejects unresolved, ambiguous,
  or non-identical supplied templates before using only the canonical template for
  later slot, main-affix, sub-group, source, and value checks.
- Main-affix identity, property, group, calculation, source records, JSON paths,
  and source fingerprints are recomputed from RuleBook and compared structurally.
- Added one typed `relic_assembly` blocker per admitted relic selection and exact
  selection/blocker one-to-one constructor closure. Invalid relic input atomically
  clears every formal assembly channel.
- The stable production blocker reason is
  `relic_set_activation_and_static_contributions_not_assembled`; production names
  and payloads contain no execution-stage number.
- Removed `RelicSubAffixComputation.display_value` and all core dependencies on
  `ROUND_HALF_UP` and `localcontext`. Display projection remains outside core.
- Added the small `build_relic_catalog_from_source_bundle` extraction. The normal
  production `build_relic_catalog` is its non-tools caller; the validator reuses it
  to lower an already-loaded source bundle without a second directory read.
- Validation-only `RelicAffixProjection*` and RuleBook scope APIs remain absent.

## Raw oracle

The validator loads one `RelicCatalogSourceBundle` and uses that same in-memory
snapshot for both production catalog lowering and the independent oracle.

The oracle reads 48 raw `RelicSubAffixConfig` rows directly from:

- `GroupID`
- `AffixID`
- `BaseValue.Value`
- `StepValue.Value`
- `StepNum`

It converts raw numeric values to `Fraction`, computes independently, and uses
local `Decimal` only to emit canonical exact text. Expected values do not read
`RelicSubAffixDefinitionIR.base_value`, `step_value`, or `step_count`.

## Actual validation

Static:

```text
python3 -B -m py_compile <eight modified Python paths>
PYTHONPYCACHEPREFIX=/tmp/hsr_p8_s12_pycache_final \
  python3 -m compileall -q simulator_v8_clean_core
git diff --check -- <S12 tracked paths>
```

Targeted direct probe:

- One source snapshot, one complete relic catalog, and one bounded RuleBook.
- Raw rows: 48; complete relic definitions: 1080; RuleBook relic definitions: 383.
- `template_json_path`, `template_sub_affix_group`, `main_property`, and
  `main_source` tampering all returned their expected structured blockers.
- Empty/non-empty equipment paths, both light-cone paths, sibling atomic failure,
  CharacterBuildAssembler blocking, and stable blocker reason all passed.
- Confirmed `RelicSubAffixComputation` has no `display_value`.

Final focused business entry, run once:

```text
/usr/bin/time -v -o /tmp/hsr_v8_p8_s12_time_v.txt \
  python3 -B -m simulator_v8_clean_core.tools.validate_p8_s12_relic_sub_affix_rolls \
  --tbgd-root /home/zhangjinhao/code/hsr/turnbasedgamedata-main \
  --output-dir /tmp/hsr_v8_p8_s12_relic_sub_affix_rolls
```

Result: `ok=true`, 19/19 predicates passed:

- `raw_sub_affix_values_match_independent_oracle`
- `count_and_step_integer_bounds_enforced`
- `maximum_four_unique_properties_enforced`
- `same_affix_rejected`
- `same_property_rejected`
- `main_sub_same_property_rejected`
- `distinct_flat_and_ratio_properties_can_coexist`
- `sub_affix_group_membership_enforced`
- `per_affix_cumulative_step_bound_enforced`
- `aggregate_upgrade_history_not_modeled`
- `main_affix_identity_and_source_recomputed`
- `canonical_template_identity_and_source_recomputed`
- `bool_float_unknown_and_stale_inputs_rejected`
- `input_containers_detached_and_immutable`
- `valid_sibling_plus_invalid_relic_fails_atomically`
- `empty_relic_build_remains_battle_admitted`
- `light_cone_and_no_light_cone_paths_future_blocked`
- `character_build_cannot_admit_zero_relic_effects`
- `accepted_bounded_domain_reuse`

## Validation governance

This is accepted bounded-domain reuse, not strict source-lowering prefiltering:

- Source snapshot loads: 1.
- Complete relic catalog builds: 1.
- Semantic tables parsed: 6.
- Ability files parsed: 15.
- Complete relic definitions: 1080.
- RuleBook builds: 1, receiving 383 relic definitions.
- Full Canonical IR builds: 0.
- Full RuleBook builds: 0.
- Focused validator entries: 1.
- Validator size: 800 non-empty lines.

## Resources

- Wall time: 0.64 seconds (`<2s`).
- Peak RSS: 68,880 KiB (`<128 MiB`).
- Evidence: 3 JSON files, 29,858 bytes total.

## Deferred and gaps

The stable blocker maps to downstream implementation as follows:

- P8-S13: relic set activation.
- P8-S14: static relic contributions.

It is an `implementation_missing` battle blocker, not an S12 exclusion. Non-empty
relic equipment cannot enter formal battle admission until both capabilities are
assembled.

S12 `gap_register=[]`.

Per product scope, S12 does not model drops, initial rolls, upgrade nodes,
materials, generation history, joint roll-path feasibility, rarity/level budgets,
or engine-rule versions. User-supplied final values and floats are rejected.

## Changed files

- `simulator_v8_clean_core/builds/equipment_assembler.py`
- `simulator_v8_clean_core/builds/relic_affix_calculator.py`
- `simulator_v8_clean_core/equipment/__init__.py`
- `simulator_v8_clean_core/equipment/models.py`
- `simulator_v8_clean_core/tbgd/relic_cards.py`
- `simulator_v8_clean_core/tools/validate_p8_s10_relic_instance_legality.py`
- `simulator_v8_clean_core/tools/validate_p8_s11_relic_main_affix.py`
- `simulator_v8_clean_core/tools/validate_p8_s12_relic_sub_affix_rolls.py`
- `live_validation_reports/P8-S12_RELIC_SUB_AFFIX_ROLLS_ready_for_review.md`

No checklist was changed and no Git commit was created.
