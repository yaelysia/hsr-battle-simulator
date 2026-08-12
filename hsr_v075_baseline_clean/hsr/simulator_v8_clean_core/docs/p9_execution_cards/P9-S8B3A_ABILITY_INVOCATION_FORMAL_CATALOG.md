# P9-S8B3A 能力入口拓扑与正式图目录执行卡

## 执行配置

- 硬前置：P9-S8B2 检查点 `f3e7a80`，以及
  `P9-S8B1-R2_FORMAL_TASK_TREE_COMPLETENESS.md` 已验收。S8B3A 预检发现的正式任务子树
  缺失必须先在 lowering 根因处清零，不能在本卡列为允许 graph gap。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 本卡只建立调用关系和正式目录，不改变 runtime 行为。
- 开工起点：`TBGDLowering._avatar_action_binding`、`_link_trigger_ability_graphs`、
  `task_graph_materializer._materialize`、`TBGDLowering.build_character_task_graph_catalog`。

## 修改前闭合地图

| 权威 | 已确认事实 |
|---|---|
| 来源分母 | S8A 的 80 份角色/共享能力来源与 10,113 条控制流责任记录 |
| 动作入口 | 直接 action binding 是 root；仅被 TriggerAbility 发现的定义不是并列 root |
| 子能力 | 同一 action 内唯一 phase 优先；否则唯一 standalone graph；歧义或缺失 blocked |
| 正式 entry | 每个已选择 phase 的真实非空 callback 恰有一个 graph entry |
| 外部内容 | 怪物、召唤怪物、关卡及装备来源不属于本卡分母，不得伪装为角色目录缺口 |
| 构建成本 | 完整来源 snapshot、控制目录、查找索引和来源账本各构建一次；entry 流式物化 |

修改前基数预检还确认：角色任务当前只使用 `OnStart`，但生产实现不得写死该事实；callback
集合必须从类型化任务实时生成。全等级 action task 数量较大，因此禁止按 entry 重建控制目录、
模板索引、定义索引或复制完整来源账本。

## 阶段目标

1. 为 `AbilityPhaseIR` 增加严格调用角色：`action_root`、`nested_only`、`standalone_root`、
   `unbound_definition`、`non_gameplay_noop`、`external_legacy`。角色 lowering 根据 S1 类型化 binding、
   已解析队列生产者和类型化调用边计算可达闭包；目录中有任务但没有生产者或调用者的定义必须保留为
   `unbound_definition`，runtime 不得因其存在就猜测入口。没有 gameplay task 的真实 phase 只能是
   明确 no-op，不能造空图。
2. TriggerAbility lowering 保存唯一的类型化目标：同 action 的 phase 或 standalone graph。
   两者互斥；缺失、同类重复、跨类型冲突均 blocked。不得以 ability 名称作为 runtime 查询键。
3. 建立批量 ability formal catalog API。它只接收一个已 lower 的 Canonical IR 视图，选择其中
   三种正式调用角色，按 phase/callback 流式物化全部 entry。
4. 批量 API 在开始前只构建一次完整来源账本、source digest、控制节点、模板、引用和定义索引；
   最后只执行一次双向来源链接归并。禁止循环调用现有单 slice API。
5. `TBGDLowering.build()` 在全部 ability task、定义和 TriggerAbility 关联完成后调用批量 API，
   将唯一 `formal_catalog` 安装进最终 Canonical IR。截断、重复或未覆盖已声明正式 phase 时
   Canonical 构造直接拒绝。
6. 单 slice API 保留为聚焦工具，但复用同一 prepared materializer；不得保留第二套物化规则。
7. 本卡不让 runtime 消费新字段；旧行为保持不变，留给 B3B/B3C 原子迁移。

## 生产不变量

- 正式 phase 的每个非空 callback 必须恰有一个 entry；`non_gameplay_noop` 和没有任务的 blocked
  standalone 不造空图，且不能借空集谓词冒充正式 graph。
- `nested_only` phase 不得出现在动作 root ledger；`action_root` 不得因同时被引用而降级。
- 定义目录不是调用入口分母。只有动作根、已解析的独立根及其类型化可达闭包进入 formal catalog；
  `unbound_definition` 必须保留来源，但不得生成 entry。
- graph 中每个 node 仍反查到同一 raw occurrence；不同 level 可以有不同正式 node，但共享同一
  来源 occurrence，不得按名字或当前顺序合并。
- entry 或 graph 构造失败时整个 formal catalog 不安装；不得返回“完整”标记的截断目录。
- 来源账本与 entry 数量的对象规模为 O(source + graph)，不能是 O(source * graph)。

## 允许修改

- `rules/ir.py`、`rules/task_graph.py`（仅调用角色和 ability 引用闭合所需）
- `tbgd/lowering.py`
- `tbgd/task_graph_materializer.py`
- 对应导出文件、一个聚焦验证器和本阶段报告

若需要修改 runtime、status/event 域，或需要第二种正式目录实现，返回 `plan_mismatch`。

## 验收谓词

```text
ability_phase_invocation_role_is_typed=true
action_root_and_nested_phase_are_not_conflated=true
unbound_definitions_are_not_formal_entries=true
trigger_ability_target_is_unique_and_typed=true
formal_phase_callback_denominator_complete=true
formal_catalog_installed_once=true
control_flow_source_scan_count=1
formal_catalog_build_count=1
complete_source_ledger_merge_count=1
complete_source_ledger_not_copied_per_graph=true
limited_catalog_cannot_masquerade_as_complete=true
external_content_not_claimed_by_character_catalog=true
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b3a_ability_invocation_formal_catalog.py`。
- 真实来源动态选择一个“root 调用 action 内 phase”的闭环和一个唯一 standalone 闭环；用至少
  两个 entry 证明批量目录，不固定角色、技能、ID 或文件。
- 独立 raw oracle 核对直接 binding、嵌套 TriggerAbility 和 callback 分母；不能复用生产选择函数。
- 只运行 import smoke、compileall、一个最小构造负例、唯一主入口和 `git diff --check`。
- 预算：60 秒、640 MiB、256 KiB evidence、验证器目标 360、硬上限 420 非空行；完整 build 为 0。
  本卡在 70% 硬上限处已复核范围；动作 root/nested 与 queue standalone 两个真实纵切均不可删除，
  未增加第二个 CLI、重复 matrix 或完整目录 dump。
- 预检或主入口发现 source×entry 复制、第二次来源扫描，或无法在 45 分钟形成双 entry 纵切，
  立即停止，不提高预算。

## 唯一执行清单

- [x] 调用角色和 TriggerAbility 目标成为类型化 compiler 权威。
- [x] 批量 formal catalog 单次准备、流式物化、单次账本归并完成。
- [x] Canonical/RuleBook 的正式目录安装和完整性闭合。
- [x] 唯一主验证与资源门通过，完成验收。
