# Timeline Process Checkpoint v0.98

Date: 2026-06-13

## Purpose

This checkpoint adds an action-local process event for regular timeline
advancement. v0.97 made each `unit.remaining_av` state change emit one
`AVRecord`; this pass groups the related `global.av` tick and per-unit AV
changes into one replayable `timeline_tick` process fact.

## Changes

- Added `BattleSimulator.advance_regular_timeline()` as the shared runtime path
  for regular timeline advancement.
- `advance_until_regular_actor()` and `advance_to_next_regular_actor()` now call
  the shared helper instead of duplicating the global/unit AV commit loop.
- Each regular timeline advancement now records one `ProcessEvent` with
  `event_type = "timeline_tick"` when a settlement collector is present.
- The process event payload records:
  - old/new global AV and delta;
  - old/new cycle index;
  - next actor id;
  - the `global.av` state-change sequence;
  - every affected unit's old/new remaining AV, old/new absolute AV, speed,
    action interval, AV delta, and `unit.remaining_av` state-change sequence.

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
  --output /tmp/hsr_v098_timeline_process_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v098_timeline_process_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v098_timeline_process_seele_five_dummy.json
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

Timeline process coverage:

- C0 to C8: 6 `timeline_tick` process events, matching 6 regular timeline
  `global.av` changes.
- C0 to C8: the 6 timeline events contain 44 unit AV rows, matching 44
  `AVRecord(reason="timeline_tick")` rows.
- Seele five-dummy: 1 `timeline_tick` process event, containing 5 unit AV rows
  and matching 5 `AVRecord(reason="timeline_tick")` rows.
- Auto probe: 0 regular timeline ticks in this short probe, so 0 timeline
  process events.
- In all checked outputs, every timeline process event had matching unit row
  counts for the timeline-tick AV records in that settlement.

## Remaining Work

The timeline tick is now visible as one grouped process event, but reducer
replay still consumes the flat `state_changes` list rather than process events.
A later pass should teach the reducer to optionally replay/validate grouped
process events as higher-level transitions, while keeping the flat state-change
path as the canonical compatibility layer.
