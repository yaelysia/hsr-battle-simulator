# 当前验证入口

从仓库根目录使用已有 uv 环境；不创建环境、不安装新依赖。

```bash
.venv/bin/python -B -m pytest
```

默认运行现行普通回归，覆盖规则、目标、资源、状态、任务图、归档和不可变导出。
开发中可在相同命令后追加单个测试文件或 `-k` 表达式，选择受影响检查。
`integration` 标记表示完整来源编译或真实场景，显式选择：

```bash
.venv/bin/python -B -m pytest -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_pre_action_dot_defeat.py
```

替换路径可选择其它检查；省略路径会运行全部集成检查。
集成组件探查不等同于游戏操作整链，支持边界见各测试与 CLI 文档。

## 批末战斗与独立回放

使用本批受影响的已有路线，或者新增路线。以下命令生成一次归档并在独立进程回放：

```bash
export PYTHONPATH=hsr_v075_baseline_clean
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli run \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.json \
  --commands hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/examples/cli/serval_natasha_vs_antimatter.commands.json \
  --output /tmp/hsr-validation-battle.json.gz
.venv/bin/python -B -m hsr.simulator_v8_clean_core.cli replay /tmp/hsr-validation-battle.json.gz
```

输出路径必须尚不存在；保留已有证据，重跑时选择新文件名。
检查战斗结果、replay 的 ok/step_count/errors，并记录耗时与产物大小。
不为同一路线额外叠加内存回放。更多路线和限制见 [CLI_MVP.md](../CLI_MVP.md)。

三人组合检查覆盖损血、定向治疗、感电命中/未命中及三人群疗，并直接生成归档：

```bash
.venv/bin/python -B -m pytest -s -m integration \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tests/test_cli_content_scope.py -k three_character
```

末尾输出 `archive: 路径`，可直接交给上述 CLI `replay` 命令验证。

## 历史工具与现行依赖

`tests/` 是当前默认入口；`tools/validate_v0_*`、P1–P9 专项脚本保留来源与历史证据，
不自动成为当前任务的必跑套餐。CI 中既有阶段 workflow 仍保留其明确范围，
新增核心回归入口负责当前 pytest；是否运行历史 Direct 由改动风险和实际调用链决定。

以下工具仍向现行测试提供辅助构造，移动/删除前必须迁移调用者：

| 工具 | 当前引用 |
| --- | --- |
| validate_p9_s5c2_action_selection_query_submit_context | action_attack_target_context |
| validate_p9_a2_action_window_status_nested_ability_transport | direct_static_context |
| validate_p8_s2_character_build_base_panel | formal_build_param_projection |
| validate_p9_a2_p4_set_entity_visible_process_only_retirement | p4 来源准入回归 |
| validate_p9_a2_p5_process_only_settlement_barrier_retirement | p5 来源准入回归 |
| validate_p9_formal_action_graph_admission_authority | p6 来源准入回归 |
| validate_p9_s8c1b_action_entry_weighted_selection | s8c1b_materialization_regression |
| validate_p7_s13_shield_hp_routing | parallel_shield_absorption |

这些引用是测试辅助，不是 runtime 依赖。不要为归档而建立另一套 fixture 框架；
触及相关检查时再将真正共享的最小构造迁到测试目录。

