# P9-S8C1B — 既有正式 action entry 的 RandomConfig 加权选择 materialization 纵切

状态：`accepted`。

验收检查点：PR #2 已完成独立集中审查。生产权威、共享 action materializer、真实 signed source Direct、Fast/负例、非 RandomConfig action 与 status 未受影响证据均通过；S8C1C、完整 RandomConfig denominator 与 runtime/RNG 继续 deferred。本卡不再是可执行入口。

- 风险模式：`STRICT`。本卡同时触及 `TaskGraphIR` 公共严格 codec 与共享正式 materializer，但不改变 runtime。
- 基线：`master@2cd1239f52cd39136576d4920302bafa671d5471`。
- 前置：P9-S8C1A 已 accepted；其 `TaskGraphWeightedChoiceIR` / `TaskGraphWeightedSelectionIR`、身份与 `.OddsList[i]` 精确来源契约为本卡上游权威。
- 阶段结果：只闭合现有正式 `ability_phase_callback` action entry 能真实到达的 `RandomConfig` 加权选择物化；不声明完整 RandomConfig 来源分母。
- 本文件是本 PR 的唯一任务权威。执行层不得用旧规划、聚合卡或相邻阶段自行扩大范围。

## 1. 当前仓库事实与卡面边界

1. S8C1A 已建立严格加权单选 IR，但刻意未挂到 `TaskGraphIR`，也未接任何 materializer。
2. 正式 action 入口已经存在：
   - `tbgd/task_graph_materializer.py::materialize_ability_phase_task_graph`
   - `materialize_ability_task_graph_catalog -> _materialize_ability_entries -> _materialize_entry`
   - `materialize_character_runtime_task_graph_catalog` 的 **ability 半边**同样走 `_materialize_ability_entries -> _materialize_entry`。
   这些 action 调用最终共享 `_build_graph`，入口类型为 `ability_phase_callback`。
3. status 有独立入口 `materialize_status_callback_task_graph` / `_materialize_status_entries`。`Lowerer.build()` 当前调用的是 ability + status 混合的 `materialize_character_runtime_task_graph_catalog`，所以 **整个 `Lowerer.build()` 不是本卡的 S8C1B 边界，也不能拿它证明完整分母**。
4. `RandomConfig` 的 S8A 控制流契约已经提供稳定、有序的 branch 拓扑，并要求 `OddsList` 长度与候选 branch 数一致；`OddsList` 数值表达式仍归 `p9_s8c`，尚未在任务图中物化。
5. `CharacterAbilityRawSnapshot` 已携带冻结的 `source_bytes` 与 source fingerprint；materializer 已接受同一 `source_snapshot`。因此本卡可从 **同一已签名 snapshot** 读取该正式 action source occurrence 的 `.OddsList[i]`，不需要新增来源仓库或第二套数据权威。
6. `tbgd/expression_lowering.py::lower_numeric_expression` 是既有数值表达式 lowering 权威。本卡只复用它，不新增 numeric parser/evaluator。
7. `RandomConfig` 仍属于 `p9_s8c -> hit_random_sequence` deferred 域。本卡只补表示与 materialization，不能执行随机选择。

若执行时上述任一事实不成立，立即按“停止条件”返回 `needs_replan`，不得就地改规划。

## 2. 唯一生产权威与正式调用者

### 2.1 模型权威

唯一模型权威：

- `rules/task_graph.py::TaskGraphWeightedChoiceIR`
- `rules/task_graph.py::TaskGraphWeightedSelectionIR`
- `rules/task_graph.py::TaskGraphIR`

S8C1A 已规定 choice/selection 的身份、顺序、一一配对、父子来源和严格 codec；本卡不得改写该语义，只允许把 selection 作为强类型、确定性集合挂入 `TaskGraphIR` 并补图级一致性约束。

### 2.2 构造权威

唯一构造权威必须位于 `tbgd/task_graph_materializer.py` 的 **共享图构造路径**：

```text
_materialize_entry
  -> _build_graph
       -> [仅 entry_kind == "ability_phase_callback"] RandomConfig selection materialization
```

