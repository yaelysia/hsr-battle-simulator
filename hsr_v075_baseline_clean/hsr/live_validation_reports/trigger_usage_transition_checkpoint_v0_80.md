# Trigger Usage Transition Checkpoint v0.80

Date: 2026-06-13

## Scope

This checkpoint continues the action transition refactor after
`queue_transition_checkpoint_v0_79.md`.

Covered runtime paths:

- Trigger usage counters through `battle.trigger_usage.<key>`.
- Usage-limit increments now pass through `commit_trigger_usage`.
- Owner-turn usage resets now pass through `commit_trigger_usage_remove`.
- `reset_trigger_usage` effects now remove matching counters through the same
  transition path.
- `action_resolution` usage keys no longer depend on Python object memory
  addresses. They use a deterministic per-simulator action resolution id such
  as `action_1`, `action_2`, and so on.

The transition kernel now captures trigger gating state that can change whether
later triggers fire. This makes usage-limit behavior visible in the same
state-change stream as resources, statuses, flags, toughness, and queues.

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
  --output /tmp/hsr_trigger_usage_seele_five_dummy.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_trigger_usage_c0_to_c8.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_trigger_usage_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  hsr_v075_baseline_clean/hsr/live_validation_reports/trigger_usage_transition_checkpoint_v0_80.md
```

Results:

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
- C0 to C8 trigger usage state changes: 0.
- C0 to C8 queue state changes: 4.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- Auto probe assertions: ok, executed step count 1.

## Remaining Work

Unit add/remove, action-list mutations, pending selector cleanup during target
resolution, defeat-credit context sets, and richer RNG/target-selection ledgers
still need explicit transition objects before the simulator can claim fully
replayable state transitions.
