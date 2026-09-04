# P9-S8C1C 其余公开 entry 与完整 RandomConfig 来源分母闭合执行卡

> 状态：`accepted`
>
> 验收检查点：PR #3 已完成独立集中审查。生产 entry-neutral `RandomConfig` attachment、完整 raw/S8A/source-ledger 来源分母、level-specific formal-position multiplicity、STRICT 共源漏 level 负例、S8C1B 回归和最终执行 head 的 PR CI 均通过；S8C1 聚合、S8C、S5D2、runtime/RNG 继续 deferred。本卡不再是可执行入口。
>
> 风险模式：`STRICT`
>
> 本文件是本轮 PR 的**唯一执行任务权威**。执行层不得从旧规划对话、PR 评论或未列入本卡的后续阶段自行扩展范围。
>
> 固定基线：`master@f0701b69911d28451f560e3bed354ead355a2865`
>
> 前置检查点：P9-S8C1A、P9-S8C1B 已 accepted；本卡只执行 P9-S8C1C，不执行 S8C1 聚合、S8C 或 S5D2 回验。

## 1. 当前仓库已确认事实

规划以当前 `master` 的源码和权威文档为准，已确认：

1. `P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md` 中：
   - S8C1A 已完成；
   - S8C1B 已完成；
   - **S8C1C 是当前首个尚未完成且依赖已满足的 S8C1 子阶段**；
   - S5D2 仍明确等待整个 S8 后再做 transaction/replay 回验，不能提前。
2. `rules/task_graph.py::EntryKind` 当前只有两个正式公开 entry kind：
   - `ability_phase_callback`；
   - `status_callback`。
   当前没有第三种“template runtime entry”。本卡不得为了让 shared template 看起来可执行而伪造新的 entry kind。
3. S8A-R1 已把完整角色 ability snapshot、document `GlobalTemplates` / local `TaskListTemplate`、以及 `Config/ConfigGlobalTaskListTemplate` shared template 的内部控制节点、分支、template definition/reference 纳入 `CharacterControlFlowContractCatalog`；S8C1C 不重新发明第二套生产 raw 扫描权威。
4. S8B1-R2 已要求正式 ability task lowering 消费 S8A branch/template reference 权威，把可达模板子树展开成独立正式 task 实例，同时保留真实模板来源位置。
5. S8B4A 已建立角色 status callback 正式目录；`materialize_status_callback_task_graph(...)` 和 `materialize_character_runtime_task_graph_catalog(...)` 是现有正式 status/联合目录入口。
6. S8C1B 已在共享 task graph materializer 中建立 `RandomConfig` 的 weighted selection 物化，但当前 `_build_graph(...)` 只在 `entry_kind == "ability_phase_callback"` 时附着 weighted selection；`TaskGraphIR` 也仍拒绝非 ability entry 携带 weighted selection。这正是本卡需要闭合的已知剩余公开入口边界。
7. `TaskGraphCatalogIR.source_dispositions`、`formal_materialization_ids` 与正式 graph/source record 已有双向闭包检查；本卡应复用该账本作为生产来源归属基础，而不是另建平行来源数据库。

以上事实只是本卡起点；执行中若当前分支事实已变化，先对照固定基线与本 PR diff。只有出现实质设计/权威冲突时才 `needs_replan`。

## 2. 阶段目标

S8C1C 的唯一阶段结果是：

> **补齐现有其余正式公开 entry 的 RandomConfig weighted-selection 物化，并对当前完整角色控制流来源中的每一个直接 RandomConfig occurrence 建立可复现的一对一来源分母结论：要么由现有正式 ability/status entry 唯一绑定，要么被精确证明当前没有正式 producer；不得遗漏、伪造 producer 或把 no-producer 定义宣称为 executable。**

必须同时满足：

