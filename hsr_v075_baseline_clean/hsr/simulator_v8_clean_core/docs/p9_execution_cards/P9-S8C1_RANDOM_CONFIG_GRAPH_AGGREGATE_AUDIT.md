# P9-S8C1 RandomConfig 任务图契约聚合审计执行卡

状态：`ready_for_execution`。

本卡是 P9 总计划 checklist 中 `P9-S8C1 RandomConfig 有序候选与权重任务图契约聚合` 的唯一直接执行入口。
它只做 **S8C1 聚合证明**：A/B/C 已分别验收，本卡不得新增业务行为，也不得借聚合之名进入 S8C runtime/RNG、
projectile/barrier/parallel、S5D2 transaction/replay 或 S9 以后阶段。

## 1. 固定基线与风险

- Stage：`P9-S8C1`
- 固定 base：`539b2e1b9a7dfb99a319bcda0249ec276b6847df`
- 风险模式：`STRICT`
- 硬前置：`P9-S8C1A`、`P9-S8C1B`、`P9-S8C1C` 均已在该 base 前完成独立验收并合并。
- 阶段结果：从当前实时类型化来源重新建立完整 `RandomConfig` 分母，并通过**公开生产 catalog 入口**证明
  每个正式 producer instance / formal task position 恰有一个严格 weighted-selection 契约；无正式 producer 的来源保持
  精确 `no_formal_producer`。本阶段仍不执行随机。
- 推荐执行能力：5.6 Sol / high；原因是本卡是来源完整性 + 正式 producer multiplicity 的 STRICT 聚合审计，
  不是普通单文件测试补充。

固定 base 不是“预期值”：执行开始和提交 ready-for-review 前都要验证 PR base 仍为该 SHA。若 base 被重定向，停止并
`needs_replan`，不得悄悄换基线。

## 2. 已确认生产事实

规划只依赖当前 base 的以下事实，不把历史报告数字写成完成门：

1. `rules/task_graph.py` 已有 `TaskGraphWeightedChoiceIR`、`TaskGraphWeightedSelectionIR`、严格身份/codec；这是 S8C1A
   已验收的类型权威。
2. `tbgd/task_graph_materializer.py::materialize_character_runtime_task_graph_catalog(...)` 是当前 ability + character-status
   联合正式 catalog 的公开生产入口；它在同一 `CharacterAbilityRawSnapshot` / S8A source authority 下安装正式 entry。
3. `tbgd/task_graph_materializer.py::_build_graph(...)` 仅当正式 control node family 为 `RandomConfig` 时调用现有唯一
   `_materialize_weighted_selection(...)`，其权重来源为 parent raw `OddsList[i]`，并保留 ordinal、branch、numeric definition、
   source occurrence 的一一身份。
4. S8C1C 已证明当前公开 entry 可闭合到完整 raw/S8A/source-ledger 分母，并修复了多 action level 共享来源时必须保留
   level-specific producer instance 的 multiplicity。**本卡必须重新从当前来源计算集合和 fingerprint；不得写死 S8C1C 当时的
   数量、角色、action ID、status ID、文件名或 fingerprint。**
5. `P9-S8C_HIT_BARRIER_RANDOM_SEQUENCE.md` 明确规定 S8C runtime/random、projectile、barrier、parallel 必须等 S8C1
   聚合验收后再重新拆卡；S5D2 完整 transaction/replay 又等待 S8 闭合。因此两者都不是本卡范围。

## 3. 唯一权威、调用者与证据边界

### 3.1 来源分母权威

当前正式 P9 角色来源的 signed `CharacterAbilityRawSnapshot` 与同 snapshot/fingerprint 的
`CharacterControlFlowContractCatalog`（S8A）是来源权威。

聚合验证必须在 task graph / Canonical IR 构建前，从当前 source scope 的 raw bytes / typed source projection 独立恢复
**direct `RandomConfig` occurrence denominator**。祖先 template/reference 上下文可以作为归属证据，但不得把祖先本身重复计入
 direct denominator。

### 3.2 正式 producer / formal position 权威

正式 producer 只能来自当前生产 lowering 已准入的正式 entry 与 formal task；producer instance 必须保留足以区分：

- action definition 的具体 definition/level instance；
- queue / standalone / nested ability 的正式实例（若当前 denominator 实际存在）；
- status callback 的正式 callback/task instance；
- template 内部 formal task 的来源 identity 与其具体 producer instance。

同一 raw source 被多个正式 producer instance 引用时，expected formal positions 必须保留 multiplicity，不能按 source key 去重。

