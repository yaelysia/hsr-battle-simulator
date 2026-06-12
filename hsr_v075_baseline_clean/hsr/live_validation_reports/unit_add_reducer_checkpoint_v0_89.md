# Unit Add Reducer Checkpoint v0.89

Date: 2026-06-13

## Scope

This checkpoint continues the transition replay work after
`transition_reducer_checkpoint_v0_88.md`.

Covered reducer paths:

- `battle.units.<unit_id>` add/replace transitions now generate full-scene
  entity records from unit payloads.
- Unit removal already supported by v0.88 remains supported.
- Unit add/replace also creates action-axis rows when the unit is on timeline.
- Added full-scene group placement for allies, summons, enemies, and others.
- Rebuilds status payload projections in `special_mechanics.status_payloads`
  after status changes.
- Recomputes action-axis speed/interval from local stat/status data after
  status changes, without overwriting complex panel stats such as dynamic
  AttackConvert-derived ATK.

This removes the last unsupported reducer paths hit by the current C0 to C8
live route. Remaining full-snapshot diffs are derived view mismatches, not
unapplied transition paths.

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
  --output /tmp/hsr_unit_add_reducer_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_unit_add_reducer_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_unit_add_reducer_seele_five_dummy.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 transitions with replay validation: 10.
- C0 to C8 direct replay matches: 10 / 10.
- C0 to C8 replay ok with no unsupported paths: 10 / 10.
- C0 to C8 unsupported replay paths: 0.
- C0 to C8 full snapshot matches: 7 / 10.
- Auto probe assertions: ok, replay direct/full match 1 / 1.
- Seele five-dummy route assertions: ok.
- Seele five-dummy replay direct match: 4 / 4.
- Seele five-dummy replay full match: 4 / 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

## Remaining Work

The main reducer gap is now derived panel-stat replay. C0 to C8 still has
full-snapshot diffs for dynamic panel fields such as Sparkle/Dan Heng PT ATK and
crit-damage windows. Those require moving panel-stat derivation behind reusable
rule functions instead of duplicating partial formulas in the reducer.
