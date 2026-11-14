# Battle-start Build Construction v1

## 1. Metadata and authority

- thread_id: `R5-BATTLE-START-BUILD-CONSTRUCTION-V1`
- inspected local baseline / expected parent: `0017ea9fd4d843df7d129ecbf867d80f4c078e34`
- TBGD authority: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- maturity: `manually_confirmed`; scope: bounded W01 + W18 construction evidence
- runtime_changed: `no`; source_kernel_alignment: `mixed`
- runtime validation: `not run`; not W01/W18 `mechanism_closed`

**S** below means pinned source fact, **K** inspected current implementation, **I** alignment inference, and **G** export/convention/transport/validation gap. Local implementation does not replace raw authority. The pipeline remains raw -> compiler/lowering -> source-bearing cards/IR/RuleBook -> admitted construction -> UnitState. All references resolve to exact revisions in section 18.

This is an `analyst_constructed_validation_build`, not an official preset, optimized build, or acquired inventory item. Numerical projections use the inspected local arithmetic and an independent Decimal check. They are **not an executed simulator result**. A calculated panel cannot bypass formal admission or prove B2 callback execution.

**Scope guard:** selected level/promotion/relic/trace values are used only as selectors for battle-state producers. This record does not study progression legality, EXP/material costs, upgrade caps, trace unlock prerequisites, relic acquisition/roll history, or account ownership. Local admission is inspected only as the gate that decides whether selected battle inputs can materialize a `UnitState`; it is not a progression-research target.

## 2. Kernel-first preflight

These consumers were inspected before extending the raw stat search. Paths below are relative to `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core`. No dependencies/environment/index were created. All runtime-validation entries are `not run`.

| Path / symbol | Input -> output | Source / failure boundary |
| --- | --- | --- |
| `tbgd/character_cards.py`, profile/promotion readers | Avatar/promotion/trace records -> source-bearing build profile | Identity, revision/fingerprint and producer references; raw reads remain source-layer work |
| `builds/character_assembler.py::assemble_character_build`, `_promotion_tier`, `_base_contributions` | RuleBook + CharacterBuildInput -> ledger, effective skills, panel and admission | Consumes selected level/promotion/trace/rank inputs; diagnostics can block `UnitState` materialization. Progression/unlock legality is not treated as battle authority |
| `builds/equipment_assembler.py` | LC level/promotion/rank and Avatar path -> static stats + passive selection | Wrong-path passive disabled independently of static LC stats |
| `equipment/models.py`, `builds/relic_affix_calculator.py` | Source-bearing affix rules + finished tuple -> Decimal contributions | Consumes selected slot/group/level and encoded count/step values; duplicate/main-sub conflicts can block materialization. Enhancement/roll history is excluded |
| `tbgd/relic_cards.py::_property_bonuses`, `builds/relic_set_assembler.py` | Set records + unique slots -> qualified static/dynamic tiers | Structural property-key recovery; set-count/binding gaps retained |
| `build_types.py::aggregate_static_stat_contributions` and property mapping | Typed base/ratio/flat ledger -> panel/resources | Unknown properties/provenance are not silently executable |
| `scenarios/build_state.py::ScenarioStateBuilder.build`, `_plan_formal_character_birth`, `_runtime_stat_pools` | Admitted assembly + initial condition -> UnitState | Admission, fingerprint and mechanism checks before birth; source IDs preserved |
| `_apply_battle_setup`, `_dispatch_battle_setup_event`, `_apply_timeline_setup` in the same file | Canonical setup/status/summon inputs -> events -> timeline | Not an arbitrary raw MazeBuff loader; phase `birth_after_enter_battle` |
| `systems/unit_stats.py::effective_unit_stat` | Pools/resources + statuses -> effective property | Concrete local formula, not exported generic GameCore evaluator |

Source provenance in loaders/contributions is distinct from `scenario_initial_condition` and canonical effect/setup sources. Existing R0 execution vocabulary, R3 lifecycle boundaries and durable LC20000 effect evidence are reused. [K1] [K2] [K3] [K4] [K5] [K6] [K7] [K8] [K9] [K10]

