# PR #8 scope-drift audit and research-charter correction

## 1. Purpose and authority

Reviewed: **2026-09-23**. Evidence branch before correction: `research/tbgd-battle-evidence-ledger` at **`8daa6a8abb9a15e423ecf987356dcc0a936565ba`**. TBGD pin remains **`14c1d18f91a8101d610e6c523447a7517de3fae1`**.

The owner explicitly requested that the historical drift into backend workflow be identified and cleaned up before any next archaeology task. The intended purpose is to establish combat-relevant facts in the game database for later backend use and implementation, not to run backend acceptance inside the evidence project.

This is a documentation/history audit. It does not perform new mechanism archaeology, validate a new backend SHA, start a repair, or authorize the previously suggested DoT/R9A/R10 tasks.

## 2. Original charter recovered from primary project history

[Issue #7](https://github.com/yaelysia/hsr-battle-simulator/issues/7), created 2026-09-07, asks for a manually audited, version-pinned battle-source catalog and relationship graph: exact source paths, identities/join keys, upstream/downstream references, field-level roles, raw evidence, confidence, false friends and unresolved semantic gaps. It permits comparison against lowerer/runtime assumptions but expressly calls the work archaeological/data-authority work, not permission to refactor runtime.

[PR #8's original purpose](https://github.com/yaelysia/hsr-battle-simulator/pull/8) is a durable Draft documentation/evidence store for that task. The [initial README at commit 540e7a7](https://github.com/yaelysia/hsr-battle-simulator/blob/540e7a7e8ff111b711d86905ec4387736554a169/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/README.md) requires reviewed source facts, references, meaning, negative evidence and unresolved questions. `runtime_verified` is a stronger evidence maturity, not a requirement for every recorded fact.

The [early archaeology handoff, comment 5566579415](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5566579415), makes the semantic unit explicit:

```text
Excel/base parameter definition
-> DynamicHash/DynamicValue binding
-> ConfigCharacter wiring
-> Ability control flow
-> Modifier/Damage/Resource consumer
```

Those consumers are part of the source-semantic explanation. The handoff does not require that the simulator already implement them. Its useful checkpoint examples include a source chain closed, an upstream source gap proven, a reusable semantic rule and a false friend classified.

[BATTLE_SCOPE.md](../../../hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/BATTLE_SCOPE.md) expands this into accounting for the in-scope battle-reachable corpus, including mixed-field filtering, reverse references and explicit unresolved/export boundaries. Backend implementation coverage is not its denominator. Corpus scope is not determined by what the local runtime currently admits.

## 3. Traceable drift, before and through R9

| Historical point | What the artifact says | Effect on scope |
| --- | --- | --- |
| Original charter and early handoff, 2026-09-07 | Build reusable reviewed source facts/reference graphs; runtime is a comparison aid. | Research supplies backend work. |
| [Post-R4 compaction, dated 2026-09-10](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/POST_R4_RESEARCH_COMPACTION_2026-09-10.md) | Adds mandatory kernel-first checks and A/B/C/D/E axes; later slice exits increasingly require alignment to current consumers. | A useful navigation/comparison technique starts becoming an acceptance dependency. The axes themselves still say they are independent. |
| [Post-R5 R6 contract](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/tbgd_evidence/POST_R5_RESEARCH_COMPACTION_2026-09-11.md) | Required chain includes local WaveDefinitionIR, UnitBirthTemplateIR, UnitState and transition consumers. A stop clause says a source-true behavior could require changing runtime/lowering/IR to document correctly. | Local materialization/transport is embedded in the archaeology exit. Correctly documenting a source fact or local discrepancy does not require repairing production. |
| [R6 checkpoint 5628592736, 2026-09-11](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5628592736) | Uses `[NEEDS_REPLAN]`; source-facing stage joins are recorded, but missing local `monster_rank_source_trace.evidence` prevents the bounded result and routes to repair. | Concrete earlier instance of a backend defect becoming a research stop, before R9. |
| R6A repair and reconciliation history | Repair/review/validation/merge becomes the path back to evidence completion. | A backend repair loop is hosted in the evidence discussion, providing a precedent for later gates. Its actual test results remain valid only for their reported scope. |
| [R8 planning comment 5660811507, 2026-09-14](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5660811507) | A selected source-backed startup chain blocked by a local mismatch must stop with NEEDS_REPLAN. | The mismatch-stop policy is repeated as a planning rule, rather than kept as a separate implementation observation. |
| [R9 plan 5661982814, 2026-09-14](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5661982814) | Primary question is formal caller -> owned-build admission -> ServantDefinitionIR/birth template -> plan_spawn_servant -> UnitState/registry. It explicitly requires `partial / NEEDS_REPLAN` if CreateServant transport is missing. | Direct source of R9's erroneous research status. The rule existed before the R9 execution result. |
| [R9 commit 8daa6a8](https://github.com/yaelysia/hsr-battle-simulator/commit/8daa6a8abb9a15e423ecf987356dcc0a936565ba) and [checkpoint 5662626039](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5662626039) | Applies the gate, updates README, and inserts one unchecked W13 CreateServant formal-caller implementation item. | The implementation result becomes the durable current research status and worklist obligation. |
| [R9 integration comment 5662809355](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5662809355) and [restart comment 5743367859](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5743367859) | Introduce R9A implementation, overlapping #17/#11 dependencies, implementation validation, acceptance/merge, and R10 blocked until reconciliation. | Full backend workflow governs future archaeology. The later restart changes execution scheduling, not this underlying scope mistake. |

The original post-R4 route called R9 a W09/W12 status-probability/control/DoT/RNG alignment slice. The later R9 plan replaced it with servant runtime admission. Renaming/reordering a research slice can be legitimate, but this substitution selected a backend integration obligation rather than an unanswered source-semantic question. The old DoT proposal is not automatically reinstated by this audit.

The literal backend label is therefore not a spontaneous source discovery and not merely a reporting typo. R9 followed a drifted task contract that had already prescribed that label for local non-admission.

## 4. Why the goal drifted

### 4.1 Comparison was promoted into a prerequisite

The legitimate rule was: use local code to navigate efficiently, identify assumptions and compare interpretations. The drifted rule became: the selected source fact must successfully connect to current local production interfaces before research may close or advance.

These are different propositions. A can be established while C is absent or D is not established. An export/native gap B can coexist with a local convention. The absence of E restricts execution claims, not the ability to publish manually confirmed source facts.

### 4.2 Two meanings of consumer were merged

The source consumer is an authored TBGD task, modifier, callback, selector or operand whose role must be understood. The implementation consumer is our lowerer, IR shape, dispatcher, admission guard or Python spawn API.

R9's decisive missing edge was between local implementation surfaces. The known raw CreateServant occurrence was not missing. Treating the local caller gap as a research failure changed the object being closed.

### 4.3 File-write scope was mistaken for mission scope

Keeping every change in Markdown prevented accidental production edits, but did not prevent the Markdown from specifying backend repair cards, dependency gates and acceptance workflows. `docs/evidence-only` was respected as a file boundary while the research goal drifted.

The correct response to a concrete local mismatch is to preserve a separately labeled consumption note, not to make PR #8 responsible for arranging its repair or awaiting its merge.

### 4.4 The old result propagated through current-entry documents

The 8daa6a8 commit put the admission-dependent result into both README and the W13 worklist. Later integration comments then treated that result as a prerequisite for the next research step. A reader starting from the latest summary could perpetuate the wrong objective while accurately repeating remote text.

The immediately preceding review in this conversation did that: it rechecked the missing local caller and continued using the inherited status instead of first testing the plan against the original charter. Verifying that a backend gap is real does not justify making it a research gate.

### 4.5 Attribution limit

The repository establishes the document/comment chain above. It does not establish which unrecorded prompt, agent, plugin or person originated each planning choice. GitHub account/app attribution alone is insufficient to infer that provenance. This audit identifies the written rule and its propagation, not an unsupported culprit.

## 5. Correct disposition of R9

| Retain | Reclassify/remove from current research control |
| --- | --- |
| Exact pinned CreateServant occurrence, ID, predicate and dynamic inputs. | The whole runtime-admission task as a prerequisite for archaeology completion. |
| Existing servant configuration, parameter-slot, ownership, recast and lifecycle source claims. | R9-G01 from a W13 research blocker into a separately scoped backend observation. |
| Genuine unknown source/native synchronization, passive-entry, scheduling, resource/coordinated-action and death-order semantics. | Unexecuted UnitState/registry/admission checks as supposed missing game-database facts. |
| Historical local guard observations and actual validation limitations. | R9A/#17/#11 repair/merge/WAIT dependencies as controls on PR #8 research. |
| Historical R6/R7/R8 source findings and actual scoped C/D/E evidence. | Any implication that future research must repeat the R6 repair loop. |

Do not fix the scope mistake by replacing the old status with `bounded_complete`. The former task was an implementation review with uncompleted implementation obligations. Those obligations are outside the research completion path; their removal proves neither that the backend works nor that W13 is globally closed.

## 6. Cleanup applied by this checkpoint

1. Replace the current README's admission/repair sequencing overlay with the original source-catalog purpose, source-based status rules and a supplementary implementation-comparison boundary. Historical compactions and checkpoint stop rules lose current task authority where they conflict with this correction.
2. Reclassify the existing R9 path into retained source facts, genuine source uncertainties and a clearly separated historical backend observation. Keep an immutable link to the complete former review; do not discard its technical evidence or manufacture a repair.
3. Restore `BATTLE_RESEARCH_WORKLIST.md` to pre-R9 blob **`06f4bfff828be120f86b4e2a49e44646c9de40a6`** from parent **`c13d4dcf0932551578fb8e4329d5c77f74d4e02f`**. The R9 commit's exact diff added only the single backend-caller leaf to this file. Restoring that blob removes precisely that item, preserving all other checked/unchecked source leaves. This audit is the explicit disposition record, not a silent deletion.
4. Preserve the original PR description, BATTLE_SCOPE, source-family inventory, pinned-source index, raw source records, old commits and old comments. The current correction supersedes mistaken workflow authority; it does not rewrite historical statements to pretend the drift never occurred.

The prior complete state is auditable at `8daa6a8abb9a15e423ecf987356dcc0a936565ba`; the original mission is auditable at Issue #7 and `540e7a7e8ff111b711d86905ec4387736554a169`.

## 7. Rules against recurrence

A future archaeology task must name a source-semantic question before naming local APIs. Its exit must be a reviewed source chain, explicitly bounded semantic result, negative evidence, or named source uncertainty. A mechanism may remain source-partial; no missing facts may be guessed for convenience.

Implementation inspection may supply navigation or an independent comparison. It cannot define which game facts exist, narrow corpus coverage to executable local operations, or require production repair/merge before further research. Backend notes do not enter source checkboxes and do not become PR #8 repair cards.

Hidden native-engine gaps stay explicit. A local convention is not source proof. Existing tests, skipped checks and unrelated successful runs neither establish the selected execution claim nor invalidate an already-supported source fact.

PR #8 remains Draft and docs/evidence-only. This checkpoint stops after restoring the research boundary and preserving the audit trail. No next mechanism research or backend implementation is started.
