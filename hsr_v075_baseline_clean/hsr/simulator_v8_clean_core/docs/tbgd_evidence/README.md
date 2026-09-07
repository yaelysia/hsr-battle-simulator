# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by #7.

## Authority rule

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value, or reference edge does not become a canonical simulator input merely because a script can find it.

Promotion requires human semantic review of representative raw data and the relevant reference chain. External game-data sites and theorycraft references are corroborating evidence only; they do not replace pinned TBGD evidence.

## Evidence maturity

Every record must carry one of these states:

- `candidate`: mechanically discovered; semantic meaning not yet accepted.
- `manually_confirmed`: raw TBGD inspected and the claimed semantic role/reference edge is understood.
- `cross_validated`: manually confirmed and independently corroborated against live-game text, a trusted data site, theorycraft formula, or another independent source.
- `runtime_verified`: cross-validated and demonstrated against simulator/runtime behavior or a focused executable validator.

No `candidate` record may be consumed as canonical runtime authority.

## Source role classes

- `battle_authoritative`: directly defines battle behavior or a required execution relationship.
- `battle_supporting`: identifies/joins/describes battle data but does not by itself define the runtime rule.
- `mixed_requires_filter`: contains battle-relevant and non-battle fields together; field-level review is mandatory.
- `progression_only`: growth, level, promotion, EXP, reward, material, synthesis, or similar non-runtime progression data.
- `presentation_only`: UI, icon, camera, animation, localization, display, or other presentation data.
- `editor_tooling`: editor/test/tooling-only data.
- `telemetry_only`: logging/telemetry-only data.
- `unknown_unreviewed`: not yet semantically audited.

## Required record contents

Each evidence record should include:

1. gameplay concept and scope;
2. pinned TBGD revision;
3. exact source path and, when useful, blob SHA;
4. JSON pointer / field / opcode / occurrence identity;
5. upstream and downstream reference edges;
6. semantic interpretation and why it is accepted;
7. authority class and evidence maturity;
8. misleading siblings/fields and explicit negative knowledge;
9. external corroboration, including live/beta/version distinction;
10. unresolved questions and confidence.

## Version discipline

The repository submodule revision is the primary raw-data version boundary. Game-version context and external-site version context must be recorded separately. Beta/pre-release data must never be silently mixed with live canonical evidence.

## Current pinned TBGD revision

`14c1d18f91a8101d610e6c523447a7517de3fae1`

## Initial records

- `characters/march_7th_preservation_source_chain.md` — first manually audited character wiring sample. It intentionally stops before claiming unreviewed numeric combat semantics.
