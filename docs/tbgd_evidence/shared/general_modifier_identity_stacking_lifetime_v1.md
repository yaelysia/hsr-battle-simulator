# General modifiers: identity, stacking, lifetime and removal v1

## 1. Scope, recovered checkpoint and result

Reviewed 2026-09-24. Evidence parent: `b1b1db9fabb04926dd2669e44d93c830fd784397`. Raw TBGD authority remains `DimbreathBot/TurnBasedGameData@14c1d18f91a8101d610e6c523447a7517de3fae1`. PR #8 stays open/Draft and documentation/evidence-only.

The interrupted F05 task had already published its [application record][F05] and checkpoint `5805904952`. This continuation does not repeat that research. F06 starts on the other side of application: what state is created or updated, whose state and clock it uses, and how it ends.

**Result:** a reusable lifecycle model distinguishing effect identity, source/holder, layers, remaining duration, payload sampling and removal dependencies. Positive discriminators include stack-cap refresh, explicit duration addition, a caster-timed parent distributing team effects, late-member installation, parent-controlled cleanup, and natural versus extra periodic activation. These are different operations, even when the UI describes several of them as refreshing a buff.

The research unit is the mechanism. Sampo supplies stacking/reapplication, Serval supplies duration addition, and Ruan Mei supplies parent/child timing and cleanup; none is a whole-character audit. Existing shared DoT, HOT, shield and immunity evidence is reused.

Exact field/operation claims are manually confirmed. Observable timing/reapplication and sampling models retain their public attribution. No game session, simulator, Direct, test suite or workflow was run. No local-runtime E or native dispatcher recovery is claimed. F06/W09/W10 remain active for the named residuals below.

## 2. Source register

### Newly inspected pinned paths

All paths in this table are relative to the fixed TBGD repository. Named selectors identify actual serialized objects; no guessed numerical AbilityList index is needed.

| Ref | Path and selected occurrence | Complete blob |
| --- | --- | --- |
| S1 | [Config/ConfigCharacter/Avatar/Avatar_Sampo_00_Config.json][S1]; SkillP01 ability membership and typed SkillP01/PointB1 reads | `480c0eaae3c1755fd38a4452b05b2bd4c85852d8` |
| S2 | [Config/ConfigAbility/Avatar/Avatar_Sampo_00_Ability.json][S2]; `Avatar_Sampo_00_PassiveSkill01.Modifiers.MAvatar_Sampo_Passive.OnAfterHit`, installer and neighboring Skill03 application | `4d2964f9ac91fa990526d88f24a46047c60e0268` |
| S3 | [Config/ConfigCharacter/Avatar/Avatar_Serval_00_Config.json][S3]; `SkillParam(Skill03,1)` | `55f8ff3ec6cbc8fd1c349954e02b1c33b4f8aece` |
| S4 | [Config/ConfigAbility/Avatar/Avatar_Serval_00_Ability.json][S4]; `Avatar_Serval_Skill03_Phase02.OnStart`, Shock installation contrast and flagged duration addition | `2f2f465d33b7259347a2b1cb6e79e2fbc5089d44` |
| S5 | [Config/ConfigCharacter/Avatar/Avatar_RuanMei_00_Config.json][S5]; Skill02 membership and indices1/2 | `42d2ae46cb0327d9c7e781b8b041ca3390f37d2b` |
| S6 | [Config/ConfigAbility/Avatar/Avatar_RuanMei_00_Ability.json][S6]; `Avatar_RuanMei_Skill02_Phase02`, local Area/Area_Caster/StanceBreakAdded definitions | `25536aef20af238ffa46787860e88cf7c2cd7d2b` |

Useful inspected line ranges: S1 310-475; S2 1050-1550; S3 240-500; S4 1000-1330; S5 155-230 and260-470; S6 Skill02 definitions through the end of its Phase02, including490-810. Named occurrences and blobs are the stable replay anchors.

### Reused exact-pin evidence

[Common Specific][COMMON], blob `2db782ddc81b7a1328e4086dc71c8a23295b06a8`, provides `MCommon_DOT_Poison`, `MCommon_Element_Poison`, the Burn/Electric families, OneMore, and the Break-state definitions already inspected in the preceding tasks. The relevant definition bodies are reused, not claimed as a fresh global scan.