### 3.3 公开生产调用链

真实 Direct/Catalog 必须驱动当前公开生产入口，最终经过：

```text
current typed source / narrow formal definitions
  -> CharacterControlFlowContractCatalog + CharacterAbilityRawSnapshot
  -> materialize_character_runtime_task_graph_catalog(...)
  -> _build_graph(...)
  -> existing RandomConfig weighted-selection materialization
  -> TaskGraphIR.weighted_selections
```

Direct/Catalog 不得直接调用 `_materialize_weighted_selection(...)` 冒充真实生产接线，不得手工拼
`TaskGraphIR` / `CanonicalIR` 冒充正式 producer。

### 3.4 独立证据要求

expected raw denominator、expected producer/formal-position denominator 与 actual graph/selection 集合必须分别生成，再做 exact set
comparison。不得把 actual graph 反推成 expected，也不得把 S8C1C validator 的输出直接当本卡 expected。

可以只读前序 validator 了解 narrow-build 环境，但本卡 validator **不得 import 前序 P9 validator 作为权威或代理执行前序主入口**。
生产 helper 可以复用；验证 helper 不能成为第二权威。

## 4. 唯一允许写集合

以下路径相对 `hsr_v075_baseline_clean/hsr/`：

1. 新增：
   `simulator_v8_clean_core/tools/validate_p9_s8c1_random_config_graph_aggregate.py`
2. 新增：
   `live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md`
3. 新增：
   `.github/workflows/p9-s8c1-pr-validation.yml`

除上述三项外，执行线程无生产写权限。

尤其禁止修改：

- `simulator_v8_clean_core/rules/task_graph.py`
- `simulator_v8_clean_core/tbgd/task_graph_materializer.py`
- 其他 `tbgd/`、`rules/`、`core/`、`systems/`、RNG、settlement、replay、scenario、UI
- `P9_CHARACTER_SHARED_MECHANISM_CLOSURE_TASK_PLAN.md`
- `CODEX_HANDOFF.md`
- `docs/p9_execution_cards/README.md`
- 本执行卡、其他执行卡和任何 checklist/governance 状态

若 aggregate 审计暴露 production mismatch，结论必须是 `needs_replan`，由规划线程确定回开 A/B/C 中的最小责任边界；
不得在本卡顺手改生产。

普通 validator、CI、报告问题只要仍在上述三项允许集合内，执行线程可直接修复，不需要重新规划。

## 5. 明确非目标

本卡不做：

- 随机权重求值、归一化、RNG request、choice 提交、选中 child 或 replay RNG 验证；
- projectile hit sequence、target iteration、barrier、parallel merge；
- mutation、event、settlement、audit/replay transaction 正例；
- S5D2 回验；
- S8C aggregate 或 S9-S20 任一业务实现；
- 重新运行 A/B/C 的历史主验证器作为“聚合通过”；
- 完整 Canonical IR / RuleBook 构建后再过滤；
- 固定角色、技能、action/status/template ID 或旧观察数量选样；
- 为 no-producer 来源制造 synthetic entry/graph。

## 6. 聚合完成条件

只有以下全部满足才允许 `ready_for_review`。

### 6.1 raw / S8A / source-ledger 闭合

1. 当前 direct `RandomConfig` raw denominator 由实时来源独立重建，输出 count + stable fingerprint。
2. raw denominator 与 S8A `RandomConfig` direct occurrence 集合双向 exact-equal。
3. production complete task-graph source ledger 中对应 source occurrence 与该 denominator 双向 exact-equal。
4. 每个 denominator occurrence **恰好**归入：
   - `formal_bound`；或
   - `no_formal_producer`。
   两集合并集等于 denominator 且交集为空。
5. `no_formal_producer` 必须带精确 source path/json path/content fingerprint、引用/祖先归属与唯一 deferred owner；不得仅用“没在 graph 中”推断。

### 6.2 formal producer / position multiplicity 闭合

1. expected formal positions 从正式 producer + formal tasks 独立建立，不从 actual graph 倒推。
2. action definition 必须枚举全部与当前 RandomConfig 来源相关的正式 definition/level instance；禁止 `min(level)`、first-only、
   source-key dedupe 或其他 multiplicity collapse。
3. actual formal positions 从联合生产 catalog 的 graph node + unique weighted selection 独立建立。
4. expected formal-position set 与 actual formal-position set exact-equal，并输出 count + stable fingerprint。
5. 同一 raw occurrence 对应多个正式 producer instance 时，每个 instance/entry/formal task 位置必须独立存在。

