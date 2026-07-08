# v8 P3-S8 summon / servant target relations checkpoint（AssistantAvatar out_of_scope）

## 结论

P3-S8 已完成当前可执行范围。

召唤相关 target alias / operation 矩阵无 unclassified：

- executable: 7
- lowering_gap: 0

`CasterServant`、`CasterSummonedMinions`、`LastSummonMonsters`、`ServantEntityList`、`GetServant`、`GetSummoner`、`RemoveServant` 均有 source-backed executable 正例。`FriendServantSelect` / AssistantAvatar 已确认不属于 P3 summon/servant target acceptance，分类为 `out_of_scope`，不再作为 P3 lowering/admission gap。

## 本次修改

- `systems/target.py`
  - 为 summon runtime target relation 增加 `targetability.targetable` gate。
  - `LastSummonMonsters`、`CasterSummonedMinions`、`ServantEntityList`、`CasterServant`、`GetServant`、`GetSummoner` 会在 runtime entity source trace、removed status、targetability、unit lifecycle 缺失时 blocked。
- `tbgd/lowering.py`
  - AssistantAvatar / `FriendServantSelect` 不进入 P3 target gap 矩阵，只保留 scope-exclusion boundary 证据。
- 新增 `validate_p3_s8_summon_target_relations`，覆盖 source matrix、正例、负例和 AssistantAvatar target boundary。

## 正例

S8 主验证使用真实 spawned servant + summoned monster runtime state：

- owner fetch: `TargetFetchModifierOwner` -> `ally:servant_owner`
- last summon: `LastSummonMonsters` -> spawned summoned monster
- caster summoned minions: `CasterSummonedMinions` -> spawned summoned monster
- servant list: `ServantEntityList` -> spawned servant
- caster servant: `CasterServant` -> spawned servant
- servant operation: `AllLightTeam.GetServant` -> spawned servant
- summoner operation: `ServantEntityList.GetSummoner` -> owner
- remove servant operation: `AllLightTeam.RemoveServant` -> non-servant light-team units only

## 负例

全部 blocked 且 state unchanged：

- missing runtime -> `summon_runtime_missing`
- flag-only servant without runtime -> `summon_runtime_missing`
- wrong owner with default registry present -> `target_map_servant_empty`
- removed servant -> `unit_removed`
- runtime targetability false -> `summon_runtime_entity_not_targetable`
- missing runtime source trace -> `summon_runtime_entity_source_trace_missing`
- unsupported target operation -> `target_alias_not_admitted:AllLightTeam.UnsupportedSummonOperation`

## 验证

所有验证均串行运行，输出到 `/tmp`，未写完整 Canonical IR 或全量 transition dump。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/systems/target.py simulator_v8_clean_core/tbgd/lowering.py simulator_v8_clean_core/tools/validate_p3_s8_summon_target_relations.py
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations --output-dir /tmp/hsr_v8_p3_s8_summon_target_relations
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_6_target_system --output-dir /tmp/hsr_v8_p1_6_target_system_p3_s8_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s2_summon_runtime_schema --output-dir /tmp/hsr_v8_p3_s2_summon_runtime_schema_p3_s8_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p3_s3_summoned_monster_spawn --output-dir /tmp/hsr_v8_p3_s3_summoned_monster_spawn_p3_s8_regression
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_assistant_servant_p3_s8_regression
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations --output-dir /tmp/hsr_v8_p3_s8_truthful_recheck2
```

结果：

- P3-S8 main: `ok=True`
- P3-S8 scope-exclusion recheck: `ok=True`，`classification_counts={'executable': 7}`，`assistant_boundary_classification='out_of_scope'`
- P1-6 target system regression: `ok=True`
- P3-S2 summon runtime schema regression: `ok=True`
- P3-S3 summoned monster spawn regression: `ok=True`
- P1-3 summon / assistant / servant regression: `ok=True`

## 下一步

进入 P3-S9：移除、过期、owner cleanup、死亡、波次切换和清场。