允许抽出一个窄私有 helper，但只能有一套生产构造逻辑。禁止分别在单 entry、ability catalog、`Lowerer.build()` 调用处各写一套。

正式 action 调用者必须共享这同一权威：

1. `materialize_ability_phase_task_graph`；
2. `materialize_ability_task_graph_catalog -> _materialize_ability_entries`；
3. `materialize_character_runtime_task_graph_catalog` 的 ability 半边；因此 `Lowerer.build()` 只能作为该 ability 半边的下游调用者，而不是本卡完整来源声明。

明确不属于本卡调用者/权威：status callback materializer、GlobalTemplates/shared templates、runtime/RNG、scheduler、replay。

## 3. 允许写集合

以下路径均相对仓库根目录，除列出的可选 CI 外不得修改其他文件：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py`
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`
3. 新增 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py`
4. 新增 `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_execution_report.md`
5. **可选且仅限 CI 治理**：`.github/workflows/p9-s8c1b-pr-validation.yml`

### PR-scoped CI 明确授权

执行层可在 **同一 PR** 自行新增或修复第 5 项 CI 文件，**无需规划线程补卡**，前提同时满足：

- 只由 `pull_request` 触发；不得 `push`、`schedule`、`workflow_dispatch` 或写回仓库；
- 只运行本卡已经列出的既有验证命令/新聚焦验证器，不新增业务语义、来源生成、完整 catalog 扫描或更宽测试套件；
- 不下载额外数据、不修改生产文件、不生成后再提交代码；
- CI 修复只能修“如何在 PR 上运行本卡验证”，不能通过删检查、弱化断言或扩大 ignore 消除失败。

除该明确例外外，若施工需要任何允许集合外生产文件，结果必须是 `needs_replan`。

## 4. 生产完成契约

### 4.1 `TaskGraphIR` 的唯一 attachment

`TaskGraphIR` 新增一个确定性、不可变、严格 JSON 的 `weighted_selections` 集合，元素只能是精确 `TaskGraphWeightedSelectionIR`。

生产构造和 `from_json()` 至少必须保证：

- selection 的 `graph_node_id` 在本图唯一存在；
- 对应 node 的 `family == "RandomConfig"`；
- 每个 RandomConfig node 最多一个 selection；selection identity 唯一；
- `selection.choices` 的 ordinal 与对应 node 的有序 `branches` 一一对应，且 `choice.branch_id` 精确等于同下标 branch identity；
- selection/choice/numeric definition 的来源与本图 source catalog/fingerprint、对应 node source occurrence 闭合；
- 未知字段、错误成员类型、重复、悬空 node/branch、错误 family、伪造 identity 均 fail-closed；
- `to_json -> from_json -> to_json` 稳定；修改调用者输入容器或 `to_json()` 结果不能改变模型。

S8C1A 已规定 selection 自己拥有一一配对的 `numeric_definitions`。本卡不得为了方便再建立第二套权重定义权威；若现有 `TaskGraphIR.numeric_definitions` 必须引用这些定义才能保持既有图级不变量，只能建立无歧义的单一身份引用/一致性约束，禁止产生内容不同的双写副本。

### 4.2 正式 action `RandomConfig` 真实来源物化

仅当 `_build_graph` 正在构造 `entry_kind == "ability_phase_callback"` 且当前 source control node 的 `family == "RandomConfig"` 时物化 selection。

对每个这样的 node：

1. **branch 拓扑只认现有 S8A -> TaskGraph branch 结果。** 不得从 raw `ConfigList` 重新发明排序或第二套 branch identity。
2. 以当前 node 的精确父 `IRSource` / source occurrence 为锚，从传入的同一 `CharacterAbilityRawSnapshot.source_bytes` 读取该 occurrence 对应的 raw `OddsList`；不得去磁盘重新发现别的 source，不得固定角色、ability、文件或数据 ID。
3. `OddsList` 必须是 list，长度必须与 node 的有序 TaskGraph branches 完全相等；缺失、类型错误、长度矛盾立即 fail-closed，不能补默认值、跳项、截断、排序或归一化。
4. 第 `i` 项只通过既有 `tbgd/expression_lowering.py::lower_numeric_expression` lower；禁止新 numeric grammar/parser/evaluator。
5. 为第 `i` 项生成 S8C1A 要求的精确 `.OddsList[i]` 子来源、source occurrence、`TaskGraphNumericDefinitionIR`、`TaskGraphWeightedChoiceIR`，并与第 `i` 个现有 branch identity 精确配对。
6. selection identity 必须由 S8C1A helper 重算闭合；choice 顺序必须严格 `0..n-1`；相同数值出现在不同下标也不得合并 occurrence/definition/choice。
7. materializer 不求值、不归一化、不抽样权重；node 的现有 `materialization_status == "deferred"` 与 `owner_domains == ("hit_random_sequence",)` 必须保持。

若无法仅凭当前正式 source occurrence + 同一 signed snapshot 精确解析 `.OddsList[i]`，或者必须修改 S8A/control-flow 来源权威才能做到，停止并 `needs_replan`。

### 4.3 action 调用者一致性

同一个动态选中的真实 ability phase/callback：

- `materialize_ability_phase_task_graph` 的 selection 结果；
- `materialize_ability_task_graph_catalog` 中对应 entry 的 selection 结果；

必须来自同一共享构造权威并结构一致。`materialize_character_runtime_task_graph_catalog` 可自然继承 ability 半边结果，但本卡不得因此检查或声明 status/GlobalTemplates/完整 RandomConfig 分母已闭合。

## 5. 明确非目标 / deferred

以下全部不做，并继续归 S8C1C 或后续 S8C：

- status callback 中的 `RandomConfig`；
- GlobalTemplates、shared global templates、GridFight/shared template formal producer gaps；
- 其余公开 entry 的 RandomConfig 接线；
- 完整 RandomConfig 来源分母、全量 source/path ledger、完整 catalog 覆盖率声明；
- `RandomSelect` / `RandomSelectList` 或其他随机 family 的顺带重构；
- weighted choice 的 runtime 执行、RNG、seed、抽样、重放、事务、scheduler、settlement；
- 改变 S8A field responsibility、control-flow branch lowering 或 source discovery；
- 改变 numeric expression 语法/求值；
- 生成表、registry、总计划/checklist、无关文档清理或重构。

## 6. 完成条件

全部满足才可回传 `ready_for_review`：

1. `TaskGraphIR.weighted_selections` 的严格模型、codec、图级 node/branch/source 不变量闭合。
2. 聚焦验证器能从当前 signed source / production lowering **动态找到至少一个**正式 `ability_phase_callback` 可达的真实 `RandomConfig`；不得把角色、phase、callback、source path、raw ID 写死为验证前提。
3. 对该真实来源，selection 的 choice 数量、ordinal、branch identity、`.OddsList[i]` source occurrence、numeric definition identity 与 S8C1A 契约逐项闭合。
4. 同一 action entry 经单 entry API 与 ability catalog API 得到一致 selection；构造逻辑只有一处。
5. 最小负例分别证明：`OddsList` 缺失/类型错误或长度矛盾、selection 指向错误 node/branch、伪造 source/identity、严格 codec 未知字段会在生产边界拒绝。每类根因保留一个最小反例即可。
6. 一个非 RandomConfig ability action graph 行为不变；一个 status callback materialization 不产生本卡新增 selection，也不改变其既有结果。
7. S8C1A 聚焦 IR 验证仍通过。
8. `RandomConfig` node 仍 deferred 到 `hit_random_sequence`；runtime 行为变化为零。
9. 实际 diff 只在允许写集合；可选 CI 若存在满足本卡 PR-scoped 限制。
10. 不输出“完整 catalog / 完整 RandomConfig denominator 已闭合”等超出 S8C1B 的结论。

若第 2 条真实正式 action source 在当前基线动态不存在，不允许用 synthetic fixture 冒充完成；直接 `needs_replan`。

## 7. Fast

从仓库根目录串行运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1b_action_entry_weighted_selection.py

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m \
  simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m \
  simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --fast

git diff --check
```

