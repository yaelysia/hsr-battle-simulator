# v8 P2-S7 状态数值绑定检查点

日期：2026-07-05

## 本步完成

- 新增 `validate_p2_s7_status_numeric_bindings`。
- `status_binding_sources` 新增 `LifeTime` / `remaining_duration` binding，状态剩余时间可被公式读取。
- 验证状态层数 `Layer` 读取、剩余时间 `LifeTime` 读取、状态 dynamic value hash 读取、StackProperty modifier term 读取。
- 验证状态移除后 binding source 消失，公式读取变为 unbound，不残留旧数值。
- 建立状态数值矩阵，区分已支持 StackProperty 和 boundary-only 未支持属性。

## 关键事实

数值矩阵：

```text
status_layer_binding executable
status_lifetime_binding executable
status_dynamic_values executable source_count=6588
status_stack_property_modifiers executable source_count=2012
unsupported_stack_properties boundary_only source_count=1941
healing_energy_sp_toughness_modifiers source_absent_not_required source_count=0
```

关键断言：

```text
layer_reads_current_stacks=True
lifetime_reads_remaining_duration=True
dynamic_binding_reads_status_value=True
modifier_term_applied=True
modifier_term_total_matches=True
removed_binding_unbound=True
```

未支持 StackProperty 不默认当 0 或 1 执行；当前只通过已映射 bucket 进入 damage formula modifier term。

## 验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m simulator_v8_clean_core.tools.validate_p2_s7_status_numeric_bindings --output-dir /tmp/hsr_v8_p2_s7_status_numeric_bindings
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

关键输出：

```text
v8 p2_s7_status_numeric_bindings validation ok=True
```

## 剩余范围

- S7 完成当前 runtime 可执行的状态数值 binding 与 modifier term。
- healing / energy / SP / toughness 等未投影为当前状态 modifier mapping，后续有真实来源时再接入，不在本步合成正例。
- S8 继续覆盖 DoT / 状态伤害 / 状态触发伤害。
