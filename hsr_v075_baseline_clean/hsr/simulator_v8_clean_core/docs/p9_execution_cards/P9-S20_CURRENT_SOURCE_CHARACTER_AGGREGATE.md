# P9-S20 当前来源角色共享机制最终聚合执行卡

## 执行配置

- 对应问题：P9-I20；机制包 M18 收口。
- 硬前置：P9-S19 已验收并形成检查点；S0-S19 的接受报告与当前源码可通过指纹关联。
- 推荐：5.6 Sol / `max` / Goal 模式。
- 理由：最终结论必须同时核对完整目录、阶段检查点、正式纵切、source gap 和完成口径，
  但不能通过重跑二十个历史验证器获得。

## 当前事实与阶段结果

S0-S17 已建立共享机制，S18 已对当前 79 条角色重算差距并选出代表，S19 已通过正式战斗
证明机制组合。最后仍需要在同一当前源码和来源指纹上，将目录事实、已接受 evidence 和正式
纵切汇合为一次性结论，防止“每阶段曾经通过”被误写成“当前完整通过”。

完成后生成 P9 当前来源最终聚合报告，并严格区分两个结论：

1. `P9-SHARED-MECHANISMS-DONE`：四类内部 gap 为零，共享机制和审计完成；允许存在已证明的
   真实 source gap，但必须列出受影响角色。
2. `current_79_character_catalog_all_executable`：只有 source gap 也为零，且 79 条角色的全技能、
   全行迹、全星魂均正式准入和被目录审计时才为 true。

本阶段是聚合和裁决，不是最后补功能的兜底阶段。

## 详细目标

1. 轻量 preflight 核对当前 Git 基线、工作区范围、来源完整指纹、S0-S19 检查点和接受报告。
   报告必须带代码指纹、来源指纹和关键产物指纹；仅有路径或 `ok=true` 不算当前证据。
2. 通过 S0 的窄投影一次性重建当前 79 条角色、共享能力及其完整 closure 状态；不得构建完整
   跨领域 Canonical IR 后再过滤。
3. 核对 S18 最终差距矩阵：四类内部 gap 必须仍为零，source gap、non-gameplay 和外部内容
   依赖的集合与当前目录一致，未知状态和漏项为零。
4. 核对 S9-S17 事件分区与当前 gameplay 事件目录：每个事件只有合法的 producer/consumer
   归属，不存在 fixture-only producer、双重身份或未归属事件。
5. 通过代码和来源指纹消费 S19 已验收纵切摘要；不重跑全部纵切。每项 proof obligation 必须
   仍对应当前生产符号和当前 manifest，过期 evidence 直接阻断。
6. 汇总逐角色结论：基础构筑、动作、被动、行迹、星魂、独立 ability、正式战斗准入和受限
   原因。不能只汇总机制族总数而遗漏受影响角色。
7. 明确列出延期的记忆、欢愉、怪物、关卡和环境内容，防止 P9 结论外推为完整游戏模拟器。
8. 生成机器可读 summary 和面向后续线程的 checkpoint 报告；执行线程只提交
   `ready_for_review`，由验收线程决定是否勾总 checklist 和建立 Git 检查点。

## 聚合原则

- 最终入口只重算“容易陈旧的当前事实”：来源、目录身份、closure 状态和 evidence 指纹。
- 已经在阶段检查点证明且生产调用链未变的深行为，通过指纹消费，不逐阶段重跑。
- 任一指纹不匹配时，先定位受影响阶段；只重跑或修复该责任阶段，不能把整个 P9 作为诊断器。
- 历史允许缺口不能成为成功条件。source gap 可以减少至零；出现新的内部 gap 必须阻断。
- 最终报告中的数量来自当次构建，不把 79、125 或历史 family 数写成生产常量。

## 本阶段不做

- 不修改 compiler、IR、RuleBook、assembler、runtime、scenario 或角色内容。
- 不修生产机制、不添加 allowlist、不新增兼容层或验证专用 core API。
- 不运行 S0-S19 全部主验证，不运行 P1-P8 聚合或完整 TBGD lowering。
- 不把共享机制完成外推为记忆、欢愉、全怪物、全关卡或 UI/推演器完成。

## 目标与证据

