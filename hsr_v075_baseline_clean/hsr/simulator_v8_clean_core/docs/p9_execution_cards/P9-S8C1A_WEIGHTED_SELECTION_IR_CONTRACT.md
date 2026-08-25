# P9-S8C1A 加权候选 IR 契约执行卡

## 阶段定位

- 基线：以包含本卡的远端 `master` 最新提交为准，开工报告必须记录实际 SHA。
- 前置：P9-S8B 已完成；P9-S8C1 聚合尚未完成。
- 执行方式：从 `https://github.com/yaelysia/hsr-battle-simulator` 创建独立分支并提交 PR，目标分支为 `master`。
- 本卡只建立一个生产权威：任务图加权单选的类型、身份、不可变性和严格 JSON 契约。
- 本卡不读取 TBGD，不接 materializer，不修改任务图节点，不执行随机，也不完成 P9-S8C1 聚合。

远端仓库没有跟踪 `turnbasedgamedata-main/`。不得下载、合成或复制外部数据来制造来源正例；
真实来源接线由后续 S8C1B/S8C1C 在具备 TBGD 的本地环境完成。

## 前因后果

当前任务图已经有：

- `TaskGraphBranchIR`：保存分支种类、顺序、子节点和来源；
- `TaskGraphNumericDefinitionIR`：保存严格数值表达式、定义身份和来源；
- `TaskGraphNodeIR` / `TaskGraphIR`：保存节点、图拓扑和 codec。

但尚无类型能够表达：

```text
同一个随机节点
  -> 第 i 个候选 branch
  -> 第 i 个权重定义
  -> 父 RandomConfig 下精确 OddsList[i] 来源
```

上一版 S8C1 同时要求建立该模型、迁移 materializer，并闭合角色能力、文件内全局模板、状态回调
和共享模板的全部来源入口。实际核对表明这些来源并不共享一个公开生产入口，继续合并会让执行线程
恢复私有 lowering 或手工拼装 Canonical IR。因此 S8C1 现拆为：

1. S8C1A：建立严格、独立的加权选择 IR，本卡。
2. S8C1B：把该 IR 接入当前正式 action entry 的 materializer。
3. S8C1C：补齐 GlobalTemplates、状态回调和共享模板的公开入口并完成来源分母闭合。

本卡通过只代表模型权威成立，不代表任何真实 `RandomConfig` 已进入正式任务图，更不代表随机可执行。

## 开工导航

新线程只需先读：

- 本卡；
- `rules/task_graph.py`：
  - `TaskGraphNumericDefinitionIR`
  - `TaskGraphBranchIR`
  - `_exact`
  - `_source`
  - `task_graph_source_occurrence_id`
  - `task_graph_numeric_id`
- `rules/__init__.py`：现有任务图公开导出区。
- `immutable_json.py`：只读现有 `freeze_json` / `thaw_json` 契约。

禁止通读历史报告、历史验证器、P8 文档或相邻 S8C1B/S8C1C 设想。上述符号出现具体未解析依赖时，
最多再做两次精确符号搜索；仍无法定位则提交 `context_gap`。

## 阶段目标

在 `rules/task_graph.py` 中建立两个互相分离的递归不可变模型，名称使用：

- `TaskGraphWeightedChoiceIR`
- `TaskGraphWeightedSelectionIR`

并提供稳定 identity helper。允许在不改变语义的前提下调整字段排列，但模型必须完整表达下列事实。

### 1. 单个候选

`TaskGraphWeightedChoiceIR` 至少保存：

- 自身稳定身份；
- 所属任务图节点身份；
- 来源 family；
- 从 0 开始的候选顺序；
- 对应 branch 身份；
- 对应权重定义身份；
- 权重字段来源 occurrence 身份；
- 精确 `IRSource`。

公开构造边界必须直接拒绝：

- 子类实例、布尔型或负数顺序、空身份；
- 与字段不一致的 choice identity；
- 缺少规范来源证据；
- 来源路径不以 `.OddsList[ordinal]` 精确结尾；
- 由该来源和 family 重算后不一致的权重 occurrence。

