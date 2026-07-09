# v8 P5-S6 Resource / Status / Callback Consumers Ready For Review

日期：2026-07-09

## 范围

本阶段把第二批 runtime consumer 接入 `ValueResolver`：

- action resource plan 的 `bp_need`、`bp_add`、`sp_base` 改为通过 `action_definition_numeric_field` resolution 生成。
- 状态 duration / stack / chance admission 增加 `runtime_numeric_expression` value resolution ledger，不改变原生命周期判定。
- callback queue enqueue 的 priority value 改为通过 `runtime_numeric_expression` resolution 后写入 queue entry、mutation metadata 和 settlement payload。
- 缺 context 的 resolver 负例保持 state unchanged。

## 产物

- `simulator_v8_clean_core/rules/value_binding.py`
- `simulator_v8_clean_core/core/executor.py`
- `simulator_v8_clean_core/systems/status.py`
- `simulator_v8_clean_core/systems/status_callbacks.py`
- `simulator_v8_clean_core/tools/validate_p5_s6_resource_status_callback_consumers.py`
- `/tmp/hsr_v8_p5_s6_resource_status_callback_consumers/validation_summary_p5_s6_resource_status_callback_consumers.json`
- `/tmp/hsr_v8_p5_s6_resource_status_callback_consumers/p5_s6_resource_status_callback_consumers_matrix.json`

## 结果

S6 主验证输出：

```text
v8 p5_s6_resource_status_callback_consumers ok=True rows=5 classifications={'executable': 5} gap_counts={}
```

summary：

```text
row_count=5
classification_counts={'executable': 5}
resource_value_resolution_count=3
status_value_resolution_count=28
queue_value_resolution_count=1
disallowed_gap_count=0
```

runtime samples：

```text
resource: action_id=avatar_skill:140104, action_level=15, resource_mutation_count=1
status: effect_id=effect:Config/ConfigAbility/Activity/Activity_FateMonster_Ability.json:..., mutation_count=2
queue: queue_kind=turn_insert_ability, mutation_count=1
```

## 关键 evidence

- `resource_consumer_value_resolver`：resource mutation metadata 含 `resource_value_resolutions`，`bp_need` / `bp_add` / `sp_base` 均由 `ActionDefinitionIR` source-backed resolution 产生。
- `status_numeric_value_resolver`：status lifecycle mutation 中能递归找到 duration / stack / chance 的 value resolution，且 status replay 通过。
- `callback_queue_value_resolver`：queue enqueue mutation 和 settlement payload 携带 `priority_value_resolution.ok=true`，样例 priority source 指向 `Config/GlobalConfig/PriorityConfig.json`。
- `missing_context_negative_state_unchanged`：缺 `event_payload` 和 `status_modifier` context 时 `ValueResolver` blocked，空 mutation replay 通过。
- `consumer_replay_source_audit`：resource/status/queue replay 均通过；resource mutation scoped source audit 通过。

## 残留注意

resource 样例所在完整 transition 的 full source audit 仍有一个非 resource violation：

```text
source=effect_system
reason=dynamic_numeric_binding_source_not_trusted
missing_field=numeric_evaluation.bindings.source_type
```

该 violation 不属于 S6 resource mutation 接入本身，已保留在 S6 matrix 的 `resource_audit` 中，归 S9 的 P5 source audit / 旧验证迁移统一收口。

## 资源口径

```text
lowering_build_count=1
rulebook_build_count=1
resource_runtime_sample_count=1
status_runtime_sample_count=1
queue_runtime_sample_count=1
full_ir_written=false
full_rulebook_written=false
full_transition_dump_written=false
large_artifacts_written=false
output_size=16K/12K
```

## 验证

已运行：

```bash
python3 -m py_compile hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/value_binding.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/core/executor.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/systems/status_callbacks.py hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p5_s6_resource_status_callback_consumers.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s6_resource_status_callback_consumers --output-dir /tmp/hsr_v8_p5_s6_resource_status_callback_consumers
du -h /tmp/hsr_v8_p5_s6_resource_status_callback_consumers/validation_summary_p5_s6_resource_status_callback_consumers.json /tmp/hsr_v8_p5_s6_resource_status_callback_consumers/p5_s6_resource_status_callback_consumers_matrix.json
```

待 P5 收尾最小集：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q simulator_v8_clean_core simulator_v8_ui
git diff --check
```

## 边界

S6 不声明所有 status/callback 数值路径均完成；它证明资源、状态 admission、callback queue priority 三类 consumer 已经有 runtime value resolution ledger。S0 中 `missing_consumer_refs` 不能作为 S6 consumer 已接入证据；本阶段只采信真实 mutation/settlement/replay evidence。
