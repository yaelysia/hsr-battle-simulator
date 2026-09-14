# Healing + Modifier Lifecycle Core v1

## 1. Metadata, authority and bounded result

- Thread: `R3-HEALING-MODIFIER-LIFECYCLE-V1`; PR #8; research date: 2026-09-09.
- Research baseline: `4b22bd24ddfa51a8676a6c74d8ebfcd798e5e0d7`; actual PR head matched at startup. The PR remains a Draft research ledger.
- Raw authority: `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. Every raw reference below is pinned to that revision.
- Maturity: `manually_confirmed` for the identified producers, bindings, calls, callbacks and literal operands. Confidence: high for those inspected surfaces; no confidence claim for unavailable runtime mathematics.
- Authority class: `battle_authoritative` for retained battle inputs/operations, `mixed_requires_filter` for containing files; scope verdict `include` for those edges, `mixed` at file level.
- Result: **bounded Healing + Modifier Lifecycle Core v1 complete**. This is not `W05 mechanism_closed`, `W09 mechanism_closed`, an opcode census, or runtime numerical reproduction.
- Runtime/business/lowering/IR/test changes: **none**. Fast, Direct, executable simulator tests and numerical reproduction: **not performed / not claimed**.
- Publication, final head and validation evidence belong to the actual PR commit/checkpoint; this document does not predict its own commit SHA.

Authority is BATTLE_SCOPE/evidence contract -> current worklist/inventory plus corrected detailed evidence -> historical comments. The current execution card expressly reuses [R0], [R1], [R2] and [March]; stale broad checkboxes do not invalidate their narrow closures. None of those records is rewritten here.

## 2. Semantic model and sample selection

The question is how an ordinary selected-ally healing request obtains its inputs, installs a periodic state, and exposes reapplication, phase, snapshot, dispel and removal contracts. Gameplay knowledge supplies this navigation/completeness question, not a formula or default.

The primary is Natasha Skill02. Gallagher Skill02 is the independent heal discriminator: a different ordinary actor, explicit inherent-target transfer and a flat-operand-only HealHP layout, rather than another identically shaped HP-scaling heal. The core lifecycle comparison uses **Natasha HOT, March main Shield and Natasha-owned shared HealRatioUp**. The third sample is already reached by the required healing-property investigation, so an additional Aventurine/stacking-policy scan is unnecessary. R2 Fire Burn supplies the periodic-damage contrast; mature Luka evidence supplies a narrowly reread snapshot-property contrast.

Reuse [R0] P1/P3/P5-P9 for parameter and environment language, E1/E2/E3/E6 for contextual entities, D1/D2/D3/D7 for entry/phase/callbacks, and O1/O2/O4/O17 for modifier/heal/property operations. A quoted selector, event, stacking token or formula token below remains a data-side contract, not its native implementation.

## 3. Primary identity, entry and invocation

```text
AvatarConfig[AvatarID=1105, Release=true]
  JsonPath = Config/ConfigCharacter/Avatar/Avatar_Natasha_00_Config.json
  SkillList contains 110502
 -> AvatarSkillConfig[SkillID=110502, Level=1]
    SkillTriggerKey=Skill02
 -> CharacterConfig.SkillList[Name=Skill02]
    SkillType=Skill; UseType=SelectEntity; TargetInfo.TargetType=FriendSelect
    EntryAbility=Avatar_Natasha_00_Skill02_Phase01
 -> Phase01.OnStart[0]: TriggerAbility(Caster, Skill02_Phase02, IsSkillPerform=true)
 -> Phase02.TargetInfo.TargetType=SkillTargetEntityList
 -> HealHP / AddModifier target AbilityTargetEntity