### 2. 加权单选

`TaskGraphWeightedSelectionIR` 至少保存：

- 自身稳定身份；
- 所属任务图节点身份；
- 父节点来源 occurrence；
- 来源 family；
- 固定为 `weighted_single` 的选择类型；
- 按顺序保存的 choices；
- 与 choices 一一对应的 `TaskGraphNumericDefinitionIR`；
- 指向随机对象本身的父 `IRSource`。

公开构造边界必须保证：

1. 至少有一个候选。
2. 顺序严格为 `0..n-1`，不排序、不去重、不补洞。
3. choices 与权重定义数量相同并按相同下标一一配对。
4. 每个 choice 都属于同一节点和同一 family。
5. choice 来源与父来源的文件、raw record、内容指纹完全一致。
6. 第 i 项来源路径严格等于 `parent_json_path + ".OddsList[i]"`。
7. choice 的 occurrence、权重定义 occurrence、权重定义来源和定义身份全部一致。
8. 同一节点两个相同数值的权重因来源位置不同而保持不同身份。
9. selection identity 由节点身份和父来源 occurrence 重算，不能信任调用者输入。
10. 不接受遗漏、额外、重复、跨文件、跨节点或交换后的成员。

branch 是否真实存在于 `TaskGraphNodeIR`、branch kind 是否为 `random_candidate`，由 S8C1B 在模型挂接时
验证。本卡不得提前修改 `TaskGraphNodeIR`，也不得伪造一个假的图来宣称该关系已经闭合。

### 3. 不可变性与 codec

- 两个模型都使用精确 dataclass 类型，禁止子类绕过。
- 普通 list、tuple、dict 输入在构造边界复制并冻结；修改原始容器不得改变模型。
- `to_json()` 返回独立普通 JSON；修改返回值不得改变模型。
- `from_json()` 接收普通 JSON 容器，但拒绝未知字段、缺字段、错误成员类型和旧弱 payload。
- `to_json -> from_json -> to_json` 必须稳定一致。
- 权重表达式继续复用 `TaskGraphNumericDefinitionIR` 和现有 numeric expression 契约，不建立第二套 parser、
  evaluator 或 fingerprint。

## 身份规则

新增 identity helper 应沿用 `task_graph.py` 的 `_id(...)` 风格：

```text
weighted selection identity = graph node identity + parent source occurrence
weighted choice identity = graph node identity + ordinal + branch identity + weight definition identity
```

身份中不得放角色名、固定 ID、固定文件名、验证样例名或工程阶段编号。相同表达式不能成为合并依据。

## 允许写集合

生产文件：

- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py`
- `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/__init__.py`

验证与报告：

- 新增 `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py`
- 新增 `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1A_WEIGHTED_SELECTION_IR_ready_for_review.md`

禁止修改：

- `tbgd/task_graph_materializer.py`
- `TaskGraphNodeIR`、`TaskGraphIR` 和现有 branch 行为
- `systems/`、`core/`、runtime、RNG、replay、scenario、UI
- P9 总计划、Checklist、交接文档和其他执行卡
- 依赖文件、GitHub workflow、`.gitignore`、CodeGraph 索引

需要修改允许集合之外的生产文件时，立即提交 `plan_mismatch`，不得扩大 PR。

## 验证设计

唯一验证器只使用明确标记为 `validation_fixture` 的最小 `IRSource`，不得声称 fixture 是 TBGD 正例。
验证器应直接调用生产构造器和 codec，至少证明：

1. 固定权重和动态表达式能进入同一类型化契约。
2. `[0.5, 0.5]` 两个相同表达式仍有两个不同字段 occurrence、definition identity 和 choice identity。
3. `[0.2, 0.2, 0.2]` 保持原始相对权重，不归一化。
4. 顺序缺口、重复或交换被拒绝。
5. choice 指向另一节点被拒绝。
6. 权重来源来自另一文件、另一 raw record、另一父路径或错误下标时被拒绝。
7. 同步伪造 occurrence 和下游 ID仍不能绕过父子来源关系。
8. choice 与 numeric definition 数量或下标配对不一致时被拒绝。
9. codec 未知字段、旧 payload、错误数组成员和伪造 identity 被拒绝。
10. 构造输入和 `to_json()` 输出修改均不能改变模型。

每条生产不变量只保留一个最小反例。禁止复制第二套 identity/source 判断逻辑预判结果；oracle 只负责
构造输入并观察生产边界是否拒绝。

## 固定验证顺序与预算

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1a_weighted_selection_ir.py

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 python3 -B -m \
  simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir

git diff --check
```

