# Toughness Break Replay Checkpoint v0.107

Date: 2026-06-13

## Purpose

This checkpoint closes the replay gap for `unit.toughness.break`. Break records
are audit facts rather than direct snapshot mutations: the actual replayable
state changes are toughness reduction, `is_broken`, HP/shield loss, and break
aftermath status changes. The reducer now classifies the break audit record as
audit-only and validates that it is supported by those concrete state changes.

## Changes

- Added `unit.toughness.break` to `AUDIT_ONLY_FIELD_PATHS`.
- Added `_validate_break_state_changes()`.
- `validate_transition_replay()` now merges break validation and requires
  `break_record_match`.
- Break validation checks:
  - payload is a dict;
  - `target_id` matches `state_change.subject_id`;
  - `actor_id` matches state-change source owner;
  - reason is `weakness_break`;
  - `state_change.delta == -payload.damage_applied`;
  - `final_break_damage == damage_applied`;
  - numeric `base_break_damage`, `hp_loss`, and `shield_absorbed`;
  - a matching `unit.toughness` state change reduced toughness from above zero
    to zero or below;
  - a matching `unit.is_broken` state change set the target to broken;
  - if `hp_loss > 0`, a matching `break_damage:hp_loss` HP state change exists;
  - if `shield_absorbed > 0`, a matching `break_damage:shield_absorb` shield
    state change exists.
- `replay_validation` now reports:
  - `break_change_count`
  - `break_change_valid_count`
  - `break_record_match`
  - `break_record_mismatch_count`
  - `break_record_mismatches`

## Validation

Commands:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_v107_break_replay_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v107_break_replay_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v107_break_replay_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v107_break_replay_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v107_break_replay_derived_skip.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v107_break_replay_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v107_break_replay_super_break.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 unsupported replay paths: 0.
- C0 to C8 direct damage changes: 14 / 14 valid.
- C0 to C8 target decisions: 38 / 38 valid.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Seele five-dummy replay direct/full/process/damage/break match: 4 / 4.
- Break/DoT minimal case replay ok: 3 / 3.
- Break/DoT minimal case break changes: 1 / 1 valid.
- Break/DoT minimal case DoT changes: 2 / 2 valid.
- Break/DoT minimal case super-break changes: 1 / 1 valid.
- Super-break case replay ok: 2 / 2.
- Super-break case break changes: 1 / 1 valid.
- Super-break case super-break changes: 2 / 2 valid.
- Unsupported process event types in checked outputs: none.
- Unsupported replay paths in checked outputs: none.
- Damage/break record mismatches in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the break/DoT minimal case break
  `state_change.payload.damage_applied`.
- `validate_transition_replay()` returned `break_record_match = False`,
  `ok = False`, and reported mismatches for break delta and final break damage.

## Remaining Work

The replay reducer now covers the prior `unit.toughness.break` unsupported path.
The next useful target is to continue converting remaining audit-only records
into explicitly validated facts, especially turn lifecycle and resource records
whose replay currently depends mostly on generic state-change projection.
