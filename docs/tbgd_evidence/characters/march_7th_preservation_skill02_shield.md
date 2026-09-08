# March 7th (Preservation) Skill02 shield/control-flow evidence

## Evidence status

- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Maturity: `manually_confirmed` with unrelated ordinary-character cross-check for the `SkillParam` producer/binding model
- Scope: ordinary-combat Skill02 numeric producer, typed parameter bindings, target/control flow, lifetime expression, trace/eidolon branches, formal shield modifier lifecycle hooks, and explicit engine-export boundaries
- Battle-scope verdict: `mixed` at Ability-file operation level; battle execution retained, presentation operations excluded; same-ID RtBattle records are deferred/false friends for this ordinary chain
- Runtime production code changed: no

## Correction history

This record supersedes two older claims from the archaeology:

1. **The exact pinned `ExcelOutput/AvatarSkillConfig.json` does contain ordinary March `SkillID=100102` rows.** Earlier “no exact row” statements were false negatives caused by large-file/search/read behavior, not by the pinned corpus.
2. The main shield modifier initializes the shield on **`OnStack`**, not `OnCreate`. It also explicitly declares `Stacking="Replace"` and `OnDestroy -> RemoveShield`.

`ILBattleAvatarSkill[100102]` remains a real numeric-ID collision from the deferred RtBattle family and is still rejected as ordinary March authority.

## Gameplay semantic model

The ordinary Skill02 is a selected-ally support action. The pinned graph must account for:

- selected ally targeting;
- DEF-based shield operands;
- base lifetime and trace lifetime extension;
- an HP-ratio branch that conditionally injects aggro increase;
- trace-gated dispel;
- rank/eidolon healing behavior;
- replacement/removal lifecycle of the formal Shield modifier.

Public/live mechanics are used only as semantic corroboration. The pinned producer/consumer chain remains the authority for this revision.

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
  -> shield modifier callbacks / property consumers
