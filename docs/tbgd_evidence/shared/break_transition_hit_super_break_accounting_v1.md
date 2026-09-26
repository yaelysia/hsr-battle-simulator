# Break-transition hits and source-qualified Super Break accounting v1

## 1. Scope, publication state and result

Reviewed 2026-09-26. Evidence parent: `a987d2607f135799a9427c9341ebdf002a1b2c90`; preceding published checkpoint: `5811382763`. Raw authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 remains open/Draft and docs/evidence-only.

This executes the selected `DIVE-BREAK-TRANSITION-ACCOUNTING-V1` from [the integrated review][REVIEW], rather than starting another foundation overview or completing a character kit. It is the first persisted record of the preceding read-only investigation and this continuation. The earlier investigation did not publish a commit; its source readings and attributed interpretation are explicitly distinguished below from this continuation's new contrast.

**Result:** the shared target-side accumulator's eligibility, addition, two explicit reset callbacks and named-state reader are mapped. A second ordinary source has its own named-hit window and passes a nonnegative value explicitly, demonstrating that one global accumulator or one universal attack-end trigger is insufficient. Zero, negative sentinel and omitted inputs are different cases. The ordinary crossing-hit exclusion model is retained with its public provenance; the ordinary direct-damage hit's exact mitigation sampling remains open.

FG-01/F02/F03/W04/W06 remain active for the named residuals, not a backend repair. No finished-build acquisition, progression, generic scheduler/RNG reconstruction, special-bar survey, simultaneous death/revive, production-code modification or runtime acceptance is part of this record.

## 2. Evidence register and strength

All S paths are relative to the fixed TBGD repository. Named occurrences, full blobs and the pin identify the evidence; search on a default branch was navigation only.

| Ref | Source and selected occurrence | Complete blob / treatment |
| --- | --- | --- |
| S1 | [Level_BattleCommonRule_Ability][S1], entire `StageAbility_BattleCommonRule`, especially its SuperBreak parent and SubOnEnemy definition | `2ae50c06ac149b49b1f8fa4547000b0fc3f0b142`; full reread |
| S2 | [GlobalTaskListTemplate][S2], complete `DealSuperBreakDamage` and `BeingDealSuperBreakDamage` entries | `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96`; reread around lines 4150-4590 |
| S3 | [Sam Ability][S3], `MAvatar_Sam_00_PointB2_SuperBreakBuff` and earlier inspected `Skill21_Phase02` | `dc815e85ba03509a158b7b4e1c7f79e3e81c9879`; caller reread 6600-6740, carrier reused from preceding exact-pin read |
| S4 | [Rappa Ability][S4], Skill03 entry/installation, UltraMode child configuration, selected Skill11 request, complete `MAvatar_Rappa_00_PointB2_Enemy` | `03c55bdd09e158cd23dade24c9fbefab83e9d46b`; new independent source/window contrast |
| S5 | [Rappa CharacterConfig][S5], Skill03/Skill11 entries and `745450807` binding | `86e978a5bc045736342b70ff9d4d0c367a5778cd`; new owner/parameter qualification |
| S6 | [Common Specific modifiers][S6], `StanceBreakState` and `MonsterAllDamageReduce` | `2db782ddc81b7a1328e4086dc71c8a23295b06a8`; reread 1-298 |
| S7 | [Monster Common Ability][S7], `Local_ListenStanceBreak.OnBeingBreak` and installing passive | `fa02f6ab070fb8da16ebd2f5976503446d633e0e`; reused preceding exact-pin read and F02/R2 |
| S8 | [StageCommonTemplate][S8], OnStartSequece adding `StageAbility_BattleCommonRule` | `d76c3f1d8a2536da6a6f79e4bb44b79f48b91c5a`; reused preceding exact-pin read |
| S9 | [Sam CharacterConfig][S9], PointB2 indices 0-3 | `0f682c63600b996e63ebfc24e761a1a6d28fec10`; reused preceding exact-pin read |

S4 replay ranges: 670-910 for the selected named attack; 2820-3340 for Skill03 Phase01 -> Phase02 and mode installation; 4600-5150 for UltraMode/child configuration; 5110-5470 for the complete PointB2 enemy-state callbacks and declarations. Camera, visual and unrelated resource neighbors are not promoted into the accounting chain.

