# P9-S8B4 状态 callback 任务图迁移聚合说明

## 拆分原因

开工预检确认，生产 lowering 只安装 ability 图，状态 callback 图尚未进入正式 RuleBook；同时旧
`StatusCallbackSystem` 是一个同时承担目录选择、控制解释和多个领域 leaf 的大型消费域。直接按旧卡
施工会在同一阶段建立目录权威并迁移 runtime，无法形成最早可编译纵切，也会让验证器手装目录冒充
生产闭合。因此 S8B4 改为聚合项，不再直接执行。

## 唯一顺序

1. `P9-S8B4A_STATUS_CALLBACK_FORMAL_CATALOG.md`
2. `P9-S8B4B_STATUS_CALLBACK_RUNTIME_MIGRATION.md`

只有 S8B4A、S8B4B 均验收并提交检查点后，才允许勾选总计划中的 P9-S8B4。

## 聚合边界

- S8B4A 建立角色来源状态 callback 的正式目录，不改变 runtime。
- S8B4B 只消费 S8B4A 已安装目录，不再修改来源模型或目录选择规则。
- 没有任务的真实 callback 不伪造节点；它们由 callback 自身的空任务账本证明为无图流程。
- 怪物、装备、关卡等未进入当前角色来源图的 callback 保持明确外部内容依赖，不允许回退伪装为
  P9 角色正式路径；公共旧字段的最终退役仍由 S8B6 裁决。
- 跨事件 active stack 归 S8B5；随机、projectile、parallel 和 barrier 归 S8C。

本文件不含执行勾选项；完成状态只记录在两张子卡和总计划中。
