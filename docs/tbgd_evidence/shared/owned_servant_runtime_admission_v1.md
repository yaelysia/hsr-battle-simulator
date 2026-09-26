# R9 — Retained servant source facts; runtime-admission scope withdrawn

## 1. Current disposition — 2026-09-23

This entry retains useful pinned-source findings from the former R9 review and separates them from backend implementation observations. Its filename is preserved for existing links; it is **not an active runtime-admission task or a gate on further archaeology**.

The former completion rule made local CreateServant transport a prerequisite for completing this research slice. That rule is withdrawn under the [PR #8 scope correction](pr8_scope_drift_audit_2026-09-23.md). The entire former review, including its partial result, source anchors, consumer observations and unadjudicated downstream items, is preserved at [evidence head 8daa6a8](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md).

Current research accounting:

- Retained exact source claims: `manually_confirmed`, restricted to the occurrences and reused chains below.
- W13: `active` for actual unresolved source semantics; not waiting for an implementation PR.
- Former R9 runtime-admission task: removed from the archaeology completion path, not relabeled as passed, runtime-verified or whole-mechanism complete.
- Local runtime execution E: not established by this record or this scope correction.
- No new TBGD archaeology, source promotion, simulator execution or backend change is claimed by the correction.

## 2. Source authority and reused evidence

Upstream: `DimbreathBot/TurnBasedGameData` at **`14c1d18f91a8101d610e6c523447a7517de3fae1`**.

The source details below are retained from the manually audited R9 source occurrence and the existing [Aglaea/11402 reference chain](../characters/aglaea_servant_11402_reference_chain.md), with [Battle Execution Language Core v1](battle_execution_language_core_v1.md) supplying reusable parameter/entity/dispatch vocabulary. The scope correction does not claim to have independently rerun those raw audits.

`AvatarServantConfig[11402]` names `Servant_AglaeaServant_00_Config.json`, `Avatar_ComplexSkilll_AutoFight_AI.json` and skills `[1140201,1140203,1140205,1140206]`. Dedicated construction inputs include:

```text
SpeedInherit = "#4"
SpeedSkill = 140204
HPInherit = "#5"
HPBase = "#6"
HPSkill = 140204
Aggro = 125
```

Skill140204 Lv1 has `ParamList=[0.12,0,0,0.35,0.44,180]`. The corresponding skill selects the parameter list and `#N` selects its one-based slot. The previously audited servant11413 discriminator supports that interpretation; it does not make every servant's coefficients or ownership identical. Native HP/speed construction mathematics and the generic parser body are not established by this slot mapping.

Ownership is expressed through the ordinary owner's creation occurrence and source relations such as `CasterSummoner`, not an invented fixed-owner field in the servant table.

Keep three source surfaces distinct: global `GameCoreConstValue.ServantSyncPropertyList`, per-servant `SyncPropertyExceptList`, and dedicated HP/speed construction references. Their existence does not by itself establish a subtraction/union algorithm, precedence or synchronization timing.

## 3. Exact ordinary CreateServant occurrence

Pinned source: [Avatar_Aglaea_00_Ability.json, lines 690–800](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json#L690-L800).

| Identity | Retained source value |
| --- | --- |
| Path | `Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json` |
| Blob | `c1993e2663dfcd0748e45b421411f7f4fdc093e8` |
| Ability | `Avatar_Aglaea_00_Skill02_Phase02` |
| JSONPath | `$.AbilityList[3].OnStart[1].SuccessTaskList[0]` |
| JSON pointer | `/AbilityList/3/OnStart/1/SuccessTaskList/0` |
| Raw type | `RPG.GameCore.CreateServant` |
| Servant ID | `IsDynamic=false`, `FixedValue.Value=11402` |

The parent `PredicateTaskList` uses `ByCompareTargetCount`, `TargetAlias=CasterServant`, `AliveOnly=true`, comparison `LessEqual` against fixed zero. The selected create occurrence is therefore in the no-living-servant branch.

Retained creation dynamic inputs are `_PointB3Layer` (hash `138415046`), `Skill11_DamagePercentage` (`-909740667`) and `Skill11_DamagePercentageAD` (`1326964645`). These authored inputs must remain distinguishable from the servant-definition construction parameters. This record does not infer their complete native initialization evaluator from their names.

The later explicit `SetActionDelay(0)` targets **Caster**, not CasterServant. The exact selected ability does not serialize a literal `ActivityOnCreate` field. Its omission is not proof of a native default or synchronous passive startup.

The source-facing chain to retain for backend use is:

```text
ordinary owner Skill02 ability
-> no-living-CasterServant predicate
-> exact CreateServant(11402) occurrence and authored dynamic inputs
-> AvatarServantConfig[11402] identity/config/skill/construction references
-> separately authored owner/servant ability, property and lifecycle surfaces
```

A missing handler in our simulator cannot erase this raw creation instruction or turn the known servant ID into a missing TBGD producer.

## 4. Recast, action identity and lifecycle limits

The existing source audit distinguishes ordinary create-if-absent from maintaining/healing an existing servant. Do not rewrite that source rule as unconditional spawn-and-replace. A local duplicate-active blocker is not the authority for ordinary recast semantics.

The selected no-living-servant predicate alone does not establish every defeated-instance replacement policy. Preserve that limitation rather than inferring unconditional recreation.

Selectable servant Skill01 is distinct from the owner's coordinated Skill11/Together contribution. Reuse the existing [Aglaea record](../characters/aglaea_servant_11402_reference_chain.md) and [R7 target-boundary record](action_targeting_enemy_decision_boundary_v1.md) for their actual source claims; do not promote a target-shape match into full coordinated-action semantics.

Existing pre-death, death-rattle, owner death-listener and later removal surfaces remain distinct. The BattleEvent-triggered muted forced-cleanup path must not be collapsed into ordinary natural death. None of these source surfaces supplies a universal native death/destruction order.

## 5. Actual source questions still open

These are research/evidence limits, not implementation acceptance tasks:

- creation-time versus continuous/event-driven synchronization and native merge/precedence of global sync, exceptions and dedicated HP/speed inputs;
- native passive auto-entry and initial queue/scheduling behavior where the corresponding engine consumer is not exported;
- generic servant resource ownership and `SPBase` semantics beyond the already audited recipient/raw-value chains;
- full JoinSkill/coordinated-action semantics and any still-unaccounted-for authored branches;
- universal natural death/death-rattle/OnDestroy/entity-removal ordering and defeated replacement authority beyond the exact source evidence.

Use bounded source questions and the existing no-repeat rules. Do not guess hidden GameCore, scheduler, RNG, AI or callback ordering. Lack of a local implementation is not evidence that another source family must be searched; lack of an exported native consumer remains a named source boundary.

## 6. Separately retained backend consumption observation

The [historical R9 review](https://github.com/yaelysia/hsr-battle-simulator/blob/8daa6a8abb9a15e423ecf987356dcc0a936565ba/docs/tbgd_evidence/shared/owned_servant_runtime_admission_v1.md#5-r9-gate-actual-production-transport) inspected business SHA **`f8e8a053ef591e1aeeb99956d46acd8390676c6f`**. Its R9-G01 observation was a local missing edge from a source-bearing CreateServant task to the existing `SummonSystem.plan_spawn_servant` consumer, not a missing upstream creation fact.

The historical source-proof, owner/build, duplicate/replacement and registry observations remain available there. They are useful implementation notes, not TBGD semantics. No guard is weakened and no defect is declared fixed by reclassifying this document. This correction does not independently certify the current backend head.

Former downstream G02–G06 were not globally cleared by that review and are not cleared here. Actual caller transport, UnitState/registry consistency and selected execution validation belong to independently authorized backend work. They no longer occupy W13 source checklist leaves or block PR #8 research.

Existing fixture tests that directly invoke a spawn API are not proof of the ordinary source Ability path. Equally, the absence of such execution proof is not a failure to establish the raw source facts in sections 2–4.

## 7. Claim separation

| Claim | Source/evidence disposition | Local implementation disposition |
| --- | --- | --- |
| Exact CreateServant ID, occurrence and no-living predicate | Retained manually confirmed claim | Not dependent on a local caller being implemented. |
| Authored creation dynamic inputs | Retained occurrence inputs | No selected runtime seeding/execution claim. |
| Servant config, corresponding-skill/one-based parameter slots | Reused source claims with existing cross-sample limit | Native evaluator and full local birth projection not inferred. |
| Global sync / exceptions / dedicated construction partition | Source surfaces retained; native merge/timing unresolved | Existing helper behavior is supplementary, not raw authority. |
| Recast and Skill01/Together distinctions | Retained bounded source distinctions | No complete runtime action/registry claim. |
| Native scheduler/passive/death ordering | Named source/engine evidence boundaries | A local convention would not close the native source gap. |
| Historical R9-G01 and downstream local review | Not missing-source research obligations | Separately scoped historical implementation observations. |

No blanket A/C/D/E label applies to the entire former R9 task. The corrected research result is retained bounded source knowledge plus explicit source uncertainties. There is no repair-dependent research stop and no automatic next task.
