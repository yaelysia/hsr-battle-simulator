# Weakness / Toughness / Break Vertical Slice v1

## 1. Metadata, authority and result

- Thread: `R2-TOUGHNESS-BREAK-VERTICAL-SLICE-V1`; PR #8; research date: 2026-09-09.
- Continuation: `R2-C1-STANCE-INPUT-PROVENANCE`; incorporates the user's revised R2 exit condition, without starting another phase.
- Research baseline: `db1cfe15c97aa7447bfe768dcb6c88b0cd68d2a0`. The actual PR head matched the planning head at startup.
- Raw authority: `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`, not its default branch or a current-live formula.
- Maturity: `manually_confirmed` for explicitly identified occurrences/edges; the unresolved links below are not promoted by association.
- Authority class: `battle_authoritative` for the retained operation/input edges; `mixed_requires_filter` for their containing files. Scope verdict: `include` at those edges, `mixed` at file level.
- Confidence: high for inspected literal operands, named installation/callback paths and distinctions; no numerical claim for unavailable evaluators.
- **Research result: `complete` for bounded R2 v1 under the C1 revised exit condition**, not `W06 mechanism_closed` or numerical reproduction. The primary numeric value is still unknown.
- `stance_value_primary_provenance=shared_injection_export_gap`; classification: `export_gap` at the producer/injection boundary, distinct from the downstream Stance evaluator's `engine_consumer_unavailable` boundary.
- Independent explicit input: Monster `4052010`, Skill `405201002`, `SkillParam(Skill02,Index=1)=30`, hash `1127134183`, consumed by `Monster_W2_Mecha02_02_DeathRattle_Insert` (WTB-13).
- Publication evidence belongs to the actual PR commit/checkpoint; this record does not assert its own future commit SHA. The earlier local-only/partial draft is superseded by this amended record, not retained as a competing authority.
- Runtime/business/lowering/IR changes: **none**. Runtime/Fast/Direct/numerical reproduction: **not performed / not claimed**.

The C1 correction permits a named, bounded injection export gap instead of forcing an unexported Avatar loader to be recovered. Three ordinary Avatar consumers and their complete character binding dictionaries were reread; a two-round, three-surface-family review found no exported field-to-hash bridge. An independent ordinary typed input chain is closed. This satisfies the revised exit condition without supplying Asta with 30, 10, zero, or any other number. It is not a whole-corpus absence theorem or proof of a particular native loader implementation.

Authority remains BATTLE_SCOPE/evidence contract -> current worklist/inventory -> corrected detailed evidence, including [R0] and [R1] -> historical reconciliation/comments. No previously corrected omission, IL-family, Together, OneMore or opaque-Asta conclusion is restored.

## 2. Gameplay semantic model and reuse

The navigation model supplied by the R2 task is an attack that can affect both HP and toughness, a target with elemental weaknesses, a break transition with elemental consequences, and later recovery. It creates separate questions about attack element, target weakness, current/max Stance, break attribution, status lifetime and cleanup. It does not supply the answers to the arithmetic or scheduling questions.

No gameplay observation or external numerical corroboration was performed in this slice. The model is used as a completeness oracle, not evidence that a particular attack must break after a particular number of hits. The analyzed pair is an analyst-selected ordinary-combat scenario, not an observed fight or a newly proven stage lineup.

Reuse [R0] P1/P5/P6/P9 for parameters/hashes/operands/injection, E1/E2/E3/E6 for invocation caster/ability target/parameter entity/modifier holder, and D1/D2/D3/D7 for entry/phase/passive/callback. Reuse [R1] DMG-01/02/07 for the separation of damage request, explicit formula selector and logical hit occurrences. None of those records establishes a numerical interpretation of the Stance operand below.

## 3. Primary attacker and target: why the sample changed

The R1 Aventurine Skill01 remains a structural comparison: its attack is explicitly Imaginary and has a dynamic StanceValue. The familiar target `MonsterID=1002011`, however, explicitly lists **Fire and Thunder**, not Imaginary, in its weaknesses. Its separately authored Imaginary resistance is `0.2`. This makes Aventurine versus that target a poor baseline for a simple static matching example; it is not evidence that the attack does zero toughness damage. [A0], [T0], [R1]

Primary pair: **Asta Skill01, AvatarID 1009, against ordinary MonsterID 1002011**. Asta is already an ordinary R0 anchor. Its Fire basic attack removes the random bounce dependency and provides a literal element occurring in the target's weakness list. Firefly/Sam is added only for the concrete non-matching/weakness-attachment discriminator, not as a replacement primary or a complete character study.

`AvatarConfig[1009]` explicitly gives `JsonPath=Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json`, `DamageType=Fire`, `Release=true` and `SkillList` including `100901`. [A0] The Skill100901 Level4 row has `SkillTriggerKey=Skill01`; ConfigCharacter declares `UseType=SelectEntity`, `TargetInfo=EnemySelect`, and `EntryAbility=Avatar_Asta_00_Skill01_Phase01`. Phase01 invokes Phase02 on Caster; Phase02's damage target is AbilityTargetEntity. [A1], [A2], [A3]

## 4. WTB-01 — Weakness is not resistance or template StanceType

`MonsterConfig[MonsterID=1002011]` explicitly joins `MonsterTemplateID=1002011`, `HardLevelGroup=1`, `EliteGroup=1` and `SkillList=[100201101]`. Those reference fields, not equal numbers, establish the identity. [T0]

| Surface | Exact sample input | Scope of conclusion |
| --- | --- | --- |
| Concrete weakness membership | `MonsterConfig.StanceWeakList=[Fire,Thunder]` | An element-list input on the concrete monster record. It is not a resistance scalar. |
| Concrete elemental resistance | `DamageTypeResistance`: Physical/Ice/Wind/Quantum/Imaginary each `0.2` | A separate list of typed numerical inputs. No final RES formula or default for omitted elements is inferred. |
| Concrete control resistance | `DebuffResist[STAT_CTRL_Frozen]=1` | Separate again; it does not establish an Ice weakness or a generic chance equation. |
| Template field | `MonsterTemplateConfig[1002011].StanceType=Ice` | Not substituted for the concrete Fire/Thunder weakness list. This occurrence alone does not decode that field's full purpose. |

The independent concrete row `MonsterID=1002012` has `StanceWeakList=[Fire,Quantum]` and a different resistance list that includes Thunder. This is a narrow representation cross-check, not permission to merge the two monsters or their template/config references. [T0], [T1]

## 5. WTB-02 — Static construction versus current/max battle state