## 3. Concrete ordinary build — BUILD-01 / BUILD-03

**S:** Avatar1002 is released, `Rogue`, Wind, `AdventurePlayerID=1002`, `SPNeed=100`. Equipment20000 is released and also `Rogue`, with its explicit skill/effect association. This establishes the selected compatible path relation without relying on the names Dan Heng/Arrows. [S1] [S3]

| Selection | Value |
| --- | --- |
| Avatar | 1002, level80, promotion6, eidolon/rank0 |
| LC | 20000, level80, promotion6, superimposition/rank1 |
| Six finished relics | 61021/61022/61023/61024/63015/63016, each level15 |
| Sets | Four distinct Set102 slots + two planar Set301 slots |
| Static trace | Point1002201 level1: AttackAddedRatio0.04 |
| Skill context | Ordinary selected levels1; Technique100207 level1; no rank-derived increment |
| Technique | Optional character-held MazeBuff100201 active before first-wave entry |
| Initial condition | Full HP; local standard-resource initialization0, explicitly a local convention |
| Not selected | Food, trial preset, mode override, manual stat bonus, extra stage/global buff |

This tuple is component selection, not a fabricated runnable scenario JSON. Actual construction still requires admitted cards, fingerprints, action/binding manifests and scenario identity/encounter/setup references. **K:** on a wrong-path LC the current assembler retains base stats and disables the passive; that policy is not proof of a universal equip prohibition. [K2] [K3] [K8]

## 4. Avatar base / level / promotion — BUILD-02

The selected battle-stat source is `AvatarPromotionConfig[1002,promotion6]`; level80 and promotion6 identify the coefficient row used by this tuple. These are coefficients, not final properties. Level/promotion are selectors for the battle-start projection; EXP/material/cost/unlock legality and progression-cap semantics are excluded. [S2]

| Property | Raw base | Raw growth | Local level80 projection |
| --- | --- | --- | --- |
| HP | 408 | 6 | 882 |
| ATK | 252.96 | 3.72 | 546.84 |
| DEF | 183.6 | 2.7 | 396.9 |
| SPD | 110 | No growth used by inspected constructor | 110 |
| Crit | 0.05 | N/A | 0.05 |
| CritDamage | 0.5 | N/A | 0.5 |
| Aggro | 75 | N/A | 75 |

**K:** HP/ATK/DEF use `base + growth*(level-1)`. The selected level does not by itself identify a promotion row; promotion remains an explicit input selector. This record does not promote the assembler's tier/cap/prerequisite checks into battle authority. Missing serialized promotion is not silently zero without the loader's explicit zero-semantic evidence. [K1] [K2]

**I/G:** source coefficients, joins and range are closed; the affine native operator is not recovered. This remains local construction convention. Do not add another promotion bonus after selecting a row whose base already includes that promotion. SPNeed100 is a separate requirement input, not an explicit raw maximum.

## 5. Light Cone static and installed effect — BUILD-04 / BUILD-05

`EquipmentPromotionConfig[20000,promotion6]` supplies the selected level80 coefficient row: HP391.68/growth5.76, ATK146.88/growth2.16 and DEF122.4/growth1.8. The local level80 values are846.72/317.52/264.6. Combined Avatar+LC base pools are HP1728.72, ATK864.36, DEF661.5. Superimposition selects effect parameters, not an invented additional stat multiplier. Equipment progression-cap legality is outside this record. [S3] [S4] [K3]

Reuse existing LC20000 evidence: `EquipmentSkillConfig[20000,Level1].ParamList=[0.12,3]`. The exact-pin file really is named `EquipmemtAbility.json`. Its consumer is: [S5] [S6]

```text
Ability20000.OnStart -> AddModifier(Caster, MEquip_20000_Main)
  LifeTime <- SkillEquip index1 / hash -1970381737 =3
MEquip_20000_Main.OnStack
  -> StackProperty(ModifierOwnerEntity, CriticalChanceBase)
  value <- SkillEquip index0 / hash -1330896030 =0.12
```

