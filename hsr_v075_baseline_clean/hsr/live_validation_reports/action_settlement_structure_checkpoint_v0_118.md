# Action Settlement Structure Checkpoint v0.118

Date: 2026-06-15

## Purpose

This checkpoint promotes the per-action settlement payload from a loose dict
assembled in `SettlementCollector.to_dict()` into an explicit
`ActionSettlement` object. The JSON output remains backward-compatible: all
existing settlement keys are preserved, and a new top-level settlement
`encoding` marks the serialized object schema.

## Changes

- Added `ACTION_SETTLEMENT_ENCODING = hsr.settlement.action.v1`.
- Added `ActionSettlement` as the top-level settlement object for one action
  input.
- `ActionSettlement.to_dict()` owns JSON-compatible serialization for:
  - target record
  - resource/status/AV/turn/control/mechanic records
  - damage, break, toughness, DoT, and super-break records
  - settlement validation summary
  - kernel transition payload
- `SettlementCollector.to_dict()` now constructs an `ActionSettlement` and
  delegates output serialization to it instead of returning an inline dict.
- Exported `ActionSettlement` and `ACTION_SETTLEMENT_ENCODING` from
  `hsr_engine.settlement`.

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
  --output /tmp/hsr_v118_action_settlement_structure_c0_to_c8_exact.json
```

Results:

- Model pack validation: ok.
- Phase 3 verification: PASS, all 10 examples pass.
- Phase 4 verification: PASS, all 10 examples pass.
- C0 to C8 exact route: `metadata.route_assertions.ok = True`.
- C0 to C8 route trace count: 8.
- C0 to C8 queued transition count: 2.
- C0 to C8 log event count: 172.
- Settlement encodings in route and queued transitions:
  `hsr.settlement.action.v1`.
- Existing settlement output keys present in all checked settlements.
- Replay ok: 10 / 10, including queued transitions.
- Checked settlement records: 148 / 148 valid.
- Target records: 10 / 10 valid.
- Mechanic records: 0 / 0 valid.
- Tribbie follow-up final damage total:
  `4393.00559968331`.
- Seele skill final damage total in C0 to C8:
  `115919.63539530325`.

Structural smoke check:

- `ActionSettlement` can be imported from `hsr_engine.settlement`.
- `ActionSettlement(damage_records=[DamageRecord(...)])` serializes typed
  records into the existing `damage_records` JSON key.

## Remaining Work

`ActionSettlement` now gives the engine a real settlement boundary, but most
subrecords are still produced directly by `SettlementCollector`. The next
structural step should split high-risk sub-settlements out of the collector,
starting with `DamageSettlement` and a normalized modifier ledger so damage can
be traced by source, bucket, condition, scope, and applied/not-applied reason.