1. 任一现有正式 `TaskGraphIR` 中，只要 node 的 `source_family == "RandomConfig"`，就恰有一个同 node 的 `TaskGraphWeightedSelectionIR`；非 RandomConfig node 不得获得 selection。
2. ability 与 status 两种当前 `EntryKind` 共用同一套 `_materialize_weighted_selection(...)`、同一 signed `CharacterAbilityRawSnapshot`、同一 S8A branch topology、同一 `lower_numeric_expression(...)`；不得复制一份 status 专用 Odds lowering。
3. status 单 entry 与生产联合目录对同一正式 callback 的 graph/selection 结果一致；ability 现有 S8C1B 行为保持一致。
4. 对当前完整直接 RandomConfig 来源分母中的每个 occurrence，最终只能归为：
   - `formal_bound`：进入一个或多个合法正式 materialization，且每个正式 graph 位置都有唯一 weighted selection；或
   - `no_formal_producer`：当前 accepted ability/status 正式入口拓扑确实不可达，保留精确 source path、JSON path、family、文件 fingerprint、所属 template/reference 闭包以及唯一后续责任，不创建 synthetic graph/node/entry。
5. `no_formal_producer` 不是“允许遗漏”。若来源在 accepted S8A + 正式 task topology 中可达，却没有 materialization/selection，必须失败，不能改名为 no-producer 通过。
6. 完整分母的当前数量只能写入 evidence/report；不得把角色数、RandomConfig 数量、ID、文件名、固定 hash 或某个样本写成生产通过条件。

## 3. 非目标 / deferred

本卡明确**不做**：

- RandomConfig 随机抽样、概率比较、动态权重求值、RNG 消耗或 RNG ledger；
- projectile hit sequence、barrier、parallel template 执行、scheduler/timeline、等待语义；
- mutation、settlement、audit、replay、scenario 或 BattleState 纵切；
- S8C1 聚合勾选、S8C 主阶段、S5D2 transaction/replay 回验；
- 新增第三种 template runtime entry 或让无 producer 的 shared template 单独“可执行”；
- 改写 S8A 来源分类、S8B1-R2 正式拓扑 lowering、S8B4 status callback 来源分母；
- 扫描怪物、装备、关卡等不属于当前角色 snapshot 的外部内容域；
- 修改总 checklist、`CODEX_HANDOFF.md`、执行卡索引或任何 accepted 历史卡状态。

## 4. 唯一权威来源与正式调用者

### 4.1 来源分母权威

生产来源权威只能是：

- `tbgd/character_ability_scope.py` 产生的完整 `CharacterAbilityRawSnapshot`；
- `tbgd/character_control_flow_contracts.py::build_character_control_flow_contract_catalog(...)` 产生的 accepted S8A `CharacterControlFlowContractCatalog`；
- 其已纳入的 document/local/shared template definition/reference 与内部控制节点；
- 固定 TBGD submodule 中由上述生产 API 声明读取的当前 source bytes。

验证器可按 STRICT 要求独立遍历同一真实 snapshot 与 accepted shared-template 来源，重建 **RandomConfig-only** oracle 来核对生产目录；但该独立遍历只能用于验证，不能成为第二个生产 compiler/parser 权威。

### 4.2 正式 graph producer

当前合法 producer 只有现有公开入口：

- `materialize_ability_phase_task_graph(...)`；
- `materialize_ability_task_graph_catalog(...)` / `_materialize_ability_entries(...)`；
- `materialize_status_callback_task_graph(...)` / `_materialize_status_entries(...)`；
- `materialize_character_runtime_task_graph_catalog(...)` 的 ability + status 联合生产目录；
- 最终共享 `_materialize_entry(...) -> _build_graph(...)`。

不得新增 parallel/private materializer 来绕开这些入口。

### 4.3 weighted / numeric 权威

- IR、identity、codec：`rules/task_graph.py` 中 S8C1A accepted contract；
- `OddsList[i] -> numeric expression`：`tbgd/expression_lowering.py::lower_numeric_expression(...)`；
- branch：S8A/S8B 已接受的正式 `TaskGraphBranchIR` 拓扑；
- exact source bytes：传入 materializer 的同一 `CharacterAbilityRawSnapshot`。

### 4.4 正式消费者

本卡只形成/加强 compiler 侧 `TaskGraphIR` / `TaskGraphCatalogIR` 契约。现有 runtime 对 RandomConfig 仍按 S8C deferred；本卡不得新增 RNG/runtime consumer。

## 5. 允许写集合

执行层只能修改以下路径：

1. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py`
   - 仅用于把 weighted-selection 图不变量从 ability-only 收口为当前全部合法 `EntryKind`，以及若现有 source disposition 无法无歧义表达完整 producer/no-producer 归属时做**最小、类型化、单一权威**扩展。
2. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py`
   - 仅用于现有公开 ability/status materializer 的 entry-neutral RandomConfig 附着、完整 source/formal ledger 闭包和必要 fail-closed。
