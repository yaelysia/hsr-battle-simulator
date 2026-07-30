# P8-S15 Relic Set Dynamic Startup - Ready for Review

## Status

- Status: `ready_for_review`
- Git baseline: `729fc907bc1e95106860d12076468cf10221661b`
- Checklist modified: no
- Git commit created: no
- S16/S17 implementation entered: no
- Source premise conflict: none found
- Current acceptance delta changes production behavior: no

## Validator Contraction

The S15 validator was reduced by changing its evidence design, not by moving
logic to another validation helper.

| Metric | Before | After |
|---|---:|---:|
| Total Python lines | 2482 | 857 |
| Non-empty Python lines | 2396 | 798 |
| Evidence artifacts, excluding summary | 9 | 3 |
| Focused RuleBook constructions per main run | 3 | 1 |
| Full lowering builds | 0 | 0 |

The retained matrix directly proves:

- real active threshold to parameter basis, mechanism ref, graph, parameter
  bindings, ability source, and `IRSource`;
- active/inactive, lower/higher threshold, outer 2+2, and multiple-wearer
  provider behavior;
- common provider startup order and registration idempotence;
- partial graph, forged source, and missing parameter fail-closed behavior;
- duplicate definition and physical-row source conflicts;
- canonical result ordering plus constructor/codec duplicate rejection;
- the exact S16/S17 blocker ledger.

Removed or inherited evidence:

- payload-class census and static-channel replay were removed; P8-S14 owns
  static ledger acceptance;
- independent raw path/fingerprint walkback was removed; P8-S9 owns physical
  raw truth;
- replacement-loss and threshold-decision replay were removed; P8-S13 owns
  active-threshold selection;
- forged mechanism, forged graph, wearer mismatch, and other S6 contract
  replays were removed; the S15 matrix retains only the source and parameter
  failures introduced by this chain;
- separate registration, startup, runtime, source-walkback, negative, and
  result artifacts were merged into one behavior matrix and one conflict
  matrix;
- manual catalog-wide chain reconstruction was replaced by the production
  `RuleBook.equipment_dynamic_parameter_context()` query on a real assembled
  selection;
- duplicate negative RuleBook variants were removed. The sole formal
  RuleBook contains the duplicate definition and is also used by all positive
  and negative provider cases.

## Production Call Chain

1. `build_relic_catalog()` supplies the P8-S9 accepted threshold, ordered
   parameters, ability source, and `IRSource`.
2. `_admitted_equipment_ability_definitions()` groups declarations by
   physical `(source_path, record_index)`. Identical declarations merge;
   definition, ability identity, or source conflicts block the whole row.
3. `TBGDLowering.build()` and `_equipment_ability_source_projection()` use
   that same admission boundary, so neither path can last-write-win.
4. `_lower_equipment_ability_graphs()` lowers only admitted rows and emits
   the common graph and equipment parameter-read channels.
5. `_attach_equipment_mechanism_refs()` preserves input entries and order.
   Duplicate definition identities reach RuleBook and resolve as
   `equipment_definition_ambiguous`.
6. `assemble_relic_set_activations()` remains the P8-S13 decision producer.
   `_active_relic_dynamic_mechanisms()` consumes only active decisions and
   calls the shared `_active_dynamic_mechanism()`.
7. `RuleBook.equipment_dynamic_parameter_context()` resolves both light-cone
   rank and relic-threshold bases. `ValueResolver` performs the common exact
   value/source binding.
8. `EquipmentAssemblyResult` canonically sorts dynamic selections and rejects
   duplicate `selection_id` or equivalent provider semantics.
9. `ScenarioStateBuilder` creates formal state, calls the single
   `register_dynamic_ability_providers()` registry, creates the common
   `_equipment_startup_spec()`, and then dispatches startup effects.

The runtime-boundary profiler observed one provider call and one startup-spec
call. That profiled segment entered neither `tbgd` nor
`builds.relic_set_assembler`; mutation source was
`ability_provider_registry` and record type was
`ability_provider_registration`. Absence of a relic-specific event loop is
not an automated predicate and remains reviewer code inspection of
`systems/ability_provider.py` and `scenarios/build_state.py`.

## Automated Predicates

The replacement final summary records all 15 top-level predicates and
aggregate `ok` as `true`:

```text
active_inactive_threshold_selection
canonical_threshold_graph_parameter_source_chain
duplicate_definition_preserved_and_fail_closed
dynamic_result_duplicate_id_and_semantics_rejected
dynamic_result_order_canonical
forged_source_and_missing_parameter_block_atomically
identical_physical_source_lowered_once
low_high_threshold_providers_distinct
multi_wearer_providers_isolated
partial_graph_blocks_startup
physical_source_conflict_order_invariant
runtime_consumes_common_selection_and_canonical_ir
s16_s17_blocker_ledger_exact
startup_order_and_idempotence
two_plus_two_providers_distinct
ok
```

The conflict artifact records:

- duplicate definition key `relic_set_threshold::101:4` remains ambiguous and
  cannot produce a dynamic selection;
