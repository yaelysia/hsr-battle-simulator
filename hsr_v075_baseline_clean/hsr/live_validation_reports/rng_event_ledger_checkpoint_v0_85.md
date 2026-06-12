# RNG Event Ledger Checkpoint v0.85

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`effect_target_decision_trace_checkpoint_v0_84.md`.

Covered runtime paths:

- Added `RNGEvent` to the transition kernel.
- `ActionTransition` now serializes `rng_events` beside state changes and target
  resolution data.
- Direct damage crit resolution records `crit` RNG events, including forced
  crit, cannot-crit, crit, noncrit, and expected modes.
- Effect-hit checks record `effect_hit` RNG events.
- Generated/probabilistic condition gates record `chance_gate` RNG events.
- Runtime random selectors record `random_select_flag` and `random_choice`
  events with selected indices/values and forced/deterministic mode metadata.
- Direct damage now passes the active packet context into crit resolution so
  damage-owned RNG decisions can attach to the current action settlement.

This is an audit-only extension. It does not change RNG policy or damage/status
settlement semantics; it makes the deterministic branch decision visible in the
canonical action transition.

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
  --output /tmp/hsr_rng_ledger_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_rng_ledger_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_rng_ledger_seele_five_dummy.json
```

Results:

- Targeted in-memory RNG ledger case: PASS.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 route-step settlement RNG events: 11, all `crit`.
- C0 to C8 RNG events including queued action transitions: 14, all `crit`.
- Auto probe assertions: ok, executed step count 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy transition RNG events: 2, all `crit`.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.

## Remaining Work

Action-list mutations, defeat-credit context sets, route-level/global RNG
decisions outside an active settlement, and replay-oriented RNG input policy
still need explicit transition objects before the simulator can claim fully
replayable state transitions.
