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

**2026-09-14 R9 — W13 selected owned-servant creation — is `partial / NEEDS_REPLAN`.** The [Owned Servant Creation / Ownership / Runtime Admission v1 record](../../../../../docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md) pins the exact ordinary Aglaea `CreateServant(11402)` occurrence and checks the production gate against actual business master `f8e8a053ef591e1aeeb99956d46acd8390676c6f`. **R9-G01:** source-bearing generic task lowering, servant definitions and `SummonSystem.plan_spawn_servant` exist, but the formal Ability/default effect route does not connect the selected CreateServant to executable servant spawn. Definition presence and direct consumer tests are not that caller edge.

The existing formal-owner spawn-source non-null/membership guards remain required; `definition.source` is not an allowed substitute for the actual create occurrence. Downstream selected build/stat/birth/registry/action closure is not claimed through the missing edge. **E is not established; no new runtime/test/Direct run or runtime change is claimed.** Only the selected W13 leaf is updated; its parent remains active and native sync/passive/scheduler/death-order boundaries stay frozen. **Stop at R9; return to integration/planning for repair/R10 decision, without automatically entering R10.** This separately authorized partial checkpoint supersedes the R8 sequencing stop, not R8's historical evidence.

**2026-09-14 R8 — W18 + startup-facing W09/W01 residual — is `bounded_complete` at the source/static-kernel boundary.** The [Battle-Start Effect Activation / Startup Admission v1 record](../../../../../docs/tbgd_evidence/shared/battle_start_effect_activation_v1.md) separates B0 static construction, B1 provider registration, B2 immediate startup ability and B3 battle-entry callbacks against actual business master `f8e8a053ef591e1aeeb99956d46acd8390676c6f`. It maps LC20000 rank/source/graph transport, Set102 static speed versus hit-context bonus, and Set301 main/conditional-child property paths. Registration is not execution and a true speed comparison is not an executed conditional effect.

Technique possession remains external pre-battle state. The current canonical-effect-referenced initial-status interface is not an automatic MazeBuff-to-CharacterSkill/SkillMaze adapter; no inspected contract promises that a finished character build acquires or imports MazeBuff100201. R8 records that boundary without inventing a build bug. No concrete new producer/consumer mismatch was identified in the inspected contracts. **E is not established: no R8 simulator/Direct/test run is claimed.** W01/W09/W18 remain `active`; their broad historical checklist leaves are not promoted by selected anchors. Native dispatcher/timer/property-watcher and static-arithmetic gaps remain. **Stop at R8; return to integration/planning for the R9 decision.** This separately authorized checkpoint supersedes the R7 sequencing stop, not its historical evidence.

**2026-09-14 R7 — W11 + source-facing W15 — is `bounded_complete`.** The [Action Targeting / Enemy Decision Boundary v1 record](../../../../../docs/tbgd_evidence/shared/action_targeting_enemy_decision_boundary_v1.md) separates T1 explicit selection, T2 automatic action targets, T3 impact expansion and T4 internal traversal. It closes the selected Asta/Aglaea target boundary, Monster1002011 fixed candidate plus automatic AllEnemy, and actual Monster1002041 complex-AI non-admission against business master `f8e8a053ef591e1aeeb99956d46acd8390676c6f` and the existing TBGD pin. The positive raw `AISkillSequence` is an object array, not an integer array. Complex AI remains blocked/external; generic native AI is not recovered.

R7 is a docs-only source/static consumer checkpoint: A/C/D apply only to the individual claims in its matrix; no new runtime/test E is claimed. Conditional target-shape alignment is not proof that the entire servant action is executable. W11/W15 remain `active`; scorer/weights/random/aggro/formation/scheduler gaps stay explicit. Its historical stop-before-R8 is superseded by the separately authorized R8 checkpoint above. The R7 checkpoint supersedes older wording that R7 has not started, without changing the historical R6 proof below.

The retained R6 execution contract and frozen boundaries are in [`POST_R5_RESEARCH_COMPACTION_2026-09-11.md`](POST_R5_RESEARCH_COMPACTION_2026-09-11.md). The **2026-09-14 R6 post-repair reconciliation** in the [R6 record](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md) is the current R6 status overlay.

The post-R5 document retains the original **R6 sequencing and kernel-cross-check plan**; its wording that R6 is next is superseded by the completed bounded R6 checkpoint below. [`POST_R4_RESEARCH_COMPACTION_2026-09-10.md`](POST_R4_RESEARCH_COMPACTION_2026-09-10.md) remains historical planning context. Those documents did not authorize automatically starting R7; the separately authorized R7 result is recorded above.

Current bounded sequence completed:

- R0 — Battle Execution Language Core v1;
- R1 — Ordinary Damage Vertical Slice v1;
- R2 — Weakness / Toughness / Break Vertical Slice v1;
- R3 — Healing + Modifier Lifecycle Core v1;
- R4 — Resource Economy Core v1;
- R5 — Battle-start Build Construction v1;
- R6 — Encounter / Spawn / Phase / Termination v1, closed after merged R6A proof repair and narrow evidence reconciliation;
- R7 — Action Targeting / Enemy Decision Boundary v1, selected source-facing and static consumer closure, without a new runtime E claim;
- R8 — Battle-Start Effect Activation / Startup Admission v1, selected static/provider/startup/entry boundaries and external Technique ownership, without a runtime E claim.

