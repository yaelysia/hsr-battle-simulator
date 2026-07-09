# v8 P5-S3 Dynamic / Custom Binding Projection Ready For Review

日期：2026-07-09

## 范围

本阶段只投影 dynamic/custom/hash 类来源与读取位点：

- 新增 `tools/validate_p5_s3_dynamic_custom_binding_projection.py`。
- 从当前 Canonical IR / data-card IR / source trace 扫描 dynamic definitions、read sites、consumer evidence。
- 输出 definition -> read site -> consumer ledger。
- 缺 definition、缺 read payload、错 key、缺事件上下文只验证 blocked/state unchanged。
- 不解释 hash 含义，不建立手写 hash/name 表，不迁移 runtime consumer。

## 产物

- `simulator_v8_clean_core/tools/validate_p5_s3_dynamic_custom_binding_projection.py`
- `/tmp/hsr_v8_p5_s3_dynamic_custom_binding_projection/validation_summary_p5_s3_dynamic_custom_binding_projection.json`
- `/tmp/hsr_v8_p5_s3_dynamic_custom_binding_projection/p5_s3_dynamic_custom_binding_projection_matrix.json`

## 结果

S3 主验证输出：

```text
v8 p5_s3_dynamic_custom_binding_projection ok=True rows=7 classifications={'admission_gap': 3, 'boundary_only': 1, 'executable': 3} gap_counts={'admission_gap': 16767}
```

summary：

```text
dynamic_definition_count=6286
dynamic_read_site_count=14034
custom_value_entry_count=2106
matched_definition_read_edge_count=2808
unmatched_read_site_count=13098
disallowed_gap_count=0
runtime_execution_deferred=true
```

## 关键 evidence

- `dynamic_definition_projection`：6286 条 projected definition，source trace 全部存在。
- `dynamic_read_site_projection`：14034 条 read site，覆盖 damage、toughness、status damage、action delay、queue intent。
- `definition_read_consumer_trace`：2808 条 matched definition/read/consumer edge；13098 条 unmatched read site 保留为 `admission_gap`。
- `custom_value_definition_projection`：2106 条 monster custom/dynamic/override parameter block 保留为 `admission_gap`，未提升为 executable。
- `status_callback_dynamic_read_sites`：1563 条 status/callback 动态读取缺 event payload / modifier instance / owner context，保留为 `admission_gap`。
- 负例覆盖 missing definition、wrong key、missing read payload，均 blocked 且空 mutation replay 通过。

## 验证

已运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p5_s3_dynamic_custom_binding_projection.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s3_dynamic_custom_binding_projection --output-dir /tmp/hsr_v8_p5_s3_dynamic_custom_binding_projection
rg -n "[[:blank:]]$" hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s3_dynamic_custom_binding_projection.py
```

待本阶段收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S3 是 projection/admission 阶段。`admission_gap` 不代表 lowering 失败；它表示当前已经看见 definition 或 read site，但缺少 S4/S6/S7 所需 ValueContext、event payload、modifier instance、owner/profile 或 custom binding 语义。任何 hash 都没有被解释成手写名字或默认数值。
