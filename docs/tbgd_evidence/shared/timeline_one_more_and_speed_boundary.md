# Ordinary timeline — OneMore, speed mutation, and scheduler boundary

## Record metadata

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed` for the source-facing paths below
- Scope: W07 ordinary action/timeline semantics and W13 coordinated servant-action ownership where it constrains timeline lowering
- Runtime production code changed: no

## Gameplay semantic model

Ordinary combat exposes several player-visible ways an entity can act sooner or more than once. The pinned data must distinguish at least:

- direct Speed-property mutation;
- normalized action advance/delay;
- absolute action-delay writes;
- inserted abilities/actions;
- `OneMore` extra-action entitlement;
- owner-coordinated sub-abilities such as Aglaea/servant joint execution.

These cannot be collapsed into a generic `AV=0` primitive unless a shared consumer proves equivalence.

## Shared `OneMore` protocol

Exact pinned `Config/ConfigGlobalModifier/GlobalModifier_Common_Specific.json` defines a formal shared modifier:

### `OneMore`

- `LifeTime=1`
- `LifeStepMoment=ActionPhaseEnd`
- `BehaviorFlagList=["OneMore","LifeStepImmediately"]`
- `Stacking=Merge`

This is a real data-facing extra-action marker/lifecycle surface.

### `OneMorePerTurn`

The same pinned file defines a distinct controller:

- `LifeStepMoment=ModifierPhase1End`
- `BehaviorFlagList=["OneMoreCount"]`
- `OnCreate` initializes/writes `OneMoreCount` state;
- `OnPhase1` adds `OneMore` to the owner;
- `OnActionEnd` updates the per-turn count;
- `OnListenTurnEnd` resets/updates per-turn state;
- `OnDestroy` clears the count.

`MoreOneMorePerTurn` and related variants further confirm that count-controller and OneMore marker are separate layers.

Opaque count arithmetic is not decoded here.

## Gepard: OneMore vs SetActionDelay(0) are alternative routes

Pinned `Avatar_Gepard_00_Ability.json` closes a turn-owner-dependent ordinary path.

The revive flow first schedules:

`TurnInsertAbility(Gepard_00_PassiveSkill_1_Insert, InsertAbilityPriority=AvatarReviveSelf)`.

After HP restoration the Rank06 branch checks:

`ByIsTurnOwnerEntity(Caster)`.

If Gepard is already the turn owner:

- add `MAvatar_Gepard_00_Rank06ActionDelay0`;
- the modifier has `BehaviorFlagList=["OneMore"]`;
- `LifeTime=1`, `LifeStepImmediately=true`;
- `OnBeforeSkillUse -> RemoveSelfModifier`.

If Gepard is not the turn owner:

- the branch does not arm OneMore;
- it executes `SetActionDelay(Caster,0)` instead.

Therefore:

```text
revive insert
-> HP restoration
-> turn-owner predicate
     true  -> OneMore marker
     false -> SetActionDelay(0)
```

This proves `OneMore`, inserted revive, and `SetActionDelay(0)` are semantically distinct source surfaces.

## Ordinary enemy cross-check: W4 Claymore

Pinned `Monster_W4_Claymore_00_Ability.json` can add `OneMorePerTurn` to the caster.

Pinned `Monster_W4_Claymore_00_AI.json` then branches action selection based on whether the caster contains `OneMore`; when the relevant condition fails it removes `OneMorePerTurn`/`OneMore` and routes to a different skill.

This establishes an ordinary enemy consumer and proves `OneMore` is not merely invisible scheduler metadata: its presence can also be read by battle AI decision logic.

## Negative cross-check: not every extra-action mechanic is OneMore

Pinned Seele execution does not expose a OneMore marker in the inspected path and instead uses turn-owner-sensitive `ModifyCurrentSkillDelayCost` / `ModifyActionDelay` and insertion semantics.

Therefore player-visible “extra action” behavior is not a single OneMore mechanism.

## Speed-property mutation and remaining-action-delay boundary

Two ordinary avatar samples provide a clean source boundary.

### Asta

Pinned `MAvatar_Asta_00_Ultra_SpeedUP`:

- `BehaviorFlagList=["STAT_SpeedUp"]`;
- `OnStack -> StackProperty(Property="SpeedDelta", ...)`;
- applied to team members with an explicit lifetime.

Manual search of the pinned Ability file finds no `SetActionDelay` or `ModifyActionDelay` in the speed-buff path. The only nearby action-delay references are preshow/prediction metadata and are not logical scheduler authority.

### Hanya

Pinned `WMAvatar_Hanya_Skill03Buff` writes a speed-family property (`SpeedConvert`) through `StackProperty` after reading current Speed-related values.

The same large Ability file contains real `ModifyActionDelay` elsewhere, but those operations belong to a separate Rank01 mechanic rather than the speed-buff path.

Cross-sample conclusion:

```text
speed buff
-> StackProperty(speed-family property)
-> no explicit character-content rewrite of remaining ActionDelay
```

Thus the pin supports a hard authority split:

- content authority: which Speed-family property changes, by how much, under what lifetime/condition;
- scheduler authority: how changed effective Speed rescales an already scheduled entity.

Do not derive `remainingAV_new = remainingAV_old * oldSPD/newSPD`, rounding, clamp or queue reinsertion from gameplay formulas as pinned TBGD authority.

## Action/timeline surface inventory confirmed by this record

At least these source surfaces are distinct:

1. Speed-family property mutation;
2. `ModifyActionDelay` normalized advance/delay;
3. `SetActionDelay` absolute delay write;
4. `ModifyCurrentSkillDelayCost` current-action delay-cost mutation;
5. `TurnInsertAbility` inserted action/ability;
6. `OneMore` marker;
7. `OneMorePerTurn` count/controller;
8. owner-coordinated `TriggerParallelAbility` contribution.

Later lowering must preserve these distinctions unless a generic engine contract proves equivalence.

## Aglaea coordinated action boundary

Pinned Aglaea/servant data distinguishes:

- servant independent selectable action:
  `ServantConfig.Skill01 -> Skill11_Phase01 -> Skill11_Phase02 -> SkillPerformFinish`;
- owner-coordinated servant contribution:
  `Aglaea Skill11 -> TriggerParallelAbility(CasterServant) -> SkillP01-owned Skill11_Together_Phase01`.

Neither the owner Skill11 region nor the servant Together region exposes an explicit action-delay mutation.

Safe conclusion: the coordinated contribution is not entered through the servant's selectable normal-skill path.

Unresolved: whether hidden scheduler accounting preserves/consumes/resets the servant's pre-existing normal action slot.

## Engine/export boundaries

The current pin does not export the generic scheduler implementation needed to close:

- SPD -> base action delay / displayed Action Value;
- initial queue construction;
- exact rescale after Speed changes;
- queue/requeue/clamp/rounding;
- equal-delay tie-break;
- exact runnable ordering of OneMore versus other ready/inserted actions;
- coordinated-subability effect on an entity's normal action slot.

These are named `engine_consumer_unavailable` boundaries, not invitations to substitute public gameplay formulas.

## Durable guardrails

- `OneMore` != `SetActionDelay(0)`.
- `OneMore` != `TurnInsertAbility`.
- not every player-facing extra action uses OneMore.
- Speed mutation != explicit action-delay mutation.
- `ActionDelayPreshowConfig` is not logical scheduler authority without an independent state consumer.
- absence of a data-facing delay write does not prove hidden scheduler non-consumption.