The primary template supplies `StanceBase=60`, `StanceCount=1`, `StanceType=Ice` and its explicit JsonConfig. Its concrete row supplies `StanceModifyRatio=1` and group context. [T0], [T1] The already-corrected [monster record][MONSTER] supplies the ordinary HardLevelGroup/StanceRatio and phase-input topology; this slice does not reopen its final-stat work.

```text
StanceBase / concrete Stance inputs / ordinary HardLevelGroup inputs
  -- configured-spawn operator unavailable --> configured battle Stance

AttackData.StanceValue
  -- Avatar input-injection export gap; match/arithmetic unavailable --> current Stance change

break template: SetDynamicValueByProperty(ParamEntity, Value=MaxStance)
recovery: ResetStance(ModifierOwnerEntity), SetStanceCount(ModifierOwnerEntity)
```

The last two lines are real battle-facing read/reset surfaces, independent of whether the spawn constructor is exported. `MaxStance`, a Stance damage operand, and `StanceCount` must remain distinct. This record does **not** prove a numeric current-Stance getter or zero-threshold implementation for the attack; it does prove the explicit MaxStance read and later reset requests. [S1], [S3]

Do not calculate `60 * StanceRatio`, decide where a flat contribution belongs, or call 60 the target's final toughness. No encounter level/final build has been fixed for a numerical reproduction.

## 6. WTB-03 — Stance input provenance: shared consumer, missing injection

The Asta Phase02 damage node contains both ordinary damage and toughness-facing operands in one `RPG.GameCore.DamageByAttackProperty` request. Its battle-facing projection is shown below; presentation fields also exist in the complete raw object. [A3]

```json
{
  "$type": "RPG.GameCore.DamageByAttackProperty",
  "TargetType": {"$type": "RPG.GameCore.TargetAlias", "Alias": "AbilityTargetEntity"},
  "AttackProperty": {
    "$type": "RPG.GameCore.AttackData",
    "DamageType": {"DamageType": "Fire"},
    "DamagePercentage": {"IsDynamic": true, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [-1126825319]}},
    "StanceValue": {"IsDynamic": true, "PostfixExpr": {"OpCodes": "AQAR", "FixedValues": [], "DynamicHashes": [1659254037]}},
    "SPHitRatio": {"IsDynamic": false, "FixedValue": {"Value": 1}}
  },
  "CanTriggerLastKill": true
}
```

| Operand or proposed producer | Evidence | Verdict |
| --- | --- | --- |
| DamagePercentage | Skill100901 Level4 `ParamList[0]=0.8` -> Asta `ReadInfo(SkillParam,Skill01,Index=0)` -> hash `-1126825319` -> damage node | Closed damage coefficient; **not** a toughness coefficient. [A1-A3] |
| StanceValue | Same node reads `1659254037` through `AQAR` | Exact consumer, performer and target closed; producer/injection classified as the bounded shared injection `export_gap` below. Numeric value/index unknown. |
| Possible table-side Stance values | The same Level4 row has `ShowStanceList=[30,0,0]`, `StanceDamageDisplay=10`, `StanceDamageType=Fire` | Literal table facts, but no inspected edge selects either 30 or 10 into `1659254037`. Neither is promoted as the answer. [A1] |
| SkillParam index for Stance | Asta's inspected Floats dictionary maps the ordinary coefficient and trace/rank parameters; it does not give this Stance hash a SkillParam index | Record the missing binding, not a guessed slot. [A2] |
| Explicit gates/defaults at the damage node | No explicit StanceDamageType, weakness gate, ForceStanceDamage flag, HitSplitRatio or separate Stance task is serialized in this particular request | Occurrence-local absence, not default zero/false, no universal gate, or absence of toughness mechanics. [A3] |

### 6.1 Ordinary cross-samples, not three new discoveries

The following planning-provided corrections were independently reread at the pin. Their role is corroboration of the consumer pattern, not a claim that C1 discovered them. In each case the character's selectable Skill01 dispatches Phase01 -> Phase02 on Caster; damage addresses AbilityTargetEntity. [A2], [A3], [D0], [D1], [H0], [H1]

| Ordinary actor / occurrence | Actual Stance consumption | Character dictionary and separate damage binding |
| --- | --- | --- |
| Asta Skill01 Phase02 `OnStart[7]` | Fire; `AQAR`, hashes `[1659254037]` | Complete `DynamicValues.Floats` has no `1659254037` entry. `-1126825319` independently binds `SkillParam(Skill01,0)`. |
| Dan Heng Skill01 Phase02 `OnStart[2]` and `[4]` | Wind; both read `AQAR/[1659254037]`; HitSplitRatio `0.45/0.55` | Same absence from the complete local dictionary, and the same *shape* of independent damage binding; not a shared actor parameter environment. |
| Gallagher Skill01 Phase02 `OnStart[2]` and `[5]` | Fire; both read `AQAR/[1659254037]`; HitSplitRatio `0.5/0.5` | Same dictionary absence and independent `-1126825319 -> SkillParam(Skill01,0)` binding. |

The corresponding ordinary AvatarSkillConfig rows were inspected: Asta `100901/Lv4/Skill01/ParamList[0]=0.8`, Dan Heng `100201/Lv1/Skill01/ParamList[0]=0.5`, Gallagher `130101/Lv4/Skill01/ParamList[0]=0.8`. Each has `ShowStanceList=[30,0,0]` and `StanceDamageDisplay=10`; their StanceDamageType is respectively Fire/Wind/Fire. These are real neighboring table fields, **not an inspected loader edge** into the common hash. [A1]

Asta Skill02 additionally uses the hash in its first-hit request; its bounce continuation preserves `AQAAAAQR`, fixed operand `0.5`, hashes `[1659254037]`. Do not describe the bounce expression as an unmodified `AQAR` read or infer a generic per-hit reduction from the other samples' HitSplitRatio. The opaque bounce selector remains R0's `GLOABNLLLEL`. [A3], [R0]

### 6.2 Bounded provenance investigation and stopping record

Round 1 inspected the three specified character dictionaries, basic entry/phase call sites, Asta Skill02 context and their selected skill rows. No fourth Avatar was added. The shared-input hypothesis was prioritized because the Stance consumer repeats while the ordinary damage coefficient has an explicit, distinct actor binding. This evidence alone does not identify the native injection mechanism.

Round 2 followed only the following three source-family surfaces. Directory/file existence and keyword lookups were navigation, not semantic promotion; missing search hits were not absence evidence.

