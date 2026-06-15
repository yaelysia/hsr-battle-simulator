# v8 tests

The first v8 checkpoint uses stdlib validation tools instead of adding a new
test dependency. Use:

```bash
python3 -m simulator_v8_clean_core.tools.validate_v0_200 --output-dir validation_outputs_v0_200
```

Future tests should keep checking:

- TBGD coverage generation.
- Canonical IR generation.
- Snapshot replay from explicit mutations.
- Static isolation from legacy simulator runtime.

