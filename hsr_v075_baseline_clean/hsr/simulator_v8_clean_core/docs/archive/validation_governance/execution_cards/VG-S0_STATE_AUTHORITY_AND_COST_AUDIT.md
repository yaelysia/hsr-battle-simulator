# VG-S0 状态权威与验证成本审计执行卡

## 执行配置

- 基线提交：`a11637d`。
- 轨道：验证治理与状态完整性回正。
- 推荐模型：GPT-5.6 Sol。
- 推荐推理等级：`max`。
- 推荐模式：普通模式，不使用 Goal 自动跨阶段。
- 执行归属：规划/验收线程完成只读审计；本卡不交给生产代码执行线程。
- 工作区现有两个无关 UI 草稿不属于本卡，禁止修改、删除或提交。

## 1. 背景

当前项目的验证成本已经影响正常开发：

- 大量阶段验证重复构建完整 Canonical IR 和 RuleBook。
- 重验证内存和 IO 峰值高，失败后常需整轮重跑。
- 新机制需要编写大量独立验证编排，代码和 token 成本过高。
- 部分历史验证固化旧缺口或旧接口，代码正确演进后仍会失败。
- 验证虽然很重，验收代码审查仍能发现它没有覆盖的通用性、权威归属和提交原子性
  问题。

本阶段不直接设计缓存、测试框架或全局状态校验器。先回答：

1. 哪些运行时事实存在多个可写表示；
2. 哪些非法状态目前可以进入 committed state；
3. 哪些验证真正昂贵，昂贵发生在读取、lowering、RuleBook、执行还是产物；
4. 哪些现有验证仍是现行契约，哪些只是历史证据；
5. 首批代码改造做哪几件事能同时降低漏检和验证成本。

## 2. 阶段完成后的具体结果

完成后必须得到一份可以直接指导后续执行卡的审计报告，而不是笼统建议。报告至少
包含：

### 2.1 状态权威矩阵

每一行必须记录：

- 领域和事实名称；
- 当前所有表示位置；
- 当前生产读者和写者；
- 建议的唯一权威所有者；
- 其他表示属于派生视图、索引、审计副本还是应删除的重复；
- 合法的事务内临时不一致；
- committed state 必须满足的不变量；
- 当前是否可构造并提交非法状态；
- 影响范围和风险等级；
- 后续建议阶段。

至少审计：

- `BattleState` / `UnitState` / `Snapshot` 的递归不可变性和别名边界；
- HP 与单位 active/defeated/removed 生命周期；
- 状态粗索引、完整状态实例、modifier 展示数据；
- shield instance 与面板护盾汇总；
- action value、timeline 和 queue 视图；
- skill point、wave、phase/window 等 battle 级事实；
- summon entity、owner/summoner/team/kind/status 与各索引；
- halo 父关系、成员清单、投影状态和动态值；
- 原始事件、dispatcher 事件、transition 事件和 callback 派生事件；
- scenario/build assembly 进入 UnitState 后的权威与审计副本。

### 2.2 非法状态入口矩阵

不能只列验证器能发现的问题。必须定位：

- 直接模型构造；
- JSON codec / snapshot load；
- 通用 MutationReducer；
- 原子提交；
- scenario build；
- spawn/remove/status/queue/timeline 等领域入口；
- dispatcher 和 scheduler 编排。

每个入口说明当前校验、缺失校验、失败是否保持 state unchanged，以及错误是否被
错误归类为游戏 blocked。

### 2.3 验证成本矩阵

每个活跃或高成本验证器至少记录：

- 文件和当前职责；
- `fast/direct/catalog/full/historical` 建议分类；
- 是否读取 TBGD；
- 是否调用完整 `TBGDLowering.build()`；
- 是否构建 RuleBook；
- 是否重复构建；
- 是否写完整 IR、coverage、fidelity、transition 或 replay 大产物；
- 静态文件体积；
- 可在低成本下测量时的耗时与峰值；
- 是否硬编码历史 gap、固定样例或旧验收语义；
- 是否已有更窄谓词可以替代；
- 建议保留、拆分、共享、归档或判无效。

不要求 S0 动态运行所有验证。无法低成本测量的项必须标记 `not_measured`，禁止
推测数字。

### 2.4 首批实施优先级

报告最多给出三个首批改造项。每项必须说明：

- 根因；
- 为什么优先；
- 精确触达文件和关键符号；
- 预期移除的非法状态空间或重复成本；
- 不应顺带修改的相邻范围；
- 需要何种正例、负例和资源证据；
- 建议模型、推理等级和执行模式。

如果一个建议仍过大，必须继续拆分，不得把多个领域塞进同一张卡。

## 3. 本阶段只做

- 阅读当前活跃生产代码、现行工作流文档和代表性验证器。
- 使用 CodeGraph 获取符号、调用链和影响范围。
- 使用静态命令统计验证器数量、体积、完整 lowering 调用和聚合关系。
- 只运行明确低成本、无需完整 lowering 的探针；运行前先确认入口。
- 利用已有 P7/P8/R1 报告记录重验证 OOM 或未证明事实。
- 新增本阶段审计报告。
- 必要时修订本卡中的事实描述，但不能改变总目标。

## 4. 本阶段不做

- 不修改 core、systems、rules、tbgd、scenarios、equipment、builds 或 UI。
- 不新增 validator registry、缓存、runner、完整性 hook 或生产数据类型。
- 不重写或删除任何旧验证器。
- 不运行完整 TBGD lowering、完整 RuleBook、P1-P8 聚合或 `validate_v0_209`。
- 不用小型 fixture 冒充 catalog 资源测量。
- 不更新 P8 checklist。
- 不提交 Git。
- 不编写 VG-S1 以后阶段的生产实现。