This is a startup-installed effect, not unconditional B1 static crit. The formal local path separately prepares equipment providers/startup specs; actual admission/execution is untested. Lifetime3 is an authored input, not a reconstructed generic timer or replacement order. [K3] [K8]

## 6. Relic main-affix producers — BUILD-06

`RelicConfig` joins each selected template to rarity5, the selected level15 tuple, main group, sub group5 and set. `RelicBaseType` distinguishes Head/Hand/Body/Foot/Neck/Object; the planar pair is not interchangeable with body slots. Relic level here is a finished-build selector, not a study of enhancement limits or history. [S7] [S8]

Main rules provide property/BaseValue/LevelAdd. The local operator is `BaseValue + LevelAdd*selected_level`. [S9] [K4]

| Template / slot | Set | Group/affix | Property | BaseValue | LevelAdd | Local level15 value |
| --- | --- | --- | --- | --- | --- | --- |
| 61021 / Head | 102 | 51/1 | HPDelta | 112.896 | 39.5136 | 705.6 |
| 61022 / Hand | 102 | 52/1 | AttackDelta | 56.448 | 19.7568 | 352.8 |
| 61023 / Body | 102 | 53/4 | CriticalChanceBase | 0.05184 | 0.018144 | 0.324 |
| 61024 / Foot | 102 | 54/4 | SpeedDelta | 4.032 | 1.4 | 25.032 |
| 63015 / Neck | 301 | 55/8 | WindAddedRatio | 0.062208 | 0.021773001 | 0.388803015 |
| 63016 / Object | 301 | 56/1 | BreakDamageAddedRatioBase | 0.10368 | 0.036288 | 0.648 |

Decimal tails are preserved; familiar rounded display numbers are not substituted. Acquisition, salvage, EXP and enhancement history are outside this finished-build contract.

## 7. Substats are a different producer — BUILD-07

Each piece selects four unique group5 sub-affixes below, each with source-encoded count2 and accumulated step2. The local calculator consumes those finished-piece fields and rejects duplicate/main-sub conflicts. This record makes no claim about how the affixes or roll history were acquired. [S10] [K4] [K10]

| Affix | Property | BaseValue | StepValue | Per piece: base*2+step*2 | Six-piece sum |
| --- | --- | --- | --- | --- | --- |
| 5 | AttackAddedRatio | 0.034560002 | 0.0043200003 | 0.0777600046 | 0.4665600276 |
| 9 | CriticalDamageBase | 0.05184 | 0.0064800004 | 0.1166400008 | 0.6998400048 |
| 10 | StatusProbabilityBase | 0.034560002 | 0.0043200003 | 0.0777600046 | 0.4665600276 |
| 11 | StatusResistanceBase | 0.034560002 | 0.0043200003 | 0.0777600046 | 0.4665600276 |

Main level scaling, substat accumulation and conditional set effects are not one undifferentiated stat sum. Native generic affix evaluation is not recovered merely by inspecting the local arithmetic.

## 8. Count gates and non-static set effects — BUILD-08 / BUILD-12

Released Set102 has thresholds2/4; released planar Set301 has threshold2. [S11] [S12]

| Set/count | Static PropertyList | Ability | ParamList |
| --- | --- | --- | --- |
| 102/2 | AttackAddedRatio0.12 | Empty field | [0.12] |
| 102/4 | SpeedAddedRatio0.06 | Ability51021 | [0.06,0.1] |
| 301/2 | AttackAddedRatio0.12 | Ability53011 | [0.12,120,0.12] |

Raw PropertyList member names include `FODBMMCKAEN` and `MNDFOPKBHKP`. **K:** `_property_bonuses` also recognizes property strings and nested Value dictionaries structurally, not only assumed canonical key spellings. These selected static rows therefore have a concrete local reader. Obfuscation alone is not a missing-parser bug. Unique equipped slots drive local thresholds; static contributions and dynamic selections/bindings remain separate. Repeated numbers in ParamList are not a second automatic PropertyList bonus. [K5] [K7]

