# Light Cone 20000 (`Arrows`) battle-source evidence chain

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `cross_validated`
- Scope: EquipmentID `20000`, effect ranks 1-5, DynamicValue bindings, and executable modifier
- Runtime production code changed: no

## Authority classification

| Source | Role | Classification |
|---|---|---|
| `ExcelOutput/EquipmentConfig.json` | equipment identity, path restriction, skill ID, rank/promotion metadata | `mixed_requires_filter` |
| `ExcelOutput/EquipmentSkillConfig.json` | effect-rank parameters and Ability name | `battle_authoritative` with presentation siblings |
| `Config/ConfigAbility/Equip/EquipmemtAbility.json` | executable light-cone ability and modifier | `battle_authoritative` |
| public live-game data | independent semantic/numeric corroboration | corroboration only |

## Raw reference chain

```text
EquipmentConfig[EquipmentID=20000]
    ├─ SkillID = 20000
    ├─ MaxRank = 5
    └─ AvatarBaseType = Rogue
         ↓
EquipmentSkillConfig[SkillID=20000, Level=1..5]
    ├─ AbilityName = Ability20000
    └─ ParamList
         L1 = [0.12, 3]
         L2 = [0.15, 3]
         L3 = [0.18, 3]
         L4 = [0.21, 3]
         L5 = [0.24, 3]
         ↓
Config/ConfigAbility/Equip/EquipmemtAbility.json
    Ability20000
      └─ AddModifier(MEquip_20000_Main)
           ├─ LifeTime = DynamicHash(-1970381737)
           └─ OnStack -> StackProperty(CriticalChanceBase)
                └─ PropertyValue = DynamicHash(-1330896030)

DynamicValues
    -1330896030 -> SkillEquip index 0
    -1970381737 -> SkillEquip index 1
```

## Confirmed semantics

The two `ParamList` positions are not guessed from order:

- `ParamList[0]` is consumed through `SkillEquip index 0` as `CriticalChanceBase`, therefore it is the CRIT Rate increase;
- `ParamList[1]` is consumed through `SkillEquip index 1` as the modifier `LifeTime`, therefore it is the duration in turns/runtime lifetime units used by this modifier family.

At the five effect/superimposition levels this yields:

| Effect level | CRIT Rate input | Lifetime input |
|---:|---:|---:|
| 1 | 0.12 | 3 |
| 2 | 0.15 | 3 |
| 3 | 0.18 | 3 |
| 4 | 0.21 | 3 |
| 5 | 0.24 | 3 |

The primary lesson is that `EquipmentSkillConfig.ParamList` is only a numeric definition table. Semantic meaning comes from the Ability/Modifier consumer.

## Independent corroboration

Current live HSR public data for the 3-star Hunt light cone **Arrows** states that, at the start of battle, the wearer gains 12% CRIT Rate for 3 turns at base superimposition, matching the raw Level 1 pair `[0.12, 3]` and the inspected `CriticalChanceBase`/`LifeTime` consumers.

This raises the record from `manually_confirmed` to `cross_validated`; the public site is corroboration, not source authority.

## Mixed / non-battle fields

`EquipmentConfig` also contains progression/economy/display information. These must not be promoted wholesale into combat IR. Examples include promotion limits/material/economy/UI metadata that are useful for inventory/build construction but are not battle execution rules.

The project already identifies several neighboring false-friend table families:

- EXP / reward / compose/material tables;
- equipment/relic recommendation tables;
- atlas/item-display tables;
- mode-specific or tooling-only equipment/relic tables.

These are candidate exclusions, subject to manual review of any field later required by build construction.

## Search hazard discovered

A global source search may return multiple `Ability20000` occurrences or historical/alternate roots. For project evidence, the accepted gameplay root is the pinned `Config/ConfigAbility/Equip` chain selected by the project's equipment discovery/lowering logic. Search result rank is not authority.

## Unresolved follow-ups

1. Trace the exact public-name/TextMap identity directly from pinned TBGD instead of relying on external naming.
2. Audit `EquipmentPromotionConfig` separately for battle-build base-stat construction; progression data may still contain inputs needed before battle initialization even if it is not runtime execution data.
3. Audit conditional, stackable, target-dependent, debuff, and event-triggered light cones; `Ability20000` is intentionally a simple baseline.
4. Establish how internal `AvatarBaseType` enums map to public Paths using pinned source, rather than hardcoding names from community knowledge.
