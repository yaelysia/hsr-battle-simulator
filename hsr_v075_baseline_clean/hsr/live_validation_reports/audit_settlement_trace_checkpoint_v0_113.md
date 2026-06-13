# Audit Settlement Trace Checkpoint v0.113

Date: 2026-06-13

## Purpose

This checkpoint closes the top-level settlement consistency gap for the
damage-family audit records:

- `damage_records`
- `break_records`
- `toughness_records`
- `dot_records`
- `super_break_records`

These records are now validated against the committed transition state changes
instead of only being emitted as parallel diagnostic payloads.

## Changes

- Extended the settlement-record consistency gate to validate top-level
  damage-family audit records.
- Added exact payload matching for damage, break, DoT, and super-break audit
  state changes.
- Added concrete old/new toughness state-change matching for
  `toughness_records`.
- Added per-family counters to `settlement_record_validation`:
  - `audit_record_count` / `audit_record_valid_count`
  - `damage_settlement_record_count` / `damage_settlement_record_valid_count`
  - `break_settlement_record_count` / `break_settlement_record_valid_count`
  - `toughness_settlement_record_count` / `toughness_settlement_record_valid_count`
  - `dot_settlement_record_count` / `dot_settlement_record_valid_count`
  - `super_break_settlement_record_count` / `super_break_settlement_record_valid_count`
- Included these audit records in `settlement_checked_record_count` and
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
  --output /tmp/hsr_v113_audit_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v113_audit_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v113_audit_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v113_audit_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v113_audit_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v113_audit_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v113_audit_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 120 / 120 valid.
- C0 to C8 audit-family records: 20 / 20 valid.
- C0 to C8 damage records: 14 / 14 valid.
- C0 to C8 toughness records: 6 / 6 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 3 / 3 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 17 / 17 valid.
- Break/DoT minimal audit-family records: 6 / 6 valid.
- Break/DoT minimal damage records: 1 / 1 valid.
- Break/DoT minimal break records: 1 / 1 valid.
- Break/DoT minimal toughness records: 1 / 1 valid.
- Break/DoT minimal DoT records: 2 / 2 valid.
- Break/DoT minimal super-break records: 1 / 1 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 14 / 14 valid.
- Super-break audit-family records: 6 / 6 valid.
- Super-break damage records: 2 / 2 valid.
- Super-break break records: 1 / 1 valid.
- Super-break toughness records: 1 / 1 valid.
- Super-break super-break records: 2 / 2 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 24 / 24 valid.
- Seele five-dummy audit-family records: 4 / 4 valid.
- Seele five-dummy damage records: 4 / 4 valid.
- Phase-lock replay ok: 1 / 1.
- Phase-lock checked settlement records: 1 / 1 valid.
- Derived-skip replay ok: 1 / 1.
- Derived-skip checked settlement records: 2 / 2 valid.
- Damage-family settlement mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one top-level `damage_records[0].damage_applied` value while
  keeping the committed transition payload unchanged.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_damage_audit_state_change`.
- Removed the concrete `unit.toughness` state change while keeping the
  top-level `toughness_records` entry.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_toughness_state_change`.

## Remaining Work

The settlement consistency gate now covers resource, status, AV, and
damage-family top-level records. The next structural target is to make these
typed settlement records the primary generated action output, then reduce the
remaining ad hoc payload matching around mechanic records, queue transitions,
trigger usage, and process events.