**102:** Ability51021.OnStart installs `MRelic_102_Main` on Caster. OnBeforeHitAll checks Normal attack and writes `ModifyDamageData.Attacker_AllDamageTypeAddedRatio` from `SkillRelic(102_4,index1)` / hash459179394 =0.1. This is a matching-hit context contribution, not persistent +0.1 ATK. [S13]

**301:** Ability53011.OnStart installs `MRelic_301_Main`. Its OnStack checks Speed >= `SkillRelic(301_2,index1)` / hash550312197 =120 and can install its submodifier. The authored Speed property-change range has add/remove paths. Submodifier OnStack contributes holder AttackAddedRatio from `SkillRelic(301_2,index2)` / hash-227304383 =0.12. This is conditional persistent property, unlike102's hit context. [S13]

B1 speed141.632 satisfies that comparison arithmetically; it does not prove local listener admission/execution. Unspecified lifetime is not relabeled permanent. Global event order is not inferred.

## 9. Static trace and eidolon partition — BUILD-09 / BUILD-10

The populated `AvatarSkillTreeConfig` Point1002201 level1 belongs to Avatar1002 and supplies `AttackAddedRatio=0.04` in PropertyList, with empty ParamList and predecessor list. It is explicitly selected, not automatically granted by level80. The local assembler recognizes the selected owner/level and adds the source-bearing contribution; trace prerequisite/unlock legality is explicitly outside this battle-state record. [S14] [K1] [K2]

Point1002007 supplies the Technique skill association100207. Other passive/trace conditions are not silently added to this static equation. E0 makes extra eidolon contributions N/A, not a fabricated raw +0. The local rank/effective-skill/startup partition exists; this record does not classify all nonzero eidolons as static or repeat their runtime archaeology.

## 10. Technique actually crosses into battle — BUILD-11

The complete selected interface is: [S15] [S16] [S17] [S18] [S19]

```text
LocalPlayer_DanHeng_MazeSkill.OnStart
 -> AddMazeBuff(Caster, ID100201, authored LifeTime=-1)
 -> AvatarMazeBuff100201:
      ADV_StageAbility_Maze_DanHeng
      InBattleBindingType=CharacterSkill, InBattleBindingKey=SkillMaze
      UseType=AddBattleBuff, MazeBuffType=Character
 -> CharacterConfig.SkillMaze: Caster -> Avatar_DanHeng_SkillMazeInLevel
 -> OnStart: AddModifier(Caster, SkillMaze_DanHeng_Modifier)
 -> OnEnterBattle(Priority=-80), ByCompareWaveCount(Equal,1)
 -> AddModifier(Caster, MAvatar_DanHeng_00_MazeSkill_AttackRatioUp)
 -> OnStack: StackProperty(ModifierOwnerEntity, AttackAddedRatio)
```

Skill100207 level1 **ParamList=[0.4,3]**. SkillMaze index0/hash-201412227 supplies injected `MDF_PropertyValue`; index1/hash-2081277152 supplies battle LifeTime. The callback reads the working value via hash2128130574; stacking is ReplaceByCaster. This closes the `.4` and `3` inputs, not generic timer/replacement semantics.

**Correction:** interrupted-session progress saying `.2,3` is superseded by exact-pin `.4,3`. Neighboring skill100206's `.5` and the description field are not the producer. BuffDescParamByAvatarSkillID is corroborating metadata, not a replacement for the executable CharacterSkill binding.

Maze lifetime-1 and battle lifetime3 are different objects. Do not infer a universal infinite-duration rule or count the battle buff in B0. Animation waits do not supply battle scheduling semantics.

**K/G:** `_apply_battle_setup` consumes canonical initial statuses/summons and dispatches setup events, not arbitrary raw MazeBuff IDs. This inspection does not demonstrate automatic MazeBuff100201 -> admitted formal startup manifest for this tuple. The missing demonstration is a **local transport/admission validation gap**, separate from the closed raw bridge. Copying `.4` directly into resources would be an invalid workaround. No whole-Maze search or universal transition-dispatcher recovery is claimed. [K8]

## 11. B0/B1/B2 and composition — BUILD-13 / BUILD-14