```

This is an ordinary released Avatar chain, not an identification based on the numeric SkillID alone. The invocation performer is Natasha; the ability target is the selected ally, which can differ from the performer. `AlwaysDoAutoLock=true` and `AutoLockType=LowHP` are authored selection inputs, not a recovered legal-target or lowest-HP evaluator. Phase01's `ByIsTurnActionEntity` branch chooses self/other camera abilities, not different numerical heal formulas. [N1], [N2], [N3], [N4]

## 4. HEAL-01 — Five distinct Skill02 producer/consumer edges

Primary row `AvatarSkillConfig[110502,Level=1]` has `ParamList=[0.07,0.048,2,70,48]`; the reread Level2 row is `[0.074375,0.051,2,112,76.8]`. Both have `SkillTriggerKey=Skill02`. `SimpleParamList` is a separate field and is not substituted for ParamList. These two rows are samples, not a claim to have audited all levels. [N2]

| Zero-based index | Lv1 raw value | Lv2 raw value | CharacterConfig hash / ReadInfo | Exact retained consumer and role |
| --- | --- | --- | --- | --- |
| 0 | 0.07 | 0.074375 | `-1544075911`, SkillParam(Skill02,0) | Phase02 direct HealHP.HealPercentage; percentage operand, not a complete equation. |
| 1 | 0.048 | 0.051 | `-754957899`, SkillParam(Skill02,1) | AddModifier.DynamicValues.MDF_ShowValue1 -> HOT environment -> periodic HealHP.HealPercentage, hash `1733325153`. |
| 2 | 2 | 2 | `-1019407308`, SkillParam(Skill02,2) | AddModifier.LifeTime expression, together with the explicitly written trace working value. |
| 3 | 70 | 112 | `-203632277`, SkillParam(Skill02,3) | Phase02 direct HealHP.ModifyValue; flat-valued input slot, not proof of its final arithmetic placement. |
| 4 | 48 | 76.8 | `-1192384503`, SkillParam(Skill02,4) | AddModifier.DynamicValues.MDF_ShowValue2 -> HOT environment -> periodic HealHP.ModifyValue, hash `2136609680`. |

All five have consumers; none receives a meaning merely from its position. In particular, **MDF_ShowValue1/2 are not display-only in this chain**: retain their named application inputs and their destination HealHP hash reads. This uses the paired named-transfer/consumer environment contract from [R0] P9, not a new global hash algorithm or a claim that equal values identify producers. The native name encoding, lookup fallback and environment inheritance implementation remain outside this closure. [N3], [N4]

## 5. HEAL-02 — Complete direct HealHP request, not final arithmetic

The entire direct operation at `AbilityList[Name=Avatar_Natasha_00_Skill02_Phase02].OnStart[4]` is: [N4]

```json
{
  "$type": "RPG.GameCore.HealHP",
  "TargetType": {
    "$type": "RPG.GameCore.TargetAlias",
    "Alias": "AbilityTargetEntity"
  },
  "FormulaType": "HealByHealerMaxHP",
  "HealPercentage": {
    "IsDynamic": true,
    "PostfixExpr": {
      "OpCodes": "AQAR",
      "FixedValues": [],
      "DynamicHashes": [-1544075911]
    }
  },
  "ModifyValue": {
    "IsDynamic": true,
    "PostfixExpr": {
      "OpCodes": "AQAR",
      "FixedValues": [],
      "DynamicHashes": [-203632277]
    }
  }
}
```

`HealByHealerMaxHP` explicitly selects a formula family. Neither this occurrence nor the retained data-side sources expose the generic HealHP evaluator. Do **not** expand the name into `healerMaxHP * percentage + flat`, select a property snapshot, compose healing bonuses, round, or clamp without another authoritative operator.

The request contains no explicit cap, overflow/overheal handler, source/snapshot selector, HealPercentage bound, SPHitRatio, or DisplayData. These are **occurrence-scoped omissions**, not explicit false/zero values and not proof that the engine lacks defaults or caps. Final HP arithmetic, current/max-HP update, clamp, overflow and numerical event payloads are `engine_consumer_unavailable`.

The local authored sequence is trace-gated DispelStatus at OnStart[3], direct HealHP at [4], lifetime working-value branch at [5], HOT installation at [6], and ModifySPNew(Caster,AddRatio=1) at [8]. A later random Retarget only selects a ReceiveHealing voice line. It is not the healing target algorithm. `ModifySPNew` is a W08 entry edge; no resource award is derived here. Serialization identifies these call sites, not completion/atomicity of the hidden HP commit relative to callbacks. [N4]

## 6. HEAL-03 — Independent ordinary heal layout: Gallagher

`AvatarConfig[1301]` points to `Avatar_Gallagher_00_Config.json` and includes ordinary Skill130102. `AvatarSkillConfig[130102,Level=1]` has `SkillTriggerKey=Skill02`, `ParamList=[200]`; CharacterConfig hash `2082775117` explicitly binds SkillParam(Skill02,0). The entry is FriendSelect -> `Avatar_Gallagher_00_Skill02_Phase01`. Its Phase02 call passes `AbilityInherentTargetType=AbilityTargetEntity` on Caster, and the callee declares `InherentTargetEntity`. [N1], [N2], [C1], [C2]

The complete HealHP at Gallagher Phase02.OnStart[4] has only four top-level keys:

```json
{
  "$type": "RPG.GameCore.HealHP",
  "TargetType": {
    "$type": "RPG.GameCore.TargetAlias",
    "Alias": "AbilityTargetEntity"
  },
  "SPHitRatio": {"IsDynamic": false, "FixedValue": {"Value": 1}},
  "ModifyValue": {
    "IsDynamic": true,
    "PostfixExpr": {
      "OpCodes": "AQAR",
      "FixedValues": [],
      "DynamicHashes": [2082775117]
    }
  }
}
```

This closes an independent raw **ModifyValue=200 input**, not a claim that final healing equals 200. FormulaType and HealPercentage are omitted, not explicitly a `FixedValue` formula or a zero percentage. Conversely, SPHitRatio is explicit here and must not be added to Natasha's request. The preceding rank-gated dispel/status branch is a routed W09 entry; its full status-resistance mechanism is not needed for this discriminator. [C2]

## 7. MOD-01 / HEAL-04 — HOT installation and periodic execution

Natasha Phase02.OnStart[6] installs `MAvatar_Natasha_00_HOT_HPByMaxHP` on AbilityTargetEntity, with the authored LifeTime expression and the two named inputs in section 4. Its definition is **GlobalModifiers in the same Avatar ability file**, not inferred from the global-sounding name. The selected ally becomes the modifier holder; the originating caster/invocation remains separately represented. Native caster-to-snapshot substitution is not decoded. [N4]

The **complete set of definition keys** is `LifeStepMoment`, `UseSnapshotEntity`, `_CallbackList`, `Stacking`, `DynamicValues`. The definition says:

```text
LifeStepMoment = ModifierPhase1End
UseSnapshotEntity = true
Stacking = ReplaceByCaster
DynamicValues.Floats[1733325153,2136609680] each declare ReadInfo(Type=None,Index=0)
_CallbackList has exactly one local event: OnPhase1
  ByCompareHP(ModifierOwnerEntity, Greater, fixed 0)
    SuccessTaskList[0] = TriggerEffect(ModifierOwnerEntity, heal effect)
    SuccessTaskList[1] = HealHP(
      ModifierOwnerEntity,
      FormulaType=HealByHealerMaxHP,
      HealPercentage=AQAR/[1733325153],
      ModifyValue=AQAR/[2136609680],
      DisplayData={FixedPosition:false})
