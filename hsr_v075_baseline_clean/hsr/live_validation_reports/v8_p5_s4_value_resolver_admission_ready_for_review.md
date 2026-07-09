# v8 P5-S4 ValueResolver Admission Ready For Review

日期：2026-07-09

## 范围

本阶段建立通用求值入口：

- 在 `rules/value_binding.py` 新增 `ValueContext`、`ValueBindingRequest`、`ValueResolution`、`ValueResolver`。
- `ValueResolver` 支持 `skill_formula_param`、`action_definition_numeric_field`、`action_definition_list_item`、`fixed_numeric_expression`、`dynamic_hash`。
- S2 静态参数路径已迁移到 `ValueResolver` 统一入口。
- unknown binding kind、缺 context key、缺 dynamic source 均 blocked。
- 不迁移 damage/resource/status/callback runtime consumer。

## 产物

- `simulator_v8_clean_core/rules/value_binding.py`
- `simulator_v8_clean_core/tools/validate_p5_s4_value_resolver_admission.py`
- `/tmp/hsr_v8_p5_s4_value_resolver_admission/validation_summary_p5_s4_value_resolver_admission.json`
- `/tmp/hsr_v8_p5_s4_value_resolver_admission/p5_s4_value_resolver_admission_matrix.json`

## 结果

S4 主验证输出：

```text
v8 p5_s4_value_resolver_admission ok=True rows=7 classifications={'boundary_only': 1, 'executable': 6} gap_counts={}
```

summary：

```text
supported_binding_kinds=[
  'action_definition_list_item',
  'action_definition_numeric_field',
  'dynamic_hash',
  'fixed_numeric_expression',
  'skill_formula_param'
]
context_key_count=11
positive_resolution_count=12
disallowed_gap_count=0
runtime_consumer_migration_claimed=false
```

## 关键 evidence

- `value_context_contract`：actor、target、owner、summoner、action、hit、status/modifier、event payload、combatant profile、data-card source、dynamic value source 均可进入 context trace。
- `s2_static_path_migrated_to_value_resolver`：`skill_formula_param` 通过 `ValueResolver` 返回 `SkillFormulaBindingIR.param_value=0.5`，保留 source/context trace。
- `dynamic_hash_value_resolver_admission`：使用真实 read-site hash `1659254037`；显式 `dynamic_values` 绑定成功，unbound 分支返回 `dynamic_hash_unbound:1659254037`。
- `context_missing_negative_cases`：actor、target、owner、event payload、combatant profile、data-card source 缺失均 blocked，空 mutation replay 通过。
- `unknown_binding_kind_blocked`：unknown kind 不会跳过后继续 executable。
- `resolution_ledger_source_context_trace`：process-only settlement traceability 和空 mutation replay 均通过。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/rules/value_binding.py simulator_v8_clean_core/tools/validate_p5_s4_value_resolver_admission.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s4_value_resolver_admission --output-dir /tmp/hsr_v8_p5_s4_value_resolver_admission
rg -n "[[:blank:]]$" hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/value_binding.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s4_value_resolver_admission.py
```

待本阶段收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S4 只建立 admission 和统一 resolution ledger。damage、toughness、resource、status numeric、callback queue 的业务 consumer 仍未迁移；这些工作归 S5/S6。当前 dynamic hash 正例只证明有显式 runtime context 值时可解析，不把 hash 硬映射成含义或默认值。
