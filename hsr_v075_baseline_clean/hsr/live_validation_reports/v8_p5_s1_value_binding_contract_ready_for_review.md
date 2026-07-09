# v8 P5-S1 Value Binding Contract Ready For Review

日期：2026-07-09

阶段状态：`ready_for_review`。本报告是执行线程证据包，不修改 `P5_FORMULA_DYNAMIC_PARAM_BINDING_TASK_PLAN.md` 第 19 节 checklist，不声明 `done`。

## 阶段目标

P5-S1 建立当前 ValueBinding / RuleBook / runtime consumer 契约账本，回答三件事：

- 哪些数值来源已经有稳定 IR 容器、稳定 ID、source trace。
- 哪些容器已经能通过 RuleBook accessor 按绑定键或 parent key 查询。
- 哪些 runtime consumer 只有直接 IR/source evidence，仍未迁移到后续 ValueResolver。

## 实际改动

新增：

- `simulator_v8_clean_core/tools/validate_p5_s1_value_binding_contract.py`
- `live_validation_reports/v8_p5_s1_value_binding_contract_ready_for_review.md`

未修改：

- 未改 `rules/ir.py`、`rules/rulebook.py`。
- 未改 `core/executor.py`。
- 未改 damage / resource / status / summon consumer 行为。
- 未改 lowering。
- 未新增 P5-S10 聚合入口。
- 未改 P5 checklist。

## 验证脚本行为

S1 验证脚本只做结构审计：

- 构建一次 `TBGDLowering(...).build()` 与 `RuleBook(ir)`。
- 输出 binding container contract matrix。
- 输出 RuleBook query contract matrix。
- 输出 runtime consumer contract matrix。
- 输出 gap attribution matrix 与 source trace samples。

脚本不执行新的数值求值，不新增 ValueResolver，不构造 synthetic positive case，不把 S0 的 `missing_consumer_refs` 当作 consumer 已接入证明。

## Matrix 结果

输出目录：

```text
/tmp/hsr_v8_p5_s1_value_binding_contract
```

关键文件：

```text
/tmp/hsr_v8_p5_s1_value_binding_contract/validation_summary_p5_s1_value_binding_contract.json
/tmp/hsr_v8_p5_s1_value_binding_contract/p5_s1_value_binding_contract_matrix.json
```

S1 主验证：

```text
ok=True
total_row_count=21
binding_container_row_count=9
rulebook_query_row_count=6
runtime_consumer_row_count=6
sample_source_trace_count=9
```

分类：

```text
classification_counts:
  executable=15
  admission_gap=4
  boundary_only=2

gap_attribution_counts:
  admission_gap=4
  source_gap_blocked=0
  implementation_missing=0
  lowering_gap=0
  validation_gap=0
  unclassified=0
```

## 契约审计结果

Binding container contract 全部可见：

```text
skill_formula_binding_contract: executable, ir=22868, rulebook_visible=22868
damage_emission_contract: executable, ir=19441, rulebook_visible=19441
toughness_emission_contract: executable, ir=19441, rulebook_visible=19441
resource_rule_contract: executable, ir=2, rulebook_visible=2
status_damage_emission_contract: executable, ir=500, rulebook_visible=500
action_delay_emission_contract: executable, ir=674, rulebook_visible=674
queue_intent_contract: executable, ir=1474, rulebook_visible=1474
summon_intent_contract: executable, ir=775, rulebook_visible=775
data_card_mechanism_slot_contract: executable, ir=32174, rulebook_visible=32174
```

RuleBook query contract 全部可见：

```text
skill_formula_binding_rulebook_queries: executable, ir=22868, visible=22868
damage_toughness_rulebook_queries: executable, ir=38882, visible=38882
resource_rulebook_queries: executable, ir=2, visible=2
status_callback_numeric_rulebook_queries: executable, ir=2648, visible=2648
summon_intent_rulebook_queries: executable, ir=775, visible=775
data_card_mechanism_rulebook_queries: executable, ir=32174, visible=32174
```

Runtime consumer contract 保留 admission gap：

```text
damage_toughness_runtime_consumer_contract: admission_gap, consumer=38882
resource_runtime_consumer_contract: admission_gap, consumer=2
status_callback_numeric_runtime_consumer_contract: admission_gap, consumer=2648
summon_intent_runtime_consumer_contract: admission_gap, consumer=775
numeric_evaluator_current_contract: boundary_only, formula_count=321833
s0_missing_consumer_ref_policy: boundary_only
```

这些 admission gap 表示：当前能定位到 consumer 和 IR/source evidence，但尚未完成 P5-S4/S5/S6/S7 的通用 ValueResolver admission 与 consumer 迁移。它们不能被解释为“数值 consumer 已完成接入”。

## S0 注意点继承

S0 验收注意点已写入 `s0_missing_consumer_ref_policy` 行：

```text
Some S0 source families have missing_consumer_refs because S0 does not load later P4 stage matrices.
S1/S5/S6 must not treat those refs as consumer admission proof.
```

本阶段所有 runtime consumer 行均使用当前 IR consumer count 或当前 runtime 文件查询 token 作为证据，不使用缺失的 P4 后续矩阵引用当作接入完成证明。

## 实际运行的验证

在 `hsr_v075_baseline_clean/hsr` 下通过：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile simulator_v8_clean_core/tools/validate_p5_s1_value_binding_contract.py
PYTHONDONTWRITEBYTECODE=1 ionice -c3 nice -n 15 python3 -B -m simulator_v8_clean_core.tools.validate_p5_s1_value_binding_contract --output-dir /tmp/hsr_v8_p5_s1_value_binding_contract
```

结果：

```text
v8 p5_s1_value_binding_contract ok=True rows=21
classifications={'admission_gap': 4, 'boundary_only': 2, 'executable': 15}
gap_counts={'admission_gap': 4, 'implementation_missing': 0, 'lowering_gap': 0, 'source_gap_blocked': 0, 'unclassified': 0, 'validation_gap': 0}
```

## 尚未运行的验证

截至本报告生成时，S1 主验证和 `py_compile` 已通过；`compileall`、`git diff --check` 和尾随空白检查将在本阶段收尾时与后续脚本一起运行。

本阶段未运行 P1/P2/P3/P4 聚合回归，因为当前只新增审计脚本和报告，没有修改 runtime、RuleBook、lowering 或 shared consumer。若后续阶段修改这些共享路径，将按触达范围补跑对应回归。

## 当前进度口径

当前做到 P5-S1 `ready_for_review`：ValueBinding / RuleBook / runtime consumer 契约审计完成，确认核心 binding 容器与 RuleBook 查询面已经稳定可见。

距离最小可用战斗纵切：S1 不改变战斗执行，只提供后续 S2-S8 数值接入的 contract 证据。

距离完整复刻：仍缺静态参数 resolver、dynamic/custom read-site 投影、ValueContext / ValueResolver、damage/toughness/heal/shield/hp-loss consumer、resource/status/callback queue consumer、怪物 custom value、召唤参数、角色行迹 / 星魂 / 强化形态绑定，以及最终负例 / audit / replay / 聚合验收。
