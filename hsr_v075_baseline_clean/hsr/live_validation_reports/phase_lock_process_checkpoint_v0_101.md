# Phase Lock Process Checkpoint v0.101

Date: 2026-06-13

## Purpose

This checkpoint adds replay validation for phase-boundary process events. These
events explain why later damage in the same action is skipped after a phase HP
bar is depleted. That makes a key non-damage intermediate decision explicit and
auditable instead of leaving it as implicit control flow.

## Changes

- Added `simulator_v7_7/examples/phase_lock_process_case.yaml`, a minimal
  two-packet phase-HP case:
  - first packet depletes the first phase HP bar;
  - second packet is skipped by the phase lock;
  - an after-damage `damage_unit` effect is also skipped by the same lock.
- Added process replay validation for:
  - `phase_damage_lock`
  - `damage_target_skip`
  - `effect_damage_target_skip`
- The validator now checks:
  - target id and `subject_id` consistency;
  - `phase_locked_targets` includes the target;
  - phase locks have a matching `unit.hp_bars_remaining` state change;
  - phase locks report positive `bars_depleted`;
  - skip events occur after a prior phase lock for the same target in the same
    transition;
  - damage packet skips include `packet_id`;
  - effect damage skips include a `damage_unit` effect payload.
- `replay_validation` now reports:
  - `phase_damage_lock_count`
  - `phase_damage_lock_valid_count`
  - `phase_damage_skip_count`
  - `phase_damage_skip_valid_count`

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
  --output /tmp/hsr_v101_phase_process_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v101_phase_process_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v101_phase_process_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/phase_lock_process_case.yaml \
  --output /tmp/hsr_v101_phase_process_case.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 9 examples pass.
- Phase 4 verification: PASS, all 9 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 replay ok: 10 / 10.
- C0 to C8 direct/full/process replay matches: 10 / 10.
- Seele five-dummy replay direct/full/process match: 4 / 4.
- Seele five-dummy timeline ticks: 1 / 1 valid.
- Seele five-dummy action defeat credits: 2 / 2 valid.
- Phase-lock process case replay direct/full/process match: 1 / 1.
- Phase-lock process case phase damage locks: 1 / 1 valid.
- Phase-lock process case phase damage skips: 2 / 2 valid.
- Unsupported process event types in checked outputs: none.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

Negative smoke check:

- Manually corrupted the phase-lock process case `damage_target_skip`
  `phase_locked_targets` list.
- `validate_transition_replay()` returned `process_event_match = False`,
  `ok = False`, and reported
  `target_missing_from_phase_locked_targets`.

## Remaining Work

Process-event replay now covers timeline ticks, defeat credits, and phase-lock
damage skips. Damage-skip process events for non-phase reasons and richer
derived-damage eligibility decisions still need targeted fixtures before they
should be made strict.
