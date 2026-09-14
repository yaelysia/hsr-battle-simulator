# R9 — Owned Servant Creation / Ownership / Runtime Admission v1

## 1. Metadata and bounded result

- Thread: `R9-OWNED-SERVANT-RUNTIME-ADMISSION-V1`.
- Reviewed: **2026-09-14**.
- Work package: selected W13 owned-servant creation vertical slice.
- Evidence PR: [#8](https://github.com/yaelysia/hsr-battle-simulator/pull/8), Draft / docs-only.
- Research parent, re-read before submission: `c13d4dcf0932551578fb8e4329d5c77f74d4e02f`.
- Business master independently resolved at execution start: **`f8e8a053ef591e1aeeb99956d46acd8390676c6f`**.
- Pinned TBGD: **`14c1d18f91a8101d610e6c523447a7517de3fae1`**, repository `DimbreathBot/TurnBasedGameData`.
- Integration authorization: [R9 integration plan](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5661982814).
- Status: **`partial / NEEDS_REPLAN`**; maturity: `manually_confirmed` source/static-code findings, not `runtime_verified`.
- Production gap: **R9-G01 — no executable ordinary CreateServant caller transport**.
- Runtime changed: **no**. New tests/workflows/implementation PRs: **none**. Runtime E: **not established**.

The first gate fails before the selected ordinary action can reach servant birth. Source creation, definition construction and the spawn consumer are separate existing surfaces; their coexistence is not an executable connection. This is an implementation-integration concern, not a reason to search additional servants or recover a hidden native evaluator.

All kernel references below use the business SHA above, not the research branch's older code, its PR base metadata, or an unmerged implementation PR. `CORE` abbreviates `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core`.

## 2. Reused W13 source facts

Reuse the [Aglaea/11402 reference chain](../characters/aglaea_servant_11402_reference_chain.md) and [Battle Execution Language Core v1](battle_execution_language_core_v1.md); these facts are not rediscovered or generalized here.

`AvatarServantConfig[11402]` names `Servant_AglaeaServant_00_Config.json`, `Avatar_ComplexSkilll_AutoFight_AI.json` and skills `[1140201,1140203,1140205,1140206]`. Dedicated construction inputs are `SpeedInherit="#4"`, `SpeedSkill=140204`, `HPInherit="#5"`, `HPBase="#6"`, `HPSkill=140204`, and `Aggro=125`. Skill140204 Lv1 has `[0.12,0,0,0.35,0.44,180]`; `#N` selects the corresponding skill's one-based ParamList slot. These are source-facing inputs, not a recovered native HP/speed formula or parser body.

Ownership comes from the ordinary owner's CreateServant occurrence and runtime relations such as `CasterSummoner`, not a fixed owner field in the servant table. Global `ServantSyncPropertyList`, per-servant `SyncPropertyExceptList`, and dedicated HP/speed fields remain three different source surfaces. No effective-sync subtraction/union formula, timing or precedence is asserted.

The selectable servant Skill01 and the owner's coordinated Skill11/Together contribution are distinct. Existing pre-death/death-rattle/death-listener/removal evidence and muted forced cleanup remain separate lifecycle surfaces.

## 3. Exact selected CreateServant producer

Pinned source: [Avatar_Aglaea_00_Ability.json, lines 690–800](https://github.com/DimbreathBot/TurnBasedGameData/blob/14c1d18f91a8101d610e6c523447a7517de3fae1/Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json#L690-L800).

- Source blob: `c1993e2663dfcd0748e45b421411f7f4fdc093e8`.
- Ability: `Avatar_Aglaea_00_Skill02_Phase02`.
- JSONPath: **`$.AbilityList[3].OnStart[1].SuccessTaskList[0]`**.
- JSON pointer: `/AbilityList/3/OnStart/1/SuccessTaskList/0`.
- Type: `RPG.GameCore.CreateServant`.
- ServantID: `IsDynamic=false`, `FixedValue.Value=11402`.

The parent `PredicateTaskList` uses `ByCompareTargetCount`, `TargetAlias= CasterServant`, `AliveOnly=true`, comparison `LessEqual` against fixed zero. The selected create is therefore in the no-living-servant branch. Its dynamic inputs are `_PointB3Layer` (hash `138415046`), `Skill11_DamagePercentage` (`-909740667`) and `Skill11_DamagePercentageAD` (`1326964645`). Their presence must not be mistaken for an executable local spawn binding.

The later explicit `SetActionDelay(0)` targets **Caster**, not CasterServant. No `ActivityOnCreate` or synchronous passive-startup meaning is invented. This lookup refines an already retained source occurrence; it does not introduce a new source family or require an index-wide update.

## 4. Kernel-first producer and formal task boundary

Relevant immutable kernel anchors:

| Surface | Exact business source / inspected boundary |
| --- | --- |
| Generic Ability task identity and lowering | [tbgd/lowering.py, 5310–5795](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py#L5310-L5795), `_lower_ability_task_tree` and `_lower_formal_ability_task_tree`; blob `335c6bb78d91ce5a4a19d61377e36a6f18988ca2` |
| Opcode admission | [tbgd/coverage.py](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/coverage.py), `ability_task_execution_mode` / `classify_opcode`; blob `12a4c974c0c1652667e3193b942b70b1f6139b1f8` |
| Formal action leaf dispatch | [systems/ability.py, 639–835](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py#L639-L835) and [1632–1730](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability.py#L1632-L1730); blob `19b1f63abb70a32b636278be680db5f107a823f1` |
| Task admission guard | [systems/ability_task_contract.py](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_task_contract.py), `ability_task_runtime_blocked_reason` |
| Default effect handlers | [systems/effect.py, 80–220](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/effect.py#L80-L220); blob `990b3fb0a6e7f0e7d7a1e078f0fe601c25e51b53` |
| Separate servant consumer | [systems/summon.py](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/summon.py), `SummonSystem.plan_spawn_servant` |

For the raw type, generic lowering obtains opcode `CreateServant`. The task constructor is:

```text
task_id = ability_task:{phase_id}:{callback_kind}:{task_path}:{opcode}
effect_id = effect:{task_id}
AbilityTaskIR(opcode=CreateServant, effect_id=..., source=...)
EffectIR(opcode=CreateServant, payload=..., source=...)
```

The task IRSource carries `source_path=ability_path`, `raw_type=AbilityTask`, `raw_id=ability_name`, plus action/level/phase/callback/task path, `source_opcode`, and exact `json_path` evidence. Formal topology lowering checks the raw task against its source document/location and retains source identity while constructing formal child nodes. This is a **structural producer**, not an executable servant-creation operation.

`CreateServant` is not an executable or process-only opcode registration in the inspected coverage module. Its generic execution mode is `runtime_effect`; generic task construction promotes runtime-effect tasks only when effect coverage is executable, otherwise it leaves them blocked. A source-bearing task/graph node does not by itself establish a typed executable ServantID-to-definition binding.

No selected Aglaea materialization was executed in R9. The ID constructor and source location above are code/source facts, not a claimed observed concrete task ID, graph ID or serialized runtime artifact.

## 5. R9-GATE: actual production transport

The formal ordinary action route is:

```text
AbilityTaskSystem.execute_callback
-> _execute_formal_action_callback / _execute_formal_entries
-> formal task-graph leaf hook
-> _execute_formal_leaf_task(invocation_kind=action)
-> _execute_ability_leaf_task(topology_authority=task_graph)
-> admission guard
-> specialized SummonMonster or damage handling, otherwise effect leaf
-> EffectRegistry
```

The inspected leaf dispatcher has an explicit **SummonMonster** branch, not a CreateServant branch. The default EffectRegistry registers no CreateServant handler. `_execute_effect_leaf_task` rejects non-executable coverage; even a directly supplied effect with fabricated executable coverage would not create a missing default handler (`effect_handler_missing:CreateServant`). These are separate defensive boundaries, not permission to forge executable coverage or install an ad hoc handler.

Consequently the current selected production route supplies no executable edge that resolves this occurrence's `ServantID=11402`, looks up its `ServantDefinitionIR`, determines a source/build-backed owner, and invokes `plan_spawn_servant` with this occurrence's declared spawn source. Ordinary formal assembled-character execution uses the same formal leaf route; a direct call to the spawn API is not an alternative proof for that route.

### R9-G01

```text
producer = Config/ConfigAbility/Avatar/Avatar_Aglaea_00_Ability.json
           $.AbilityList[3].OnStart[1].SuccessTaskList[0]
           RPG.GameCore.CreateServant(ServantID.FixedValue.Value=11402)
lowered_producer = source-bearing AbilityTaskIR / EffectIR, opcode CreateServant
consumer = SummonSystem.plan_spawn_servant
missing_edge = executable CreateServant admission and formal task consumer
               -> selected ServantDefinitionIR lookup
               -> source/build-backed owner
               -> exact occurrence spawn_source
               -> plan_spawn_servant
business_kernel_head = f8e8a053ef591e1aeeb99956d46acd8390676c6f
impact = ordinary Aglaea formal CreateServant cannot reach runtime servant spawn
status = partial / NEEDS_REPLAN
```

This is a local production transport gap, not the native engine/export gap for sync timing or passive entry. Repair needs compiler/runtime integration and appropriately scoped validation outside PR #8. Further servant samples cannot supply the missing local caller. R9 stops expansion at this gate.

## 6. Separate definition / owner / source-proof contracts

The inspected lowering includes separate servant-definition construction and `_discover_servant_spawn_sources`; definition metadata is not dispatched as an Ability operation. The discovery helper records CreateServant occurrence sources with `raw_type=RPG.GameCore.CreateServant`, occurrence identity and servant ID. Generic AbilityTask sources use another raw type/evidence shape. A future caller must preserve/map the exact occurrence to the **declared** spawn-source object; merely passing an arbitrary task source or `definition.source` is not sufficient equality/provenance proof.

The existing consumer accepts a `ServantDefinitionIR`, resolves the actual owner from state, and calls `definition.owner_relation_for(owner.template_id)`. It also asks `_formal_owned_combatant_build(owner, definition)` for formal owned-build admission. Thus a matching avatar template number alone is not the whole formal owner/build contract.

Its provenance checks are meaningful:

```text
supplied spawn_source not in definition.spawn_sources
  -> servant_spawn_source_not_declared_by_definition
assembled_character_build and spawn_source is None
  -> formal_servant_spawn_source_required
```

The later `spawn_source or definition.source` fallback is **after** the assembled-owner guard; it is not authorization to bypass that guard for an assembled character. No caller is present here to observe dropping or substituting the source. Accordingly this record reports **G01**, not an invented observed G02 or G03.

Definition fields, owner relations, spawn sources, lifecycle sources, action sets and birth-template references are potential downstream contracts. R9 does not claim that a selected 11402 assembled build traversed, materialized or validated all of them. Full `OwnedCombatantBuildAssemblyResult`, lifecycle/stat/action bindings and selected owner admission remain downstream verification work after G01 is repaired.

## 7. Stat / synchronization partition

At S, preserve separately:

1. `GameCoreConstValue.ServantSyncPropertyList`;
2. per-servant `SyncPropertyExceptList`;
3. `HPBase/HPInherit/HPSkill` and `SpeedBase/SpeedInherit/SpeedSkill` construction references.

At K, the inspected lowering's `_servant_owner_sync_fields` has explicit property-family/exception checks and source traces; this is not evidence that every owner stat is blindly copied. Nevertheless R9 has not closed the selected `OwnedCombatantStatBinding -> birth -> runtime stat projection` chain, nor proved global-sync-source representation or native merge/timing. **Dedicated versus generic formal binding alignment remains not established in this gate-stopped record.** No G04 verdict is manufactured from uninspected downstream behavior.

Independent discriminator: reuse the existing W13 servant11413 `#N` cross-sample. It supports the corresponding-skill/one-based-slot interpretation without turning 11402's numeric slots, exclusions or ownership into a global servant rule. No second servant vertical slice was run.

## 8. Static spawn-plan boundary; no birth/registry closure

`plan_spawn_servant` statically obtains the birth template and constructs a `UnitSpawnRequest` with:

| Field | Consumer-side assignment |
| --- | --- |
| `spawn_kind` | `servant` |
| `owner_id`, `summoner_id` | supplied and admitted owner identity |
| `entity_ref` | `definition.servant_ref` |
| `birth_template_id` | selected definition/template reference |
| `source_id`, `entry_id` | servant-definition identity |
| `source_trace` | effective spawn source, requiring the declared occurrence for formal owners |
| `entry_source_trace` | definition source |

It delegates to `UnitSpawnSystem.plan(template, request, owner=owner)`. This verifies the **existence and shape of a consumer-side API boundary**, not successful traversal from the selected raw create.

The selected birth template's HP/SPD/resources/action/build flags, actual UnitState team and owner/summoner fields, and `apply_spawn -> summon_runtime` dual consistency are **not established by R9**. In particular `entities`, `by_owner`, `servants`, `last_servants`, active/removed flags, and bidirectional UnitState/registry validation are not promoted merely because their consumer APIs or unit tests exist. G05 is unadjudicated, not cleared.

No wave-enemy Catalog, native HP formula, sync evaluator, SPD-to-AV conversion or broad lifecycle dispatcher was reopened.

## 9. Recast, active duplicate and defeated replacement

Source A already closes ordinary create-if-absent / maintain-or-heal-existing. The exact selected predicate confirms that the CreateServant occurrence requires no living CasterServant.

The spawn consumer's `servant_duplicate_active_policy_missing` is a defensive fail-closed boundary for callers that attempt a duplicate active spawn. It does not redefine normal recast as spawn-and-replace. Because the formal creation transport is missing, R9 has no observed production living-servant branch that wrongly calls spawn and reports no such extra bug.

The consumer also checks defeated instances and replacement policy, including `servant_replacement_policy_missing`. This selected source gate does not establish formal defeated-instance replacement authority. Keep replacement blocked absent the required admitted policy; do not infer unconditional recreation from gameplay or convert an AliveOnly condition into an unproven replacement policy.

## 10. Skill01 / Together, resources and lifecycle residuals

At S, servant11402 Skill01 is selectable (`UseType=SelectEntity`, `EnemySelect`), whereas owner Skill11 coordinates a `TriggerParallelAbility(CasterServant)` Together contribution. Their source action/graph identities must remain distinct. Local selectable action ownership, action admission and availability for the selected assembled servant were not closed after G01; no G06 clearance or failure is inferred. Full Together execution is not required for a future R9 creation closure and an unmerged P9 change is not current-master authority.

Reuse R7 for the selected target boundary and R4/W08 for resource boundaries. Skill01 `SPBase=10`, servant BattleCry self delay, and DeathRattle `ModifySPNew(CasterSummoner,+20 raw)` do not establish UI Skill Point meaning, caps or a generic resource evaluator. No new typed resource/action consumption claim is added.

Own speed and self delay are source evidence for an independently actionable entity surface, not proof of initial queue position, SPD-to-AV, tie-break/requeue or OneMore interaction. Passive EntryAbility existence remains `engine_consumer_unavailable` for native create-time auto-entry. Natural and muted cleanup stay distinct; retained removed-registry records, if inspected in a later pass, would be local audit identity rather than native death timing.

## 11. Claim-level A / B / C / D / E

A = pinned source-facing closed; B = native/export gap; C = local implementation present; D = selected source/local alignment; E = actual executed/test-backed at a stated tested SHA. “Not established” is not “absent”; “not audited after gate” is not “passed”.

| Claim | A | B / residual | C | D | E |
| --- | --- | --- | --- | --- | --- |
| Exact CreateServant11402 occurrence and predicate | Closed, section 3 | None for these literal fields | Generic source/task construction present | Occurrence/source representation only, not spawn execution | Not established |
| Formal CreateServant task lowering | Raw producer closed | Not a native-gap excuse | Generic task/effect structure; no executable servant admission established | Executable operation alignment missing, G01 | Not established |
| Actual caller -> definition -> spawn transport | Raw producer closed | Local integration gap G01 | Missing in inspected formal action/default effect route | Not closed | Not established |
| ServantDefinitionIR construction/lookup | Source table/creation facts reused | Selected lookup occurs only after missing edge | Definition construction and consumer parameter exist | Selected production lookup not closed | Not established |
| Owner relation | Source owner relation reused | Formal selected build downstream | Consumer relation/build gates present | Consumer guard only; selected assembly not closed | Not established |
| Owned build lifecycle/stat/action admission | Source surfaces reused | Gate-stopped | Full selected assembly not audited | Not established | Not established |
| Dedicated HP/speed bindings | Dedicated inputs and #N closed | Native evaluator/timing frozen | Selected assembled binding not audited | Not established | Not established |
| Generic sync-source partition | Distinct source surfaces closed | Native merge/timing/precedence unknown | Exception-aware helper seen; full global-source transport not closed | Not established | Not established |
| Exact spawn-source proof | Raw occurrence closed | Caller absent | Non-null and membership guards present | Guards preserve a requirement; no caller proof | Not established |
| UnitSpawnRequest | Source identities reused | Birth not reached | Static consumer assignments present | Request from actual selected create not established | Not established |
| Servant UnitState identity | Source independent servant surface closed | Gate-stopped | Downstream instance not inspected/executed | Not established | Not established |
| summon_runtime ownership registry | Source ownership relation reused | Gate-stopped | Downstream consistency not audited | Not established | Not established |
| Create-if-absent / active duplicate | Closed source recast | No replacement inference | Defensive duplicate blocker present | Static boundary explanation only | Not established |
| Selectable Skill01 ownership | Servant-owned source surface closed | Local action path gate-stopped | Selected assembled action not audited | Not established | Not established |
| Together ownership | Distinct owner-coordinated contribution closed | Full parallel execution remains separate | No unmerged change used as authority | Local full action identity/execution not closed | Not established |
| Defeated replacement | Selected explicit policy authority not established | Keep blocked without formal authority | Replacement guard present | Not established | Not established |

No blanket A/C/D/E label applies to the whole record. G02–G06 are **not adjudicated beyond the limited static observations above**, not a claim that the whole downstream kernel is defect-free.

## 12. Existing validation scope and exit accounting

Existing [tests/test_servant_runtime_admission.py](https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_servant_runtime_admission.py#L1-L200), blob `308a0ab6db07e36f37200b02cfc0d0d8a9f690c6f7`, contains `test_servant_spawn_and_remove_via_formal_consumer`. It constructs fixture IR/UnitState and directly calls `SummonSystem(rules).plan_spawn_servant(state, definition, owner_id="aglaea")`. That first fixture call supplies no `spawn_source` and is not an ordinary assembled Aglaea Ability invocation. Its registry/action/queue assertions are useful consumer-test coverage, **not proof that the pinned CreateServant production caller exists or ran**.

R9 inspected test source, not an executed selected-source report. No retained run with exact selected Aglaea caller scope plus tested SHA was established. No simulator, Direct, Catalog or unit test was run in this thread. Therefore **E remains not established**, including for the inspected fixture tests; test existence is not test execution. Documentation CI is accounted separately in the PR checkpoint, and a skipped workflow is never counted as passed.

Exit obligations 1 (exact producer) and structural part of 2 (task/source representation) have evidence. Obligations 3–4 (actual caller and transport) fail at G01. The consumer has the obligation-5 provenance guard, but its selected caller proof is missing. Remaining owner/build/stat/birth/registry/action closure obligations are not promoted through that gap. Frozen engine boundaries and claim-level accounting are retained.

**Final R9 status: `partial / NEEDS_REPLAN`, not `bounded_complete`.** Persist this record, update README navigation and only the selected W13 worklist leaf, retain PR #8 Draft/docs-only, then stop. Integration/planning must decide whether and how to authorize an independent implementation repair and later narrowly validate the repaired source-facing caller. **Do not automatically enter R10.**
