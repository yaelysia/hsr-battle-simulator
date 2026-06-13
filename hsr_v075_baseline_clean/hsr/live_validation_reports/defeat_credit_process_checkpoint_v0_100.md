# Defeat Credit Process Checkpoint v0.100

Date: 2026-06-13

## Purpose

This checkpoint extends process-event replay validation beyond timeline ticks.
`action_defeat_credit` records are action-local facts used to preserve who
defeated a target inside an action window, so derived damage and follow-up
logic can make deterministic decisions without rediscovering kill ownership.

## Changes

- Added `action_defeat_credit` support to
  `hsr_engine.transition_reducer._validate_process_events()`.
- The validator now checks that a defeat-credit event:
  - has a payload dictionary;
  - uses `subject_id == payload.target_id`;
  - uses reason `action:defeat_credit`;
  - has source owner matching `payload.source_id` when the source id is present;
  - includes the target in `defeated_targets_this_action`;
  - includes a target credit entry in `defeat_credits_this_action`;
  - has credit `source_id` and `damage_kind` matching the payload;
  - has a matching `unit.alive` state change from `True` to `False`;
  - has a matching target damage state change on `unit.hp_or_shield`.
- `replay_validation` now reports:
  - `action_defeat_credit_count`
  - `action_defeat_credit_valid_count`
- Unsupported process-event counts now exclude supported defeat-credit events.

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
  --output /tmp/hsr_v100_defeat_credit_process_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v100_defeat_credit_process_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v100_defeat_credit_process_seele_five_dummy.json
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
- C0 to C8 direct/full/process replay matches: 10 / 10.
- C0 to C8 supported process events: 6 / 6, all timeline ticks.
- Auto probe assertions: ok, replay direct/full/process match 1 / 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy replay direct/full/process match 4 / 4.
- Seele five-dummy supported process events: 3 / 3.
- Seele five-dummy timeline ticks: 1 / 1 valid.
- Seele five-dummy action defeat credits: 2 / 2 valid.
- Unsupported process event types in the three checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the first Seele five-dummy `action_defeat_credit` credit
  source id.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported a mismatch at
  `process_events[0].payload.defeat_credits_this_action.e1.source_id`.

## Remaining Work

The replay validator now covers the process events currently present in the
main C0 to C8 and Seele five-dummy checks. Other process event classes such as
damage-target skips and phase-damage locks are already emitted by the runtime,
but need targeted scenario outputs before strict validation rules should be
enabled for them.
