# Target Settlement Trace Checkpoint v0.116

Date: 2026-06-13

## Purpose

This checkpoint closes the top-level settlement consistency gap for
`target_record`. Target selection was already represented by
`transition.target_resolution` and target process events, but the top-level
settlement target record was not checked as part of settlement consistency.

## Changes

- Extended `_validate_resource_record_consistency()` to accept `target_record`.
- Validates `target_record` against the transition action request and final
  target resolution:
  - `actor_id` matches `transition.request.actor_id`;
  - `action_id` matches `transition.request.action_id`;
  - `target_ids` match `transition.target_resolution.resolved_target_ids`;
  - `target_selection_reason` matches `transition.target_resolution.method`;
  - target resolution actor/action ids match the target record.
- Added `target_record_count` and `target_record_valid_count` to
  `settlement_record_validation` and `transition.replay_validation`.
- Included target records in `settlement_checked_record_count` and
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
  --output /tmp/hsr_v116_target_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v116_target_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v116_target_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v116_target_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v116_target_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v116_target_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v116_target_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 148 / 148 valid.
- C0 to C8 target records: 10 / 10 valid.
- C0 to C8 control records: 4 / 4 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 6 / 6 valid.
- Auto probe target records: 1 / 1 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 22 / 22 valid.
- Break/DoT minimal target records: 1 / 1 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 16 / 16 valid.
- Super-break target records: 2 / 2 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 37 / 37 valid.
- Seele five-dummy target records: 4 / 4 valid.
- Phase-lock replay ok: 1 / 1.
- Phase-lock checked settlement records: 2 / 2 valid.
- Phase-lock target records: 1 / 1 valid.
- Derived-skip replay ok: 1 / 1.
- Derived-skip checked settlement records: 3 / 3 valid.
- Derived-skip target records: 1 / 1 valid.
- Target settlement mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one top-level `target_record.target_ids` value while keeping the
  final transition target resolution unchanged.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `target_record.target_ids`.
- Removed `transition.target_resolution` while keeping the top-level target
  record.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_target_resolution`.

## Remaining Work

The settlement consistency gate now covers target, resource, status, AV, turn,
control queue/trigger records, and damage-family top-level records. The next
structural target is to cover the remaining broad `mechanic_records`, then
split or rename the consistency helper into a general settlement validator
because it is no longer resource-only.
