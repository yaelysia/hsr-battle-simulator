# Contextual Stat Rules Checkpoint v0.92

Date: 2026-06-13

## Scope

This checkpoint continues the shared rule-source work after
`stat_rules_checkpoint_v0_91.md`.

Covered refactor:

- Added `stat_rules.runtime_contextual_stat()` for runtime stat evaluation.
- Moved HP/max-HP scaling semantics, dotted stat references, conditional
  status modifiers, packet-local stat modifiers, split-stat recomposition, and
  dynamic stat addition assembly behind the shared stat rule module.
- Reduced `BattleEngine.contextual_stat()` to an adapter that supplies battle
  engine callbacks for unit lookup, special unit resolution, condition
  evaluation, and runtime dynamic stat additions.
- Kept `BattleEngine.eval_condition()` and
  `BattleEngine.derived_status_add_for_stat()` as engine-owned callbacks for
  now, so this checkpoint does not change condition semantics or dynamic source
  resolution behavior.

This moves the highest-risk runtime stat path closer to the same rule source
used by snapshot replay, without changing the public `contextual_stat()` call
surface.

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
  --output /tmp/hsr_v092_contextual_stat_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v092_contextual_stat_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v092_contextual_stat_seele_five_dummy.json
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

The next stat-rule cleanup is to move runtime `derived_stat_add` source
resolution into a reusable helper as well. That likely needs a small context
adapter for actor/source/target unit names so snapshot replay and runtime
settlement can resolve dynamic sources consistently.

The reducer still builds initial panel values from unit-add payloads locally.
After runtime and snapshot stat contexts converge further, that construction can
also move behind `stat_rules`.
