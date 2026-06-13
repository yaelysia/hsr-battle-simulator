# Derived Damage Skip Process Checkpoint v0.102

Date: 2026-06-13

## Purpose

This checkpoint adds replay validation for derived-damage target skips. The
engine already emits these process events when a non-primary damage source sees
that its target was defeated earlier in the same action, or is otherwise not
alive. The replay layer now verifies those events instead of treating them as
opaque logs.

## Changes

- Added `simulator_v7_7/examples/derived_damage_skip_process_case.yaml`, a
  minimal action where:
  - the primary packet defeats the target;
  - an `effects_after_damage` `damage_unit` effect targets the same unit;
  - the derived damage is skipped with
    `derived_damage:already_defeated_this_action`.
- Added process replay validation for `derived_damage_target_skip`.
- The validator now checks:
  - target id and `subject_id` consistency;
  - skip reason is one of the supported derived-damage reasons;
  - `effect` is a non-empty effect name;
  - `already_defeated_this_action` payloads include the target in
    `defeated_targets_this_action`;
  - `already_defeated_this_action` skips occur after a valid
    `action_defeat_credit` for the same target in the same transition;
  - `already_defeated_this_action` has a matching `unit.alive True->False`
    state change;
  - `not_alive` payloads include a boolean `target_exists`.
- `replay_validation` now reports:
  - `derived_damage_skip_count`
  - `derived_damage_skip_valid_count`

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
  --output /tmp/hsr_v102_derived_skip_process_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_v102_derived_skip_process_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v102_derived_skip_process_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v102_derived_skip_process_phase_lock.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/derived_damage_skip_process_case.yaml \
  --output /tmp/hsr_v102_derived_skip_process_case.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 direct/full/process replay matches: 10 / 10.
- C0 to C8 timeline ticks: 6 / 6 valid.
- Auto probe assertions: ok, 1 / 1 actions executed.
- Seele five-dummy replay direct/full/process match: 4 / 4.
- Seele five-dummy timeline ticks: 1 / 1 valid.
- Seele five-dummy action defeat credits: 2 / 2 valid.
- Phase-lock process case replay direct/full/process match: 1 / 1.
- Phase-lock process case phase damage locks: 1 / 1 valid.
- Phase-lock process case phase damage skips: 2 / 2 valid.
- Derived-damage skip process case replay direct/full/process match: 1 / 1.
- Derived-damage skip process case action defeat credits: 1 / 1 valid.
- Derived-damage skip process case derived damage skips: 1 / 1 valid.
- Unsupported process event types in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the derived-damage skip process case
  `defeated_targets_this_action` list.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported `target_missing_from_defeated_targets`.

## Remaining Work

Process-event replay now covers timeline ticks, defeat credits, phase-lock
damage skips, and derived-damage target skips. The next useful target is to keep
moving action-local control-flow facts out of ad hoc logs and into strict
process events with targeted fixtures.