3. `hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py`
   - 本卡唯一专项 validator。
4. `hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md`
   - 本卡唯一执行报告。
5. `.github/workflows/p9-s8c1c-pr-validation.yml`
   - 可新增/修复本 PR 专项 CI；仅允许承载本卡已规定的验证。

不得修改 `tbgd/lowering.py`、`tbgd/character_control_flow_contracts.py`、`character_ability_scope.py`、`systems/`、RuleBook runtime 查询语义或其他生产文件。

若真实闭合必须改变 S8A 来源分类/模板解析、S8B 正式 task lowering、增加新 `EntryKind`、增加新的 runtime producer/consumer，返回 `needs_replan`；这不是普通实现细节。

## 6. 实现边界与必须成立的生产不变量

### 6.1 entry-neutral RandomConfig attachment

在共享 `_build_graph(...)` 中，对所有当前合法正式 entry 一视同仁：

- `control is not None and control.family == "RandomConfig"` 时使用现有 `_materialize_weighted_selection(...)`；
- 不再以 `ability_phase_callback` 作为附着前提；
- `TaskGraphIR` 不得继续拒绝 status weighted selection；
- 完成后，**每个正式 graph 中的 RandomConfig node 恰有一个 selection**，不能只检查“selection 若存在则合法”。

如果最小模型检查可以直接由现有 `TaskGraphIR.__post_init__` 完成，应优先在那里建立 fail-closed；不得把“正式 RandomConfig node 漏 attachment”仅留给 validator 事后发现。

### 6.2 branch / Odds / source 一对一保持

必须继承 S8C1A/B 的全部既有约束：

- `TaskList[i]` 与 `OddsList[i]` ordinal 一一对应；
- 相同数值的多个 Odds 位置仍是不同 source occurrence / numeric definition / choice；
- selection parent source 与 node source 完全一致；
- `OddsList[i]` source 从同一 signed source bytes 的 parent JSON path 派生；
- branch 数量、顺序、branch id 与 weighted choice 完全一致；
- 不做归一化、不求值、不舍弃零值/相同值位置；
- source bytes 缺失、路径不一致、长度不一致、fingerprint 冲突均 fail-closed。

### 6.3 status 与联合目录一致性

动态真实 status callback 若包含可达 RandomConfig：

- `materialize_status_callback_task_graph(...)` 结果必须携带 selection；
- `materialize_character_runtime_task_graph_catalog(...)` 中同一 callback 的 graph/selection 必须结构一致；
- callback taskless 时继续不造 synthetic graph；
- callback 上游存在 deferred obligation 时，不得因此删除其已准入的真实 RandomConfig 结构。

### 6.4 GlobalTemplates / shared templates

S8A-R1 与 S8B1-R2 已决定 template 来源和可达实例化权威。本卡只能遵循：

- 若 document `GlobalTemplates`、local template 或 shared template 内的 RandomConfig 经 accepted template reference 从 ability/status 正式入口可达，则它是该正式 graph 中的真实 task 实例，必须获得 weighted selection；
- 同一 template source 被多个正式 reference path 展开时，source occurrence 可相同，但正式 graph/task/node 位置保持各自身份；每个正式位置都必须闭合；
- 若某个 shared/document template 定义当前没有任何合法正式 ability/status producer，则只做 `no_formal_producer` 精确归账，不创建 template entry、空 graph 或假 task；
- parallel template 的**执行**仍属于 S8C；本卡只处理其当前来源/producer 归属，不执行 parallel。

### 6.5 完整 RandomConfig 来源分母账本

最终 production + STRICT validation 必须能对当前完整来源做双向对账：

- independent RandomConfig denominator occurrence -> 恰有一个 production source record；
- production RandomConfig source record -> 恰对应 denominator occurrence；
- formal-bound source -> `formal_materialization_ids` 非空，并能追到 graph node + unique selection；
- graph RandomConfig node/selection -> 反向追到已签名 source record；
- no-producer source -> `formal_materialization_ids` 为空且正式入口可达性证明为空，同时 template definition/reference closure 和后续 owner 仍明确；
- 不允许 orphan selection、dangling materialization、未归属 gameplay source、重复 producer 身份或“验证器白名单式 no-producer”。

