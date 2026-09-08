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
- Important negative searches are retained only when the search method itself has been validated for that blob. Large-file/search-tool false negatives must be corrected, not preserved as evidence.
- If the upstream pin changes, all exact-pin entries require revalidation. Until then, reuse this index rather than rebuilding it from scratch.

## Classification vocabulary

- `unreviewed` — navigation hit only.
- `ordinary_candidate` — plausible ordinary-combat source, semantic closure pending.
- `ordinary_confirmed` — manually tied to an ordinary-combat producer/consumer chain.
- `mixed` — family contains multiple semantic domains; inspect individual records/consumers.
- `special_mode` — manually confirmed special-mode ownership for this record/path.
- `false_positive` — superficially matching hit manually disproven for the investigated identity/claim.
- `deferred` — valid source family outside the current ordinary-combat closure target.
- `export_gap` — a pinned consumer/identity proves the mechanism/family exists, but the executable definition/engine consumer needed for deeper semantics is absent from the exported corpus.
- `engine_consumer_unavailable` — raw data-facing values/opcodes are present, but their generic GameCore implementation is outside the pinned release-data dump.

## Reusable file-family index

| Family / path | Exact-pin blob SHA | Classification | Indexed facts / negative evidence | Next semantic action |
|---|---|---|---|---|
| `ExcelOutput/AvatarSkillConfig.json` | `a5416ced941c247d475b2aaa83277b9cdf474dd9` | `ordinary_confirmed` / mixed | Exact pinned blob contains ordinary per-level skill rows including March `SkillID=100102` / `SkillTriggerKey=Skill02` and Aglaea-construction `SkillID=140204`. The earlier exact-ID negative was a search/read false negative and is superseded. March examples include Lv11 `[0.589,3,0.3,802.75,5]` and Lv12 `[0.608,3,0.3,845.5,5]`; `140204` supplies the ParamList selected by servant `SpeedSkill/HPSkill`. | Reuse as the ordinary `SkillParam`/servant-construction producer; do not reopen the disproven omission hypothesis. |
| `ExcelOutput/AvatarSkillConfigLD.json` | `003abcf5527856f46e7598b99ea01cebf451af26` | `mixed` | Earlier fixed-pin negative searches are no longer needed to explain March/Aglaea producer gaps because `AvatarSkillConfig.json` itself supplies those rows. | Inspect only when a separate chain points here. |
| `ExcelOutput/AvatarServantSkillConfig.json` | exact-pin file confirmed; blob SHA pending durable backfill | `ordinary_confirmed` for Servant 11402 passives | Exact pin contains `SkillID=1140205 / SkillTriggerKey=SkillP03` with `ParamList[0]=1` and `SkillID=1140206 / SkillTriggerKey=SkillP04` with `ParamList[0]=20` across inspected exported levels. | Reuse for servant passive numerics; keep generic passive-entry activation timing separate. |
| `ExcelOutput/ILBattleAvatarSkill.json` | pending backfill | `false_positive` for March ordinary Skill02 | Record ID `100102` exists with unrelated RtBattle ownership; it is not March ordinary-combat Skill02 authority. | Retain as numeric-collision counterexample; never promote by ID equality. |
| `ExcelOutput/MonsterConfig.json` | `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` | `ordinary_confirmed` for representative monster chains | Exact pinned family identity recorded. Prior manual row audit establishes `MonsterID=1002011 -> MonsterTemplateID=1002011`; later W14 work also found concrete flat modification samples. | Reuse concrete instance inputs; final configured-stat operator remains unresolved. |
| `ExcelOutput/MonsterTemplateConfig.json` | `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` | `ordinary_confirmed` for Monster `1002011` | Exact pinned row `MonsterTemplateID=1002011`: `AttackBase=18`, `DefenceBase=210`, `HPBase=69.75`, `SpeedBase=100`, `StanceBase=60`. | Reuse as base/template inputs, never as final encounter stats. |
| `ExcelOutput/HardLevelGroup.json` | `9ee36b767b010d2c85aa7169e86e9f0a4220a935` | `ordinary_confirmed` for W14 | Exact pinned rows are keyed by `(HardLevelGroup, Level)` and expose ATK/DEF/HP/SPD/Stance ratios. Example group 1 / level 29: ATK `5.19238`, DEF `2.333333`, HP `5.020885`, SPD `1`, Stance `1`; multiple levels/groups were cross-checked and SPD ratio changes at higher levels. | Recover the real final-stat getter/operator, flat-value placement and Stage/Monster/Elite precedence. |
| `ExcelOutput/ILHardLevelGroup.json` | `0440228b44d6fd1cfbc1ac823f9148b48e02b595` | `false_positive` for ordinary W14 / special-mode family | The previously indexed `700.23926/69.67834/619.263` row is real raw data, but the first parallel W14 pass showed it belongs to the `IL*`/RtBattle family and is not ordinary-monster scaling authority. The old ordinary classification is superseded. | Keep only as a high-value ID/prefix collision example unless a special-mode investigation needs it. |
| `ExcelOutput/MonsterUniqueConfig.json` | `a0fde2b2bbd00b82eaa48d2f2c1e253571bdec4b` | `ordinary_candidate` / conditional | No representative ordinary row was found for several audited IDs; existence of the family does not make it a universal override layer. | Include only when an explicit ordinary producer/consumer chain references it. |
| `Config/GlobalConfig/GameCoreConstValue.json` | exact-pin identity to backfill | `engine_consumer_unavailable` | Contains raw battle-facing constants such as `SpeedToDelayDistance=1000`, BP/SP-related constants, resistance bounds and `DamageRandomMin=DamageRandomMax=1`. Repeated reverse scans did not expose the generic engine consumers that turn these fields into formulas. | Preserve raw values as candidate inputs; do not infer SPD→AV, defence/resistance, BP initialization or RNG formulas from names. |
| `Config/GlobalConfig/PriorityConfig.json` | exact-pin identity indexed in W10 evidence | `ordinary_confirmed` shared ordering input | Separate modifier-event and insert priority domains are exported. Inspected symbolic/numeric mappings establish lower numbers as earlier/higher priority within each domain; same-priority and cross-domain arbitration remain unresolved. | Reuse as ordering input; seek dispatcher/tie-break consumer rather than comparing numbers across domains. |
| `Config/ConfigCommonSkillPool/**` | pinned tree contains only empty Painter layout executable-definition gap | `export_gap` | Pinned Painter ordinary battle ability carries exact CommonSkillPool consumer key `CommomSkill_W5_Painter_00`, while the pinned directory lacks the corresponding executable JSON payload. | Preserve consumer/key and opaque opcode; do not import current/default payload into the pin. |
| logical BattleEvent family (`BattleEventData/Config/SkillConfig` + ConfigCharacter/ConfigAbility) | distributed family | `mixed` with ordinary-confirmed owners | No single `ConfigBattleEvent/**` directory backs the logical family at this pin. Ordinary Lingsha and YaoGuang/Elation chains prove BattleEvent can be ordinary-combat scheduling authority; mode/event owners also coexist. | Classify per owner/consumer, not by family name. |

