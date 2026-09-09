# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by #7.

## Authority rule

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value, or reference edge does not become a canonical simulator input merely because a script can find it.

Promotion requires human semantic review of representative raw data and the relevant reference chain. External game-data sites and theorycraft references are corroborating evidence only; they do not replace pinned TBGD evidence.

## Battle-semantic scope

The governing scope/completeness contract is [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md).

The living corpus triage is [`SOURCE_FAMILY_INVENTORY.md`](SOURCE_FAMILY_INVENTORY.md). It records included, mixed, excluded, deferred, unresolved and export/engine-boundary families.

The mechanism-level queue is [`BATTLE_RESEARCH_WORKLIST.md`](BATTLE_RESEARCH_WORKLIST.md). It is a **living ledger, not a fixed denominator**; W01..W18 must not be converted into a misleading completion percentage.

The reusable exact-pin cache is [`PINNED_SOURCE_INDEX.md`](PINNED_SOURCE_INDEX.md). It records expensive path/blob/ID lookups, false friends and explicit export/engine boundaries. It is navigation evidence, not semantic authority by itself.

The latest parallel reconciliation supplement is [`PARALLEL_INTEGRATION_2026-09-09.md`](PARALLEL_INTEGRATION_2026-09-09.md). Until the next worklist/source-inventory compaction, this supplement plus the corrected detailed evidence files supersede stale summary wording where conflicts remain.

The work model is hybrid: automation aggressively enumerates/indexes candidates and references; semantic inclusion, exclusion, formula meaning and runtime behavior require manual raw-data review and producer/consumer tracing.

The target is not a representative sample. Archaeology must account for the battle-reachable TBGD corpus at the pinned revision and separate it from progression, UI, camera/animation/presentation and other non-battle data.

The inclusion test is runtime consequence: a fact is battle-relevant when changing it can alter battle initialization, legal actions/targets, timeline, resources, numerical/state outcomes, statuses/triggers, AI, encounter transitions, mode rules or termination.

## Game-mechanics-informed archaeology

Before a mechanism is semantically closed, the researcher must understand enough of the corresponding **actual in-game combat mechanic** to know what the raw chain must explain: observable state changes, owners/targets, branches, timing, lifecycle and important edge cases.

Gameplay knowledge is a navigation/completeness oracle, not a replacement source. A fully connected reference graph is necessary but not sufficient; if pinned raw interpretation and known gameplay behavior conflict, preserve the discrepancy as unresolved/version drift instead of forcing either side to match.

See `BATTLE_SCOPE.md` and `EVIDENCE_RECORD_TEMPLATE.md` for the normative form of this rule.

## Evidence maturity

Every record carries one of:

- `candidate`
- `manually_confirmed`
- `cross_validated`
- `runtime_verified`

No `candidate` record may be consumed as canonical runtime authority.

## Source role / gap classes

Core source roles:

- `battle_authoritative`
- `battle_supporting`
- `mixed_requires_filter`
- `progression_only`
- `presentation_only`
- `editor_tooling`
- `telemetry_only`
- `unknown_unreviewed`

A source may additionally be marked `export_gap` or `engine_consumer_unavailable` when a real ordinary data-facing edge exists but the pinned release-data dump does not expose the definition/consumer needed for deeper semantics.

## Required record contents

Each evidence record should include:

1. gameplay concept and scope;
2. pinned TBGD revision;
3. exact source path/blob where useful;
4. field/opcode/occurrence identity;
5. producer/reference/consumer edges;
6. semantic interpretation and acceptance reason;
7. authority class/evidence maturity;
8. battle consequence or exclusion reason;
9. negative knowledge/false friends;
10. corroboration/version context where useful;
11. unresolved questions and confidence.

## Version discipline

The pinned upstream revision is the raw-data boundary. Current/default/live sources may be used for navigation/corroboration but must not silently fill pinned gaps. Large-file search/read failures are not omission proof.

## Current pinned TBGD revision

`14c1d18f91a8101d610e6c523447a7517de3fae1`

## Durable records / current navigation

Core governance and ledgers:

- `BATTLE_SCOPE.md`
- `SOURCE_FAMILY_INVENTORY.md`
- `BATTLE_RESEARCH_WORKLIST.md`
- `PINNED_SOURCE_INDEX.md`
- `EVIDENCE_RECORD_TEMPLATE.md`
- `PARALLEL_INTEGRATION_2026-09-09.md` — latest reconciliation and continuation overlay.

Representative/cross-cutting evidence:

- repository-level `docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md` — ordinary March Skill02 authority, dispellability, snapshot-routing inputs and Shield engine boundaries.
- repository-level `docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md` — servant construction, property-sync partition, self scheduling, coordinated-action ownership, death/death-rattle and forced cleanup.
- repository-level `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md` — representative monster/skill chain, ordinary HardLevel inputs, Stage/Elite/phase topology and final-stat engine boundary.
- repository-level `docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md` — OneMore/OneMorePerTurn, Gepard/Claymore cross-validation, speed mutation and scheduler boundary.
- repository-level `docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md` — RandomConfig/random-target/random-value/application-RNG distinctions and callback/death/revive priority examples.
- repository-level `docs/tbgd_evidence/shared/global_shared_reverse_scan.md` — completed W17 broad reverse scan, owner-backed shared producers, Assistant boundary and export gaps.

## Parallel archaeology state

The first five-lane research round produced durable corrections and then reached diminishing returns on several engine-hidden domains.

Current continuation rule:

- W17 broad reverse scan is complete for this pin and becomes an event-driven sentinel;
- W02/March-local W05, W07 scheduler internals, W12 generic RNG, W13 sync/passive timing, and W14 final-stat arithmetic must not be repeatedly reopened without a genuinely new authoritative source;
- next parallel research should shift toward source-facing W04 damage, W06 break, W05/W09 healing+modifier lifecycle, W03 execution/opcode language, and W16 encounter/termination work as specified in the latest integration supplement.