| Ref | Public/source-model evidence | Actual use and qualification |
| --- | --- | --- |
| P1 | [KQM SRL damage formula][P1] at `de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, blob `2928c24daa92422d90df5cf3ef1766932779f4d2` | Reread here. Supplies the ordinary 0.9/1 toughness-state model, but no explicit crossing-hit sampling instant. It is marked under construction and credits arkkus; not an independent new test. |
| P2 | [Previously cited TapTap split-hit explanation][P2] | Carried forward from the immediately preceding read-only investigation, which used it to adopt exclusion of the crossing hit and its unused toughness. Not independently reread through the GitHub-only continuation; no new empirical corroboration or exact-pin numerical-row claim. |

The P2 interpretation is kept as an attributed ordinary behavior model, not elevated to a raw-only theorem about native event dispatch. S1's predicate is compatible with it, but the callback name alone cannot prove the precise native state visible at every event. The former hypothetical Q10/Q15/Q20/Q30 comparison therefore has a preferred ordinary model with stated support, not a newly performed four-way experiment.

Existing [R0][R0] arithmetic/context vocabulary, [F01][F01] source-qualified values, [F02][F02] damage-state distinctions, [F03][F03] formula/unit roles and [R2][R2] source reachability are reused. This record does not recertify all of their raw files or external tests.

## 3. Shared installation is not itself a Super Break enabler

S8 explicitly requests `AddStageAbilityByName(StageAbility_BattleCommonRule, CanReplace=false)`. S1's `OnAdd` installs `MStageAbility_BattleCommonRule_SuperBreak` on `LevelEntity`. Its `AdditionConfig.SubModifierList` names:

```text
MStageAbility_BattleCommonRule_SuperBreak_SubOnEnemy
TargetType = AllDarkTeamWithAllDarkTeamUnselectable.RemoveBattleEvent
IsHaloStatus = true
AliveOnly = "False"
```

The child has the actual accounting callbacks. Its own callback body does not issue Super Break damage. A target can carry accounting machinery without the current attacker possessing an eligible damage-producing source. Installation, recording, permission to invoke and coefficient selection are distinct facts.

The target set retains its unselectable and BattleEvent qualifications. Do not replace it with all visible enemies or claim how every late spawn inherits the halo from this declaration alone.

## 4. Shared accumulator: conditional addition and two explicit resets

The complete S1 child defines only the following three callbacks:

| Callback | Authored state-facing operation |
| --- | --- |
| `OnAfterBeingAttackedEnd` | Set `MDF_TotalStanceDamage` to literal 0 |
| `OnListenBeforeAction` | Set `MDF_TotalStanceDamage` to literal 0 |
| `OnBeforeBeingStanceDamage` | Test the eligibility predicate below; on success read `ParamValue2` and add it to the total |

The addition predicate is an OR of:

```text
ModifierOwnerEntity contains Break
ParamEntity contains STAT_ForceSuperBreakDamage
ModifierOwnerEntity contains STAT_ForceSuperBreakDamage
```

The successful branch is:

```text
SetDynamicValueByVariateType(MDF_HitStanceDamage, ParamValue2)
SetDynamicValue(MDF_TotalStanceDamage,
  PostfixExpr=AQABAQIR,
  DynamicHashes=[2124587683,-1094919248])
```

With `Q` the source-qualified total and `q_event` the supplied second event value, the local operation is `Q := Q + q_event` when the predicate holds. It is not an unconditional addition of the entire skill's nominal toughness damage. There is no explicit crossing-overflow correction in this body.

This identifies the *consumer* of `ParamValue2`; it does not recover the native producer's efficiency, matching, clamp, split or rounding stages. Do not equate `ParamValue2`, another event's `ParamValue`, the primary skill's unbound hash `1659254037`, and actual gauge loss solely because they concern toughness.

The explicit reset events are not replaced with a generic per-turn rule, nor with reset after each visual damage number. Their exact ordering relative to arbitrary nested damage or inserts remains separate. No global callback total order follows from the order in which the callback definitions are serialized.

## 5. The shared reader has two input modes, not a fallback for every zero

S2 `DealSuperBreakDamage` traverses `TemplateParamEntityList`, preserving its literal `ByRandom=true` without inferring undocumented cardinality. For each actual `ParamEntity`, it defines `TDF_TotalStanceDamageOnTarget` in `ContextTaskTemplate` and selects:

```text
if template-context StanceValue < 0:
    copy ParamEntity's
      MStageAbility_BattleCommonRule_SuperBreak_SubOnEnemy.MDF_TotalStanceDamage
else:
    use the supplied StanceValue

if selected value > 0:
    issue the authored Super Break damage request