| Surface / concrete navigation signal | Exact inspected extent and result | Stop boundary |
| --- | --- | --- |
| Common Avatar Ability: all three configs explicitly reference `Avatar_Common_PassiveSkill` | Its complete OnStart installs Local_SPAdd (named input 10), TriggerStanceCountDown_Test and MAvatar_Common_TriggerDeparted. Its declared Floats are `-1800273296,142612140,-1293338785,-276098552,-2054634397`, all Type=None. There is no input map for `1659254037` at this entry. [S2] | This is a real common passive installer, not a recovered per-skill Stance loader. Existing break callbacks are reviewed below, not searched as a new census. |
| GlobalConfig shared declarations/config registry: prior R2 exposed `AllCharacterDynamicValues` | That complete map in GameCoreConstValue contains only `-1030509054,-179683352,2073292217`, all Type=None. GameCoreConfigPathInfo is an actual path registry, not field/index-to-hash preprocessing. The pinned GlobalConfig directory was checked for a concrete next context/skill source; no such bridge was identified. [G0], [G1] | Stance constants and registered paths do not establish numeric injection. No generic engine formula search or unrelated global family expansion. |
| Registered `Config/ExcelOutputGameCore/` path, named explicitly in GameCoreConfigPathInfo | Exact-pin Contents request for this path returned `404 Not Found`. This identifies an unavailable registered path in the inspected export; it does not say populated `ExcelOutput/AvatarSkillConfig.json` is missing. [G1] | No replacement from a default branch, IL/RtBattle, or similarly named directory. The registry does not prove the missing path would contain this particular injector. |

**Outcome A2 — `export_gap`: ordinary shared StanceValue consumer is present; authoritative `1659254037` skill-context injection/producer is not exported in the inspected pinned surfaces.** The specific gap name is **shared skill-context StanceValue injection export gap**. The inspection set and stopping rule above bound that statement. A native/common invocation input is a supported architectural hypothesis, not a recovered allocator, source field, numeric constant or inheritance rule. There is no identified, untraversed exported producer edge in this bounded investigation.

The classification concerns the missing *producer/injection/loader*. It must not be relabeled merely as the already-known final Stance mutation `engine_consumer_unavailable`. Those are two different missing links. Reopen this input gap only with a new concrete authoritative source/bridge, not more identical consumers or renewed keyword sweeps.

### 6.3 WTB-13 — Independent ordinary typed Stance producer

This is the C1 discriminator that completes the explicit-input obligation without changing the primary Asta/Monster1002011 pair. The ordinary owner is established through **StageConfig[1012260]**, `StageType=FarmElement`, `Release=true`, `LevelGraphPath=Config/Level/StageCommonTemplate.json`, empty StageAbilityConfig/SubLevelGraphs, and `MonsterList[0].Monster0=4052010` (also Monster2). Its Level24/HardLevelGroup1/EliteGroup6 are encounter inputs only. This is an ordinary farm battle, not its reward/upgrade process, an event-only entity, or an IL/RtBattle collision. [Q0]

```text
StageConfig[1012260].MonsterList[0].Monster0 = 4052010
 -> MonsterConfig[MonsterID=4052010]
      MonsterTemplateID=4052010
      SkillList=[405201001,405201002,405201003,405201004]
      OverrideSkillParams=[]
 -> MonsterTemplateConfig[4052010].JsonConfig
      Config/ConfigCharacter/Monster/Monster_W2_Mecha02_02_Config.json
 -> MonsterSkillConfig[SkillID=405201002]
      SkillTriggerKey=Skill02; ParamList=[0.15,30]
 -> CharacterConfig.DynamicValues.Floats["1127134183"].ReadInfo
      Type=SkillParam; TriggerKey=Skill02; Index=1  // zero-based
 -> SkillList[Name=Skill02].EntryAbility
      Monster_W2_Mecha02_02_DeathRattle_Insert
 -> AbilityList[Name=that ability].OnStart[5]
      TriggerAnimStateWithMove.EventList[2].TaskList[1]
 -> DamageByAttackProperty(AllTeammate)
      AttackData.StanceValue = AQAR / hashes[1127134183]
      raw authored input = 30
```

Each identity/reference/binding/consumer edge above is `manually_confirmed`. The MonsterConfig row's absence of skill overrides applies only to this chosen instance. A nearby concrete MonsterID `405201002` is **not** the SkillID merely because it has the same number. The template's explicit JsonConfig, not an icon, formation string or filename prefix, selects the character config. [T0], [T1], [M0], [M1], [M2]

The exact damage node also declares `DamageType=Ice`, `StanceDamageType=Ice`, `AttackType=Normal`, and `FormulaType=ByMaxHP`. Its **different** DamagePercentage hash `-1847083384` binds `Skill02,Index=0`, value `0.15`. FormulaType is not used to reinterpret the Stance input. The operation targets **AllTeammate**, while the enclosing Skill02/ability TargetInfo is **AllTeamMember**; do not normalize either to AllEnemy. [M0], [M1], [M2]

Ordinary lifecycle reachability is separately visible: PassiveSkill01 -> PassiveSkillInitiate -> self-installed MMonster_W2_Mecha02_02_DeathRattle -> OnDeathrattle -> TurnInsertAbility with the same named callee and priority MonsterDeathRattle. This supports a real ordinary battle call site; it does not derive omitted insert context defaults, normal-action accounting or universal death order. The damage is nested inside an animation event wrapper (authored normalized time `0.57`): its battle mutation cannot be discarded with the camera/effect siblings, and that time is not AV. [M0], [M1]

**Closed:** source value 30 -> zero-based SkillParam binding -> StanceValue consumer, with ordinary ownership and literal operands. **Not closed:** the resulting Stance subtraction, friendly-target matching/force behavior, final toughness units, or any loader/value rule for Avatar `1659254037`. One explicit Monster producer proves that this typed shape exists; it does not repair the separate Avatar injection gap.

## 7. WTB-04 — Matching and a concrete non-matching exception

Asta's attack Fire and the target's `StanceWeakList` Fire establish a static membership comparison. They do not implement the actual battle-time match rule, effective weakness aggregation, Stance subtraction or per-hit scaling. In particular, the record does not conclude `match=100%`, `non-match=0`, or `HP damage implies Stance damage`.

A bounded ordinary counterexample is available without scanning more characters. `AvatarConfig[1310].JsonPath` selects the Sam ConfigCharacter; Skill11 is an EnemySelect entry and calls its Phase02. The first inspected damage block is preceded by: [A0], [X0], [X1]

