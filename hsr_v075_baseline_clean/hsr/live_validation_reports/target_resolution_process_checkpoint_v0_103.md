# Target Resolution Process Checkpoint v0.103

Date: 2026-06-13

## Purpose

This checkpoint promotes action target resolution into the canonical process
event stream. Target selection is part of the state-transition chain: an action
input is not fully replayable unless the transition can prove which target ids
the engine resolved before applying rules and mutations.

## Changes

- `SettlementCollector.record_target()` now emits a `target_resolution`
  `ProcessEvent` whenever an action target record is written.
- The event payload records:
  - `actor_id`
  - `action_id`
  - `requested_target_ids`
  - `resolved_target_ids`
  - `method`
  - `reason`
  - `source`
- `transition_reducer._validate_process_events()` now validates
  `target_resolution` events.
- The validator checks:
  - event `subject_id` matches the payload actor;
  - event reason is `target:resolution`;
  - payload actor/action/requested targets match the transition request;
  - event source and payload source match the request source;
  - requested/resolved targets are lists;
  - method is a non-empty string;
  - payload reason matches method;
  - the final `transition.target_resolution` matches the latest valid
    `target_resolution` event for stable fields.
- `replay_validation` now reports:
  - `target_resolution_count`
  - `target_resolution_valid_count`

The validator intentionally compares the final target-resolution object only to
the latest valid event. Deferred queued actions can create an initial empty
target-resolution event before a later deferred-policy target selection
overwrites the final resolved targets. Both events are useful intermediate
facts, but only the latest one represents the final action target resolution.

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
  --output /tmp/hsr_v103_target_resolution_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v103_target_resolution_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v103_target_resolution_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v103_target_resolution_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v103_target_resolution_derived_skip.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 process events: 18, unsupported 0, mismatches 0.
- C0 to C8 target resolutions: 12 / 12 valid.
- C0 to C8 timeline ticks: 6 / 6 valid.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Auto probe target resolutions: 1 / 1 valid.
- Seele five-dummy replay direct/full/process match: 4 / 4.
- Seele five-dummy target resolutions: 6 / 6 valid.
- Seele five-dummy timeline ticks: 1 / 1 valid.
- Seele five-dummy action defeat credits: 2 / 2 valid.
- Phase-lock process case target resolutions: 1 / 1 valid.
- Phase-lock process case phase damage locks: 1 / 1 valid.
- Phase-lock process case phase damage skips: 2 / 2 valid.
- Derived-damage skip process case target resolutions: 1 / 1 valid.
- Derived-damage skip process case action defeat credits: 1 / 1 valid.
- Derived-damage skip process case derived damage skips: 1 / 1 valid.
- Unsupported process event types in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the derived-damage skip process case
  `target_resolution.payload.resolved_target_ids`.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported `target_resolution.resolved_target_ids`.

## Remaining Work

Action target resolution is now a replay-validated process fact. Effect-level
target decisions are still stored in `target_resolution.decision_trace`; the
next step is to split those into their own strict process events so nested
effects, packet-level target overrides, and triggered damage can be replayed
without relying on a mutable trace list.
