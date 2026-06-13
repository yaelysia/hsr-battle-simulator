# Derived Stat Rules Checkpoint v0.93

Date: 2026-06-13

## Scope

This checkpoint continues the shared stat-rule work after
`contextual_stat_rules_checkpoint_v0_92.md`.

Covered refactor:

- Added `stat_rules.runtime_derived_stat_add()` for runtime
  `derived_stat_add` evaluation.
- Moved runtime `derived_stat_add` source/source-stat parsing, special unit
  resolution, self-recursion guard, source context construction, scale, ratio,
  and flat addition handling behind the shared stat rule module.
- Reduced `BattleEngine.derived_status_add_for_stat()` to an adapter that
  supplies unit lookup, special unit resolution, and recursive contextual stat
  evaluation callbacks.

This further narrows the gap between runtime settlement stat evaluation and
snapshot replay stat evaluation. AttackConvert-style derived stats now use the
same rule module for runtime source resolution and replay dependency handling.

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
  --output /tmp/hsr_v093_derived_stat_rules_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v093_derived_stat_rules_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v093_derived_stat_rules_seele_five_dummy.json
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

Snapshot `contextual_entity_stat()` still resolves derived stat sources from
canonical snapshot IDs directly, while runtime uses special-unit source
resolution through the adapter. A future context adapter should make runtime
and snapshot source resolution explicit variants of one source-resolution rule.

The reducer still builds initial panel values from unit-add payloads locally.
After source resolution is unified, this construction can move behind
`stat_rules` too.
