# AV Settlement Checkpoint v0.97

Date: 2026-06-13

## Purpose

This checkpoint moves action-value audit records closer to the real state-change
source. Before this change, some AV records were handwritten around specific
effects or regular-action endings, while many `unit.remaining_av` state changes
had no matching `AVRecord`. The new invariant is:

`unit.remaining_av` StateChange count == `AVRecord` count for every settlement.

## Changes

- Extended `AVRecord` with trace fields:
  - `old_absolute_av`
  - `new_absolute_av`
  - `speed`
  - `action_interval`
  - `detail`
- Updated `SettlementCollector.record_av()` so these fields are preserved
  instead of discarded.
- Added `BattleSimulator.record_committed_av_change()` as the projection point
  from a committed `unit.remaining_av` state change to an AV settlement record.
- Updated `commit_unit_remaining_av()` to commit the state change first, then
  append exactly one `AVRecord` with `record_state_change=False`.
- Removed handwritten `_settle(..., "av")` blocks from frozen action advance,
  regular action end, and effect advance/delay handling.
- Added typed AV reasons at call sites for timeline ticks, regular action
  interval refreshes, action advances, delays, and speed-change recalculation.

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
  --output /tmp/hsr_v097_av_settlement_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v097_av_settlement_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v097_av_settlement_seele_five_dummy.json
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

AV settlement coverage:

- C0 to C8: 57 `AVRecord` rows and 57 `unit.remaining_av` state changes.
- Auto probe: 1 `AVRecord` row and 1 `unit.remaining_av` state change.
- Seele five-dummy: 8 `AVRecord` rows and 8 `unit.remaining_av` state changes.
- Every AVRecord in the three outputs includes `old_absolute_av`,
  `new_absolute_av`, `speed`, `action_interval`, and `detail`.

C0 to C8 AV reasons:

- `timeline_tick`: 44
- `regular_turn_end`: 8
- `action_advance`: 3
- `speed_change`: 1
- `effect:set_resources:remaining_av`: 1

## Remaining Work

AV settlement is now generated from the same runtime commit that changes
`unit.remaining_av`, but global timeline advancement still commits
`global.av` separately. A later pass should introduce a higher-level timeline
settlement object that groups the global AV tick and all affected unit
remaining-AV changes into one replayable timeline event.
