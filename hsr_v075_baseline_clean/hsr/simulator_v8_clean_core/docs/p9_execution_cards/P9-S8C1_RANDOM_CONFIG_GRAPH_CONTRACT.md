# P9-S8C1 RandomConfig 任务图权重契约执行卡

## 执行配置

- 基线检查点：`6bcad0e`。
- 硬前置：P9-S8B1 至 P9-S8B6 均已验收。
- 推荐执行：使用能够严格遵守类型化来源和 fail-closed 边界的高推理档，普通聚焦执行，不开子代理。
- 本卡只建立一个主要权威：`RandomConfig` 在正式任务图中的有序加权候选契约。
- 本卡不执行随机分支，不修改 runtime，不进入 P9-S8C2 或其他阶段。

## 为什么单独拆卡

原 S8C 同时包含 projectile 命中、barrier、parallel、随机分支和跨领域事务回验，至少横跨来源模型、
共享执行器、RNG、领域窗口和 replay 五个边界，不适合作为单次阶段任务。

当前代码已经具备：

- S8A 的完整角色控制流来源目录和 `random_candidate` 有序 child 分支；
- S8B 的正式任务图、严格查询和原子执行器；
- 通用数值表达式定义与 RNG ledger。

但任务图尚未保存“第几个随机候选使用哪一条权重表达式”。状态 callback 的旧路径仍直接读取
task payload 中的 `OddsList`，它不是正式任务图的可复用权威，也不能作为本卡实现模板。

## 修改前已确认事实

2026-08-25 使用当前生产窄投影得到以下调查事实：

- 完整角色来源包含 80 份能力文档；`RandomConfig` family 窄投影有 43 条记录，其中 14 条为
  直接选中记录、29 条为祖先上下文，全部属于 gameplay，投影 issue 为 0。
- 14 条直接记录来自 5 份当前角色来源文件；这些数量只写入报告，不得成为固定通过条件。
- 当前直接 raw 形状只出现 `$type`、`OddsList`、`TaskList`；候选数观察到 2 至 7，但生产契约
  必须从实时来源推导，不能固定数量。
- `OddsList` 同时存在固定表达式和动态表达式。
- 权重是相对权重，不是必须合计为 1 的概率。真实来源存在总和不为 1 的固定权重记录。
- 同一节点经常有数值完全相同的多个权重。若只用“节点 occurrence + 表达式内容”生成身份，
  会把不同 `OddsList[i]` 错误合并，因此每个权重项必须具有独立字段位置身份。
- `TaskGraphBranchIR` 当前只保存分支和 child，没有权重绑定；任务图数值定义当前主要服务循环终止。
- `_node_status()` 仍把 S8C 责任节点标记为 deferred。本卡完成后 `RandomConfig` 节点仍须 deferred，
  直到后续运行时卡真正实现选择和原子执行。

若开工核对发现上述事实发生变化且会改变模型职责，必须返回 `plan_mismatch`，不能自行缩减来源。

## 开工导航摘要

本阶段默认只读本卡和
以下精确符号，使用 `rg -n` 和定向源码读取完成最多两轮结构定位：

- `rules/task_graph.py`：`TaskGraphNumericDefinitionIR`、`TaskGraphBranchIR`、`TaskGraphNodeIR`、
  `TaskGraphIR` 及其 identity/codec helper；
- `tbgd/task_graph_materializer.py`：`_build_graph()`、`_branches()`、`_node_status()`、
  `materialize_ability_phase_task_graph()`、`materialize_status_callback_task_graph()`；
- `tbgd/character_control_flow_contracts.py`：只读 `RandomConfig` 的字段责任和 `_branch_specs()` 分支；
- `tbgd/character_ability_scope.py`：只读 `build_character_ability_raw_snapshot()` 与
  `build_character_ability_scope_projection()` 的公开边界。

当前生产链已经确定为：

```text
complete raw snapshot
  -> RandomConfig family source projection / S8A source contract
  -> formal ability or status entry materialization
  -> _build_graph
  -> strict TaskGraphIR codec
```

不要阅读 S8A/S8B 历史验证器寻找 fixture，不要把 `StatusCallbackExecutor._execute_random_config_task()`
作为实现模板。只有上述符号暴露出具体未解析依赖时，才能定向申请 `context_gap` 或扩大一次阅读。

## 阶段结果

完成后，每个进入正式任务图物化范围的 `RandomConfig` 来源节点都具有一个严格、不可变、来源可逆
的加权候选契约：

```text
RandomConfig source occurrence
  -> ordered random_candidate branch[i]
  -> exact TaskList[i] child graph
  -> exact OddsList[i] numeric definition
```

来源目录中的每条直接 `RandomConfig` 记录还必须唯一归为：

1. 已绑定某个正式任务图位置并完成权重契约物化；或
2. 尚无正式 producer/entry，保留精确来源和后续依赖。

