# v8 P6-S2/S3 Unit Spawn Birth Plan - ready_for_review

## Scope

P6-S2/S3 moved summoned-monster, servant, and wave enemy birth-template assembly before runtime.

Lowering projects first-class `UnitBirthTemplateIR` records into Canonical IR. Summon entries, servant definitions, and wave entries reference those templates by `birth_template_id`; RuleBook only indexes and returns the projected records.

Runtime `UnitSpawnSystem` has no RuleBook or content-card dependency. It materializes stable binding specs with the current `UnitSpawnRequest`, and apply stages require each `UnitSpawnPlan` to match the authoritative request exactly before passing a `UnitState` to `UnitLifecycleSystem`.

`UnitSpawnPlan.to_unit()` strictly validates unit fields, request identity, spawn kind, owner/summoner, source/entry identity, wave identity and source traces. Missing, incomplete, or complete-but-tampered birth plans are blocked before mutation. No default side, level, HP, or speed is supplied.

Wave level and stat scaling are projected from `StageConfig.Level`, `HardLevelGroup`, and `HardLevelGroup.json`; absent level provenance blocks the wave definition instead of creating a level-80 unit.

## Changed Files

- `simulator_v8_clean_core/rules/ir.py`, `rules/rulebook.py`, `tbgd/lowering.py`
  - Add, project, serialize, index, and expose first-class `UnitBirthTemplateIR`.
  - Add wave stage level / hard-level policy and source-backed stat ratios.

- `simulator_v8_clean_core/systems/unit_spawn.py`
  - Add shared `UnitSpawnRequest` and `UnitSpawnPlan` contracts.
  - `UnitSpawnPlan.to_unit()` requires explicit unit identity, side, template, level, HP, speed, source trace, flags, resources, and path-specific ownership/source evidence.
  - `UnitSpawnSystem` only materializes pre-lowered binding specs and does not read RuleBook or content definitions.

- `simulator_v8_clean_core/systems/summon.py`
  - Planning resolves referenced templates and records authoritative spawn requests.
  - Apply requires one exact request-bound plan per unit and blocks missing, incomplete, or tampered plans.

- `simulator_v8_clean_core/systems/wave.py`
  - Planning resolves wave birth templates carrying stage level and hard-level sources.
  - Apply verifies wave definition, stage, wave index, entry, position, level, and source binding.

- `simulator_v8_clean_core/scenarios/build_state.py`
  - Initial-wave scenario assembly uses the same projected birth template rather than reconstructing wave stats or timeline defaults.

- `simulator_v8_clean_core/tools/validate_p6_s2_s3_unit_spawn_birth_plan.py`
  - S2/S3 matrix covers first-class projection, positives, missing plans, incomplete plans, complete tampering, stage-level provenance, and static runtime-boundary guards.

## Evidence

Commands run:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p6_s2_s3_unit_spawn_birth_plan --output-dir /tmp/hsr_v8_p6_s2_s3_refactor_final_probe
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p6_refactor_p3_aggregate
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s7_monster_custom_summon_binding --output-dir /tmp/hsr_v8_p6_refactor_p5_s7
```

Observed results:

```text
v8 p3_summon_assistant_servant_complete validation_gate_ok=True p3_summon_foundation_closed=True p3_summon_phase_complete=True p3_summon_all_executable_complete=False p3_summon_sources_classified=True gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}
v8 p5_s7_monster_custom_summon_binding ok=True rows=5 classifications={'admission_gap': 1, 'boundary_only': 1, 'executable': 3} gap_counts={'admission_gap': 1}
v8 p6_s2_s3_unit_spawn_birth_plan ok=True rows=15 classifications={'boundary_guard': 11, 'executable': 4}
```

S2/S3 matrix rows:

- `summoned_monster_birth_plan_positive`: executable.
- `summoned_monster_missing_birth_plan_negative`: boundary guard.
- `summoned_monster_incomplete_birth_plan_negative`: boundary guard.
- `summoned_monster_tampered_birth_plan_negative`: boundary guard.
- `servant_birth_plan_positive`: executable.
- `servant_missing_birth_plan_negative`: boundary guard.
- `servant_incomplete_birth_plan_negative`: boundary guard.
- `servant_tampered_birth_plan_negative`: boundary guard.
- `wave_birth_plan_positive`: executable.
- `wave_missing_birth_plan_negative`: boundary guard.
- `wave_incomplete_birth_plan_negative`: boundary guard.
- `wave_tampered_birth_plan_negative`: boundary guard.
- `unit_birth_template_first_class_projection`: executable.
- `wave_stage_level_source_contract`: executable.
- `apply_stage_static_guard`: boundary guard.

Negative coverage totals:

- 3 missing-plan cases.
- 14 incomplete-plan variants covering required stats, ownership/identity, level, and source provenance.
- 17 complete-but-tampered variants covering unit ID, entity, spawn kind, owner/summoner, source/entry identity, and wave definition/stage/index/position.
- Every negative is blocked, process-only, zero mutation, and state unchanged.

## Remaining Scope

Existing P3 gaps remain inherited and unchanged. This stage does not claim `p3_summon_all_executable_complete=true`; it proves that admitted summon/servant/wave generation paths use first-class projected templates and request-bound runtime plans.

Full summon, servant, monster, wave, stage, and environment mechanism coverage remains outside this refactor. The first-class birth-template projection and source-backed wave level goals themselves are no longer backlog items.

S2/S3 are ready for review, but checklist completion is left to the acceptance thread.
