# Turn Lifecycle Replay Checkpoint v0.108

Date: 2026-06-13

## Purpose

This checkpoint closes the replay validation gap for `unit.turn` audit records.
Turn begin/end records are not direct snapshot mutations, but they are still
part of the action settlement contract. The reducer now validates that every
turn audit state change is internally consistent, source-traceable, and paired
within the same transition.

## Changes

- Added `_validate_turn_state_changes()`.
- `validate_transition_replay()` now merges turn validation and requires
  `turn_record_match`.
- Turn validation checks:
  - payload is a dict;
  - payload `unit_id` is present and matches `state_change.subject_id`;
  - payload `turn_kind` is present;
  - payload `event_type` is `begin` or `end`;
  - `change_type` is `turn`;
  - scope is `unit`;
  - `reason` matches payload `event_type`;
  - `old_value`, `new_value`, and `delta` are all `None`;
  - source type is `action`;
  - source owner matches the turn unit;
  - source id matches payload `action_id` when present, otherwise the
    transition request action id;
  - every `(unit_id, turn_kind)` begin has a matching end in the same
    transition;
  - no end may appear without a prior begin in the same transition.
- `replay_validation` now reports:
  - `turn_change_count`
  - `turn_change_valid_count`
  - `turn_begin_count`
  - `turn_end_count`
  - `turn_pair_count`
  - `turn_pair_valid_count`
  - `turn_record_match`
  - `turn_record_mismatch_count`
  - `turn_record_mismatches`

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
  --output /tmp/hsr_v108_turn_replay_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v108_turn_replay_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v108_turn_replay_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v108_turn_replay_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v108_turn_replay_seele_five_dummy.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10, including queued transitions.
- C0 to C8 unsupported replay paths: 0.
- C0 to C8 target decisions: 38 / 38 valid.
- C0 to C8 direct damage changes: 14 / 14 valid.
- C0 to C8 turn changes: 14 / 14 valid.
- C0 to C8 turn pairs: 7 / 7 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe turn changes: 2 / 2 valid.
- Auto probe turn pairs: 1 / 1 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy turn changes: 2 / 2 valid.
- Seele five-dummy turn pairs: 1 / 1 valid.
- Break/DoT minimal case replay ok: 3 / 3.
- Break/DoT minimal case turn changes: 4 / 4 valid.
- Break/DoT minimal case turn pairs: 2 / 2 valid.
- Super-break case replay ok: 2 / 2.
- Super-break case turn changes: 0 / 0.
- Unsupported replay paths in checked outputs: none.
- Process/damage/break/turn record mismatches in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually removed one `unit.turn` end state change from the first C0 to C8
  transition.
- `validate_transition_replay()` returned `turn_record_match = False`,
  `ok = False`, and reported `turn_begin_without_end`.

## Remaining Work

`unit.turn` is still an audit-only field, but it is now a strict validated
settlement fact. The next replay-hardening target should be the remaining
audit-only damage facts around `unit.hp_or_shield`: they already have record
validation, but the reducer still does not reconstruct HP/shield effects from
the audit record itself.
