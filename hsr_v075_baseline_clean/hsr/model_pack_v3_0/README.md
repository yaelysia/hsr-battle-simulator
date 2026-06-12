# hsr_model_pack_v3_0

This pack restructures `hsr_model_pack_v2_8` into canonical simulator-facing data.

Key rule: external character text, Dimbreath-derived fields, route/checkpoint fields, and hand-authored aliases are normalized before entering the simulator. The battle engine consumes the canonical IR only.

Main entrypoints:

- `MANIFEST.yaml`
- `schema/hsr_model_pack_schema_v3_0.yaml`
- `rules/combat_rules_v3_0.yaml`
- `teams/seele_sparkle_tribbie_dan_heng_pt.yaml`
- `stages/arbitration_4_3_knight_3.yaml`
- `battles/arbitration_4_3_knight_3_full_combat.yaml`
- `compiled_cases/arbitration_4_3_knight_3_opening.yaml`

`legacy_sources/` is retained only for provenance and diffing. New simulator integration should use the normalized files above.