```

Exact pinned `AvatarSkillConfig.json` blob:

`a5416ced941c247d475b2aaa83277b9cdf474dd9`

Manually rechecked ordinary rows include:

- Level 11: `ParamList = [0.589, 3, 0.3, 802.75, 5]`
- Level 12: `ParamList = [0.608, 3, 0.3, 845.5, 5]`

These are raw parameter-array values. Their meanings come from the downstream consumers below, not from their positions alone.

## Typed bindings and consumer mapping

The ordinary ConfigCharacter binds Skill02 parameters as:

| Index | Dynamic hash | Confirmed consumer role |
|---:|---:|---|
| 0 | `-1091495116` | `MDF_ShieldPercentage` -> `InitShield.ShieldPercentage` |
| 1 | `-1016136907` | base shield lifetime operand |
| 2 | `398047946` | target HP-ratio threshold |
| 3 | `1935511666` | `MDF_ShieldValue` -> `InitShield.ShieldValue` |
| 4 | `-1672381420` | HP-gated `MDF_AggroUp` -> `AggroAddedRatio` |

The selected target contract is `FriendSelect`, and the Ability applies the modifier to `AbilityTargetEntity`.

The HP comparison is `GreaterEqual`: when target HP ratio is `>= SkillParam[2]`, `SkillParam[4]` is injected as the aggro operand; otherwise the same shield is applied with aggro input forced to `0`.

## Parameter-family authority

The first parallel audit closes the following producer/index distinction for the inspected ordinary samples:

- `SkillParam` -> `AvatarSkillConfig[SkillID, Level].ParamList[index]`
- `SkillTreeParam` -> `AvatarSkillTreeConfig[PointID / PointTriggerKey].ParamList[index]`
- `SkillRank` -> `AvatarRankConfig[RankID / rank trigger].Param[index]`
- `SkillAddLevelList` is a separate skill-level increment mechanism, not another anonymous ParamList.

Dan Heng provides an unrelated ordinary-character cross-check: ordinary `SkillID=100202` has per-level `AvatarSkillConfig.ParamList`, its ConfigCharacter maps `SkillParam(Skill02,index=0)` to a dynamic hash, and the pinned Ability consumes that hash as a Skill02 damage-percentage input.

This is sufficient to close March's W02 producer gap and to establish a reusable ordinary producer/binding pattern. It is not a claim that every character/source family has already been exhaustively enumerated.

## Trace and rank branches

Pinned ordinary data confirms:

- **PointB1:** `DispelStatus` on `AbilityTargetEntity`, `Numbers=1`, `Order="LastAdded"`.
- **PointB2:** `AvatarSkillTreeConfig` point `1001102` supplies `ParamList=[1]`; Skill02 writes this to `_Tree02_LifeTimeAdd`, otherwise it writes `0`.
- **Rank06:** `AvatarRankConfig[100106]` has `Param=[0.04,106]`; the Skill02 path injects Rank06 heal operands when the rank is active and zeros otherwise.

Trace/rank parameters are therefore separate producer spaces from the five ordinary Skill02 parameters.

## Lifetime expression

The Skill02 lifetime expression is source-backed as:

`base SkillParam[1] + _Tree02_LifeTimeAdd`

The encoded postfix operator family was cross-validated on independent pinned behavior samples rather than decoded from naming intuition:

- operator byte `0x02` behaves as addition in counter-increment samples;
- `0x03` behaves as subtraction in decrement/removal samples;
- `0x04` behaves as multiplication in Gepard split-hit arithmetic.

For March Skill02 the relevant expression combines `SkillParam[1]` and `_Tree02_LifeTimeAdd` with the confirmed addition operator. With ordinary rows whose index 1 is `3`, the lifetime input is `3` without PointB2 and `4` with PointB2.

## Formal shield modifier lifecycle

`MAvatar_March7th_00_BPSkill_Shield` in the exact pinned ordinary Ability file confirms:

- `BehaviorFlagList` contains `Shield`;
- `UseSnapshotEntity=true`;
- `Stacking="Replace"`;
- `OnCreate` performs resilience/effect setup, **not** shield initialization;
- `OnStack` performs `InitShield` on `ModifierOwnerEntity` with:
  - `FormulaType="ShieldByCasterDefence"`
  - injected `ShieldPercentage`
  - injected `ShieldValue`
  - and stacks the injected `AggroAddedRatio`;
- `OnDestroy` performs explicit `RemoveShield` and resilience cleanup;
- `OnPhase1` contains the Rank06 heal branch when the injected heal percentage is positive.

This closes the character-local application/reapplication/removal hooks. It does **not** expose the generic GameCore implementation body of `ShieldByCasterDefence`, `UseSnapshotEntity`, or `Stacking="Replace"`.

## Separate Rank02 shield: useful arithmetic corroboration, not ordinary Skill02 authority

`AvatarRankConfig[RankID=100102]` is March's Rank 2 producer, not ordinary SkillID 100102. It has:

`Param=[0.24,3,320]`

and a separate Rank02 shield expression whose pinned postfix operations resolve to:

`0.24 * CasterDefence + 320`

with lifetime `3`.

This is useful arithmetic-language corroboration and a strong numeric-collision example. It must not be substituted for the ordinary Skill02 parameter rows above.

## Rejected same-ID candidate: RtBattle `100102`

`ExcelOutput/ILBattleAvatarSkill.json` also contains ID `100102`, including a `ParamList=[6,0.3,6,1,6]` row. Manual parent-family tracing ties it to `Config/Activity/RtBattle/**`, not the ordinary Preservation March chain.

Therefore those values remain explicitly rejected for ordinary Skill02.

## Battle/presentation filtering

The same Ability file mixes battle and presentation operations. Retained battle evidence includes DEF/property reads, predicates, dispel, HP comparison, DynamicValue injection, modifier application, shield/heal/aggro consumers and modifier callbacks. Camera operations, animation waits, VFX and choreography are presentation unless an independent battle-state consumer proves otherwise.

Animation time is not action/timeline authority.

## Negative knowledge / false friends

- Exact-ID search absence in a very large pinned blob is not omission proof. The earlier `100102` false negative is now a durable tool/search hazard.
- `ILBattleAvatarSkill[100102]` is an unrelated RtBattle collision.
- `AvatarSkillConfigLD.json` is not needed to close ordinary March Skill02 just because its name resembles the ordinary producer family.
- `SkillParam index=N` has no globally reusable semantic meaning across different skills; consumer tracing is required.
- `FormulaType="ShieldByCasterDefence"` identifies a generic formula family but does not by itself reveal the unexported engine arithmetic.
- `UseSnapshotEntity=true` proves snapshot behavior is requested, not the exact capture object/time/field set.
- `Stacking="Replace"` proves replacement mode, not the precise old-instance `OnDestroy` versus new-instance `OnStack` dispatcher order.
- raw fields containing `SP` must not be renamed to user-facing Skill Points without consumer/context tracing.

## Remaining engine/export boundaries

The character-local W02/W05 chain is no longer blocked on numeric discovery. Remaining open questions are generic runtime semantics:

1. implementation arithmetic for `InitShield.FormulaType="ShieldByCasterDefence"`;
2. exact `UseSnapshotEntity` capture scope and timing;
3. exact callback ordering during `Stacking="Replace"`;
4. generic lifetime decrement and shield-depletion -> modifier-destroy behavior;
5. shield dispellability;
6. phase-exact ordering of `OnStack`, `OnDestroy` and `OnPhase1` where it matters.

These should remain `not_proven` / engine-authority gaps if the pinned release-data corpus does not export the relevant GameCore consumer. They must not be filled from tooltip formulas.