### 6.3 weighted-selection 一一契约

对每个 actual formal `RandomConfig` graph node：

1. 恰有一个 `TaskGraphWeightedSelectionIR`，其 node/source occurrence/family 与 graph node 一致。
2. choices ordinal 必须严格 `0..n-1`，与 source `TaskList/ConfigList` branch 顺序、graph branch、`OddsList[i]` weight definition 一一对应。
3. 每个 choice 的 branch id、numeric definition id、weight occurrence、精确 `OddsList[i]` source 均可双向重算闭合。
4. 固定权重和动态 numeric expression 保留原始 expression 结构；不同 ordinal 即使数值/表达式相等也必须保持独立 source occurrence、definition 和 choice identity。
5. graph 中不得有 orphan weighted selection；非 `RandomConfig` node 不得携带 weighted selection。
6. source fingerprint、ordinal/branch/weight identity 任一冲突必须 fail-closed，而不是跳过该项或降级成 no-producer。

### 6.4 公开入口与行为不变

1. Direct/Catalog 的正式 materialization 必须走 `materialize_character_runtime_task_graph_catalog(...)`；不得以单 entry/private helper
   结果替代联合 catalog 完成结论。
2. 若当前 denominator 中同时存在不同 entry/producer class，Direct 动态各选最小真实样本，证明单 entry 观察与联合 catalog 对同一
   formal position/selection 完全一致；某类实时 denominator 为零时输出 `zero_by_denominator`，不得造 fixture 冒充。
3. `full_canonical_ir_build_count=0`：source/family/action/status narrowing 必须在昂贵 IR 构建前完成。
4. 本验证过程不得进入 runtime executor，不请求/消费 gameplay RNG，不产生 mutation/event/settlement/replay；报告明确这些仍 deferred。
5. 不重跑 A/B/C 历史主入口；本卡只证明当前整合后的公开生产不变量。

## 7. Fast 与负例

新 validator 提供互斥参数：`--fast`、`--direct`、`--catalog`。

`--fast` 不读取全 TBGD，只验证 aggregate auditor 自身最小 fail-closed 机械边界，不复制业务 materializer：

- expected/actual formal-position 少一个 instance 时 exact-set audit 必须失败；
- 同一 source occurrence 对应两个 producer instance 时，按 source key 去重后的错误 actual 必须失败；
- denominator occurrence 同时落入 formal_bound 与 no_formal_producer 必须失败；
- orphan selection / duplicate node-selection identity 必须失败；
- source fingerprint 或 `OddsList[i]` ordinal identity 被篡改时必须失败。

每类不变量只保留一个最小反例。Fast fixture 不得被报告成真实 gameplay 证据。

## 8. Direct

`--direct` 使用当前真实来源，先动态发现 denominator/producer class，再选最小代表；禁止固定业务 ID。

Direct 至少证明：

- 联合公开 catalog 确实经过 ability/status 共用的当前 materializer；
- 每个实时存在的 producer class 至少有一个真实 formal position 完成 node -> selection -> choices -> branch/child/weight/source 链；
- 同一样本的单 entry（若生产有公开单-entry query）与联合 catalog 结果完全一致；
- 一个真实非 `RandomConfig` formal node 没有 weighted selection；
- 不执行 RNG/runtime。

Direct 不是完整 denominator 完成证据。

## 9. Catalog

`--catalog` 才承担 S8C1 聚合完整性：

- 从实时 typed source 独立重建完整 direct RandomConfig denominator；
- 与 S8A/source ledger 双向闭合；
- 完整分类 formal_bound / no_formal_producer；
- 枚举所有当前相关正式 producer instance 与 formal task position；
- expected/actual formal-position exact-equal；
- 每个 actual RandomConfig node 恰有一个 weighted selection 且 ordinal contract 双向闭合；
- 无 synthetic producer、无 orphan、无 denominator 丢失；
- `full_canonical_ir_build_count=0`。

Catalog 的完成条件按集合/fingerprint 判断，不按旧数量判断。报告可以记录实际 count/fingerprint 供独立验收复现。

## 10. 命令

从仓库根目录串行运行。执行报告必须记录退出码、墙钟和最大 RSS；命令本身不得改成等价但更弱的检查。

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
  hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/tools/validate_p9_s8c1_random_config_graph_aggregate.py

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --fast

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --direct