`--fast` 只使用最小 typed fixture 验证 attachment/codec/共享 helper 与负例，不扫描完整来源分母、不运行 runtime。

## 8. Direct

生产自审和 Fast 全绿后只运行一次：

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m \
  simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --direct
```

`--direct` 必须：

- 复用现有 production snapshot / control-flow / canonical lowering；
- 动态选择一个真实、正式 `ability_phase_callback` 可达的 `RandomConfig`，选择逻辑不得固定业务 ID/文件；
- 对该单一代表 source 调正式 `materialize_ability_phase_task_graph`，并对照 ability catalog 中同 entry 的结果；
- 逐项检查 raw `.OddsList[i]` -> 既有 numeric lowering -> definition -> choice -> branch -> selection 的身份和来源；
- 同时做一个最小非 RandomConfig action 与一个最小 status 未受影响检查；
- 找到并完成代表纵切后即停止，不顺带统计完整 RandomConfig denominator，不升级为 catalog/full 验证。

除非执行面的实际改动触及来源发现、S8A lowering/ref 或完整分母，本卡禁止新增 catalog/full 门禁；若发现必须触及这些面，结果应为 `needs_replan`，不是自行扩大 Direct。

## 9. 预算

- Fast：目标 `<= 10s`，硬上限 `30s`，峰值 RSS 软上限 `256 MiB`、硬上限 `512 MiB`。
- Direct：目标 `<= 45s`，硬上限 `120s`，峰值 RSS 软上限 `512 MiB`、硬上限 `1 GiB`。
- 执行报告正文目标 `<= 300` 行；不得落盘 raw source dump。
- 达到任一硬上限约 `70%` 时先停止扩展诊断；同一根因连续失败两次时不得第三次盲跑，直接记录 blocker 并返回 `needs_replan` 或明确的外部 `blocked`。
- 不通过删断言、改 warning、增加 ignore、缩减真实来源要求或扩大超时来“过门”。

## 10. 停止条件

出现任一项立即停止施工，写执行报告并返回 `needs_replan`（纯外部权限/基础设施不可用才用 `blocked`）：

- 当前 signed source 中找不到任何正式 `ability_phase_callback` 可达的真实 `RandomConfig`；
- `.OddsList[i]` 无法从当前正式 source occurrence + 同一 snapshot 精确恢复，必须改 S8A/control-flow 来源模型；
- 必须修改 `character_control_flow_contracts.py`、`expression_lowering.py`、`lowering.py`、status producer、GlobalTemplates/shared templates 或其他允许集合外生产文件；
- action 单 entry 与 ability catalog 不能收敛到一处共享构造权威；
- S8C1A 的 identity/source 规范与当前正式 branch/source 事实发生冲突；
- 必须求值/归一化/执行随机，或触及 RNG/runtime/replay/scheduler；
- 必须把 S8C1C 的其余入口或完整 denominator 合并进本卡才能证明完成；
- 预算达到硬限制，或同一根因连续两次验证失败仍未定位。

停止时禁止扩大写集合或重新解释卡面。

## 11. 执行报告路径与最低证据

唯一执行报告：

`hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1B_ACTION_ENTRY_WEIGHTED_SELECTION_execution_report.md`

报告必须包含：

- `base`、最终 `head`、结果 `ready_for_review | needs_replan | blocked`；
- 实际 changed files 与允许写集合对账；
- 唯一构造权威及实际 action caller map；
- Direct 动态选中代表来源的最小可审计元数据：entry kind、phase/callback identity、source occurrence/json path；不得把它反写成未来固定业务 fixture；
- 每条 Fast/Direct 命令、exit code、耗时、峰值 RSS；
- raw `.OddsList[i]` 到 definition/choice/branch/selection 的逐项闭合证据摘要；
- 负例、非 RandomConfig action、status 未受影响、`hit_random_sequence` 仍 deferred 的证据；
- S8C1C deferred：其余公开 entry、status/GlobalTemplates/shared templates 与完整 RandomConfig denominator 均未声明闭合；
- 若使用可选 CI：CI 路径、触发条件与“仅运行本卡既有验证”的证明。

不勾 checklist、不合并 PR、不推进 S8C1C。

## 12. 交付状态

`accepted: true`
`ready_for_execution: false`