[R3] and [the public healing/shield reconciliation][HEAL] provide selected Natasha HOT, March shield and per-property snapshot/read distinctions. [Burn] provides ordinary source/holder and custom-activation inputs. [F03] provides the distinct Break status families and periodic property reads. [F05] provides the admitted/immune boundary and consumed-protection cleanup. Their raw gaps are not silently relabeled as solved.

### Public explanations and text

Resources were consulted on2026-09-24. Public skill text is semantic evidence, not an independent gameplay experiment or an exact-pin numeric row.

| Ref | Source/context | Accepted use and limit |
| --- | --- | --- |
| P1 | [KQM, 4-star characters at a glance][P1], Sampo section | One stack group, maximum five, reapplication refreshes its duration, and skill/Break Wind Shear coexist. Authored explanation, not a new experiment. |
| P2 | [KQM SRL Serval][P2], Ultimate | Describes adding two turns to existing Shock. The inspected raw increment reads Skill03 index1; this task does not claim to have newly read that numeric skill row or joined its localization hash. |
| P3 | [KQM Ruan Mei][P3], Version1.6, Skill/timing explanation | Overtone lasts three of her turns, decreases at their starts and does not spend duration when faster teammates act. This is a published description/model reconciled with the pinned parent on Caster. |
| P4 | [KQM Kafka][P4], Version1.2, Mechanics/Skill/Serval sections | Ordinary extra DoT activation does not consume duration, retains the DoT originator, and can act on Break DoTs; Shock extension is not restricted to the skill-applied formula. |
| P5 | [KQM Asta][P5], Version1.4, Ultimate | Her speed buff does not decrement at the end of its application turn. A specific first-turn exception, not an all-buff default. |
| P6 | [KQM Seele][P6], Version1.6, Talent/playstyle | Extra action and buffed state are distinct; the buff's application-turn exception prevents a one-turn duration from meaning exactly one attack. No new Seele graph audit. |
| P7 | [LiasLuck, original GameFAQs DoT answer][P7] | Explicit ordinary-DoT dynamic-stat explanation: applicable buffs when damage occurs matter. An attributed community model, not a controlled experiment; the page supplies relative age, not a verified exact test date. |
| P8 | [KQM SRL Tingyun evidence][P8], added2023-06-01, last-tested2023-05-01 | Original credited report includes ownership comparisons and a snapshot-labelled video. The short prose does not specify every sampled property; no new viewing or full snapshot audit is claimed. |

P8 was read at `KQM-git/SRL@de0e5c09c8dbba9577367ad86e991fe91c4f0e36`, blob `55fb73f6a56f5e1c7d1fba5a90c7e4a15c21bfa3`. Its external revision is not the TBGD pin. Wrong-game Genshin snapshot results were rejected. Video titles, empty evidence headings and repeated publication are not additional test results.

## 3. The reusable state description is not one integer

For research, keep these dimensions separately:

| Dimension | Question it answers |
| --- | --- |
| Definition and application occurrence | Which configured behavior was requested, from which exact source path? |
| Caster/source, holder and damage owner | Who applied it, who carries it, and whose inputs a later effect uses? These roles can differ. |
| Matching/stacking domain | Which existing effect group may be updated? Preserve `Stacking`, `StackingFlag` and any explicit source filters. |
| Layer and cap | How many potency layers apply, and which definition/installer supplies the cap? |
| Initial and remaining duration | What duration was admitted, how much remains, and which entity/event spends it? |
| Count/charges and predicates | Is a use consumed by a separate event or condition rather than a turn counter? |
| Payload and sampling | Which parameters are transferred, and which properties are queried later? |
| Dependency and exit | Which parent, dispel, expiry, named removal or death condition ends the effect? |

This is an evidence vocabulary, not a proposed IR or a recovered native instance-key tuple. A display name or behavior flag alone cannot identify the entire state. The same template can be instantiated for different holders or sources; a similarly named skill DoT and Break DoT can have different definitions and formula families.

A useful transition map is:

```text
application admitted
  -> no matching group: initialize the applicable state
  -> matching group: apply this occurrence's update policy
active state
  -> eligible lifecycle event: tick/decrement/consume as specified
  -> explicit mutation: change layer, duration or another payload
  -> exit condition: remove the state and its specified dependencies
```

It describes observable obligations, not a universal OnCreate/OnStack/OnDestroy callback order. A rejected request does not prove that this target modifier was refreshed; separate immunity-charge or other side effects remain F05 questions.

