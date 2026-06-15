# Mechanic Settlement Trace Checkpoint v0.117

Date: 2026-06-13

## Purpose

This checkpoint moves committed mechanic state changes into explicit top-level
`mechanic_records` and validates them through the settlement consistency gate.
Mechanic state changes such as defeat flags and phase HP bar transitions are now
trace-bound like resources, targets, turns, queues, and damage records.

## Changes

- Added `SettlementCollector.record_committed_mechanic_change()`.
- `BattleSimulator.record_committed_state_change()` now derives a
  `MechanicRecord` whenever the committed state change has
  `change_type = mechanic`.
- Mechanic records generated from committed state changes include:
  - `scope`
  - `subject_id`
  - `field_path`
  - `old_value`
  - `new_value`
  - `delta`
  - `reason`
  - `payload`
  - `source`
- Extended the settlement consistency gate to validate `mechanic_records`.
- Added `mechanic_record_count` and `mechanic_record_valid_count` to
  `settlement_record_validation` and `transition.replay_validation`.
- Included mechanic records in `settlement_checked_record_count` and
  `settlement_checked_record_valid_count`.
- Renamed the validator entry point to
  `_validate_settlement_record_consistency()`.
  `_validate_resource_record_consistency` remains as a compatibility alias.

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
  --output /tmp/hsr_v117_mechanic_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v117_mechanic_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v117_mechanic_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v117_mechanic_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v117_mechanic_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v117_mechanic_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v117_mechanic_record_trace_derived_skip.json
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
- C0 to C8 mechanic records: 0 / 0 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 6 / 6 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 22 / 22 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 16 / 16 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 39 / 39 valid.
- Seele five-dummy mechanic records: 2 / 2 valid.
  Both are `unit.alive` defeat transitions.
- Phase-lock replay ok: 1 / 1.
- Phase-lock checked settlement records: 3 / 3 valid.
- Phase-lock mechanic records: 1 / 1 valid.
  This is a `unit.hp_bars_remaining` phase HP bar transition.
- Derived-skip replay ok: 1 / 1.
- Derived-skip checked settlement records: 4 / 4 valid.
- Derived-skip mechanic records: 1 / 1 valid.
  This is a `unit.alive` defeat transition.
- Mechanic settlement mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Confirmed `_validate_resource_record_consistency` is a compatibility alias
  for `_validate_settlement_record_consistency`.
- Corrupted one top-level mechanic record `data.field_path` while keeping the
  committed mechanic state change unchanged.
  `_validate_settlement_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_mechanic_state_change`.
- Removed the concrete mechanic state change while keeping the top-level
  mechanic record.
  `_validate_settlement_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_mechanic_state_change`.

## Remaining Work

The settlement consistency gate now covers target, resource, status, AV, turn,
control queue/trigger records, mechanic records, and damage-family top-level
records. The next structural step is to promote the settlement payload into an
explicit `ActionSettlement` object rather than returning a loose dict assembled
inside `SettlementCollector.to_dict()`.
