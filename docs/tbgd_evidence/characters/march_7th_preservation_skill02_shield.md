# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`
- Scope: ordinary-combat Skill02 entry wiring, DynamicValue roles, branch conditions, modifier parameter injection, trace/eidolon hooks, formal shield modifier location, and rejected same-ID event data
- Battle-scope verdict: `mixed` at Ability-file operation level; battle execution retained, camera/animation/presentation operations excluded; event/RtBattle same-ID records are `deferred`
- Runtime production code changed: no

**Important:** this record does not yet claim the final numeric shield formula or base ordinary-combat Skill02 parameter values. The DynamicValue roles are closed to their consumers and the formal `MAvatar_March7th_00_BPSkill_Shield` definition has been located in the pinned ordinary Ability file. A mechanically tempting `ID=100102` row was also found in `ILBattleAvatarSkill.json`, but manual parent-table inspection proves that row belongs to an event `Config/Activity/RtBattle/**` character family and must not be used as the ordinary March 7th numeric authority.

## Ordinary-combat source chain

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

## DynamicValue bindings confirmed from ordinary ConfigCharacter

The ordinary character config maps Skill02 parameters to stable dynamic hashes:

| Dynamic hash | Raw binding |
|---:|---|
| `-1091495116` | `SkillParam(Skill02, index=0)` |
| `-1016136907` | `SkillParam(Skill02, index=1)` |
| `398047946` | `SkillParam(Skill02, index=2)` |
| `1935511666` | `SkillParam(Skill02, index=3)` |
| `-1672381420` | `SkillParam(Skill02, index=4)` |

The same character config binds Trace/Rank parameters separately. Skill parameters, traces and eidolons must therefore not be flattened into one anonymous parameter array.

## Confirmed ordinary execution semantics

Manual inspection of the Skill02 Ability shows the following sequence/branches:

1. Reads the caster's `Defence` property into a dynamic working value.
2. Checks trace/eidolon conditions that can alter lifetime/healing/dispelling behavior.
3. A trace hook can remove one negative effect from the target.
4. Compares target HP ratio against the Skill02 index-2 dynamic parameter.
5. Both branches apply `MAvatar_March7th_00_BPSkill_Shield`.
6. The branch satisfying the HP threshold injects the Skill02 index-4 value as `MDF_AggroUp`; the other branch injects `0` for aggro increase.
7. The modifier receives shield, heal, duration and aggro parameters through DynamicValues rather than embedding one self-contained literal formula in the AddModifier node.

The heal-related working hashes observed around modifier application, including `-889193254` / `-1361024633`, are not replacements for the five raw Skill02 `SkillParam` hashes above. They belong to the surrounding heal/working-value chain and must be traced separately.

## Consumer meaning of Skill02 parameters

These meanings come from the actual consumers, not from parameter-order guesses:

| Skill02 parameter | Confirmed consumer role |
|---|---|
| index 0 | injected as `MDF_ShieldPercentage` |
| index 1 | base modifier lifetime/duration input |
| index 2 | target HP-ratio threshold controlling the aggro branch |
| index 3 | injected as `MDF_ShieldValue` |
| index 4 | injected as `MDF_AggroUp` when the HP condition passes |

The shield modifier also receives heal-related values from eidolon/rank logic and a caster DEF-derived working value.

## Formal shield modifier located

The same pinned ordinary file:

`Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json`

contains the formal definition of:

```text
MAvatar_March7th_00_BPSkill_Shield
```

The definition explicitly carries:

- `BehaviorFlagList` containing `Shield`;
- `UseSnapshotEntity = true`;
- callback/configuration structure attached to the modifier.

This closes the earlier archaeology gap about where the formal shield modifier is defined. It does **not** close the final arithmetic. The modifier and surrounding AddModifier nodes use encoded postfix expressions/DynamicValues. Until those opcodes, operands, snapshot semantics and stack/refresh behavior are traced far enough to prove the equation, the ledger must not turn observed parameter names into an assumed formula.

## Rejected same-ID candidate: `ILBattleAvatarSkill[100102]`

Mechanical search of the pinned ExcelOutput family finds this row in:

`ExcelOutput/ILBattleAvatarSkill.json`

with:

- `ID = 100102`
- `InitialCD.Value = 6`
- `CoolDown.Value = 12`
- `ParamList = [6, 0.3, 6, 1, 6]`
- `MaxLevel = 10`

The ID match is **not** sufficient to use those numbers for ordinary March 7th.

Manual inspection of the parent family in:

`ExcelOutput/ILBattleAvatar.json`

shows `ID = 1001` pointing to:

