# Monster 1002011 battle-source evidence chain

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: representative ordinary monster identity/template/skill chain plus corrected ordinary hard-level scaling inputs and final-stat evidence boundary
- Runtime production code changed: no

This record intentionally does **not** assign a localized/public display name to MonsterID `1002011` yet. The config path strongly associates it with the Cocolia P1 weapon family, but the pinned TextMap/display-name chain is not closed here.

## Critical W14 correction

The earlier version of this record treated `ExcelOutput/ILHardLevelGroup.json` as part of the ordinary monster scaling chain. That classification is **superseded**.

The first parallel W14/W16 audit re-read the ordinary and `IL*` families and established:

- ordinary five-stat `(HardLevelGroup,Level)` inputs are in `ExcelOutput/HardLevelGroup.json`;
- `ILHardLevelGroup` / `ILBattleMonster` belong to a separate RtBattle/IL family for the inspected numeric collision and are not ordinary W14 authority.

The previously recorded `ILHardLevelGroup` values (`700.23926`, `69.67834`, `619.263`) remain real raw values in that other family, but must not be used to construct this ordinary monster's stats.

## Authority classification

| Source | Role | Classification |
|---|---|---|
| `ExcelOutput/MonsterConfig.json` | concrete monster identity, weaknesses/resists/skills/instance modifications | `battle_authoritative` / mixed |
| `ExcelOutput/MonsterTemplateConfig.json` | base ATK/DEF/HP/SPD/Stance and config/AI path | `battle_authoritative` |
| `ExcelOutput/HardLevelGroup.json` | ordinary `(HardLevelGroup,Level)` ATK/DEF/HP/SPD/Stance scaling inputs | `battle_authoritative` input family; final operator unresolved |
| `ExcelOutput/ILHardLevelGroup.json` | RtBattle/IL scaling family | `false_positive` for this ordinary W14 chain |
| `ExcelOutput/MonsterUniqueConfig.json` | conditional candidate override family | record-level participation must be explicitly referenced; not universal |
| `ExcelOutput/MonsterSkillConfig.json` | skill metadata and numeric parameters | `battle_authoritative` |
| `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json` | ordinary skill entry wiring / DynamicHash bindings | `battle_authoritative` |
| `Config/ConfigAbility/Monster/Monster_W1_CocoliaP1_01_Ability.json` | executable battle graph | `battle_authoritative` |
| `Config/ConfigAI/Monster_Common_SequenceThree_AI.json` | sequenced-skill AI data | `battle_supporting` / AI authority for the inspected control surface |

## Raw identity / skill chain

```text
MonsterConfig[MonsterID=1002011]
  -> MonsterTemplateID = 1002011
  -> MonsterTemplateConfig[1002011]
       JsonConfig = Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
       AIPath = Config/ConfigAI/Monster_Common_SequenceThree_AI.json
       base ATK/DEF/HP/SPD/Stance

MonsterConfig[1002011].SkillList = [100201101]
  -> MonsterSkillConfig[100201101]
       SkillTriggerKey = Skill04
       ParamList[0] = 2
  -> ConfigCharacter DynamicHash(-190305622)
       SkillParam(Skill04,index=0)
  -> ConfigAbility Skill04 damage consumer
       DamageByAttackProperty
       Target = AllEnemy
       DamageType = Ice
       DamagePercentage = DynamicHash(-190305622)
```

## Confirmed concrete instance facts

The inspected ordinary `MonsterConfig[1002011]` establishes:

- `MonsterTemplateID=1002011`;
- weaknesses: Fire and Thunder;
- 20% resistance to Physical, Ice, Wind, Quantum and Imaginary;
- Freeze control resistance `1`;
- formal skill list `[100201101]` for the inspected instance;
- no promoted instance-local summon/custom/dynamic/AI-sequence override in this row.

These are instance-level battle facts and should not be inferred from the template.

## Confirmed template facts

Exact pinned `MonsterTemplateConfig[1002011]` supplies:

- ATK base `18`
- DEF base `210`
- HP base `69.75`
- SPD base `100`
- Stance base `60`
- stance type Ice
- status resistance base `0.2`
- character config path `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json`
- AI path `Config/ConfigAI/Monster_Common_SequenceThree_AI.json`

This resolves the older `1002010`/`1002011` template ambiguity: the referenced template is `1002011` at the pin.

Template bases are not final encounter properties.

## Correct ordinary hard-level input family

Exact pinned ordinary source:

`ExcelOutput/HardLevelGroup.json`

blob:

`9ee36b767b010d2c85aa7169e86e9f0a4220a935`

Rows are keyed by `(HardLevelGroup, Level)` and expose:

- `AttackRatio`
- `DefenceRatio`
- `HPRatio`
- `SpeedRatio`
- `StanceRatio`

Cross-checked examples include:

| HardLevelGroup | Level | ATK | DEF | HP | SPD | Stance |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 29 | `5.19238` | `2.333333` | `5.020885` | `1` | `1` |
| 1 | 40 | `8.634539` | `2.857143` | `9.524581` | `1` | `1` |
| 2 | 29 | `6.127009` | `2.333333` | `13.429104` | `1` | `1` |