```

The condition is a **holder HP > 0 query at the authored callback**, not a comparison against full HP and not a recovered revive/clamp rule. DisplayData and the heal effect do not produce the heal number. The HOT callback reads the destination working inputs; it does not reread Skill02 index0 or index3 as its periodic inputs. `Type=None` declares a working slot, not a default value of zero. [N4]

No OnCreate, OnStack or OnDestroy event, MaxLayer, LayerAddWhenStack, BehaviorFlagList, RemoveWhenCasterDead or KeepOnDeath flag is serialized in this HOT definition. Do not invent local callbacks, interpret omissions as no engine teardown, or derive generic caster-death persistence. Expiry/other removal -> native destruction is a named boundary, not a missing heal producer.

## 8. MOD-02 / MOD-03 — Authored lifetime versus native ticking

`AvatarSkillTreeConfig[PointID=1105103,Level=1,AvatarID=1105]` has PointTriggerKey=PointB3 and ParamList=[1]. CharacterConfig hash `2117344201` binds SkillTreeParam(PointB3,0). The Phase02 branch writes `SkillTree_LifeTime` from that input when active, and explicit zero otherwise; Phase02 declares its working hash `-1087299341` with Type=None. [N3], [N4], [N5]

```text
LifeTime.PostfixExpr:
  OpCodes = AQABAQIR
  FixedValues = []
  DynamicHashes = [-1019407308,-1087299341]