```text
ByAnd(
  BySkillPointActivated(PointB1),
  ByHasStanceWeak(AbilityTargetEntity, WeakType.Fire, Inverse=true))
 -> AddModifier(Caster, MAvatar_Sam_00_ForceStanceDamage)
 -> DamageByAttackProperty(AbilityTargetEntity,
      DamageType.Fire, StanceDamageType.Fire,
      StanceValue=hash1659254037, HitSplitRatio=0.15)
 -> RemoveModifier(Caster, MAvatar_Sam_00_ForceStanceDamage)
```

The modifier carries `BehaviorFlagList=[ForceStanceDamage]`; its OnStack writes `StackProperty(ModifierOwnerEntity, ForceStanceBreakRatio, hash547956141)`. Sam ConfigCharacter binds that hash to `SkillTreeParam(PointB1,Index=0)`. This closes the authored condition/install/property/request/removal interface. The trace's numerical value, the flag's consumer mathematics, and whether it bypasses particular locks are not resolved here. [X0], [X1]

The inspected failed branch is empty: it is not an explicit `StanceValue=0` branch. The predicate implementation and aggregation of base/attached/suppressed weaknesses remain engine-owned. The raw constant `StanceWeakRatio=1` and `DefaultStanceResistance=0` in GameCoreConstValue do not fill that evaluator. [G0]

## 8. WTB-05 — Runtime weakness attachment and its cleanup boundary

Ordinary Sam Skill21 has a separate explicit attachment path, not just an ignore-weakness flag. ConfigCharacter declares its selectable EnemySelect/adjoin entry; Phase01 calls Phase02. Phase02 adds `MAvatar_Sam_00_Skill21_FireWeakType` to **AbilityTargetEntity**, with lifetime hash `237049100`, bound to `SkillParam(Skill21,Index=3)`. [X0], [X1]

That modifier carries `STAT_AttachWeakness`, `Stacking=ReplaceByCaster`, and:

```text
OnStack -> StackWeakness(
  TargetType=ModifierOwnerEntity,
  OPType=Attach,
  WeakList=[Fire])
```

This is a real runtime weakness mutation surface; the concrete static StanceWeakList cannot alone represent all runtime weakness state. The inspected modifier does not serialize an OnDestroy detach task. Its lifetime input and modifier ownership are known, but revocation at expiry, overlapping attached weaknesses, pre-existing Fire weakness preservation and native stack cleanup are **not proven**. Do not invent a `RemoveWeakness` opcode or a simultaneous resistance change. [X1]

Weakness protection/lock coverage remains partial. The same reviewed sources expose `SkipLockTeamStance` on recovery, a `StanceLock` constant, and `MuteAttachWeakness -> STAT_AttachWeakness` in the global immunity map; a named AI group mentions LockWeakness. Those are not a closed ordinary protection installer/evaluator. Do not elevate the AI group name or constant into a universal rule. [S1], [G0], [X0]

## 9. WTB-06 — Break transition: exact target-side listener, hidden threshold

The primary monster's ConfigCharacter explicitly declares `PassiveSkill05 -> Monster_Common_PassiveSkill_StanceBreak_Action` and includes that ability. This common ability has TargetInfo Caster and installs `Local_ListenStanceBreak` on Caster. [T2], [S0]

```text
attack Stance evaluation / threshold test / event emission [engine boundary]
 -> Local_ListenStanceBreak.OnBeingBreak
 -> AddModifier(ModifierOwnerEntity, StanceBreakState, AliveOnly=false)
 -> RemoveModifier(ModifierOwnerEntity, MonsterAllDamageReduce)
```

The holder of the break state is therefore the target monster through the inspected self-passive/holder chain. The handler contains **no explicit `Stance == 0` or `Stance <= 0` predicate**. Threshold crossing, underflow, repeated-hit suppression and the emission of OnBeingBreak belong to the missing attack/Stance consumer, not to a recovered JSON comparison. The semantic phrase “reaches break condition” names this interface, not an independently demonstrated zero equation.

The common passive also installs `Local_ListenRedStance` and `TriggerStanceCountDown_Monster`. The former has separate OnEnterRedStance/OnEndBreak handling. Their presence does not prove that every ordinary target enters a second Stance regime. These are separately routed residuals, not folded into the primary break transition. [S0]

## 10. WTB-07 — StanceBreakState, attribution and normalized delay

The complete inspected StanceBreakState definition declares `BehaviorFlagList=[Break]`, `LifeStepMoment=ModifierPhase1End` and no explicit numeric LifeTime. [S1]

| Callback | Actual state-facing work | Boundary |
| --- | --- | --- |
| OnCreate | Add StanceBreakState_Effect to ModifierOwnerEntity; ModifyActionDelay on that holder with **AddNormalizedValue=0.25**; TriggerBreak targeting **Caster** | A creation-hook delay, not a proven AV formula, normal-turn grant, or a callback repeated on every hit. Native reapplication rules remain unknown. |
| OnStack | Add MCommon_MonsterBreak_ActionBarText to holder | This auxiliary modifier supplies UI hints; it is not the numeric break producer. |
| OnEndBreak | RemoveSelfModifier | Explicit recovery/lifecycle entry; the engine producer and timing of OnEndBreak are not recovered. |
| OnDestroy | Remove effect; ResetStance; SetStanceCount; restore MonsterAllDamageReduce; remove action-bar text | Expanded in section 13; no restored amount is serialized. |

**TriggerBreak's literal target is Caster, not DamageAttackerEntity or ParamEntity.** The immediate installer is the target-side listener. Record this caster/holder distinction rather than silently assigning Caster to the breaking avatar. The native break-attribution transport and the relationship between this TriggerBreak operation and the attacker's OnTriggerBreak notification are engine boundaries. [S0], [S1], [S2]

The separate `StanceBreakState_Effect` contains a SwitchCaseByAttackDamageType reading DamageAttackerEntity, but the inspected branches select effects. That visual switch is **not** the authoritative dispatcher for the numeric Fire consequence below. [S1]

## 11. WTB-08 — Element dispatch: an actual Fire predicate, not a name match

Asta ConfigCharacter explicitly installs the common avatar passive through PassiveSkill02. `Avatar_Common_PassiveSkill` targets Caster and its OnStart installs `TriggerStanceCountDown_Test` on AbilityTargetEntity. The common modifier has an **OnTriggerBreak** callback. The `_Test` suffix does not make this path non-battle. [A2], [S2]

The actual Fire branch is `ByCharacterDamageType(ModifierOwnerEntity, DamageType=Fire) -> IncludeTaskListTemplate(StanceBreak_Fire)`. The template is a named entry in the consolidated GlobalTaskListTemplate file. [S2], [S3]

