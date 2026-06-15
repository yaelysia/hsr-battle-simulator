# simulator_v8_clean_core

v8 is the TBGD-first clean-core rewrite line for the HSR combat simulator.

Data flow:

```text
turnbasedgamedata-main -> TBGD compiler -> Canonical IR -> combat core
```

Rules for this baseline:

- Runtime code reads Canonical IR, not raw TurnBasedGameData files.
- v8 does not use the old model pack as a rule source.
- v8 does not use legacy simulator adapters or action context dictionaries.
- Every state change must be represented as a `Mutation`.
- Every action result must carry before/after snapshots through `BattleTransition`.

Initial validation:

```bash
python3 -m compileall -q simulator_v8_clean_core
python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

Constraint documents:

- `PROJECT_GOALS.md`: final product goals, fidelity targets, snapshot requirements, and milestone outcomes.
- `FORBIDDEN.md`: non-negotiable project red lines.
