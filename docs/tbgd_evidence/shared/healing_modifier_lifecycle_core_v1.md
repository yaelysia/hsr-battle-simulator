# Healing + Modifier Lifecycle Core v1

## 1. Metadata, authority and current result

- Original raw audit: `R3-HEALING-MODIFIER-LIFECYCLE-V1`, 2026-09-09, research baseline `4b22bd24ddfa51a8676a6c74d8ebfcd798e5e0d7`.
- Public-model reconciliation: **2026-09-23**, evidence parent `61541a5c692314bbd33e5ac835b12da0044dd8ce`.
- Raw authority: `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.
- PR #8 remains Draft / docs/evidence-only. No runtime, lowering, IR, tests, CI or pin changes.
- Original source findings remain `manually_confirmed`; the selected equations and recipient-turn-start interpretation below are now **cross-validated with public gameplay evidence**, not recovered native implementation bodies.
- No simulator, Direct or gameplay test was run for this reconciliation. Numerical examples are predictions; externally reported tests are separately attributed. No new local runtime E.

The [public mechanics reconciliation][Public] supersedes the former blanket rule that no usable heal equation, flat-heal interpretation or selected turn semantics could be accepted until GameCore implementation was available. Missing native code and unknown observable behavior are different claims.

The [complete original raw audit at the parent][Original] preserves all earlier literal observations and the old interpretations for review. This revised entry keeps the source chains, field omissions and meaningful limits, while correcting overbroad arithmetic/timing uncertainty. It does not declare all W05/W09 mechanics closed.

## 2. Gameplay model and sample selection

Natasha's selected-ally Skill02 produces a direct heal and installs a periodic heal. Public descriptions specify Natasha's maximum HP as the scaling stat and the healed ally's turn starts as the periodic event. Gallagher provides a discriminator: his Skill has a flat base rather than an HP/ATK/DEF-scaled base. March's shield remains the lifecycle contrast. [P1] [P2] [P3]

These public models direct the raw investigation toward separate coefficient/flat-value bindings, caster versus recipient, installed working values, callback identity, duration and conditional healing bonuses. Reuse [R0] for parameter/entity/dispatch vocabulary, [R2] for Fire Break Burn and [March] for Shield. A publicly explained operation need not remain semantically unknown merely because its native implementation is unexported.

## 3. Primary identity, entry and invocation

```text
AvatarConfig[AvatarID=1105, Release=true]
  JsonPath = Config/ConfigCharacter/Avatar/Avatar_Natasha_00_Config.json
  SkillList contains 110502
 -> AvatarSkillConfig[SkillID=110502, Level]
    SkillTriggerKey=Skill02
 -> CharacterConfig.SkillList[Name=Skill02]
    SkillType=Skill; UseType=SelectEntity; TargetInfo.TargetType=FriendSelect
    EntryAbility=Avatar_Natasha_00_Skill02_Phase01
 -> Phase01.OnStart[0]: TriggerAbility(Caster, Skill02_Phase02, IsSkillPerform=true)
 -> Phase02.TargetInfo.TargetType=SkillTargetEntityList
 -> HealHP / AddModifier target AbilityTargetEntity