Thus this dispatcher tests the common modifier holder's **character DamageType**, not a literal read of the incoming AttackData.DamageType. Asta's AvatarConfig Fire and the primary request Fire agree in this simple sample. That agreement does not prove how overridden attack elements, alternate attribution or servants are handled generically.

The template addresses ParamEntity as its break target. Its role as the notified break target is the source-level interpretation of this paired callback/template path; the native callback argument construction/transport is not exported here. Do not substitute either the template caster or the generic break-state holder without preserving the event boundary.

OnTriggerStanceCountDown is a separate callback in the same common modifier, with a ByCompareStanceCount gate and `StanceCountDown_*` templates. It is not an alias for OnTriggerBreak. Its count-decrement regime is not expanded in this v1. [S2]

## 12. WTB-09 — Fire initial damage, status damage and presentation

The Fire template has four authored tasks. Their serialized positions identify local operations, not a universal engine death/break order. [S3]

| Task | Actual operands | Consequence and limit |
| --- | --- | --- |
| SetDynamicValueByProperty | `DynamicKey=TargetStance`, `ReadTargetType=ParamEntity`, `Value=MaxStance` | Reads target max Stance, not a new static spawn formula or the current remaining meter. |
| AddModifier | ParamEntity; `MCommon_Element_Burn`; Chance `1.5`; LifeTime `2`; injected `MDF_DamagePercentage=1` | Break-associated status request. Chance is an input, not a final 150% probability. |
| DamageByAttackProperty | ParamEntity; Fire; `FormulaType=ByBreakDamage`; `AttackType=ElementDamage`; `FinalFormulaType=ByPureDamage`; `CanTriggerLastKill=true` | Separate initial break-damage request, not the basic attack's DamagePercentage. |
| TriggerEffect | ParamEntity; Fire effect asset | Presentation, not the damage evaluator. |

The initial request's BreakDamagePercentage preserves the exact expression: `OpCodes=AAAAAAEAAQEFAgQAAQUR`, `FixedValues=[2,4]`, `DynamicHashes=[-1293338785,-276098552]`. No complete numerical producer chain for all these operands, expression arithmetic, ByBreakDamage formula, mitigation bypass or rounding is claimed. A `ByPureDamage` token alone does not prove all bypass rules. [S3]

The installed **MCommon_Element_Burn** is a different modifier from both StanceBreakState and Asta's trace-applied **MCommon_DOT_Burn**. Its source-facing lifecycle is: [S1], [A3]

```text
MaxLayer=1; LayerAddWhenStack=1; LifeStepMoment=ModifierPhase1End
BehaviorFlagList=[STAT_DOT,STAT_DOT_Burn]
UseSnapshotEntity=true; Stacking=ReplaceByCaster
OnStack -> SetDynamicValueByModifierValue(holder, ValueType=Layer, DynamicKey=_Layer)
OnPhase1 -> DamageByAttackProperty(holder,
  Fire, FormulaType=ByBreakDamage, AttackType=DOT,
  DamageTag=[{EnumIndex:3,Value:32}],
  BreakDamagePercentage: AQABAQQR / hashes[1486739431,1912601768],
  FinalFormulaType=ByPureDamage)
```

The injected percentage and layer working value have a callback consumer. OnCustomEvent exposes a separate DOT request with expression `AQABAQQBAgQR` and extra hash `375103313`; its ordinary trigger producer is not closed by this slice, so that additional trigger is not promoted. Snapshot capture, status application probability and generic lifetime decrement/destruction implementation stay bounded.

## 13. WTB-10 — Recovery/reset is an explicit separate path

```text
StanceBreakState.OnEndBreak
 -> RemoveSelfModifier
 -> [native removal/destruction lifecycle]
 -> StanceBreakState.OnDestroy
    RemoveModifier(holder, StanceBreakState_Effect)
    ResetStance(holder, ForbidWhenEmpty=false, SkipLockTeamStance=true)
    SetStanceCount(holder)  // no explicit Count/value operand
    AddModifier(holder, MonsterAllDamageReduce, AliveOnly=false)
    RemoveModifier(holder, MCommon_MonsterBreak_ActionBarText)
```

This is a source-facing recovery contract, not merely “Stance becomes zero.” The source explicitly restores the common mitigation modifier; its OnStack contributes `AllDamageReduce=0.1`. The final numeric effect of that property remains W04. [S1]

Neither ResetStance's restored amount nor the default count of SetStanceCount is serialized. Do not replace the calls with “recover to full toughness” or “count becomes one.” The source does not serialize removal of MCommon_Element_Burn in this cleanup: break-state recovery and the independently lifetime-governed burn are separate authored surfaces. This local distinction does not exclude additional engine cleanup.

The normalized +0.25 operation is in **OnCreate**, not this recovery callback. No scheduler conversion, requeue policy or universal “only once ever” rule is inferred. `LifeStepMoment=ModifierPhase1End` alone supplies neither a numeric break duration nor the exact time of OnEndBreak.

The separately exported Monster_ChangePhase template uses `ExitBreakState(Caster,CancelRecoverAnim=true)`, `ResetStance(Caster,ForbidWhenEmpty=false)` and SetStanceCount alongside HP/phase work. Its ordinary phase context is retained from [MONSTER]; this is not a newly demonstrated call on Monster1002011 and is not natural break recovery or wave respawn. [S3]

## 14. WTB-11 — Local order versus hidden hit/death arbitration

Closed local dependencies are the monster passive installing its listener; the listener's OnBeingBreak installing the shared state; the state's configured creation work; the avatar OnTriggerBreak Fire branch invoking its template; the template installing burn; and burn's own callbacks consuming its inputs. Recovery has its separate event/removal/destruction path.

Three joins must remain visible gaps: **Stance arithmetic -> threshold/event**, **TriggerBreak -> correctly attributed attacker callback/ParamEntity**, and **break lifecycle -> OnEndBreak/removal timing**. No JSON list establishes the universal total order of HP damage, Stance loss, break damage, on-hit listeners, death and recovery. AliveOnly=false on a particular installation/reset-related operation is not proof that it outranks death.

## 15. WTB-12 — Super Break contrast, not a second full vertical slice

Reuse [GLOBAL]'s closed ordinary topology: StageCommonTemplate -> StageAbility_BattleCommonRule -> target-side SuperBreak state -> ordinary Sam passive -> DealSuperBreakDamage. That topology is not newly rediscovered or downgraded here.

