# Ordinary Damage Vertical Slice v1

## 1. Metadata, authority and bounded result

- Thread: `R1-DAMAGE-VERTICAL-SLICE-V1`; PR #8, documentation/evidence only.
- Research date: 2026-09-09; source version is the pinned revision, not an inferred current-live version.
- Research baseline: `e0f6f4549a4536f6940455a67783178d1bda63f4`; actual PR head matched the planning head at startup.
- Upstream authority: `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Maturity: `manually_confirmed` for the occurrences and producer/consumer edges explicitly closed here; heterogeneous structural cross-checks are not runtime verification.
- Authority class: `battle_authoritative` for retained operation/input edges; `mixed_requires_filter` for their containing files. Battle-scope verdict: `include` at those edges, `mixed` at file level.
- Confidence: high for literal fields, bindings and authored call sites; no confidence claim for unavailable engine mathematics.
- Result: **complete for this bounded damage vertical slice v1**, not `W04 mechanism_closed`, an exhaustive damage dictionary, or a numerically reproduced combat result.
- Runtime/business/lowering/IR changes: **none**. Runtime/Fast/Direct verification: **not performed / not claimed**.

The governing contract remains BATTLE_SCOPE/evidence contract, current worklist/inventory, corrected detailed records, then historical reconciliation. Exact pinned raw always outranks an interpretation. No current-game formula, tooltip, source-name inference or default-branch payload supplies missing semantics.

This record extends [Battle Execution Language Core v1][R0], rather than rebuilding it: P1/P2/P5/P6/P9 for family-qualified parameters, hashes and modifier injection; E1/E2/E3/E4/E6/E7 for performer, ability target, callback/traversal parameter, servant, modifier holder and relative enemy set; D1/D2/D3/D7 for entry, phase, listener and callback; O3/O16/O17 for the damage request, working values and property contributions. `ModifyDamageData` is expanded below from R0's routed edge, not retroactively asserted to be a previously complete R0 formula.

## 2. Gameplay semantic model and search discriminator

The navigation model is an ordinary actor using a legal action against selected entities, producing one or more damage requests whose operands may be affected by installed battle state. It must distinguish outgoing actor, defender, modifier caster, modifier holder, current hit data and persistent entity properties. It also must distinguish a coefficient from a final HP loss, logical operations from visual impacts, and missing fields from explicit zero/false.

The mandatory primary remains Monster `1002011` / Skill `100201101`. Its simple AllEnemy request is suitable for a full occurrence audit, but does not explicitly select a scaling formula or author a damage-context modifier. Two bounded discriminators are therefore added, not substituted for it:

| Sample | New discriminator | Stop boundary |
| --- | --- | --- |
| Aglaea Skill01 and its GoldenSword/Rank02 state | Avatar single-target repeated damage requests; ordinary installed defender- and attacker-side callback surfaces that modify damage data | Do not expand servant scheduling, full passive follow-up, rank-six damage formulas or universal dispatcher order |
| Aventurine Skill01; Skill03 mark application only | Same damage opcode with explicit `FormulaType=ByDefence`; entity resistance write versus hit-context critical-damage write | No shield lifecycle, coin RNG, complete resource economy or full follow-up archaeology |

The model is the current card's gameplay/completeness hypothesis, checked against raw producers and consumers. No new external gameplay observation or numerical corroboration is claimed. All interpretations below are pin-scoped; unresolved behavior is preserved rather than reconciled with a live formula.

## 3. Primary anchor: retain the R0 chain, audit the next surface

The following joins were established in R0 and re-read at the pin for this record. Repeating the coefficient discovery is not the new result. [M1][M2][M3][M4][M5]

```text
MonsterConfig[MonsterID=1002011]
  MonsterTemplateID=1002011; SkillList=[100201101]
  -> MonsterTemplateConfig[1002011].JsonConfig
       Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
  -> MonsterSkillConfig[SkillID=100201101]
       SkillTriggerKey=Skill04; ParamList[0].Value=2
  -> ConfigCharacter.DynamicValues.Floats["-190305622"].ReadInfo
       Type=SkillParam; TriggerKey=Skill04; Index=0
  -> SkillList[Name=Skill04].EntryAbility
       Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01
  -> TriggerAbility(TargetType=Caster, Phase02, IsSkillPerform=true)
  -> Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase02
       TargetInfo.TargetType=SkillTargetEntityList
  -> OnStart[5]: DamageByAttackProperty(TargetType=AllEnemy)