## Reverse-ID registry

### Avatar / servant skill IDs

| ID | Investigation | Exact-pin known locations / results | State |
|---|---|---|---|
| `100102` | March 7th Preservation Skill02 | `AvatarSkillConfig.json` contains ordinary per-level `Skill02` rows; March ConfigCharacter binds indices 0..4; Ability consumers map those slots to shield %, lifetime, HP threshold, flat shield and HP-gated aggro. `ILBattleAvatarSkill[100102]` remains an unrelated collision. | ordinary producer/binding chain confirmed |
| `140204` | Aglaea servant HP/Speed construction source | `AvatarServantConfig[11402]` selects `HPSkill=140204` / `SpeedSkill=140204`; exact `AvatarSkillConfig[140204]` rows exist. `#4/#5/#6` are cross-sampled as 1-based ParamList slots. | construction producer/slot mapping confirmed |
| `1140205` | Aglaea servant BattleCry passive | `AvatarServantSkillConfig`: `SkillP03`, inspected `ParamList[0]=1`; servant Ability consumes it as `0 - value` for self `ModifyActionDelay`. | numeric consumer chain confirmed |
| `1140206` | Aglaea servant DeathRattle passive | `AvatarServantSkillConfig`: `SkillP04`, inspected `ParamList[0]=20`; `OnDeathrattle` consumes it via `ModifySPNew(CasterSummoner,+20)`. | numeric consumer chain confirmed |
| `141304` | servant `#N` cross-case | `AvatarServantConfig[11413]` + `AvatarSkillConfig[141304]` independently matches the 1-based positional rule. | cross-validation confirmed |

## Known semantic hazard registry

1. **Numeric collision:** `100102` is both an ordinary March skill identifier and an unrelated RtBattle record ID. Numeric equality is not identity proof.
2. **IL-family false friend:** `ILHardLevelGroup` is a concrete example where a plausible-looking scaling table and matching group/level keys are still the wrong ordinary authority; ownership beats field-name similarity.
3. **Trigger-key/decimal hazard:** skill numeric suffixes must not be decoded into ConfigCharacter trigger keys by decimal intuition.
4. **Search-index hazard:** GitHub code search covers the repository default branch, not the pinned commit. Search hits are navigation candidates only.
5. **Large-file read/search hazard:** a tool/read path that returns empty content or no exact hit for a very large blob is not omission proof. `AvatarSkillConfig` produced exactly this failure; direct exact-blob inspection recovered `100102` and `140204`.
6. **Arithmetic-name hazard:** `Ratio`, `Chance`, `OddsList`, `SpeedToDelayDistance` and similar names expose candidate inputs, not their final operators.
7. **RandomConfig hazard:** ordinary `OddsList` examples sum to `0.6`, `1.0` and `1.1`; do not lower entries as final normalized probabilities without the missing consumer algorithm.
8. **Presentation RNG hazard:** a `RandomConfig` inside a battle Ability can select only hit-effect/presentation variation; check state consequences before promoting the draw.
9. **Callback-order hazard:** serialized callback order is not dispatch order. Use causal dependencies and priority data; same-priority/cross-domain arbitration remains unresolved.
10. **Creation-adjacency hazard:** an operation appearing immediately after `CreateServant` does not imply it targets the servant. Aglaea Skill02's explicit `SetActionDelay(0)` targets `Caster`, not `CasterServant`.