| 目标 | 通过条件 | 证据 |
|---|---|---|
| 基线一致 | 所有接受 evidence 与当前代码/来源指纹一致 | checkpoint manifest |
| 当前目录一致 | 目标角色、共享能力和入口集合完整且无重复 | final catalog matrix |
| 内部 gap 归零 | 四类内部 gap 均为 0 | final gap summary |
| 事件闭合 | gameplay event union 无漏项、冲突或 fixture-only producer | event aggregate |
| 纵切仍有效 | S19 每项义务仍绑定当前生产符号 | evidence linkage matrix |
| 角色结论诚实 | 每条角色均有完整准入或明确 source gap | character readiness table |
| 完成口径分离 | 两个最终布尔值按各自条件独立计算 | final summary |
| 范围无扩张 | 延期命途和内容域未被计入通过 | scope exclusions |

## 结构化通过谓词

```text
accepted_stage_evidence_current=true
current_source_fingerprint_complete=true
current_target_character_catalog_complete=true
current_shared_ability_catalog_complete=true
current_catalog_identity_conflict_count=0
lowering_gap_count=0
admission_gap_count=0
implementation_missing_count=0
validation_gap_count=0
unknown_closure_status_count=0
fixture_only_event_producer_count=0
current_event_partition_complete=true
s19_obligation_evidence_current=true
every_target_character_has_honest_readiness=true
shared_mechanisms_done_formula_correct=true
all_executable_formula_correct=true
memory_elation_and_external_domains_excluded=true
production_code_changed=false
```

## 最终结论算法

```text
P9-SHARED-MECHANISMS-DONE =
  catalog_complete
  and all_four_internal_gap_counts_are_zero
  and event_partition_complete
  and representative_obligations_proven

current_79_character_catalog_all_executable =
  P9-SHARED-MECHANISMS-DONE
  and source_gap_count == 0
  and every_target_character_full_build_and_battle_admitted
```

若第一项为 true、第二项为 false，报告必须用普通语言列明哪些角色因何种真实来源缺口仍不能
宣称完整可玩。不得把第二项 false 写成 P9 共享机制失败，也不得省略这一限制。

## 关键负例与停止条件

- 接受报告缺失、代码/来源指纹不匹配、S18 manifest 或 S19 evidence 被篡改，必须阻断。
- 当前目录新增、删除或重复入口但历史矩阵未反映，必须阻断并退回 S18。
- 内部 gap 非零、未知事件、fixture-only producer 或只有 allowlist 才能通过，必须阻断。
- source gap 没有穷尽来源证据，必须重新分类，不能进入最终允许集合。
- 聚合器通过修改生产状态、补 synthetic 入口或将失败改写为治理成功，必须阻断。
- 最终入口失败后不允许在 S20 修业务；报告责任阶段并停止。责任阶段修复验收后，才可重新
  获得一次最终运行额度。

## 拟改范围

- 新增 `tools/validate_p9_s20_current_source_character_aggregate.py`。
- 新增机器可读 summary 和 P9 最终 `ready_for_review` 报告。
- 执行线程不得修改总计划 checklist、`CODEX_HANDOFF.md` 或生产代码；这些由验收线程在通过后
  原子更新。

## 验证与资源

1. 先做不构建目录的静态 preflight：文件、schema、指纹结构、工作区和报告引用。
2. preflight 通过后，权威当前目录聚合只运行一次；失败即停止并归责，不循环重跑。
3. 完整来源只读取一次，角色窄目录只构建一次；S19 evidence 只校验，不重放场景。
4. 不输出完整 Canonical IR、RuleBook、能力图、transition 或逐阶段原始 evidence。
5. 不运行任何历史阶段主验证作为固定套餐，direct 数量为 0。
6. 预算：主入口 20 分钟、累计 25 分钟、1.5 GiB、20 MiB、900 非空验证行。
7. `compileall`、静态 preflight、唯一 S20 主验证、`git diff --check`。

## 唯一执行清单

- [ ] 当前代码、来源和 S0-S19 接受 evidence 指纹一致。
- [ ] 当前 79 条角色和共享能力目录一次性聚合完整。
- [ ] 四类内部 gap、未知状态和 fixture-only producer 全部为零。
- [ ] S19 全部 proof obligation 仍绑定当前生产实现。
- [ ] 每条目标角色均获得诚实的当前可用结论。
- [ ] 两个最终完成布尔值按独立公式计算并清楚解释。
- [ ] 主验证、资源和范围审计通过并提交 `ready_for_review`。