```

The request uses `FormulaType=ByBreakDamage`, `AttackType=ElementDamage`, tag `{EnumIndex:3,Value:33}`, and `FinalFormulaType=ByPureDamage`. The percentage expression is `AQABAQAABQQR`, fixed `[30]`, hashes `[44044987,1039671212]`: source coefficient times selected old-unit Q divided by 30, as already reconciled in F03. These tokens are not a new universal mitigation-bypass claim.

`BeingDealSuperBreakDamage` first requires the holder to be alive, copies from the holder's named shared state in its negative branch, and damages `ModifierOwnerEntity`. Its element read addresses `Caster`; the outgoing form instead reads `ModifierOwnerEntity`. Equal arithmetic does not make those entity roles interchangeable.

Neither complete reader body explicitly subtracts or clears the source total. It is a copy/read, not an authored consume-on-read operation. This does not rule out side effects from a resulting damage event or intervening callbacks; those require their own source/observation.

### Boundary discriminators

Assume a legal template invocation, a valid relevant target, shared total 30, and no intervening mutation. The following are source-conditional predictions, not gameplay measurements:

| Supplied template StanceValue | Selected Q | Consequence |
| --- | ---: | --- |
| -1 | 30 | Negative branch copies the named shared total |
| 10 | 10 | Explicit input overrides the choice of accounting source; do not add the shared 30 |
| 0 | 0 | Positive-Q guard fails; do not fall back to 30 |
| omitted | Not established by these bodies | Do not fabricate either 0 or -1 as a serialized default |

The negative value above selects an input mode; it is not a claim that an enemy's remaining toughness is negative. The exact missing-argument environment remains a source-transport question.

## 6. Existing ordinary caller: source qualification remains independent

S3 `MAvatar_Sam_00_PointB2_SuperBreakBuff.OnAfterAttack` has Priority 100. It tests the holder's `BreakDamageAddedRatio` against a higher threshold, otherwise a lower threshold, and invokes `DealSuperBreakDamage` with `AttackTargetList` and the appropriate `DamagePercentage` input. S9 binds:

| Hash | Qualified parameter |
| --- | --- |
| -1031150293 | SkillTreeParam(PointB2,0), lower threshold |
| 574260151 | SkillTreeParam(PointB2,1), higher threshold |
| -1222745430 | SkillTreeParam(PointB2,2), lower coefficient |
| -53190708 | SkillTreeParam(PointB2,3), higher coefficient |

The nested success/failure branches choose one coefficient, rather than automatically summing both threshold rewards. No new pinned point-table numbers are supplied by this record. The installer/range qualification in the preceding read remains distinct from the invocation's comparison.

This caller does not explicitly pass `StanceValue`. The shared reader's negative branch is known, but the missing-argument bridge is not newly closed. Source-compatible observable Super Break behavior is not withheld because of that bridge, and an omitted argument is not silently rewritten to -1 in the evidence.

## 7. New independent contrast: named-hit-local explicit input

The one added source contrast is Rappa's ordinary PointB2 path. Its purpose is to discriminate window/input ownership, not to complete that character.

### 7.1 Reachability and parameter donation

S5's Skill03 entry leads to `Avatar_Rappa_00_Skill03_Phase01`; S4 explicitly triggers Phase02. The latter checks for `MAvatar_Rappa_00_UltraMode` and, in the absent-state branch, installs that mode on Caster. The mode's child configuration names `MAvatar_Rappa_00_PointB2_Enemy` on `AllDarkTeamWithAllDarkTeamUnselectable`, gated by `BySkillPointActivated(PointB2)`.

The child receives `MDF_PropertyValue2` from hash `745450807`, which S5 binds to `SkillTreeParam(PointB2,0)`. This is a combat conversion-coefficient input; no trace unlock cost or account prerequisite is needed. The child declares the receiving working hash `-2125946860` and later passes it as template `DamagePercentage`. No unread numeric row is filled from a remembered character percentage.

S5 also selects Skill11's Phase01, which explicitly calls Phase02. The selected ordinary, matching-Imaginary-weakness/no-rank-override request in Phase02 carries `AttackType=Normal` and `CustomName=Rappa_UltraAttack_Damage`. Its primary StanceValue still uses the existing common-hash surface. A raw name containing Ultra does not turn this request into an Ultimate attack category.

### 7.2 A different accounting window

S4's complete `MAvatar_Rappa_00_PointB2_Enemy` defines:

```text
OnBeforeBeingHitAll:
    if damage CustomName == Rappa_UltraAttack_Damage:
        MDF_TotalStanceDamage := 0

OnBeforeBeingStanceDamage:
    if holder has Break OR event entity/holder has STAT_ForceSuperBreakDamage:
        MDF_HitStanceDamage := ParamValue2
        MDF_TotalStanceDamage := MDF_TotalStanceDamage + MDF_HitStanceDamage