## High-value unresolved reverse lookups

### W02 — ordinary avatar parameter model

Closed in the first parallel integration:

- March `SkillID=100102` ordinary producer exists in exact pinned `AvatarSkillConfig`;
- indices 0..4 meet their typed ConfigCharacter bindings and Ability consumers;
- Dan Heng independently cross-checks the ordinary `SkillParam` producer/binding pattern;
- SkillParam / SkillTreeParam / SkillRank are distinct producer/index spaces.

Still useful:

- add one further unrelated ordinary-character cross-check before declaring the family mapping exhaustive;
- record version-drift cases without confusing missing-current/missing-pin behavior.

Do **not** resume the disproven `100102` omission search.

### W13 — servant construction and lifecycle

Closed:

- `#N` construction references: corresponding `SpeedSkill/HPSkill` selects an `AvatarSkillConfig` ParamList and `#N` selects its 1-based slot;
- `SkillP03 -> BattleCry -> servant ModifyActionDelay(-1 normalized)`;
- `SkillP04 -> OnDeathrattle -> CasterSummoner ModifySPNew(+20)`;
- ordinary Aglaea recast is create-if-absent / maintain-existing.

Still unresolved:

- generic parser implementation for literal `"#N"` syntax;
- passive-entry activation timing on servant creation;
- exact initial queue placement / scheduler arithmetic;
- natural death-rattle/listener/OnDestroy/entity-removal total order.

Correction: Aglaea Skill02's explicit `SetActionDelay(0)` targets Aglaea (`Caster`), not the newly created servant. Do not assert literal `ActivityOnCreate=false` from that pinned Ability file; the field is absent there.

### W14 — monster final stat composition

Closed inputs/topology:

- exact ordinary `MonsterTemplateConfig[1002011]` base ATK/DEF/HP/SPD/Stance;
- ordinary `HardLevelGroup.json` as the five-stat `(HardLevelGroup,Level)` scaling-input family;
- multiple cross-level/group samples including real SPD scaling;
- Stage context and Stage/Monster EliteGroup coexistence;
- concrete/template flat-value inputs exist;
- phase-property and live StageAbility overlays are distinct post/base-construction layers.

False friend:

- `ILHardLevelGroup` / `ILBattleMonster` are not the ordinary scaling authority for the inspected chain.

Still unresolved:

- final getter/operator arithmetic, clamp/rounding and flat-value placement;
- Stage versus Monster hard-level/Elite precedence;
- phase-property application order;
- MonsterUnique participation only where explicitly referenced.

### W07 / W12 exported-engine boundaries

- W07 SPD→AV/queue/requeue/rescale/tie-break: data-facing constants/opcodes exist, but the pinned release-data dump exposes no identifiable GameCore scheduler implementation. Treat the generic formula as `blocked_evidence`, not an invitation to import public `10000/SPD` as pinned authority.
- W12 RandomConfig algorithm, `SetDynamicValueByRandom` endpoint/distribution, `AddModifier.Chance` effective-probability arithmetic and shared RNG seed/state/stream remain outside the located TBGD consumer layer. Preserve raw weights/ranges/draw sites.

### W17 reverse-scan tail

Broad first-pass findings already establish ordinary reachability for representative global modifiers, task templates, common passives, BattleEvents, Super-Break/break producers and reference/property prototypes. Remaining high-value work is narrow:

- AssistantTrigger ordinary owner or explicit `ordinary_owner_unavailable` boundary;
- opaque CommonSkillPool consumer identity while executable pin payload is absent;
- generic skill-tree loader export gap;
- only new high-signal unowned shared definitions, not exhaustive sibling enumeration.

No W19+ mechanism candidate emerged from the first five-lane pass.

## Navigation-only candidates from default-branch search

These remain non-authoritative until exact-pin verification:

- newer/current CommonSkillPool executable payloads corroborate that the family is real but must not fill the pinned executable-definition gap;
- default/current AI or avatar hits that are absent from the pin remain version-drift/navigation clues only;
- Maze/RtBattle/GridFight families may contain numeric/name collisions and must retain their own owner classification.

## Maintenance log

- 2026-09-08: Created reusable pinned-source index. Seeded W02/W13/W14 findings and known semantic hazards.
- 2026-09-08: Backfilled initial W14 identities and then corrected cached AvatarSkill blob identities.
- 2026-09-08: First five-lane integration corrected two substantive durable false conclusions: `AvatarSkillConfig` **does** contain ordinary `100102/140204` rows, and ordinary monster five-stat scaling uses `HardLevelGroup.json` rather than `ILHardLevelGroup`. Added servant passive numerics, scheduler/RNG engine boundaries, shared/global reverse-scan results and large-file search/read false-negative guardrails.