The narrow reread supplies two discriminators. Sam's `MAvatar_Sam_00_PointB2_SuperBreakBuff` invokes DealSuperBreakDamage from **OnAfterAttack, Priority=100**, with an AttackTargetList argument and conditional inputs. The shared template reads or accepts a total-Stance-damage working value, including copying `MDF_TotalStanceDamage` from `MStageAbility_BattleCommonRule_SuperBreak_SubOnEnemy`, then emits a separately tagged break-formula damage request when its working-value test succeeds. [X1], [S3]

Its request has `DamageTag=[{EnumIndex:3,Value:33}]`, ByBreakDamage, ElementDamage and ByPureDamage. `DisplayData.ElementDamageType=Super` is a display label, not the sole authority for this distinction. This record does not derive the total-Stance accumulator, the template's fallback arithmetic or a full Super Break formula.

Initial break is the OnTriggerBreak -> StanceBreak_Fire path; Super Break is a distinct caller/accumulator/template path. Their reuse of DamageByAttackProperty does not merge them. A template-local variable named StanceValue is not automatically the primary skill hash `1659254037`.

## 16. Heterogeneous checks and limits

The Firefly/Sam checks change the primary discriminator from static matching to **conditional force-Stance state and runtime weakness attachment**. Both have ordinary ConfigCharacter entries and actual downstream operations. They disprove a proposed source model in which an immutable StanceWeakList alone determines every Stance request. They do not determine the generic non-match formula. [A0], [X0], [X1]

The concrete Monster1002012 Fire/Quantum list independently checks the representation, without borrowing Monster1002011's identity. The Super Break contrast changes the event/source path, not just an element label. These are bounded cross-samples; no complete second character, second encounter, all-element census or complete universal state machine is claimed.

## 17. Evidence partition

`closed` applies to the explicitly named input/operation/edge. `partial` means a data-facing link remains unproven. `export_gap` identifies the bounded missing producer/injection described in section 6; `engine boundary` instead identifies the missing generic consumer after inspected endpoints. `candidate` has not earned an ordinary owner-to-consumer closure in this slice. Multiple labels on one layer are intentional.

| W06 layer | Evidence partition | Exact extent / remaining obligation |
| --- | --- | --- |
| Weakness representation | closed | Concrete StanceWeakList; independent resistance/control inputs; runtime StackWeakness Attach sample. |
| DamageType / weakness match | partial + engine boundary | Fire occurrence and membership plus ByHasStanceWeak interface; final effective match evaluator unavailable. |
| Static Stance inputs | closed inputs + engine boundary | StanceBase/concrete context; reuse W14 ratios; no configured-final equation. |
| Current/max Stance state | partial + engine boundary | MaxStance read and ResetStance/SetStanceCount surfaces; no current meter subtraction/getter implementation recovered. |
| Skill StanceValue producer | **closed ordinary shared consumers + shared injection export_gap; independent typed chain closed** | Asta/Dan Heng/Gallagher read 1659254037 without local bindings; bounded C1 A2 result. Monster4052010 Skill405201002 index1=30 ->1127134183 -> StanceValue is closed. Avatar numeric value remains unknown, but the revised R2 v1 exit obligation is satisfied. |
| Non-match behavior | closed local gate + engine boundary | Sam inverse Fire predicate; no universal zero or full-ratio branch. |
| Weakness-ignore / universal Stance damage | closed local flag/property interface; partial numeric chain | ForceStanceDamage and ForceStanceBreakRatio with PointB1 binding; no universal bypass semantics or ratio claim. |
| Stance reaches zero transition | engine boundary + closed event handler | Threshold/comparison not exported in inspected handler; OnBeingBreak -> StanceBreakState is explicit. |
| StanceBreakState | closed source contract | Target-side holder, Break flag, exact callbacks; not synonymous with elemental burn. |
| TriggerBreak | closed call + engine boundary | Literal target Caster; native attribution/event transport not recovered. |
| Element dispatch | closed Fire branch + engine boundary | ByCharacterDamageType(holder,Fire) -> template; not a universal incoming-hit-element mapping. |
| Initial break damage | closed request + partial inputs + engine boundary | Fire ByBreakDamage/ElementDamage/ByPureDamage request; keep expression hashes and math unresolved. |
| Break status / DOT | closed Fire installation/phase consumer + engine boundary | Element_Burn differs from skill DOT; snapshot/chance/timing implementation unavailable. |
| Break action delay | closed operand + engine boundary | OnCreate holder normalized +0.25; no AV/scheduler formula. |
| Break callbacks | closed local surfaces + engine boundary | OnBeingBreak/OnTriggerBreak/OnEndBreak and separate StanceCountDown; no universal order. |
| Recovery/reset | closed reset path + engine boundary | Self-remove/destruction/reset/count/common-mitigation path; exact amount, count and trigger timing unknown. |
| Death interaction | engine boundary / not_proven | No total order, recovery-after-death rule or guaranteed death-trigger behavior inferred. |
| Super Break distinction | closed path distinction; formula deferred | Independent OnAfterAttack/accumulator/template versus initial Fire break. |

Weakness protection installers, generic attached-weakness revocation, the unrelated OnCustomEvent DOT trigger, and alternate RedStance/count-decrement event producers remain partial/candidate residuals as individually described; none is silently declared absent.

## 18. Reusable versus sample-local language

Reusable source-reading rules: retain weakness membership separately from resistance; distinguish the skill Stance operand from ordinary damage; separate current/max/count surfaces; preserve target-side break-state holder and attacker-side notifier as different contexts; resolve the actual element predicate; retain initial damage, periodic status and Super Break as separate requests; trace recovery beyond installation.

Sample-local facts: Monster1002011's Fire/Thunder membership and template inputs; Asta's basic Fire request; Sam's PointB1 inverse Fire gate, ForceStanceDamage property and Skill21 Fire attachment; Fire's exact Chance/lifetime/status/expressions; the inspected common state's +0.25/reset recipe; Monster4052010's typed Skill02 input 30 and peer-targeted inserted request. Do not generalize their constants, callback counts or targets to every actor, element, player or special mode.

The C1 common-hash checks change the input-provenance dimension across three ordinary Avatars. WTB-13 changes both producer shape and actor family, and independently proves ordinary stage reachability. Neither is a fourth primary pair or a census.

## 19. Engine boundaries, negative knowledge and corrections

The accepted pinned artifact boundary remains release data without an exported GameCore implementation tree. It justifies stopping at identified native match/arithmetic/threshold/event/lifecycle/scheduler consumers; it does **not** prove every unresolved data lookup is absent.

