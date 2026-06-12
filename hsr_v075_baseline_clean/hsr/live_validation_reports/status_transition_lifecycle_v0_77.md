# Status Transition Lifecycle Checkpoint v0.77

Date: 2026-06-13

## Scope

This checkpoint extends the action transition kernel so status runtime state is
emitted from the same commit path that mutates battle state.

Covered runtime paths:

- Whole status add, refresh, and remove through `unit.statuses.<status_id>`.
- Status scalar fields through `unit.statuses.<status_id>.stacks`,
  `duration_value`, `duration_type`, `duration_extra_turn_consumes`, and
  `max_stacks`.
- Status modifier entries through
  `unit.statuses.<status_id>.modifiers.<key>`.
- Data-driven `add_status`, `remove_status`, duration expiry, hit/attack
  duration expiry, cleanse, zone expiry, dispel categories, weakness-break
  aftermath, bondmate AttackConvert, shield refresh tracking, Glory, Titanic
  Corpus, armor layers, entanglement stack payloads, and count-attacks-taken
  counters.

The old `UnitState.add_status` and `UnitState.remove_status` container helpers
remain in place, but current external call sites no longer use them directly.

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
  --output /tmp/hsr_special_status_c0_to_c8.json
python3 -B simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --auto-probe-steps 1 \
  --output /tmp/hsr_special_status_auto_probe.json
git diff --check -- \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/kernel.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_engine/settlement/collector.py \
  hsr_v075_baseline_clean/hsr/simulator_v7_7/hsr_simulator_prototype_v7_7.py
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 8 examples pass.
- Phase 4 verification: PASS, all 8 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 log event count: 172.
- Tribbie follow-up total: `4393.00559968331`.
- Seele skill total: `115919.63539530325`.
- C0 to C8 status state changes: 31.
- C0 to C8 status modifier state changes: 4.
- Auto probe assertions: ok, executed step count 1.
- Diff whitespace check: clean.

## Remaining Work

The transition kernel still does not cover every possible runtime mutation.
Remaining known areas include non-status unit flags, unit stat/toughness direct
setters, summon list changes, queue mutations, and richer RNG/event ledgers.
Those should continue to move behind explicit commit helpers before the engine
can claim full replayable state transitions.