```

These table, ability and template identities are explicit references, not decimal-ID decoding. In particular, a nearby concrete Monster row also has numeric ID `100201101`; it is not the skill-row identity merely because the numbers match. Template `AttackBase=18`, `DefenceBase=210` and `CriticalDamageBase=0.2` are separate construction inputs, not the current damage's evaluated ATK/DEF/crit result. W14 final-stat construction stays outside this slice.

## 4. DMG-01: complete primary damage occurrence

This is the complete logical operation object, including its colocated presentation fields, from [M5]. No absent field has been supplied.

```json
{
  "$type": "RPG.GameCore.DamageByAttackProperty",
  "TargetType": {
    "$type": "RPG.GameCore.TargetAlias",
    "Alias": "AllEnemy"
  },
  "AttackProperty": {
    "$type": "RPG.GameCore.AttackData",
    "DamageType": {"DamageType": "Ice"},
    "DamagePercentage": {
      "IsDynamic": true,
      "PostfixExpr": {
        "OpCodes": "AQAR",
        "FixedValues": [],
        "DynamicHashes": [-190305622]
      }
    },
    "SPHitRatio": {"IsDynamic": false, "FixedValue": {"Value": 1}},
    "AttackType": "Normal",
    "HitAnimation": "Hit",
    "HitTimeSlowType": "Impact"
  },
  "DisplayData": {"DitherRangeX": 0.02, "DitherRangeY": 0.02}
}
```

| Field/context | Classification | Proven role and limit |
| --- | --- | --- |
| Operation `$type`; `AttackProperty.$type` | `raw explicit` | Typed damage request plus AttackData payload; not an exported evaluator body |
| Performer | Invocation-derived, R0 E1/D2 | Monster instance's Phase01 dispatches Phase02 on Caster; the damage object has no independent performer override |
| `TargetType=AllEnemy` | `raw explicit` | Relative enemy set in that monster invocation, not globally synonymous with TeamDark |
| Phase02 `TargetInfo=SkillTargetEntityList` | `raw explicit`, enclosing invocation | Distinct from this operation's explicit AllEnemy selector; no retarget/ParamEntity override in this occurrence |
| `DamagePercentage` | `dynamic binding` | Single-hash read of Skill04 index 0, raw value 2; final scaling operation is not thereby known |
| `DamageType=Ice` | `raw explicit` | Authored damage-type discriminator; does not supply a RES or weakness equation |
| `AttackType=Normal` | `raw explicit` | Authored attack-category input, not an assertion of basic-attack UI semantics for every actor |
| `SPHitRatio=1` | `raw explicit` | Resource-adjacent attack operand; W08 owns resource identity, base, multiplication and caps |
| `HitAnimation=Hit`, `HitTimeSlowType=Impact` | `presentation-only` for this claim | Animation/impact presentation, not hit count, Action Value or numeric damage arithmetic |
| `DisplayData.DitherRangeX/Y` | `presentation-only` | Display-position jitter, not gameplay damage RNG |

The **entire inspected object** has no explicit `FormulaType`, scaling-property selector/read, `DamageValue`, `StanceValue`, `HitSplitRatio`, `DamageBehavior`, crit switch, damage-tag/custom-name attribution, snapshot/property-source selector, attacker override or `CanTriggerLastKill`. Their omission is occurrence-local evidence. Their effective defaults are **`default unknown` / `engine-owned`**, not zero damage, zero toughness damage, split ratio 1, normal behavior 0, non-crit, or a guaranteed ATK formula. No `property-derived` or `modifier/context-derived` coefficient is authored inside this object itself; callbacks elsewhere are a separate contribution surface.

## 5. DMG-02: scaling-property discrimination

`AvatarConfig[AvatarID=1304]` explicitly references Aventurine's ConfigCharacter, SkillList including 130401/130403, and RankIDList including 130402; the inspected row has `Release=true`. Its ConfigCharacter supplies EnemySelect Skill01 -> `Avatar_Aventurine_00_Skill01_Phase01` -> same-caster Phase02. `AvatarSkillConfig[130401,Level=1].ParamList[0].Value=0.5` binds through character hash `-1126825319`, `SkillParam(Skill01,0)`, into `DamagePercentage`. [A1][A2][A3][A4]

The Phase02 damage operation explicitly contains `AttackData.FormulaType="ByDefence"`, `DamageType=Imaginary`, the above dynamic coefficient, `StanceValue` hash `1659254037`, `SPHitRatio=1`, and operation-level `CanTriggerLastKill=true`. Its direct damage object omits `AttackType` even though the skill-table row has `AttackType=Normal`; preserve both facts without inventing the table-to-operation default/override rule.

**Closed scaling conclusion:** the same literal `DamageByAttackProperty` operation accepts an explicitly selected defence-based formula family in an ordinary character path. The opcode name alone therefore cannot establish ATK scaling for the monster occurrence, which omits FormulaType. The coefficient is a direct typed skill-parameter read, not visibly a precomputed defence product in this sample.

**Still engine-owned:** the implementation of ByDefence, whether and when it reads the invoking actor's current/snapshot/redirected Defence, getter/override resolution, final multiplication/addition, caps and rounding. Caster is the source-facing execution owner; that does not establish the hidden formula's exact property-fetch implementation.

A nearby `SetDynamicValueByProperty(Caster.Defence -> MDF_CurrentDefence2)` is in **Skill02 shield preparation**. It is not an explicit argument to this Skill01 damage operation and is not borrowed to close its property-read edge. Separately, Aventurine's trace template reads `ModifierOwnerEntity.Defence` and `DefenceConvert` for a crit-property contribution; that is another consumer domain, not proof of the direct-damage formula.

## 6. DMG-03: ordinary GoldenSword damage-context mutation

This expands the exact high-signal edge left by R0. [G1][G2][R1]

```text
Avatar_Aglaea_00_Config.Skill01 (EnemySelect) -> Phase01 -> Phase02
  -> ByIsTargetValid(CasterServant, AliveOnly=true)
  -> AddModifier(AbilityTargetEntity, AliveOnly=false,
       MAvatar_Aglaea_00_GoldenSword_Mark, named DynamicValues)
  -> installed enemy-side modifier.OnBeforeBeingHitAll
       ByRankActivated(TargetType=Caster, Trigger.Hash=2089636447)
  -> ModifyDamageData.Defender_AllDamageTypeTakenRatio
       AQAR; DynamicHashes=[-941578568]
  <- Aglaea ConfigCharacter: SkillRank(Rank01,index=0)
  <- AvatarRankConfig[RankID=140201].Param[0].Value=0.15
