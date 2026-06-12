# State Flag and Toughness Transition Checkpoint v0.78

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`status_transition_lifecycle_v0_77.md`.

Covered runtime paths:

- Global flags through `global.flags.<key>`.
- Unit flags through `unit.flags.<key>`, including explicit removal with
  `delta = "remove"`.
- Toughness fields through `unit.toughness`, `unit.max_toughness`, and
  `unit.is_broken`.
- Turn lifecycle flags, target marks, zones, generated flag effects, random
  masks, dynamic entity params, unit counters, enemy AI decision cursors, enemy
  skill-use records, Souldragon enhancement lifecycle flags, recoverable HP cap
  flags, and phase-transition immediate-action flags.
- Damage toughness reduction and weakness-break state now commit through the
  transition kernel before settlement records are appended.

Direct runtime assignment searches for global flags, unit flags, toughness, and
broken state now only match the `commit_state_change` implementation itself.

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
  --output /tmp/hsr_flag_toughness_c0_to_c8.json
python3 -B simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_flag_toughness_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/kernel.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/settlement/collector.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  hsr_v075_baseline_clean/hsr/live_validation_reports/status_transition_lifecycle_v0_77.md
```

Results:

- Targeted in-memory flag/toughness case: PASS.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- C0 to C8 flag state changes: 44.
- C0 to C8 toughness/break state changes: 6.
- Auto probe assertions: ok, executed step count 1.
- Diff whitespace check: clean.

## Remaining Work

Queue mutations, unit add/remove, action-list mutations, trigger usage mutation,
defeat-credit context sets, and richer RNG/target-selection ledgers still need
explicit transition objects before the simulator can claim fully replayable
state transitions.