不得因为上游 entry 尚未准入就让真实来源记录从分母消失，也不得把“契约已物化”写成“随机分支已执行”。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 完成分母 | 当前完整 S8A 来源目录中 family 为 `RandomConfig` 的直接记录；祖先上下文单独计数 |
| 输入权威 | S8A 节点、分支及 raw snapshot 中精确的 `OddsList[i]` / `TaskList[i]` 位置 |
| 输出权威 | 任务图节点内一对一绑定 branch、weight numeric definition 和来源位置的加权选择契约 |
| 非输出 | RNG request、选中 child、mutation、event、settlement、replay 和 committed state |
| 正式调用者 | 本卡只迁移 task graph model/codec 与 materializer；runtime 调用者保持不变 |
| 后续归属 | 随机求值与原子执行归 S8C 后续卡；projectile、barrier、parallel 均不属于本卡 |

## 已确定语义

### 1. 位置绑定

- `TaskList[i]` 与 `OddsList[i]` 只按相同原始 ordinal 绑定。
- 禁止排序、去重、按表达式内容合并或按数值重新配对。
- 每个候选直接绑定对应任务图 branch 身份和对应数值定义身份，不能保存两组靠位置默契对齐的平行列表。
- 相同权重表达式出现在不同下标时，必须形成不同的来源 occurrence 和不同的定义身份。
- 分支来源精确指向 `TaskList[i]`，权重来源精确指向 `OddsList[i]`；二者必须属于同一文件、同一
  `RandomConfig` 父节点和同一内容指纹。

### 2. 权重含义

- 权重只表示“从候选中选择一个”的相对权重，不要求合计为 1，也不在 lowering 时归一化。
- 固定和动态表达式都复用现有严格数值表达式模型，不建立第二套 evaluator。
- 本卡不求值动态权重，也不生成 JSON float 形式的派生概率。
- 非法表达式结构、缺项、候选/权重数量不一致、空候选和无法反查的来源必须 fail-closed。
- 非负、全零和运行时动态值的最终准入由后续随机执行边界负责；本卡不得通过复制 evaluator 提前判断。

### 3. 类型化模型

生产模型必须表达以下事实，但具体类名可遵循现有 `rules/task_graph.py` 风格：

- 选择类型固定为“有权单选”；
- 所属任务图节点身份；
- 有序候选项；
- 每个候选项的 branch 身份、ordinal、权重数值定义身份以及精确来源；
- 稳定身份和严格 JSON codec。

允许使用独立的 typed selection/choice 模型，或给 branch 增加严格的可选选择元数据；无论采用哪种，
都必须满足以下不变量：

- 非随机节点不能携带加权选择契约；
- 随机契约中的 branch 必须真实存在于同一节点，且 kind 为 `random_candidate`；
- ordinal 必须从 0 连续排列，branch、choice、weight 三者 ordinal 一致；
- 每个权重定义在所属图中恰好存在一次，且 source 路径对应同一下标；
- 没有遗漏、额外、重复或跨节点引用；
- codec 拒绝未知字段、旧弱 payload、伪造 fingerprint、可变嵌套和错误成员类型；
- `to_json -> from_json -> to_json` 稳定一致。

不要直接复用当前只由“父 occurrence + 表达式内容”计算的数值身份来表示同一节点中的多个相等权重。
应增加字段 occurrence 身份，或以等价方式把精确 `OddsList[i]` 来源位置纳入身份。

## 实施范围

允许修改的生产文件：

- `rules/task_graph.py`
- `rules/__init__.py`
- `tbgd/task_graph_materializer.py`

仅在现有公开导出确有需要时，允许最小修改 `tbgd/__init__.py`。新增：

- `tools/validate_p9_s8c1_random_config_graph_contract.py`
- 仓库级 `live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_CONTRACT_ready_for_review.md`

禁止修改：

- `systems/task_graph.py`
- `systems/status_callbacks.py`
- `systems/rng.py`、`systems/target_random.py`
- `core/executor.py`
- scenario、UI、角色卡、状态和结算系统
- 总 checklist

若必须修改任一禁止文件才能形成可编译纵切，提交 `plan_mismatch`，不要扩大范围。

## 最早可编译纵切

1. 建立严格加权选择模型、身份和 codec，并用一个最小构造反例证明相同表达式不同位置不会合并。
2. 在 materializer 中只对一个实时选出的真实 `RandomConfig` 正例建立 branch-weight 绑定。
3. 通过同一生产路径扩展到完整实时分母，生成绑定与未绑定来源账本。
4. 完成调用者自审后才运行唯一主验证。

30 分钟内完成事实核对，45 分钟内应形成步骤 1-2 的可编译纵切；90 分钟仍未进入自审则停止并
提交 `context_gap` 或 `plan_mismatch`，不得继续扫描项目。