```

The Rank01 row also has `Param[1]=20`; its trigger hash matches the callback gate. The ordinary Skill01 installation site is ordered before the three direct-hit operation sites in Phase02. Installation is conditional on the valid living servant; Rank01 separately gates the damage-data modification. Do not collapse these two predicates into one.

The AddModifier injection includes `BombDamagePercentage`, `_SpRecover`, `MDF_PropertyValue` and `MDF_PropertyValue2`. **The inspected damage-taken callback reads character hash `-941578568` directly**, not the modifier-local `MDF_PropertyValue2` slot. A similarly valued injected field is not interchangeable producer evidence.

| Identity/domain | Meaning in this occurrence |
| --- | --- |
| Modifier caster / parameter owner | Aglaea, whose Rank01 binding is read |
| Modifier holder | The selected enemy receiving the mark |
| Callback surface | `OnBeforeBeingHitAll` on the installed mark |
| Destination | Literal `ModifyDamageData.Defender_AllDamageTypeTakenRatio` |
| Mutation domain | Damage-context modification request for the defender-side field, not a `StackProperty` on the enemy's persistent property set |

The raw input 0.15 and destination are closed. The modifier's `RemoveWhenCasterDead` flag and local callbacks are exported. Calling the destination a damage-taken input is supported; claiming a complete universal vulnerability bucket, `1+0.15` formula, additive stacking, final order relative to DEF/RES/crit, or guaranteed visibility on the immediately following hit is **not** established by this graph. Allocation, merge and callback-dispatch details remain engine-owned.

`OnStack` here can issue `StackStatusDesc`: that is descriptive presentation and is not the damage producer. The numeric producer is the typed Rank01 binding consumed by ModifyDamageData.

## 7. DMG-04: DEF-facing context, without a guessed DEF formula

Aglaea's ordinary passive EntryAbility `Avatar_Aglaea_00_PassiveSkill01` conditionally installs `MAvatar_Aglaea_Rank02_Listen` on Caster under Rank02. The listener's `OnListenBeforeSkillUse` and `OnListenInsertAbilityStart` compare their ParamEntity with `Caster + CasterServant`, then add `MAvatar_Aglaea_Rank02_Effect` to that owner/servant set. [G1][G2][R1]

The ordinary producer is `AvatarRankConfig[140202].Param=[0.14,3]`. Character hashes `191785981` and `-481881088` bind Rank02 indices 0 and 1. The add request injects `_IgnoreDefenceRatio` from index 0, sets `MaxLayer` from index 1, and authors `LayerAddWhenStack=1`.

The effect has two separate surfaces:

```text
OnStack:
  SetDynamicValueByModifierValue(ValueType=Layer, DynamicKey=_Layer)
  SetDynamicValue(_IgnoreDefenceRatioTotal,
    OpCodes=AQABAQQR,
    DynamicHashes=[1912601768,-606660942])