The first parallel audit also confirmed that group 1 `SpeedRatio` changes from `1` at level 65 to `1.1` at level 66. Therefore SPD scaling is a real ordinary data input, not an assumed constant.

These fields remain **inputs**. Their `Ratio` names do not prove the final multiply/add/replace/clamp operator.

## Final-stat construction model: confirmed topology, unresolved arithmetic

The current evidence supports a layered ordinary construction model rather than a single complete row:

```text
wave / encounter occurrence
  -> concrete MonsterConfig
       + MonsterTemplateConfig base inputs
       + effective HardLevelGroup + Level inputs
       + concrete MonsterConfig EliteGroup / flat modifications where present
       + encounter Stage/Elite context where present
  -> configured spawn-property domain
  -> optional same-entity phase-property overrides
  -> live StageAbility / Ability / Modifier overlays
  -> current battle properties
```

The parallel W14/W16 audit cross-corroborated this topology against runtime-facing `MonsterRowData`/phase configuration structures, but the actual final getter/operator bodies were not available in source form. Therefore exact arithmetic, precedence, clamp/rounding and flat-value placement remain unresolved.

### Concrete hazards discovered beyond this sample

Pinned ordinary data includes non-zero flat speed modifications in concrete monster rows, for example:

- Monster `100202014`, template `1002020`, `SpeedModifyValue=33`
- Monster `100202010`, template `1002020`, `SpeedModifyValue=20`

and template-level flat speed/stance modification fields also exist.

These are high-value discriminating inputs for a future operator recovery. They must not be silently dropped or placed by community-formula intuition.

### Stage/Monster Elite coexistence

Representative Stage data shows Stage-level EliteGroup and concrete MonsterConfig EliteGroup can coexist (for example Stage `301001` uses a different EliteGroup from inspected concrete monsters). This proves two context layers can be simultaneously present; it does not prove whether runtime replaces, composes or otherwise orders them.

### MonsterUnique is conditional, not universal

The first parallel audit did not find a matching `MonsterUniqueConfig` row for several representative ordinary IDs, including `1002011`. Therefore `MonsterUniqueConfig` must only enter a final formula when an explicit reference/consumer chain proves it for that family. Family existence alone is not enough.

## StageAbility and phase are later layers, not static hard-level coefficients

W16 found two relevant distinctions:

1. Stage bootstrap has explicit pre-/post-monster-birth StageAbility binding phases around `WaveMonster`.
2. StageAbility can mutate live properties after creation (for example a representative stage applies a `SpeedAddedRatio` mutation under a condition).

Those live overlays must not be folded into static `HardLevelGroup` coefficients.

The parallel audit also closed a representative Yanqing phase-property producer chain showing that phase can supply HP/Stance ratio inputs to the **existing monster entity**. Common phase transition logic does not imply wave respawn, but exact phase override arithmetic/order remains an engine/operator question.

## Closed numeric proof: Skill 100201101 damage multiplier

The original skill-param proof remains valid and is independent of the W14 scaling correction:

1. `MonsterSkillConfig[100201101]` has `SkillTriggerKey=Skill04`, `ParamList[0]=2`.
2. ConfigCharacter maps DynamicHash `-190305622` to `SkillParam(Skill04,index=0)`.
3. The ordinary Skill04 Ability uses that hash as `DamagePercentage` in an AoE Ice `DamageByAttackProperty` consumer.

Therefore the pinned raw value `2` is the 2.0 damage-percentage input for that specific formal operation.

This is an example of why ParamList positions require consumer tracing.

## AI semantics

The template points to `Monster_Common_SequenceThree_AI.json`, whose inspected surface uses sequenced-skill behavior. Instance-level `OverrideAIPath` / sequence fields, where present on other monsters, must take precedence according to their own consumer rules and must not be ignored simply because a template AI exists.

## False friends / hazards

- `ILHardLevelGroup` / `ILBattleMonster` are explicit wrong-family examples for ordinary W14 despite plausible names and matching numeric keys.
- Template base values are not final encounter stats.
- Stage rows are not complete monster-state rows.
- `Ratio` field names are not arithmetic authority.
- `MonsterUniqueConfig` is not a universal override layer.
- live StageAbility property mutations are separate from static spawn-stat construction.
- phase count/labels are not equivalent to respawn, and same-entity phase transitions do not imply phase-property overrides never exist.
- public/player-facing Toughness units must not be substituted for internal Stance without a conversion consumer.
- target/look-up references to a MonsterID do not prove the missing creation/config-selection authority for that instance.

## Remaining W14/W16 boundaries

1. Recover/establish the final configured-stat operators for ATK/DEF/HP/SPD/Stance.
2. Settle flat `*ModifyValue` placement and precedence.
3. Settle Stage versus Monster HardLevelGroup/Level ownership when conflicting values exist.
4. Settle Stage EliteGroup versus MonsterConfig EliteGroup composition/precedence.
5. Recover phase override application/order and omitted `ApplyOverrideConfig` semantics.
6. Resolve internal Stance versus player-facing Toughness conversion only with its consumer.
7. Bring `MonsterUniqueConfig` into a chain only where explicitly referenced.

Until those operators are available, W14 remains `active/partial`; the input-family correction does not justify inventing final formulas.
