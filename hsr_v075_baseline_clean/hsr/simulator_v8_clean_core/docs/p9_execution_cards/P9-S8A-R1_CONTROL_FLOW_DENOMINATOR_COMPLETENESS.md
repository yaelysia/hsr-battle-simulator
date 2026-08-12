# P9-S8A-R1 控制流来源分母完整性修复执行卡

> 状态：`accepted`。验收报告：
> `live_validation_reports/P9-S8A-R1_CONTROL_FLOW_DENOMINATOR_COMPLETENESS_accepted.md`。

## 执行配置

- 性质：P9-S8B1 开工前置修复；不是 S8B1 的一部分。
- 基线：P9-S8A 检查点 `e513b79`。
- 推荐：5.6 Sol / `max` / 普通聚焦。
- 本卡只修复 compiler 侧来源责任分母，不建立任务图，不修改 runtime。
- 完成本卡并重新验收前，禁止继续 S8B1。

## 阻断事实

S8B1 的修改前来源审查发现，现有 S8A 目录虽然报告 `8,651` 个直接节点且 `issues=0`，但其
分母只由预先标成 `combat_control_flow` / `simulation_sequence` 的 family 生成，没有检查同一
family 在真实对象中承担的物化角色，也没有递归类型化共享 template 的内部控制节点。

当前 raw 窄扫描确认：

- 角色 ability 文件中至少有 373 个“普通 gameplay task 同时携带子任务”的混合控制发生项：
  `Retarget` 347、`AddBuffPerform` 10、`AddModifier` 7、`Remodifier` 6、`SortTargets` 3。
- 31 个 `IncludeTaskListTemplate` 调用提供了 31 个命名 `TemplateParamSequences`，S8A 只记录
  同级字段责任，没有记录其有序子图。
- 共享任务模板中存在 5 个 `TaskTemplateFetchParamSequence`，用于回调调用方传入的命名子图；
  当前 scope 和 S8A 节点目录均无此 family。
- 共享模板内部共有一批控制、同步和混合节点；当前 S8A 只保存模板及直接 child 摘要，正式节点
  数为零，嵌套分支、template 引用和终止依据没有进入直接节点目录。

这些是来源契约漏项，不是 B1 可以用 blocked 图或验证 fixture 代替的问题。继续 B1 会把模板调用
错误地物化成“只有模板主体、没有调用方子图”的不完整任务图。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 完整分母 | 完整角色 ability snapshot，加 S8A 已声明读取的共享任务模板目录 |
| 选择规则 | 结构化 family 分类与对象物化角色共同决定；携带 gameplay 子图的 hybrid task 必须进入 |
| 输出 | 修订后的 `CharacterControlFlowContractCatalog`，包括直接节点、分支、template 内节点与义务 |
| 生产拒绝 | 未分类子任务字段、命名参数子图缺失、template fetch 无调用参数、来源或父子闭包矛盾 |
| 下游 | 修复后的完整目录作为 S8B1 唯一来源分母 |

## 阶段目标

1. 将直接控制流分母从“当前已知 control family 列表”改为两部分并集：
   - 类型化语义本身属于控制流或模拟时序的发生项；
   - 真实对象形状表明其承担子图、条件后继、目标作用域或命名子图调用职责的混合发生项。
   选择必须由生产分类器生成，不能在验证器里维护另一份白名单。
2. 为混合节点建立明确物化角色，不改变其原有 leaf gameplay 语义：
   - effect 成功后继；
   - 目标/状态作用域内的有序子图；
   - 排序后子图；
   - 经完整分支证明确属表现的延迟表现子图。
   不得把所有同 family 记录一律当控制节点；只有实际出现对应结构字段的发生项进入。
3. 将 `TemplateParamSequences` 投影为有序、按参数名区分的来源分支；每个 child 均保留真实位置，
   不能把整个字段仅记成一个“已归属”同级字段。
