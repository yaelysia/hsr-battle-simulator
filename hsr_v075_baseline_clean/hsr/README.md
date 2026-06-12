# HSR Combat Workspace v0.9

Unified workspace for building a general Honkai: Star Rail combat simulator.

Current components:

- `simulator_v7_7/`: route validator / combat kernel prototype plus compiler-boundary tooling.
- `spec_v0_8/`: combat-kernel and content-IR specifications.
- `model_pack_v3_0/`: structured hand-authored model pack baseline.
- `generated_content_ir_v0_6/`: template-level Content IR from TurnBasedGameData.
- `targeted_action_ir_v0_8/`: candidate ActionIR compiled from TurnBasedGameData for the current target team.
- `bound_action_ir_v0_8/`: ActionIR with high-confidence dynamic expressions bound to skill parameters.

Validation summary is in `validation_v7_7.log`.

## v0.9 additions

- `targeted_action_ir_v0_9/`: regenerated target-team ActionIR from the provided full TurnBasedGameData package.
- `bound_action_ir_v0_9/`: regenerated bound ActionIR.
- `status_ir_v0_2/`: StatusIR candidates compiled from status_definition_hints, enriched with raw callback metadata.

See `spec_v0_8/STATUS_IR_COMPILER_v0_9.md` and `spec_v0_8/SELF_ITERATION_LOG_v0_9.md`.
