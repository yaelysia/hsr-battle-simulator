# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by #7.

## Authority rule

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value, or reference edge does not become a canonical simulator input merely because a script can find it.

Promotion requires human semantic review of representative raw data and the relevant reference chain. External game-data sites and theorycraft references are corroborating evidence only; they do not replace pinned TBGD evidence.

The formal source chain remains:

```text
turnbasedgamedata-main
-> compiler/lowering
-> Canonical IR / data-card IR
-> Combat Core
```

The existing v8 Combat Core is an important **independent reverse-engineered implementation and consumer map**, but it is not raw TBGD authority. A local formula/state machine may be inspected to avoid repeating generic-engine archaeology and to verify source alignment; it must not silently supply a missing raw producer, field, selector or source reference.

## Current navigation / sequencing overlay

The current post-R4 state and recommended research route are in [`POST_R4_RESEARCH_COMPACTION_2026-09-10.md`](POST_R4_RESEARCH_COMPACTION_2026-09-10.md).

That document is the current authority for **research sequencing and kernel-cross-check planning**. It preserves `BATTLE_RESEARCH_WORKLIST.md` as the historical living mechanism ledger and supersedes only stale `Next closure` / old R0-R4 sequencing wording.

Current bounded sequence already completed:

- R0 — Battle Execution Language Core v1;
- R1 — Ordinary Damage Vertical Slice v1;
- R2 — Weakness / Toughness / Break Vertical Slice v1;
- R3 — Healing + Modifier Lifecycle Core v1;
- R4 — Resource Economy Core v1.

The next recommended serial thread is **R5 — W01 + W18 — Battle-start Build Construction v1**. Do not resume W03/W04/W06/W05/W08 merely because their older worklist `Next closure` text predates these bounded records.

## Battle-semantic scope

The governing scope/completeness contract is [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md).

The living corpus triage is [`SOURCE_FAMILY_INVENTORY.md`](SOURCE_FAMILY_INVENTORY.md). It records included, mixed, excluded, deferred, unresolved and export/engine-boundary families.

The mechanism-level queue is [`BATTLE_RESEARCH_WORKLIST.md`](BATTLE_RESEARCH_WORKLIST.md). It is a **living ledger, not a fixed denominator**; W01..W18 must not be converted into a misleading completion percentage. Its historical checklist remains useful even when a later bounded record supersedes an older sequencing suggestion.

The reusable exact-pin cache is [`PINNED_SOURCE_INDEX.md`](PINNED_SOURCE_INDEX.md). It records expensive path/blob/ID lookups, false friends and explicit export/engine boundaries. It is navigation evidence, not semantic authority by itself.

[`PARALLEL_INTEGRATION_2026-09-09.md`](PARALLEL_INTEGRATION_2026-09-09.md) remains the historical reconciliation for the earlier parallel lanes. Post-R4 sequencing is now governed by `POST_R4_RESEARCH_COMPACTION_2026-09-10.md` plus the corrected detailed evidence records.

The work model is hybrid: automation aggressively enumerates/indexes candidates and references; semantic inclusion, exclusion, formula meaning and runtime behavior require manual raw-data review and producer/consumer tracing.

The target is not a representative sample. Archaeology must account for the battle-reachable TBGD corpus at the pinned revision and separate it from progression, UI, camera/animation/presentation and other non-battle data.

The inclusion test is runtime consequence: a fact is battle-relevant when changing it can alter battle initialization, legal actions/targets, timeline, resources, numerical/state outcomes, statuses/triggers, encounter transitions, mode rules or termination.

## Game-mechanics-informed archaeology

Before a mechanism is semantically closed, the researcher must understand enough of the corresponding **actual in-game combat mechanic** to know what the raw chain must explain: observable state changes, owners/targets, branches, timing, lifecycle and important edge cases.

Gameplay knowledge is a navigation/completeness oracle, not a replacement source. A fully connected reference graph is necessary but not sufficient; if pinned raw interpretation and known gameplay behavior conflict, preserve the discrepancy as unresolved/version drift instead of forcing either side to match.

See `BATTLE_SCOPE.md` and `EVIDENCE_RECORD_TEMPLATE.md` for the normative form of this rule.

## Kernel-first verification rule

Before launching a new search for a generic formula, scheduler rule, RNG rule, resource evaluator, status lifecycle, targeting primitive or spawn formula:

1. identify the exact source-facing residual;
2. inspect the corresponding current v8 L1 consumer / RuleBook / `EngineRuleRegistry` entry;
3. record whether a concrete local implementation exists, what source kind it declares, and which inputs/fail-closed boundaries it uses;
4. return to pinned TBGD to prove the producers and transport edges needed by that implementation;
5. compare the two sides and record alignment, mismatch or unresolved boundary;
6. reopen generic-engine archaeology only when the local implementation is missing/conflicting, a new authoritative source appears, or a convention itself blocks required correctness.

File existence alone is not runtime verification.

For planning, keep these states separate:

- **A — TBGD source-facing closed**;
- **B — TBGD export/engine gap**;
- **C — local v8 implementation present**;
- **D — local v8 source-aligned**;
- **E — local v8 validated/test-backed**.

A local `engine_convention` remains a convention until a formal admitted source replaces it. Only E supports a runtime-verified claim for the exact validated behavior.

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

These gap labels describe the **upstream pinned corpus**. They no longer imply that the local simulator necessarily lacks an implementation; consult the post-R4 A-E kernel-cross-check classification before planning a repeated generic-engine search.

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
11. unresolved questions and confidence;
12. when relevant, current local-kernel consumer/rule, its source kind, source-alignment result and validation level.

## Version discipline

The pinned upstream revision is the raw-data boundary. Current/default/live sources may be used for navigation/corroboration but must not silently fill pinned gaps. Large-file search/read failures are not omission proof.

Local simulator code must be inspected at the actual business-repository head used by the thread. An old local implementation/report is not evidence that the current head still behaves the same way.

## Current pinned TBGD revision

`14c1d18f91a8101d610e6c523447a7517de3fae1`

## Durable records / current navigation

Core governance and ledgers:

- `BATTLE_SCOPE.md`
- `SOURCE_FAMILY_INVENTORY.md`
- `BATTLE_RESEARCH_WORKLIST.md`
- `PINNED_SOURCE_INDEX.md`
- `EVIDENCE_RECORD_TEMPLATE.md`
- `PARALLEL_INTEGRATION_2026-09-09.md` — historical parallel reconciliation.
- `POST_R4_RESEARCH_COMPACTION_2026-09-10.md` — current sequencing and kernel-cross-check overlay.

Completed R0-R4 cross-cutting records:

- repository-level `docs/tbgd_evidence/shared/battle_execution_language_core_v1.md` — reusable P/E/D/O execution vocabulary across Avatar / Servant / Monster anchors.
- repository-level `docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md` — bounded source-facing damage slice and modifier/context operands.
- repository-level `docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md` — bounded weakness/toughness/break slice and named Stance injection export gap.
- repository-level `docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md` — independent HealHP chains plus reusable modifier lifecycle surfaces.
- repository-level `docs/tbgd_evidence/shared/resource_economy_core_v1.md` — raw-SP/raw-BP source topology, operation inputs and native resource boundaries.

Other representative/cross-cutting evidence:

- repository-level `docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md` — ordinary March Skill02 authority, dispellability, snapshot-routing inputs and Shield engine boundaries.
- repository-level `docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md` — servant construction, property-sync partition, self scheduling, coordinated-action ownership, death/death-rattle and forced cleanup.
- repository-level `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md` — representative monster/skill chain, ordinary HardLevel inputs, Stage/Elite/phase topology and final-stat engine boundary.
- repository-level `docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md` — OneMore/OneMorePerTurn, Gepard/Claymore cross-validation, speed mutation and scheduler boundary.
- repository-level `docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md` — RandomConfig/random-target/random-value/application-RNG distinctions and callback/death/revive priority examples.
- repository-level `docs/tbgd_evidence/shared/global_shared_reverse_scan.md` — completed W17 broad reverse scan, owner-backed shared producers, Assistant boundary and export gaps.

## Current archaeology state

R0-R4 have moved the ordinary execution middle from isolated examples toward reusable source-facing contracts. The central risk has shifted toward:

- battle-start character/build construction;
- encounter/spawn/phase/termination construction;
- legal action/target semantics;
- source alignment of timeline/death/revive/status/RNG residuals with the existing v8 kernel.

W17 broad reverse scan remains an event-driven sentinel. W02 SkillParam discovery, hidden W07 scheduler body, hidden W10 dispatcher, hidden W12 PRNG implementation, W13 passive/sync internals, W14 configured-spawn native operator and prior R2/R3/R4 native evaluator gaps must not be reopened by default without a concrete new source, consumer or local-kernel mismatch.

See `POST_R4_RESEARCH_COMPACTION_2026-09-10.md` for the R5-R10 route and per-thread execution contract.