## 4. Identity and stacking: do not merge by elemental label

The selected skill Wind Shear installs `MCommon_DOT_Poison`; Wind Break installs `MCommon_Element_Poison`. Both carry the Wind-Shear behavior family, but the former has ordinary attack-percentage damage and the latter a Break formula. P1 explicitly describes their coexistence. Therefore even same-applier, same-holder, same-element effects cannot be collapsed solely by a UI label or status flag. [S2], [COMMON], [F03], [P1]

Conversely, multiple successful applications can update one observable stack group rather than producing independent timed damage instances. `ReplaceByCaster` occurs on the shared stackable Poison definition and on one-layer Burn/Electric definitions. The token alone does not mean zero out all layers or add a new independent group on every application. Layer policy, admitted cap, caster identity and observed reapplication must be considered together. [COMMON], [Burn]

Do not turn the word Caster into a claim that the complete native matching algorithm is recovered. Cross-source same-template matching, `StackingFlag` precedence and alias-equivalent casters remain specific residuals. Publicly established coexistence remains usable without that engine body.

## 5. Sampo discriminator: more layers and a refreshed clock are separate updates

S1/S2 close the selected application input map:

```text
SkillP01 -> Avatar_Sampo_00_PassiveSkill01
 -> AddModifier(Caster, MAvatar_Sampo_Passive)
 -> OnAfterHit
 -> resolve PointB1 lifetime addition and separate Rank06 coefficient addition
 -> AddModifier(DamageDefenderEntity, MCommon_DOT_Poison)
      StackingFlag = CharacterSkill
      Chance: hash -1841533120 = SkillP01[0]
      LifeTime: hashes [-1156924325,696550181], AQABAQIR
                = SkillP01[2] + _Tree01_LifeTimeAdd
      MaxLayer: hash -1542519066 = SkillP01[3]
      Modifier_Poison_DamagePercentage:
                hashes [644848458,-1669038400], AQABAQIR
                = SkillP01[1] + _Rank06_DamagePercentageAdd
```

The helper values are explicitly set by their condition branches; the inactive branches write zero. No native hashing implementation is newly inferred. Public baseline duration/max values are not silently substituted for unread pinned SkillP01 table rows.

The shared definition has default `MaxLayer=5`, `LayerAddWhenStack=1`, `LifeStepMoment=ModifierPhase1End`, `Stacking=ReplaceByCaster` and `UseSnapshotEntity=true`. The actual installer also has a MaxLayer input, so the effective cap must retain that input, not blindly ignore it in favor of the definition default. Its OnPhase1 reads current Layer into `Modifier_Poison_PoisonLayer`, then multiplies the installed percentage by that layer; its custom callback has a separate activation-ratio factor. [COMMON]

P1 establishes the selected ordinary reapplication behavior, including maintaining maximum stacks. Let n be current layers, N the admitted cap, d remaining duration and d0 the admitted reapplication duration:

```text
on the selected successful ordinary reapplication:
  n' = min(N, n + 1)
  d' = d0
```

The reset to d0 is the public behavior interpretation, not an exported generic replacement function. At the ordinary five-layer cap, another successful application can refresh duration while n remains5. Failure to gain a sixth layer therefore does not imply the entire application had no effect. Nor does gaining a new layer imply each earlier layer retains an independent expiry clock.

This rule is scoped to this ordinary stack group. A larger already-extended timer, stronger/weaker prior payload, per-layer-duration mechanics or a different policy requires its own discriminator; no universal `max(d,d0)` versus `d0` rule is asserted for every status.

## 6. Serval discriminator: extending an existing timer is actual addition

The new data-side operation is not AddModifier. S3 binds `-1034967551` to `SkillParam(Skill03,index1)`. In S4, `Avatar_Serval_Skill03_Phase02.OnStart` contains a Retarget over AllEnemy with a `STAT_DOT_Electric` predicate, followed by:

```text
SetModifierValueByBehaviorFlag
  TargetType = ParamEntity
  ModifierBehaviorFlags = [STAT_DOT_Electric]
  ModifyFunction = Add
  ValueType = LifeTime
  Value = AQAR / [-1034967551]
```

P2 supplies the published two-turn meaning. For the affected eligible state with remaining duration d, the model is `d' = d + 2`, not `d' = 2`, not a fresh damage roll and not a second Shock. The exact raw increment remains the typed Skill03 read; no same-pin numeric row is claimed read in this session.

