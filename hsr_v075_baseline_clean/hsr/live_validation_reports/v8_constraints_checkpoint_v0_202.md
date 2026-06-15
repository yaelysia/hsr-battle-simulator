# v8 Constraints Checkpoint v0_202

## Scope

This checkpoint reduces v8 long-lived design documentation to two constraint
documents:

- `PROJECT_GOALS.md`
- `FORBIDDEN.md`

The intent is to keep project context dense and searchable. Detailed
recommendations and step-by-step implementation advice should not become
permanent top-level documentation.

## Changed

- Removed:
  - `ARCHITECTURE.md`
  - `MECHANIC_WORKFLOW.md`
  - `WORK_PLAN.md`
- Added:
  - `PROJECT_GOALS.md`
  - `FORBIDDEN.md`
- Updated README to point only to the two constraint documents.

## Policy Locked

v8 prioritizes:

```text
final product completeness > clean core > source traceability > repeatable validation > old compatibility
```

Old v7 compatibility is not a goal. v7 may be used as reference and regression
comparison only, not as a runtime dependency or API constraint.

## Validation

Commands:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

Expected:

- compileall passes.
- v0_200 validation remains `ok=true`.
- Static checks remain clean.
- Snapshot replay remains clean.