```

Natasha is the healer; the selected ally is the recipient and may be a different unit. `AlwaysDoAutoLock=true` and `AutoLockType=LowHP` are selection inputs, not a recovered targeting evaluator. Phase01's `ByIsTurnActionEntity` branch selects camera abilities, not different heal equations. [N1] [N2] [N3] [N4]

## 4. HEAL-01 — Numeric producers and independent consumers

Pinned Skill110502 Lv1 has `ParamList=[0.07,0.048,2,70,48]`; Lv2 has `[0.074375,0.051,2,112,76.8]`. `SimpleParamList` is not substituted. These are audited samples, not all-level census evidence. [N2]

| Index | Lv1 | Lv2 | CharacterConfig hash / read | Consumer |
| --- | --- | --- | --- | --- |
| 0 | 0.07 | 0.074375 | `-1544075911`, SkillParam(Skill02,0) | Direct HealHP.HealPercentage. |
| 1 | 0.048 | 0.051 | `-754957899`, SkillParam(Skill02,1) | AddModifier.MDF_ShowValue1 -> HOT working hash `1733325153` -> periodic HealPercentage. |
| 2 | 2 | 2 | `-1019407308`, SkillParam(Skill02,2) | LifeTime plus trace working value. |
| 3 | 70 | 112 | `-203632277`, SkillParam(Skill02,3) | Direct HealHP.ModifyValue. |
| 4 | 48 | 76.8 | `-1192384503`, SkillParam(Skill02,4) | AddModifier.MDF_ShowValue2 -> HOT working hash `2136609680` -> periodic ModifyValue. |

`MDF_ShowValue1/2` are battle inputs here, despite their names. Named transfer and destination reads establish the binding, not equal numeric values or a guessed global hash algorithm. [N3] [N4]

## 5. HEAL-02 — Direct healing equation and raw request

At `AbilityList[Name=Avatar_Natasha_00_Skill02_Phase02].OnStart[4]`, the raw operation is `RPG.GameCore.HealHP`, recipient `AbilityTargetEntity`, with `FormulaType=HealByHealerMaxHP`. Both numerical operands use `AQAR`, empty FixedValues, and their respective DynamicHashes `[-1544075911]` / `[-203632277]`. [N4]

Let `H_N` be Natasha's effective maximum HP used by the heal. Combining this source chain with the public description yields a usable, cross-validated interpretation:

```text
Lv1 direct base heal = 0.07 * H_N + 70
Lv2 direct base heal = 0.074375 * H_N + 112
```

The coefficient and flat value are pinned; the arithmetic/owner interpretation is corroborated publicly. The native evaluator body is not recovered, but the basic equation is no longer unknown. For the ordinary case without received-healing modifiers or special conversions, the public healing model applies the eligible Outgoing Healing multiplier to the whole base amount. See [Public] for provenance and restrictions.

The raw occurrence omits a numerical cap, overflow action, snapshot selector, HealPercentage bound, SPHitRatio and DisplayData. Those omissions stay omissions: they are not evidence of zero values, unlimited HP, or absence of engine defaults. Exact rounding and result-event representation remain separate questions.

Authored sites: PointB1 dispel at OnStart[3], direct heal at [4], lifetime branch at [5], HOT installation at [6], and ModifySPNew(Caster,AddRatio=1) at [8]. Later random targeting is voice presentation. Serialization locates these operations; it does not alone prove cross-event completion order. [N4]

## 6. HEAL-03 — Gallagher's flat base is positively identified

Avatar1301 -> Skill130102 Lv1 has `SkillTriggerKey=Skill02`, `ParamList=[200]`. CharacterConfig hash `2082775117` reads SkillParam(Skill02,0). Phase01 passes `AbilityInherentTargetType=AbilityTargetEntity` on Caster; Phase02 declares `InherentTargetEntity`. [N1] [N2] [C1] [C2]

Phase02.OnStart[4] has four top-level keys: `$type=RPG.GameCore.HealHP`, TargetType=AbilityTargetEntity, fixed `SPHitRatio=1`, and dynamic ModifyValue using `AQAR/[2082775117]`. FormulaType and HealPercentage are absent. [C2]

P3 independently describes the selected Skill's level-1 base as 200 and distinguishes healing-level scaling from attack-stat scaling. Therefore **base heal=200** is an accepted gameplay interpretation, not an unresolved operand without meaning. Healing bonuses can still change the result; a flat base is not a universally fixed final HP recovery.

Do not invent a serialized default FormulaType or add HealPercentage=0 to the JSON. Do not transfer this Skill's source attribution automatically to Gallagher's separately triggered Talent. The rank-gated preceding dispel/status branch and SPHitRatio remain separate source facts. [P3]

## 7. MOD-01 / HEAL-04 — HOT installation, amount and recipient

Phase02.OnStart[6] installs `MAvatar_Natasha_00_HOT_HPByMaxHP` on AbilityTargetEntity. Its definition is in **GlobalModifiers of the same Avatar ability file**, not inferred from a global-sounding name. [N4]

The complete definition-key set is `LifeStepMoment`, `UseSnapshotEntity`, `_CallbackList`, `Stacking`, `DynamicValues`:

```text
LifeStepMoment = ModifierPhase1End
UseSnapshotEntity = true
Stacking = ReplaceByCaster
working slots 1733325153 / 2136609680: ReadInfo(Type=None,Index=0)
only local callback event = OnPhase1
  predicate: ModifierOwnerEntity HP > 0
  success[0]: TriggerEffect
  success[1]: HealHP(ModifierOwnerEntity,
    FormulaType=HealByHealerMaxHP,
    HealPercentage=AQAR/[1733325153],
    ModifyValue=AQAR/[2136609680],
    DisplayData.FixedPosition=false)