Preserve: the scoped shared Stance input-injection **export_gap**, separately from native effective-weakness aggregation and force/lock precedence; configured-final Stance; threshold/event emission; break-attribution transport; break/DOT numeric evaluators and remaining operand bindings; status chance/snapshot/lifetime; reset amount/count; death ordering. No frozen W05/W07/W10/W12/W13/W14/W17 generic search is reopened.

False friends: StanceType Ice versus Fire/Thunder weakness; damage resistance versus status resistance; ShowStanceList 30 versus StanceDamageDisplay 10 versus an unbound Stance hash; display-only damage-type effect switches versus actual element dispatch; `_Test` versus ordinary consumers; Element_Burn versus DOT_Burn; normalized delay versus AV; StanceCountDown versus full break; UI Super labels versus a real independent path; native defaults versus omitted fields.

Additional C1 negative knowledge: identical hash usage across ordinary Avatars does not establish an identical or constant numeric value; ShowStanceList is not automatically StanceValue authority; StanceDamageDisplay is not automatically execution authority; absence from CharacterConfig does not mean StanceValue=0; the explicit Monster SkillParam path does not prove Avatar common-hash semantics. The Monster's 30 is authorized by its own index/consumer, not by its coincidental equality to an Avatar display field.

Large MonsterConfig, MonsterSkillConfig, StageConfig and AvatarSkillConfig Contents reads returned empty or limited text with valid blob SHAs. Exact Git-blob reads recovered the actual rows; no source-absence conclusion follows. Layout files and default-branch searches were navigation only. The failed ExcelOutputGameCore request is for a **registered exact path**, not a guessed whole-corpus absence proof. It is only one scoped negative in the C1 inspection record.

No R0/R1 contradiction requiring a rewrite was established. C1 supersedes the earlier R2 mandatory-blocker wording under the user's revised contract; it does not claim a newly recovered Avatar numeric producer. The original R2 weakness, Fire dispatch/template, StanceBreakState/TriggerBreak/delay/recovery and independent Super Break distinctions were reviewed against their retained pin-scoped anchors. Critical Fire and recovery nodes were freshly reread without contradiction; the earlier mechanism evidence is reused, not counted as C1 discovery.

## 20. Routed dependencies, exit check and next work

| Residual / discovery | Routing and stopping rule |
| --- | --- |
| Primary StanceValue numeric producer/injection | **Named shared injection export_gap; no longer a bounded R2 blocker under C1.** Reopen only on a concrete authoritative field-to-hash bridge. Do not substitute a display value, compiler assumption, Monster input30 or more identical consumers. |
| Force/attached/suppressed weakness aggregation and detach lifecycle | W06/W09 concrete residuals; use Sam's actual installer/predicate as entry, not a global rescan. |
| Local_ListenRedStance, StanceCountDown and RedStanceState | Named W06 child candidates; require event producer and ordinary activation condition before treating them as an additional meter/phase rule. No W19+ consequence is established here. |
| Burn snapshot, status probability, stack/expiry/custom DOT trigger | W09/W12 boundaries or a later bounded status slice; do not reconstruct the generic dispatcher. |
| BreakDamage expressions and Super Break accumulator | W04/W06 later numerical slices only with sufficient producers; no full formula claimed now. |
| SPHitRatio, mitigation restoration, phase reset | W08, W04 and W16 respectively; their entry edges do not authorize unrelated implementation. |

- [x] Ordinary primary attack, actual element, target and Stance consumer occurrence identified.
- [x] Asta, Dan Heng and Gallagher common-hash consumers and complete local-dictionary absence reread; the planning facts are not recounted as discoveries.
- [x] Two-round, three-surface-family provenance inspection completed; Outcome A2 explicitly classified as shared injection export_gap, with unknown numeric value preserved.
- [x] Independent ordinary Stage1012260 -> Monster4052010 -> Skill405201002 index1=30 ->1127134183 -> StanceValue chain manually confirmed.
- [x] Concrete target weakness and static Stance inputs separated from final construction.
- [x] Matching/force/attachment surfaces and their limits recorded.
- [x] Target-side shared break installation, ownership, TriggerBreak and normalized delay traced; hidden threshold and attribution joins named.
- [x] Fire initial damage/status/periodic callback and recovery/reset surfaces traced.
- [x] Initial Break, skill DOT, generic broken state and Super Break distinguished.
- [x] Bounded heterogeneous cross-samples and all 18 requested evidence-partition layers present.
- [x] Generic ordering/arithmetic unknowns retained; runtime unchanged.

The C1 delivery changes only this R2 durable record, retaining the earlier downstream work. No broad W06 worklist checkbox is checked, no whole source family is reclassified, and R0/R1 are not rewritten. The narrow producer-gap classification is kept here rather than creating a competing index or batch governance update. `complete` means that the **revised bounded v1 exit condition** is met; it does not close the numerical export gap, generic W06 mechanism, all Stance opcodes, all elements or runtime behavior.

**Next:** return this R2 checkpoint for direction correction. W05/W09 is not started or automatically dispatched. Further research on the primary injection requires new source evidence, not repetition of the exhausted bounded search.

## 21. Exact-pin replay index

All following raw references use the same pinned revision. Codes identify files; named records/abilities/modifiers identify occurrences, not equal numeric IDs in other families. Blob identity is a replay aid, not semantic proof.

