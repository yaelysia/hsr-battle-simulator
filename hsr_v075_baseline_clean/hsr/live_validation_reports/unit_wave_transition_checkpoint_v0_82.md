# Unit and Wave Transition Checkpoint v0.82

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`queued_target_selector_transition_v0_81.md`.

Covered runtime paths:

- Unit additions through `battle.units.<unit_id>`.
- Unit removals through `battle.units.<unit_id>` with `delta = "remove"`.
- Wave index changes through `global.wave_index`.
- `summon_unit` effects now add units through the transition kernel.
- Souldragon bondmate summoning now adds the attached unit through the
  transition kernel.
- Summon lifecycle removals now remove units through the transition kernel.
- Wave spawn now records spawned units and wave index through the transition
  kernel. If the wave transition happens during an action settlement, the
  spawned units are attached to that same action transition.

The unit payload used by these changes includes current resources, action axis
state, statuses, flags, action definitions, and status definitions. This keeps
runtime unit add/replace/remove operations replayable from the transition
stream instead of requiring out-of-band mutation knowledge.

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
  --output /tmp/hsr_unit_wave_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_unit_wave_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_unit_wave_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  hsr_v075_baseline_clean/hsr/live_validation_reports/trigger_usage_transition_checkpoint_v0_80.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/queued_target_selector_transition_v0_81.md \
  hsr_v075_baseline_clean/hsr/live_validation_reports/unit_wave_transition_checkpoint_v0_82.md
```

Results:

- Targeted `summon_unit` add case: PASS.
- Targeted summon lifecycle remove case: PASS.
- Targeted action-owned wave spawn case: PASS.
- Targeted queued pending-selector case: PASS.
- Targeted action-resolution usage key case: PASS.
- Targeted owner-turn usage reset case: PASS.
- Targeted `reset_trigger_usage` effect case: PASS.
- Seele five-dummy route assertions: ok.
- Seele five-dummy trigger usage state changes: 3.
- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- C0 to C8 battle unit state changes: 2.
- C0 to C8 wave index state changes: 0.
- C0 to C8 queue state changes: 4.
- C0 to C8 trigger usage state changes: 0.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- Auto probe assertions: ok, executed step count 1.

## Remaining Work

Action-list mutations, non-settlement target selection audits, defeat-credit
context sets, and richer RNG/target-selection ledgers still need explicit
transition objects before the simulator can claim fully replayable state
transitions.
