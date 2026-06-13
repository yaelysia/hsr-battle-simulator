# Target Decision Process Checkpoint v0.104

Date: 2026-06-13

## Purpose

This checkpoint promotes target-decision trace entries into strict process
events. v0.103 made the final action target resolution replay-visible; v0.104
adds the intermediate decision steps behind that result, including packet-level
target overrides and effect-level target resolution.

## Changes

- `SettlementCollector.record_target_decision()` now emits a `target_decision`
  `ProcessEvent` for each target decision trace entry.
- The event payload records:
  - `decision_index`
  - `stage`
  - `actor_id`
  - `action_id`
  - `resolved_target_ids`
  - the full original `decision` payload
- `transition_reducer._validate_process_events()` now validates
  `target_decision` events.
- The validator checks:
  - event `subject_id` matches the payload actor;
  - event reason is `target:decision`;
  - payload actor/action match the transition request;
  - event source matches the request source;
  - `decision_index` is present and unique;
  - `stage` is non-empty;
  - `resolved_target_ids` is a list;
  - embedded `decision.stage` and `decision.resolved_target_ids` match the
    top-level payload fields;
  - final `target_resolution.decision_trace` has the same count as the
    emitted decision events;
  - each emitted decision payload matches the corresponding
    `decision_trace[decision_index - 1]` entry.
- `replay_validation` now reports:
  - `target_decision_count`
  - `target_decision_valid_count`

This keeps the final target result and its derivation separate:
`target_resolution` is the final resolved action target set, while
`target_decision` records the decision steps that led to or occurred under that
action.

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
  --output /tmp/hsr_v104_target_decision_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v104_target_decision_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v104_target_decision_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v104_target_decision_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v104_target_decision_derived_skip.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 process events: 56, unsupported 0, mismatches 0.
- C0 to C8 target resolutions: 12 / 12 valid.
- C0 to C8 target decisions: 38 / 38 valid.
- C0 to C8 timeline ticks: 6 / 6 valid.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Auto probe target decisions: 3 / 3 valid.
- Seele five-dummy replay direct/full/process match: 4 / 4.
- Seele five-dummy target resolutions: 6 / 6 valid.
- Seele five-dummy target decisions: 10 / 10 valid.
- Seele five-dummy timeline ticks: 1 / 1 valid.
- Seele five-dummy action defeat credits: 2 / 2 valid.
- Phase-lock process case target decisions: 3 / 3 valid.
- Phase-lock process case phase damage locks: 1 / 1 valid.
- Phase-lock process case phase damage skips: 2 / 2 valid.
- Derived-damage skip process case target decisions: 2 / 2 valid.
- Derived-damage skip process case action defeat credits: 1 / 1 valid.
- Derived-damage skip process case derived damage skips: 1 / 1 valid.
- Unsupported process event types in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the derived-damage skip process case first
  `target_decision.payload.resolved_target_ids`.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported
  `process_events[1].payload.decision.resolved_target_ids`.

## Remaining Work

Action-level target resolution and nested target decisions are now process
events. The next remaining gap in the same chain is packet/effect damage
settlement: damage records still carry rich formula ledgers, but their
relationship to process events and state changes is only partially strict.