- conflicting declarations for
  `Config/ConfigAbility/Equip/RelicAbility.json` record 6 produce zero rows in
  all eight lowering channels in both input orders;
- an identical physical-row declaration projects and lowers once;
- reversed dynamic selections produce canonical fingerprint
  `813954f60214eeb40a9136a6946d3946380fc635acc9d7dc38b74e7620a0387d`;
- constructor and codec both reject duplicate selection identity and
  equivalent provider semantics.

Provider negatives are atomic with unchanged state and no mutation:

- forged source:
  `ability_provider_graph_missing_partial_or_wrong_source`;
- missing parameter:
  `ability_provider_parameter_read_set_mismatch`;
- partial graph: equipment battle admission is blocked, no dynamic selection
  is exposed, and formal scenario startup returns no battle state.

## Source Inheritance Boundary

- P8-S9 owns physical raw row, path, fingerprint, ordered parameter, and
  ability-source authenticity.
- P8-S15 performs no independent raw oracle scan.
- P8-S15 proves the new
  `provider -> threshold/parameter basis -> mechanism ref -> graph/parameter
  binding -> IRSource` chain and runtime consumption of that Canonical chain.
- The chain's internal agreement is not reported as a second validation of
  all raw data.

## S16/S17 Blocker Ledger

All 25 blocked graphs are accounted for: 17
`equipment_ability_callback_graph_partial` and 8
`equipment_ability_nested_modifier_graph_unclassified`. There are 102
blocking dependency occurrences. Stage totals overlap by threshold:
`s7=33/19`, `s8=14/10`, and `unknown=55/8`, where each pair is
`dependency occurrences / affected thresholds`.

| Stage | Kind | Family | Reason | Dependencies | Thresholds | Exact threshold keys |
|---|---|---|---|---:|---:|---|
| s7 | condition | `ByAnd` | `condition_not_executable:audit_only:ByAnd` | 1 | 1 | `relic_set_threshold::126:4` |
| s7 | condition | `ByCompareAbilityProperty` | `condition_not_executable:unsupported:ByCompareAbilityProperty` | 31 | 17 | `relic_set_threshold::124:4`, `relic_set_threshold::130:4`, `relic_set_threshold::301:2`, `relic_set_threshold::302:2`, `relic_set_threshold::303:2`, `relic_set_threshold::304:2`, `relic_set_threshold::305:2`, `relic_set_threshold::306:2`, `relic_set_threshold::307:2`, `relic_set_threshold::308:2`, `relic_set_threshold::309:2`, `relic_set_threshold::310:2`, `relic_set_threshold::311:2`, `relic_set_threshold::319:2`, `relic_set_threshold::320:2`, `relic_set_threshold::322:2`, `relic_set_threshold::325:2` |
| s7 | condition | `ByContainBehaviorFlag` | `condition_not_executable:unsupported:ByContainBehaviorFlag` | 1 | 1 | `relic_set_threshold::132:4` |
| s8 | event | `OnBeforeHitAll` | `equipment_event_family_deferred_to_p8_s8` | 1 | 1 | `relic_set_threshold::132:4` |
| s8 | event | `OnEnterBattle` | `equipment_event_family_deferred_to_p8_s8` | 4 | 4 | `relic_set_threshold::302:2`, `relic_set_threshold::305:2`, `relic_set_threshold::308:2`, `relic_set_threshold::310:2` |
| s8 | event | `OnListenBeforeSkillUse` | `equipment_event_family_deferred_to_p8_s8` | 1 | 1 | `relic_set_threshold::126:4` |
| s8 | event | `OnListenCharacterCreate` | `equipment_event_family_deferred_to_p8_s8` | 4 | 4 | `relic_set_threshold::302:2`, `relic_set_threshold::310:2`, `relic_set_threshold::319:2`, `relic_set_threshold::320:2` |
| s8 | event | `OnPhase2` | `equipment_event_family_deferred_to_p8_s8` | 1 | 1 | `relic_set_threshold::303:2` |
| s8 | event | `OnStack` | `equipment_event_family_deferred_to_p8_s8` | 3 | 3 | `relic_set_threshold::124:4`, `relic_set_threshold::319:2`, `relic_set_threshold::320:2` |
| unknown | condition | `ByCompareDamageTag` | `condition_not_executable:blocked:ByCompareDamageTag` | 1 | 1 | `relic_set_threshold::119:4` |
| unknown | event | `OnAfterAttackEnd` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::132:4` |
| unknown | event | `OnAfterAttackEnd` | `event_source_missing:OnAfterAttackEnd` | 1 | 1 | `relic_set_threshold::132:4` |
| unknown | event | `OnBeforeHitAll` | `equipment_event_family_unclassified` | 2 | 2 | `relic_set_threshold::116:4`, `relic_set_threshold::119:4` |
| unknown | event | `OnListenAfterSkillUse` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::303:2` |
| unknown | event | `OnListenAfterSkillUse` | `event_source_missing:OnListenAfterSkillUse` | 2 | 1 | `relic_set_threshold::303:2` |
| unknown | event | `OnListenBattleEventCreate` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::318:2` |
| unknown | event | `OnListenBattleEventCreate` | `event_source_missing:OnListenBattleEventCreate` | 4 | 1 | `relic_set_threshold::318:2` |
| unknown | event | `OnListenDepartedEnd` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::321:2` |
| unknown | event | `OnListenDepartedEnd` | `event_source_missing:OnListenDepartedEnd` | 18 | 1 | `relic_set_threshold::321:2` |
| unknown | event | `OnListenDepartedStart` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::321:2` |
| unknown | event | `OnListenDepartedStart` | `event_source_missing:OnListenDepartedStart` | 18 | 1 | `relic_set_threshold::321:2` |
| unknown | event | `OnModifierOnStack` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::128:4` |
| unknown | event | `OnStack` | `equipment_event_family_unclassified` | 1 | 1 | `relic_set_threshold::129:4` |
| unknown | task | `DIHCJLDIMNA` | `equipment_task_family_unclassified` | 1 | 1 | `relic_set_threshold::129:4` |
| unknown | task | `SetDynamicValueByBehaviorFlagCount` | `equipment_task_family_unclassified` | 1 | 1 | `relic_set_threshold::116:4` |

