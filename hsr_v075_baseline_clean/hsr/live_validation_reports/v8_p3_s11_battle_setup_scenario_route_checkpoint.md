# v8 P3-S11 battle setup / scenario route checkpoint

## 结论

P3-S11 已完成当前可执行范围。

本阶段补齐 BattleSetup、scenario route 和外部推演器入口的端到端闭环：

- executable：BattleSetup 开局生成 servant，scenario route 显式选择 servant action，经过 action availability、target admission、executor、mutation、settlement、replay 和 source audit。
- blocked：battle unit summon initial setup 当前仍是 boundary-only，blocked / process-only / state unchanged。
- blocked：route 显式选择不可用 servant hp-damage action 时 blocked / state unchanged，不自动改选。
- blocked：route 缺目标时 blocked / state unchanged，不自动补默认 target。

## 本次修改

- `scenarios/identity.py`
  - route action / source 仍在 setup 前校验。
  - 当存在 `battle_setup.initial_summons` 时，route actor / target 可延迟到 setup 后校验。
- `scenarios/build_state.py`
  - BattleSetup mutation 应用后新增 route unit-id 精确校验。
  - setup 后仍不存在的 actor / target 会报错，不能进入 executor。
- 新增 `tools/validate_p3_s11_battle_setup_scenario_route.py`
  - 覆盖 initial servant route execution、initial battle unit summon boundary、illegal summon route blocked、missing target route blocked。
  - 输出 summary / compact audit，不写完整 Canonical IR 或全量 transition dump。

## 正例

S11 主验证使用结构化谓词选择 executable servant definition 和可执行 servant action：

- selected servant definition: `servant_definition:11402`
- selected route action: `servant_skill:1140205`
- BattleSetup initial servant 产生 `UnitSpawn` 和 summon runtime mutation。
- scenario route command 由 `ScenarioStateBuilder` 生成。
- action availability 暴露同一个 route action。
- executor 执行后产生 mutation 和 settlement record。
- target resolution 选中 route 提供的 target。
- replay ok。
- source audit ok。

## 边界与负例

- battle unit summon initial setup：
  - `blocked_reason=battle_unit_summon_initial_setup_boundary_only`
  - no setup mutation
  - state unchanged
- illegal servant hp-damage route：
  - route command 保留原始非法 action，不自动改选。
  - action availability 不暴露该 action。
  - `summon_damage_stat_blocked_reason=summon_damage_stat_binding_not_admitted`
  - no mutation
  - state unchanged
  - process-only blocked record
- missing target route：
  - `blocked_reason=no_selected_target`
  - no mutation
  - state unchanged
  - 不自动补默认 target

## 剩余边界

- S11 不改变 servant damage stat admission；servant hp-damage formula executable 仍等待真实 stat binding source。
- S11 不把 `SummonUnitData` 升级为 battle runtime spawn；battle unit summon 仍保持 S4 的 boundary-only 分类。
- UI 只允许 scenario 编排和审计展示，不能提供规则事实；本阶段未改 UI。

## 验证

所有构建型验证均串行运行，输出到 `/tmp`。验证命令使用 `nice` / `ionice` 降低 CPU 和磁盘 IO 优先级；未并行运行重验证，未写完整 Canonical IR 或全量 transition dump。

```bash
python3 -B -m py_compile simulator_v8_clean_core/scenarios/identity.py simulator_v8_clean_core/scenarios/build_state.py simulator_v8_clean_core/tools/validate_p3_s11_battle_setup_scenario_route.py
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p3_s11_battle_setup_scenario_route --output-dir /tmp/hsr_v8_p3_s11_battle_setup_scenario_route
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p1_8_battle_setup --output-dir /tmp/hsr_v8_p1_8_battle_setup_s11_regression
ionice -c2 -n7 nice -n 10 python3 -B -m simulator_v8_clean_core.tools.validate_p1_9_phase1_aggregate --output-dir /tmp/hsr_v8_p1_9_phase1_aggregate_s11_regression
PYTHONPYCACHEPREFIX=/tmp/hsr_v8_pycache_s11_compile PYTHONDONTWRITEBYTECODE=1 ionice -c2 -n7 nice -n 10 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

结果：

- P3-S11 main: `ok=True`
- P1-8 battle setup regression: `ok=True`
- P1-9 phase1 aggregate regression: `ok=True phase1_minimum_battle_slice=True`
- compileall: pass
- git diff --check: pass
- repository pycache check: no `__pycache__` / `.pyc` residue after cleanup
- S11 summary resource budget: `rulebook_build_count=1`, `large_artifacts_written=false`, `full_ir_written=false`, `full_transition_dump_written=false`

未运行 v0_209、P2 全量聚合或其他无关重验证；本次直接触达 scenario identity / BattleSetup builder，按计划只跑 P1-8 和 P1-9 直接回归。P3-S12 会再做最终聚合验收。

## 下一步

进入 P3-S12：全来源闭环、聚合验收、最终报告和交接。
