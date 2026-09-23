# TBGD Battle Evidence Ledger

This directory is the durable evidence store for the manually audited TurnBasedGameData (TBGD) battle-source archaeology tracked by [Issue #7](https://github.com/yaelysia/hsr-battle-simulator/issues/7) / [PR #8](https://github.com/yaelysia/hsr-battle-simulator/pull/8).

## Core purpose

**Determine which facts in the pinned game database affect in-scope combat, what those facts mean, and how their source/reference chains fit together, so backend work can reuse and implement them.**

The deliverable is a version-pinned, manually audited battle-source catalog, relationship graph and evidence ledger. It is not a backend implementation, runtime-admission acceptance or repair-coordination project. Backend usefulness is the purpose of the research output; backend implementation readiness is not its completion criterion.

Pinned TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`.

The governing source scope and completeness obligations remain [BATTLE_SCOPE.md](BATTLE_SCOPE.md). Representative slices are milestones, not a substitute for accounting for the in-scope battle-reachable corpus. Deferred modes remain deferred, not non-battle.

## Current scope correction — 2026-09-23

The [PR #8 scope-drift audit](../../../../../docs/tbgd_evidence/shared/pr8_scope_drift_audit_2026-09-23.md) restores the original research charter after the owner explicitly rejected the backend workflow that had entered R9.

This correction supersedes the **research-status and sequencing authority** of earlier kernel-first/admission/repair instructions, including the post-R4/post-R5 compactions, R6 repair-dependent stops, R7/R8 mismatch-stop rules, R9 admission plan/checkpoint, and R9A dependency/restart comments. It does not invalidate their correctly scoped raw evidence or rewrite historical execution results.

- `NEEDS_REPLAN`, implementation repair acceptance, upstream implementation-PR waits and repair-before-next-research rules are not current PR #8 research states or gates. Historical quotations may remain for auditability; they are not instructions.
- R9's ordinary servant source facts are retained in the [corrected R9 entry](../../../../../docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md). Its runtime-admission task is withdrawn from the archaeology completion path, not relabeled as successfully executed or globally complete.
- The R9-added W13 backend caller checklist item has been removed by restoring that worklist's exact pre-R9 blob. This removes only the implementation item, not the servant source findings or any other research leaves. The audit records the old item and its disposition.
- W13 remains `active` for actual unresolved source semantics. A missing local CreateServant handler does not make the pinned creation occurrence unknown, and it does not block unrelated research.
- R0-R8 retain their recorded bounded source claims. C/D/E observations remain restricted to their inspected/tested SHA and actual scope. No package is newly promoted to `mechanism_closed`.
- No next archaeology slice, R9A implementation or R10 execution is authorized by this correction. Old numbered sequences and worklist `Next closure` suggestions are historical input, not automatic task assignments.

The full prior README and R9 review remain available at immutable evidence head [8daa6a8](https://github.com/yaelysia/hsr-battle-simulator/tree/8daa6a8abb9a15e423ecf987356dcc0a936565ba). No history is erased or backend defect declared repaired.

## Authority and research method

Programmatic discovery is **candidate generation only**. A path, field, opcode, formula, dynamic value or reference edge is not authoritative merely because a tool can find it.

A source claim requires manual semantic inspection of pinned raw rows/graphs, their owners, bindings, references, conditions and battle-state consequences. Classify mixed sources below file level and retain false friends and negative evidence.

The research chain is:

```text
gameplay question and source scope
-> exact pinned producer / reference / binding / authored consumer
-> interpreted battle consequence
-> reviewed evidence or a named source uncertainty
-> reusable facts for later backend consumption and implementation
```

An authored consumer in this chain can be a TBGD Ability task, Modifier, selector, formula operand or callback. It must not silently be replaced by a requirement that our Python runtime implements that operation.

The downstream architecture remains `TBGD -> compiler/lowering -> Canonical IR -> Combat Core`. That architecture explains how research may be consumed; it is not an obligation to make the entire path execute inside this evidence PR.

Gameplay knowledge guides questions and completeness checks but cannot fill missing pinned values or hidden native behavior. External/runtime disagreement is a reason to inspect and document the discrepancy, not to force either source to match the other.

## Local implementation comparison is supplementary

Reading current lowering, IR, runtime and validators is allowed when it helps navigation, exposes an interpretation assumption or identifies a concrete consumption concern. Such comparison does not select the research scope, replace raw authority, or require repair before research can continue.

Keep the independent axes when relevant:

| Axis | Meaning | Consequence for this ledger |
| --- | --- | --- |
| A | TBGD source-facing claim closed | State the exact source-supported claim, not whole-mechanism completion. |
| B | Pinned export/native-engine gap | Name the missing source contract; preserve uncertainty without inventing an engine body. |
| C | Local implementation exists | Optional implementation observation, not proof of A. |
| D | Inspected local contract agrees with source evidence | Optional comparison, not a prerequisite for a source fact to be recorded. |
| E | Actual matching-scope, SHA-bound execution evidence | Required only for a runtime-verified claim, not for archaeological progress. |

A local gap is a **backend consumption note**, separate from source uncertainties and the research queue. Record its source anchor and inspected SHA if useful, then leave implementation ownership outside PR #8. Do not attach a repair card, merge dependency or runtime acceptance gate to the next archaeology step. If comparison challenges a source interpretation, reopen only that evidenced interpretation question; a missing local implementation by itself is not such a contradiction.

Local `engine_convention` remains a convention. Existing code is not native GameCore authority. Test-file existence is not execution, and `skipped != passed`; neither an absent E nor a skipped workflow makes a reviewed raw fact fail.

Generic scheduler, RNG, AI, callback-total-order and native formula boundaries stay explicitly unresolved where the pinned artifact does not expose them. Do not repeatedly scan the same corpus to guess hidden bodies, and do not use a local implementation to claim those native bodies were recovered.

## Research status and evidence maturity

Use [BATTLE_RESEARCH_WORKLIST.md](BATTLE_RESEARCH_WORKLIST.md) for source/mechanism obligations and [SOURCE_FAMILY_INVENTORY.md](SOURCE_FAMILY_INVENTORY.md) for corpus triage. The worklist is not a backend execution queue or fixed denominator.

Research work statuses remain `candidate_new`, `active`, `blocked_evidence`, `mechanism_closed`, `deferred`, `retired_not_required` and `merged_into:<id>`, with their existing meanings. `blocked_evidence` refers to a named source/semantic evidence boundary, not an unimplemented local handler. A bounded record may retain a source-partial result when source obligations really remain; do not use that result to smuggle in implementation acceptance.

Individual evidence maturity remains `candidate -> manually_confirmed -> cross_validated -> runtime_verified`. Cross-validation and runtime validation must describe their actual supporting evidence. Not every useful research claim must reach the final maturity level.

A checked leaf covers only its exact statement. No completion percentage or global closure follows from representative examples, a repaired backend path, or accumulated R-number milestones.

## Required record contents

Every source record should state the gameplay concept/scope, exact revision/path/blob/occurrence, entity and binding identities, producer/reference/authored-consumer chain, interpreted battle consequence, authority class/maturity, negative evidence, and unresolved source questions. Include version context and corroboration where relevant.

When local code is inspected, put its SHA, behavior, comparison and validation level in a separately labeled implementation note. Do not make such a note mandatory for every raw fact or turn its unresolved items into research blockers.

Source roles remain `battle_authoritative`, `battle_supporting`, `mixed_requires_filter`, `progression_only`, `presentation_only`, `editor_tooling`, `telemetry_only` and `unknown_unreviewed`. Explicit `export_gap` / `engine_consumer_unavailable` annotations refer to pinned source boundaries, not backend readiness.

## Version discipline

All raw authority uses the fixed TBGD revision. Default-branch or live data may aid navigation but cannot silently fill pinned gaps. Large-file search/read failures are not omission proof. A source occurrence and its semantic interpretation must remain distinguishable from normalized local representations.

Implementation observations are dated and SHA-bound. Old inspection or execution evidence is not a claim about every later master. This does not require continuously revalidating the backend before publishing source research.

## Durable records and navigation

Governance and research ledgers:

- [BATTLE_SCOPE.md](BATTLE_SCOPE.md)
- [SOURCE_FAMILY_INVENTORY.md](SOURCE_FAMILY_INVENTORY.md)
- [BATTLE_RESEARCH_WORKLIST.md](BATTLE_RESEARCH_WORKLIST.md)
- [PINNED_SOURCE_INDEX.md](PINNED_SOURCE_INDEX.md) — navigation cache, not independent semantic authority.
- [EVIDENCE_RECORD_TEMPLATE.md](EVIDENCE_RECORD_TEMPLATE.md)
- [Scope-drift audit and correction](../../../../../docs/tbgd_evidence/shared/pr8_scope_drift_audit_2026-09-23.md)

Bounded source records; consult their claim-level limits rather than treating them as backend acceptance gates:

- [R0 battle execution language](../../../../../docs/tbgd_evidence/shared/battle_execution_language_core_v1.md)
- [R1 ordinary damage](../../../../../docs/tbgd_evidence/shared/ordinary_damage_vertical_slice_v1.md)
- [R2 weakness, toughness and Break](../../../../../docs/tbgd_evidence/shared/weakness_toughness_break_vertical_slice_v1.md)
- [R3 healing and modifier lifecycle](../../../../../docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md)
- [R4 resource economy](../../../../../docs/tbgd_evidence/shared/resource_economy_core_v1.md)
- [R5 battle-start build source construction](../../../../../docs/tbgd_evidence/shared/battle_start_build_construction_v1.md)
- [R6 encounter, spawn, phase and termination](../../../../../docs/tbgd_evidence/shared/encounter_spawn_phase_termination_v1.md)
- [R7 targeting and enemy decision boundary](../../../../../docs/tbgd_evidence/shared/action_targeting_enemy_decision_boundary_v1.md)
- [R8 startup-effect source chains](../../../../../docs/tbgd_evidence/shared/battle_start_effect_activation_v1.md)
- [R9 retained servant source facts and scope correction](../../../../../docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md)

Representative and shared records:

- [March shield](../../../../../docs/tbgd_evidence/characters/march_7th_preservation_skill02_shield.md)
- [Aglaea servant11402](../../../../../docs/tbgd_evidence/characters/aglaea_servant_11402_reference_chain.md)
- [Monster1002011](../../../../../docs/tbgd_evidence/monsters/monster_1002011_reference_chain.md)
- [LC20000](../../../../../docs/tbgd_evidence/equipment/light_cone_20000_arrows.md)
- [Stage wave sources](../../../../../docs/tbgd_evidence/stages/stage_config_wave_source.md)
- [Global/shared reverse scan](../../../../../docs/tbgd_evidence/shared/global_shared_reverse_scan.md)
- [RNG and callback source chains](../../../../../docs/tbgd_evidence/shared/ordinary_rng_callback_reference_chains.md)
- [OneMore and speed boundary](../../../../../docs/tbgd_evidence/shared/timeline_one_more_and_speed_boundary.md)
- [Initial March wiring](characters/march_7th_preservation_source_chain.md)

Historical integration/planning, not current task authorization:

- [Parallel integration](PARALLEL_INTEGRATION_2026-09-09.md)
- [Post-R4 compaction](POST_R4_RESEARCH_COMPACTION_2026-09-10.md)
- [Post-R5 compaction](POST_R5_RESEARCH_COMPACTION_2026-09-11.md)

R6's retained implementation validation remains limited to the recorded tested SHA `70eabfe4a94ec458eacdd4bf324d9a8889743c49` and its selected materialization/wave-fixture/rejection/catalog scope. It does not prove complete battles, confer E on R7-R9, or establish a repair prerequisite for this ledger.

## Publication boundary

Keep PR #8 open/Draft and docs/evidence-only. Do not modify runtime, lowering, IR, tests, CI or the TBGD pin. A checkpoint reports new source knowledge, exact anchors, remaining source uncertainties, affected documents and any separately scoped corroboration. It must not become a backend repair/merge handoff.
