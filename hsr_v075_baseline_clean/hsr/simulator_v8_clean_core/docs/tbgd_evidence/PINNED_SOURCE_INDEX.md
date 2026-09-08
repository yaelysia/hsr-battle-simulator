# Pinned TBGD source index

Status: **living navigation index; not semantic authority by itself**

Pinned upstream repository: `DimbreathBot/TurnBasedGameData`
Pinned commit: `14c1d18f91a8101d610e6c523447a7517de3fae1`
Pinned `ExcelOutput` tree SHA: `b1681c407643b4e1c1f3b3e940bb6b507dd79d41`

This file exists to make archaeology reusable across sessions. It records expensive navigation work once, so later research can jump directly to exact pinned sources instead of repeatedly rescanning large trees or JSON exports.

## Authority boundary

- This index answers **where to look**, not **what a record means**.
- Default-branch GitHub search may be used only as navigation bait. Every promoted claim must be re-read at the pinned commit above.
- Filename, directory, prefix, numeric-ID equality, or search co-occurrence has no automatic inclusion/exclusion authority.
- Automation must not silently discard candidates. Ambiguous hits remain indexed until manual semantic review classifies them.
- Important negative searches are retained; they prevent later sessions from paying the same search cost again.
- If the upstream pin changes, all exact-pin entries require revalidation. Until then, reuse this index rather than rebuilding it from scratch.

## Classification vocabulary

- `unreviewed` — navigation hit only.
- `ordinary_candidate` — plausible ordinary-combat source, semantic closure pending.
- `ordinary_confirmed` — manually tied to an ordinary-combat producer/consumer chain.
- `mixed` — family contains multiple semantic domains; inspect individual records/consumers.
- `special_mode` — manually confirmed special-mode ownership for this record/path.
- `false_positive` — superficially matching hit manually disproven for the investigated identity/claim.
- `deferred` — valid source family outside the current ordinary-combat closure target.

## Reusable file-family index

| Family / path | Exact-pin blob SHA | Classification | Indexed facts / negative evidence | Next semantic action |
|---|---|---|---|---|
| `ExcelOutput/AvatarSkillConfig.json` | `7b041fca79d43ce6f5372080e06bb51a6b6daae8` | `mixed` / unresolved for W02 | Exact pinned file exists. Exact searches for `"SkillID": 100102`, `140204`, and `140201` returned no match. Therefore this family is **not** the missing numeric ordinary-skill row for those IDs at this pin. | Inspect schema/consumer role only if another chain points back here; do not rescan these IDs. |
| `ExcelOutput/AvatarSkillConfigLD.json` | `00591c03da335fb1732e047a728be0a6ce3f55da` | `mixed` / unresolved for W02 | Exact pinned file exists. Exact searches for `"SkillID": 100102` and `140204` returned no match. | Preserve as a candidate family, but do not repeat those exact-ID searches. |
| `ExcelOutput/ILBattleAvatarSkill.json` | pending backfill | `false_positive` for March ordinary Skill02 | Record ID `100102` exists with `ParamList=[6,0.3,6,1,6]`, but manual parent/config tracing ties the record to `Config/Activity/RtBattle/**`; it is not March ordinary-combat Skill02 authority. | Retain as numeric-collision counterexample; never promote by ID equality. |
| `ExcelOutput/MonsterConfig.json` | `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` | `ordinary_confirmed` for Monster `1002011` | Exact pinned family identity recorded. Prior manual row audit establishes `MonsterID=1002011 -> MonsterTemplateID=1002011` plus instance-level battle facts. File is large enough that later navigation should reuse the existing evidence record rather than repeatedly loading the table. | Trace any instance override that participates in final-stat precedence; do not rebuild the already-closed identity chain. |
| `ExcelOutput/MonsterTemplateConfig.json` | `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` | `ordinary_confirmed` for Monster `1002011` | Exact pinned row `MonsterTemplateID=1002011`: `AttackBase=18`, `DefenceBase=210`, `HPBase=69.75`, `SpeedBase=100`, `StanceBase=60`; config/AI paths also match the existing monster evidence chain. This resolves the historical `1002010`/`1002011` template-ID ambiguity. | Reuse these base inputs in W14; do not treat them as final encounter stats. |
| `ExcelOutput/ILHardLevelGroup.json` | `0440228b44d6fd1cfbc1ac823f9148b48e02b595` | `ordinary_confirmed` for the already traced `(HardLevelGroup=1, Level=29)` lookup | Exact pinned row: `AttackRatio=700.23926`, `DefenceRatio=69.67834`, `HPRatio=619.263`. Despite the `IL` prefix, prior manual producer/consumer tracing established this lookup as part of the investigated ordinary monster/stage scaling chain. These are raw inputs, not a proven equation. | Find the real consumer/operator and precedence with template/unique/stage/instance inputs; do not infer arithmetic from `*Ratio` names. |
| `ExcelOutput/MonsterUniqueConfig.json` | `a0fde2b2bbd00b82eaa48d2f2c1e253571bdec4b` | `ordinary_candidate` for W14 | Exact pinned family exists. This checkpoint does **not** promote a `1002011` row or any unique-scaling operator. | Determine whether this family contributes to Monster `1002011` or only other monster families, then trace its consumer if applicable. |

## Reverse-ID registry

### Avatar / servant skill IDs

