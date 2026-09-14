# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by Issue #7 / PR #8.

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

The retained R6 execution contract and frozen boundaries are in [`POST_R5_RESEARCH_COMPACTION_2026-09-11.md`](POST_R5_RESEARCH_COMPACTION_2026-09-11.md). The **2026-09-14 R6 post-repair reconciliation** in the [R6 record](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md) is the current R6 status overlay.

The post-R5 document retains the original **R6 sequencing and kernel-cross-check plan**; its wording that R6 is next is superseded by the completed bounded R6 checkpoint below. [`POST_R4_RESEARCH_COMPACTION_2026-09-10.md`](POST_R4_RESEARCH_COMPACTION_2026-09-10.md) remains historical planning context. Neither document authorizes automatically starting R7; return to integration/planning for that decision.

Current bounded sequence completed:

- R0 — Battle Execution Language Core v1;
- R1 — Ordinary Damage Vertical Slice v1;
- R2 — Weakness / Toughness / Break Vertical Slice v1;
- R3 — Healing + Modifier Lifecycle Core v1;
- R4 — Resource Economy Core v1;
- R5 — Battle-start Build Construction v1;
- R6 — Encounter / Spawn / Phase / Termination v1, closed after merged R6A proof repair and narrow evidence reconciliation.

`complete` here means the bounded evidence record met its own exit condition. It does **not** mean the corresponding W-package is globally `mechanism_closed`, and it does not imply runtime verification.