OnBeforeHitAll:
  ModifyDamageData.Defender_DefenceAddedRatio
    OpCodes=AAAOAQAEEQ==
    FixedValues=[1]
    DynamicHashes=[-194503132]
```

Those three effect-local hashes are declared in its DynamicValues environment; `-606660942` carries the injected ratio and `-194503132` is the working total read by the callback. This closes a producer -> listener installation -> effect initialization -> hit-context input chain, including its scope transfer. The installed effect may be on the attacking owner or servant, while the destination field is defender-side.

**Do not rename the actual field to generic DEF ignore.** `_IgnoreDefenceRatio` is a local key, while the exported consumer is `Defender_DefenceAddedRatio`. The final expression is retained byte-for-byte; this record does not decode every operator in `AAAOAQAEEQ==` or derive a DEF-ignore equation from the key's name. `Stacking=Replace` does not independently specify stack arithmetic or event order. JSON lists OnBeforeHitAll before OnStack, but serialization order is not a universal dispatcher sequence.

## 8. DMG-05: entity resistance versus damage-context fields

The Aventurine basic-attack Phase02 contains a Rank02 gate before its damage request. Under that gate it adds `MAvatar_Aventurine_Rank02_ResistanceDown` to AbilityTargetEntity. [A2][A3][R1]

```text
AvatarRankConfig[130402].Param = [1.2,0.12,3]
  ConfigCharacter SkillRank(Rank02,index=1), hash -1968707556
    -> AddModifier.DynamicValues.MDF_PropertyValue = 0.12
  ConfigCharacter SkillRank(Rank02,index=2), hash 329378919
    -> AddModifier.LifeTime = 3
  installed modifier.OnStack
    -> StackProperty(ModifierOwnerEntity, AllDamageTypeResistance,
         OpCodes=AAABAAMR, FixedValues=[0], DynamicHashes=[2128130574])
```

This is the inspected `0 - injected value` property-contribution expression, distinct from a hit-context ModifyDamageData write. The Rank02 index-0 value 1.2 is not substituted for the resistance operand. `ReplaceByCaster` is retained as raw stacking configuration; generic replace/add/cleanup arithmetic is not inferred.

The authored property-write chain is closed. Its exact consumption by the generic damage-resistance evaluator, element-specific versus all-type combination, timing relative to the following damage request, penetration interaction, clamp and rounding remain **source-facing partial / engine_consumer_unavailable**. `AllDamageTypeResistance` is not `StatusResistance` or `StatusResistanceBase`; the latter's effect-application probability semantics do not prove a damage RES formula.

## 9. DMG-06: enemy-held state can modify attacker critical damage

Use only the ordinary Skill03 mark application and adjacent damage request, not the coin or follow-up mechanics. [A2][A3][A4]

`AvatarSkillConfig[130403,Level=7]` supplies `SkillTriggerKey=Skill03`, `ParamList=[7,2.295,0.1275,3]`. Character bindings are:

| Hash | Typed binding | Inspected consumer |
| --- | --- | --- |
| `-1137062232` | SkillParam(Skill03,1) | Ultimate damage request's DamagePercentage, value 2.295 in this row |
| `264843332` | SkillParam(Skill03,2) | Named modifier injection `MDF_PropertyValue`, value 0.1275 |
| `235360596` | SkillParam(Skill03,3) | Mark lifetime input, value 3 |

Skill03 Phase02 adds `MAvatar_Aventurine_00_Skill03_CritDmgIncrease` to AbilityTargetEntity, then authors its `DamageByAttackProperty` request with ByDefence / Imaginary / Ultra. The installed mark has `OnBeforeBeingHitAll`, a `ByTargetTeam(ParamEntity, TeamLight)` gate, and:

```text
ModifyDamageData.Attacker_CriticalDamage
  OpCodes=AQAR; DynamicHashes=[2128130574]
  <- modifier-local MDF_PropertyValue injected by Skill03
