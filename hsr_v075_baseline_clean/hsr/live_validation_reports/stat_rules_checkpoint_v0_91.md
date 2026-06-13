# Stat Rules Checkpoint v0.91

Date: 2026-06-13

## Scope

This checkpoint continues the transition replay work after
`panel_reducer_checkpoint_v0_90.md`.

Covered refactor:

- Added `hsr_engine.stat_rules` as the shared home for snapshot entity stat and
  panel-derivation helpers.
- Moved canonical panel stat keys out of `transition_reducer.py`.
- Moved reducer-local contextual entity stat replay into `stat_rules`.
- Moved reducer-local `derived_stat_add` dependency propagation into
  `stat_rules`.
- Routed `UnitState.get_stat()` through `stat_rules.unit_stat_value()` so
  runtime unit stats and replay snapshot stats share the same base/pct/flat plus
  unconditional status modifier formula.

This is a structural cleanup, not a rule change. It reduces the risk that live
settlement and transition replay drift apart when basic stat formulas change.

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
  --output /tmp/hsr_v091_stat_rules_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v091_stat_rules_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v091_stat_rules_seele_five_dummy.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 transitions with replay validation: 10, counting queued actions
  once.
- C0 to C8 direct replay matches: 10 / 10.
- C0 to C8 full snapshot matches: 10 / 10.
- C0 to C8 replay ok with no unsupported paths: 10 / 10.
- C0 to C8 unsupported replay paths: 0.
- C0 to C8 direct mismatch count: 0.
- C0 to C8 full diff sample count: 0.
- Auto probe assertions: ok, replay direct/full match 1 / 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy replay direct match: 4 / 4.
- Seele five-dummy replay full match: 4 / 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

## Remaining Work

`BattleEngine.contextual_stat()` still owns conditional status modifiers,
packet-local stat modifiers, dotted stat references, and runtime
`derived_stat_add` source resolution. The next step is to move those contextual
rules behind `stat_rules` without weakening the current route validation.

The reducer still builds initial panel values from unit-add payloads locally.
That can also move behind `stat_rules` after contextual stat handling is
shared.
