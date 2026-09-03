# P9-S8C1A_WEIGHTED_SELECTION_IR — ready_for_review

Status: `ready_for_review`

PR: #1 (`exec/p9-s8c1a-weighted-selection-ir`)

## Actual diff

Task implementation remains limited to:

- `simulator_v8_clean_core/rules/task_graph.py`
  - adds `TaskGraphWeightedChoiceIR` and `TaskGraphWeightedSelectionIR`;
  - adds `task_graph_weighted_choice_id` and `task_graph_weighted_selection_id`;
  - closes stable identity, parent/child source lineage, numeric-definition pairing, JSON isolation and strict codec validation.
- `simulator_v8_clean_core/rules/__init__.py`
  - exports the weighted-selection IR contract only.
- `simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py`
  - single `validation_fixture` validator for this card;
  - covers legal round trip, equal-weight positional identity, pairing mismatch, wrong parent path, forged identity, strict codec rejection, and mutable-container isolation.

Validation-environment CI is an execution-layer self-rescue only. It adds no Python dependency and does not alter business IR or deferred scope:

- `.github/workflows/p9-s8c1a-pr1-fast.yml`
  - only executes for PR #1 with head branch `exec/p9-s8c1a-weighted-selection-ir`;
  - checks out `github.event.pull_request.head.sha` with `fetch-depth: 0`;
  - retains the task-card compileall and focused validator commands;
  - checks the committed PR diff from the fixed base to the triggering PR head, rather than an empty clean working tree.

This report is the only ready-for-review evidence file for the card.

## Validation evidence — CI-2

Fixed base: `f7ca8b02d670a574e09066c874ede61eebf8bc27`

Validated PR head: `7dce55024f6ff64229fae09b71b8561df6ae1fd1`

GitHub Actions run: `33730334606`

Job: `p9-s8c1a-fast` — `success`

The runner explicitly checked out PR head `7dce55024f6ff64229fae09b71b8561df6ae1fd1` before validation.

### compileall

Command:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py
```

Result: exit 0; no output.

### focused validator

Command:

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir
```

Raw result:

```json
{"cases": 7, "elapsed_seconds": 0.010194, "fixture_kind": "validation_fixture", "ok": true, "peak_memory_bytes": 31249}
```

Budget check:

- focused validator elapsed: `0.010194s` <= `2s` target and < `10s` hard stop;
- peak traced memory: `31,249 bytes` < `128 MiB`.

### committed PR diff check

Command as expanded by the CI run:

```bash
git diff --check f7ca8b02d670a574e09066c874ede61eebf8bc27 "7dce55024f6ff64229fae09b71b8561df6ae1fd1"
```

Result: exit 0; no output.

This checks the committed diff between the fixed PR base and the triggering PR head. It does not rely on a dirty working tree and does not use a merge commit or floating base ref.

CI-2 required one workflow-only remediation for the acceptance finding; no business-code repair was required.

## Deferred

Exactly deferred to later cards:

- `S8C1B`: materializer attachment and proof of real branch existence/kind.
- `S8C1C`: real source entrances and complete source denominator.

Not claimed by S8C1A: TBGD parsing, RandomConfig/OddsList lowering, materializer behavior, TaskGraphNodeIR/TaskGraphIR integration, RNG execution, dynamic weight evaluation, runtime execution, or complete-source coverage.