The operation filters by the Shock behavior family, not by a single ModifierName or a serialized caster-equals-Serval condition. Shared ordinary Electric and Break Electric have that flag; P4 corroborates extension of Break Shock. A broader status family can therefore be selected for a duration operation while retaining different source identities and damage formulas. This does not transfer damage ownership to the extender. [COMMON], [F03]

There is a separate Rank04/unshocked-target AddModifier branch earlier in the Ultimate body. That branch must not be confused with the later extension, and its existence is not permission to claim that the base extension creates Shock on a target with none. Direct damage may also alter target state; exact same-action creation/extension arbitration and exceptional filters are not generalized.

### Operations with superficially similar wording

| Operation | Observable change | Source discriminator |
| --- | --- | --- |
| More layers with refresh | Potency-layer update and refresh to the admitted duration | Sampo application plus P1 |
| Explicit extension | Add to remaining LifeTime of selected existing states | Serval SetModifierValueByBehaviorFlag(Add,LifeTime) |
| Longer newly installed duration | Change the initial/reapplication input | Sampo PointB1 or retained Natasha PointB3 branch |
| Reinitialization/replacement | Apply the chosen replacement policy and initialization payload | Retained March OnStack -> InitShield, with Replace metadata |
| Extra activation | Run the selected effect again using its existing state | Shared DoT OnCustomEvent; not automatically a duration decrement |
| Consumption | Remove or reduce a use-bearing state following its event | F05 OnImmuneDebuff removal; no fabricated Count field |

No policy name on its own closes payload selection, old/new instance identity or native callback ordering. In particular this record does not invent a weaker-versus-stronger shield replacement rule from `Replace`.

## 7. Duration has an owner and an eligible event

A lifetime model must identify its clock entity, lifecycle moment, first eligible step, reapplication rule and exit condition. An enemy turn, an ally action, an inserted Ultimate and a cycle in a game mode are not interchangeable units.

For a finite ordinary clock at its specified eligible event, decrementing remaining duration by one is a useful model. It is not an instruction to decrement every modifier after every damage operation. The selected shared DoT's recipient-turn-start damage and `ModifierPhase1End` lifetime surface are separate entries; the local phase ending is not the end of a whole team's round. [COMMON], [Burn], [HEAL]

### 7.1 Caster-timed parent with recipient-side children

S5 maps `-1019407308` to `SkillParam(Skill02,2)`. S6 `Avatar_RuanMei_Skill02_Phase02` installs `RuanMei_Skill02_Area` on **Caster** with that lifetime. The local Area definition has `LifeStepMoment=ModifierPhase1End` and `Stacking=ReplaceByCaster`.

```text
Area.OnStack
 -> AddModifier(AllTeamMemberWithUnselectable, RuanMei_Skill02_DamageUp)
 -> AddModifier(same team set, RuanMei_Skill02_StanceBreakAdded)
      named input Skill02_StanceBreakAddedRatio <- Skill02[1]
 -> AddModifier(Caster, RuanMei_Skill02_Area_Caster, supplied lifetime)
 -> AddModifier(AllTeammateWithUnselectable, RuanMei_Skill02_Area_Friend)

Area.OnListenCharacterCreate
 -> check new ParamEntity intersects eligible team set
 -> install the corresponding children on that entity

Area.OnDestroy
 -> remove DamageUp, StanceBreakAdded and named Area marker children
```

The efficiency child uses `Stacking=Refresh`; OnStack writes `StanceBreakAddedRatio` from working hash `-1139434500`. Its selected definition has no local numeric lifetime, and the parent installs it without one. Missing a child timer is not evidence for an eternal independent buff: the parent explicitly removes it.

The Area_Caster helper also binds LifeTime to hash1820617363 using `AdditionConfig.ValueBindList`. Its positive dynamic-value change branch sends a `SetModifierValue(...LifeTime...)` to the named Area and updates the displayed count. This is a real timer-coupling surface, not proof that the UI energy bar is the authoritative timer or a recovered global clock implementation.

P3's text explains the observable clock: three Ruan Mei turns, stepping at their starts. The teammate can receive the effect without becoming the duration owner. Thus extra ordinary turns taken by a fast teammate do not consume this parent timer; the teammate's own independently timed buffs can still expire. Public numbers are labeled as text/model values rather than newly read pinned skill rows.

