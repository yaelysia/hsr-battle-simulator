# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: Skill02 entry wiring, DynamicValue roles, branch conditions, modifier parameter injection, trace/eidolon hooks
- Runtime production code changed: no

**Important:** this record does not yet claim the final numeric shield formula or base Skill02 parameter values. The DynamicValue roles are closed to consumers, but the exact pinned `SkillID=100102` numeric definition row and the full `MAvatar_March7th_00_BPSkill_Shield` modifier arithmetic still need to be resolved.

## Source chain

```text
AvatarConfig[AvatarID=1001]
    ├─ JsonPath = Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json
    └─ SkillList includes 100102

ConfigCharacter Skill02
    ├─ target = FriendSelect
    └─ EntryAbility = Avatar_Mar_7th_00_Skill02_Phase01
         ↓
ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
    └─ Skill02 execution/control flow
         ↓
AddModifier(MAvatar_March7th_00_BPSkill_Shield)
```

## DynamicValue bindings confirmed from ConfigCharacter

The character config maps Skill02 parameters to stable dynamic hashes:

| Dynamic hash | Raw binding |
|---:|---|
| `-1091495116` | `SkillParam(Skill02, index=0)` |
| `-1016136907` | `SkillParam(Skill02, index=1)` |
| `398047946` | `SkillParam(Skill02, index=2)` |
| `1935511666` | `SkillParam(Skill02, index=3)` |
| `-1672381420` | `SkillParam(Skill02, index=4)` |

The same character config also binds Trace/Rank parameters separately. Therefore Skill parameters, traces, and eidolons must not be flattened into one anonymous parameter array.

## Confirmed execution semantics

Manual inspection of the formal Skill02 Ability shows the following sequence/branches:

1. Reads the caster's `Defence` property into a dynamic working value.
2. Checks trace/eidolon conditions that can alter lifetime/healing/dispelling behavior.
3. A trace hook can remove one negative effect from the target.
4. Compares target HP ratio against the Skill02 index-2 dynamic parameter.
5. Both branches apply `MAvatar_March7th_00_BPSkill_Shield`.
6. The branch satisfying the HP threshold injects the Skill02 index-4 value as `MDF_AggroUp`; the other branch injects `0` for aggro increase.
7. The modifier receives shield, heal, duration, and aggro parameters through DynamicValues rather than embedding one self-contained literal formula in the AddModifier node.

## Consumer meaning of Skill02 parameters

From the actual consumers, not from parameter order guesses:

| Skill02 parameter | Confirmed consumer role |
|---|---|
| index 0 | injected as `MDF_ShieldPercentage` |
| index 1 | base modifier lifetime/duration input |
| index 2 | target HP-ratio threshold controlling the aggro branch |
| index 3 | injected as `MDF_ShieldValue` |
| index 4 | injected as `MDF_AggroUp` when the HP condition passes |

The shield modifier also receives heal-related values from eidolon/rank logic and a caster DEF-derived working value.

## Why this matters for lowering

A naive script might find `AddModifier(MAvatar_March7th_00_BPSkill_Shield)` and treat the modifier name as the whole skill. That would miss source-authoritative behavior implemented in surrounding Ability control flow:

- target HP conditional;
- aggro parameter branching;
- trace-gated debuff removal;
- eidolon-gated heal values;
- duration extension;
- caster DEF capture;
- formal skill resource operation.

Conversely, treating every animation/camera/WaitAnimState operation in the same Ability as combat semantics would over-lower presentation behavior.

For this family the actual battle rule spans at least:

```text
skill metadata
  + ConfigCharacter DynamicValue definitions
  + Ability control flow
  + Modifier implementation
  + Trace/Rank parameter sources
```

## Raw-field naming hazard: `SP`

`AvatarConfig[1001].SPNeed = 120` corresponds to the character's ultimate-energy requirement in this data schema, while skill-level fields such as `SPBase` are used elsewhere for energy/resource generation semantics.

Therefore raw names containing `SP` cannot be mechanically interpreted as player skill points. The simulator catalog must assign semantic names only after tracing the consumer/context.

## Internal targeting hazard

Other abilities on this character show that a user-facing AoE skill can contain internal retarget/random-target operations as part of hit/effect execution. Internal Ability target operations therefore must not automatically define the external action-selection contract. External selectable target shape and internal execution target traversal are separate concepts.

## False friends / hazards

- `CameraConfig`, camera abilities, animation state waits/triggers, radial blur, look-at operations: presentation/control artifacts unless a separate battle consequence is demonstrated.
- modifier name alone is not enough to reconstruct the skill.
- `SkillParam index=N` does not have a globally reusable meaning across skills.
- public tooltip formulas must not substitute for the missing pinned raw numeric definition.
- `SPNeed` / `SPBase` cannot be classified from their names alone.

## External corroboration status

Public live-game descriptions are consistent with the structural findings: March 7th's Preservation skill shields an ally based on DEF for a duration and conditionally increases their chance to be attacked, with trace/eidolon upgrades adding cleansing/healing-related behavior.

This corroborates the semantic structure but is not being used here to fill the unresolved numeric values. Maturity remains `manually_confirmed` until the exact pinned numeric rows and modifier arithmetic are closed.

## Unresolved follow-ups

1. Locate the exact pinned TBGD row(s) that define `SkillID=100102` / the Skill02 numeric parameter list across the split Avatar skill tables.
2. Locate and audit the formal definition of `MAvatar_March7th_00_BPSkill_Shield` to close exact shield arithmetic and stacking/refresh semantics.
3. Trace the exact Trace/Rank numeric sources feeding lifetime extension and healing.
4. Close the Skill02 resource accounting through the shared action/resource runtime rather than interpreting the local `ModifySPNew` operation in isolation.
5. Add live external numeric corroboration only after the raw numeric chain is complete.
