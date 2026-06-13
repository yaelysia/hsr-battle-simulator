# Resource Rules Checkpoint v0.95

Date: 2026-06-13

## Scope

This checkpoint starts the same rule-source consolidation for resources after
`panel_payload_rules_checkpoint_v0_94.md`.

Covered refactor:

- Added `hsr_engine.resource_rules` for shared resource normalization and
  snapshot projection helpers.
- Routed runtime commit helpers for HP, max HP, shield, energy, toughness,
  max toughness, and HP bars through shared normalization functions.
- Routed reducer resource replay through `apply_snapshot_resource_change()`,
  including HP/max-HP panel projection and `hp_percent` synchronization.
- Removed reducer-local HP percent and panel-number projection helpers.

This is intended as a no-behavior-change cleanup. It puts the resource write
path and the snapshot replay projection path behind explicit reusable helpers.

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
  --output /tmp/hsr_v095_resource_rules_c0_to_c8_exact.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode auto_probe \
  --output /tmp/hsr_v095_resource_rules_auto_probe.json
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  simulator_v7_7/examples/seele_five_dummy_case_v0_3.yaml \
  --output /tmp/hsr_v095_resource_rules_seele_five_dummy.json
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

Many resource effects still compose their amounts locally before calling the
commit helpers. The next resource refactor should target settlement records for
resource deltas so resource changes are authored once and projected into both
state changes and audit ledgers.

Action-axis and AV rules are still mostly outside shared rule helpers and are a
good next target after resources.
