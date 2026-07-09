# v8 P5-S2 Static Param / Level Binding Ready For Review

日期：2026-07-09

## 范围

本阶段只实现静态参数与等级缩放绑定准入：

- 新增 `rules/value_binding.py`，提供 `StaticValueBindingContext`、`StaticValueBindingResolver` 和结构化 resolution ledger。
- 新增 `tools/validate_p5_s2_static_param_level_binding.py`。
- 不修改 damage / toughness / resource runtime consumer，不声明 S5/S6 已接入。
- 不使用 S0 `missing_consumer_refs` 作为 consumer admission 证明。

## 产物

- `simulator_v8_clean_core/rules/value_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s2_static_param_level_binding.py`
- `/tmp/hsr_v8_p5_s2_static_param_level_binding/validation_summary_p5_s2_static_param_level_binding.json`
- `/tmp/hsr_v8_p5_s2_static_param_level_binding/p5_s2_static_param_level_binding_matrix.json`

## 结果

S2 主验证输出：

```text
v8 p5_s2_static_param_level_binding ok=True rows=8 classifications={'boundary_only': 1, 'executable': 7} gap_counts={}
```

summary：

```text
row_count=8
classification_counts={'boundary_only': 1, 'executable': 7}
gap_attribution_counts={}
disallowed_gap_count=0
blocked_negative_case_count=6
positive_resolution_count=10
runtime_consumer_migration_claimed=false
```

## 关键 evidence

- 角色静态参数：`SkillFormulaBindingIR.param_value`，level source 为 `skill_level`。
- 怪物静态参数：`SkillFormulaBindingIR.param_value`，level source 为 `data_card_level`。
- damage 静态参数：`DamageEmissionIR.scaling_ratio_expr` 匹配同 action/level 的 `SkillFormulaBindingIR.param_value`。
- toughness 静态值：`ActionDefinitionIR.show_stance_list[0]`，只证明静态配置可解析；dynamic hash 执行延后。
- resource 静态值：`ActionDefinitionIR.bp_need`，不使用 `ResourceRuleIR` 的 `engine_convention` 作为 TBGD 参数绑定正例。
- process-only settlement traceability 通过，空 mutation replay 通过。
- 负例覆盖缺 level、错 level、错 param index、缺 binding、list 越界、unsupported dynamic expression，均 blocked 且 state unchanged。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/rules/value_binding.py simulator_v8_clean_core/tools/validate_p5_s2_static_param_level_binding.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s2_static_param_level_binding --output-dir /tmp/hsr_v8_p5_s2_static_param_level_binding
rg -n "[[:blank:]]$" hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/value_binding.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s2_static_param_level_binding.py
```

待本阶段收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S2 没有迁移 runtime consumer。后续 S4 会把静态路径迁移到通用 `ValueResolver`，S5/S6 才能声明 damage/resource/status/callback consumer 接入。当前 `ResourceRuleIR` 里存在 `engine_convention` 行，只能作为 runtime convention 记录，不能当成 source-backed static param binding。