```

Thus an **enemy-held** modifier can author an **attacker-side damage-context** input. Modifier holder does not determine the destination side. This is not a persistent `CriticalDamageBase` StackProperty and does not assert a crit outcome. Whether that same cast already observes the newly installed modifier, how the field combines with existing crit damage, and the crit probability/draw/exception rules require the missing consumers.

The nearby `MAvatar_Aventurine_SkillTree01` is a separate source-facing crit-chance path: the passive's PointB1 branch installs it; its OnStack/Defence-change surfaces include a template reading `ModifierOwnerEntity.Defence` and `DefenceConvert`, followed by a submodifier that writes `CriticalChanceConvert`. That operation/owner path is observed, but its complete trace-parameter/numeric expression chain and final crit evaluator are **not closed here**. Do not upgrade it to a numerically verified crit formula or treat the preceding direct ByDefence damage as already using that property-read algorithm.

## 10. DMG-07: logical multi-hit and downstream surfaces

Primary Phase02's explicit task-site order is:

```text
SkillExecutionStart -> DamageByAttackProperty(AllEnemy)
  -> DamagePerformFinish -> SkillPerformFinish
```

Animation waits/effects intervene at authored sites; they are not scheduler/Action Value inputs. Finisher names do not expose which generic events they emit, the instant of HP commit, or callback draining. **The primary source-facing chain closes at the damage request and explicit continuation markers; generic downstream HP evaluation/mutation is `engine_consumer_unavailable`.** No raw `HP_after=HP_before-damage` implementation was recovered or invented. [M5]

Aglaea ordinary Skill01 Phase02 explicitly authors **three** DamageByAttackProperty operations on AbilityTargetEntity, with `HitSplitRatio` values **0.2, 0.2, 0.6** and the same dynamic DamagePercentage source. It then calls DamagePerformFinish and SkillPerformFinish. These are three logical operation occurrences, not three inferred animation impacts. The monster comparison is one authored operation selecting AllEnemy, not an authored per-target loop. Internal target iteration order, per-hit rounding/crit and split normalization remain unknown. [G2]

The installed GoldenSword mark also has a distinct `OnAfterBeingAttacked` callback. It compares ParamEntity against CasterServant and Caster; the servant branch under Rank01 issues `ModifySPNew(Caster,AddValue=77717678)`, whose Rank01 index-1 producer is 20. The other branch contains a separate Pursued damage request. This is an ordinary attack-observer/secondary-consequence surface, not proof that OnAfterBeingAttacked equals OnAfterHitAll, HP change or death, and not proof that the outgoing monster attack triggers this enemy-held avatar mark. Resource semantics and the full follow-up remain routed dependencies. [G1][G2][R1]

The examined callback domains are therefore not flattened: attacker `OnBeforeHitAll`, defender `OnBeforeBeingHitAll`, later `OnAfterBeingAttacked`, effect `OnStack`, and action/attack finish call sites retain separate identities. No universal total order is claimed.

## 11. Damage-layer evidence partition

Partition the **claim**, not merely the field name. A closed input can coexist with an unavailable evaluator.

- **A / source-facing closed:** ordinary producer/owner and actual consumer or operation are traced for the stated narrow claim.
- **B / source-facing partial:** an ordinary surface exists, but a required producer, numeric subexpression, merge/default/order or downstream consumption remains open.
- **C / engine_consumer_unavailable:** the concrete exported surface has reached an unexported generic consumer; not a whole-package absence assertion.
- **D / candidate only:** not traced through a complete ordinary chain in this slice; this does not revoke another record's closure.

| W04 layer | A/B: evidence established in this slice | C: missing generic semantics / D: unpromoted remainder |
| --- | --- | --- |
| Base coefficient | A: primary Skill04 input 2; Aventurine Skill01 Lv1 input 0.5; explicit typed bindings | C: base-damage evaluation and missing-field defaults |
| Attacker scaling | A: ordinary ByDefence selection under the same opcode; B: exact property getter is hidden | C: primary's omitted formula default; current/snapshot/redirected property source, multiply/add/cap/rounding; no ATK formula inferred from the opcode name |
| Generic damage bonus | D: nearby Aglaea Rank06 `Attacker_AllDamageTypeAddedRatio`/template edge is not expanded through its full installation/operand chain here | C: generic bonus composition is not supplied by an isolated field; D remains outside this slice's confirmed registry |
| Damage taken / vulnerability | A: installed GoldenSword -> Defender_AllDamageTypeTakenRatio, Rank01 input 0.15 | C: final bucket equation, merge/stack semantics and precedence |
| Mitigation / reduction | B: prior ordinary shared damage-reduction lifecycle evidence remains in [W17]; this slice does not re-audit its full operand chain | C: generic reduction evaluator; no formula inferred from `MinimumFatigueRatio` or a sibling modifier name |
| DEF | A: installed Rank02 effect -> Defender_DefenceAddedRatio plus raw expression and inputs | B: expression interpretation not fully decoded; C: final DEF equation, bounds, interaction with ignore/reduction |
| Elemental resistance | A: damage-type discriminators; A at property-write level: ordinary Rank02 -> AllDamageTypeResistance contribution | B/C: entity property -> final damage RES calculation, elemental/all-type composition and floors/caps |
| Penetration / ignore | A: literal DEF-facing operation in DMG-04, not a renamed ignore opcode; D: nearby ThunderPenetrate rank-six branch not completed here | C: universal penetration/ignore math and precedence; local key names do not close it |
| Crit chance | B: PointB1-installed trace template/property contribution path observed, numerical trace chain not closed | C: final chance, cap, forced/non-crit exceptions and RNG draw; D: no new forced-crit/non-crit flag contract established |
| Crit damage | A: ordinary Skill03 injection -> Attacker_CriticalDamage callback input | C: final crit damage assembly and condition of application |
| DamageBehavior | Prior closed ordinary Sam `DamageBehavior=1 -> DirectlyLoseHp` remains valid in [W17]; no such field exists in DMG-01 | C: omitted default and hidden special-case evaluator; TrueDamage/DirectlyLoseHpHit semantics are not generalized from the prior Sam sample; no new census |
| Multi-hit / split / traversal | A: three explicit Aglaea operations with split operands versus one AllEnemy monster operation | B/C: internal per-target execution, split normalization, per-hit rounding/crit and event grouping; damage-sharing is not proven by a split ratio |
| Downstream hit/attack/HP | A: explicit finish call sites and installed before-hit/after-attack callback surfaces | C: exact event emission/dispatch, HP evaluator, shield interaction, death decisions and universal cross-event order |
| Toughness and resources adjacent to damage | A: preserve present StanceValue/SPHitRatio operands; primary StanceValue omitted | B/C: final effects not derived here; W06/W08 own the next edges, not an inferred damage formula |

The prior Sam row is a consumption of the already corrected W17 record, not a newly re-traversed stage claim or a new DamageBehavior formula. Its ordinary reachability is not downgraded. No table in this section is a disguised complete damage equation.

## 12. Reusable damage language and actor-local limits

The reusable unit is **an occurrence-qualified damage request plus its execution frame and provenance**, not a bare multiplier. Retain literal type, enclosing ability/callback, performer, selection source, actually serialized operands, typed binding/expression provenance, explicit modifier installation and the destination mutation domain.

| Reusable distinction | Actor-local fact that must not become a default |
| --- | --- |
| DamageByAttackProperty carries AttackData and typed dynamic inputs across Monster/Avatar | Monster's coefficient 2, Ice, Normal and AllEnemy |
| Formula selection is separate from opcode spelling | Aventurine's explicit ByDefence; do not add it to other occurrences |
| Missing, explicit zero/false and explicit value are distinct source facts | Primary has no StanceValue/HitSplitRatio/crit/DamageBehavior override |
| Modifier source, holder and modified side are separate | GoldenSword reads Aglaea Rank01 but changes defender hit data; enemy-held Aventurine mark changes attacker crit-damage data |
| ModifyDamageData is not StackProperty | Rank02 resistance is an entity contribution; GoldenSword and Aglaea DEF effect are context requests |
| Each dynamic read retains its own producer and scope | Equal hash/name/value at another entity or local environment does not establish identical authority |
| Count logical operation sites/loops, not visual impacts | Aglaea's 0.2/0.2/0.6 versus one primary AllEnemy operation |
| Data-facing callbacks are distinct from the hidden dispatcher | OnStack initialization and before-hit reads do not expose universal ordering |

No new generic execution-frame correction to R0 was required. This record refines its routed damage edges. R0's Asta `GLOABNLLLEL` identity stays opaque, and Together remains distinct from a servant selectable normal action.

## 13. Engine/export boundaries and negative knowledge

The pin is a release-data corpus, not exported GameCore implementation source. After reaching the actual typed request/context/property surfaces above, the following missing consumers are named rather than replaced with gameplay formulas:

1. DamageByAttackProperty/AttackData evaluator, omitted defaults, formula dispatch and property-source sampling.
2. ModifyDamageData destination resolution, replace/add/merge behavior, cross-modifier precedence and current-hit lifetime.
3. Entity-property reduction/DEF/RES/penetration/crit getters and final numeric composition, clamps and rounding.
4. Internal multi-target/per-hit processing, completion/event emission, downstream HP mutation and shield/death interactions.
5. Generic RNG and callback ordering already frozen by W10/W12. No stream, probability or scheduler search was reopened.

`HitAnimation`, `HitTimeSlowType`, DisplayData, VFX, waits and StackStatusDesc are not promoted to damage math. A control/task container must nevertheless keep its battle-bearing children: excluding visuals is not permission to delete a contained damage request.

The high-risk false friends are: a skill's table AttackType mistaken for an explicit operation field; opcode spelling mistaken for its scaling formula; an injected similarly valued field mistaken for the actual read; `_IgnoreDefenceRatio` mistaken for a fully decoded DEF-ignore equation; damage resistance confused with status resistance; modifier holder confused with attacker/defender destination; local stacking names confused with universal order; template bases confused with final attacker stats; one AllEnemy operation confused with an authored per-target loop; and a missing field confused with a non-crit/zero/no-effect rule.

Large-file Contents reads returned empty content with a valid blob SHA for MonsterConfig and other large tables; exact Git-blob reads recover real rows. That transport result is not source absence. Default-branch search and response snippets were navigation only; final binding/operand claims use the exact pinned file/blob and named occurrence. No change to a pinned source or runtime was needed.

## 14. Discoveries and later-work routing

The new reusable distinctions are DMG-01 through DMG-07 above. No consequence requiring a W19+ package was established; the current damage/property/callback/resource work packages cover these edges.

| Routed item | Next owner and narrow obligation |
| --- | --- |
| Damage-context DEF/damage-taken/crit field composition | W04: new authoritative evaluator or explicit data-side consumer; preserve raw operands meanwhile |
| Rank06 bonus/penetration and complete trace crit-property numeric chain | W04 with W09/W02 dependency: complete only the named install/binding/consumer edge when prioritized, not a corpus scan |
| HitDamageSplit / damage sharing candidate from R0 | W04/W09: close a concrete installation chain before promoting the definition; not equivalent to HitSplitRatio |
| StanceValue and damage-type/weakness adjacency | W06: next toughness/break vertical slice; do not infer a primary omitted StanceValue default |
| SPHitRatio and GoldenSword ModifySPNew input 20 | W08: actual resource identity, generation, caps and callback effects |
| Lifetime, Replace/ReplaceByCaster, snapshot/live state | W09/W05 only as required by a concrete new source; frozen generic gaps are not reopened |
| Target iteration or callback arbitration | W11/W10 dependencies; no universal order inferred from serialized lists |

Recommended next slice: **W06 — Weakness / Toughness / Break vertical slice**, retaining these Damage interfaces. This thread stops after its durable checkpoint; W06 is not started automatically.

## 15. Verification and exit audit

Verification is manual exact-pin producer/consumer inspection and documentation consistency, not executable combat validation. Named occurrence locators below are preferred to guessed line numbers; JSON array indices are zero-based. Git blob SHA is of the complete upstream file, not of an excerpt.

| Exit obligation | Evidence / result |
| --- | --- |
| Primary full producer-to-operation chain and actual operands | DMG-01, M1-M5; satisfied |
| Scaling-property source-facing conclusion | DMG-02 explicit ByDefence versus omitted primary formula; satisfied without guessed math |
| Installed ordinary damage-context mutation | DMG-03 and DMG-04, with independent DMG-06; satisfied |
| Downstream surface or explicit HP-engine boundary | DMG-07; satisfied at the permitted source-facing boundary |
| Major damage-layer evidence partition | Section 11; satisfied, generic mathematics remains open |
| Heterogeneous sample and generic/local separation | Monster versus Aglaea/Aventurine, sections 2/12; satisfied |
| Unknowns, presentation and runtime boundary | Sections 4/11/13; no runtime changes or numerical reproduction claim |

The PR checkpoint records actual local documentation checks, remote content identity, final head and Draft status after writing. No broad W04 checkbox, source-family classification or R0 contract is changed by this record.

## 16. Exact-pin replay index

Replay means repeatable source inspection, not a runtime replay. The following links all select the same authoritative revision. Read only the listed rows/nodes and necessary context.

| Key | Exact raw file / complete blob SHA | Occurrence / fields to inspect |
| --- | --- | --- |
| M1 | [MonsterConfig][M1]; `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` | First row, MonsterID1002011: template and SkillList; separate numeric-collision row follows |
| M2 | [MonsterTemplateConfig][M2]; `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` | First row, template1002011: JsonConfig; bases are not damage output |
| M3 | [MonsterSkillConfig][M3]; `b6cbf024dd00a13fee5578d0e3eca101d467a1e6` | First row, Skill100201101: Skill04, ParamList[0]=2 |
| M4 | [Monster CharacterConfig][M4]; `9f381d9768cd4d780d642ca3ad7e5dc2f5d14f9f` | Skill04 entry/membership; Floats[-190305622].ReadInfo |
| M5 | [Monster Ability][M5]; `f030e0b7e585353c469dc9bf98a156d2ecb4c9f2` | AbilityList names Skill04_Phase01/Phase02; Phase02 OnStart[5] damage and following finish sites |
| G1 | [Aglaea CharacterConfig][G1]; `aa02558dd5138b426ec26e205ad696c077c6fa29` | Skill01/passive entry; Rank01/Rank02 ReadInfo bindings |
| G2 | [Aglaea Ability][G2]; `c1993e2663dfcd0748e45b421411f7f4fdc093e8` | Skill01_Phase02; GoldenSword mark; PassiveSkill01 installation; Rank02_Listen/Effect callbacks |
| A1 | [AvatarConfig][A1]; `7ef386fe8256f1374c693e4962e7599249aac9db` | AvatarID1304: ordinary JsonPath, SkillList, RankIDList and Release; display/manikin paths not execution authority |
| A2 | [Aventurine CharacterConfig][A2]; `092c497b64e381ac3e49f6bfc3198d755e7e326f` | Skill01/Skill03/passive entry; Skill01[0], Skill03[1..3], Rank02[1..2] bindings |
| A3 | [Aventurine Ability][A3]; `67212a729fcfbae03093549b69194e6987968d6c` | Skill01_Phase02; Skill03_Phase02; ResistanceDown and CritDmgIncrease callbacks; trace path is partial |
| A4 | [AvatarSkillConfig][A4]; `a5416ced941c247d475b2aaa83277b9cdf474dd9` | Skill130401 Level1 ParamList[0]=0.5; Skill130403 Level7 ParamList=[7,2.295,0.1275,3] |
| R1 | [AvatarRankConfig][R1]; `ecd3581d9307d3ac94123e0c30983ef6e627f4f3` | Rank140201=[0.15,20]; Rank140202=[0.14,3]; Rank130402=[1.2,0.12,3]; retain namespace/trigger keys |

[R0]: battle_execution_language_core_v1.md
[W17]: global_shared_reverse_scan.md
[M1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterConfig.json
[M2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json
[M3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterSkillConfig.json
[M4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
[M5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_W1_CocoliaP1_01_Ability.json
[G1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Aglaea_00_Config.json
[G2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json
[A1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarConfig.json
[A2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Aventurine_00_Config.json
[A3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aventurine_00_Ability.json
[A4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[R1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarRankConfig.json