| Phase | Meaning | Local mapping |
| --- | --- | --- |
| B0 | Selected finished build, trace/rank and optional maze marker | CharacterBuildInput and explicit initial-condition/setup inputs |
| B1 | Constructed actor before startup effects | Admitted birth plan -> UnitState static panel/pools/resources, statuses=() |
| B2 | Selected startup effects admitted and dispatched, before ordinary actions | Provider/startup preparation -> explicit setup -> setup event -> timeline `birth_after_enter_battle` |

Formal birth creates `max_hp`, `hp`, `attack`, `defense`, `speed`, `energy`, `max_energy`, `resources` and `stat_pools`. For the chosen full-HP condition, hp=max_hp. It also explicitly initializes local toughness/max_toughness/action_value to0; these are constructor decisions, not raw missing-field defaults. Contribution/binding source references are preserved. Admission-blocked data must not create a formal unit just because a panel can be calculated. [K8]

Pools retain base, static percentage, static flat and contribution IDs. The inspected local HP/ATK/DEF/SPD operator is:

```text
base_pool*(1 + static_ratio + active_status_ratio)
    + static_flat + active_status_flat
```

It is not `(base+flat)*(1+ratio)`: the hands' flat352.8 is not multiplied by ATK ratios here. Secondary resources/crit use their mapped additive paths; aggro has a separate nonnegative composition. Static-source identity/deduplication is not native global precedence. Unknown override/conversion/snapshot semantics remain unknown. Active modifiers need not rewrite UnitState.attack directly; effective-stat readers can combine statuses with pools. [K6] [K9]

## 12. Component ledger and conditional projection

N/A means not selected/applicable, not a raw zero. Final columns below are **Decimal checks of local arithmetic, not simulator execution**. [S1] [S2] [S4] [S9] [S10] [S12] [S14] [K6] [K8]

| Property | Avatar level/promo | LC | Main | Sub | Static set | Trace/rank | B1 projection |
| --- | --- | --- | --- | --- | --- | --- | --- |
| MaxHP | 882 base | 846.72 base | 705.6 flat | N/A | N/A | N/A | 2434.32 |
| ATK | 546.84 base | 317.52 base | 352.8 flat | .4665600276 ratio | .12+.12 ratio | .04 ratio; rank N/A | 1862.456625456336 |
| DEF | 396.9 base | 264.6 base | N/A | N/A | N/A | N/A | 661.5 |
| SPD | 110 base | N/A | 25.032 flat | N/A | .06 ratio | N/A | 141.632 |
| Crit | .05 | Effect at B2 | .324 | N/A | N/A | N/A | .374 |
| CritDamage | .5 | N/A | N/A | .6998400048 | N/A | N/A | 1.1998400048 |
| Wind bonus | No selected raw base term | N/A | .388803015 | N/A | N/A | N/A | .388803015 |
| Break bonus | No selected raw base term | N/A | .648 | N/A | N/A | N/A | .648 |
| Effect hit | No selected raw base term | N/A | N/A | .4665600276 | N/A | N/A | .4665600276 |
| Effect resistance | No selected raw base term | N/A | N/A | .4665600276 | N/A | N/A | .4665600276 |
| Aggro | 75 | N/A | N/A | N/A | N/A | N/A | 75 |
| raw-SP requirement / local cap | SPNeed100 | N/A | N/A | N/A | N/A | N/A | local max_energy100; convention |

Actual code destination example: Avatar/LC coefficients -> levelled base HP1728.72 -> Head HPDelta705.6 -> aggregate2434.32 -> birth_plan.max_hp -> UnitState.max_hp and full-HP UnitState.hp. This proves inspected source/code mapping, not executed admission.

Secondary mappings are WindAddedRatio -> `Wind_damage_added_ratio`, BreakDamageAddedRatioBase -> `break_damage_added_ratio`, StatusProbabilityBase -> `effect_hit_rate`, StatusResistanceBase -> `effect_resistance`. They reach birth-plan/UnitState resources; no Damage/Break final formula is reopened. [K6] [K8]

Conditional **effective-property references**, only if the specified admitted effects are active:

| Condition | Reference | Still unverified |
| --- | --- | --- |
| Set301 submodifier active; Technique absent | ATK1966.179825456336 | Actual threshold listener execution |
| Set301 submodifier + selected Technique active | ATK2311.923825456336 | MazeBuff-to-local-startup transport/admission |
| LC20000 effect active | Crit.494 | Actual callback/lifetime execution |
| Set102 listener sees Normal hit | Hit-context operand.1 | Not a static ATK/panel bonus or final damage |

## 13. Alignment findings / conventions — BUILD-15 / BUILD-16

| Finding | Classification | Routed action, no runtime edits |
| --- | --- | --- |
| Raw SPNeed requirement becomes local max_energy | Source-role alignment partial / engine convention, not a raw cap proof | Validate cap/requirement authority separately; keep R4 boundary |
| Panel and admission are separate outcomes | Inspected local implementation; tuple admission not executed | Preserve source/graph diagnostics; do not publish runnable parity |
| Automatic raw MazeBuff import not demonstrated | Local transport/admission validation gap in inspected setup path | Trace/validate MazeBuff100201 -> formal manifest, no manual stat injection |
| Obfuscated relic keys have a structural reader | Selected static source transport aligned, not a parser-missing bug | Retain producer shape and exact values |
| Wrong-path LC retains stats but disables passive | Local policy, not universal raw equip law | Use Dan/March discriminator without overstating scope |
| Decimal reference differs in authority from runtime floats/display | Validation scope boundary | No exact runtime-float or public-game reproduction claim |

No incorrect numeric formula is alleged merely because its native operator is unexported. The concrete residuals are convention authority, admission/execution validation and specific unproved local Technique import. No raw coefficient is changed to fit the implementation.

## 14. Heterogeneous checks / false friends

Released March1001 is Knight/Ice rather than Dan's Rogue/Wind. Its promotion6 HP489.6/growth7.2, ATK236.64/growth3.48, DEF265.2/growth3.9, SPD101 and aggro150 demonstrate the shared source/constructor shape with different coefficients and passive eligibility. This is not a second fully assembled/admitted build. Set102's hit context and Set301's persistent conditional property supply another independent discriminator. [S1] [S2] [S3] [S13]

EXP/material costs, upgrade caps, unlock prerequisites and relic roll history are progression-side and not battle-state producers here; templates are not acquired items; display totals are not affix operators; equal values do not identify producers; rank is not promotion; ParamList is not a duplicate static bonus; animation is not scheduler authority; empty ability fields do not erase static stats; a Technique with scene operations can still have ordinary battle consequences; manually entered statuses are not formal admission. R4 raw-SP/raw-BP terminology remains intact.

## 15. A/B/C/D/E evidence partition

A closes the specified producer/edge, not every evaluator. B names native/export/convention gaps. C is code presence. D is static alignment only. No C/D result grants E.

| Layer | A source | B gap | C local | D alignment | E runtime validation |
| --- | --- | --- | --- | --- | --- |
| Avatar identity/owner | yes | no selected join gap | yes | selected owner yes | not run |
| Base coefficients | yes | final native evaluation separate | yes | selected fields yes | not run |
| Level scaling | inputs yes | native operator unavailable | yes | inputs yes, formula convention | not run |
| Promotion | selected row/coefficients yes | omitted-zero/native convention | yes | selected p6 input yes | not run |
| LC compatibility | enum relation yes | universal policy not recovered | yes | selected Rogue match yes | not run |
| LC static stats | inputs yes | native arithmetic convention | yes | selected pools yes | not run |
| LC battle effect | install/params yes | native timer/dispatcher | startup path yes | partial, admission untested | not run |
| Relic main | producer/slot/level yes | native evaluator unavailable | yes | selected affine inputs yes | not run |
| Relic sub | property/count/step yes | native evaluator; generation excluded | yes | selected tuple yes | not run |
| Set-count gate | threshold/slot yes | native equip loader not restored | yes | selected4/2 yes | not run |
| Set battle effect | causal chain yes | callback/order boundary | dynamic path yes | partial, execution untested | not run |
| Trace static | point -> .04 yes | none for selected input | yes | owner/selection yes | not run |
| Eidolon static | N/A, E0 | N/A | rank path yes | N/A extra contribution | not run |
| Technique entry | MazeBuff -> SkillMaze -> property yes | native transition/timer | generic setup yes | partial, auto-import unproved | not run |
| Flat/ratio composition | typed input buckets yes | native composition unavailable | yes | inputs yes; operator convention | not run |
| Startup passive install | authored calls yes | native dispatcher | yes | partial, manifests not executed | not run |
| UnitState projection | ingredients yes | initialization conventions | yes | static mapping; cap/initial partial | not run |

