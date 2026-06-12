# HSR Simulator v0.75 baseline clean package

This package is intentionally pruned for IDE/Codex migration.

Included:
- latest simulator entry and engine modules
- latest model pack v3.0, excluding legacy_sources
- latest C0→C8 baseline validation output
- latest handoff and audit reports

Excluded:
- historical workspace summaries
- old generated output_v*/validation_v* folders
- old prototype simulator versions
- model_pack_v3_0/legacy_sources
- __pycache__ and temporary files

Baseline command:

```bash
python3 -m compileall -q simulator_v7_7
python3 simulator_v7_7/hsr_simulator_prototype_v7_7.py \
  --model-pack model_pack_v3_0 \
  --case-id arbitration_4_3_knight_3_live_c0_to_c8_simulator_only \
  --route-mode exact \
  --output validation_outputs_v0_75/c0_to_c8_full_audit_v0_75_rerun.json
```

Expected baseline:
- route_assertions.ok = true
- route steps = 8
- key known mismatch still open: Seele skill simulated total ~115919.635 vs observed 109262
