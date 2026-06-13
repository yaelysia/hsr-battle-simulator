# Control Settlement Trace Checkpoint v0.115

Date: 2026-06-13

## Purpose

This checkpoint moves queue mutations and trigger usage counters into explicit
top-level settlement records. These control-plane changes already passed
through transition state changes, but the settlement payload did not expose a
typed record that could be checked and traced alongside resources, turns, and
damage records.

## Changes

- Added `QueueRecord`:
  - `queue_name`
  - `operation`
  - `old_queue`
  - `new_queue`
  - `delta`
  - `item`
  - `requested_queue`
  - `reason`
  - `source_id`
  - `payload`
- Added `TriggerUsageRecord`:
  - `key`
  - `old_count`
  - `new_count`
  - `delta`
  - `reason`
  - `source_id`
  - `payload`
- `commit_queue_append()` and `commit_queue_popleft()` now emit queue
  settlement records from the committed queue state change.
- `commit_trigger_usage()` and `commit_trigger_usage_remove()` now emit trigger
  usage settlement records from the committed trigger usage state change.
- Extended the settlement-record consistency gate to validate:
  - `queue_records` against `battle.queues.<queue_name>` state changes;
  - `trigger_usage_records` against `battle.trigger_usage.<key>` state changes.
- Added counters:
  - `control_record_count` / `control_record_valid_count`
  - `queue_record_count` / `queue_record_valid_count`
  - `trigger_usage_record_count` / `trigger_usage_record_valid_count`
- Included control records in `settlement_checked_record_count` and
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
  --output /tmp/hsr_v115_control_record_trace_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v115_control_record_trace_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/break_dot_minimal_case.yaml \
  --output /tmp/hsr_v115_control_record_trace_break_dot.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/super_break_case.yaml \
  --output /tmp/hsr_v115_control_record_trace_super_break.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v115_control_record_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v115_control_record_trace_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v115_control_record_trace_derived_skip.json
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
- C0 to C8 checked settlement records: 138 / 138 valid.
- C0 to C8 control records: 4 / 4 valid.
- C0 to C8 queue records: 4 / 4 valid.
- C0 to C8 trigger usage records: 0 / 0 valid.
- Auto probe replay ok: 1 / 1.
- Auto probe checked settlement records: 5 / 5 valid.
- Break/DoT minimal replay ok: 3 / 3.
- Break/DoT minimal checked settlement records: 21 / 21 valid.
- Super-break replay ok: 2 / 2.
- Super-break checked settlement records: 14 / 14 valid.
- Seele five-dummy replay ok: 4 / 4.
- Seele five-dummy checked settlement records: 33 / 33 valid.
- Seele five-dummy control records: 7 / 7 valid.
- Seele five-dummy queue records: 4 / 4 valid.
- Seele five-dummy trigger usage records: 3 / 3 valid.
- Phase-lock replay ok: 1 / 1.
- Derived-skip replay ok: 1 / 1.
- Control settlement mismatches in checked outputs: none.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Negative smoke checks:

- Corrupted one top-level `queue_records[0].operation` value while keeping the
  committed queue state change unchanged.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `queue_records[0].operation`.
- Corrupted one top-level `trigger_usage_records[0].new_count` value while
  keeping the committed trigger usage state change unchanged.
  `_validate_resource_record_consistency()` returned
  `settlement_record_match = False` and reported
  `missing_matching_trigger_usage_state_change`.

## Remaining Work

The settlement consistency gate now covers resource, status, AV, turn, control
queue/trigger records, and damage-family top-level records. The next structural
target is to cover the remaining broad `mechanic_records` and then begin
renaming/splitting the consistency helper into a general settlement validator,
because it is no longer resource-only.
