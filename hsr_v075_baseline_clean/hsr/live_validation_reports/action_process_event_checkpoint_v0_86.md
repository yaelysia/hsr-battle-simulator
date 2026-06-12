# Action Process Event Checkpoint v0.86

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`rng_event_ledger_checkpoint_v0_85.md`.

Covered runtime paths:

- Added `ProcessEvent` to the transition kernel.
- `ActionTransition` now serializes `process_events` beside state changes,
  target resolution data, and RNG events.
- Action-local defeat credit changes now emit `action_defeat_credit`.
- Derived damage target filtering now emits `derived_damage_target_skip` for
  targets already defeated in the same action and for dead/missing targets.
- Phase-HP action locks now emit `phase_damage_lock`.
- Later direct packets skipped by a phase-HP action lock now emit
  `damage_target_skip`.
- Later effect damage skipped by a phase-HP action lock now emits
  `effect_damage_target_skip`.
- Primary action packets that intentionally continue resolving against a target
  already defeated by the same primary action now emit
  `primary_damage_continue_defeated_target`.

This is an audit-only extension. It records action-local process facts that
affect control flow without treating them as persistent battle state.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr` unless noted.

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_process_events_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_process_events_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_process_events_seele_five_dummy.json
```

Results:

- Targeted defeat-credit plus derived-damage skip case: PASS.
- Targeted phase-HP lock plus later-packet skip case: PASS.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 process events: 0.
- C0 to C8 RNG events including queued action transitions: 14, all `crit`.
- Auto probe assertions: ok, executed step count 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy process events: 2, both `action_defeat_credit`.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

## Remaining Work

Action-list mutations, route-level process/RNG decisions outside an active
settlement, replay-oriented RNG input policy, and a reducer that applies
`ActionTransition` back onto a snapshot still need explicit implementation
before the simulator can claim fully replayable state transitions.
