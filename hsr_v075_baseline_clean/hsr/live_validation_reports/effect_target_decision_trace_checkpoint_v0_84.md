# Effect Target Decision Trace Checkpoint v0.84

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`target_decision_trace_checkpoint_v0_83.md`.

Covered runtime path:

- `resolve_effect_targets` now records `effect_targets` entries in
  `TargetResolution.decision_trace` when it resolves a real effect payload.
- Effect target trace entries include effect type/id, raw target spec, expanded
  target specs, default target policy, context target ids, and resolved target
  ids.
- Condition/reference callers that reuse `resolve_effect_targets` without a
  real effect `type` are intentionally not recorded as effect target decisions.

This is an audit-only extension. It does not change effect target semantics; it
only makes effect-owned target resolution visible beside action and packet
target decisions.

## Validation

Commands run from `hsr_v075_baseline_clean/hsr` unless noted.

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
cd simulator_v7_7 && python3 hsr_simulator_prototype_v7_7.py \
  examples/seele_five_dummy_case_v0_3.yaml \
  --route-mode exact \
  --output /tmp/hsr_effect_target_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_effect_target_trace_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_effect_target_trace_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/kernel.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/settlement/collector.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  hsr_v075_baseline_clean/hsr/live_validation_reports/trigger_usage_transition_checkpoint_v0_80.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/queued_target_selector_transition_v0_81.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/unit_wave_transition_checkpoint_v0_82.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/target_decision_trace_checkpoint_v0_83.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/effect_target_decision_trace_checkpoint_v0_84.md
```

Results:

- Targeted effect target decision trace case: PASS.
- Targeted action and packet decision trace case: PASS.
- Targeted queued pending-selector decision trace case: PASS.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 target decision trace entries: 44.
- C0 to C8 effect target decision trace entries: 23.
- C0 to C8 target decision stages: `effect_targets`, `packet_targets`,
  `select_targets`.
- C0 to C8 battle unit state changes: 2.
- C0 to C8 queue state changes: 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- Auto probe assertions: ok, executed step count 1.
- Auto probe target decision trace entries: 3.
- Seele five-dummy route assertions: ok.
- Seele five-dummy target decision trace entries: 16.
- Seele five-dummy effect target decision trace entries: 6.
- Seele five-dummy trigger usage state changes: 3.

## Remaining Work

Action-list mutations, defeat-credit context sets, and richer RNG ledgers still
need explicit transition objects before the simulator can claim fully replayable
state transitions.
