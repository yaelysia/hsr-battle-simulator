# v8 scenarios

v8 scenarios are intentionally separate from the old compiled case format.

A scenario may hand-write battle setup and route commands, but character,
enemy, skill, status, equipment, and mechanism references must point to TBGD
IDs or Canonical IR IDs. Old model-pack records are not valid v8 rule inputs.

Minimal examples live under `examples/` and are validated by
`simulator_v8_clean_core.tools.validate_v0_204`.
