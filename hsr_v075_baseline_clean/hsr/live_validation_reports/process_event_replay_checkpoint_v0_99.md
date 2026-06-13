# Process Event Replay Checkpoint v0.99

Date: 2026-06-13

## Purpose

This checkpoint adds replay-time validation for grouped process events. v0.98
introduced `timeline_tick` process events that group one `global.av` change and
the affected `unit.remaining_av` changes. v0.99 teaches replay validation to
check those grouped records against the flat state-change stream.

## Changes

- Added process-event validation to `hsr_engine.transition_reducer`.
- Added state-change sequence indexing for replay validation.
- Added strict validation for supported `timeline_tick` process events:
  - the referenced `global.av` state change must exist;
  - old/new global AV, delta, and reason must match;
  - every unit row must reference an existing `unit.remaining_av` state change;
  - unit id, old/new remaining AV, delta, old absolute AV, and new absolute AV
    must match the referenced state change and process payload;
  - duplicate unit state-change references are reported.
- `replay_validation` now includes:
  - `process_event_match`
  - `process_event_mismatch_count`
  - `process_event_mismatches`
  - `timeline_tick_count`
  - `timeline_tick_valid_count`
  - process event supported/unsupported counts and unsupported event types.
- `replay_validation.ok` now requires supported process events to match.
  Unsupported process event types are reported but do not fail replay yet.

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
  --output /tmp/hsr_v099_process_event_replay_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v099_process_event_replay_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v099_process_event_replay_seele_five_dummy.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 transitions with replay validation: 10.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 direct replay matches: 10 / 10.
- C0 to C8 full snapshot matches: 10 / 10.
- C0 to C8 process event matches: 10 / 10.
- C0 to C8 supported timeline ticks: 6 / 6 valid.
- C0 to C8 process event mismatches: 0.
- C0 to C8 unsupported process event types: none.
- Auto probe assertions: ok, replay direct/full/process match 1 / 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy replay direct/full/process match 4 / 4.
- Seele five-dummy supported timeline ticks: 1 / 1 valid.
- Seele five-dummy unsupported process event types: `action_defeat_credit` (2 events).
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the first C0 to C8 `timeline_tick` unit row
  `new_remaining_av`.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported a value mismatch at
  `process_events[0].payload.unit_av_changes[0].new_remaining_av`.

## Remaining Work

Only `timeline_tick` has structured process replay validation. Existing process
events such as `action_defeat_credit` are still reported as unsupported. The
next process-audit pass should validate defeat-credit and damage-skip process
events against damage records, HP state changes, and action-local target
eligibility.
