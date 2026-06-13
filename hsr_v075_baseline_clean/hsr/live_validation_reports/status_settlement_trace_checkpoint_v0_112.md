# Status Settlement Trace Checkpoint v0.112

Date: 2026-06-13

## Purpose

This checkpoint closes the top-level settlement consistency gap for
`status_records`. Status records now carry the same stack, duration, and source
facts as the committed status state change, then pass through the same
settlement-record gate as HP, shield, SP, energy, and AV.

## Changes

- Fixed weakness-break aftermath status record production:
  - records `change_type` as `add` or `refresh`;
  - records `stacks_before` and `stacks_after`;
  - records `max_stacks`;
  - records `duration_type` and `duration_value`;
  - records the committed status source id.
- Extended `_validate_resource_record_consistency()` to validate
  `status_records`.
- Status record validation checks:
  - matching `unit.statuses.{status_id}` status state change exists;
  - state-change delta matches record `change_type`;
  - old/new stacks match the concrete old/new status payloads;
  - max stacks match the concrete committed/removed status payload;
  - duration type/value match the concrete committed/removed status payload;
  - source owner matches record `source_id` when present.
- `status_record_count` and `status_record_valid_count` are now included in
  `settlement_record_validation` and `transition.replay_validation`.

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
  --output /tmp/hsr_v112_status_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v112_status_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v112_status_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v112_status_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v112_status_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v112_status_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v112_status_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 100 / 100 valid.
- C0 to C8 status records: 8 / 8 valid.
- C0 to C8 resource records: 35 / 35 valid.
- C0 to C8 AV records: 57 / 57 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 3 / 3 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 11 / 11 valid.
- Break/DoT minimal status records: 1 / 1 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 8 / 8 valid.
- Super-break status records: 1 / 1 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 20 / 20 valid.
- Seele five-dummy status records: 4 / 4 valid.
- Phase-lock replay ok: 1 / 1.
- Derived-skip replay ok: 1 / 1.
- Damage and turn record mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one status settlement record `new_stacks`.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `status_records[0].new_stacks`.
- Removed concrete status state changes while keeping the top-level status
  settlement record.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_status_state_change`.

## Remaining Work

The current settlement consistency gate now covers HP, shield, SP, energy,
status, and AV top-level records. The next structural target is to reduce the
remaining ad hoc payload matching by moving toward explicit typed settlement
objects as the primary replay input, especially for status field changes,
mechanic records, and queue/trigger side effects.
