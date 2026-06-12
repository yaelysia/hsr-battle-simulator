# Target Decision Trace Checkpoint v0.83

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`unit_wave_transition_checkpoint_v0_82.md`.

Covered runtime paths:

- `TargetResolution` now carries a `decision_trace` list.
- `SettlementCollector.record_target` preserves prior decision trace entries
  when the final resolved target list is written.
- `select_targets` records policy, context targets, candidate ids, resolved ids,
  and reason whenever a settlement is active.
- `resolve_packet_targets` records packet-level target resolution, including
  explicit packet targets, target refs, target-policy overrides, and default
  action-target inheritance.
- Route-step auto target selection now happens after the action settlement is
  created, so action-level auto target decisions are recorded.
- Queued deferred target selection continues to record pending selector flag
  consumption and now also records the target decision itself.

This is an audit-only extension: it does not change target selection semantics.
It makes the target axis explainable from the transition stream instead of only
showing the final target list.

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
  --output /tmp/hsr_target_trace_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_target_trace_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_target_trace_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/kernel.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/settlement/collector.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  hsr_v075_baseline_clean/hsr/live_validation_reports/trigger_usage_transition_checkpoint_v0_80.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/queued_target_selector_transition_v0_81.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/unit_wave_transition_checkpoint_v0_82.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/target_decision_trace_checkpoint_v0_83.md
```

Results:

- Targeted action and packet decision trace case: PASS.
- Targeted queued pending-selector decision trace case: PASS.
- Targeted `summon_unit` add case: PASS.
- Targeted summon lifecycle remove case: PASS.
- Targeted action-owned wave spawn case: PASS.
- Seele five-dummy route assertions: ok.
- Seele five-dummy target decision trace entries: 10.
- Seele five-dummy trigger usage state changes: 3.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 target decision trace entries: 21.
- C0 to C8 target decision stages: `packet_targets`, `select_targets`.
- C0 to C8 battle unit state changes: 2.
- C0 to C8 queue state changes: 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- Auto probe assertions: ok, executed step count 1.

## Remaining Work

Effect target selection audits, action-list mutations, defeat-credit context
sets, and richer RNG ledgers still need explicit transition objects before the
simulator can claim fully replayable state transitions.
