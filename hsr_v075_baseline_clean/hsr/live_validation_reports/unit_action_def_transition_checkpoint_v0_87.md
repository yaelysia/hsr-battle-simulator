# Unit Action Definition Transition Checkpoint v0.87

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`action_process_event_checkpoint_v0_86.md`.

Covered runtime paths:

- Added a generic `commit_unit_action_def` helper for unit action definition
  additions/replacements.
- `StateChange` replay now supports `unit.actions.<action_id>`.
- Souldragon default action injection now uses `commit_unit_action_def` when the
  target unit is already present in battle state.
- New units that receive default actions before being inserted into battle state
  still mutate their pending unit object directly; the subsequent unit-add
  transition already carries the complete action definition payload.

This keeps runtime action-list mutations visible as transition state changes
without changing action selection or action execution semantics.

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
  --output /tmp/hsr_action_def_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_action_def_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_action_def_seele_five_dummy.json
```

Results:

- Targeted `commit_unit_action_def` transition case: PASS.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 action-definition state changes: 0.
- Auto probe assertions: ok, executed step count 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy action-definition state changes: 0.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

## Remaining Work

Route-level process/RNG decisions outside an active settlement, replay-oriented
RNG input policy, and a reducer that applies `ActionTransition` back onto a
snapshot remain the main blockers for fully replayable state transitions.
