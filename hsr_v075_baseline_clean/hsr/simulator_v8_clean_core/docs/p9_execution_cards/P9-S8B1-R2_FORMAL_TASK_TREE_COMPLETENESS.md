# P9-S8B1-R2 正式能力任务树完整性修复卡

## 为什么必须先修复

S8B3A 开工前的全目录窄预检证明，新任务图物化器可以处理来源图，但角色能力的旧
lowering 只递归了条件分支和一种固定次数循环。通用任务列表、模板展开、混合控制节点等
真实子树仍会丢失，导致正式任务拓扑小于 S8A 已验收的来源拓扑。

这不是 runtime 迁移问题，也不能在验证器中把缺失子节点列为允许 gap。若继续 S8B3A，
正式目录会把不完整任务树当作输入。因此本卡是 S8B3A 的硬前置，只修复 compiler 投影。

## 执行配置

- 基线：P9-S8B2 检查点 `f3e7a80`，并保留当前尚未验收的 S8B3A compiler patch。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 精确起点：`TBGDLowering._lower_ability_phase_tasks`、
  `TBGDLowering._lower_ability_task_tree`、S8A `CharacterControlFlowContractCatalog`。
- 不读取旧 runtime 验证器，不扫描怪物、装备或状态回调消费域。

## 修改前闭合地图

| 项目 | 本卡权威 |
|---|---|
| 来源分母 | S8A 完整目录中，从 P9 角色 gameplay ability callback 根可达的任务型来源发生及其传递模板子树 |
| 子节点权威 | S8A 节点的类型化 branches 与已唯一解析的 template reference；不得再按少数 opcode 名称猜子字段 |
| 原始 payload | 对应来源路径和 JSON path 指向的真实 task 对象；共享模板只读取 S8A 已解析到的真实文件 |
| 正式输出 | 同一生产 `_lower_ability_task_tree` 生成的 `AbilityTaskIR` 父子拓扑及既有 effect/condition 引用 |
| 身份 | 来源发生身份与正式 task 实例身份分离；同一模板被两处引用时形成两个实例，但反查同一来源 |
| 非本卡内容 | invocation role、正式多 entry 目录归 S8B3A；动作/queue 消费归 S8B3B/C；runtime 不变 |

修改前预检已确认至少存在 `LoopExecuteTaskList -> TaskList -> IncludeTaskListTemplate` 的真实
丢失链。禁止把该单例写成专属修复；完成集由上述完整可达分母动态生成。

## 阶段目标

1. 建立一次性、可缓存的角色正式任务来源上下文：复用 S8A 完整目录的控制节点、branch、
   template 定义和唯一引用；共享模板文件每个最多读取一次并核对来源指纹。
2. 根回调集合从真实 ability 对象中的类型化 task list 动态发现；不得继续用固定的
   `OnStart/OnAttack/OnHit/OnEnd` 列表定义完整分母。空列表不造空 entry，未知同级类型化
   task list 不能静默遗漏。
3. 正式角色 ability task lowering 以该上下文递归全部类型化分支，而不是只识别
   `PredicateTaskList` 和某个循环名称。新增真实 family 时，只要 S8A 已类型化其 branch，
   lowering 就自然继承，不增加 family 特判。
4. 分离正式实例路径与 raw JSON path。普通嵌套保持真实顺序；模板每次引用形成独立实例路径，
   但每个子 task 的 `IRSource` 必须回到模板文件内的真实记录。
5. 缺失控制节点、悬空 child、模板缺失/歧义/循环、来源路径或指纹冲突必须在生产 lowering
   边界 blocked/fail-closed，不能生成截断后仍可物化的父节点。
6. 保持现有 condition、target、effect 和 decoded dynamic lowering 为唯一语义实现；本卡只
   补完整拓扑，不复制 effect payload，不改变 admission 结论。
7. 外部域继续走其既有 lowering。怪物、装备、状态回调不会因本卡被宣称迁移或完整。

## 生产边界必须拒绝

- S8A branch 声明了 child，但正式任务树找不到或少投影该 child。
- 正式任务额外声明 S8A branch 未拥有的 child，或 child 的父身份不一致。
- 同一正式实例出现重复 task ID；同一模板多次引用被错误合并为一个实例。
- child 的 source path、JSON path、family 或内容指纹与 S8A 来源不一致。
- 未解析模板仍展开任意候选，或模板环导致递归继续。
- 正式角色来源脱离 S8A 完整 snapshot；限量来源冒充完整任务树。

任一矛盾都不能靠验证器白名单、允许 blocked 数或按文件顺序取第一项通过。

## 允许修改

- `tbgd/lowering.py`
- 为精确类型或导出所需的最小 `rules/ir.py` / `tbgd/__init__.py`
- 一个聚焦验证器和本阶段报告
- 当前 P9 计划、执行卡索引与流程文档的必要修订

不得修改 runtime、`systems/task_graph.py`、状态系统、事件系统或 scenario。若拓扑修复要求
改变 S8A 的来源分类，返回 `plan_mismatch`，不能在本卡顺手改 S8A。

## 验收谓词

```text
formal_ability_task_reachable_denominator_non_empty=true
root_callback_denominator_complete=true
every_reachable_source_task_has_one_formal_instance_per_reference_path=true
every_formal_child_is_owned_by_one_s8a_branch=true
all_s8a_branch_children_are_projected=true
template_instance_identity_and_source_identity_are_separate=true
local_document_and_shared_templates_resolve_from_s8a=true
template_missing_ambiguous_and_cycle_fail_closed=true
source_path_json_path_family_and_fingerprint_match=true
condition_target_effect_lowering_not_duplicated=true
external_content_behavior_changed=false
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

## 验证与预算

- 唯一主入口：`validate_p9_s8b1_r2_formal_task_tree_completeness.py`。
- 一次构建 S0/S8A 来源上下文；随后按唯一 ability definition 流式投影并立即对账，不按角色
  等级重复保留相同 raw 结构，不构建完整 Canonical IR 或 RuleBook。
- 独立 oracle 从 S8A branch/template 引用重建可达 task 分母；不得调用生产递归辅助函数反推。
- 最小负例各一条：少 child、额外 child、模板歧义/环、来源篡改、模板双引用实例合并。
- 预算目标：45 秒、640 MiB、256 KiB evidence、验证器 360 非空行；达到硬上限 70% 时先
  收缩保留证据，不压缩代码规避预算。
- 只运行 import/compileall、最小构造负例、唯一主入口、`git diff --check`。不跑 S8A/S8B1
  历史主入口，不跑 full lowering 或 runtime direct。

## 唯一执行清单

- [x] 正式角色任务 lowering 改为消费 S8A 类型化子图权威。
- [x] 全部可达根回调、普通分支和模板子树逐项闭合，实例身份与来源身份分离。
- [x] 拓扑矛盾在生产边界 fail-closed，外部域和 runtime 不变。
- [x] 唯一主验证及资源门通过，已由规划/验收线程验收。
