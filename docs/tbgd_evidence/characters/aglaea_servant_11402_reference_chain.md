# Aglaea — Servant 11402 battle reference chain

## Record metadata

- Concept: normal-combat servant / memosprite creation, identity, skill wiring, property relationship and death-path evidence
- Owner character context: Aglaea (`AvatarID = 1402` is established by the ordinary avatar chain, not by the `AvatarServantConfig[11402]` row)
- Servant: Garmentmaker (`ServantID = 11402`)
- TBGD revision: `14c1d18f91a8101d610e6c523447a7517de3fae1`
- Evidence maturity: `manually_confirmed`
- Battle-scope verdict: `include`
- Confidence: high for the structural edges and exact raw fields listed below; inheritance arithmetic, synchronization timing, lifecycle ordering and turn ownership remain unresolved
- Tracking issue: #7

## Why this chain matters

A battle servant is not safely recoverable from names such as `SummonUnit`. The pinned corpus contains an Aglaea `ConfigSummonUnit` file that is scene/maze-side, while the actual battle entity is created through the `Servant` data family. This record therefore captures both the positive battle chain and a concrete false friend.

This record also preserves a correction made during manual re-audit: an earlier draft accidentally attributed an `AvatarID` field, the wrong AI path and the wrong four-skill list to `AvatarServantConfig[11402]`. The exact pinned row does not contain `AvatarID`; its AI and skill IDs are listed below.

## Confirmed battle chain

```text
Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json
  CreateServant
    ServantID = 11402
    ActivityOnCreate = false
        |
        v
ExcelOutput/AvatarServantConfig.json
  ServantID = 11402
  Config -> Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
  AIPath -> Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json
  SkillIDList -> [1140201, 1140203, 1140205, 1140206]
        |
        v
Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json
  ServantConfig / Memosprite
  skill, target, AI and property-inherit wiring
        |
        v
Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json
  distinct servant/summoner property reads and death-event graph
```

These edges were manually inspected in the pinned raw files. They are not inferred from current-game descriptions or from filename matching.

## 1. Creation edge

Path:

`Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json`

A manually inspected operation uses:

- `$type = CreateServant`
- `ServantID = 11402`
- `ActivityOnCreate = false`

This establishes a battle-side creation edge from Aglaea's avatar ability graph to the servant identity in `AvatarServantConfig.json`.

The same large ability file contains `ForceKill` operations elsewhere. Their presence is **not** sufficient to claim the servant's exact replacement, cleanup or despawn rule. The owning ability context and event ordering still need to be traced before a lifecycle statement is promoted.

Classification: `mixed_requires_filter`.

## 2. Servant identity and combat metadata

Path:

`ExcelOutput/AvatarServantConfig.json`

The exact inspected row with `ServantID = 11402` contains:

- `ServantID = 11402`
- `Config = "Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json"`
- `AIPath = "Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json"`
- `SkillIDList = [1140201, 1140203, 1140205, 1140206]`
- `HPBase = "#6"`
- `HPInherit = "#5"`
- `HPSkill = 140204`
- `SpeedBase = "0"`
- `SpeedInherit = "#4"`
- `SpeedSkill = 140204`
- `Aggro.Value = 125`

The row also contains presentation-facing fields such as icon paths, so the table remains `mixed` rather than safe for wholesale lowering.

### Negative knowledge about owner identity

The inspected `ServantID=11402` row does **not** contain an `AvatarID=1402` field. Owner identity must therefore not be asserted from this row. The Aglaea-to-servant relationship is instead proven here by the normal Aglaea ability graph's `CreateServant(11402)` edge together with the servant row/config identity.

The strings `#4`, `#5` and `#6` are preserved exactly as raw evidence. This record does **not** assign formulas, units or inheritance percentages to those tokens until their source is located and manually read.

Classification: `mixed_requires_filter`.

## 3. Servant character definition

Path:

`Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json`

Confirmed structure includes:

- `$type = "ServantConfig"`
- `AvatarServantType = "Memosprite"`
- `DamageType = "Thunder"`
- `ControlImmunity = true`
- `DefaultAIPath = "Config/ConfigAI/Avatar_ComplexSkilll_AutoFight_AI.json"`
- combat skill definitions and target configuration
- passive/special ability references
- property inheritance configuration

For the inspected Skill01 definition:

- `SkillType = Servant`
- `UseType = SelectEntity`
- `SPBase = 10`
- target configuration selects an enemy and includes adjacent-target behavior
- `EntryAbility = Servant_AglaeaServant_00_Skill01_Part01`
- AI type is `ComplexSkillAI`
- `SkillFirstPriority = true`

The config also contains:

- a `ServantPassiveSkillConfig` with `Key = DeathRattle` and `SkillType = DeathRattle`;
- special-AI ability references including `Servant_AglaeaServant_00_Ability_BPSkill01`, `...BPSkill02` and `...PassiveSkill01`;
- `JoinSkillList`, including `Servant_AglaeaServant_00_Ability_BPSkill01`;
- a buff-resistance blacklist.

