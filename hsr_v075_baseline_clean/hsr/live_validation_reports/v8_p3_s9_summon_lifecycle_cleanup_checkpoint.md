# v8 P3-S9 summon lifecycle cleanup checkpoint

## 结论

P3-S9 已完成当前可执行范围。

本阶段补齐了 summon / servant remove 的同步清理闭环：

- servant 显式 remove：真实 lifecycle remove admission -> status cleanup -> queue cleanup -> turn owner cleanup -> `UnitRemove` -> summon runtime removed audit。
- owner cleanup：真实 servant lifecycle source -> `UnitRemove` -> summon runtime removed audit。
- 缺 remove source 或尝试复用 spawn source：blocked、process-only、state unchanged。
- wave clear policy：当前真实 summoned monster `wave_clear_policy=counts`，会阻塞 wave clear；`ignore` policy 分支允许 wave transition，且不把 ignored summon 当作当前 wave remove unit。

## 本次修改

- `systems/summon.py`
  - `plan_remove` 携带 summon / servant intent id，便于 source audit 反查 IR。
  - `plan_owner_cleanup` 保留 owner death policy source、remove admissions 和单一 servant definition id。
  - `apply_remove` 在 lifecycle remove 前清理 removed summon 的 statuses、`status_details`、queue entries、`turn_owner_id`。
  - summon runtime remove 会把 removed unit 从 `by_owner`、`by_unique_group`、`last_summon_monsters`、`last_servants` 中剪掉，同时保留 `entities` / `servants` 的 removed audit entry。
- `core/source_audit.py`
  - 增加 `summon_system` mutation source policy。
  - 对 summon spawn / remove / owner cleanup / cleanup mutation 通过 `SummonMonsterIntentIR` 或 `ServantDefinitionIR` 做 source audit。
  - remove path 额外检查 remove admission，避免 spawn source 冒充 remove source。
- 新增 `tools/validate_p3_s9_summon_lifecycle_cleanup.py`
  - 输出 summary / matrix / compact audit，不写完整 Canonical IR 或全量 transition dump。

## 正例

S9 主验证使用结构化谓词选择 executable servant definition 和 executable summon monster intent：

- 显式 remove 正例：
  - `plan.operation=remove_summon`
  - `plan.intent_id` 指向真实 `ServantDefinitionIR`
  - 产生 status cleanup、status detail cleanup、queue cleanup、turn owner cleanup、`UnitRemove`、removed record、summon runtime mutation
  - replay ok，source audit ok
  - 移除后 `CasterServant` / `ServantEntityList` 不再返回 removed servant
  - 移除后 pending queue 不再引用 removed servant
- owner cleanup 正例：
  - `plan.operation=owner_removed_cleanup`
  - source 来自 servant lifecycle owner death remove policy
  - 产生 `UnitRemove` 与 runtime removed audit
  - replay ok，source audit ok
- wave policy 正例：
  - 当前真实 summoned monster policy 为 `counts`
  - active enemy summon blocked reason 为 `active_enemy_summon_blocks_wave_clear`

## 负例

全部 blocked 或不产生无来源 mutation：

- 使用 spawn source 但缺 remove admission -> `summon_remove_source_not_admitted`
- blocked result 无 mutations
- blocked record 为 process-only
- state unchanged

## 剩余边界

- expire、summoned monster death、owner 离场、setup reset 尚未扩成独立 executable 正例。
- 当前完成口径是 S9 底座可验收：已有真实来源的 remove / owner cleanup 可执行；缺 remove source 不假执行；wave clear policy 由 runtime policy 决定。
- 后续如果 lowering 暴露更细的 expire / death / setup reset source，需要继续按本阶段的 source audit / replay / negative 口径补正例。

## 验证

所有验证均串行运行，输出到 `/tmp`。构建型验证用 `nice` / `ionice` 限低 CPU 和磁盘 IO 优先级；未并行运行重验证，未写完整 Canonical IR 或全量 transition dump。

```bash
python3 -B -c "import py_compile; files=['simulator_v8_clean_core/systems/summon.py','simulator_v8_clean_core/core/source_audit.py','simulator_v8_clean_core/tools/validate_p3_s9_summon_lifecycle_cleanup.py']; [py_compile.compile(path, cfile=f'/tmp/hsr_v8_compile_{index}.pyc', doraise=True) for index, path in enumerate(files)]"
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s9_summon_lifecycle_cleanup --output-dir /tmp/hsr_v8_p3_s9_lifecycle_cleanup
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s5_servant_lifecycle --output-dir /tmp/hsr_v8_p3_s5_servant_lifecycle_s9_regression
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s8_summon_target_relations --output-dir /tmp/hsr_v8_p3_s8_target_relations_s9_regression
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p1_3_summon_assistant_servant --output-dir /tmp/hsr_v8_p1_3_summon_s9_regression
ionice -c2 -n7 nice -n 10 python3 -B -m compileall -q simulator_v8_clean_core
git diff --check
```

结果：

- P3-S9 main: `ok=True`
- P3-S5 servant lifecycle regression: `ok=True`
- P3-S8 summon target relations regression: `ok=True`
- P1-3 summon / assistant / servant regression: `ok=True`
- compileall: pass
- git diff --check: pass

未运行全量 P1 aggregate / P2 full status / v0_209 等重验证；本次未改 shared damage、status lifecycle reducer、TBGD full artifact 输出或 P1 aggregate contract，全量验证留到 P3-S12 或用户明确要求时串行执行。

## 下一步

进入 P3-S10：状态、资源、伤害、击杀归因与召唤物联动。