若现有 `TaskGraphSourceDispositionIR` + accepted source catalog 已足够无歧义表达上述事实，不要新增模型；若不足，只允许在 `rules/task_graph.py` 做最小 typed extension，且该 extension 必须由共享 catalog construction 唯一生成、codec/fail-closed 完整，不得由 validator 单独维护。

## 7. 明确禁止项

- 禁止硬编码角色 ID、ability 名、status 名、template 名、JSON path、当前数量或特定 source hash 作为生产逻辑。
- 禁止用手工构造/合成 CanonicalIR 冒充 Direct/Catalog 真实来源证明。
- 禁止通过全仓库 grep/raw 全扫建立第二套生产来源权威。
- 禁止复制 `lower_numeric_expression`、branch lowering、template resolver 或 status task lowering。
- 禁止把 no-producer source 标为 `materialized` / executable。
- 禁止恢复旧 status interpreter/private lowering 作为第二 graph authority。
- 禁止弱化 S8C1A 的 identity/codec/source 检查或删除 S8C1B 的 action invariants 来让新测试通过。
- 禁止新增 runtime RNG、随机选路、概率归一化或 replay 语义。
- 禁止修改本卡、P9 checklist、卡索引、handoff 或 accepted 历史报告来“完成”阶段。

## 8. 执行层普通修复权限

以下问题**不需要重新规划**，执行层可在本卡允许写集合内直接修复并提交到同一 PR：

- 本卡生产代码的普通 bug、类型/codec/fail-closed 问题；
- 本卡专项 validator 的错误、漏判、资源问题或入口包装问题；
- `.github/workflows/p9-s8c1c-pr-validation.yml` 的 YAML、checkout、submodule、命令、timeout、路径触发等 CI 问题；
- execution report 的事实/格式/命令记录问题；
- 为让本卡已授权 Fast/Direct/Catalog 在 CI 中真实运行所需的非语义环境修复。

这些修复不得扩大生产范围、改变来源权威、引入第三种 entry 或弱化验证。超出允许写集合或改变上述设计边界才 `needs_replan`。只有真实外部权限/服务/基础设施阻断，且已给出可复现工具错误，才 `blocked`。

## 9. 验证计划

专项入口固定为：

```text
simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure
```

validator 必须支持 `--fast`、`--direct`、`--catalog`，且输出结构化 JSON 摘要；evidence 写 `/tmp`，不得提交大 dump。

### 9.1 Fast

在生产自审后串行执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/rules/task_graph.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tbgd/task_graph_materializer.py \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1c_remaining_entry_random_config_source_closure.py

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1a_weighted_selection_ir

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1b_action_entry_weighted_selection --fast

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --fast

git diff --check f0701b69911d28451f560e3bed354ead355a2865 HEAD
```

说明：S8C1B 的 **Direct** 历史检查包含“status 尚未附 weighted”的当时 deferred 事实，本卡正要合法改变该事实，因此不得机械运行旧 B Direct 并为了让它通过而回退生产；action 回归由本卡 Direct 自己证明。B `--fast` 仅在其当前谓词仍不依赖该历史 deferred 事实时保留；若实际 validator 证明连 Fast 也含过时 status 谓词，可在报告中给出精确谓词并跳过该单条，不能修改 accepted B validator 迎合本卡。

Fast 目标预算：总墙钟 `< 45s`，单进程 peak RSS `< 512 MiB`，输出 `< 256 KiB`。

### 9.2 最小负例

`--fast` 至少覆盖以下新不变量，每类只保留一个最小反例：

1. status `TaskGraphIR` 中存在 `RandomConfig` node 但缺 weighted selection -> production model/construction 必须拒绝；
2. status RandomConfig 的 `OddsList` 与 branch 数量/ordinal 不闭合 -> fail-closed；
3. selection/source fingerprint 或 parent occurrence 与 node 不一致 -> fail-closed；
4. 把一个实际从 accepted formal entry 可达的 RandomConfig 强行归成 no-producer -> denominator audit 必须失败；
5. 一个真实 no-producer source 被伪造 synthetic materialization/entry -> 必须失败。

不得用大量 fixture 堆矩阵；已有 S8C1A/B 覆盖的纯 identity/codec 负例不重复复制。

### 9.3 Direct：真实公开 entry 纵切

生产自审和 Fast 全绿后执行一次：

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --direct
```