authored input = SkillParam(Skill02,2) + SkillTree_LifeTime
Lv1 / Lv2 samples: 2 without PointB3; 3 with PointB3
```

The addition interpretation reuses [March]'s already-confirmed small postfix operator mapping. This is **input arithmetic**, not heal arithmetic or a count of a particular player's turns. PointB3's empty table AbilityName does not make the trace absent: the actual skill predicate consumes its trigger and its typed parameter.

`LifeStepMoment=ModifierPhase1End` and `OnPhase1` are distinct source fields. Their presence does not recover which entity's round drives the counter, when the first tick occurs, the decrement amount, refresh/reset behavior, or expiry ordering. PointB3 increases the supplied duration; no SetModifierValue-style mutation of an already-existing HOT timer is authored in this inspected Skill02 branch. Reapplication passes a new duration and the ReplaceByCaster policy; whether native replacement preserves or resets an old counter remains unknown.

The adjacent **Rank02 HOT is a different modifier**; its Skill03 installation explicitly has `LifeStepImmediately=true`. That field is not present on the primary Skill02 installation and is not copied into it. The Rank02 chain is not expanded here. [N4]

## 9. MOD-04 to MOD-08 — Three ordinary lifecycle samples

Each consequence is a configured request/hook, not a verified native transition. No additional sample was collected merely to obtain a Merge token.

| Sample and ordinary installer | Explicit lifecycle/stacking | Authored callbacks and effects | What is not supplied by this sample |
| --- | --- | --- | --- |
| Natasha Skill02 -> `MAvatar_Natasha_00_HOT_HPByMaxHP` | ReplaceByCaster; LifeTime 2 or 3 in the chosen rows; ModifierPhase1End; snapshot true | Only OnPhase1; HP>0 gate -> periodic HealHP(holder) | Local OnStack/OnDestroy are absent; native allocation, timer replacement, same/different-caster coexistence and expiry policy unknown. |
| March Skill02 -> `MAvatar_March7th_00_BPSkill_Shield` | Replace; supplied lifetime; snapshot true; Shield flag | OnCreate resilience/effect setup; OnStack InitShield(holder) and AggroAddedRatio input; OnDestroy RemoveShield(holder) and resilience reset; OnPhase1 conditional Rank06 heal | Hidden ShieldByCasterDefence, snapshot capture, depletion trigger and old/new callback order remain frozen. No lifetime stepping default is added to this definition. |
| Natasha PointB2 -> `M_SkillTree_HealRatioUp` | ReplaceByCaster; no LifeTime on its inspected install; no local LifeStepMoment or snapshot flag | Only OnStack -> StackProperty(holder,HealRatioBase,input 0.1) | Omitted lifetime does not prove permanent duration; omitted snapshot flag does not prove universally live reads; property rollback/aggregation and reapplication algorithm unknown. |

These are three distinct ordinary-reachable modifiers and two explicit policy tokens, with both a periodic and a property-producing non-Shield sample. March's numeric/dispellability discovery is **reused**, not reopened; its raw main-shield definition was reread solely to constrain lifecycle comparison. [N4], [S1], [M1], [March]

### Replace, ReplaceByCaster, reapply, refresh and extend

- **Source-facing closed:** the two literal policy tokens, application targets, supplied values/durations, and callbacks shown above.
- **Source-facing partial:** a reapply reaches the same named modifier definition and carries the caller's caster context. Neither token alone specifies matching keys, same-caster timer handling, different-caster coexistence, layer limits, or old-instance visibility.
- **Engine boundary:** old OnDestroy versus new OnCreate/OnStack order, property rollback, old/new snapshot switching, timer reset/retention and effect aggregation. A policy name is not a recovered replacement algorithm.
- **Refresh/extend:** PointB3 supplies a longer lifetime input. No generic in-place refresh/extend operation is established from these samples. Do not equate a longer new application with extending the remaining duration of an existing instance.
- **Merge:** not needed and not sampled as an ordinary lifecycle policy in this slice. This is not absence evidence for Merge in TBGD.

## 10. MOD-09 — Snapshot routing and current-property queries

Natasha HOT and March Shield explicitly request `UseSnapshotEntity=true`. The ordinary Luka contrast already retained by [March] was reread at `GlobalModifiers.MAvatar_Luka_DOT_Tear.OnCreate`: `SetDynamicValueByProperty(SnapshotPropertyEntity,Attack -> MDF_CasterAttack)` is separate from `SetDynamicValueByProperty(ModifierOwnerEntity,MaxHP -> MDF_TargetMaxHP)`. Both coexist under a snapshot-requesting modifier. This demonstrates selective entity/property routing, not freezing every value seen by every callback. No Luka damage formula or timer semantics are expanded. [N4], [M1], [L1], [March]

Natasha also has an explicit, actor-local snapshot callback edge. Ordinary SkillP01 installs `Fuka_Beginner_PassiveSkill_Buff_1` on Caster. Its OnSnapshotCreate installs the literally named `Fuka_Beginner_PassiveSkill_Buff_1_ForSnapshitEntity` on event ParamEntity, injecting a threshold value. The callee has its own OnBeforeDealHeal callback. The spelling and the Fuka prefix do not replace the actual Natasha owner chain. [N3], [N4]

This extra edge proves an authored response to a snapshot-creation event, **not** the native event producer, event-ParamEntity construction, capture time, complete inherited parameters or automatic installation on every HOT snapshot. The auxiliary callback still references the original passive's heal-ratio hash; its native cross-context lookup is not recovered here. [N4]

The inspected GameCoreConstValue exposes `SnapshotEntityInheritBlackList`, including healing-related property names, and callback-recall configuration. Their existence does not reveal operational blacklist semantics or a final heal evaluator. The previously documented SnapshotPropertyEntity/GetSnapshot routing remains as in [March]/[R0], without a new alias-algorithm search. [G1]

Natasha HOT's holder HP query and passive's event ParamEntity HP-ratio query are **explicit contextual reads**, distinct from copied numeric operands. No explicit `UseSnapshotEntity=false` heal sample was needed. Absence of that flag on direct HealHP is not proof that all of its properties are live. Capture, refresh, inheritance, default lookup and reentrancy remain engine-owned.

## 11. MOD-10 / MOD-11 — Dispelling is three separate layers

| Layer | Actual ordinary evidence | Limit |
| --- | --- | --- |
| Dispelling eligibility metadata | AvatarStatusConfig[10010011]: main March Shield, StatusType Buff, CanDispel=true. AvatarStatusConfig[10011055]: primary Natasha HOT, StatusType Buff, CanDispel=true. | Eligibility metadata is not an operation and does not assert that Natasha will remove either Buff. |
| Active dispel request | Natasha Phase02 PointB1 branch -> DispelStatus(AbilityTargetEntity,Numbers=AQAR/[-2124210825],Order=LastAdded). Point1105101 supplies ParamList[0]=1 via SkillTreeParam(PointB1,0). | Count input 1 and ordering token are closed; actual removed status, default status filter, resistance/immunity and tie-break resolution are not. |
| Removal/destruction | A named RemoveModifier is a different operation; R2's StanceBreakState.OnDestroy removes its named effect modifier. March main Shield has OnDestroy -> RemoveShield. | No generic equivalence DispelStatus=RemoveModifier=RemoveShield; native selection and teardown connect these surfaces. |

Natasha's inspected DispelStatus occurrence does **not** serialize a StatusType, BehaviorFlags or OnlyCanDispel filter. Do not infer a complete debuff-only resolver or guarantee which existing status is removed. The `LastAdded` token is an ordering input, not a universal same-time tie-break rule. [N3], [N4], [N5], [S2], [M1], [R2]

For the HOT, the status metadata closes dispellability, but its local definition has no OnDestroy tasks. The appropriate end edge is eligibility/removal request -> **native removal/expiry/destruction boundary**, not an invented cleanup callback. March's authored OnDestroy can be cited as a different concrete teardown hook, not copied to HOT.

## 12. MOD-12 — Periodic effect specialization: heal versus damage

This section **reuses [R2] WTB-09**, rather than reopening Fire Break, Super Break or a DoT census. Its ordinary Fire template installs `MCommon_Element_Burn` on the break target with LifeTime=2 and a named percentage input. The modifier has ModifierPhase1End, UseSnapshotEntity=true and ReplaceByCaster. OnStack reads its layer; OnPhase1 emits DamageByAttackProperty(holder,Fire,FormulaType=ByBreakDamage,AttackType=DOT,FinalFormulaType=ByPureDamage). [R2]

```text
modifier lifecycle surface
  Natasha HOT:     OnPhase1 -> HP>0 predicate -> HealHP(holder)
  element Burn:   OnPhase1 -> break-derived DOT damage request(holder)