```

The selected holder is the heal recipient; the base scaling stat belongs to Natasha:

```text
Lv1 HOT base pulse = 0.048 * H_N + 48
Lv2 HOT base pulse = 0.051 * H_N + 76.8
```

P1/P2's turn-start healing description, together with holder identity and this callback, supports **the healed ally's turn-start pulse** for this selected HOT. That mapping is a reconciled gameplay interpretation, not a universal definition of every OnPhase1 callback. [P1] [P2]

The holder HP>0 predicate is not an overheal test or revival rule. DisplayData/VFX does not produce the heal amount. The periodic callback uses installed indices1/4, not the direct indices0/3. `ReadInfo.Type=None` declares working slots, not default zeros.

No local OnCreate/OnStack/OnDestroy, MaxLayer, LayerAddWhenStack, BehaviorFlagList, RemoveWhenCasterDead or KeepOnDeath is serialized in this definition. No callback or caster-death persistence rule is manufactured to fill those omissions. [N4]

## 8. MOD-02 / MOD-03 — Duration and stepping are distinct

Point1105103 Lv1 Avatar1105 has `PointTriggerKey=PointB3`, `ParamList=[1]`. Hash `2117344201` binds SkillTreeParam(PointB3,0). The active branch writes SkillTree_LifeTime, otherwise explicit zero, with working hash `-1087299341`. [N3] [N4] [N5]

```text
LifeTime: AQABAQIR, DynamicHashes=[-1019407308,-1087299341]
         SkillParam(Skill02,2) + SkillTree_LifeTime
selected duration = 2 without PointB3; 3 with PointB3
```

The addition uses the already-audited postfix mapping. P1's description and trace now explain these as the selected HOT's two-turn duration and one-turn extension, not merely uninterpreted numbers. This does not prove all extra-turn interactions, same-caster reapplication/reset or expiry-versus-other-callback ordering.

A new application with a longer supplied duration is not evidence of an in-place extension of an existing remaining timer. The adjacent Rank02 HOT is a **different modifier** whose Skill03 install explicitly has `LifeStepImmediately=true`; that field is absent from the primary install and is not copied across. Empty AbilityName in the PointB3 table does not remove the actual predicate/parameter dependency. [N4] [N5]

## 9. MOD-04 to MOD-08 — Lifecycle comparison

| Sample | Explicit data | Authored consequence / bounded interpretation |
| --- | --- | --- |
| Natasha Skill02 HOT | ReplaceByCaster; duration2/3; ModifierPhase1End; snapshot true | OnPhase1 HP>0 -> periodic HealHP(holder); selected recipient-turn-start meaning is now publicly reconciled. |
| March main Shield | Replace; supplied lifetime; snapshot true; Shield flag | OnCreate resilience/VFX; OnStack InitShield and AggroAddedRatio; OnDestroy RemoveShield/reset; OnPhase1 conditional Rank06 heal. |
| Natasha PointB2 HealRatioUp | ReplaceByCaster; no supplied LifeTime, local LifeStepMoment or snapshot flag | OnStack -> StackProperty(holder,HealRatioBase,0.1); public gameplay role is Outgoing Healing. |

Raw callback presence/absence and policy tokens are preserved. Omitted lifetime does not itself prove permanent duration; omitted snapshot flag does not prove all reads are live. These are not reasons to withhold the separately supported healing/shield equations. [N4] [S1] [M1] [P2] [March]

Replace/ReplaceByCaster still need specific evidence for matching keys, different-caster coexistence, old/new callback order, property rollback and snapshot refresh. Merge was not sampled here, not declared absent. The previous complete raw comparison is retained in [Original].

## 10. MOD-09 — Snapshot routing versus observable scaling

Natasha HOT and March Shield request `UseSnapshotEntity=true`. Luka's `GlobalModifiers.MAvatar_Luka_DOT_Tear.OnCreate` separately reads Attack from `SnapshotPropertyEntity` into MDF_CasterAttack and holder MaxHP into MDF_TargetMaxHP. Selective entity/property routing is real; this is not copy-all/freeze-all evidence. [L1] [March]

Natasha SkillP01 installs `Fuka_Beginner_PassiveSkill_Buff_1`. OnSnapshotCreate installs the literally named `Fuka_Beginner_PassiveSkill_Buff_1_ForSnapshitEntity` on event ParamEntity with an injected threshold; that child has OnBeforeDealHeal and references a heal-ratio input. Neither the Fuka prefix nor spelling changes its established Natasha ownership. [N3] [N4]

Native snapshot event construction, capture/refresh time, cross-context fallback and the operational blacklist algorithm remain unestablished by this raw audit. GameCoreConstValue's SnapshotEntityInheritBlackList and callback-recall settings are inputs, not a complete algorithm. [G1]

Knowing that the heal scales with Natasha's MaxHP does not determine exactly when every property is captured. Conversely, not knowing capture internals does not make the identity of the scaling character unknown. Public controlled stat-change tests can resolve observable capture behavior without recovering native code.

## 11. MOD-10 / MOD-11 — Dispel and removal

| Layer | Source evidence | Public reconciliation / limit |
| --- | --- | --- |
| Eligibility | AvatarStatus10010011 main March Shield and10011055 primary Natasha HOT: Buff, CanDispel=true, exact ModifierName. | Eligibility is not a claim that either Buff is removed by Natasha's cleanse. |
| Natasha Skill cleanse | PointB1 -> DispelStatus(AbilityTargetEntity, Numbers hash-2124210825, Order=LastAdded); Point1105101 supplies1. | P1/P2 identify this selected gameplay effect as removing one debuff. No universal default filter or same-time tie-break is inferred for every DispelStatus occurrence. |
| Removal/destruction | Named RemoveModifier differs from RemoveShield; March OnDestroy explicitly removes its shield; primary HOT has no local OnDestroy tasks. | Native teardown connection/order is not supplied by a callback name. |

The raw Natasha operation omits StatusType, BehaviorFlags and OnlyCanDispel. Those fields remain absent; the public interpretation of the selected Skill is not a fabricated serialized filter. [N3] [N4] [N5] [S2] [M1]

## 12. MOD-12 — Periodic healing is not one generic DoT formula

Reuse [R2] WTB-09. The Fire Break template installs MCommon_Element_Burn with LifeTime2 and a named percentage input. The modifier has ModifierPhase1End, snapshot true and ReplaceByCaster; OnStack reads its layer. OnPhase1 emits `DamageByAttackProperty(holder,Fire,FormulaType=ByBreakDamage,AttackType=DOT,FinalFormulaType=ByPureDamage)`.

Natasha HOT's callback instead requests HealHP with healer-MaxHP operands. Shared lifecycle fields do not merge these equations or owners. Burn MaxLayer=1/LayerAddWhenStack=1 is not copied into HOT. MCommon_Element_Burn, MCommon_DOT_Burn and StanceBreakState stay distinct. The Burn OnCustomEvent extra-trigger producer is not closed merely by this comparison.

The public DoT model in [Public] now guides the next exact producer/callback questions; it is not a claimed complete DoT census or new raw trace here.

## 13. HEAL-05 — Healing boosts have a known gameplay role

Persistent contribution:

```text
Point1105102 Lv1 -> PointB2 ParamList[0]=0.1
 -> CharacterConfig hash103268114
 -> Avatar_Natasha_SkillTree02
 -> AddModifier(Caster,M_SkillTree_HealRatioUp), MDF_PropertyValue
 -> GlobalModifier_Avatar.ModifierMap.M_SkillTree_HealRatioUp
 -> OnStack StackProperty(ModifierOwnerEntity,HealRatioBase,hash2128130574)