Direct 必须从当前真实 signed snapshot / production source catalog **动态发现**来源，不得写死业务 ID：

- 对 denominator 中每一种实际存在的 formal producer class，动态选至少一个真实 occurrence；
- 若 status callback 中存在 formal-bound RandomConfig，必须证明 `status_callback source -> formal task identity -> graph node -> existing branch -> OddsList[i] source -> numeric definition -> choice -> selection` 全链，并证明 single-status entry 与联合生产目录一致；
- 若可达 document/local/shared template 内存在 formal-bound RandomConfig，必须动态证明至少一个真实 reference path 下的 template source identity 与 formal graph position identity均保留；
- ability action 至少动态回归一个真实 formal-bound RandomConfig，证明 S8C1B action 结果未被改变；
- 至少动态证明一个非 RandomConfig ability/status node 没有 selection。

若某个 producer class 在当前完整 denominator 中真实为零，Direct 必须输出由 denominator 得出的 `zero_by_denominator` 证据，而不是造 synthetic Direct 样本。

Direct 不运行 BattleState、不抽 RNG、不做随机选择。目标预算：墙钟 `< 120s`，peak RSS `< 1 GiB`，输出 `< 512 KiB`。

### 9.4 Catalog：完整来源分母 STRICT 证明

因为本卡声称“完整 RandomConfig 来源分母闭合”，必须执行 `catalog`：

```bash
PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1c_remaining_entry_random_config_source_closure --catalog
```

Catalog 必须：

1. 从完整角色 `CharacterAbilityRawSnapshot` 与 S8A 已声明的 shared-template 来源独立重建 **RandomConfig-only** raw denominator；
2. 在 source/IR 构建前尽可能先按 family=`RandomConfig`/必要 reference closure 过滤，不能先生成全量 Canonical IR 再筛；
3. 与 `CharacterControlFlowContractCatalog` 中 RandomConfig control occurrence 做双向身份比较；
4. 对所有 denominator occurrence 动态归类 `formal_bound` / `no_formal_producer`，并与 production task graph source/formal ledger 双向核对；
5. 对每个 formal-bound occurrence 核实每一个正式位置恰有一个 weighted selection；
6. 对每个 no-producer occurrence核实没有合法 ability/status 可达实例、没有 synthetic graph，并保留 template/reference closure 与后续责任；
7. 计数、分类数量、代表来源只作为 evidence，不作为固定通过条件。

允许复用生产 lowering 的窄投影/正式 task 构造；禁止调用完整 `TBGDLowering.build()` 形成全世界 CanonicalIR/RuleBook 后再过滤。要求 `full_canonical_ir_build_count=0`。

Catalog 目标预算：墙钟 `< 180s`，peak RSS `< 1.25 GiB`，输出 `< 1 MiB`，临时 evidence `< 4 MiB`。

### 9.5 Full

本卡**不运行 Full**。它不是 S8C1 聚合/S8C 运行时收口，也不重跑 P1-P8 或 P9 历史聚合。

## 10. PR CI 与资源预算

允许新增 `.github/workflows/p9-s8c1c-pr-validation.yml`，要求：

- 只用 `pull_request` 触发；不得 `push`、`schedule`、`workflow_dispatch`；
- `permissions: contents: read`，不得写回仓库、评论、标签或自动合并；
- `paths` 仅覆盖本卡允许写集合中的 production/validator/report/workflow 路径；
- `actions/checkout@v4`，`fetch-depth: 0`，`submodules: true`；
- 串行运行 scoped compile、仍适用的 S8C1A focused、S8C1B Fast、S8C1C Fast/Direct/Catalog、以及 base->HEAD `git diff --check`；
- diff check 必须使用 PR base SHA 与当前 CI checkout HEAD，不能检查空 working tree；
- 不安装无关依赖、不下载额外数据、不运行 full Canonical/runtime suite；
- job `timeout-minutes <= 8`；各命令用 `/usr/bin/time -v` 记录墙钟/RSS，Direct/Catalog 用 `timeout` 硬门；
- CI 中任一预算/断言失败均不得改成 warning 或删除检查。

最终可接受 CI 预算：job 总墙钟 `< 8min`；任一 Python validator peak RSS `< 1.25 GiB`；提交产物不得包含 raw/full dump。

## 11. execution report