以上命令均从仓库根目录运行。不得运行 TBGD lowering、历史 P9 验证、完整 Canonical IR、runtime
direct 或 catalog 聚合。

预算：

- 唯一验证入口 1 个；
- 主验证目标 2 秒，硬上限 10 秒；
- 峰值内存硬上限 128 MiB；
- evidence 可不落盘；如确需落盘，写 `/tmp` 且不超过 32 KiB；
- 验证器目标 220 个非空行，硬上限 300；达到 210 行时先复核是否复制了生产规则；
- 生产改动目标不超过 260 个新增非空行。超过时提交 `plan_mismatch`，不得压缩排版规避。

## ready_for_review 门槛

只有同时满足以下条件才能在 PR 中提交 `ready_for_review`：

- 两个模型的身份、来源关系、顺序、一一配对、不可变性和 codec 均由生产边界保证。
- 验证器的正例明确标记为 fixture，没有 TBGD、角色或 gameplay executable 声明。
- 允许写集合之外零修改。
- `TaskGraphNodeIR`、materializer 和 runtime 行为保持不变。
- 所有新增公开符号已在 `rules/__init__.py` 原子导出，且无兼容双轨。
- `compileall`、唯一主验证和 `git diff --check` 通过且资源在预算内。
- 报告明确写出：S8C1A 只完成类型契约，真实来源接线和完整来源闭合仍分别属于 S8C1B/S8C1C。

绿色验证不能替代生产代码自审。若任一项无法证明，只能提交 `blocked`、`plan_mismatch` 或
`context_gap`。

## GitHub PR 交付协议

1. 从包含本卡的最新 `master` 创建分支，建议命名 `p9-s8c1a-weighted-selection-ir`。
2. 只提交允许写集合中的四个文件，不提交缓存、环境文件、会话日志或生成数据。
3. PR 标题使用：`P9-S8C1A: add strict weighted-selection IR contract`。
4. PR 正文必须包含：基线 SHA、实际改动、生产不变量、验证命令与结果、资源数据、明确 deferred。
5. 不修改 Checklist，不把 S8C1/S8C 标成完成，不自行合并 PR。
6. 请求验收时提供 PR 链接；最终是否通过和合并由规划/验收线程决定。

## 停止条件

出现以下任一情况立即停止：

- 需要 TBGD 或外部下载才能继续。
- 需要把模型挂到 `TaskGraphNodeIR` 或修改 materializer 才能通过本卡。
- 需要执行随机、求值动态权重或改变 RNG/replay。
- 现有 numeric expression 模型无法保存所需 fixture 形状。
- 需要兼容旧 payload、私有 lowering 或写第二套来源解释器。
- 首次五面自审发现三个以上系统性问题类别，或 90 分钟仍未形成可审查 PR。

## 唯一执行清单

- [ ] 加权 choice 与 selection 模型、身份和严格 codec 已建立。
- [ ] 顺序、一一配对、父子来源和输入隔离矛盾均由生产边界拒绝。
- [ ] 最小 fixture 验证在预算内通过，且没有冒充真实来源或可执行 gameplay。
- [ ] PR 范围、报告和 deferred 已完整自审并提交 `ready_for_review`。