`Config/Activity/RtBattle/ConfigCharacter/Avatar/IL_Launch_00_Config.json`

and carrying event-character metadata including:

- `AvatarBaseType = Hunt`
- `Rarity = CombatPowerAvatarRarityType5`

Those properties do not describe the ordinary Preservation March 7th chain above. The `ILBattleAvatar*` family is an event/RtBattle family under the current scope, so this same-ID candidate is `deferred` and its `[6, 0.3, 6, 1, 6]` values are explicitly rejected as evidence for the ordinary Skill02 shield.

This is an important negative-evidence case: exact numeric ID collisions across source families make script-only matching unsafe.

## `AvatarSkillConfigLD.json` is not the missing `100102` row

The pinned `ExcelOutput/AvatarSkillConfigLD.json` was also manually inspected. It contains battle-facing skill fields in its actual rows, including skill IDs, target/effect/AI-related fields and parameter lists, so it must **not** be blanket-labelled a pure presentation table.

However, an exact search of this pinned file found no `SkillID = 100102`. Therefore it is not the direct ordinary March Skill02 numeric source at this revision.

A previously mentioned `AvatarSkillConfigLDPath.json` path has not been re-established in the pinned tree and must not be used as evidence until existence is confirmed.

## Why this matters for lowering

A naive crawler can fail in two opposite directions:

1. find `AddModifier(MAvatar_March7th_00_BPSkill_Shield)` and miss battle control flow around it — HP threshold, aggro branching, trace-gated dispel, eidolon healing, duration changes and DEF capture;
2. find a numerically matching `100102` in an unrelated event family and silently import the wrong parameters.

For this ordinary skill the battle rule currently spans at least:

```text
ordinary avatar/skill metadata
  + ConfigCharacter DynamicValue definitions
  + ordinary Ability control flow
  + Modifier implementation
  + Trace/Rank parameter sources
  + still-unresolved ordinary numeric SkillParam source
```

## Raw-field naming hazard: `SP`

`AvatarConfig[1001].SPNeed = 120` corresponds to the character's ultimate-energy requirement in this data schema, while skill-level fields such as `SPBase` are used elsewhere for resource/energy-generation semantics.

Therefore raw names containing `SP` cannot be mechanically interpreted as player skill points. Semantic names require consumer/context tracing.

## Internal targeting hazard

Other abilities on this character show that a user-facing AoE skill can contain internal retarget/random-target operations as part of hit/effect execution. Internal Ability target operations therefore must not automatically define the external action-selection contract. External selectable target shape and internal execution target traversal are separate concepts.

## False friends / hazards

- `ILBattleAvatarSkill[100102]` is a confirmed same-ID false positive from deferred `Config/Activity/RtBattle/**` content.
- `AvatarSkillConfigLD.json` contains genuine battle-facing fields in some rows, but has no pinned `100102`; it is neither the missing March row nor safely classifiable by the `LD` name alone.
- camera abilities, animation state waits/triggers, radial blur and look-at operations are presentation/control artifacts unless a separate battle consequence is demonstrated.
- modifier name alone is not enough to reconstruct a skill.
- locating the modifier definition does not decode postfix arithmetic, snapshot behavior or stack/refresh semantics.
- `SkillParam index=N` has no globally reusable meaning across skills.
- public tooltip formulas must not substitute for the missing pinned ordinary numeric definition.
- `SPNeed` / `SPBase` cannot be classified from their names alone.

## External corroboration status

Current public live-game references are consistent with the structural findings: March 7th's Preservation skill shields an ally based on DEF for a duration and conditionally increases their chance to be attacked; trace/eidolon behavior includes debuff removal, duration extension and healing-related effects.

This corroborates semantic roles only. Current live values are not being used to fill the unresolved pinned ordinary numeric row or encoded arithmetic, and version drift must remain explicit.

## Unresolved follow-ups

1. Locate the exact pinned ordinary-combat TBGD row(s), if present, that supply the five `SkillParam(Skill02,index=0..4)` numeric values for the `Avatar_Mar_7th_00` chain; if the pinned export omits them, record that omission explicitly rather than substituting event/live data.
2. Decode/validate the formal shield modifier's postfix arithmetic, operand identity, snapshot behavior and stacking/refresh semantics.
3. Trace the exact Trace/Rank numeric sources feeding lifetime extension and healing.
4. Close Skill02 resource accounting through the shared action/resource runtime rather than interpreting local resource operations in isolation.
5. Add version-matched external numeric corroboration only after the pinned ordinary numeric chain is complete or the pinned omission has been proven.
