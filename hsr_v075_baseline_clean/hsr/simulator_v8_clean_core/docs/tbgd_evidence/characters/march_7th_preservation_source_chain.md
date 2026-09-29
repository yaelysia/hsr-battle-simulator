# March 7th (Preservation) — Character Source Chain

## Record metadata

- Concept: playable character skill/ability wiring
- Character: March 7th, Preservation form (`Mar_7th_00`)
- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed`
- Confidence: high for the wiring claims below; unreviewed numeric/effect semantics remain explicitly out of scope
- Tracking issue: #7

## Confirmed raw sources

### Character config

Path:

`Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json`

Blob SHA at the pinned revision:

`614cbf345e7d0d7d39adb525a04fc4685b0f48f5`

Observed battle-relevant structure:

- `SkillList[].Name`
- `SkillList[].SkillType`
- `SkillList[].UseType`
- `SkillList[].TargetInfo.TargetType`
- `SkillList[].EntryAbility`
- `SkillList[].PrepareAbility` where present
- `SkillAbilityList[]`
- `AbilityList[]`

Representative wiring at the pinned revision:

- `Skill01` targets `EnemySelect` and enters `Avatar_Mar_7th_00_Skill01_Phase01`.
- `Skill02` targets `FriendSelect` and enters `Avatar_Mar_7th_00_Skill02_Phase01`.
- `Skill03` is `Ultra`, targets `AllEnemy`, enters `Avatar_Mar_7th_00_Skill03_Phase01`, and also names a prepare ability.
- `SkillP01` is passive, targets `Caster`, and enters `Avatar_Mar_7th_00_PassiveSkill01`.

The same file also contains camera, animation, formation, hit-box, and other presentation/runtime-adjacent metadata. Therefore the file is not safe to consume wholesale as a battle-rule object.

Classification:

`mixed_requires_filter`

Field-level judgment:

- skill identity/target/entry-ability relationships above: `battle_authoritative` for wiring;
- camera/animation presentation parameters: `presentation_only` for simulator-rule purposes unless a later audit proves a gameplay dependency;
- other fields: remain `unknown_unreviewed` until individually audited.

### Ability file

Path:

`Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json`

Blob SHA at the pinned revision:

`b9b4e3705a73cb691306d7e68912a7b33e597e94`

The ability named by the character config is present as a concrete `AbilityList` member:

`Avatar_Mar_7th_00_Skill01_Phase01`

Its inspected `OnStart` sequence includes both gameplay/control-flow wiring and clearly presentation-oriented operations. In the inspected prefix it triggers:

- `Avatar_Mar_7th_00_Skill01_Camera`;
- `Avatar_Mar_7th_00_Skill01_Phase02`;
- look-at / animation operations.

This proves an important archaeological rule: an ability file cannot be classified by filename alone, and an `OnStart` list cannot be treated as uniformly battle-semantic. Individual opcode families and referenced abilities require semantic review.

Classification:

`mixed_requires_filter`

## Confirmed reference edge

```text
ConfigCharacter.SkillList[].EntryAbility
    -> ConfigAbility.AbilityList[].Name
```

Concrete example:

```text
Avatar_Mar_7th_00_Config.json
  Skill01.EntryAbility = Avatar_Mar_7th_00_Skill01_Phase01
        |
        v
Avatar_Mar_7th_00_Ability.json
  AbilityList[].Name = Avatar_Mar_7th_00_Skill01_Phase01
```

This edge is `manually_confirmed` and is suitable for a future mechanically checked relationship graph.

## Negative knowledge / false friends

The inspected character config and ability file both mix simulator-relevant relationships with presentation details. In particular:

- camera configuration is not evidence of combat targeting or damage semantics;
- animation timing/state operations are not automatically battle timing rules;
- a referenced ability with `Camera` in its identity must not be promoted merely because it appears in the same execution list as a combat phase;
- alternate activity-specific March 7th configs/abilities (for example special game-mode variants) must not be substituted for the canonical playable-character chain without an explicit mode audit.

## Not yet claimed

This record intentionally does **not** yet claim canonical values or formulas for:

- damage multipliers;
- toughness damage;
- energy generation/cost;
- shield values;
- freeze probability;
- aggro modification;
- follow-up trigger conditions;
- buff duration/stack rules;
- dynamic-value/formula interpretation.

Those claims require deeper opcode/reference tracing and independent external corroboration before this record is promoted to `cross_validated`.

## External corroboration

Status: pending.

When added, corroboration must record the exact live-game/data-site version and the specific claim being checked. External agreement can increase confidence but cannot replace the pinned TBGD source chain.