| Code | Raw source / exact blob | Occurrences used |
| --- | --- | --- |
| A0 | [AvatarConfig][raw-a0] — `7ef386fe8256f1374c693e4962e7599249aac9db` | Avatar1009 JsonPath/Fire/SkillList; Avatar1304 Imaginary comparison; Avatar1310 JsonPath/Fire. |
| A1 | [AvatarSkillConfig][raw-a1] — `a5416ced941c247d475b2aaa83277b9cdf474dd9` | Skill100901 Lv4,100201 Lv1,130101 Lv4: Skill01 rows, separate ParamList damage coefficients and display fields; no field-to1659254037 bridge. Git-blob fallback. |
| A2 | [Asta ConfigCharacter][raw-a2] — `147dfdfb5b6170e0371bc0a105d5342868e8f025` | Skill01 entry/target, PassiveSkill02 common entry, complete Floats binding dictionary. |
| A3 | [Asta Ability][raw-a3] — `b2a03d625fe8628eb927bd198d4108e5f7ba70b7` | Skill01 Phase01/02, sole basic damage request and adjacent trace DOT; Skill02 Stance consumer as bounded navigation. |
| T0 | [MonsterConfig][raw-t0] — `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` | Monster1002011 explicit references, weakness/resist lists and StanceModifyRatio;1002012 comparison;4052010 template/SkillList/empty OverrideSkillParams. Git-blob fallback. |
| T1 | [MonsterTemplateConfig][raw-t1] — `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` | Template1002011 StanceBase/Count/Type;4052010 exact JsonConfig -> Mecha02_02, not the LocalLegend/TimeSlow sibling. |
| T2 | [Target ConfigCharacter][raw-t2] — `9f381d9768cd4d780d642ca3ad7e5dc2f5d14f9f` | PassiveSkill05 and AbilityList -> common break passive. |
| S0 | [Monster Common Ability][raw-s0] — `fa02f6ab070fb8da16ebd2f5976503446d633e0e` | Monster_Common_PassiveSkill_StanceBreak_Action; Local_ListenStanceBreak; adjacent RedStance/count entries. |
| S1 | [Common Specific modifiers][raw-s1] — `2db782ddc81b7a1328e4086dc71c8a23295b06a8` | StanceBreakState complete callbacks; MonsterAllDamageReduce; effect-only switch; MCommon_Element_Burn complete definition. |
| S2 | [Avatar Common Ability][raw-s2] — `21db58fafcb8fa826c5913b4e019d6c9e56e5f6f` | Common passive installation; TriggerStanceCountDown_Test OnTriggerBreak Fire branch and separate count-decrement callback. |
| S3 | [GlobalTaskListTemplate][raw-s3] — `d1da985fbac1bcf4e23f3c1dcdf7dfd11bcb5c96` | StanceBreak_Fire; Monster_ChangePhase reset contrast; DealSuperBreakDamage parameter/accumulator/request. |
| X0 | [Sam ConfigCharacter][raw-x0] — `0f682c63600b996e63ebfc24e761a1a6d28fec10` | Skill11/21 entries; PointB1 index0 and Skill21 index3 bindings; common passive entry. |
| X1 | [Sam Ability][raw-x1] — `dc815e85ba03509a158b7b4e1c7f79e3e81c9879` | Skill11 inverse weakness gate/damage/cleanup; Skill21 attachment; ForceStanceDamage and FireWeakType definitions; bounded SuperBreak caller. |
| G0 | [GameCoreConstValue][raw-g0] — `47ed0e027c76df398cf6e13de104933299ec1700` | Stance constants/shared declarations and MuteAttachWeakness mapping only; not generic evaluators. |
| D0 | [Dan Heng ConfigCharacter][raw-d0] — `37ac9144bb9f6724452c5ec7f0a834916113aee2` | Complete Floats, Skill01 EntryAbility and common passive reference; no1659254037 binding. |
| D1 | [Dan Heng Ability][raw-d1] — `953968c80c62ba46dd4d4fdf2698031c918a9b48` | Skill01 Phase01/02, OnStart[2]/[4] Stance consumers. |
| H0 | [Gallagher ConfigCharacter][raw-h0] — `20e142906136597d24edbe7995d50acf9f748673` | Complete Floats, Skill01 entry and common passive; no1659254037 binding. |
| H1 | [Gallagher Ability][raw-h1] — `9c29a5776ba33334439d3b38e6988098a2925f85` | Skill01 Phase01/02, OnStart[2]/[5] Stance consumers. |
| M0 | [Mecha02_02 ConfigCharacter][raw-m0] — `ff441c9fba0ad933d4d5bb73d3047ee8f949170a` | Skill02 EntryAbility and1127134183 ReadInfo; PassiveSkill01 installer entry. |
| M1 | [Mecha02_02 Ability][raw-m1] — `2f375b7662177935aeda87349683e39b527eace5` | PassiveSkillInitiate/DeathRattle callback; DeathRattle_Insert.OnStart[5].EventList[2].TaskList[1]. |
| M2 | [MonsterSkillConfig][raw-m2] — `b6cbf024dd00a13fee5578d0e3eca101d467a1e6` | Skill405201002,Skill02,ParamList=[0.15,30]. Git-blob fallback. |
| Q0 | [StageConfig][raw-q0] — `91840cadab4a1d01831cbdc3219bf4baff493fce` | Stage1012260 FarmElement/Release=true, common graph, Monster0/Monster2=4052010. Git-blob fallback. |
| G1 | [GameCoreConfigPathInfo][raw-g1] — `6eca8f5e8a406f37ee8e14a5b1e21438b5663f25` | Complete path registry and named ExcelOutputGameCore path; not an injector implementation. |

[R0]: battle_execution_language_core_v1.md
[R1]: ordinary_damage_vertical_slice_v1.md
[GLOBAL]: global_shared_reverse_scan.md
[MONSTER]: ../monsters/monster_1002011_reference_chain.md
[A0]: #21-exact-pin-replay-index
[A1]: #21-exact-pin-replay-index
[A2]: #21-exact-pin-replay-index
[A3]: #21-exact-pin-replay-index
[A1-A3]: #21-exact-pin-replay-index
[T0]: #21-exact-pin-replay-index
[T1]: #21-exact-pin-replay-index
[T2]: #21-exact-pin-replay-index
[S0]: #21-exact-pin-replay-index
[S1]: #21-exact-pin-replay-index
[S2]: #21-exact-pin-replay-index
[S3]: #21-exact-pin-replay-index
[X0]: #21-exact-pin-replay-index
[X1]: #21-exact-pin-replay-index
[G0]: #21-exact-pin-replay-index
[D0]: #21-exact-pin-replay-index
[D1]: #21-exact-pin-replay-index
[H0]: #21-exact-pin-replay-index
[H1]: #21-exact-pin-replay-index
[M0]: #21-exact-pin-replay-index
[M1]: #21-exact-pin-replay-index
[M2]: #21-exact-pin-replay-index
[Q0]: #21-exact-pin-replay-index
[G1]: #21-exact-pin-replay-index
[raw-a0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarConfig.json
[raw-a1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[raw-a2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json
[raw-a3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json
[raw-t0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterConfig.json
[raw-t1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json
[raw-t2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
[raw-s0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_Common_Ability.json
[raw-s1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[raw-s2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Common_Ability.json
[raw-s3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json
[raw-x0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Sam_00_Config.json
[raw-x1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Sam_00_Ability.json
[raw-g0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConstValue.json
[raw-d0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_DanHeng_00_Config.json
[raw-d1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_DanHeng_00_Ability.json
[raw-h0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Gallagher_00_Config.json
[raw-h1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Gallagher_00_Ability.json
[raw-m0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W2_Mecha02_02_Config.json
[raw-m1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Monster/Monster_W2_Mecha02_02_Ability.json
[raw-m2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterSkillConfig.json
[raw-q0]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/StageConfig.json
[raw-g1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/GlobalConfig/GameCoreConfigPathInfo.json