```

Conditional per-heal contribution:

```text
Skill110504 Lv1 -> SkillP01 ParamList=[0.3,0.25]
 -> threshold hash-889510027; bonus hash-1134214845
 -> Fuka_Beginner_PassiveSkill_Buff_1.OnBeforeDealHeal
 -> ByCompareHPRatio(ParamEntity,LessEqual,0.3)
 -> ModifyHealData.Healer_HealRatio from the0.25 input
```

P2 describes the corresponding Healer trace and low-HP talent as Outgoing Healing, including the talent's application to continuous healing. Their role is thus not an unexplained healing-named property. In the ordinary public multiplier model, eligible outgoing-healing contributions modify the whole base heal rather than adding another HP-scaled base coefficient. [N2] [N3] [N4] [N5] [S1] [P2]

The eligible condition must be evaluated for the heal in question; do not assume that a recipient healed above the threshold still gets the talent on every later pulse. Preserve `MuteDotCasterCallBack` without extending it to all periodic effects. Exact event argument construction, native aggregation/capture and special received-healing interactions are not claimed from these two operations alone. [Public] separates model use from executed evidence.

## 14. Heal amount, actual HP recovery and remaining tests

The requested healing amount and actual HP gained are different quantities when the recipient lacks less HP than the computed heal. A maximum-HP limit is not a missing coefficient in Natasha's skill row. Published discussions of overhealing and outgoing-healing effects are usable gameplay evidence; neither an absent cap field nor an unavailable HP-commit body makes the selected base heal equation unknowable. [P3] [Public]

This checkpoint predicts pre-cap amounts, with sufficient missing HP where a comparison needs uncapped recovery. It does not claim an observed numeric result, a complete display-rounding rule, overheal payload/conversion semantics or all received-healing effects. The HOT's HP>0 predicate and talent's low-HP condition remain different from an HP-limit operation.

At `H_N=3000`, Lv1 direct base heal is280 and each base pulse192. With only the Healer trace's10% contribution, the ordinary model predicts308 and211.2 before rounding/capping. These are arithmetic checks, not new gameplay measurements. The independently published shield/mitigation experiment in [Public] is separately labeled external empirical evidence.

## 15. Evidence partition after reconciliation

| Claim | Current interpretation |
| --- | --- |
| Numeric rows/bindings | Manually confirmed raw samples, preserved. |
| Natasha direct/periodic base equations | Cross-validated pinned operands plus public MaxHP/flat interpretation. |
| Gallagher flat base200 | Cross-validated selected gameplay behavior; omitted raw enum remains omitted. |
| Outgoing-healing role | Public descriptions corroborate persistent and conditional source contributions. |
| Selected HOT recipient-turn-start and duration2/3 | Source/public reconciliation, not universal dispatcher recovery. |
| Selected Natasha cleanse | One-debuff gameplay role corroborated; generic raw defaults/tie-break are separate. |
| Snapshot/replacement exact implementation | Specific unresolved questions, open to public experimental evidence as well as new raw sources. |
| Rounding, special received healing, overheal events | Not fully audited here; do not conflate with known base arithmetic. |
| Native function bodies | Not recovered. |
| Backend execution | Not run; not a research prerequisite. |

No global W05/W09 closure, Merge absence, complete control/immunity mechanism or universal callback total order is asserted.

## 16. Reusable vocabulary

Retain the original HEAL/MOD distinctions: row-to-binding-to-operand; caster versus recipient; direct versus installed periodic values; property contribution versus per-heal mutation; duration versus callback; replacement versus extension; eligibility versus active dispel; named removal versus shield removal; and HP healing versus Break-derived damage.

A public formula does not assign global meanings to every SkillParam index. A known flat-heal behavior does not invent an omitted enum. A known recipient-turn-start pulse does not define all phase events. These are scoped interpretation limits, not blanket prohibitions on using established mechanics.

## 17. Source anchors and continuing uncertainties

| Ref | Exact pinned path / selected occurrence |
| --- | --- |
| N1 | AvatarConfig: ordinary1105 and1301 identity/wiring. |
| N2 | AvatarSkillConfig: Skill110502 Lv1/Lv2;130102 Lv1;110504 Lv1. Blob `a5416ced941c247d475b2aaa83277b9cdf474dd9`. |
| N3 | Natasha CharacterConfig: Skill02/SkillP01, parameter indices and PointB1/B2/B3 bindings. |
| N4 | Natasha Ability: Skill02 Phase01/02, primary HOT, trace and passive/snapshot-child. Blob `0dd71d6942e4f8420749c56c8151710dee0bf9f0`. |
| N5 | AvatarSkillTreeConfig:1105101/2/3 Lv1. Blob `cee634adac569ad417ebedf55f9be67caa05fab8`. |
| S1 | GlobalModifier_Avatar: M_SkillTree_HealRatioUp. |
| S2 | AvatarStatusConfig:10010011/10011055. Blob `2779ce6cff1f2411e2ae400b98eef2a6f0a4c775`. |
| C1 | Gallagher CharacterConfig: Skill02 and hash2082775117. |
| C2 | Gallagher Ability: inherent-target transfer and Phase02.OnStart[4]. Blob `9c29a5776ba33334439d3b38e6988098a2925f85`. |
| M1 | March Ability: main shield install/lifecycle. Blob `b9b4e3705a73cb691306d7e68912a7b33e597e94`. |
| L1 | Luka Ability: MAvatar_Luka_DOT_Tear.OnCreate selective property reads. |
| G1 | GameCoreConstValue: snapshot blacklist / callback-recall settings. |

Large-table transport failures in the original audit were resolved through exact blobs, not treated as missing data. Exact source paths below remain pinned. R0/R1/R2 raw claims are not changed here.

Remaining work should ask a discriminating question about snapshot refresh, reapplication, received-healing interaction, rounding, control or DoT activation. Public observations can resolve gameplay semantics without a native body. Raw-SP/BP labels and SPHitRatio remain W08 questions; no new resource conversion is inferred. This record does not schedule backend work or restart a generic engine search.

[Public]: public_mechanics_healing_shield_reconciliation_v1.md
[Original]: https://github.com/yaelysia/hsr-battle-simulator/blob/61541a5c692314bbd33e5ac835b12da0044dd8ce/docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md
[P1]: https://starrail.honeyhunterworld.com/love-heal-and-choose-skill/?lang=EN
[P2]: https://srl.keqingmains.com/characters/physical/natasha
[P3]: https://hsr.keqingmains.com/q/gallagher-quickguide/
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