**R6 — W16 + source-facing W14 residuals — is now `bounded_complete`.** The [record](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md) preserves the original partial checkpoint and the full `R6-G01: reproduced -> repaired -> validated -> merged` lifecycle. Independent repair [PR #15](https://github.com/yaelysia/hsr-battle-simulator/pull/15) was accepted and squash-merged as `f8e8a053ef591e1aeeb99956d46acd8390676c6f`.

Accepted [run 34570966064](https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34570966064) / [artifact 10187755334](https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34570966064/artifacts/10187755334) executed on **`70eabfe4a94ec458eacdd4bf324d9a8889743c49`**, not on the merge SHA: 12 passed / exit=0. E applies only to Stage103201 materialization, duplicate-slot identity, `_wave_unit_spec`, Stage202212020 subsequent-wave spawn/mutations/replay from an explicit cleared-wave + inert-ally fixture boundary, eight source/request rejection cases, and the consumer-aligned shape Catalog (59,940 templates; 899,100 formal identities; missing formal evidence=0). It does not prove complete attacks/kills, victory/defeat battles, StageAbility execution or hidden native formulas.

Exact merged producer/test blobs match the validated head; the base-to-merge changes did not rewrite wave/spawn consumers. Thus accepted runtime evidence remains applicable to the merged R6A behavior. This docs-only reconciliation ran no new simulator/Direct/Catalog and did not rebase the research branch. **Bounded complete is not global W14/W16 mechanism closure or all encounter-engine internals recovered. R6 bounded sequence closed. Do not automatically start R7.** Do not resume stale worklist `Next closure` wording as a serial task assignment.

## Battle-semantic scope

The governing scope/completeness contract is [`BATTLE_SCOPE.md`](BATTLE_SCOPE.md).

The living corpus triage is [`SOURCE_FAMILY_INVENTORY.md`](SOURCE_FAMILY_INVENTORY.md). It records included, mixed, excluded, deferred, unresolved and export/engine-boundary families.

The mechanism-level queue is [`BATTLE_RESEARCH_WORKLIST.md`](BATTLE_RESEARCH_WORKLIST.md). It remains the historical living mechanism ledger, not a fixed denominator and not the current serial scheduler. Later bounded records and compaction overlays may supersede stale per-package `Next closure` wording without declaring the whole package closed.

The reusable exact-pin cache is [`PINNED_SOURCE_INDEX.md`](PINNED_SOURCE_INDEX.md). It records expensive path/blob/ID lookups, false friends and explicit export/engine boundaries. It is navigation evidence, not semantic authority by itself.

[`PARALLEL_INTEGRATION_2026-09-09.md`](PARALLEL_INTEGRATION_2026-09-09.md) remains the reconciliation for the earlier parallel lanes.

The work model is hybrid: automation aggressively enumerates/indexes candidates and references; semantic inclusion, exclusion, formula meaning and runtime behavior require manual raw-data review and producer/consumer tracing.

The target is not a representative sample. Archaeology must account for the battle-reachable TBGD corpus at the pinned revision and separate it from progression, UI, camera/animation/presentation and other non-battle data within the current-phase scope.

## Game-mechanics-informed archaeology

Before a mechanism is semantically closed, the researcher must understand enough of the corresponding in-game combat mechanic to know what the raw chain must explain: observable state changes, owners/targets, branches, timing, lifecycle and important edge cases.

Gameplay knowledge is a navigation/completeness oracle, not a replacement source. If pinned raw interpretation and known gameplay behavior conflict, preserve the discrepancy as unresolved/version drift instead of forcing either side to match.

See `BATTLE_SCOPE.md` and `EVIDENCE_RECORD_TEMPLATE.md` for the normative form of this rule.

## Kernel-first verification rule

Before launching a new search for a generic formula, scheduler rule, RNG rule, resource evaluator, status lifecycle, targeting primitive, spawn formula or encounter transition:

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

Core source roles remain:

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

Each durable evidence record should include, where relevant:

1. gameplay concept and scope;
2. pinned TBGD revision;
3. exact source path/blob and occurrence identity;
4. producer/reference/consumer edges;
5. semantic interpretation and battle consequence;
6. authority class/evidence maturity;
7. negative knowledge/false friends;
8. corroboration/version context;
9. unresolved questions and confidence;
10. current local-kernel consumer/rule, source kind, alignment result and validation level.

## Version discipline

The pinned upstream revision is the raw-data boundary. Current/default/live sources may be used for navigation/corroboration but must not silently fill pinned gaps. Large-file search/read failures are not omission proof.

Local simulator code must be inspected at the actual business-repository head used by the thread. An old implementation/report is not evidence that the current head still behaves the same way.

## Current pinned TBGD revision

`14c1d18f91a8101d610e6c523447a7517de3fae1`

## Durable records / current navigation

Core governance and ledgers:

- `BATTLE_SCOPE.md`
- `SOURCE_FAMILY_INVENTORY.md`
- `BATTLE_RESEARCH_WORKLIST.md`
- `PINNED_SOURCE_INDEX.md`
- `EVIDENCE_RECORD_TEMPLATE.md`
- `PARALLEL_INTEGRATION_2026-09-09.md` — historical parallel reconciliation;
- `POST_R4_RESEARCH_COMPACTION_2026-09-10.md` — historical R0-R4 compaction;
- `POST_R5_RESEARCH_COMPACTION_2026-09-11.md` — retained R6 execution contract; current R6 completion status is overlaid above and in the R6 record.

Completed bounded cross-cutting records:

- repository-level `docs/tbgd_evidence/shared/battle_execution_language_core_v1.md` — R0 reusable P/E/D/O execution vocabulary;
- repository-level `docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md` — R1 ordinary damage source-facing slice;
- repository-level `docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md` — R2 weakness/toughness/break slice;
- repository-level `docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md` — R3 HealHP plus modifier lifecycle surfaces;
- repository-level `docs/tbgd_evidence/shared/resource_economy_core_v1.md` — R4 resource-economy topology;
- repository-level `docs/tbgd_evidence/shared/battle_start_build_construction_v1.md` — R5 selected ordinary build -> battle-start construction slice;
- repository-level `docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md` — R6 bounded closure after R6A merge; claim-level E evidence and explicit non-E residuals, with the original blocker history retained.

Other representative/cross-cutting evidence:

- repository-level `docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md`;
- repository-level `docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md`;
- repository-level `docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md`;
- repository-level `docs/tbgd_evidence/stages/stage_config_wave_source.md` — corrected ordinary `HardLevelGroup` / conditional `MonsterUnique` boundary and R6 stage entry evidence;
- repository-level `docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md`;
- repository-level `docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md`;
- repository-level `docs/tbgd_evidence/shared/global_shared_reverse_scan.md`.

## Current archaeology state

R0-R5 have moved the ordinary execution path from isolated examples toward reusable source-facing contracts from selected battle-start inputs through the core execution middle. R5 additionally establishes a concrete selected Avatar/Light Cone/relic/trace/Technique construction slice, but its formal admission and callback execution remain a separate validation residual rather than a reason to restart source discovery.

The post-R5 **encounter construction and control** topics below are traced in the bounded R6 record. Its sole newly identified birth blocker R6-G01 is repaired, validated and merged; the post-repair status no longer asks for that repair or another broad source search:

- StageConfig -> ordered waves/slots -> wave definitions;
- Level / ordinary `HardLevelGroup` / Elite context -> enemy birth inputs;
- source-bearing birth templates -> `UnitSpawnRequest` -> enemy `UnitState`;
- StageAbility pre/post-spawn ownership;
- same-entity phase transition versus spawn/reinforcement;
- wave clearing, next-wave transition and battle termination.

W17 broad reverse scan remains an event-driven sentinel. W02 hidden producer searches, hidden W07 scheduler body, hidden W10 universal dispatcher, hidden W12 PRNG implementation, W13 passive/sync internals, W14 native configured-spawn arithmetic, and prior R2/R3/R4 native evaluator gaps must not be reopened by default without a concrete new source, consumer or local-kernel mismatch.

The R6 record's sections 11–13 retain the limits: StageAbility/native dispatcher, complete victory/defeat, generic monster arithmetic, flat/clamp/rounding, HardLevel/Elite precedence, malformed-input validation and full reinforcement/AI admission are not promoted by the R6A Direct. No new TBGD family/index fact changed, so this checkpoint does not relabel source inventory entries or mark the historical W14/W16 worklist globally closed.

See `POST_R5_RESEARCH_COMPACTION_2026-09-11.md` for the retained R6 exit contract; return to integration/planning for the R7 decision, without starting R7 here.