| ID | Investigation | Exact-pin known locations / results | State |
|---|---|---|---|
| `100102` | March 7th Preservation Skill02 | Ordinary `ConfigCharacter` chain uses Skill02 semantics; `AvatarSkillConfig.json` no exact `SkillID` row; `AvatarSkillConfigLD.json` no exact `SkillID` row; `ILBattleAvatarSkill[100102]` is a manually rejected RtBattle collision. | numeric producer unresolved |
| `140204` | Aglaea servant HP/Speed parameter source | `AvatarServantConfig[11402]` references `HPSkill=140204` and `SpeedSkill=140204`; exact `AvatarSkillConfig*` searches above are negative. Pinned `Avatar_Aglaea_00_Config.json` has ordinary trigger keys `Skill01/Skill02/Skill11/Skill03/Skill21/P01/Maze`, **not `Skill04`**; therefore the previous `140204 -> Skill04` hypothesis is rejected. | binding layer unresolved |
| `131508` | servant `#N` cross-case | `AvatarServantConfig[8002]` uses it for HP/Speed indirection. | producer/decoder unresolved |
| `141201` | servant `#N` cross-case | `AvatarServantConfig[11412]` uses it for HP/Speed indirection. | producer/decoder unresolved |
| `140704` | servant `#N` cross-case | `AvatarServantConfig[11407]` uses it for HP/Speed indirection. | producer/decoder unresolved |
| `140906` | servant `#N` cross-case | `AvatarServantConfig[11409]` uses it for HP/Speed indirection. | producer/decoder unresolved |
| `141304` | servant `#N` cross-case | `AvatarServantConfig[11413]` uses it for HP/Speed indirection. | producer/decoder unresolved |

## Known semantic hazard registry

1. **Numeric collision:** `100102` is both an ordinary March skill identifier in one chain and an unrelated RtBattle record ID in another. Numeric equality is not identity proof.
2. **Prefix hazard:** `ILHardLevelGroup.json` demonstrates that an `IL` prefix is not an automatic special-mode exclusion rule.
3. **Trigger-key hazard:** Aglaea's pinned ordinary ConfigCharacter does not contain a `Skill04` trigger key, so decimal suffix intuition (`140204 -> Skill04`) is not a valid mapping rule.
4. **Search-index hazard:** GitHub code search covers the repository default branch, not the pinned commit. Search hits from it are navigation candidates only.
5. **Arithmetic-name hazard:** fields named `AttackRatio`, `DefenceRatio`, or `HPRatio` identify candidate numeric inputs but do not prove addition/multiplication/normalization/replacement semantics or precedence.

## High-value unresolved reverse lookups

### W02 — ordinary avatar SkillParam numeric source

- Locate the exact pinned producer/binding that maps numeric skill IDs such as `100102` and `140204` to ordinary ConfigCharacter trigger keys / SkillParam arrays.
- Search all plausible pinned families without assuming that the word `AvatarSkill` must appear in the filename.
- Preserve negative family checks in this index.
- For March Skill02, close indices `0..4` only when their pinned numeric source and the already-confirmed ConfigCharacter consumer meet.

### W13 — servant `#N` decoder

- Locate a parser/consumer for strings such as `"#4"`, `"#5"`, `"#6"`.
- Compare the six known AvatarServantConfig cross-cases, but treat pattern correlation as cross-validation rather than decoder proof.
- Do not infer `#N == SkillParam index N` until producer/consumer semantics establish it.

### W14 — monster final stat composition

Closed at this checkpoint:

- exact pinned `MonsterConfig` family identity for the previously audited `MonsterID=1002011` row;
- exact `MonsterTemplateConfig[1002011]` identity and base ATK/DEF/HP/SPD/Stance values;
- exact `(HardLevelGroup=1, Level=29)` `ILHardLevelGroup` HP/ATK/DEF scaling inputs;
- exact pinned `MonsterUniqueConfig` family identity without assuming that it applies to this instance.

Still unresolved:

- actual arithmetic joining template base, hard-level values, any applicable unique values and instance overrides;
- precedence among those layers;
- final SPD/Stance construction, because the inspected hard-level row itself exposes HP/ATK/DEF fields rather than a complete property set;
- whether `MonsterUniqueConfig` participates in this exact instance.

The next W14 search should therefore target the **consumer/operator**, not re-extract the already-pinned numeric inputs.

## Navigation-only candidates from default-branch search

These entries deliberately remain non-authoritative until exact-pin verification:

- `ExcelOutput/MazeSkill.json` contains a default-branch `MazeSkillId=100102` hit; likely maze/technique-related and must not be conflated with March battle Skill02 without producer/consumer proof.
- `ExcelOutput/ILBattleAvatarPromotion.json` and `ExcelOutput/ILBattleAvatarSkill.json` surfaced for the `100102 + ParamList` search; individual semantic ownership must be verified at the pin before any reuse.
- `ExcelOutput/BattleEventSkillConfig.json` and GridFight families surface substring/numeric collisions and are retained as reverse-search candidates rather than filtered out automatically.

## Maintenance log

- 2026-09-08: Created reusable pinned-source index. Seeded W02/W13/W14 findings, exact pinned negative searches for `AvatarSkillConfig*`, and known semantic hazards. The index is intentionally incomplete and must grow incrementally rather than be regenerated wholesale.
- 2026-09-08: Backfilled exact pinned W14 source identities and values for `MonsterConfig`, `MonsterTemplateConfig`, `ILHardLevelGroup`, and `MonsterUniqueConfig`; resolved the template-ID ambiguity while explicitly leaving the final-stat arithmetic/precedence unresolved.