The create-listener also supplies an authored path for newly appearing eligible members. It is not a claim that every aura in the game automatically affects late spawns, or that all parent/child fields use this same implementation.

### 7.2 First-step and action-category distinctions

S2's separate Ultimate DoT-vulnerability AddModifier explicitly supplies `LifeStepImmediately=true`; its poison installer does not. Preserve that occurrence distinction without treating omission as false or deriving every first-step rule from the flag alone.

P5 and P6 provide concrete observable exceptions: Asta's speed buff and Seele's buffed state do not spend a duration step at the end of the turn when gained. P6 separately distinguishes Resurgence's extra action from the buff. These public rules refute `one turn remaining = one more damage/action event`. They are not a new raw audit of those two kits or a universal algorithm for every extra action.

The next F08 foundation should reconcile these clock/action categories and supported first-step behavior. It need not recover a universal hidden scheduler before documenting them.

## 8. A refreshed timer does not mean every property was resampled

Separate installed operands from queried battle properties. Shared ordinary DoT stores its damage-percentage payload and has later layer reads. [R3] retains examples of explicit OnCreate property reads, while [F03]'s Break Bleed rereads holder MaxHP and a source-facing Break Effect property during periodic/custom callbacks. Those sites have different read times and entity selectors.

An explicit callback query proves the query occurs there; `SnapshotPropertyEntity` still requires its own property-routing interpretation. Conversely `UseSnapshotEntity=true` alone does not prove all stats were frozen at application, and extending LifeTime alone does not prove the damage payload was reinstalled.

For ordinary ATK-scaling DoT, P7's dynamic-stat explanation gives the useful attributed gameplay model:

```text
D_at_activation = installed_percentage * current_group_layers
                  * applicable_source_ATK_at_activation
                  * applicable_damage_factors_at_activation
```

This is an adopted community behavior model, not a new controlled measurement or a raw proof of native alias resolution. It is not imposed on every Break, conversion, capped-HP, special DoT or buff formula. Changing a source buff can affect the next damage without changing the modifier's installed coefficient or remaining timer. P4 independently supports preserving the original DoT owner's role during extra activation, not using the triggering teammate's ATK.

P8 demonstrates why an unqualified all-effects-are-dynamic rule would also be inappropriate: its credited report explicitly discusses a snapshot test for a different additional-damage effect. The report's short prose is insufficient to assign every stat a capture time. A reusable sampling record should identify property, getter/entity, read site, what can update it, and the observed discriminator; it should not be one blanket snapshot boolean.

## 9. Removal, dispelling and property cleanup are different edges

`CanDispel` metadata, an active `DispelStatus` request, named `RemoveModifier`, self-removal and `OnDestroy` cleanup are different facts. R3's status identity/category audit remains useful, but its unresolved default dispel filter does not block the positive named-removal chains here.

| Exit path | Positive evidence | Do not substitute |
| --- | --- | --- |
| Parent expiry/removal | Ruan Mei Area.OnDestroy removes named team children | Give every child the recipient's turn clock |
| Use consumed | F05 protection.OnImmuneDebuff removes itself | Invent Count=1 or claim a debuff was admitted then cleansed |
| Parent-dependent protection | F05 parent.OnDestroy removes the protection | Keep the child indefinitely because it has no local timer |
| Shield cleanup | March OnDestroy -> RemoveShield | Assume zero shield implies immediate modifier destruction |
| Break recovery | F03 reset/removal/common-reduction restoration | Remove every independent elemental status at recovery |
| Presentation removal | RemoveEffect/visual teardown | Treat it as RemoveModifier or a cleanse operation |

Property cleanup should preserve contribution ownership. Ending one supplying state removes its applicable contribution, not every unrelated modifier on the recipient. S6 gives actual child-removal edges; the public aura duration establishes that its benefit ends with the parent. The native property-container rollback implementation, duplicate-source arbitration and same-hit visibility are not recovered from those facts. Do not synthesize an arbitrary negative StackProperty callback or restore a saved entire character sheet.

`OnStack -> StackProperty` describes a contribution/update site, not permission to add the same full group total permanently after every refresh. For a layer-dependent effect, the current group contribution and the increment in layer count must remain distinct. Existing Firekiss's layer-to-total expression and the Refresh efficiency child are concrete evidence of this distinction. [Burn], [S6]

## 10. Discriminating examples and claim accounting