```

Common lifecycle metadata does not identify a formula, source property, snapshot algorithm or timing counter. Burn's MaxLayer=1 and LayerAddWhenStack=1 are not copied into Natasha HOT. `MCommon_Element_Burn`, `MCommon_DOT_Burn` and `StanceBreakState` remain different states. The Burn OnCustomEvent extra-trigger producer remains unclosed in R2 and is not promoted by this comparison. [R2]

## 13. HEAL-05 — Healing-property input and heal-context mutation

### Persistent property contribution

```text
AvatarSkillTreeConfig[1105102,1], AvatarID1105, PointB2, ParamList[0]=0.1
  AbilityName=Avatar_Natasha_SkillTree02
 -> CharacterConfig hash103268114 = SkillTreeParam(PointB2,0)
 -> named trace ability: AddModifier(Caster,M_SkillTree_HealRatioUp)
    DynamicValues.MDF_PropertyValue = AQAR/[103268114]
 -> GlobalModifier_Avatar.ModifierMap.M_SkillTree_HealRatioUp
    OnStack -> StackProperty(ModifierOwnerEntity,HealRatioBase,AQAR/[2128130574])
```

The ordinary owner, input value, named transfer, ReplaceByCaster policy and property contribution are closed. This is not merely discovering a healing property name. No exported consumer in the inspected sources composes HealRatioBase with Natasha's heal formula, so the final composition is `engine_consumer_unavailable`. [N3], [N4], [N5], [S1]

### Per-heal context contribution

`AvatarSkillConfig[110504,Level=1]` has SkillTriggerKey=SkillP01 and ParamList=[0.3,0.25]. CharacterConfig binds index0 to `-889510027` and index1 to `-1134214845`. The ordinary passive entry installs `Fuka_Beginner_PassiveSkill_Buff_1` on Caster. Its OnBeforeDealHeal tests `ByCompareHPRatio(ParamEntity,LessEqual,0.3)` and, on success, executes `ModifyHealData.Healer_HealRatio` from the 0.25 input. [N2], [N3], [N4]

This is an actual heal-context mutation, distinct from the PointB2 entity property contribution and from HOT's own input values. Do not silently combine 0.1 and 0.25 or turn them into a final multiplier. Native event argument construction, HP sampling, operation algebra and callback combination are not exported. Preserve the passive's `MuteDotCasterCallBack` flag without extrapolating its effect to all DoT/HOT callbacks.

## 14. Final heal, caps and overheal: inspected endpoints and stop boundary

The active cap/overheal check was restricted to the two direct occurrences, Natasha's full primary HOT definition and connected heal callbacks, plus the already-indexed GameCoreConstValue surface. The inspected requests do not serialize a numerical heal cap or overflow action. The HOT checks holder HP>0; the passive checks an event entity's HP ratio against a skill input. Neither is an implementation of currentHP/maxHP clamping. [N4], [C2]

GameCoreConstValue's healing-named entries encountered here are property names in the snapshot list and OnBeforeDealHeal/OnAfterDealHeal entries in a recall-control list, not a field-to-HealHP cap expression or an overheal resolver. No HealRatio bounds/composition operator was recovered on these inspected surfaces. This is not a keyword-based proof that no heal-related caps or overflow mechanics exist elsewhere. [G1]

**HealHP request is source-facing; final currentHP/maxHP clamp and overheal semantics are engine-owned.** The pinned-source index's established release-data/engine boundary is reused; no generic GameCore search, standard public healing formula or purported full-health axiom is substituted. No indispensable, identified exported edge in the primary numeric/HOT chain is left untraced.

## 15. Evidence partition

`Closed` below means the stated source-facing scope only. `Partial` is not promoted to a native algorithm. No new primary producer export gap is declared: table transport failures were resolved with exact blobs.

| Layer | Classification | Supported scope / remaining boundary |
| --- | --- | --- |
| Heal numeric producer | Closed | Natasha Skill110502 Lv1/Lv2 indices0..4, and Gallagher Skill130102 Lv1 index0; typed actor-specific bindings. |
| HealHP operation | Closed | Full direct occurrences and primary periodic callback, explicit targets and operands. |
| Scaling formula family | Closed token / engine boundary | Natasha HealByHealerMaxHP; Gallagher omitted FormulaType remains unknown. |
| Flat heal operand | Closed input | ModifyValue receives70/112 or48/76.8 in Natasha samples and200 in Gallagher; final placement not recovered. |
| Healing-property bonus | Closed input / partial composition | PointB2 -> HealRatioBase; passive -> Healer_HealRatio context. Native composition unknown. |
| Final heal arithmetic | Engine boundary | HealHP body, property selection, bonus algebra, rounding/defaults not exported. |
| Current/max HP clamp | Engine boundary | No cap operand/HP commit body in inspected requests; contextual HP predicates are different. |
| Overheal behavior | Engine boundary | No recovered generic overflow payload, conversion, event or discard rule. |
| HOT install | Closed | Named application, selected holder, duration and two transferred working inputs. |
| Periodic heal | Closed request | OnPhase1 -> holder HP>0 -> HealHP, percentage/flat destination reads. |
| Lifetime input | Closed | Skill index2 plus explicit PointB3 branch; 2 or3 in inspected rows. |
| Lifetime decrement | Engine boundary | Whose phase, first/last tick, decrement, reset and expiry trigger unknown. |
| LifeStepMoment | Closed field / engine boundary | ModifierPhase1End is literal metadata, not reconstructed round accounting. |
| Replace | Closed token / partial reapply | March ordinary main Shield with authored OnStack and OnDestroy hooks; native old/new order unknown. |
| ReplaceByCaster / second policy | Closed token / partial reapply | Natasha HOT and shared HealRatioUp; no inferred caster matching/coexistence algorithm. |
| Refresh / extend | Partial input / engine boundary | Longer authored duration proven; no in-place timer-extension or generic refresh implementation claimed. |
| Snapshot routing | Closed request/route / engine boundary | HOT/Shield flags, Luka snapshot property getter, Natasha OnSnapshotCreate child edge; capture/inheritance unknown. |
| Live reads | Partial contextual-read surface | Holder HP and event-entity HP ratio queried in callbacks; no universal live/snapshot/default getter rule. |
| CanDispel metadata | Closed | March10010011 and Natasha10011055 -> exact modifier names, Buff, true. |
| DispelStatus operation | Closed request / engine boundary | Natasha PointB1 number1, target, LastAdded; selection/default filters/immunity/tie-break unknown. |
| RemoveModifier / OnDestroy | Closed local hooks / engine boundary | Named removal differs from destruction; March OnDestroy cleanup explicit; primary HOT has no local OnDestroy. |
| Periodic DOT contrast | Closed reused scope | R2 Element Burn OnPhase1 damage versus Natasha HOT heal; no merged formula or timing. |
| Universal callback ordering | Engine boundary | Only specific authored calls/callbacks; no OnStack -> OnPhase1 -> OnDestroy global total order. |

Candidate-only/not-promoted entries include interpreting omitted Gallagher FormulaType as a particular default, using snapshot-list property names as a heal-cap formula, an in-place HOT refresh inferred only from ReplaceByCaster, and the R2 Burn extra-trigger producer. The nearby Rank02 LifeStepImmediately is a real field of another installation, not primary HOT evidence. Merge and broad control/immunity rules were not sampled; they are not declared absent.

## 16. Reusable vocabulary and actor-local boundaries

| Reference | Reusable language | Do not generalize |
| --- | --- | --- |
| HEAL-01 | Row -> zero-based typed binding -> independent operand/working input. | SkillParam positions or equal numbers across actors as global identities. |
| HEAL-02 | HealHP target, explicit formula token, dynamic/flat slots; request versus HP evaluator. | One public heal equation or default-filled operand layout. |
| HEAL-03 | A second ordinary HealHP layout with explicit inherent-target transfer and flat input. | Omitted FormulaType/HealPercentage means fixed formula/zero. |
| HEAL-04 | Periodic callback dispatches a target-specific heal using installed numeric inputs. | Every HOT shares these values, predicate, lifetime or formula. |
| HEAL-05 | Persistent healing property versus per-heal context contribution. | An additive/multiplicative final bonus formula. |
| MOD-01 | AddModifier carries name, target, optional duration and named inputs. | Successful application, capture and callback firing automatically known. |
| MOD-02 | Authored lifetime expression and trace-dependent input. | Remaining-timer extension or specific player's turn count. |
| MOD-03 | LifeStepMoment metadata distinct from a phase callback. | Generic counter/decrement implementation. |
| MOD-04 | OnStack is a configured consumer hook where explicitly present. | It always equals first creation or follows destruction. |
| MOD-05 | OnPhase1 specializes to a heal or damage request. | Universal phase cadence, formula or ownership. |
| MOD-06 | OnDestroy may contain explicit cleanup; local omission is preserved. | How expiry/dispel/depletion enters destruction or its total order. |
| MOD-07 | Replace policy token plus concrete Shield lifecycle hooks. | Full instance/snapshot/rollback replacement algorithm. |
| MOD-08 | ReplaceByCaster token on ordinary non-Shield states. | Same/different-caster identity, coexistence or timer reset policy. |
| MOD-09 | Snapshot request and explicit contextual property/event routing. | Capture time, copy-all, live-all or blacklist algorithm. |
| MOD-10 | CanDispel is linked status metadata. | An active dispel occurred or selected this status. |
| MOD-11 | DispelStatus has target, count and ordering operands. | Equivalence to named removal/destruction or recovered resolver. |
| MOD-12 | One lifecycle vocabulary supports different periodic effect operations. | HOT=DoT, skill Burn=element Burn, or one generic periodic formula. |

## 17. Negative knowledge, corrections and routed residuals

No correction to R0/R1/R2/March was needed. Two useful clarifications are retained: the `MDF_ShowValue` names here feed battle consumers, and Natasha HOT has only one local callback event, not a presumed create/stack/destroy skeleton. Its independently linked dispellability is now recorded alongside the already-closed March fact.

Keep these false friends explicit: formula family is not final arithmetic; missing field is not zero/false; HP>0 is not a max-HP cap; a snapshot flag is not copy-all at cast time; Replace is not a callback total order; LifeStepMoment is not a player-round count; CanDispel is not active dispelling; DispelStatus is not RemoveModifier; RemoveShield is not RemoveModifier; periodic HealHP is not DOT damage; the voice-only Retarget is not a random heal target; the Fuka prefix and `ForSnapshitEntity` spelling do not override Natasha's actual ownership.

| Residual | Routing / stopping condition |
| --- | --- |
| HealHP final arithmetic, formula defaults, bonus composition, cap/overheal and numeric result payloads | W05; reopen generic implementation only with a new authoritative source, not renamed keyword searches. |
| Reapply matching, snapshot refresh, timer decrement/destruction, dispel selection/immunity and deeper DoT/control behavior | W09 future child slices; this record supplies the common lifecycle contract, not those algorithms. |
| OnSnapshotCreate auxiliary context lookup and cross-event completion/teardown order | W05/W09 with W10 boundary; no universal dispatcher investigation. |
| Natasha ModifySPNew(Caster,AddRatio=1); Gallagher HealHP.SPHitRatio=1; table SPBase/BPNeed | W08 named entry edges only; no gain/cost/cap conclusions here. |
| Enemy/friend legal-target evaluator and event ParamEntity construction | W11/context boundary, not inferable from selection labels alone. |
| R2 shared StanceValue hash1659254037 injection gap and Fire/Super Break residuals | Leave R2 intact; additional occurrences are not discoveries and do not reopen the gap. |

No new independent consequence requiring a W19+ package was established. The next candidate remains **W08 resource economy**, subject to direction correction after this checkpoint. No W08 or subsequent W09 child slice is executed by this thread.

## 18. Exact-pin replay index

All raw links use the same TBGD pin. Named row selectors and node paths, not transient search-result line offsets, are the durable replay locators. Whole containing files remain mixed and were not promoted wholesale.

| Ref | Exact source | Retained locator / purpose |
| --- | --- | --- |
| N1 | [AvatarConfig][N1] | AvatarID1105 and1301: actual JsonPath, ordinary SkillList and Release ownership. |
| N2 | [AvatarSkillConfig][N2] | (110502,Level1/2) five-slot map; (110504,Level1) passive pair; (130102,Level1) flat heal input. Exact blob `a5416ced941c247d475b2aaa83277b9cdf474dd9`. |
| N3 | [Natasha CharacterConfig][N3] | Skill02/SkillP01 entries; DynamicValues.Floats Skill02 indices0..4, PointB1/B2/B3 and passive bindings. |
| N4 | [Natasha Ability][N4] | Skill02_Phase01/02; GlobalModifiers.MAvatar_Natasha_00_HOT_HPByMaxHP; Avatar_Natasha_SkillTree02; PassiveSkill01 and its two local modifiers. Blob `0dd71d6942e4f8420749c56c8151710dee0bf9f0`. |
| N5 | [AvatarSkillTreeConfig][N5] | Point1105101/2/3 Level1 Avatar1105; parameter, trigger and AbilityName edges. Exact blob `cee634adac569ad417ebedf55f9be67caa05fab8`. |
| S1 | [GlobalModifier_Avatar][S1] | ModifierMap.M_SkillTree_HealRatioUp only: OnStack/HealRatioBase/ReplaceByCaster/working input. |
| S2 | [AvatarStatusConfig][S2] | Status10010011 main Shield and10011055 primary HOT; exact ModifierName, Buff, CanDispel=true. Blob `2779ce6cff1f2411e2ae400b98eef2a6f0a4c775`. |
| C1 | [Gallagher CharacterConfig][C1] | Skill02 FriendSelect entry, SkillParam(Skill02,0) hash2082775117. |
| C2 | [Gallagher Ability][C2] | Skill02_Phase01 explicit inherent-target transfer; Skill02_Phase02.OnStart[4] full HealHP. Blob `9c29a5776ba33334439d3b38e6988098a2925f85`. |
| M1 | [March Ability][M1] | Only the ordinary main-shield install and GlobalModifiers.MAvatar_March7th_00_BPSkill_Shield lifecycle. Blob `b9b4e3705a73cb691306d7e68912a7b33e597e94`. |
| L1 | [Luka Ability][L1] | Mature snapshot contrast: GlobalModifiers.MAvatar_Luka_DOT_Tear.OnCreate holder MaxHP versus SnapshotPropertyEntity Attack reads. No full DoT closure. |
| G1 | [GameCoreConstValue][G1] | SnapshotEntityInheritBlackList and ForbidRecallModifierEventList; inspected endpoint/boundary, not a recovered heal formula or cap. |

Large AvatarSkillConfig/AvatarSkillTreeConfig Contents responses returned empty content, and direct raw/GitHub URL fetch of the former returned HTTP400. Both tables were actually read through the exact Git blob endpoints above; no empty/missing-table conclusion was drawn. Blob lookup is transport recovery, not a second numeric authority.

Document validation checks structure, reference definitions, fenced JSON, table columns, literal input preservation and patch application. It is not runtime testing or an engine-formula proof. Final PR checkpoint records the actual validation results and head.

[R0]: battle_execution_language_core_v1.md
[R1]: ordinary_damage_vertical_slice_v1.md
[R2]: weakness_toughness_break_vertical_slice_v1.md
[March]: ../characters/march_7th_preservation_skill02_shield.md
[N1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarConfig.json
[N2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[N3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Natasha_00_Config.json
[N4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Natasha_00_Ability.json
[N5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillTreeConfig.json
[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Avatar.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarStatusConfig.json
[C1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Gallagher_00_Config.json
[C2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gallagher_00_Ability.json
[M1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
[L1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Luka_00_Ability.json
[G1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