Their exact runtime semantics remain operation-level work rather than conclusions inferred from field names.

### Speed is explicitly outside generic property sync

`PropertyInheritConfig.SyncPropertyExceptList` includes the speed-family properties:

- `SpeedPercent`
- `SpeedAddedRatio`
- `Speed`
- `SpeedDelta`
- `SpeedBase`
- `SpeedConvertedRatio`

Therefore the pinned config proves a narrow but important fact: these speed-family properties are explicitly excluded from whatever generic property synchronization path this configuration supplies. It does **not** by itself prove whether other properties are snapshotted, continuously synchronized, or refreshed on particular events.

Classification: `mixed_requires_filter`.

## 4. Servant ability graph and summoner relationship

Path:

`Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json`

Manual inspection confirms the ability graph reads `Speed` from two distinct entity selectors:

- `CasterSummoner`
- `Caster`

This is enough to establish that the raw battle graph distinguishes summoner and servant entities and applies special speed handling somewhere outside the generic synchronized-property path. It is **not** enough to assign an inheritance percentage, to prove snapshot versus continuous synchronization, or to prove independent timeline ownership.

An earlier draft also listed several exact speed working/modifier names. Those names have been removed from the confirmed set here because they were not re-verified in the latest pinned-file audit. They may be promoted again only if their exact occurrences and consumers are manually re-established.

The same ability file contains the formal modifier:

`MAvatar_AglaeaServant_00_PassiveSkill01_DeathRattle`

The inspected modifier has:

- `LifeTime = -1`
- `UseSnapshotEntity = false`
- callback-registration/configuration structure

Death-related ability identities are also present, including `Servant_AglaeaServant_00_Ability_OnDeath_RestoreEnergy`. This establishes a real death/death-rattle subgraph. It does not yet establish exact callback ordering, cleanup point, energy recipient/value or equivalence across forced-kill and ordinary-death paths.

Classification: `mixed_requires_filter`.

## 5. Negative knowledge — `ConfigSummonUnit` is a false friend here

Path:

`Config/ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json`

Despite the directory and filename, the manually inspected file is not the Garmentmaker battle-servant definition. Its observed structure is scene/maze/Technique-side and includes:

- `$type = ConfigSummonUnit`
- `GroupConfig = "FollowField"`
- collision / near-target triggers
- prop/NPC hit handling
- VFX and scene callbacks
- `AddMazeBuff`
- `AddAdventureModifier`
- scene-side summon removal behavior

For normal-combat archaeology this Aglaea file is therefore **not** the battle servant authority. It is retained as negative knowledge because a filename-driven crawler would otherwise be likely to classify it incorrectly.

This does not justify blanket-excluding `ConfigSummonUnit/**`. Other records remain `unresolved` until manually inspected or made reachable from an ordinary-combat chain.

## Battle semantics established by this record

The pinned raw corpus currently supports these structural claims:

1. Aglaea's ordinary battle ability graph can execute `CreateServant` for `ServantID 11402`.
2. `AvatarServantConfig[11402]` provides the servant config path, complex-skill auto-fight AI path, four exact skill IDs, HP/speed construction tokens and aggro value.
3. The servant character config explicitly types the entity as a `Memosprite` and gives it battle skill/target/AI/property-inherit wiring.
4. Generic property synchronization explicitly excludes speed-family properties.
5. The servant ability graph separately reads `CasterSummoner.Speed` and `Caster.Speed`.
6. A formal DeathRattle modifier/death-event subgraph exists.
7. `ConfigSummonUnit/SummonUnit_Aglaea_00_Config.json` is not a substitute for the battle servant chain.

These facts justify representing the servant/memosprite as a distinct battle entity relationship. They are **not** enough to reproduce all numeric or temporal servant semantics.

## Unresolved before stronger promotion

- Locate and decode the pinned source behind `HPBase = #6`, `HPInherit = #5` and `SpeedInherit = #4`.
- Determine exact owner/servant property synchronization timing: creation snapshot, continuous sync, event refresh, or another mechanism.
- Trace the exact owning ability/event around every ordinary `CreateServant` path.
- Trace lifetime, countdown, replacement, `ForceKill`, death and final cleanup/despawn ordering.
- Prove action-value / turn-queue ownership from raw scheduling operations rather than inferring it from separate speed state or live behavior.
- Determine servant resource ownership and the semantic meaning of `SPBase = 10` in the servant skill context.
- Resolve DeathRattle callback order, energy restoration destination/value and interaction with forced death/removal.
- Trace `JoinSkillList` semantics and any owner-servant joint-action path.
- Manually audit the referenced `Avatar_ComplexSkilll_AutoFight_AI.json` consumer path before promoting AI decision semantics.

## External corroboration

Current live-game descriptions and independent mechanics references can corroborate that Garmentmaker is a memosprite with owner-linked stats and dedicated action/death behavior. Those sources are secondary only: they must not fill the unresolved `#4/#5/#6`, synchronization, cleanup, ordering or scheduling gaps at the pinned TBGD revision.