PYTHONPATH=hsr_v075_baseline_clean/hsr PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m simulator_v8_clean_core.tools.validate_p9_s8c1_random_config_graph_aggregate --catalog

git diff --check 539b2e1b9a7dfb99a319bcda0249ec276b6847df HEAD
```

禁止用 `TBGDLowering.build()` 全量 Canonical build 之后再筛 RandomConfig。

## 11. PR-scoped CI 与资源预算

新增 `.github/workflows/p9-s8c1-pr-validation.yml`，仅 `pull_request` 触发，paths 只覆盖：

- 本卡新增 validator；
- 本卡 execution report；
- 该 workflow 自身。

CI 不得扩大成 P9 历史套件。串行执行第 10 节 compile/Fast/Direct/Catalog 和固定 base 的 `git diff --check`。

预算：

- Fast：目标 < 5s，硬上限 30s，RSS < 256 MiB；
- Direct：硬上限 120s，RSS < 1.0 GiB；
- Catalog：硬上限 180s，RSS < 1.25 GiB；
- 单个 validator 进程 RSS 硬上限 1.25 GiB；
- PR workflow 总 timeout `< 8 min`；
- 持久 evidence/report 目标 < 1 MiB，不写完整 Canonical IR/raw dump/task graph dump。

达到预算先检查是否发生 full build、重复 source parse 或后过滤；不得删谓词、缩 denominator 或改成 warning 过门。

## 12. 执行报告

提交：

```text
hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md
```

报告只记录实际事实：

- fixed base、code-validation head、最终 report head；
- changed files；
- Fast/Direct/Catalog 命令、退出码、wall/RSS；
- raw denominator count/fingerprint；
- formal_bound/no_formal_producer count 与精确分类摘要；
- expected/actual formal-position count/fingerprint；
- producer classes 与动态 Direct 样本来源 identity；
- `full_canonical_ir_build_count`；
- CI run/job URL；
- deferred：runtime RNG/choice、S8C、S5D2 transaction/replay、settlement/audit/replay。

报告不得声称包含自身 commit SHA；最终 head 由 ready-for-review handoff 单独给出。

## 13. ready_for_review 交付格式

全部条件满足后，在同一 Draft PR 留结构化评论：

```text
[HANDOFF:REVIEW]
role=EXEC
stage=P9-S8C1
conclusion=ready_for_review
base=539b2e1b9a7dfb99a319bcda0249ec276b6847df
code_validation_head=<sha>
final_head=<sha>
card=hsr_v075_baseline_clean/hsr/simulator_v8_clean_core/docs/p9_execution_cards/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_AUDIT.md
report=hsr_v075_baseline_clean/hsr/live_validation_reports/P9-S8C1_RANDOM_CONFIG_GRAPH_AGGREGATE_execution_report.md
validation=<Fast/Direct/Catalog/CI summary>
deferred=<runtime RNG/S8C/S5D2...>
next=REVIEW
```

执行线程不把 PR 标记 ready、不勾 checklist、不合并、不推进 S8C。

## 14. 停止条件

出现以下任一情况立即 `needs_replan` 并给出可复现 finding：

- aggregate 发现需要修改任何生产文件才能闭合；
- 当前来源出现新的正式 entry kind / producer domain，超出 ability/status 当前公开 catalog 权威；
- raw、S8A、source ledger 三个 denominator 无法在当前生产事实下 exact-equal；
- formal producer multiplicity 无法由现有正式定义唯一恢复；
- no_formal_producer 的唯一 owner/source closure 无法证明；
- 必须执行 RNG/runtime 才能证明 S8C1 契约；
- 必须完整 Canonical build 或超出资源预算才能完成当前完整 denominator；
- 当前 PR base 不再是固定 SHA。

只有外部来源不可访问、GitHub/CI 权限或不可控基础设施问题才是 `blocked`。普通 validator/CI/report bug 在允许写集合内直接修。

## 15. 验收摘要

独立验收不能只看 `ok=true`。至少复核：

- 实际 changed files 严格等于本卡允许集合；
- raw/S8A/source-ledger expected 集合来源彼此独立；
- expected formal positions 不是从 actual graph 倒推；
- producer instance multiplicity 未按 source/action level 折叠；
- Direct/Catalog 真正走联合公开生产 catalog；
- no-producer 没有 synthetic formal graph；
- 负例真的 fail-closed；
- no full Canonical build、no runtime RNG；
- 固定 base diff-check 与 PR-scoped CI 真实通过；
- S8C1 之外的 checklist 仍未推进。