固定报告路径：

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md
```

报告必须包含：

- fixed base SHA；
- 实际 production code validation SHA（先完成代码/validator/CI 前的可复现 head）；
- 最终 PR head 在回复中单独给出；报告正文不得伪造包含自身 commit 的“自引用 SHA”；
- 实际 diff 文件列表；
- Fast / Direct / Catalog 每条命令、exit code、elapsed、peak RSS；
- 当前完整 RandomConfig denominator 的动态数量和 fingerprint（仅 evidence）；
- `formal_bound` / `no_formal_producer` 数量与分类规则；
- 至少一个真实 status/template/action 纵切摘要（仅实际存在的 class；零类写明 `zero_by_denominator`）；
- no-producer 的精确来源闭包结论，不得宣称 executable；
- 最终 PR-scoped CI run/job 链接、checkout SHA 与结果；
- 明确 deferred：RNG evaluation、parallel/projectile/barrier、S8C、S5D2、settlement/audit/replay。

## 12. ready_for_review 交付格式

只有全部生产谓词、Fast、Direct、Catalog、最终 PR CI 都通过后才能回传：

```text
status: ready_for_review
stage: P9-S8C1C
pr: <PR URL>
base: f0701b69911d28451f560e3bed354ead355a2865
code_validation_head: <SHA>
final_pr_head: <SHA>
card: hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE.md
report: hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1C_REMAINING_ENTRY_RANDOM_CONFIG_SOURCE_CLOSURE_execution_report.md
ci: <run URL / job / success>
fast: <commands + results>
direct: <real source summary + results>
catalog: <complete denominator summary + results>
deferred: <explicit list>
```

执行层不勾 checklist、不改 handoff/index、不合并 PR、不推进 S8C1 aggregate/S8C。

## 13. 独立验收门槛

独立验收只有在以下全部成立时可 `accepted`：

```text
current_entry_kind_denominator_is_ability_and_status_only=true
all_formal_random_config_nodes_have_exactly_one_weighted_selection=true
non_random_config_nodes_have_no_weighted_selection=true
ability_and_status_share_one_weighted_materialization_authority=true
status_single_entry_and_combined_catalog_are_identical=true
action_s8c1b_contract_is_preserved=true
random_config_raw_denominator_is_independently_reproducible=true
s8a_random_config_source_denominator_is_bidirectionally_complete=true
every_denominator_occurrence_is_exactly_formal_bound_or_no_formal_producer=true
formal_bound_sources_close_to_every_formal_graph_position_and_selection=true
no_formal_producer_sources_have_no_synthetic_entry_or_graph=true
template_source_identity_and_formal_instance_identity_are_not_collapsed=true
odds_branch_source_and_numeric_identity_are_one_to_one=true
source_fingerprint_mismatch_fails_closed=true
full_canonical_ir_build_count=0
runtime_rng_behavior_changed=false
s8c_or_s5d2_claimed_complete=false
```

验收必须检查实际 diff、真实 Direct/Catalog evidence 与 CI；不能只看报告自述。

## 14. stop / replan 规则

以下情况返回 `needs_replan`，不要自行扩大范围：

- accepted S8A `CharacterControlFlowContractCatalog` 被真实独立 denominator 证明漏掉 RandomConfig 来源或 template closure，必须改 S8A 来源权威；
- accepted S8B 正式 task topology 被证明漏掉本应可达的 template/status task，必须改 lowering；
- 闭合需要新增第三种 `EntryKind`、新的 template runtime producer、RuleBook/runtime consumer；
- 需要修改本卡允许写集合之外的生产文件；
- 需要提前实现 RNG/parallel/projectile/barrier/S8C 才能证明本卡契约。

以下不属于 replan：本卡代码 bug、测试 bug、CI YAML/checkout/submodule/timeout、报告错误、当前 validator 性能优化；按第 8 节在允许写集合内直接修复。

真实外部权限、GitHub Actions 服务或 pinned submodule 无法访问且经实际重试仍阻断时才 `blocked`，并附具体命令/工具操作与错误。

## 15. 预计执行成本

- 推荐执行：5.6 Sol / `high` 或 `max`，单 PR 串行。
- 规划估算：实现、自审、Fast/Direct/Catalog、报告及一轮 CI 合计约 **60–90 分钟**；若 CI 暴露普通可修问题，继续在本 PR 修复，不重新规划。
