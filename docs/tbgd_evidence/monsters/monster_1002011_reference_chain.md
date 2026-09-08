# Monster 1002011 battle-source evidence chain

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: one concrete monster instance, its template, skill metadata, character wiring, ability semantics, AI source, and pinned inputs relevant to final-stat scaling
- Runtime production code changed: no

This record intentionally does **not** assign a localized/public display name to MonsterID `1002011` yet. The template path strongly associates it with the Cocolia P1 weapon entity, but the display-name/TextMap chain has not been manually closed at the pinned revision.

## Authority classification

| Source | Role | Classification |
|---|---|---|
| `ExcelOutput/MonsterConfig.json` | instance-level weaknesses/resists/skills/overrides | `battle_authoritative` with mixed non-runtime metadata possible |
| `ExcelOutput/MonsterTemplateConfig.json` | base stats, stance, base AI/config path | `battle_authoritative` |
| `ExcelOutput/ILHardLevelGroup.json` | level/hard-level HP/ATK/DEF scaling inputs reached by the stage chain | `battle_authoritative` for the manually traced lookup; composition operation still unresolved |
| `ExcelOutput/MonsterUniqueConfig.json` | candidate unique-monster scaling/override layer | exact-pin family confirmed; record-level role for `1002011` still unresolved |
| `ExcelOutput/MonsterSkillConfig.json` | skill metadata and numeric parameters | `battle_authoritative` |
| `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json` | skill entry wiring and DynamicHash bindings | `battle_authoritative` |
| `Config/ConfigAbility/Monster/Monster_W1_CocoliaP1_01_Ability.json` | executable ability semantics | `battle_authoritative` |
| `Config/ConfigAI/Monster_Common_SequenceThree_AI.json` | generic sequenced-skill AI mechanism | `battle_supporting` / runtime authoritative for AI control flow |

## Raw reference chain

```text
MonsterConfig[MonsterID=1002011]
    ├─ MonsterTemplateID = 1002011
    │    ↓
    │  MonsterTemplateConfig[1002011]
    │    ├─ JsonConfig = Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json
    │    ├─ base ATK/DEF/HP/SPD/Stance
    │    └─ AIPath = Config/ConfigAI/Monster_Common_SequenceThree_AI.json
    │
    └─ SkillList = [100201101]
         ↓
       MonsterSkillConfig[100201101]
         ├─ SkillTriggerKey = Skill04
         ├─ DamageType = Ice
         ├─ AttackType = Normal
         └─ ParamList[0] = 2

ConfigCharacter Skill04
    └─ EntryAbility = Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01
         ↓
ConfigAbility ... Skill04 Phase02
    └─ DamageByAttackProperty
         ├─ Target = AllEnemy
         ├─ DamageType = Ice
         └─ DamagePercentage = DynamicHash(-190305622)

ConfigCharacter DynamicValues[-190305622]
    └─ SkillParam(trigger=Skill04, index=0)
         ↓
MonsterSkillConfig[100201101].ParamList[0] = 2
```

## Confirmed instance semantics

`MonsterConfig[1002011]` confirms:

- weaknesses: Fire and Thunder;
- 20% resistance to Physical, Ice, Wind, Quantum, and Imaginary;
- Freeze control resistance: `1`;
- formal skill list: only `100201101` in this instance row;
- no instance-local summon list, custom values, dynamic values, skill-parameter override, AI path override, or sequence override in the inspected row.

These values are instance-level battle facts. They must not be inferred from the template alone.

## Confirmed template semantics

`MonsterTemplateConfig[1002011]` supplies the base/template layer:

- rank: `MinionLv2`;
- ATK base: `18`;
- DEF base: `210`;
- HP base: `69.75`;
- SPD base: `100`;
- stance base: `60`;
- stance type: `Ice`;
- status resistance base: `0.2`;
- character config path: `Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json`;
- AI path: `Config/ConfigAI/Monster_Common_SequenceThree_AI.json`.

The direct exact-pin row therefore resolves the earlier `1002010` versus `1002011` template-ID ambiguity for this investigation: the referenced template is `MonsterTemplateID=1002011` at the pinned revision.

Therefore a complete monster combat card must merge the concrete `MonsterConfig` row with its `MonsterTemplateConfig`, rather than treating either table as self-contained.

## Pinned final-stat input checkpoint

The current W14 archaeology now has exact pinned identities for the major source families without claiming a final composition formula prematurely:

