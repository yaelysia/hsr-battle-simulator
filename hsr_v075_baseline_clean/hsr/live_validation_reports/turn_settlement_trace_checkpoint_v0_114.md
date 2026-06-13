# Turn Settlement Trace Checkpoint v0.114

Date: 2026-06-13

## Purpose

This checkpoint closes the top-level settlement consistency gap for
`turn_records`. Turn begin/end records already produced `turn` state changes,
but they were not counted by the settlement-record gate. They are now validated
as first-class settlement records, which keeps turn lifecycle data bound to the
same action transition used for replay.

## Changes

- Extended `_validate_resource_record_consistency()` to accept `turn_records`.
- Validates each turn record against a matching transition state change:
  - `change_type = turn`
  - `field_path = unit.turn`
  - `subject_id = turn_records[*].unit_id`
  - `payload = turn_records[*]`
  - `reason = turn_records[*].event_type`
- Added `turn_record_count` and `turn_record_valid_count` to
  `settlement_record_validation` and `transition.replay_validation`.
- Included turn records in `settlement_checked_record_count` and
  `settlement_checked_record_valid_count`.

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
  --output /tmp/hsr_v114_turn_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v114_turn_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v114_turn_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v114_turn_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v114_turn_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v114_turn_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v114_turn_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 134 / 134 valid.
- C0 to C8 turn records: 14 / 14 valid.
- C0 to C8 audit-family records: 20 / 20 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 5 / 5 valid.
- Auto probe turn records: 2 / 2 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 21 / 21 valid.
- Break/DoT minimal turn records: 4 / 4 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 14 / 14 valid.
- Super-break turn records: 0 / 0 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 26 / 26 valid.
- Seele five-dummy turn records: 2 / 2 valid.
- Phase-lock replay ok: 1 / 1.
- Derived-skip replay ok: 1 / 1.
- Turn settlement mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one top-level `turn_records[0].event_type` value while keeping the
  committed transition payload unchanged.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_turn_state_change`.
- Removed the concrete `turn` state change while keeping the top-level turn
  settlement record.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_turn_state_change`.

## Remaining Work

The settlement consistency gate now covers resource, status, AV, turn, and
damage-family top-level records. The next structural target is to make the
remaining mechanic records, queue mutations, trigger usage mutations, and
process events similarly trace-bound, then promote typed settlement objects
from audit output into the engine's primary action result.
