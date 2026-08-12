# P9-S8B5B 状态 TriggerAbility 目录准入执行卡

## 执行配置

- 硬前置：P9-S8B5A 已验收并提交。
- 推荐：5.6 Sol / `high` / 普通聚焦。
- 唯一权威：角色 ability phase 的正式调用角色与 nested catalog 可达闭包。
- 精确起点：`_link_status_trigger_ability_graphs`、`_assign_character_ability_invocation_roles`、
  `_materialize_ability_entries`。
- 最早纵切：一个真实状态 TriggerAbility 的唯一目标 phase 从 `unbound_definition` 变为
  `nested_only`，并生成一个不可作为 root 的 formal entry。

## 闭合地图

| 项目 | 本卡裁决 |
|---|---|
| 来源分母 | 完整角色状态 callback 中全部类型化 TriggerAbility task 及其唯一 linked phase/standalone graph |
| 可达角色 | `mainline_avatar_ability` callback 的类型化调用边可令目标 phase 成为 `nested_only` |
| admission 分离 | 父 callback/task blocked 只阻止 runtime，不能删除目标定义或把父项提升为 executable |
| 外部内容 | 装备、怪物和全局 callback 不进入角色 nested phase 分母 |
| runtime | 本卡不执行状态 callback 或子能力 |

## 阶段目标

1. 调用角色分配同时读取 ability task 和角色状态 TriggerAbility 的已类型化调用边；不按 ability 名称
   在 runtime 或 materializer 重新发现目标。
2. 每个唯一目标 phase 保留来源并归为 `nested_only`；它不得成为 action/queue root。缺失、重复、
   跨来源歧义或外部内容混入必须在 catalog 前 fail-closed。
3. 正式目录为这些 nested phase 的实际非空 callback 生成 entry；blocked 状态 callback/task 保持原
   coverage，不以目录存在冒充真实 gameplay executable。

## 不做与停止条件

- 不修改共享执行器、ability/event/status runtime 或事件准入。
- 不放宽现有 callback/task blocker，不实现随机或状态生命周期。
- 若真实调用边还缺类型化目标，返回 S8B3A/S8B4A `plan_mismatch`，不能用名称扫描补 runtime。

## 允许修改

- `tbgd/lowering.py`。
- 必要时 `tbgd/task_graph_materializer.py` 仅做既有 nested role 消费。
- 一个聚焦验证器、报告和规划状态文档。

## 验收谓词与预算

```text
all_status_trigger_ability_links_are_typed=true
status_linked_phases_are_nested_only=true
status_linked_phases_are_not_root_entries=true
blocked_parent_does_not_delete_nested_definition=true
blocked_parent_is_not_promoted_to_executable=true
external_content_not_claimed_by_character_catalog=true
runtime_behavior_changed=false
full_canonical_ir_build_count=0
```

- 独立 raw/source 分母与生产类型化链接对账；动态数量只记报告，不写固定门。
- `compileall`、一个构造负例、唯一主入口、`git diff --check`；不重跑 B4A。
- 预算：35 秒、640 MiB、128 KiB evidence；验证器目标 260、硬上限 330 非空行。

## 唯一执行清单

- [ ] 角色状态调用边纳入 phase 可达闭包。
- [ ] nested entry 完整且不提升父 callback/task admission。
- [ ] 外部内容和歧义 fail-closed。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
