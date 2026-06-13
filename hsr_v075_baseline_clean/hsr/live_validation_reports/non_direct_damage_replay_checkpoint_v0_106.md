# Non-Direct Damage Replay Checkpoint v0.106

Date: 2026-06-13

## Purpose

This checkpoint extends damage replay validation beyond direct action damage.
v0.105 made direct damage records and formula ledgers strict; v0.106 applies
the same transition-level discipline to DoT and super-break `unit.hp_or_shield`
audit state changes.

## Changes

- Extended `_validate_damage_state_changes()` to cover:
  - `change_type = dot`
  - `change_type = super_break`
- DoT validation checks:
  - payload is a dict;
  - payload `unit_id` matches `state_change.subject_id`;
  - payload `kind` matches `state_change.reason`;
  - status source points back to `source_status_id`;
  - `state_change.delta == -payload.damage_applied`;
  - payload `final_damage` is numeric;
  - payload `stacks` is a non-negative int.
- Super-break validation checks:
  - payload is a dict;
  - payload `target_id` matches `state_change.subject_id`;
  - payload `actor_id` matches state-change source owner;
  - state-change reason is `super_break`;
  - `state_change.delta == -payload.damage_applied`;
  - payload `final_damage` is numeric;
  - payload `toughness_reduction` is numeric.
- `replay_validation` now reports:
  - `dot_damage_change_count`
  - `dot_damage_change_valid_count`
  - `super_break_damage_change_count`
  - `super_break_damage_change_valid_count`

This keeps the v0.105 `damage_record_match` gate as a single hard replay gate
for direct, DoT, and super-break HP/shield damage records.

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
  --output /tmp/hsr_v106_nondirect_damage_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v106_nondirect_damage_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v106_nondirect_damage_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v106_nondirect_damage_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v106_nondirect_damage_derived_skip.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v106_nondirect_damage_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v106_nondirect_damage_super_break.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 direct damage changes: 14 / 14 valid.
- C0 to C8 target decisions: 38 / 38 valid.
- C0 to C8 damage record mismatches: 0.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Seele five-dummy replay direct/full/process/damage match: 4 / 4.
- Seele five-dummy direct damage changes: 4 / 4 valid.
- Phase-lock process case direct damage changes: 1 / 1 valid.
- Derived-damage skip process case direct damage changes: 1 / 1 valid.
- Break/DoT minimal case DoT changes: 2 / 2 valid.
- Break/DoT minimal case super-break changes: 1 / 1 valid.
- Super-break case super-break changes: 2 / 2 valid.
- Unsupported process event types in checked outputs: none.
- Damage record mismatches in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Known residual:

- `break_dot_minimal_case` and `super_break_case` still each contain an older
  replay unsupported path around `unit.toughness.break`. Their new
  `damage_record_match` checks pass; the unsupported toughness-break reducer
  path remains separate follow-up work.

Negative smoke check:

- Manually corrupted the break/DoT minimal case DoT
  `state_change.payload.kind`.
- `validate_transition_replay()` returned `damage_record_match = False`,
  `ok = False`, and reported `state_changes[9].reason`.

## Remaining Work

Direct, DoT, and super-break HP/shield damage records now have strict replay
validation. The next concrete gap is the toughness-break state-change path:
`unit.toughness.break` is still audit-only/unsupported in replay and should be
made replayable or deliberately classified with stricter semantics.
