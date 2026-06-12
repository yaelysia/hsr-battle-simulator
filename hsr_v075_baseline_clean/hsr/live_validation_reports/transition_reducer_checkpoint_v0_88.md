# Transition Reducer Checkpoint v0.88

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`unit_action_def_transition_checkpoint_v0_87.md`.

Covered runtime paths:

- Added `hsr_engine.transition_reducer`.
- Each serialized action transition now includes `replay_validation`.
- The reducer applies replayable `StateChange` entries to
  `before_snapshot` and validates the result against `after_snapshot`.
- Audit-only settlement summary changes such as `unit.turn` and
  `unit.hp_or_shield` are explicitly reported instead of being treated as
  persistent mutations.
- Internal-only action definition changes are reported separately because full
  scene snapshots do not currently expose action definitions.
- Unsupported paths are reported explicitly; they are not hidden.
- Numeric replay comparison uses a small tolerance for snapshot rounding.

The reducer currently validates direct state paths on full-scene snapshots. It
does not yet regenerate every derived snapshot view such as panel stats and
special-mechanic payload projections, and it does not yet build a full-scene
entity record from a unit-add payload.

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
  --output /tmp/hsr_reducer_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_reducer_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_reducer_seele_five_dummy.json
```

Results:

- Targeted minimal damage/resource replay case: PASS, direct and full snapshot
  replay both matched.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 transitions with replay validation: 10.
- C0 to C8 direct replay matches: 10 / 10.
- C0 to C8 replay ok with no unsupported paths: 9 / 10.
- C0 to C8 full snapshot matches: 3 / 10.
- C0 to C8 unsupported replay paths: `battle.units.furiae_warrior_1`,
  `battle.units.furiae_warrior_2`.
- C0 to C8 audit-only state changes: 28 (`unit.turn`, `unit.hp_or_shield`).
- Auto probe assertions: ok, replay direct/full match 1 / 1.
- Seele five-dummy route assertions: ok, replay direct match 4 / 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total in C0 to C8: `115919.63539530325`.

## Remaining Work

The next reducer milestone should generate full-scene entity records for
`battle.units.<unit_id>` add/replace transitions and recompute derived snapshot
views such as panel stats and special-mechanic status payloads. After that,
full snapshot replay can become a hard gate for more live routes.
