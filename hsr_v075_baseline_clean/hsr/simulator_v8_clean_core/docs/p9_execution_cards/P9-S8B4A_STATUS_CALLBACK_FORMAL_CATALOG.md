# P9-S8B4A 状态 callback 正式图目录执行卡

## 执行配置

- 对应问题：P9-I08；S8B4 的来源与目录权威部分。
- 硬前置：P9-S8B3 已验收并提交检查点。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 本卡不改 runtime。正式行为保持由旧状态 callback 路径承担，消费迁移严格留给 S8B4B。
- 精确起点：`TBGDLowering._lower_status_callback_task_tree`、
  `materialize_status_callback_task_graph`、`TBGDLowering.build` 中 task graph 安装点。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 完成分母 | S0 完整角色能力 snapshot 中全部状态 callback，以及每个 callback 的完整任务树 |
| 图位置 | callback、root 顺序、分支顺序和 template 展开位置形成唯一正式位置 |
| 来源位置 | 原始文件、JSON 路径、family 和文件指纹；共享 template 同一来源可出现在多个图位置 |
| 正式目录 | ability entry 与有任务的角色 status callback entry 共存于一个 Canonical IR task graph catalog |
| 无图 callback | 真实任务列表为空；保留 callback 来源并明确不创建 synthetic graph/node |
| 上游阻断 | 属性监听等上游尚未准入时，下游 callback 结构仍进入目录；blocked 只阻止执行，不得删除来源结构 |
| 外部内容 | 不在角色 snapshot 中的怪物、装备和关卡 callback 不进入本目录，保持原内容域责任 |
| 后续归属 | runtime 消费归 S8B4B；跨入口归 S8B5；旧字段退役归 S8B6；随机/时序归 S8C |

## 阶段目标

1. 角色状态任务 lowering 分离“原始来源位置”和“正式图位置”。同一共享 template 被不同 include
   展开时，来源 occurrence 可以相同，但 task/effect/condition 的图位置身份必须不同；不得覆盖、静默
   去重或因旧 source path 身份冲突阻断整个 callback。
2. 每个 callback 的 root 账本必须与其任务树双向闭合；全部非 root 恰有一个父节点，分支与 child
   顺序可从正式任务树重建。重复身份、跨 callback 子节点、悬空节点、环和不可达节点 fail-closed。
3. 新增一次准备来源上下文、一次物化账本合并的完整状态 callback 目录构建；不得逐 callback 重建
   10,113 条 S8A 来源账本。
4. 生产 lowering 安装 ability 与状态 callback 的联合正式目录。通用 limit 打开时不得把截断目录
   标记完整；现有仅 ability 的聚焦构建 API可保留，但不得继续作为生产最终目录。
5. 有任务的角色 callback 必须恰有一个 entry；任务为空的 callback 必须恰无 entry，且不创建
   synthetic task、空 graph 或伪来源。callback 已 blocked 不妨碍结构图 materialize；选中 deferred
   节点仍由共享执行器按后续责任阻断。
6. RuleBook 对状态 entry、graph 和来源返回唯一结构化结果；缺失、重复、跨 authority 或损坏身份
   fail-closed。runtime、事件、mutation、settlement 和 RNG 行为保持不变。

## 不得自行决定

- 不把无任务 callback 当成实现缺口，也不伪造 process-only 节点。
- 不把角色来源目录扩成全怪物、全装备或全关卡目录。
- 不以固定角色、callback 数量、ID、文件名或当前 hash 定义生产范围。
- 不迁移 `StatusCallbackSystem`，不删除旧 task 拓扑字段，不实现 S8C 节点。

## 允许修改

- `tbgd/lowering.py`
- `tbgd/task_graph_materializer.py`
- `rules/ir.py` 仅补状态任务能力引用和联合目录构造闭包
- 必要的 `tbgd/__init__.py` 导出
- 本卡聚焦验证器、报告和规划状态文档

若需要修改 `systems/`、core executor、RuleBook 查询语义或公共状态生命周期，返回
`plan_mismatch`，不得扩卡。

## 验收谓词

```text
status_callback_source_and_graph_positions_are_distinct=true
shared_template_expansions_have_unique_graph_positions=true
status_callback_task_topology_is_closed=true
task_bearing_character_callbacks_have_exactly_one_entry=true
taskless_callbacks_have_no_synthetic_graph=true
ability_and_status_entries_share_one_production_catalog=true
limited_catalog_cannot_masquerade_as_complete=true
status_entry_queries_are_unique_and_source_closed=true
catalog_build_prepares_source_once=true
runtime_behavior_changed=false
```

## 验证与止损

- 一个主入口：`validate_p9_s8b4a_status_callback_formal_catalog.py`。
- 独立 raw 分母按 snapshot 逐文件读取 callback 与任务字段；生产投影复用 `_lower_ability_file`，不
  复制 lowering 规则。目录正例覆盖真实重复 template 展开和真实无任务 callback，禁止固定 ID。
- 聚焦 Canonical 视图不挂载会要求完整角色卡世界的来源图目录；来源完整性由同一真实 snapshot、
  完整控制流目录和独立 raw 分母证明，生产最终安装仍由 `TBGDLowering.build` 完成。
- 每个新构造不变量只保留一个最小反例；不构建 BattleState，不运行 runtime。
- 预算：45 秒、640 MiB、256 KiB evidence；验证器目标不超过 300 非空行，硬上限 360。
- 允许一次开发诊断和一次最终主入口。若 30 分钟内无法得到完整状态目录，或发现状态任务还需要
  第二个来源权威，立即暂停并修订闭合地图。

## 唯一执行清单

- [x] 状态任务来源位置与图位置已分离，完整任务树身份无冲突。
- [x] 角色状态 callback 完整正式目录已建立并与 ability 目录联合安装。
- [x] 有任务/无任务 callback 分母均诚实闭合，外部内容未越界。
- [x] 唯一主验证和资源门通过，提交 `ready_for_review`。