| Source | Exact-pin blob SHA | Confirmed input at this checkpoint |
|---|---|---|
| `ExcelOutput/MonsterConfig.json` | `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` | concrete instance family; prior row audit establishes `MonsterID=1002011 -> MonsterTemplateID=1002011` and the instance facts above |
| `ExcelOutput/MonsterTemplateConfig.json` | `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` | row `MonsterTemplateID=1002011`: ATK `18`, DEF `210`, HP `69.75`, SPD `100`, Stance `60` |
| `ExcelOutput/ILHardLevelGroup.json` | `0440228b44d6fd1cfbc1ac823f9148b48e02b595` | `(HardLevelGroup=1, Level=29)`: `AttackRatio=700.23926`, `DefenceRatio=69.67834`, `HPRatio=619.263` |
| `ExcelOutput/MonsterUniqueConfig.json` | `a0fde2b2bbd00b82eaa48d2f2c1e253571bdec4b` | exact pinned family exists; no `1002011` row/operator claim is promoted by this checkpoint |

These raw values are **inputs, not yet an equation**. Field names such as `AttackRatio`/`HPRatio` do not establish whether the runtime adds, multiplies, normalizes, clamps, replaces, or otherwise combines them. The final HP/ATK/DEF composition and any MonsterUnique precedence remain unresolved until a real consumer or equivalent manually closed producer/consumer chain establishes the operation.

This checkpoint also deliberately keeps SPD and Stance separate from the three `ILHardLevelGroup` fields above: the inspected hard-level row exposes HP/ATK/DEF ratios, but does not by itself prove how final SPD/Stance are constructed.

## Closed numeric proof: Skill 100201101 damage multiplier

The exact source chain for the skill's base damage percentage is closed without relying on description text:

1. `MonsterSkillConfig[100201101]` declares `SkillTriggerKey=Skill04` and `ParamList[0]=2`.
2. The template's `JsonConfig` leads to `Monster_W1_CocoliaP1_01_Config.json`.
3. That character config binds DynamicHash `-190305622` to `SkillParam(Skill04, index=0)`.
4. `Skill04` enters `Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01`.
5. The corresponding ability's damage operation targets `AllEnemy`, uses Ice damage, and takes `DamagePercentage` from DynamicHash `-190305622`.

**Conclusion:** for this pinned source, `ParamList[0] = 2` is the 2.0 / 200% ATK damage-percentage input consumed by this formal AoE Ice damage operation.

This is a strong example of why `ParamList` cannot be interpreted by position alone. Its meaning is established only after following the DynamicHash consumer.

## AI semantics

The template references `Monster_Common_SequenceThree_AI.json`. The inspected AI root uses a sequenced-skill mechanism (`UseSequencedSkill`). Therefore skill order is controlled through typed/configured AI sequence data, not through localized skill descriptions.

When an instance supplies `OverrideAIPath` or `OverrideAISkillSequence`, those must be treated as instance-level overrides rather than ignored in favor of the template.

## False friends / hazards

- Template base stats are **not** final encounter stats by themselves; stage/level scaling remains a separate unresolved layer.
- Raw fields named `*Ratio` are not arithmetic authority; their consumer determines the operation and precedence.
- `MonsterSkillConfig.ParamList[i]` positions have no safe global semantic meaning. The actual consumer must be traced.
- A filename containing `Cocolia` is not sufficient evidence for a public display identity.
- A generic AI path does not mean every instance uses the same sequence; instance overrides exist in the schema.
- Localized descriptions are not numeric authority.

## External corroboration

Public HSR references confirm that Cocolia-related battle content includes summoned ice/weapon entities, which is consistent with the inspected source family. This is contextual corroboration only; it is not used to prove the exact MonsterID display identity or the 2.0 multiplier.

## Unresolved follow-ups

1. Close MonsterID `1002011` -> TextMap/display-name identity at the pinned revision.
2. Prove the actual operation and precedence joining stage `Level`/`HardLevelGroup`, `ILHardLevelGroup`, `MonsterTemplateConfig`, any applicable `MonsterUniqueConfig`, and instance overrides into final HP/ATK/DEF; separately close final SPD/Stance construction.
3. Determine whether `MonsterUniqueConfig` contributes to this exact instance or only to other monster families; do not infer this from family existence.
4. Confirm how `StatusResistanceBase` combines with per-instance `DebuffResist` and mechanic-specific resistance checks.
5. Audit `OverrideSkillParams`, `CustomValues`, and `DynamicValues` on representative monsters that actually use them.
6. Audit non-sequenced/complex AI paths separately; this sample only proves the simple sequenced family.