## 16. Validation and bounded exit

Performed: exact-pin raw reads and current-head kernel reads; selected coefficient/affix/set/trace/Technique joins; independent Decimal arithmetic; document/table/reference/fence checks; diff whitespace check; isolated patch roundtrip. Publication verifies commit parent, changed files, remote blob and actual PR head/Draft in the checkpoint.

**Not run:** native card compilation/admission for this tuple; ScenarioStateBuilder; actual B2 callbacks; Fast/Direct/runtime tests; public-game numerical reproduction; full CI. No new dependency/environment or runtime/test code. Document/arithmetic checks are not E.

The selected source component/battle-entry edges and formal local destinations are recorded. Residuals are explicitly bounded source/native conventions and local transport/admission validation, not an omitted known raw coefficient. This closes R5 v1 research, not runnable parity. The checkpoint must use the actual final remote head, not this inspected parent.

## 17. Routed residuals / stop

An implementation-validation task should run the exact tuple through existing lowering/admission, capture any concrete rejected graph/binding, and validate the MazeBuff100201 startup bridge and requirement-to-cap convention. This PR does not weaken admission. Other sets, overrides/conversions, acquisitions and generic formulas remain outside the slice.

Inventory updates are narrow: selected relic stat/set families and ordinary Adventure/MazeBuff entry. No broad checkbox completion or R0–R4 rewrite. Next route candidate remains R6 Encounter/Spawn/Phase/Termination, subject to direction correction after these findings. **Do not start R6 here.**

## 18. Exact-revision replay index

S labels are raw producers/consumers; K labels are inspected local readers/operators. Their row/ability/symbol locators are above. Navigation search results are not authority. Failed candidate paths and large-file empty responses are not absence evidence. Skill and skill-tree selected rows were reread through exact blobs when necessary.

Prior durable evidence: [LC20000](../equipment/light_cone_20000_arrows.md), [R0](battle_execution_language_core_v1.md), [R3](healing_modifier_lifecycle_core_v1.md), [R4](resource_economy_core_v1.md). Corrected records outrank stale broad-checklist wording.
[S1]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarConfig.json
[S2]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarPromotionConfig.json
[S3]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/EquipmentConfig.json
[S4]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/EquipmentPromotionConfig.json
[S5]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/EquipmentSkillConfig.json
[S6]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Equip/EquipmemtAbility.json
[S7]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicConfig.json
[S8]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicBaseType.json
[S9]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicMainAffixConfig.json
[S10]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSubAffixConfig.json
[S11]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetConfig.json
[S12]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/RelicSetSkillConfig.json
[S13]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Equip/RelicAbility.json
[S14]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillTreeConfig.json
[S15]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarSkillConfig.json
[S16]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_DanHeng_00_Config.json
[S17]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_DanHeng_00_Ability.json
[S18]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/AvatarMazeBuff.json
[S19]: https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAdventureAbility/LocalPlayer/LocalPlayer_DanHeng_00_Ability.json
[K1]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/character_cards.py
[K2]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/character_assembler.py
[K3]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/equipment_assembler.py
[K4]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/relic_affix_calculator.py
[K5]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/relic_cards.py
[K6]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/build_types.py
[K7]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/relic_set_assembler.py
[K8]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/scenarios/build_state.py
[K9]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/unit_stats.py
[K10]: https://github.com/yaelysia/hsr-battle-simulator/blob/0017ea9fd4d843df7d129ecbf867d80f4c078e34/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/equipment/models.py