R9 has a durable **partial** record above and is deliberately not included in this completed list.

`complete` here means the bounded evidence record met its own exit condition. It does **not** mean the corresponding W-package is globally `mechanism_closed`, and it does not imply runtime verification.

**R6 — W16 + source-facing W14 residuals — is now `bounded_complete`.** The [record](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md) preserves the original partial checkpoint and the full `R6-G01: reproduced -> repaired -> validated -> merged` lifecycle. Independent repair [PR #15](https://github.com/yaelysia/hsr-battle-simulator/pull/15) was accepted and squash-merged as `f8e8a053ef591e1aeeb99956d46acd8390676c6f`.

Accepted [run 34570966064](https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34570966064) / [artifact 10187755334](https://github.com/yaelysia/hsr-battle-simulator/actions/runs/34570966064/artifacts/10187755334) executed on **`70eabfe4a94ec458eacdd4bf324d9a8889743c49`**, not on the merge SHA: 12 passed / exit=0. E applies only to Stage103201 materialization, duplicate-slot identity, `_wave_unit_spec`, Stage202212020 subsequent-wave spawn/mutations/replay from an explicit cleared-wave + inert-ally fixture boundary, eight source/request rejection cases, and the consumer-aligned shape Catalog (59,940 templates; 899,100 formal identities; missing formal evidence=0). It does not prove complete attacks/kills, victory/defeat battles, StageAbility execution or hidden native formulas.

Exact merged producer/test blobs match the validated head; the base-to-merge changes did not rewrite wave/spawn consumers. Thus accepted runtime evidence remains applicable to the merged R6A behavior. This docs-only reconciliation ran no new simulator/Direct/Catalog and did not rebase the research branch. **Bounded complete is not global W14/W16 mechanism closure or all encounter-engine internals recovered. R6 bounded sequence closed.** Its historical stop-before-R7 instruction has been superseded only by the separately authorized R7 checkpoint above. Do not resume stale worklist `Next closure` wording as a serial task assignment.

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

Partial / replanning records:

- repository-level `docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md` — R9 exact CreateServant producer and static consumer gates; G01 formal caller gap; downstream selected closure and E not established.

Completed bounded cross-cutting records:

- repository-level `docs/tbgd_evidence/shared/battle_execution_language_core_v1.md` — R0 reusable P/E/D/O execution vocabulary;
- repository-level `docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md` — R1 ordinary damage source-facing slice;
- repository-level `docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md` — R2 weakness/toughness/break slice;
- repository-level `docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md` — R3 HealHP plus modifier lifecycle surfaces;
- repository-level `docs/tbgd_evidence/shared/resource_economy_core_v1.md` — R4 resource-economy topology;
- repository-level `docs/tbgd_evidence/shared/battle_start_build_construction_v1.md` — R5 selected ordinary build -> battle-start construction slice;
- repository-level `docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md` — R6 bounded closure after R6A merge; claim-level E evidence and explicit non-E residuals, with the original blocker history retained;
- repository-level `docs/tbgd_evidence/shared/action_targeting_enemy_decision_boundary_v1.md` — R7 T1/T2/T3/T4, fixed enemy candidate versus automatic target contract, actual complex-AI negative anchor, and external-controller handoff; no new runtime E;
- repository-level `docs/tbgd_evidence/shared/battle_start_effect_activation_v1.md` — R8 B0/B1/B2/B3, source-bearing provider/startup contracts, selected LC/set consequences, external Technique transport and actual setup order; E not established.

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

The R6 record's sections 11–13 retain the limits: StageAbility/native dispatcher, complete victory/defeat, generic monster arithmetic, flat/clamp/rounding, HardLevel/Elite precedence, malformed-input validation and full reinforcement/AI admission are not promoted by the R6A Direct. No new TBGD family/index fact changed in that R6 checkpoint, so it does not relabel source inventory entries or mark the historical W14/W16 worklist globally closed.

R7 adds a selected target/decision boundary, not a source-family census or full-battle proof. Its exact-pin lookup table retains the new Monster1002041 reverse join and the raw sequence-shape correction. Source-family interpretation is unchanged, so the family inventory is not relabeled. W11/W15 bounded leaves and residuals are recorded in the worklist; the wider package obligations remain open.

R8 maps the selected R5 activation residual without reopening build-source discovery. A/C/D are bounded source/static consumer claims, not proof that the selected bundle, conditional submodifier or Technique ran. The worklist, pinned index and source-family inventory are unchanged: this selected closure does not satisfy their broad remaining obligations or introduce a new raw family/lookup.

R9 stops at a concrete local production transport gap, rather than extending source archaeology to compensate for it. The selected W13 creation leaf remains unchecked with R9-G01; downstream G02–G06 are not globally adjudicated. The pinned index and family inventory are unchanged because this checkpoint reuses established source identities.

See `POST_R5_RESEARCH_COMPACTION_2026-09-11.md` for the retained R6 exit contract and the R9 record for the current partial result. Stop at R9 and return to integration/planning; do not automatically enter R10.
