# Action Axis Rules Checkpoint v0.96

Date: 2026-06-13

## Purpose

This checkpoint starts consolidating action-axis and AV projection rules after
the resource/stat rule-source cleanups. The goal is no behavior change: keep the
current exact-route replay and full-scene snapshot validation stable while
moving duplicated timeline formulas into a shared rule module.

## Changes

- Added `hsr_engine.action_axis_rules` for shared AV normalization, action-axis
  sorting, `absolute_av` projection, and speed-to-interval snapshot projection.
- Routed runtime `global.av` and `unit.remaining_av` commits through
  `normalize_av()`.
- Routed runtime full-scene snapshot `absolute_av` and top-level action-axis
  ordering through the shared action-axis helpers.
- Routed reducer action-axis replay through the shared helpers for:
  - `absolute_av` synchronization after state changes;
  - top-level action-axis ordering;
  - speed/action interval projection after dirty stat recomputation;
  - unit `remaining_av` projection.

## Validation

Commands:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
cd simulator_v7_7 && python3 test_phase3_verify.py
cd simulator_v7_7 && python3 test_phase4_verify.py
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output /tmp/hsr_v096_action_axis_rules_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v096_action_axis_rules_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v096_action_axis_rules_seele_five_dummy.json
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

This is still only the projection/normalization layer. The next action-axis
refactor should move timeline event settlement itself toward explicit AV
records that are authored once, then projected into state changes, snapshots,
and ledgers. Important remaining targets include action advance/delay sources,
extra-turn and immediate-action timing, summon/attached-unit timeline rules, and
dead/not-on-timeline visibility rules.
