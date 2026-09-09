# Monster 1002011 battle-source evidence chain

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: representative ordinary monster identity/template/skill chain, corrected HardLevel scaling inputs, Stage/Elite/phase topology, typed HardLevel-property access, and explicit final-stat engine boundary
- Runtime production code changed: no

This record intentionally does not assign a localized/public display name to MonsterID `1002011`; the pinned TextMap/display-name chain is not closed here.

## Critical W14 correction

Earlier archaeology treated `ExcelOutput/ILHardLevelGroup.json` as ordinary monster scaling authority. That classification is superseded.

The ordinary five-stat `(HardLevelGroup,Level)` family is `ExcelOutput/HardLevelGroup.json`. `ILHardLevelGroup` / `ILBattleMonster` are a separate RtBattle/IL family for the inspected collision and must not be used for ordinary W14.

## Authority classification

| Source | Role | Classification |
|---|---|---|
| `ExcelOutput/MonsterConfig.json` | concrete monster identity, skills, resistances, instance modification inputs | battle-authoritative / mixed |
| `ExcelOutput/MonsterTemplateConfig.json` | base ATK/DEF/HP/SPD/Stance, config/AI path | battle-authoritative |
| `ExcelOutput/HardLevelGroup.json` | ordinary level/group ATK/DEF/HP/SPD/Stance inputs | battle-authoritative input family; final operator unavailable |
| `ExcelOutput/EliteGroup.json` | additional encounter/monster difficulty context | ordinary input family; precedence unresolved |
| `ExcelOutput/ILHardLevelGroup.json` | RtBattle/IL scaling | false positive for ordinary W14 |
| `ExcelOutput/MonsterUniqueConfig.json` | conditional family | include only with explicit chain |
| `ExcelOutput/MonsterSkillConfig.json` | skill numeric producer | battle-authoritative when consumer traced |
| ConfigCharacter / ConfigAbility monster files | execution wiring/semantics | battle-authoritative at operation level |
| `SetDynamicValueByHardLevelProperty` | typed HardLevel-property read surface | battle-authoritative operation surface; generic implementation unavailable |

## Raw identity and skill chain

```text
MonsterConfig[1002011]
  -> MonsterTemplateID=1002011
  -> MonsterTemplateConfig[1002011]
       base ATK/DEF/HP/SPD/Stance
       JsonConfig=Monster_W1_CocoliaP1_01_Config.json
       AIPath=Monster_Common_SequenceThree_AI.json

MonsterConfig[1002011].SkillList=[100201101]
  -> MonsterSkillConfig[100201101]
       SkillTriggerKey=Skill04
       ParamList[0]=2
  -> ConfigCharacter DynamicHash(-190305622)
       SkillParam(Skill04,index=0)
  -> ConfigAbility DamageByAttackProperty
       DamagePercentage=DynamicHash(-190305622)
```

The specific damage-percentage input `2` is therefore source-closed for this formal AoE Ice operation.

## Representative concrete/template facts

`MonsterConfig[1002011]` establishes the concrete identity, weaknesses/resists and skill list. `MonsterTemplateConfig[1002011]` supplies:

- ATK base `18`
- DEF base `210`
- HP base `69.75`
- SPD base `100`
- Stance base `60`
- status resistance base `0.2`
- ordinary ConfigCharacter and AI paths.

Template bases are not final encounter properties.

## Correct ordinary HardLevel input family

Exact pinned `ExcelOutput/HardLevelGroup.json` blob:

`9ee36b767b010d2c85aa7169e86e9f0a4220a935`

Rows expose:

- `AttackRatio`
- `DefenceRatio`
- `HPRatio`
- `SpeedRatio`
- `StanceRatio`

Representative cross-checks:

| Group | Level | ATK | DEF | HP | SPD | Stance |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 29 | `5.19238` | `2.333333` | `5.020885` | `1` | `1` |
| 1 | 40 | `8.634539` | `2.857143` | `9.524581` | `1` | `1` |
| 2 | 29 | `6.127009` | `2.333333` | `13.429104` | `1` | `1` |

Group 1 `SpeedRatio` changes from `1` at level 65 to `1.1` at level 66, so SPD scaling is a real ordinary input.

`Ratio` names do not prove the final operator.

## Typed HardLevel-property access is real

Pinned `Config/ConfigAbility/Level/Level_FarmStage_Ability.json` blob:

`16dd1882925e66eb9d7b11c7d1d5b98c9938ed67`

contains `RPG.GameCore.SetDynamicValueByHardLevelProperty(Property=HPRatio)` in an ordinary farm-stage ability.

This proves HardLevel properties are engine-readable battle inputs. It does not reveal the ordinary monster spawn-stat constructor or its precedence rules.

## Static final-stat topology and hard engine boundary

Current evidence supports a layered model:

```text
wave/occurrence MonsterID
  -> concrete MonsterConfig
  -> MonsterTemplateConfig base inputs
  + effective Level/HardLevelGroup
  + MonsterConfig flat/ratio inputs
  + Monster/Stage Elite context
  -> configured spawn-property domain
  -> same-entity phase property layer where applicable
  -> StageAbility / Ability / Modifier live overlays
  -> current battle properties
```

The exact repository pin is a release-data/config corpus; it does not export the GameCore implementation bodies for the generic configured-spawn getter/constructor.

The following therefore remain `engine_consumer_unavailable` unless a new authoritative source appears:

