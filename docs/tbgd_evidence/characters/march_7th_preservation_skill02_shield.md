# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: Skill02 entry wiring, DynamicValue roles, branch conditions, modifier parameter injection, trace/eidolon hooks, formal shield modifier location
- Battle-scope verdict: `mixed` at Ability-file operation level; battle execution retained, camera/animation/presentation operations excluded
- Runtime production code changed: no

**Important:** this record does not yet claim the final numeric shield formula or base Skill02 parameter values. The DynamicValue roles are closed to their consumers and the formal `MAvatar_March7th_00_BPSkill_Shield` definition has now been located in the pinned Ability file, but the exact pinned `SkillID=100102` numeric definition row plus the modifier-expression opcode/arithmetic and stacking/refresh semantics still need to be resolved.

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
    ├─ Skill02 execution/control flow
    └─ formal modifier definition
         ↓
AddModifier(MAvatar_March7th_00_BPSkill_Shield)
         ↓
MAvatar_March7th_00_BPSkill_Shield
```

## Battle-scope filtering inside the Ability file

`Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json` is a concrete example of why `ConfigAbility` must be filtered below filename level.

Retained battle operations include:

- reading caster `Defence` into a working DynamicValue;
- trace/eidolon predicates;
- debuff removal;
- target HP-ratio comparison;
- modifier application and lifetime inputs;
- shield/heal/aggro DynamicValue injection;
- the formal shield modifier and its callbacks/behavior flags;
- resource operations only after their shared runtime semantics are traced.

Excluded presentation operations include camera triggers, camera-root following, animation state triggers/waits, VFX and comparable choreography when no independent battle-state consequence is demonstrated.

The animation time at which a visual/effect operation is authored must not be promoted into logical simulator timing without proving that it gates battle-state execution.

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

The heal-related working hashes observed around the modifier application, including `-889193254` / `-1361024633`, are not replacements for the five raw Skill02 `SkillParam` hashes above. They belong to the surrounding heal/working-value chain and must be traced separately.

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

## Formal shield modifier located

The same pinned `ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json` contains the formal definition of:

```text
MAvatar_March7th_00_BPSkill_Shield
```

The definition explicitly carries:

- `BehaviorFlagList` containing `Shield`;
- `UseSnapshotEntity = true`;
- callback/configuration structure attached to the modifier.

This closes the earlier archaeology gap "where is the formal shield modifier defined?". It also strengthens the classification of the AddModifier edge as battle-authoritative rather than presentation metadata.

It does **not** yet close the final numeric arithmetic. The modifier and surrounding AddModifier nodes use encoded postfix expressions/DynamicValues. Until those opcodes, operands, snapshot semantics and stack/refresh behavior are traced far enough to prove the equation, the ledger must not turn the observed parameter names into an assumed formula.

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
- locating the modifier definition does not by itself decode postfix arithmetic, snapshot behavior or stack/refresh semantics.
- `SkillParam index=N` does not have a globally reusable meaning across skills.
- public tooltip formulas must not substitute for the missing pinned raw numeric definition.
- `SPNeed` / `SPBase` cannot be classified from their names alone.

## External corroboration status

Current public live-game references are consistent with the structural findings: March 7th's Preservation skill shields an ally based on DEF for a duration and conditionally increases their chance to be attacked; trace/eidolon behavior includes debuff removal, duration extension and healing-related effects.

This corroborates semantic roles only. Current live values are not being used to fill the unresolved pinned numeric row or encoded arithmetic, and version drift must remain explicit. Maturity therefore remains `manually_confirmed` for the raw chain rather than being promoted solely from public descriptions.

## Unresolved follow-ups

1. Locate the exact pinned TBGD row(s) that define `SkillID=100102` / the Skill02 numeric parameter list across the split Avatar skill tables.
2. Decode/validate the formal shield modifier's postfix arithmetic, operand identity, snapshot behavior and stacking/refresh semantics.
3. Trace the exact Trace/Rank numeric sources feeding lifetime extension and healing.
4. Close the Skill02 resource accounting through the shared action/resource runtime rather than interpreting the local `ModifySPNew` operation in isolation.
5. Add version-matched external numeric corroboration only after the pinned raw numeric chain is complete.