## 5. 重点代码边界

必须审查但不修改：

- `core/model.py`
  - `UnitState`
  - `BattleState`
  - `Snapshot`
- `core/unit_state_codec.py`
- `core/reducer.py`
  - `MutationReducer.apply_all_result`
- `core/atomic_commit.py`
  - `finalize_selected_execution_graph`
- `core/snapshot_contract.py`
- `systems/unit_lifecycle.py`
- `systems/status.py`
- `systems/summon_runtime.py`
- `systems/summon.py`
- `systems/event_dispatch.py`
- `systems/scheduler.py`
- `systems/queue.py`
- `systems/timeline.py`
- `systems/wave.py`
- `scenarios/build_state.py`
- `tbgd/lowering.py`
- `tools/validate_p7_current_tree_shared_regressions.py`
- 当前最大的 P8、P4、P3、P2 验证器及其直接聚合器。

若审计发现其他直接调用者，可以纳入；禁止借机扫描旧 v7 或无关 UI。

## 6. 目标与证据映射

| 目标 | 允许通过 | 必须判未完成 | 证据 |
|---|---|---|---|
| 权威事实清晰 | 每个重点事实只有一个建议权威所有者，派生表示有同步/重算语义 | 只列字段、不判断权威归属 | authority matrix |
| 非法入口可定位 | 每个高风险非法状态能定位到具体构造或提交边界 | 只说“增加测试” | invalid-state entry matrix |
| 提交边界完整 | 明确区分 mutation 校验、领域不变量和全局完整性 | 把所有校验塞进每动作全局扫描 | commit-boundary analysis |
| 成本有证据 | 静态数量完整；动态数字仅来自实际轻量测量 | 猜测全量耗时/内存 | validator inventory |
| 历史语义可识别 | 至少定位现有聚合器中的固定旧 gap/旧谓词 | 默认把旧脚本失败视为生产失败 | stale-contract matrix |
| 下一步可执行 | 最多三个窄改造项，可直接继续写卡 | 建议仍是“大规模重构验证系统” | prioritized recommendations |

## 7. 结构化审计结论

报告必须明确给出：

```text
state_authority_matrix_complete
committed_state_integrity_gap_located
external_alias_mutation_boundary_classified
domain_invariants_not_global_scan
validator_inventory_complete
full_lowering_call_sites_counted
shared_rulebook_prototype_assessed
stale_validation_contracts_located
dynamic_measurements_are_observed_only
first_implementation_batch_bounded
production_behavior_changed=false
heavy_validation_run_count=0
```

任何值为 false 时，本卡不得进入 `ready_for_review`。

## 8. 重点负例思考实验

S0 可以使用最小内存对象或静态调用链证明以下状态是否可构造，但不得写正式验证器：

- 创建 `UnitState` 后修改传入的 flags/shield 容器。
- 显式 `active` 但 HP 为 0，或 `defeated` 但 HP 为正。
- 只修改 `statuses`，不修改 `status_details`，反之亦然。
- 只修改 summon entities，不修改 owner/servant 索引或 UnitState flags。
- halo 父关系列出成员，但投影状态缺失、重复或来源不符。
- dispatcher 已返回原始事件，调用者再次手工追加原始事件。
- candidate state 与 Mutation 一致，但领域状态整体非法。
- snapshot 字段齐全，但内部语义互相矛盾。

每项必须区分：

- 构造时已拒绝；
- reducer 已拒绝；
- 原子提交已拒绝；
- 领域 consumer 使用时才拒绝；
- 当前可进入正式 committed state。

## 9. 资源限制

- 只做静态源码读取和小型内存探针。
- 不扫描 TBGD 内容；允许读取文件清单但不得解析完整目录。
- 不调用 `TBGDLowering.build()`。
- 不构建 RuleBook。
- 不写完整 IR、snapshot、transition、coverage 或 replay 产物。
- 临时统计写入 `/tmp`，仓库只保留 Markdown 报告。
- 单个动态探针目标应在数秒内结束；出现来源读取即停止。
- 不使用并发验证。

最小检查：

```bash
git diff --check
git status --short
```

本阶段是文档和静态审计，不要求 `compileall`。

## 10. 交付物

唯一仓库交付报告：

```text
live_validation_reports/v8_vg_s0_state_authority_validation_cost_audit_ready_for_review.md
```

报告必须包含：

- 审计范围和明确未审计范围；
- 状态权威矩阵；
- 非法状态入口矩阵；
- 验证器统计与成本分类；
- 已确认问题、待测量项和非问题；
- 最多三个首批实现建议；
- 对后续执行卡顺序的建议；
- `ready_for_review` 状态。

## 11. 唯一执行清单（仅验收线程可勾）

- [x] 重点运行时事实均已确定权威所有者、派生表示和 committed invariant。
- [x] 重点非法状态均已定位构造、reducer、commit 或 consumer 边界。
- [x] 验证器数量、体积、完整 lowering 路径、聚合关系和历史语义已有静态证据。
- [x] 所有动态成本数字均来自实际轻量测量，未测项明确标记。
- [x] 首批实施建议不超过三个，且每项范围足够窄可独立制卡。
- [x] 未修改生产行为、旧验证、P8 checklist 或无关 UI。
- [x] 审计报告满足结构化谓词并提交 `ready_for_review`。