- final ATK/DEF/HP/SPD/Stance arithmetic;
- flat `*ModifyValue` placement;
- clamp/rounding;
- effective Stage-vs-Monster HardLevelGroup/Level precedence;
- Stage-vs-Monster Elite composition/order;
- generic phase override application/default handling.

## Flat-value hazards

Pinned data contains non-zero flat speed modifications, e.g. concrete rows on template `1002020` with `SpeedModifyValue=20` and `33`, and template-level flat speed/stance fields also exist.

These must not be silently dropped or placed by community-formula intuition.

## Stage / Monster Elite coexistence

Pinned Stage `301001` supplies Stage-level Elite context while its concrete monsters carry their own EliteGroup values. This proves both layers can coexist.

A public runtime layout corroboration pass found multiple `EliteGroupRow*` slots in `MonsterRowData`, but no available method body maps those slots to Stage-vs-Monster provenance or proves stack order.

Safe conclusion: multiple elite inputs are structurally supported.

Unsafe conclusion: any specific replace/multiply/order rule.

## HardLevel conflict coverage: negative evidence, not precedence proof

The lane audited thousands of `MonsterConfig.HardLevelGroup` occurrences by broad sampling; ordinary inspected rows were dominated by group `1`, and inspected ordinary Mainline stages also used group `1`.

Therefore the current ordinary samples do **not** supply a clean Stage.HardLevelGroup != MonsterConfig.HardLevelGroup discriminator.

This weak conflict coverage is negative evidence against pretending precedence is empirically closed. It does not prove every MonsterConfig row is group 1.

## MonsterUnique is conditional

No matching `MonsterUniqueConfig` row was found for representative ordinary IDs including `1002011`, `1022020`, and `1023010`.

Family existence is not a universal override rule. Include MonsterUnique only where an explicit ordinary reference/consumer chain proves participation.

## StageAbility is a later live layer

Stage bootstrap exposes before-/after-character-born StageAbility binding around `WaveMonster`.

Representative StageAbility behavior can mutate live properties after creation, e.g. a conditional `SpeedAddedRatio=-0.3` overlay.

These must remain separate from static HardLevel coefficients.

## Phase-property path is distinct from wave respawn

Pinned ordinary phase archaeology supports a same-entity live phase-property subsystem.

### Yanqing concrete producer chain

Shared Yanqing phase wiring binds phase MaxHP/Stance inputs to `SkillP01` indices. Concrete variants provide different `MonsterSkillConfig.ParamList` values, proving phase property inputs can vary by concrete monster while using the same ConfigCharacter phase wiring.

These are confirmed producer inputs, not a multiplication formula.

### CharacterPhaseOverrideConfig is not Excel MonsterConfig

A corroborating type-layout pass shows `CharacterPhaseOverrideConfig.MonsterConfig` is the JSON `RPG.GameCore.MonsterConfig` type carrying runtime/config fields such as creation timing, initial HP ratio/value, multi-hit normalization, UI/model/location behavior and body-part inheritance flags.

It is not `ExcelOutput/MonsterConfig.json` / `MonsterRow` and must not be cited as evidence that a phase change reselects the static Excel row.

### Huanlong cross-check

Pinned Huanlong phases show:

- phase-specific `OverrideConfig` blocks;
- a phase with dynamic `PhaseMaxHPRatio` and a sibling OverrideConfig;
- authored `SetMonsterPhase(... ApplyOverrideConfig=false)` in the Ability graph.

Therefore `ApplyOverrideConfig` cannot be equated with the existence/application of phase HP/Stance ratio inputs. Static phase-property data and JSON override config are sibling subpaths.

Exact default/application semantics still require the unexported phase runner.

### Common phase transition is not respawn

Pinned `Monster_ChangePhase` operates on the existing caster: reads current state, resets HP/Stance-related state, refreshes UI, emits events and continues the same entity.

No `WaveMonster`/`SummonMonster` or visible Stage/HardLevel row reselection appears in this common path.

## AI note

`MonsterTemplateConfig[1002011]` references sequenced AI. Instance AI/sequence overrides on other monsters remain separate per-instance inputs and must be traced when used.

## False friends / guardrails

- `ILHardLevelGroup` / `ILBattleMonster` are wrong-family examples for ordinary W14.
- GridFight/AetherDivide/other mode difficulty rows need their own mode chain.
- template base values are not final encounter stats.
- Stage rows are not complete monster state.
- `Ratio` fields are not arithmetic authority.
- typed HardLevel reads do not expose the spawn-stat formula.
- `MonsterUniqueConfig` is not universal.
- StageAbility live mutation is not static difficulty scaling.
- phase transition is not wave respawn by default.
- `CharacterPhaseOverrideConfig.MonsterConfig` is not Excel MonsterConfig.
- multiple EliteGroup slots prove capacity, not provenance/order.
- absence of a HardLevel conflict sample is not precedence proof.
- player-facing Toughness units must not replace internal Stance without a conversion consumer.

## Remaining W14/W16 boundaries

Source-facing work still worth pursuing:

1. internal Stance/Toughness conversion only if an exported consumer appears;
2. explicit MonsterUnique participation in families that actually reference it;
3. W16 spawn/transition/reinforcement/termination data where source is exported;
4. phase-property application details only where an individual Ability/config explicitly exposes them.

Frozen until a new engine/source family appears:

- final configured-spawn ATK/DEF/HP/SPD/Stance operator;
- flat-value placement, clamp and rounding;
- Stage/Monster HardLevel and Elite precedence;
- generic phase override default/application order.

W14 remains active for source-family completeness, but the generic final-stat formula is a named blocked-evidence subproblem rather than a reason to repeat the same searches.