4. 将 `TaskTemplateFetchParamSequence` 类型化为参数子图调用节点，保存参数名和真实来源。调用点
   缺少同名参数子图时必须 blocked；不能退化为空操作。
5. 对共享 template 的完整任务树递归应用与角色 ability 相同的节点、字段、分支、引用和终止契约。
   模板定义的直接 child 摘要继续保留，但不能替代内部正式节点目录。
6. 对同步/表现节点按完整子树裁决：只有所有 descendants 均为非战斗表现且不改变时序、动作、
   状态或结算时才可排除；服务器同步、波次推进或含 gameplay descendant 的 wrapper 必须保留并
   指向精确后续阶段。
7. 目录构造边界必须拒绝：遗漏的结构 child、同一来源多重物化、跨 template 父子、命名参数
   不闭合、调用环、未知同级字段和伪造来源。不能依赖主验证事后发现。

## 允许修改

- `tbgd/character_ability_scope.py`：仅补类型化 family/物化角色分类所必需内容。
- `tbgd/character_control_flow_contracts.py`：完整分母、共享模板递归节点和分支来源。
- `rules/control_flow_contract.py`：仅在现有模型无法表达“参数子图调用/混合物化角色”时最小扩展。
- `tools/validate_p9_s8a_control_flow_source_contract.py`：迁移为新的独立完整分母核对。
- S8A-R1 审计报告，以及 S8A/S8B1 卡的前置状态说明。

若需要修改正式 task lowering、Canonical IR、RuleBook 或 runtime，返回 `plan_mismatch`；这些属于
S8B1 及后续阶段。

## 生产边界必须拒绝

- 已知 control family 全部出现但混合 child-bearing 发生项被遗漏。
- shared template 只有 template/直接 child 摘要，没有内部控制节点。
- `TemplateParamSequences` 有字段责任但没有按名称和顺序展开的 child 来源。
- `TaskTemplateFetchParamSequence` 被当 leaf、表现节点或空操作。
- 同一 family 的无子图普通记录被误分类为控制节点。
- 表现 wrapper 内含 gameplay descendant 却被整体排除。
- 完整分母由当前已实现 family 反向定义，或用当前固定数量作为通过条件。

## 验收谓词

```text
denominator_uses_semantic_kind_and_materialization_role=true
hybrid_child_bearing_occurrences_are_not_omitted=true
ordinary_non_control_occurrences_are_not_promoted=true
template_param_sequences_are_ordered_source_branches=true
template_param_fetch_is_typed_and_source_closed=true
shared_template_internal_control_nodes_are_recursive=true
presentation_exclusion_requires_descendant_closure=true
every_selected_occurrence_has_one_node_disposition=true
every_child_source_has_one_parent_branch=true
unknown_shape_fails_at_catalog_construction=true
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

当前扫描数量只写入 evidence 作为事实，不作为固定通过条件。验收器必须独立遍历 raw 对象的
结构字段与 shared template 完整树，再与生产目录逐身份比较；不得从生产目录反推分母。

## 验证与预算

- 保留一个 S8A 主入口；不新增并列长期验证器。
- 一次完整 snapshot、一次 scope、一次 shared template 读取、一次 S8A 目录构建。
- 一个 family/物化角色只保留一个最小生产反例；目录完整性只保留一份聚合差量账本。
- 不构建 Canonical IR，不运行 runtime、S8B1 或历史阶段聚合。
- 预算：30 秒、640 MiB、512 KiB evidence；验证器非空行不得超过现有 700 行预算。
- 开发中只用 `compileall` 与最小结构反例；生产自审完成后才运行一次主入口。

## 唯一执行清单

- [x] 直接分母已同时覆盖语义 family 与真实混合物化角色。
- [x] 命名 template 参数子图与 fetch 调用完成来源闭合。
- [x] shared template 内部节点、分支、引用和终止依据递归闭合。
- [x] 生产构造边界能够拒绝遗漏、伪造和父子矛盾。
- [x] 唯一主验证、资源门和代码审查通过，完成验收。
