# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by #7.

## Authority rule

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value, or reference edge does not become a canonical simulator input merely because a script can find it.

Promotion requires human semantic review of representative raw data and the relevant reference chain. External game-data sites and theorycraft references are corroborating evidence only; they do not replace pinned TBGD evidence.

## Battle-semantic scope

The governing scope/completeness contract is [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md).

The living corpus triage is [`SOURCE_FAMILY_INVENTORY.md`](SOURCE_FAMILY_INVENTORY.md). It records which source families are currently included, mixed, excluded, deferred, unresolved or blocked by export/engine boundaries.

The mechanism-level research queue and checklist is [`BATTLE_RESEARCH_WORKLIST.md`](BATTLE_RESEARCH_WORKLIST.md). It is a **living ledger, not a fixed requirements list**: new mechanisms must be added when discovered; packages may be split, merged, deferred, retired with negative evidence, or reopened; checked leaves may be unchecked when later evidence invalidates them. Its current `W01..W18` decomposition is therefore not a stable denominator and must not be used to publish a misleading completion percentage.

The reusable exact-pin navigation cache is [`PINNED_SOURCE_INDEX.md`](PINNED_SOURCE_INDEX.md). It records expensive path/blob/ID lookups, false friends and explicit export/engine boundaries so later threads do not repeatedly rescan the same large sources. It is navigation evidence, not semantic authority by itself.

The worklist preserves the intended division of labor: automation should aggressively enumerate/index candidates and references so discovery is broad, while semantic inclusion, exclusion, formula meaning and runtime behavior still require manual raw-data review and producer/consumer tracing.

The target is not a representative sample. Archaeology must account for the battle-reachable TBGD corpus at the pinned revision and separate it from progression, UI, camera/animation/presentation and other non-battle data.

The operational inclusion test is runtime consequence: a fact is battle-relevant when changing it can alter battle initialization, legal actions/targets, timeline, resources, numerical/state outcomes, statuses/triggers, AI, encounter transitions, mode rules or termination. Mixed files must be filtered below filename level, and reviewed exclusions must be retained as negative knowledge.

## Game-mechanics-informed archaeology

Before a mechanism is semantically closed, the researcher must understand enough of the corresponding **actual in-game combat mechanic** to know what the raw chain has to explain: observable state changes, owners/targets, branches, timing, lifecycle and important edge cases.

Gameplay knowledge is a navigation/completeness oracle, not a replacement source. A fully connected reference graph is necessary but not sufficient; if pinned raw interpretation and known gameplay behavior conflict, preserve the discrepancy as unresolved/version drift instead of forcing either side to match.

See `BATTLE_SCOPE.md` and `EVIDENCE_RECORD_TEMPLATE.md` for the normative form of this rule.

## Evidence maturity

Every record must carry one of these states:

- `candidate`: mechanically discovered; semantic meaning not yet accepted.
- `manually_confirmed`: raw TBGD inspected and the claimed semantic role/reference edge is understood.
- `cross_validated`: manually confirmed and independently corroborated against another source/sample.
- `runtime_verified`: cross-validated and demonstrated against simulator/runtime behavior or a focused executable validator.

No `candidate` record may be consumed as canonical runtime authority.

## Source role classes

- `battle_authoritative`: directly defines battle behavior or a required execution relationship.
- `battle_supporting`: identifies/joins/describes battle data but does not by itself define the runtime rule.
- `mixed_requires_filter`: contains battle-relevant and non-battle fields together; field-level review is mandatory.
- `progression_only`: growth/EXP/reward/material/economy data with no battle consequence.
- `presentation_only`: UI/icon/camera/animation/localization/display data with no logical battle consequence.
- `editor_tooling`: editor/test/tooling-only data.
- `telemetry_only`: logging/telemetry-only data.
- `unknown_unreviewed`: not yet semantically audited.

A source can additionally be marked `export_gap` or `engine_consumer_unavailable` in the living inventory/index when an ordinary data-facing edge is real but the pinned release-data dump does not expose the executable definition/consumer required for deeper semantics.

## Required record contents

Each evidence record should include:

1. gameplay concept and scope;
2. pinned TBGD revision;
3. exact source path and, when useful, blob SHA;
4. JSON pointer / field / opcode / occurrence identity;
5. upstream and downstream reference edges;
6. semantic interpretation and why it is accepted;
7. authority class and evidence maturity;
8. battle-scope verdict and concrete runtime consequence/exclusion reason;
9. misleading siblings/fields and explicit negative knowledge;
10. external corroboration/version context where useful;
11. unresolved questions and confidence.

## Version discipline

The pinned upstream revision is the primary raw-data version boundary. Current/default/live sources may be used for navigation/corroboration but must not silently fill pinned gaps. Large-file search/read failures are also not omission proof; important negatives require a reliable exact-pin read method.

## Current pinned TBGD revision

`14c1d18f91a8101d610e6c523447a7517de3fae1`

## Durable records / current navigation

Core governance and ledgers:

- `BATTLE_SCOPE.md` — battle-semantic boundary and corpus-completeness contract.
- `SOURCE_FAMILY_INVENTORY.md` — living normal-combat source-family coverage and unresolved/export-gap ledger.
- `BATTLE_RESEARCH_WORKLIST.md` — living mechanism-level work packages, mutable checklist and closure queue.
- `PINNED_SOURCE_INDEX.md` — exact-pin path/blob/navigation cache and semantic-hazard registry.
- `EVIDENCE_RECORD_TEMPLATE.md` — required evidence-record structure including gameplay semantic model.

Representative/cross-cutting evidence:

- repository-level `docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md` — ordinary March Skill02 producer/binding/consumer chain, lifetime/replacement hooks and generic Shield engine boundaries.
- repository-level `docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md` — servant `#N` construction, scheduling/death-rattle numerics, lifecycle distinctions and corrected creation-delay ownership.
- repository-level `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md` — representative monster/skill chain plus corrected ordinary `HardLevelGroup` scaling inputs.
- repository-level `docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md` — RandomConfig/random-target/random-value/application-RNG distinctions plus callback/death/revive priority examples.
- repository-level `docs/tbgd_evidence/shared/global_shared_reverse_scan.md` — W17 ordinary global/shared producer reverse scan, owner-backed includes, false friends and export boundaries.

## First parallel-integration checkpoint

The first five read-only research lanes produced several durable corrections now reflected in the files above:

- W02: ordinary March `SkillID=100102` producer exists in exact pinned `AvatarSkillConfig`; the earlier omission claim was a large-file/search false negative.
- W14: ordinary five-stat level scaling uses `HardLevelGroup.json`; `ILHardLevelGroup` is a wrong-family false friend for the inspected ordinary chain.
- W13: servant `#N` construction mapping and BattleCry/DeathRattle numerics are closed; Aglaea Skill02's explicit `SetActionDelay(0)` targets Aglaea (`Caster`), not the servant.
- W12/W10: representative RNG/callback chains are closed, while RNG algorithms/streams and full dispatcher semantics are explicitly separated as engine-authority gaps.
- W17: broad reverse scan found ordinary shared/global producers and no W19+ mechanism; remaining work is narrowed to specific owner/export gaps.

All mechanism packages remain governed by their exact worklist leaves; these corrections do not imply that the parent W01..W18 packages are globally complete.