OnAfterBeingHitAll:
    require Caster intersects ParamEntity
    require ParamEntity has MAvatar_Rappa_00_UltraMode
    require damage CustomName == Rappa_UltraAttack_Damage
    call BeingDealSuperBreakDamage(
        DamagePercentage = local MDF_PropertyValue2,
        StanceValue = local MDF_TotalStanceDamage)
```

The reset predicate checks the custom damage name; the final-use predicate is stricter and also checks source identity and mode. Do not copy the final-use predicates backwards into the update/reset body when quoting raw data.

This is a named-hit accounting window with an explicit argument, not the shared state's `OnListenBeforeAction` / `OnAfterBeingAttackedEnd` lifetime. Exact correspondence between native hit callbacks and visual sub-hits is not inferred merely from the event names.

The resulting template request has a positive-Q guard and, in the receiver-oriented form, a holder-alive guard. A local total of zero therefore cannot borrow an older positive total from the shared stage state. The explicit path is now source-closed as an input-mode contrast; it does not close Sam's omitted-argument transport by analogy.

### 7.3 Same variable spelling and hashes do not create one pool

Both the shared state and this source-specific state use `MDF_TotalStanceDamage`, `MDF_HitStanceDamage`, and the same addition hashes. Their installers, containing definitions, reset predicates and readers differ. One path names the shared modifier in a copy; the other passes the current source's value explicitly.

The reusable evidence identity must therefore retain target, supplying modifier/source context, interval and invocation. This is a semantic distinction, not a claim to have recovered the native memory layout or a proposal to change the local IR.

For two successive qualifying local windows with admitted event values 10 then 20 and no other mutation, the inspected zero-before-name-matched-hit/add/read recipe supplies 10 then 20, not 10 then 30. The independent shared total might describe a larger interval; it is not automatically the explicit source's input. These are deliberately supplied callback values, not newly extracted nominal Skill11 toughness numbers.

The final-use name/source/mode predicates also prevent interpreting this as an unconditional reaction to every attack by any ally. The shared template does not explicitly author the originating `CustomName` on its generated request; exact native custom-name propagation and arbitrary recursion policies remain outside this bounded claim.

## 8. Ordinary crossing model and required controls

Retain the preceding P2-attributed ordinary model: with no force override, no intervening recovery/lock, a valid ordinary bar and nonlethal matching hits, the crossing hit and its unused toughness are excluded; later eligible hit inputs are included. Write `r` for initial remaining toughness and `q_i` for each correctly resolved hit input in one consistent unit. If `k` is the first hit whose cumulative reduction reaches r, the ordinary model is:

```text
Q = sum(q_i for i > k)
```

This summarizes an observable allocation rule under those assumptions. It is not raw proof of native event ordering or permission to set every hit's q_i from an HP-damage split. Already-broken targets start with all otherwise eligible hit inputs; a never-broken target has none in the unforced path.

| Controlled ordinary setup | Model prediction |
| --- | --- |
| q=[10,10,10], r=15 | k=2; Q=10, not 15/20/30 |
| q=[10,10,10], r=20 | Exact zero on hit2 still leaves only hit3; Q=10 |
| q=[10,10,10], r=30 | Break only on final hit; Q=0 |
| q=[10,10,10], already broken | Q=30 |
| q=[10,10,10], r>30 | No break; Q=0 |
| Eligible accounting but no applicable damage-producing source | Accumulation alone is not a Super Break request |
| Different target histories, r_A=15 and B already broken, same supplied q sequence | Q_A=10 and Q_B=30; do not use a merged target total |
| A subsequent independently reset accounting window | It does not inherit the previous Q merely because the target remains broken |

All entries are model/source-conditional predictions, not executed tests. The final row depends on the relevant reset event actually occurring, not on a fabricated universal action boundary.

The preceding Sam carrier read records four primary requests with HitSplitRatio .15 followed by one .4 request. Its previously quoted total45/displayed-unit example and q=[6.75,6.75,6.75,6.75,18] remain public-example inputs, not a solved loader-to-1659254037 mapping. At r=25 that model yields Q=18, not45-25=20. Different weakness, efficiency, source or split rules require independently resolved q_i.

## 9. Crossing eligibility is not ordinary direct-damage sampling

S7's `OnBeingBreak` authors AddModifier(StanceBreakState), then RemoveModifier(MonsterAllDamageReduce). S6 shows that the former carries `Break` and has an `OnCreate -> TriggerBreak(Caster)` request; the latter independently contributes `AllDamageReduce=.1`.

Thus presence of Break, presence/withdrawal of the reduction contribution, and the damage context's sampled reduction are different facts. Installation can have its own callbacks; serialized task order does not establish that all nested work is synchronously complete before the next task, or when the current ordinary hit fixes its damage operands.

P1 describes a 0.9 factor before break and 1 afterward, but does not explicitly resolve the ordinary hit that crosses the threshold. A separate initial-Break damage request is not that ordinary hit. This record does not assign a new conclusive 0.9 or1 outcome to either request from the stage accumulator's eligibility predicate.

A clean missing discriminator is the *same ordinary hit* with unchanged offensive/defensive inputs and crit outcome, differing only in remaining toughness so that it is noncrossing versus crossing. Identify its damage separately from initial Break, later hits and Super Break; do not compare a summed UI total. An adequately scoped original report can settle the observable rule without a native engine dump. No such directly discriminating report was newly obtained through this continuation's GitHub source checks.

## 10. Claim accounting and precise residuals

| Claim | Current basis | Remaining limitation |
| --- | --- | --- |
| Shared installation, eligible ParamValue2 addition and two literal resets | S1/S8, source-facing confirmed | Native event production, alias/default context internals and interleaving |
| Negative-copy versus explicit-input selection and zero guard | Complete S2 bodies, source-facing confirmed | Omitted-argument setup in callers that do not serialize the input |
| Read is not an explicitly authored consume operation | Complete S2 bodies | Resulting nested event side effects are not excluded |
| Selected Sam source thresholds and mutually exclusive coefficient branches | S3/S9 | No newly read numeric point row; missing StanceValue bridge remains |
| Independent Rappa parent/child, named-hit reset and explicit-input reader | S4/S5/S2, new source-facing contrast | Per-native-hit grouping and additional callback/context propagation |
| Same names/hashes are insufficient pool identity | Different containing definitions, reset/use chains and named-source copy | Not a recovered universal native scope resolver |
| Ordinary crossing-hit and unused-portion exclusion | Carried-forward P2 interpretation, source-compatible | Not new testing or a raw-only proof of event visibility |
| Ordinary crossing-hit direct-damage reduction sample | Open | Requires a properly separated observed result or exact authoritative evaluation sequence |
| Whole FG-01 or local runtime correctness | Not claimed | F02/F03/W04/W06 remain active; no new C/D/E |

Additional specific residuals are ParamValue2's complete numerical construction; native template defaults for omitted inputs; read/reset ordering across multiple enablers and nested requests; and the observable native-hit grouping needed to apply each source's window. Do not expand these into a universal scheduler census or erase the supported explicit-input branch.

Navigation checks for OnBeforeBeingStanceDamage found the new ordinary contrast; deferred GridFight results were not admitted. A default-branch StanceValue/DefaultValue search supplied no bridge and is not pin-wide absence proof. A narrow KQM SRL issue search supplied no additional toughness report; it is not proof that no public report exists. The P1 page was actually reread, not its uninspected linked Google document or video evidence.

## 11. Publication and continuation boundary

Persist this main record and link the current result from the integrated review. Preserve its original execution card and historical review beneath the dated follow-through. A PR checkpoint records actual commits, diffs and readbacks; no publication is inferred from an uncommitted conversation answer.

Validation is manual GitHub source/document reading, exact-pin/blob and predicate/owner/expression checks, labeled model arithmetic, and Git diff/head/Draft checks. No game, simulator, Direct, test suite or workflow is intentionally run for this investigation. Runtime, lowering, IR, tests, CI, broad W checkboxes, mode scope and the TBGD pin remain unchanged. Source facts and external interpretations are not local-runtime E.

**Next within FG-01:** prioritize directly discriminating evidence for the ordinary crossing hit's reduction sample, or a concrete bridge for ParamValue2 / omitted template input. Reuse the now-persisted two source/window contracts; do not start another identical accumulator scan or another character kit. Other foundation gaps remain queued rather than automatically dispatched. A native-body absence does not prohibit a credible public behavior result, and a missing local handler is not a research gate.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Level/Level_BattleCommonRule_Ability.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Sam_00_Ability.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Rappa_00_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Rappa_00_Config.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_Common_Ability.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/Level/StageCommonTemplate.json
[S9]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Sam_00_Config.json
[P1]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/docs/combat-mechanics/damage/damage-formula.md
[P2]: https://www.taptap.cn/moment/552526368189974727
[REVIEW]: foundational_mechanics_gap_coverage_review_v1.md
[R0]: battle_execution_language_core_v1.md
[R2]: weakness_toughness_break_vertical_slice_v1.md
[F01]: general_parameter_effective_property_semantics_v1.md
[F02]: general_damage_formula_and_input_layers_v1.md
[F03]: general_weakness_toughness_break_super_break_v1.md
