# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed`, with unrelated ordinary-character cross-checks for the `SkillParam` producer/binding model and independent postfix-expression samples
- Scope: ordinary Skill02 numeric authority, typed parameter bindings, target/control flow, lifetime expression, trace/eidolon branches, shield lifecycle hooks, dispellability, snapshot-routing inputs, and explicit engine/export boundaries
- Battle-scope verdict: `mixed` at Ability-operation level; battle execution retained, presentation operations excluded; same-ID RtBattle records are false friends for this ordinary chain
- Runtime production code changed: no

## Correction history

This record supersedes older archaeology claims that:

1. pinned `ExcelOutput/AvatarSkillConfig.json` had no ordinary March `SkillID=100102` row — it does; the earlier result was a large-file/search false negative;
2. the main shield initializes on `OnCreate` — exact pin shows `OnStack -> InitShield`, `Stacking="Replace"`, and `OnDestroy -> RemoveShield`;
3. shield dispellability was unresolved — exact `AvatarStatusConfig[10010011]` now closes `CanDispel=true` for the ordinary main shield.

`ILBattleAvatarSkill[100102]` remains a real numeric-ID collision from deferred RtBattle content and is rejected as ordinary March authority.

## Gameplay semantic model

The ordinary Skill02 is a selected-ally support action. The pinned source chain must account for:

- selected ally targeting;
- DEF-based shield operands;
- base lifetime plus trace lifetime extension;
- an HP-ratio branch that conditionally injects aggro increase;
- trace-gated dispel;
- rank/eidolon healing behavior;
- replacement/removal lifecycle;
- dispellability;
- snapshot semantics without assuming an unexported capture algorithm.

Gameplay knowledge is used only as a completeness oracle; the pinned producer/consumer chain remains authority.

## Ordinary source chain

```text
AvatarConfig[AvatarID=1001]
  -> ordinary SkillID 100102
  -> ExcelOutput/AvatarSkillConfig.json[SkillID=100102, Level]
       ParamList[index]
  -> Config/ConfigCharacter/Avatar/Avatar_Mar_7th_00_Config.json
       SkillParam(Skill02,index) -> DynamicHash
  -> Config/ConfigAbility/Avatar/Avatar_Mar_7th_00_Ability.json
       Skill02 control flow
  -> AddModifier(MAvatar_March7th_00_BPSkill_Shield)
  -> shield modifier callbacks/property consumers
```

Exact pinned `AvatarSkillConfig.json` blob:

`a5416ced941c247d475b2aaa83277b9cdf474dd9`

Manually inspected rows include:

- Level 11: `[0.589, 3, 0.3, 802.75, 5]`
- Level 12: `[0.608, 3, 0.3, 845.5, 5]`

These are raw operands; semantics come from consumers rather than positional guessing.

## Typed bindings and consumer mapping

| Index | Dynamic hash | Confirmed consumer role |
|---:|---:|---|
| 0 | `-1091495116` | `MDF_ShieldPercentage` -> `InitShield.ShieldPercentage` |
| 1 | `-1016136907` | base shield lifetime operand |
| 2 | `398047946` | selected-target HP-ratio threshold |
| 3 | `1935511666` | `MDF_ShieldValue` -> `InitShield.ShieldValue` |
| 4 | `-1672381420` | HP-gated `MDF_AggroUp` -> `AggroAddedRatio` |

CharacterConfig declares `FriendSelect`. Ability application targets `AbilityTargetEntity`.

The HP comparison is `GreaterEqual`: when target HP ratio is `>= SkillParam[2]`, `SkillParam[4]` is injected as the aggro operand; otherwise the same shield is applied with aggro input `0`.

## Parameter-family authority

The inspected ordinary samples support distinct producer/index spaces:

- `SkillParam` -> `AvatarSkillConfig[SkillID,Level].ParamList[index]`
- `SkillTreeParam` -> `AvatarSkillTreeConfig[PointID/PointTriggerKey].ParamList[index]`
- `SkillRank` -> `AvatarRankConfig[RankID/rank trigger].Param[index]`
- `SkillAddLevelList` -> independent skill-level increment mechanism, not another ParamList producer.

Dan Heng independently cross-validates the ordinary `AvatarSkillConfig -> CharacterConfig SkillParam -> Ability consumer` pattern.

W02's March producer gap is therefore closed; broader family exhaustiveness remains a separate corpus-completeness task.

## Trace and rank branches

Pinned ordinary data confirms:

- PointB1: `DispelStatus` on `AbilityTargetEntity`, `Numbers=1`, `Order="LastAdded"`;
- PointB2: `AvatarSkillTreeConfig` point `1001102` has `ParamList=[1]`; Skill02 writes this to `_Tree02_LifeTimeAdd`, otherwise `0`;
- Rank06: `AvatarRankConfig[100106]` has `Param=[0.04,106]`; Skill02 injects heal operands when active, otherwise zeros.

Trace/rank parameters are not part of the five ordinary Skill02 operands.

## Lifetime and postfix-expression closure

The lifetime input is source-backed as:

`SkillParam[1] + _Tree02_LifeTimeAdd`

Independent exact-pin samples establish the relevant postfix operator bytes:

- `0x02` -> addition;
- `0x03` -> subtraction;
- `0x04` -> multiplication.

Therefore, with ordinary rows whose index 1 is `3`, the modifier lifetime input is `3` without PointB2 and `4` with PointB2.

## Formal main-shield lifecycle

Exact `MAvatar_March7th_00_BPSkill_Shield` confirms:

- `BehaviorFlagList` includes `Shield`;
- `UseSnapshotEntity=true`;
- `Stacking="Replace"`;
- `OnCreate` performs resilience/effect setup, not `InitShield`;
- `OnStack` performs `InitShield(ModifierOwnerEntity)` with:
  - `FormulaType="ShieldByCasterDefence"`
  - injected shield percentage
  - injected flat shield value
  - and applies injected `AggroAddedRatio`;
- `OnDestroy` explicitly calls `RemoveShield` and resets resilience state;
- `OnPhase1` contains the Rank06 heal branch when its injected heal operand is positive.

This closes character-local application/reapplication/removal hooks. It does not expose generic `ShieldByCasterDefence`, snapshot capture, or Replace dispatcher internals.

## Main-shield dispellability now closed

Exact pinned `ExcelOutput/AvatarStatusConfig.json`:

- `StatusID=10010011`
- `ModifierName="MAvatar_March7th_00_BPSkill_Shield"`
- `StatusType="Buff"`
- `CanDispel=true`

Therefore the ordinary main Skill02 shield is source-confirmed dispellable.

The neighboring Rank02 shield is a distinct status and is also dispellable; it must not be conflated with the ordinary Skill02 modifier.

## Snapshot subsystem: real routing surface, capture algorithm unavailable

The pin exports explicit snapshot infrastructure:

- `GameCoreConstValue.SnapshotEntityInheritBlackList` with battle-property entries including Defence, Attack, Shield/MaxShield, MaxStance, SPRatio and others;
- `TargetAliasConfig` aliases including `SnapshotEntityList`, `SnapshotEntityActualOwner`, and `SnapshotPropertyEntity`;
- `TargetOperationConfig.GetSnapshot -> RPG.GameCore.TargetMapSnapshotEntity`.

An independent pinned Luka DOT with `UseSnapshotEntity=true` reads Attack from `SnapshotPropertyEntity` in `OnCreate`, proving this is a real battle-state routing subsystem rather than presentation metadata.

Safe conclusion:

> `UseSnapshotEntity=true` participates in selective snapshot/source-entity routing.

Unsafe conclusions without GameCore implementation:

- exact capture moment;
- whether all properties are copied or selectively redirected;
- operational meaning of `SnapshotEntityInheritBlackList`;
- exact DEF source used by `ShieldByCasterDefence` for this modifier.

The nearby Skill02 Phase02 `SetDynamicValueByProperty(Caster.Defence -> CasterDefence)` is not explicitly passed into the ordinary main-shield `AddModifier.DynamicValues`, so it must not be promoted as a direct formula operand for the main shield without another edge.

## Shield depletion / shield-change negative evidence

Pinned generic/global data exposes shield events such as `OnListenInitShield` and `OnListenShieldChange`.

Independent Gepard shield implementations use the same formal pattern:

`Shield + OnStack -> InitShield + OnDestroy -> RemoveShield + Stacking="Replace"`.

Their `OnListenShieldChange` callbacks read current shield state for UI/resource behavior but do not remove the shield modifier there.

Therefore:

> `OnListenShieldChange` is not equivalent to a generic rule that zero shield immediately removes the modifier.

March's ordinary main shield has no local shield-change callback that closes depletion-to-destruction semantics. Generic depletion/expiry -> modifier destruction remains an engine/export boundary.

## Separate Rank02 shield: arithmetic corroboration only

`AvatarRankConfig[RankID=100102]` is March Rank 2, not ordinary SkillID 100102. It has:

`Param=[0.24,3,320]`

Its separate add-modifier expression resolves to:

`0.24 * CasterDefence + 320`

with lifetime `3`.

This independently corroborates the postfix multiplication/addition mapping but must never replace the ordinary Skill02 formula family.

## Rejected same-ID candidate

`ExcelOutput/ILBattleAvatarSkill.json` contains ID `100102` with unrelated RtBattle ownership, including a superficially plausible `ParamList=[6,0.3,6,1,6]`.

Numeric identity is insufficient; these values are explicitly rejected for ordinary March.

## Battle/presentation filtering

Retained battle evidence includes property reads, predicates, dispel, HP comparison, DynamicValue injection, modifier application, shield/heal/aggro consumers and modifier callbacks.

Camera, animation waits, VFX and choreography remain presentation unless an independent battle-state consumer proves otherwise. Animation time is not action/timeline authority.

## Negative knowledge / guardrails

- Large-file exact-search absence is not omission proof.
- Same numeric ID across source families is not entity identity proof.
- `SkillParam index=N` has no global semantic meaning across skills.
- `FormulaType="ShieldByCasterDefence"` identifies a formula family, not its hidden arithmetic body.
- `UseSnapshotEntity=true` does not mean “freeze the whole character at cast time”.
- `Stacking="Replace"` does not prove old `OnDestroy` vs new `OnStack` global dispatcher order.
- `OnListenShieldChange` does not prove zero-shield self-removal.
- raw `SP`-named fields must not be renamed to player Skill Points without consumer tracing.

## Remaining boundaries

March-local W02/W05 source work is largely closed. Remaining generic runtime/export questions are:

1. `ShieldByCasterDefence` exact arithmetic, DEF-source resolution, rounding/caps;
2. snapshot capture timing and inheritance semantics;
3. Replace callback ordering and old/new-state visibility;
4. lifetime decrement timing and shield-depletion/expiry -> modifier destruction;
5. phase-exact ordering among `OnStack`, `OnDestroy`, `OnPhase1`, shield-change and dispel callbacks where required.

These are `engine_consumer_unavailable` / `not_proven` unless a new authoritative engine source appears. They must not be filled from tooltips or community formulas.
