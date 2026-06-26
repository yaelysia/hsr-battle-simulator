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
python3 -m simulator_v8_clean_core.tools.validate_v0_272 --output-dir /tmp/hsr_v8_audit_v0_272
```

Constraint documents:

- `PROJECT_GOALS.md`: final product goals, fidelity targets, snapshot requirements, and milestone outcomes.
- `FORBIDDEN.md`: non-negotiable project red lines.

Current checkpoint:

```text
v0_272 global source genericity audit
```

Current shape:

- Runtime consumes Canonical IR and character-card IR, not TextMap or raw TBGD.
- Character text interpretation belongs to character card construction.
- Mutating paths must pass settlement traceability, replay, and source audit.
- `engine_convention` is allowed only when explicitly labeled and audited; it must not masquerade as a TBGD source.
- Blocked, audit-only, discovered-only, and placeholder sources may produce process records only, not state mutations.

Near-term missing large modules:

- Full character panel assembly, light cones, relics, and equipment composition.
- More character cards beyond the enhanced Seele example.
- Enemy AI, wave system, summons/assistants, and special battle modes.
