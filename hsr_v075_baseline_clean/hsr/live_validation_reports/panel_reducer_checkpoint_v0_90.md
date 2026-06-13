# Panel Reducer Checkpoint v0.90

Date: 2026-06-13

## Scope

This checkpoint continues the transition replay work after
`unit_add_reducer_checkpoint_v0_89.md`.

Covered reducer behavior:

- Status modifier changes now mark only affected panel stats as dirty instead
  of broadly rebuilding the whole panel.
- Dirty panel stats are flushed after all `StateChange` entries in an action
  transition, so same-action source and target status changes are evaluated
  from the final post-change snapshot.
- Panel stat recomputation now supports `derived_stat_add` entries such as the
  Dan Heng PT AttackConvert ATK contribution.
- Dirty stat propagation now follows `derived_stat_add.source/source_stat`
  dependencies, so a source stat change also refreshes dependent panel stats.
- Speed dirty flush continues to synchronize the entity action-axis projection
  and the canonical `action_axis` row.

This removes the remaining C0 to C8 full-snapshot replay diffs from v0.89 while
keeping direct transition replay fully supported.

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
  --output /tmp/hsr_v090_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v090_c0_to_c8_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v090_seele_five_dummy.json
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

Panel stat derivation is still duplicated in the simulator and reducer. The
next structural step is to move contextual stat derivation behind a shared rule
helper so action settlement generation, replay, and future audit views use the
same source of truth.

The current validation still covers a narrow route set. Broader live routes are
needed before treating reducer full-snapshot replay as generally complete.
