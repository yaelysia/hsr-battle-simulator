# P9-S8C1A 加权单选 IR 契约

状态：`accepted`。独立验收已闭合；CI-2 已验证固定 base 到 PR head 的 committed diff，S8C1B/S8C1C deferred 保持不变。

- 风险模式：`STANDARD`
- 执行方式：可由主线程、人工新线程或子代理实施；不依赖子代理功能。
- 推荐能力：平台可选模型时使用 Terra Max。本卡只有纯 IR/codec 权威，没有正式消费者。
- 升级触发：缺少现有 helper 语义时由主线程补导航；需要 materializer、TBGD 或新权威时直接
  `needs_replan`。若平台可升级且 Terra 在既定规则内两次仍不能闭合，由主线程使用 Sol Medium
  接管当前 diff；平台不可升级时，由主线程直接接管或进一步缩卡。
- 前置：P9-S8B 已完成；S8C1 聚合未完成。
- 阶段结果：建立任务图加权单选的类型、身份、来源关系、不可变性和严格 JSON 契约。
- 本卡不读取 TBGD、不接 materializer、不修改任务图节点、不执行随机。

## 已确认事实

任务图已有 `TaskGraphBranchIR`、`TaskGraphNumericDefinitionIR`、`TaskGraphNodeIR` 和严格 codec，
但还不能表达以下一一对应关系：

```text
随机节点 -> 第 i 个候选 branch -> 第 i 个权重定义 -> OddsList[i] 来源
```

S8C1A 只建立该模型权威；S8C1B 负责正式 materializer 接线，S8C1C 负责其余来源入口和完整分母。
本卡通过不代表真实 `RandomConfig` 已进入任务图，也不代表随机可执行。

## 开工导航

只读：

- 本卡；
- `rules/task_graph.py` 中的 `TaskGraphNumericDefinitionIR`、`TaskGraphBranchIR`、`_exact`、
  `_source`、`task_graph_source_occurrence_id` 和 `task_graph_numeric_id`；
- `rules/__init__.py` 的任务图导出区；
- `immutable_json.py` 的冻结与解冻契约。

出现具体未解析依赖时最多再做两次精确符号定位；仍无法闭合则提交 `needs_replan`，不得扫描历史计划、
P8 报告或相邻阶段实现。

## 唯一生产权威

在 `rules/task_graph.py` 新增并公开导出：

- `TaskGraphWeightedChoiceIR`
- `TaskGraphWeightedSelectionIR`
- 对应的稳定 identity helper

`Choice` 保存节点身份、family、从零开始的顺序、branch 身份、权重定义身份、权重字段 occurrence 和
精确 `IRSource`。

`Selection` 保存节点身份、父来源 occurrence、family、固定 `weighted_single` 类型、有序 choices、
一一对应的数值定义和父 `IRSource`。

当前没有正式消费者；S8C1A 的完成状态是“类型契约可用但未挂接”，不得创建伪消费者证明执行。

身份规范固定为：

```text
selection = graph node identity + parent source occurrence
choice = graph node identity + ordinal + branch identity + weight definition identity
```

## 生产完成条件

生产构造与 `from_json()` 必须直接拒绝以下矛盾，不能依赖验证器预判：

1. 空选择、空身份、子类实例、布尔或负数顺序。
2. 顺序不是严格 `0..n-1`，或 choices 与权重定义数量、下标不一致。
3. choice 与 selection 的节点、family 或父来源不一致。
4. 第 i 项来源不是父路径下精确的 `.OddsList[i]`。
5. occurrence、数值定义来源和数值定义身份不能互相重算闭合。
6. 调用者提供的 choice/selection identity 与规范重算结果不一致。
7. 未知字段、缺字段、错误成员类型和旧弱 payload。

同时满足：

- 相同权重值位于不同下标时保持不同 occurrence、定义和 choice 身份；不归一化权重。
- 普通容器在构造时复制并冻结；`to_json()` 返回独立普通 JSON。
- `to_json -> from_json -> to_json` 稳定一致。
- 复用现有数值表达式模型，不建立第二套 parser、evaluator 或 fingerprint。
- 不修改 `TaskGraphNodeIR`、`TaskGraphIR`、现有 branch 行为或 runtime。

branch 是否真实存在、kind 是否正确属于 S8C1B，本卡不得用假图提前闭合。

## 允许写集合

以下路径均相对 `hsr_v075_baseline_clean/hsr/`：

- `simulator_v8_clean_core/rules/task_graph.py`
- `simulator_v8_clean_core/rules/__init__.py`
- 新增 `simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py`
- 新增 `live_validation_reports/P9-S8C1A_WEIGHTED_SELECTION_IR_ready_for_review.md`

禁止修改 materializer、systems、core、RNG、replay、scenario、UI、总计划、checklist 和其他执行卡。

## 最小验证

唯一聚焦验证器使用明确标记为 `validation_fixture` 的最小来源，只观察生产边界：

- 一个固定权重加动态表达式的合法选择可 round-trip；
- 两个相同数值但不同下标的身份彼此独立；
- 一个顺序/配对矛盾被拒绝；
- 一个跨父来源或错误 `OddsList` 下标被拒绝；
- 一个伪造 identity 或 codec 未知字段被拒绝；
- 修改输入容器和 `to_json()` 输出不影响模型。

每类生产不变量只保留一个最小反例。fixture 不能声明 TBGD 来源或 gameplay executable。

从仓库根目录串行运行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m \
  simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir

git diff --check
```

不运行 TBGD lowering、历史 P9 验证、完整 Canonical IR、runtime direct 或 catalog/full。

预算：单一入口目标 2 秒、硬上限 10 秒；峰值内存 128 MiB；产物默认不落盘，必要诊断写 `/tmp`。
达到上限前先检查验证器是否复制了生产规则，不通过压缩排版规避。

## 交付与停止

`ready_for_review` 报告只记录实际改动、命令结果、资源和 S8C1B/S8C1C deferred，不复述本卡。
不勾 checklist、不提交 Git、不进入下一阶段。

出现以下任一情况提交 `needs_replan`：

- 需要 TBGD、外部下载、materializer 或 `TaskGraphNodeIR` 才能完成；
- 需要执行随机、求值动态权重或改变 RNG/replay；
- 现有 numeric expression 无法承载合法 fixture；
- 需要修改允许集合外生产文件、兼容旧 payload 或建立第二套来源解释器。

## 执行清单

- [x] choice/selection、身份和严格 codec 已建立并导出。
- [x] 顺序、配对、父子来源和输入隔离由生产边界保证。
- [x] 最小 fixture 验证在预算内通过，未冒充真实来源或可执行 gameplay。
- [x] 写集合、报告和 deferred 自审完成并提交 `ready_for_review`。
