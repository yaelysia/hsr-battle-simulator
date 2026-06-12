# AGENTS.md - HSR Combat Simulator Workspace Instructions

## Project purpose

Build a rigorous Honkai: Star Rail combat simulator and route solver. Current code is a compiled-case route executor with a v0.75 audit layer. Refactor toward a general simulator while preserving existing live-route validation.

## Baseline commands

```bash
cd /mnt/data/hsr_fixed_workspace/current
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py --model-pack model_pack_v3_0 --validate-model-pack
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output validation_outputs_v0_75/c0_to_c8_full_audit_v0_75.json
```

Expected C0→C8 baseline: `route_assertions.ok = true`, 8 route steps, 172 log events.

## Do not break these current numeric baselines unless intentionally changing a verified rule

- Tribbie follow-up total: about `4393.005600`.
- Seele skill total: about `115919.635395`.

The Seele value is known to be higher than the observed `109262`; do not hand-patch it. Use ledgers to locate the real buff/debuff/window issue.

## Key documents

Read first:

1. `CODEX_HANDOFF.md`
2. `simulator_v7_7/ENGINE_ARCHITECTURE_v7_0.md`
3. `live_validation_reports/foundation_audit_layer_v0_75.md`
4. `live_validation_reports/simulator_workflow_audit_v0_74.md`
5. `model_pack_v3_0/MANIFEST.yaml`

## Engineering rules

- Observed combat damage is validation data only, never simulation input.
- Prefer generic engine/model-pack fixes over route-specific hacks.
- Do not import raw TurnBasedGameData opcode/hash schema directly into the engine. Normalize through model pack / IR boundaries.
- Keep compiled-case exact-route replay working while refactoring.
- Add or update a report under `live_validation_reports/` for meaningful changes.
- Put validation outputs under a versioned `validation_outputs_v*/` directory.

## Current refactor priority

1. Introduce explicit `ActionSettlement`, `DamageSettlement`, `ModifierLedger`, `StatusChange`, `ResourceChange`, `AVChange`, `TargetResolution`, and `RNGEvent` data objects.
2. Make action settlement generated directly by the engine rather than reconstructed from raw logs.
3. Normalize modifier terms by source, bucket, condition, scope, and applied/not-applied reason.
4. Preserve current CLI behavior and baseline validation.
