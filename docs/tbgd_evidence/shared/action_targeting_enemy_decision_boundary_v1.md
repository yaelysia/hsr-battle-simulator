# R7 — Action Targeting / Enemy Decision Boundary v1

## 1. Metadata and bounded scope

- Thread: `R7-ACTION-TARGETING-ENEMY-DECISION-BOUNDARY-V1`.
- Evidence PR: [#8](https://github.com/yaelysia/hsr-battle-simulator/pull/8), Draft and docs/evidence-only.
- Research input head: `7f58627429dddc70875008697c552125dea96a99`.
- Business kernel inspected: actual `master`, resolved to `f8e8a053ef591e1aeeb99956d46acd8390676c6f` on 2026-09-14. The research branch's older runtime is not the kernel authority for this record.
- Upstream: `DimbreathBot/TurnBasedGameData` at `14c1d18f91a8101d610e6c523447a7517de3fae1` throughout.
- Bounded status: `bounded_complete` for W11 target-layer separation and the source-facing W15 candidate/constraint boundary. W11 and W15 remain `active`; generic enemy AI is not closed.
- Maturity: pinned occurrences manually confirmed; selected producer/consumer interpretations statically cross-checked. Claim-level A/B/C/D/E accounting is in section 11. No R7 runtime-verified/E claim is made.
- Runtime, lowering, IR, tests and CI changed: **no**.

The causal starting point is an actor that already legally owns a decision/action opportunity. This record does not explain why that actor acts now. It separates legal action provenance, external/automatic action targets, impact expansion, and traversal inside an executing Ability. It does not implement an enemy controller.

Here `K/` means `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/`. All local code references below are at the inspected business SHA, not at the evidence head. JSON occurrences selected by an ID or Name are predicates, not invented array offsets. Raw field absence is not proof of a native engine default.

### Exact-pin source anchors

Each path below is relative to the pinned upstream repository. The linked path, full revision and occurrence selector together identify the source; blob IDs are retained for costly repeat lookups.

| Ref | Pinned source / exact occurrence | Blob |
| --- | --- | --- |
| S1 | [Asta ConfigCharacter](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Avatar/Avatar_Asta_00_Config.json), `SkillList[Name=Skill02].TargetInfo` and its Ability wiring | `477aaca79eecbbd220c1aa9c856a8c4d1ddc87e97` |
| S2 | [Asta Ability](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Asta_00_Ability.json), `Avatar_Asta_Skill02_Phase01/Phase02`, initial target and `Bounce_SelectTarget` caller | `a2b5f8dcea3b5b4239d723fc43ffb2e99a5b70cef` |
| S3 | [GlobalTaskListTemplate](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigGlobalTaskListTemplate/GlobalTaskListTemplate.json), `Bounce_SelectTarget` | `e278051b685184ed0466d4c30effeb765f94b7815` |
| S4 | [Aglaea servant ConfigCharacter](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Servant/Servant_AglaeaServant_00_Config.json), `SkillList[Name=Skill01]` | `cc032100ca59685fef625e94aa3b318a5b36c582cd` |
| S5 | [Aglaea servant Ability](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Servant/Servant_AglaeaServant_00_Ability.json), `Servant_AglaeaServant_00_Skill11_Phase01/Phase02` | `80cb71c2d1c5b166ec4726a1828497d8ca28d640` |
| S6 | [MonsterConfig](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterConfig.json), `MonsterID=1002011` and `MonsterID=1002041` | `f0096989cc770b8e50746c3ac929f3a7eaa58fc9` |
| S7 | [MonsterTemplateConfig](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterTemplateConfig.json), `MonsterTemplateID=1002011` and `1002041`; `1002040` is a different row | `cddb6b3d6d46ec12dc4c7a985190723aadbca57e` |
| S8 | [Sequence AI](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAI/Monster_Common_SequenceThree_AI.json), `DecisionList[Name=UseSequenceSkill]` | `26aab40120a49b8b467ac4535f80e4381d9df0c1` |
| S9 | [MonsterSkillConfig](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/ExcelOutput/MonsterSkillConfig.json), `SkillID=100201101`, `SkillTriggerKey=Skill04` | `b6cbf024dd00a13fee5578d0e3eca101d467a1e6` |
| S10 | [Monster1002011 ConfigCharacter](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigCharacter/Monster/Monster_W1_CocoliaP1_01_Config.json), `SkillList[0]`, `Name=Skill04` | `9f381d9768cd4d780d642ca3ad7e5dc2f5d14f9f` |
| S11 | [Complex soldier AI](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAI/Monster_W1_Soldier01_00_AI_A.json), `DecisionList[Name=UseSkill01]`, root tasks and consideration axis | `76d00c34f2777ec96d00d0500f0c132edb70291d` |

Large Excel contents reads returned an empty content payload with a blob identity. The exact blob was then read through the GitHub API; empty contents responses were not treated as missing rows. The ordinary MonsterConfig/MonsterTemplateConfig joins, not a filename prefix or AIName, establish the selected monster consumers.

## 2. Kernel-first consumer map

| Current local consumer | Responsibility established by inspection | Not its responsibility |
| --- | --- | --- |
| `K/rules/action_target_contract.py` | Typed `ActionTargetContractIR` and source-component roles; blocked contracts do not carry a successful selection payload | Inventing targets from skill names, UI text or `SkillEffect` |
| `K/tbgd/action_target_contracts.py` | `_contract_from_definition` joins character action-source ConfigCharacter evidence, `monster_target_source`, or `servant_target_source`; decodes raw TargetInfo with conflict/missing/decode blockers | Supplying an absent target producer from runtime defaults |
| `K/systems/action_selection.py` | `query` -> legal candidate/automatic set; `accept` -> accepted selection context; `resolve_impact` -> action-level impact expansion | Enemy skill scoring; a new external choice for each internal bounce |
| `K/tbgd/monster_cards.py` | `_action_sequence`, `_sequence_skill_id`, `_ai_policy` produce source-bearing card sequence/constraint data | Executing generic native AI |
| `K/systems/enemy_action.py` | `candidate_constraint`, `next_candidate`, command identity transport; separate cursor-mutation construction | Choosing a target, executing an action, or directly applying its cursor mutation |
| `K/systems/action_availability.py` | Legal actions from admitted actor/card/build ownership, effective level, action contract, graph/binding and resource gates; attach target queries | Turning every existing skill definition or card entry into a legal action |
| `K/systems/decision.py` | Current choice/token exposure, submitted identity/envelope validation, target acceptance, authorization transport to `scheduler.step` | Defining SPD/AV, queue ordering or a native enemy AI policy |

Core inspected blobs: target contract `1bb55c51aec3f83561b3caa3e530d7d7d5a386bc`; target lowerer `99c206a864d1ae84faefb16e5e0364c27775cf2d`; target selection `c19accf600ec7fb236e7f0dac84f280cd1fd8ca3`; monster cards `9ee1f13e564b9328f36d6f642c5aca097227219f`; enemy actions `76aca3b4c5742ff8a356aaaa72df6e9fb9f4625a`; availability `f4241c14e5f2bbd0d429da6b0cfa80866f92383e`; decision `698b09ff95ca2dee1eb38b17ce841c9dcc6e7a66`.

These are C implementations and D comparison points. Their existence is not E and is not evidence that the corresponding native GameCore bodies are exported. `systems/scheduler.py` and `systems/rng.py` were not opened for implementation archaeology.

## 3. Target semantics: T1 / T2 / T3 / T4

| Layer | Input and owner | Selected examples | Boundary |
| --- | --- | --- | --- |
| T1 — action selection target | External controller submits legal primary identity/identities against a query | `EnemySelect`, `FriendSelect` | External cardinality is not the number of eventual damage recipients |
| T2 — automatic action target | The action contract supplies its target set; the command supplies no target identity | `AllEnemy`, `AllTeamMember`, `Caster` | Automatic target resolution is not a native AI target-scoring decision |
| T3 — impact expansion | Accepted primary/automatic context plus effect shape and current target relations | `TargetAdjoinEntity`, `TargetAllTeammate`, servant/summoner relations | Expansion is not another external selection; it is not necessarily a chronological hit list |
| T4 — internal execution traversal | Ability/template execution environment and its own selector/parameter state | Initial AbilityTargetEntity, bounce template, random ParamEntity, downstream damage | Internal Retarget/random traversal does not reopen T1 |

### TargetInfo field responsibility

The current lowerer distinguishes all five requested TargetType values. `EnemySelect` projects to explicit/enemy and `FriendSelect` to explicit/ally_or_self, with one required selection in the absence of a supported `MaxTargetCount` override. `Caster` projects to automatic/self; `AllEnemy` to automatic/enemy; `AllTeamMember` to automatic/ally_or_self. Automatic contracts have zero externally submitted selections, not zero internally resolved targets.

| Raw field | Current contract role | Limit retained |
| --- | --- | --- |
| `TargetType` | T1/T2 selection mode and candidate relation | Unsupported types are blocked, not inferred from UI/SkillEffect |
| `SubTargetType` | `TargetAdjoinEntity` -> `impact_sub_target=adjacent`; `TargetAllTeammate` -> `all_teammate`; `TargetServantOrSummoner` -> selection relation | One field has variant-dependent roles; it is not universally an external sub-target prompt |
| `AliveState` | Candidate alive-state policy; supported `AliveOrLimbo` is distinct from the local absent-field alive-only projection | Native defaults beyond this admitted local interpretation remain unproven |
| `TargetFilter` | Typed selection predicate and its condition admission | An unreadable/unsupported predicate is not ignored |
| `AllowFriendServant`, `AllowEnemyServant` | Candidate servant policy, including supported forbidden and friend conditional-admission forms | No generic servant lifecycle or aggro inference |
| `MergeServantSelectToSummoner` | Selection identity normalization to the admitted summoner relation | Does not create a second independent command |
| `AvoidSelf` | Candidate exclusion | Not a score preference |
| `MaxTargetCount` | Explicit external selection bound when supported | Not a bounce count or an AoE hit count |
| `IsDynamicTarget` | Effect/execution-shape declaration | Does not license arbitrary retargeting or bypass deferred execution support |
| `AdjoinSubTargetCount` | Adjacent impact shape/count | Not the number of external primary targets |
| `InvalidTargetMessage`, `InvalidTargetMessageIcon` | Non-gameplay/UI components | Not selectable-target authority |
| action-table `SkillEffect` | Effect-shape evidence, separate from ConfigCharacter target-selection evidence | `Blast`/`AoE` labels alone cannot establish T1/T2 legality |

Missing, conflicting or unsupported source interpretation remains a blocked contract. A raw TargetInfo that can be projected is still not proof of admitted ownership, a runnable full action graph or a successful battle execution.

## 4. Asta Skill02 — one external target, internal bounce traversal

Pinned S1 declares `TargetType=EnemySelect` with `SubTargetType=TargetAllTeammate`. The T1 interpretation is one explicit enemy, while the latter field is an effect-shape discriminator. It does not instruct the player to submit every internally affected enemy.

```text
Skill02 TargetInfo (S1)
  -> character action-source ConfigCharacter evidence
  -> ActionTargetContractIR: explicit / enemy / one primary
  -> query legal candidates -> accept submitted primary
  -> initial AbilityTargetEntity damage (S2)
  -> IncludeTaskListTemplate(Bounce_SelectTarget)
       template candidate parameter: AllEnemy
       internal selected entity: ParamEntity
  -> caller's ParamTaskList downstream damage to that ParamEntity (S2/S3)
```

The required occurrence was rechecked at the pin; broader binding/execution vocabulary is reused from [R0](battle_execution_language_core_v1.md), and the random-selector boundary from [ordinary RNG/callback chains](ordinary_rng_callback_reference_chains.md). The template supplies `ByRandom=true` and `MaxNumber=1` for the selected internal traversal. This is not the external action's MaxTargetCount and does not prove the random algorithm, stream or universal replacement rule.

The R0 correction is retained: the first raw task type in the pinned `Bounce_SelectTarget` template is **`GLOABNLLLEL`**, not a literal `RPG.GameCore.Retarget`. Its selector/parameter/caller chain supports the traversal interpretation; the record does not rename the opaque raw type. A generic Retarget label is vocabulary, not a faithful quotation of this occurrence.

Current target-contract lowering classifies TargetAllTeammate as T3. An action-level impact envelope is not evidence that every member is hit on every bounce. The actual per-hit recipient is carried by the executing graph's T4 context. No second external query/submit is introduced by the bounce call. This closes the external/internal boundary, not a runtime Asta damage result.

## 5. Aglaea servant Skill01 — primary target and adjacent impact

Reuse the servant identity from [the existing Servant11402 record](../characters/aglaea_servant_11402_reference_chain.md). R7 only rechecks the selected ConfigCharacter/Ability occurrences S4/S5; it does not rederive creation, HP/SPD, scheduling, JoinSkill or death.

S4 `SkillList[Name=Skill01]` contains:

```text
TargetInfo.TargetType = EnemySelect
TargetInfo.SubTargetType = TargetAdjoinEntity
AbilityList includes Servant_AglaeaServant_00_Skill11_Phase01
```

S5 carries the accepted target through the normal Skill11 phase chain: the Phase01 sub-ability call to Phase02 passes `AbilityInherentTargetType=AbilityTargetEntity`; Phase02 exposes separate primary `AttackTargetEntity` damage and adjacent-target damage. The adjacent raw alias occurrence is retained as `ADMOGLFLKHK="TargetAlias_AbilityTargetAdjoinEntity"` with `NGLMMFNIFAF=[1]`; its separate adjacent damage operand includes `Kid_SKL_AdjDmgRate`. These are not two independent external decisions.

```text
EnemySelect primary (T1)
  -> accepted target context
  -> TargetAdjoinEntity / impact_sub_target=adjacent (T3)
  -> primary + admitted adjacent impact group
  -> separate primary/adjacent damage consumers inside Skill11 (T4)
```

The current lowerer reads `definition.source.evidence.servant_target_source`, follows `character_config_path` and `skill_trigger_key`, and projects the selected TargetInfo. No successful payload is manufactured when that evidence is missing (`servant_action_selection_source_missing`), fails decoding, or conflicts (`action_selection_source_conflict`). The matching adjacent branch of `ActionTargetSelectionSystem.resolve_impact` is the local consumer, not an extra player-target prompt.

**Admission limit:** the TargetInfo -> projection -> impact-consumer boundary is statically closed. This session did not build a new complete target catalog, submit this servant action or run its full graph. It therefore does not assert that the entire selected servant action is currently executable; any source/catalog/action admission blocker remains effective. The source shape and the conditional consumer path above are not a successful Direct trace. Generic formation placement and native adjacent enumeration remain outside this claim.

## 6. Monster1002011 — fixed action candidate and automatic AllEnemy

### Source join, preserving raw shape

```text
MonsterConfig[MonsterID=1002011] (S6)
  MonsterTemplateID=1002011
  OverrideAIPath="", OverrideAISkillSequence=[]
  SkillList includes 100201101
    -> MonsterTemplateConfig[MonsterTemplateID=1002011] (S7)
       AIPath=Config/ConfigAI/Monster_Common_SequenceThree_AI.json
       AISkillSequence=[{"MNAHFIGOHML":100201101}]
    -> DecisionList[Name=UseSequenceSkill] (S8)
       RootTask SequenceConfig -> UseSequencedSkill
    -> MonsterSkillConfig[SkillID=100201101] (S9)
       SkillTriggerKey=Skill04
    -> Monster_W1_CocoliaP1_01_Config.json (S10)
       SkillList[Name=Skill04].TargetInfo.TargetType=AllEnemy
       EntryAbility=Monster_Boss_Cocolia_P1_Weapon_Skill04_Phase01
```

`AISkillSequence=[100201101]` is normalized shorthand only. The source is an array of objects with the opaque key `MNAHFIGOHML`. The local `_sequence_skill_id` decodes the value, while `_action_sequence` preserves raw item/key evidence, sequence order and the join to the monster skill list/definition. The resulting formal action reference is **`monster_skill:100201101`**; the display name or `Skill04` string is not the command identity.

### What the selected AI proves

`UseSequencedSkill`, the template sequence, and the actual monster consumer establish a strong sequenced-candidate contract. The selected AI also has `ChoseSequencedSkillAxis` under its consideration list. Reading `DefaultDSE`, a score input, phase label, `AI_CD`/`AI_ICD`, or `ForbidClearSkillUseRecord` does not recover the native scorer, cooldown evaluator, phase machine or skill-history algorithm. Even the filename `SequenceThree` does not prove three entries: this concrete sequence has one.

The local `_ai_policy` admits the selected task shape as `fixed_skill_sequence` only with its required source/sequence conditions and no recognized complex task. Its executable admission is **candidate-constraint admission**, not native AI execution. `selection_controller=external`, `runtime_execution_admitted=false` and `enemy_ai_runtime_execution_admitted=false` remain explicit.

### Candidate, target and command are separate

1. `candidate_constraint` recognizes the admitted card constraint and returns `fixed_sequence_constraint`.
2. `next_candidate` reads the current sequence position, action reference and level; requires the definition/event and a resolved `ActionTargetSelectionSystem.query` for that same identity.
3. S10's AllEnemy projects through the **action target contract** to an automatic enemy set. The controller submits no target identity; `accept` rejects supplied target IDs for an automatic action. It does not ask the controller to choose one enemy.
4. `EnemyActionCandidate` attaches the target query; it does not accept a target or execute the action. An available candidate is not sufficient proof of final graph, ownership or resource admission: `ActionAvailabilitySystem` applies those gates before offering an action choice.
5. `command_from_candidate` transports the same actor, `action_ref` and `action_level` into `ActionCommand`, with `source="manual"` and `selection_controller="external"`. `ActionChoice` and `DecisionSystem.submit` retain that identity; no second AI-specific action namespace is introduced for later execution.
6. The local cursor uses modulo sequence length and a separate matching-command, enabled-transition mutation constructor. This is C local behavior, not proof of a universal native sequence cursor/timing algorithm.

Thus **automatic AllEnemy does not need an external target choice**, although the action/decision still goes through the external-controller submission contract. No generic native enemy AI has been recovered.

## 7. Actual ordinary complex-AI negative anchor

The candidate AI file is promoted here because its concrete consumer was joined, not because its primitive names look meaningful:

```text
MonsterConfig[MonsterID=1002041] (S6)
  MonsterTemplateID=1002041
  OverrideAIPath="", OverrideAISkillSequence=[]
  SkillList=[100204101]
    -> MonsterTemplateConfig[MonsterTemplateID=1002041] (S7)
       Rank=MinionLv2
       JsonConfig=Config/ConfigCharacter/Monster/Monster_W1_Soldier01_00_Config.json
       AIPath=Config/ConfigAI/Monster_W1_Soldier01_00_AI_A.json
       AISkillSequence=[]
    -> selected AI (S11)
       DecisionList[Name=UseSkill01]
       RootTask SequenceConfig
         -> SelectAISkillTarget(SkillName=Skill01)
              AIModifierNameSelector:
              ModifierName=Monster_Gepard_Attack_Sign
         -> UseSkill(SkillName=Skill01)
       ConsiderAxisList -> CheckSkillUsabilityAxis(SkillName=Skill01)
```

The source AIName is `Monster_W1_CWSoldier_02`; it is not substituted for the path or used to infer special-mode ownership. The selected concrete join is through MonsterConfig/MonsterTemplateConfig, not an `ILBattleMonster` collision. Template1002040 is a false friend: it shares the soldier character configuration but has a different simple AI/sequence. Neither that row nor a similarly numbered monster variant can replace Template1002041.

Current `_collect_task_types` / `_ai_policy` sees `SelectAISkillTarget`, `UseSkill` and `CheckSkillUsabilityAxis` among the explicitly complex task types. This source does not silently become `fixed_skill_sequence`; it is retained as `complex_or_unsupported_ai`, with the non-simple-policy blocker and no admitted fixed candidate constraint. This is a static producer/consumer comparison, not a newly executed card-build report.

At the consumer boundary, `next_candidate` rejects a non-executable policy as `enemy_ai_policy_not_fixed_sequence`. Separately, `candidate_constraint` may return `external_card_actions` when the declared selection controller is external. That allows the availability layer to consider otherwise admitted card actions without inventing the native AI's order/choice. It does **not** admit or execute the complex AI. Missing action/target/graph/resource authority can still block those actions.

The modifier-name target-selector edge is A source evidence. It is not a recovered generic aggro/taunt score formula, and this record does not chase its marker producer or implement its evaluation. `UseSkill`, `SelectAISkillTarget`, `AIStepperDecisionGroupConfig`, `RandomConfig`, `ByRandomChance` and `CheckSkillUsabilityAxis` must not be converted into native policies merely from readable names. No simple/complex admission mismatch requiring a runtime repair was found in this selected comparison.

## 8. Selection-system and enemy-system boundary

```text
admitted actor/card action identity
  -> EnemyActionSystem candidate constraint (enemy only)
  -> ActionTargetSelectionSystem.query
       legal explicit candidates OR automatic action target set
  -> externally submitted action command
  -> ActionTargetSelectionSystem.accept
       T1 explicit identities OR T2 empty external selection
       accepted context bound to actor/action/level/contract/state
  -> execution entry receives accepted context
  -> resolve_impact: T3 impact group
  -> Ability/template traversal: T4 internal recipients
```

`query` describes legality; it does not mutate the battle or rank enemy skills. `accept` rechecks the query against current state and rejects stale, illegal, wrong-cardinality or inappropriate automatic submissions. `resolve_impact` consumes accepted context rather than accepting an arbitrary unvalidated primary. Dynamic or unsupported target behavior is not evidence to broaden external selection.

`EnemyActionSystem` never calls these interfaces to make a target decision on the controller's behalf. Its attached query joins candidate and target authority without merging their responsibilities. Its mutation-construction helper does not make it an executor.

## 9. Decision / external-controller boundary

The inspected public path is `DecisionSystem.current_decision` / `submit`, not a newly invented native AI loop.

`current_decision` obtains `ActionAvailabilitySystem.view`. For the already-eligible actor, availability offers only actions surviving ownership/admission, effective-level, event/binding and resource checks, with a target query per action. For the simple enemy it offers the fixed candidate with `control=external`; for a complex policy the external-card-actions branch does not recover native scoring. The decision token binds the current state/choice revision, mode, actor and window.

`submit` checks the token and matches **actor_id + action_id + action_level** against an offered choice. It reconstructs the authorized command envelope from that choice, rejects conflicting internal metadata, and calls `action_targets.accept` with the offered query and the submitted target IDs. The accepted context plus the same formal identity is carried by `_issue_decision_submission_authorization` into `scheduler.step`.

That call is the execution handoff boundary. R7 does not inspect scheduler internals or assert a scheduler ordering formula. The external controller selects among legal actions and supplies T1 targets where required; for T2 it supplies no target identity. It cannot use a readable AI task or an arbitrary command ID to bypass these gates.

## 10. False friends and frozen gaps

| Tempting inference | Actual boundary |
| --- | --- |
| `SkillEffect` or UI invalid-target text defines selectable targets | TargetInfo/action-source contract defines selection; effect/UI roles remain separate |
| S10 `UseType=SelectEntity` means select one enemy | Its exact TargetInfo is AllEnemy, an automatic contract |
| Every affected entity is an external target | T1/T2, T3 and T4 are different authorities |
| Asta `TargetAllTeammate` means every enemy is hit on every bounce | An impact envelope is not a chronological internal hit trace |
| `Bounce_SelectTarget` is literally a Retarget raw opcode | The pinned first task is `GLOABNLLLEL`; retain its exact caller/selector chain |
| `AISkillSequence` is a raw integer array | The selected raw object key is `MNAHFIGOHML`; integers are the decoded sequence |
| SequenceThree means three actions | The selected template has one decoded action |
| Neighbor soldier template/config or AIName determines this policy | Monster1002041 -> Template1002041 -> exact AIPath is the authority |
| `admission_status=executable` means native enemy AI can execute | In this card slice it admits a candidate constraint; native execution flags remain false |
| Complex-policy blocker means an external controller may never act | Policy remains blocked; independently admitted card actions may be exposed externally |
| A validator file or a historical encounter run is R7 E | Only a real executed, SHA-bound, matching-scope result can support E |

B/G residuals retained: hidden AI scorer/score evaluator, conditional skill-history/cooldown semantics, priority/weights and target scoring; generic AI random choice and shared RNG streams; generic aggro/taunt formula; unsupported selector/filter/dynamic-target semantics; native formation/adjacency internals; scheduler/AV/queue total order and universal event dispatcher. These are not automatically reopened by W11/W15 remaining active. Damage, Break, resources, servant lifecycle and full-battle completion are not R7 obligations.

## 11. Claim-level A/B/C/D/E and validation

A = source-facing closed; B = export/engine gap; C = local implementation present; D = selected source/local contract aligned; E = actual executed/test-backed scope. A and C are not interchangeable. G labels a retained gap, not another maturity grade.

| Claim | A | B/G retained | C | D | E |
| --- | --- | --- | --- | --- | --- |
| S1 Asta Skill02 EnemySelect -> one external primary | yes, selected raw configuration | native unexported defaults beyond selected shape | typed projection/query/accept present | selected field-role comparison | not established |
| S2/S3 initial target -> bounce ParamEntity -> damage | yes, reused R0 plus exact-pin occurrence check | algorithm/stream/universal replacement | separate internal/selection consumers exist | boundary separation only; no new bounce execution assertion | not established |
| S4/S5 servant primary versus adjacent recipient | yes, source wiring and separate consumers | full action admission/run and native formation semantics not demonstrated here | servant target projection / adjacent impact branch present | conditional source-shape/consumer alignment | not established |
| S6/S7/S8/S9 positive fixed-sequence candidate provenance | yes | native scorer/CD/cursor internals | card producer and candidate API present | selected task admission and formal action join | not established |
| S10 AllEnemy is automatic action targeting | yes | no native AI-target scorer inferred | automatic query/accept path present | no external target identity required | not established |
| S6/S7/S11 actual complex consumer exists | yes | complex evaluator remains blocked | explicit complex-task classification present | selected source not silently reduced to fixed sequence | not established |
| Candidate -> query -> same formal command identity | source action join yes | later full execution not claimed | candidate/availability/decision transport present | static identity agreement | not established |
| Decision token/choice/target acceptance handoff | not claimed as native exported engine body | native scheduling body out of scope | current local API inspected | consumer-boundary comparison only | not established |
| Generic scorer, weights, aggro, RNG and scheduler formulas | not closed | B/G | no completeness claim | not established | not established |

### Existing verification inspected, not rerun

At the inspected business SHA, `K/tools/validate_p9_s5c1_action_target_source_contract.py` contains raw-source/field-role and contract negative audits. `K/tools/validate_p9_s5c2_action_selection_query_submit_context.py` contains query/submit transport fixtures; it explicitly marks fixture evidence `gameplay_executable_evidence=false` and an event as `S5C2 transport fixture; not real gameplay evidence`. The generic selected contracts in those fixtures are not a demonstrated execution of all four R7 anchors.

No retained result with an actual tested SHA and a directly matching R7 scope was adopted as E. The R6A encounter proof retained in the README is not targeting/AI validation. This thread did not run the simulator, Direct, a full target catalog, new tests or a transient workflow. Source inspection and static cross-checking are the validation level of this bounded record. Docs CI is reported against the actual final evidence head in the PR checkpoint; `skipped` is never reported as `passed`.

## 12. Exit accounting and next residuals

| Bounded exit condition | Accounting |
| --- | --- |
| Explicit TargetInfo -> IR -> external selection semantics | S1 and sections 2–4; static A/C/D, not an executed action |
| Primary target -> adjacent/internal impact chain | S4/S5 and section 5; source/consumer boundary closed without bypassing possible full-action admission blockers |
| Internal traversal separated from external selection | Asta caller/template/ParamEntity chain and T1–T4 classification |
| Monster1002011 AIPath/sequence -> card -> candidate | Sections 6 and 8; raw object shape and formal skill identity retained |
| AllEnemy belongs to action target contract | S10, automatic acceptance, no fabricated single-target AI decision |
| Actual ordinary complex consumer and non-admission | Monster1002041 -> Template1002041 -> S11; section 7 |
| External-controller / Decision boundary | Sections 8–9; same identity plus accepted context at execution handoff |
| Generic AI/RNG/aggro/scheduler gaps explicit | Sections 6–7 and 10–11, B/G retained |
| Claim-level A/B/C/D/E | Section 11; no E awarded |
| PR remains docs/evidence-only and Draft | Publication constraint; final head, parent, changed paths, Draft and CI are checked and recorded in the PR checkpoint |

No selected source/local mismatch requiring runtime, lowering or IR changes was established. The bounded result is useful without pretending to recover generic enemy AI or to run a complete battle. The worklist's broader inventory/formation/taunt/AI-scoring obligations stay open; the new R7 leaves do not mechanically close their parents.

**Stop at R7. Return to integration/planning for the R8 decision; do not start R8 automatically.**