## 验收标准

| 目标 | 允许通过的条件 | 权威证据 |
|---|---|---|
| 实时分母完整 | family 窄投影的每条直接记录恰有一个绑定或精确未绑定归属；祖先上下文不混入 | source denominator ledger |
| 位置一一对应 | 每个正式节点的候选、branch、TaskList child 和 OddsList weight 按 ordinal 双向闭合 | graph binding ledger |
| 相等权重不合并 | 同节点相同表达式的不同下标仍有不同来源身份和定义身份 | one constructor/source probe |
| 相对权重诚实 | 非归一化真实来源保持原表达式，不要求总和为 1、不生成派生概率 | real source sample |
| 固定/动态兼容 | 两种真实表达式形状都进入同一数值定义契约 | numeric shape ledger |
| 生产边界严格 | 数量错配、缺失项、跨节点、跨来源、重复 ordinal 和伪造身份直接拒绝 | one minimal negative per invariant |
| 状态诚实 | 契约可物化，但节点仍为 S8C runtime deferred；无 RNG 或业务输出 | task graph disposition audit |
| 调用者不漂移 | 所有 `TaskGraphIR/Node/Branch` 正式构造和 codec 调用者已迁移或证明无需迁移 | `rg` 调用者清单与定向源码审计 |
| runtime 未变化 | 禁止文件零修改，现有执行行为不变 | diff scope audit |

`ready_for_review` 前必须同时满足以上九项；主验证绿色不能替代其中任一项。

## 最小负例

- 两个相同权重表达式被合并为一个字段来源或定义身份。
- `OddsList` 与 `TaskList` 数量不一致、为空或成员类型错误。
- 候选 ordinal 重复、跳号、交换，或 branch 与 weight ordinal 不一致。
- weight 引用缺失、跨图、跨节点、跨文件或来源指纹不一致。
- 非 `random_candidate` branch 被加入加权选择。
- 非随机节点携带选择契约。
- JSON 携带未知字段、旧 task payload、伪造身份或修改输入容器后改变模型。
- 完成模型物化后错误地把节点标成 executable/materialized runtime。

每条生产不变量只保留一个最小反例；不得扩张为组合矩阵。

## 验证与资源预算

固定顺序：

```text
compileall
秒级构造/来源负例
唯一主入口 validate_p9_s8c1_random_config_graph_contract
git diff --check
```

- 来源只建立一次完整 raw snapshot，再应用 `RandomConfig` family 窄投影；不得构建完整 Canonical IR。
- 主验证只 materialize 包含真实 `RandomConfig` 的正式窄 entry；不得先构建完整任务图目录再过滤。
- 不运行 S8A、S8B1-S8B6 或 S5D 主验证，不导入历史验证器 helper。
- 不运行 runtime direct，因为本卡明确要求 runtime 行为不变。
- 预算：主入口 90 秒，累计 3 分钟，峰值 512 MiB，evidence 512 KiB，验证器目标 420 非空行、
  硬上限 480 行。
- 预计达到任一硬上限 70% 时先收缩重复 evidence；不得压缩排版或拆第二个验证器规避预算。

## 停止条件

以下任一情况出现时不得自行裁决：

- 实时直接来源出现 `OddsList` / `TaskList` 之外的新 gameplay 同级字段。
- 真实来源表明不是“按下标一一对应、有权单选”的语义。
- 必须让 runtime 读取 raw/task payload 才能完成契约。
- 必须执行随机、修改原子提交或改变 replay 才能完成本卡。
- 完整来源中出现无法归入“正式绑定”或“精确未绑定依赖”的记录。
- 需要修改两个以上未列出的生产文件。

返回时说明事实、来源位置、影响和建议，不得伪造兼容或静默过滤。

## 交付记录

最终只能提交 `ready_for_review`、`blocked`、`plan_mismatch` 或 `context_gap`。不得勾总 checklist、
提交 Git 或进入下一阶段。报告除业务证据外记录：

- 首次完成事实核对和首次可编译纵切的时间；
- 主验证实际运行次数及每次原因；
- 实际读取的生产文件范围；
- 生产/验证改动行数、墙钟、峰值内存和 evidence 大小。

这些执行数据不改变业务通过标准，也不得为收集数据增加验证入口。

## 唯一执行清单

- [ ] 实时 `RandomConfig` 直接来源分母与祖先上下文已分离并完整列账。
- [ ] 每个正式随机节点已建立 branch、child、weight 和精确来源的一对一类型化绑定。
- [ ] 相同表达式不同位置保持独立身份，固定/动态权重均不被归一化或提前求值。
- [ ] 所有矛盾模型在生产边界 fail-closed，节点继续诚实保持 runtime deferred。
- [ ] 调用者、gap、唯一主验证和资源预算均完成自审并提交 `ready_for_review`。