Both ledger checks are true: every blocked graph is accounted for, and no
listed S16/S17 family was partially executed.

## Validation Runs And Resources

Before this contraction delta, the S15 report recorded three main
invocations over the implementation lifetime. This delta added:

1. One source-projection slice with no RuleBook, used only to confirm that the
   focused files require three generic event-family support rows.
2. One in-memory focused matrix slice with one RuleBook; all retained
   predicates passed.
3. One main invocation that exited 1 because code review temporarily added
   the incorrect requirement that a blocked provider emit no audit record.
   Production state remained unchanged and mutation-free; all other
   predicates were true. The assertion was removed. Its `/usr/bin/time`
   file and output directory were subsequently replaced by the explicitly
   authorized replacement run, so no separate peak-RSS artifact is retained.
4. One explicitly authorized replacement final invocation; it exited 0.

Thus the implementation-lifetime S15 main count is five. The contraction
delta contains one failed main and one authorized replacement final. No S6
direct was run because this delta did not change the shared production
provider contract.

Replacement final command:

```text
PYTHONDONTWRITEBYTECODE=1 /usr/bin/time -v -o /tmp/hsr_v8_p8_s15_compact_time_v.txt timeout --signal=TERM 8m ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p8_s15_relic_set_dynamic_startup --tbgd-root ../../turnbasedgamedata-main --output-dir /tmp/hsr_v8_p8_s15_relic_set_dynamic_startup_compact
```

Replacement final resources:

- exit status: 0;
- external wall clock: 2.69 seconds;
- peak RSS: 351092 KiB;
- focused RuleBook constructions: 1;
- full lowering builds: 0;
- full relic transitions: 0;
- serialized full Canonical IR/RuleBook: no;
- evidence files: 4 including summary;
- output directory size: 42571 bytes, below 5 MiB.

Final static checks:

- validator count: 857 total lines and 798 non-empty lines;
- targeted `py_compile`: exit 0;
- `python3 -m compileall -q simulator_v8_clean_core`, with pycache redirected
  to `/tmp`: exit 0;
- `git diff --check`: exit 0;
- trailing-whitespace audit for the untracked validator and report: exit 0;
- HEAD remained `729fc907bc1e95106860d12076468cf10221661b`.

## Evidence Paths

- `/tmp/hsr_v8_p8_s15_relic_set_dynamic_startup_compact/behavior_matrix_p8_s15.json`
- `/tmp/hsr_v8_p8_s15_relic_set_dynamic_startup_compact/conflict_matrix_p8_s15.json`
- `/tmp/hsr_v8_p8_s15_relic_set_dynamic_startup_compact/s16_s17_family_blocker_ledger_p8_s15.json`
- `/tmp/hsr_v8_p8_s15_relic_set_dynamic_startup_compact/validation_summary_p8_s15_relic_set_dynamic_startup.json`
- `/tmp/hsr_v8_p8_s15_compact_time_v.txt`

## Contraction Delta Files

- `simulator_v8_clean_core/tools/validate_p8_s15_relic_set_dynamic_startup.py`
- `live_validation_reports/P8-S15_RELIC_SET_DYNAMIC_STARTUP_ready_for_review.md`

Production files were not changed by the contraction delta.

## Not Run

- P8-S6 direct or any other historical S1/S4/S8/R2/S14 validator;
- S13 aggregate or full relic-set transition matrix;
- complete `TBGDLowering.build()` or full Canonical IR construction;
- P7 direct, P7 aggregate, old nine-family aggregate, or 209 suite;
- full Canonical IR, RuleBook, coverage, fidelity, or transition dumps;
- any S16/S17 gameplay-family implementation or execution.

The pre-existing modification to `ARCHITECTURE_BOUNDARY_CONTRACT.md` and the
two unrelated UI drafts were preserved and are not part of P8-S15.
