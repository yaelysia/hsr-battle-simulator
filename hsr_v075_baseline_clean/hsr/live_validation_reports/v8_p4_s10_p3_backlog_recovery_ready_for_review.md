# v8 P4-S10 P3 backlog recovery ready_for_review

## Scope

P4-S10 covers the P3 inherited summon backlog only. It does not clear all P3 summon gaps and does not implement the P4-S12 aggregate gate.

Execution policy:

- Rebuild current P3 stage matrices in memory from current TBGD lowering and RuleBook.
- Project every P3 inherited gap row into a P4 backlog row.
- Split the backlog into actionable dimensions instead of using broad executable positives to hide gaps.
- Keep AssistantAvatar as a separate `out_of_scope` row.
- Write summary/matrix artifacts only; no full Canonical IR or transition dump.

## New Validation

Added:

```text
simulator_v8_clean_core/tools/validate_p4_s10_p3_backlog_recovery.py
```

Output:

```text
/tmp/hsr_v8_p4_s10_current/validation_summary_p4_s10_p3_backlog_recovery.json
/tmp/hsr_v8_p4_s10_current/p4_s10_p3_backlog_recovery_matrix.json
```

Result:

```text
ok=True
row_count=14
classification_counts={'admission_gap': 8, 'executable': 3, 'out_of_scope': 1, 'source_gap_blocked': 2}
inherited_gap_count=2150
inherited_projection_row_count=3
inherited_row_count=3
disallowed_inherited_gap_count=0
unclassified_count=0
allowed_gap_evidence_ok=True
assistant_avatar_scope_excluded=True
p3_stage_results_ok=True
```

## Inherited Gap Projection

All current P3 inherited rows are projected:

```text
domain:summon_target_expression:gap_attribution:admission_gap = 342
domain:summoned_monster_intent:gap_attribution:admission_gap = 1781
domain:summoned_monster_intent:gap_attribution:source_gap_blocked = 27
```

No inherited `implementation_missing`, `lowering_gap`, `validation_gap`, or `unclassified` gap remains.

## Backlog Dimensions

S10 split the retained backlog into explicit work packages:

```text
target_alias = 320
TargetQuery = 22
custom_value_hash = 1163
dynamic_monster_id = 632
level_policy_monster_id_unresolved = 1787
location_type = 398
profile_card_source = 64
```

These are token/dimension counts, not replacements for the P3 inherited gap count. A single blocked intent or entry can carry multiple blocker tokens, so token totals intentionally exceed the inherited row counts.

## AssistantAvatar Scope

AssistantAvatar remains separate:

```text
assistant_avatar_ability_config classification=out_of_scope
follow_up_owner=future AssistantAvatar / avatar assistant ability queue work
```

It is not counted as summon target or summoned monster intent backlog.

## Regression

Commands run serially with low priority:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p4_s10_p3_backlog_recovery.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p4_s10_p3_backlog_recovery --output-dir /tmp/hsr_v8_p4_s10_current
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p3_summon_assistant_servant_complete --output-dir /tmp/hsr_v8_p3_after_p4_s10
```

P3 aggregate regression:

```text
ok=True
validation_gate_ok=True
p3_summon_foundation_closed=True
p3_summon_phase_complete=True
p3_summon_all_executable_complete=False
p3_summon_sources_classified=True
gap_counts={'admission_gap': 2123, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 27, 'unclassified': 0, 'validation_gap': 0}
```

## Current Position

P4-S10 is ready for review. The stage does not mark P3 backlog as solved; it makes the remaining admission/source gaps visible, attributable, and owned by follow-up work packages.

Minimum battle slice status is unchanged: P1/P2/P3 substrate remains available; the remaining gaps are outside the already validated P3 foundation closure and still short of full game replication.
