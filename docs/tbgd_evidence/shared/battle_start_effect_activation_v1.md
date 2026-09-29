# R8 — Battle-Start Effect Activation / Startup Admission v1

## 1. Metadata and bounded authority

- Thread: `R8-BATTLE-START-EFFECT-ACTIVATION-V1`.
- Scope: W18 and the startup-facing W09/W01 residual of R5; LC20000, Set102, Set301 and Dan Heng Technique only.
- Research parent inspected: `d123ef3e710006d499446c915b5d3b20f0c7a866`, PR #8, `research/tbgd-battle-evidence-ledger`.
- Business `master` resolved and inspected: `f8e8a053ef591e1aeeb99956d46acd8390676c6f`. This is not the evidence-branch runtime.
- TBGD pin: `14c1d18f91a8101d610e6c523447a7517de3fae1`.
- Authorization: [R8 integration plan](https://github.com/yaelysia/hsr-battle-simulator/pull/8#issuecomment-5660811507).
- Status: `bounded_complete` for the source/static-kernel activation boundary described below; maturity `cross_validated`, **not** `runtime_verified`.
- Runtime/lowering/IR/tests/CI changed: **no**. Actual simulator execution in this thread: **not run**. E is **not established** for every R8 claim.

The source facts below are explicitly reused from [R5 at the research parent][R5], not rediscovered from live tables. [R3][R3] supplies the already bounded modifier/lifecycle vocabulary and [R0][R0] the execution-language vocabulary. Current business code is an independent consumer map, not authority for an unexported GameCore implementation.

Here, D means inspected source-to-local contract alignment, not a claim that a selected compiled graph or callback has actually run. A successful registry call, a startup-spec object, and an applied modifier are different assertions. No runnable BUILD-01 parity or complete battle is claimed.

## 2. R5 facts reused, without rebuilding the panel

The selected build is Avatar1002, level80/promotion6, E0, Rogue/Wind; compatible LC20000 level80/promotion6/rank1; four distinct Set102 slots and two distinct Set301 planar slots; selected static Point1002201. It is an analyst-selected finished build, not an account-acquisition proof. Technique possession is a separate optional pre-battle state, not part of that equipment tuple. [R5, sections 2–10][R5]

| Anchor | Already closed source input | Activation discriminator |
| --- | --- | --- |
| LC20000 | `EquipmentSkillConfig[20000, Level1].ParamList=[0.12,3]`; exact filename `Config/ConfigAbility/Equip/EquipmemtAbility.json` | Base stats are static; Ability20000 installs the crit modifier at startup |
| Set102/2 | `PropertyList: AttackAddedRatio=0.12` | Static only; its empty Ability does not erase the static bonus |
| Set102/4 | `PropertyList: SpeedAddedRatio=0.06`; Ability51021; parameters `[0.06,0.1]` | Static speed versus normal-hit damage-data callback |
| Set301/2 | `PropertyList: AttackAddedRatio=0.12`; Ability53011; parameters `[0.12,120,0.12]` | Static ATK versus conditional submodifier ATK |
| Point1002201 | Selected level1 `AttackAddedRatio=0.04` | Static trace property, not a trace startup ability |
| Technique100207 | Level1 parameters `[0.4,3]`, reached through MazeBuff100201/CharacterSkill/SkillMaze | External pre-battle transport, then startup listener, then battle-entry callback |

R5's locally calculated pre-effect speed is **141.632**. Thus `141.632 >= 120` is a true input comparison, not evidence that Set301's predicate, submodifier or property-change listener executed. No full panel or promotion/affix arithmetic is recalculated here.

## 3. Kernel-first startup map

Inspected symbols are linked to the exact business SHA in section 14. The selected producer/consumer chain is:

```text
CharacterBuildInput / finished equipment instances
  -> assemble_character_build
     -> assemble_equipment_build
        -> static contributions
        -> source-bearing DynamicMechanismSelection
  -> _plan_formal_character_birth / _formal_character_activation
     -> UnitState birth inputs
     -> equipment provider selections + _equipment_startup_spec
  -> UnitState exists in BattleState
  -> register_dynamic_ability_providers                 [B1, identity only]
  -> _apply_startup_ability_effects                     [B2]
     -> selected graph / phase / startup root AddModifier
     -> StatusSystem.apply_add_modifier
     -> committed status + lifecycle events
     -> EventDispatchSystem / StatusCallbackSystem
  -> _apply_battle_setup: explicit statuses, summons
  -> _dispatch_battle_setup_event: OnEnterBattle        [B3]
  -> timeline initialization, birth_after_enter_battle
```

Formal assembly and startup specification are planned before mutation. A calculated panel is not an admission token: character assembly/admission rechecks the canonical selected inputs and equipment result. An unresolved/partial dynamic mechanism must not be silently dropped to obtain a seemingly valid stat-only character. [K1][K1] [K2][K2] [K4][K4]

The same startup executor also receives eidolon, trace and monster-passive specifications. This is a single machinery discriminator, not a new audit of those source families.

## 4. Four activation channels — R8 terminology

These labels describe **channels**, not R5's B0/B1/B2 construction snapshots.

| Channel | Owner and timing | Formal output | Explicit non-equivalence |
| --- | --- | --- | --- |
| **B0 — Static construction** | Assemblers, before UnitState creation | Static contribution ledger, stat pools and resources | Not `OnStart`, not an installed status |
| **B1 — Dynamic provider registration** | Admitted equipment/set mechanism, after owner UnitState exists | Provider identity, graph reference, typed exact parameter bindings and source identity | Registry entry is not an executed passive |
| **B2 — Immediate startup ability** | Source-bearing startup spec and selected canonical graph | AddModifier installation and its admitted lifecycle consequences | Ability registration is not startup execution; `OnStart` is not `OnEnterBattle` |
| **B3 — Battle-entry event** | Scenario/setup dispatch to admitted status listeners | Source-facing callback gate and consequent effects | External Maze acquisition is not manufactured by a character build |

Avatar/LC base stats, selected relic main/substats, set PropertyList and Point1002201 belong to B0. Dynamic parameter arrays do not themselves add values to B0. A later effective-stat read can combine B0 pools with active B2/B3 statuses without rewriting the original panel. [K1][K1] [K2][K2] [K3][K3] [K8][K8]

## 5. LC20000: rank source to startup and property consumer

**Partition and selection.** `assemble_equipment_build` emits LC base-stat contributions separately from its passive. The selected Rogue wearer passes the local path eligibility check. Wrong-path handling retains base stats but deactivates the passive; that inspected policy is not a newly established universal native equip rule. The active passive is represented by a `DynamicMechanismSelection`, not a direct `+0.12` resource write. [K2][K2]

The LC basis is `LightConeRankParameterBasis`: definition identity, skill identity, selected rank and the exact selected rank source. Rank is the superimposition/skill-parameter selector, not promotion. `equipment_dynamic_parameter_context` resolves that basis against the canonical LC definition and selected rank, then resolves its mechanism and source-owned graph. The provider source is the selected LC instance; the owner is the actual wearer unit. [K2][K2] [K5][K5]

The lowerer gives an equipment graph a source-row-derived identity of the form `standalone_equipment_ability_graph:<source_path>:ability_list_row:<record_index>`. Both graph and phase retain the selected `ability_source.source`; the mechanism/selection/registry retain the exact graph reference. No graph row number or concrete serialized provider ID is invented here: no new canonical bundle was built. Equality is checked on canonical source objects, not just `Ability20000` or a matching float. [K6][K6] [K7][K7]

The reused source chain is:

```text
Ability20000.OnStart
  -> AddModifier(Caster, MEquip_20000_Main)
       LifeTime: SkillEquip index1 / hash -1970381737 = 3
MEquip_20000_Main.OnStack
  -> StackProperty(ModifierOwnerEntity, CriticalChanceBase)
       value: SkillEquip index0 / hash -1330896030 = 0.12
```

`_equipment_startup_spec` transports the resolved full parameter list and configured hash bindings, with read ID/read source/value source/index. `_apply_startup_ability_effects` resolves the exact graph, finds its OnStart phase and admitted root AddModifier, binds the configured hashes, and installs the status through `StatusSystem`. The caster/owner/parameter/current-target startup identities are the same actual unit. Registry registration occurs first. [K4][K4] [K7][K7]

**Important local consumer distinction.** `StatusSystem.apply_add_modifier` resolves the modifier definition, dynamic values and `_runtime_modifiers`, then stores the modifiers on the status instance. Its property mapping is `CriticalChanceBase -> (crit, critical_chance)`. `StatusCallbackSystem._execute_formal_leaf_task` treats `StackProperty` as a successful non-mutating callback leaf; it does **not** apply the property a second time. `effective_unit_stat(unit, "critical_chance")` reads the installed status term together with the unit's base resource. This is the current declarative local implementation of the authored property consequence, not proof of native OnStack internals/order. [K8][K8] [K9][K9] [K10][K10]

Blocked authority is layered: definition/rank/graph/read closure in RuleBook and assembly; identity integrity in the registry; startup graph/effect/value admission in build_state; modifier/lifecycle admission in StatusSystem; callback admission in event dispatch. The startup executor rolls back that task's candidate state when installation or its dispatched lifecycle callbacks fail; formal equipment startup does not treat the blocked result as an applied passive. **LC equipped does not establish active +0.12 crit.** [K12][K12] [K13][K13]

## 6. Set102: threshold, static speed and dynamic hit context

`relic_set_assembler` checks distinct equipped slot identities and qualifies the 2/4 thresholds. The 2-piece ATK contribution and 4-piece SPD contribution are static outputs; the 4-piece ability is a separate dynamic output. Its provider source is the threshold decision, with `RelicSetThresholdParameterBasis` retaining threshold/set identity, required count and exact source. [K2][K2] [K3][K3] [K5][K5]

```text
Set102 / 2 -> PropertyList AttackAddedRatio +0.12       [B0]
Set102 / 4 -> PropertyList SpeedAddedRatio +0.06        [B0]
           -> Ability51021 / parameters [0.06,0.1]      [B1]
Ability51021.OnStart
  -> AddModifier(Caster, MRelic_102_Main)               [B2]
MRelic_102_Main.OnBeforeHitAll
  -> Normal attack predicate
  -> ModifyDamageData(Attacker_AllDamageTypeAddedRatio,
       SkillRelic(102_4,index1), hash459179394 = 0.1)
```

`_equipment_startup_spec` and the shared startup executor install the main modifier, subject to the same canonical graph and callback-admission checks as LC startup. Status installation retains `trigger_ids_by_event`; later callback selection is limited to the IDs attached to that status instance, not arbitrary same-named callbacks. `StatusCallbackSystem` has a distinct `ModifyDamageData` consumer. The R8 endpoint is listener installation/availability and source-aligned dispatch ownership, **not** a newly executed attack or R1 damage evaluation. [K4][K4] [K8][K8] [K9][K9]

The static ledger is not populated by copying ParamList into properties. The repeating `0.06` does not create another speed contribution, and matching-hit `0.1` is neither a static ATK increase nor an unconditional panel damage bonus. Native global ordering of OnBeforeHitAll versus other hit callbacks remains B/G; E for a real selected hit is not established.

## 7. Set301: static ATK, installed main status, conditional submodifier

```text
Set301 / 2 -> PropertyList AttackAddedRatio +0.12       [B0]
           -> Ability53011 / [0.12,120,0.12]            [B1]
Ability53011.OnStart
  -> AddModifier(Caster, MRelic_301_Main)               [B2]
MRelic_301_Main.OnStack
  -> Speed >= SkillRelic(301_2,index1)=120
  -> conditional submodifier installation
submodifier.OnStack
  -> AttackAddedRatio += SkillRelic(301_2,index2)=0.12
```

The main status and conditional child are different installations. The child ATK term is read through the same status-property/effective-stat consumer described above, not through a second static PropertyList contribution. `_execute_predicate_task` uses a condition result to select success/failure children; false is not inherently a blocked callback. Source-attached property-range callbacks retain watcher/range/branch identities, checked by `execute_callback_id`; this is an attachment/identity observation, not recovery of a generic watcher scheduler. [K8][K8] [K9][K9] [K10][K10]

The authored property-change range has add/remove paths. R8 keeps three distinct statements: (1) the R5 input comparison would be true; (2) current machinery can install the selected main status and execute admitted conditional callbacks through the documented contract; (3) that concrete selected callback/submodifier was actually executed. Only the first two are supported by this source/static inspection. The third remains **E not established**. No permanent-lifetime rule is inferred from an omitted lifetime.

## 8. Technique: external pre-battle state versus battle entry

The reused pinned bridge is not scene-only:

```text
LocalPlayer_DanHeng_MazeSkill.OnStart
  -> AddMazeBuff(Caster, ID100201, LifeTime=-1)
AvatarMazeBuff100201
  -> ADV_StageAbility_Maze_DanHeng
  -> InBattleBindingType=CharacterSkill
  -> InBattleBindingKey=SkillMaze
  -> UseType=AddBattleBuff; MazeBuffType=Character
CharacterConfig.SkillMaze
  -> Caster -> Avatar_DanHeng_SkillMazeInLevel
SkillMazeInLevel.OnStart
  -> AddModifier(Caster, SkillMaze_DanHeng_Modifier)
SkillMaze_DanHeng_Modifier.OnEnterBattle
  -> Priority=-80; ByCompareWaveCount(Equal,1)
  -> AddModifier(Caster, MAvatar_DanHeng_00_MazeSkill_AttackRatioUp)
  -> OnStack / AttackAddedRatio=0.4; battle LifeTime=3
```

`Skill100207` level1 supplies `[0.4,3]`: SkillMaze index0/hash-201412227 supplies the injected property value, index1/hash-2081277152 supplies battle lifetime, and hash2128130574 reads the working callback value. Maze lifetime `-1` and battle lifetime `3` belong to different objects. Priority and the wave comparison are authored source facts, not a locally invented gate. Their native total-order interpretation is not proven. [R5, section 10][R5]

**Current input contract.** `ScenarioSpec` owns `battle_setup`; `BattleSetupSpec` has `initial_statuses` and `initial_summons`. `InitialStatusSpec` supplies target/source IDs, canonical `effect_ref`, explicit caster/owner/parameter/current-target identities, dynamic values and metadata. There is no dedicated held-MazeBuff/Technique-possession field in these inspected types, and the inspected formal character activation does not derive a Maze acquisition event from `CharacterBuildInput`. [K4][K4] [K11][K11]

`_apply_initial_statuses` resolves the supplied effect reference, requires `AddModifier`, checks executable coverage, and calls StatusSystem with `_status_setup_binding_source`. It records both canonical effect source and scenario initial-condition provenance. Therefore **a canonical-effect-referenced setup transport exists**, but it is **not a canonical MazeBuff100201 -> CharacterSkill binding -> SkillMaze adapter**. Supplying a status directly starts downstream of the maze/ability-root edge; it is not evidence that SkillMaze.OnStart executed. No direct `.4` panel injection is an acceptable substitute.

**Ownership conclusion.** The held MazeBuff is external pre-battle world state. R5's unproved auto-import is reclassified here as an explicit unimplemented/unestablished adapter boundary, not evidence of a broken character build. No inspected contract promises automatic world-state acquisition/transport from the selected finished build. Consequently its absence is not a demonstrated production mismatch and does not trigger NEEDS_REPLAN.

**Timing conclusion.** The source requires SkillMaze startup to install the listener before OnEnterBattle. The inspected builder's equipment/trace/eidolon/passive startup families do not demonstrate automatic SkillMaze startup for this selected tuple. Explicit initial statuses are applied before the builder dispatches OnEnterBattle; if the correctly sourced listener is admitted and present then, its wave gate belongs to the battle-entry callback. This bounded endpoint neither proves actual Technique acquisition nor claims a successfully executed Technique effect.

## 9. Provider and source-proof contract audit

| Identity/value | Producer | Consumer / rejection boundary |
| --- | --- | --- |
| Owner/wearer | Formal birth activation plus selected character card | Registry requires owner UnitState and matching wearer card |
| Provider source | LC instance ID or set-threshold decision ID | Included with owner/mechanism key in provider semantic identity; conflicting payloads are rejected |
| Definition and parameter basis | Selected LC rank or qualified set threshold | RuleBook checks kind, definition, selected rank/count and exact source |
| Graph source | Canonical ability-source object | Lowerer assigns that object to graph/phase; RuleBook, registry and startup resolve the exact mechanism graph |
| Parameter read source | Canonical SkillEquip/SkillRelic read IR | Registry checks ordered read IDs, graph, type, hash, index, source and basis |
| Parameter value source | Selected canonical rank/threshold parameter | Exact value and source must match; similar values from another row are not accepted |
| Startup hashes | `_equipment_startup_spec` read/value/source bindings | `_startup_dynamic_values` resolves required configured hashes; startup retains callback-needed hashes in the installed status path |
| Installed listener ownership | Selected AddModifier effect and modifier definition | Status holds owner/caster/source, source trace and attached callback IDs; callback selection is instance-scoped |

`ability_provider_payload` preserves selection ID, owner, provider source, mechanism key, target definition, parameter basis, graph reference, exact parameter bindings and selection source. Registration is atomic, rejects malformed/duplicate/conflicting registrations and accepts identical existing payloads idempotently. It contains no callback executor. [K7][K7]

Named failures include `ability_provider_owner_unit_missing`, `wearer_identity_mismatch`, `graph_missing_partial_or_wrong_source`, `target_definition_mismatch`, `parameter_read_set_mismatch`, `parameter_binding_mismatch`, `parameter_index_out_of_range` and `parameter_value_source_mismatch`. These describe inspected guards, not newly executed negative tests. Canonical equipment graph closure also rejects missing/non-admitted gameplay callbacks rather than promoting a partially lowered graph. [K5][K5] [K7][K7]

**Proof transport nuance.** Startup passes resolved numeric values and retained hashes to StatusSystem with `binding_sources=()`. The source-bearing binding record remains in the startup trace and canonical provider registry; it is not accurate to say that the original provider binding objects are passed unchanged as StatusSystem binding sources. StatusSystem normalizes complete status-local numeric operands for evaluation. This inspected conversion alone is not evidence of a failed source contract, and no wrong-source/value acceptance or selected startup rejection was reproduced. It is not a waiver of any downstream source audit. [K4][K4] [K8][K8]

No concrete new producer/consumer mismatch was identified in the inspected selected transport contracts. No empty-evidence fixture, fixed LC/Set-ID runtime branch, altered admission rule or repaired runtime was introduced to reach that conclusion. Actual execution/source-audit outcomes remain unestablished.

## 10. Actual local setup order and rollback boundary

`ScenarioStateBuilder.build` at the inspected master orders the selected path as follows; this is code order, not the order suggested by a generic conceptual checklist. [K4][K4]

1. Expand the initial-wave specification; validate source/build identities; plan formal character births and activations before materialization.
2. Create all initial UnitStates with static pools/resources; collect their provider/startup selections; construct the BattleState and formal context.
3. Register dynamic ability providers after owner units exist.
4. Apply startup abilities, including equipment startup, and immediately dispatch the lifecycle events emitted by successful installations. A failed installation/listener result rolls that startup task back and is reported as blocked.
5. Apply explicit initial statuses, then initial summons through `_apply_battle_setup`.
6. Dispatch setup unit-create/snapshot events, then the per-unit `OnEnterBattle` setup events; complete remaining setup/integrity work.
7. Initialize the timeline with phase `birth_after_enter_battle`.

`_startup_root_tasks` distinguishes the `external_legacy` parentless-root path from formal task-graph entry queries for the explicit formal invocation roles. Do not describe the bounded startup helper as an unrestricted generic graph interpreter: the inspected loop applies admitted root `AddModifier` tasks. The selected three equipment roots have that source shape. No generic nested executor or dispatcher reconstruction is authorized by this record.

Provider registration and startup application are visibly separate calls. Initial-status installation and OnEnterBattle are also separate calls. Neither the local sorted traversal nor the source Priority=-80 is promoted to native global callback ordering. Native timer/watcher/scheduler internals remain frozen.

## 11. Existing validation search and precise E boundary

The following existing files were read at business SHA `f8e8a053ef591e1aeeb99956d46acd8390676c6f`. **That is an inspected code SHA, not a newly tested SHA.** No corresponding executed artifact with a verified tested SHA and the exact R5 selected tuple was established in this thread.

| Existing test/entry | Boundary visible in test code | What R8 may claim |
| --- | --- | --- |
| `validate_p8_s6_light_cone_dynamic_startup.run_validation` / `_startup_matrix` | Focused canonical LC bundle, exact-rank bindings, provider registration/idempotency and formal scenario registration; samples are selected structurally | Existing validator design/C only; not an executed LC20000 gameplay proof |
| `validate_p8_s15_relic_set_dynamic_startup.validate` / `_behavior_matrix` | Focused relic threshold/graph/provider/startup and conflict matrices; chosen structural sample families | Existing transport tests, not evidence that the R5 Set102+301 tuple ran |
| `validate_p8_s16_relic_set_status_condition_listener_closure.validate` / `_speed_case` | Structurally selected 4+2 speed-condition lifecycle, false/true/false checks and source-audit/replay predicates | Relevant future validation route, not a tested Set301 result at 141.632 |

Tested SHA for newly claimed R8 execution: **N/A — not run**. Test result: **not established**. Existing fixture/transport tests are not relabeled gameplay E. No transient workflow, test changes, simulator run or new test report was created. The publication checkpoint reports docs-head CI separately; skipped is not passed. [V1][V1] [V2][V2] [V3][V3]

## 12. False friends and residual B/G

LC base stats are not its passive; relic PropertyList is not Ability; repeated ParamList values are not repeated static bonuses; OnStart is not OnEnterBattle; a provider is not an executed callback; a true input comparison is not an executed conditional effect; Maze lifetime is not battle lifetime; scene-side Technique operations do not erase their battle binding; a selected build is not account acquisition; static trace properties are not trace startup abilities; callback source order is not native global order.

Retained gaps: native callback total ordering and dispatcher body; generic modifier timers and replacement timing; generic property-watch scheduling; external Maze acquisition and a canonical Maze-to-setup adapter; native static-stat arithmetic. No SPD/AV research, damage evaluator, RNG, enemy AI, servant lifecycle, family census, trace/eidolon expansion or R9 work was performed.

## 13. Claim-level A/B/C/D/E and exit accounting

A = reused pinned source-facing fact; B = named export/native boundary; C = inspected local implementation; D = bounded static source/local alignment. **No row has E.**

| Claim | A | B / external boundary | C | D | E |
| --- | --- | --- | --- | --- | --- |
| Static build contribution | R5 selected inputs closed | Native arithmetic separate | Assembly/pools | Selected static/dynamic partition aligned | Not established |
| LC20000 provider | Rank1/read/source chain closed | Native loader not recovered | Typed mechanism + registry | Canonical source/rank/read/value/owner checks aligned | Not established |
| LC20000 startup modifier | OnStart/AddModifier/OnStack closed | Native timer/order | Startup + StatusSystem + effective crit reader | Selected root/parameter/property transport aligned statically | Not established |
| Set102 static effect | 2pc ATK/4pc speed closed | Native loader/arithmetic | Threshold/static ledger | No ParamList-to-static duplication in inspected path | Not established |
| Set102 dynamic callback | Normal-hit source operand closed | Native hit total order | Startup listener + ModifyDamageData consumer | Installation/attachment/operand boundary; no real hit claimed | Not established |
| Set301 static effect | 2pc ATK closed | Native arithmetic | Static threshold contribution | Separate from child modifier | Not established |
| Set301 startup main modifier | Source root closed | Native lifecycle order | Shared startup/status machinery | Main installation/parameter ownership boundary aligned | Not established |
| Set301 speed-gated child | Gate/add/remove/property source closed | Native watcher scheduling | Predicate, status and property consumers | Gate inputs/child consequence aligned; execution not asserted | Not established |
| Technique pre-battle transport | Maze-to-CharacterSkill bridge closed | External acquisition/adapter absent from inspected contract | Explicit canonical-effect setup only | Ownership boundary closed; no automatic bridge claimed | Not established |
| Technique SkillMaze startup | Authored listener installation closed | Automatic selected SkillMaze admission not demonstrated | Downstream AddModifier/setup consumer | Source/local endpoint mapped; not an executed ability root | Not established |
| Technique OnEnterBattle effect | Priority/wave1/.4/3 source closed | Native dispatcher/timer | Setup event + admitted status callback machinery | Event/gate ownership boundary; no acquired/executed Technique claimed | Not established |
| Setup ordering | Source event kinds reused; not native total order | Native total order remains gap | Exact current builder sequence | Provider/startup/setup/entry/timeline roles separated | Not established |

The bounded exit is satisfied at the source/static consumer level: selected B0/B1/B2/B3 are separated; LC/set provider/startup contracts are mapped; Set102's two channels are not double-counted; Set301's main/gate/child are distinct; Technique's external acquisition and absent automatic adapter are not mislabeled a character-build bug; current-master ordering and fail-closed ownership checks are recorded. No demonstrated new production contract mismatch requires a runtime repair in this PR.

The broad W01/W09/W18 packages remain `active`. Their existing general checklist leaves are not promoted by these selected anchors; the worklist is intentionally unchanged. No new exact-pin lookup was needed, so PINNED_SOURCE_INDEX and SOURCE_FAMILY_INVENTORY are unchanged. Only this record and evidence README navigation are updated.

Stop at R8. Return to integration/planning for the **R9 decision**, without starting R9. A future execution claim must name its actual tested SHA, exact scenario/anchor, exercised boundary and result; none is supplied by this docs checkpoint.

## 14. Exact-head source and consumer index

R5 contains the exact pinned source-file index and corrected Technique numerics. Local links below are all pinned to the independently resolved business master, not PR #8's old runtime tree.

[R5]: https://github.com/yaelysia/hsr-battle-simulator/blob/d123ef3e710006d499446c915b5d3b20f0c7a866/docs/tbgd_evidence/shared/battle_start_build_construction_v1.md
[R3]: https://github.com/yaelysia/hsr-battle-simulator/blob/d123ef3e710006d499446c915b5d3b20f0c7a866/docs/tbgd_evidence/shared/healing_modifier_lifecycle_core_v1.md
[R0]: https://github.com/yaelysia/hsr-battle-simulator/blob/d123ef3e710006d499446c915b5d3b20f0c7a866/docs/tbgd_evidence/shared/battle_execution_language_core_v1.md
[K1]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/character_assembler.py
[K2]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/equipment_assembler.py
[K3]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/builds/relic_set_assembler.py
[K4]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/scenarios/build_state.py
[K5]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/rulebook.py
[K6]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/lowering.py
[K7]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/ability_provider.py
[K8]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status.py
[K9]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status_callbacks.py
[K10]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/unit_stats.py
[K11]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/scenarios/schema.py
[K12]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/event_dispatch.py
[K13]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/effect.py
[V1]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p8_s6_light_cone_dynamic_startup.py
[V2]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p8_s15_relic_set_dynamic_startup.py
[V3]: https://github.com/yaelysia/hsr-battle-simulator/blob/f8e8a053ef591e1aeeb99956d46acd8390676c6f/hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p8_s16_relic_set_status_condition_listener_closure.py