The following are **model predictions**, not new measurements. Assume the specified application succeeds and no intervening expiry, immunity or unrelated operation changes the state.

| Controlled situation | Predicted distinction |
| --- | --- |
| Selected ordinary five-layer Sampo group, d=1, reapplication duration d0=3 | Layers remain5 and duration refreshes to3; not six layers, and not1+3=4. d0=3 is the deliberately selected public baseline. |
| Existing eligible Shock has d=1 and receives the published two-turn extension | d becomes3. With d=4 it becomes6; neither is a reset to2. |
| Existing DoT receives an ordinary extra activation | Damage occurs; the activation alone does not spend its natural duration step. |
| Two teammate turns occur before the caster-timed Area's next eligible step | No two-step reduction of that Area merely because teammates acted. |
| Area exits while unrelated recipient statuses remain | Its named children are removed; unrelated states are not all reset. |
| Same ordinary DoT coefficient/layers, source ATK rises2000->3000 before activation, all other factors fixed | P7's model predicts1.5x damage, not a longer lifetime or an extra stack. This is not a new sampling experiment. |

| F06 claim | Accepted basis | Limit |
| --- | --- | --- |
| Display/category identity is insufficient | Distinct shared definitions, source roles and P1 coexistence | Complete native matching key not recovered |
| Selected stacking plus cap-refresh behavior | S1/S2/shared definition + P1 | Stronger/weaker payload and unusual extended-timer precedence remain specific |
| Explicit existing-state lifetime addition | S3/S4 + P2, with P4 Break-Shock cross-check | Exact special-status/overlap/same-action arbitration not generalized |
| Caster clock and parent/child cleanup | S5/S6 + P3 | Universal aura/counter lifecycle not claimed |
| Natural tick versus extra activation | Shared callbacks and P4 | Arbitrary custom event routing is not inferred |
| Property sampling separate from state lifetime | Reused raw read sites, P7 model and scoped P8 report | No all-properties/all-effects snapshot theorem |
| Runtime correctness | Not evaluated | No C/D/E promotion or repair gate |

Remaining research is precise: same-template cross-source matching and StackingFlag precedence; weaker/stronger replacement and already-extended-timer arbitration; per-layer or independently expiring variants; duration first-step/extra-action/control exceptions; exact property sampling by family; and overlapping removal/rollback visibility. None invalidates the supported ordinary cases above.

## 11. Publication and next boundary

This checkpoint adds this mechanism record and updates the foundation roadmap/README. It does not rewrite the historical R3, F03 or F05 records, change broad W checkboxes, or claim exhaustive modifier coverage. Earlier native-body-only stopping language is superseded only for the observable lifecycle rules supported here.

Validation is pinned source/text inspection, named-reference and expression review, deliberately labeled state-transition predictions, and Git parent/diff/head verification. No numerical game replay, simulator correctness, passing CI or new external experiment is claimed.

**Next primary foundation: F08 time, turn and action categories**, because the remaining shared boundary is which events legitimately advance these clocks, rather than another sample character's remaining kit. Existing F04 healing/shield and F07 resource obligations remain queued; this checkpoint does not execute them. Backend implementation is outside PR #8.

[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Sampo_00_Config.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Sampo_00_Ability.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Serval_00_Config.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Serval_00_Ability.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_RuanMei_00_Config.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_RuanMei_00_Ability.json
[COMMON]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json
[P1]: https://hsr.keqingmains.com/misc/4s-at-a-glance/
[P2]: https://srl.keqingmains.com/characters/lightning/serval
[P3]: https://hsr.keqingmains.com/ruan-mei/
[P4]: https://hsr.keqingmains.com/kafka/
[P5]: https://hsr.keqingmains.com/asta/
[P6]: https://hsr.keqingmains.com/seele/
[P7]: https://gamefaqs.gamespot.com/boards/333603-honkai-star-rail/80695922
[P8]: https://github.com/KQM-git/SRL/blob/de0e5c09c8dbba9577367ad86e991fe91c4f0e36/docs/evidence/characters/lightning/tingyun.md
[R3]: healing_modifier_lifecycle_core_v1.md
[HEAL]: public_mechanics_healing_shield_reconciliation_v1.md
[Burn]: guinaifen_burn_tick_detonation_source_chain_v1.md
[F03]: general_weakness_toughness_break_super_break_v1.md
[F05]: general_effect_application_hit_resistance_immunity_v1.md
