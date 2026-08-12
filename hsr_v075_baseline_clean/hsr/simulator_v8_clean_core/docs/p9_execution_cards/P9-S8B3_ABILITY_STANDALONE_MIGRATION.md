# P9-S8B3 Ability 消费域迁移聚合说明

此文件不再是可直接执行的阶段卡。

状态：`accepted`。S8B1-R2、S8B3A、S8B3B、S8B3C 均已验收。

S8B1/S8B2 完成后复核生产调用链，确认原 S8B3 混合了三个可独立验收的边界：能力入口
拓扑与正式目录、普通动作消费、queue standalone 消费。原卡还错误假定 S8A 来源分母覆盖
怪物等全部 `AbilityTaskSystem` 消费者；实际上该分母只覆盖 P9 范围内的角色能力文件。
继续按原卡一次迁移会导致角色子能力重复执行、完整来源账本按 entry 复制，或者在没有来源图
的情况下误删怪物旧执行路径。

## 严格执行顺序

S8B3A 的目录预检又发现 S8B1 当时只证明了少量正式 slice，没有证明角色 ability 的旧 task
lowering 完整保留 S8A 子树。先执行根因修复，再进入迁移：

1. `P9-S8B1-R2_FORMAL_TASK_TREE_COMPLETENESS.md`
2. `P9-S8B3A_ABILITY_INVOCATION_FORMAL_CATALOG.md`
3. `P9-S8B3B_ACTION_CALLBACK_MIGRATION.md`
4. `P9-S8B3C_STANDALONE_QUEUE_MIGRATION.md`

修复卡及三张迁移卡全部验收后，才能勾选总计划中的 P9-S8B3。

## 边界划分

| 子阶段 | 唯一生产结果 | 明确不承担 |
|---|---|---|
| S8B3A | 角色能力入口/嵌套关系和一次性正式图目录 | runtime 执行 |
| S8B3B | 普通角色动作只由共享任务图执行 | queue standalone、status callback |
| S8B3C | queue standalone 复用同一目录和执行器 | status callback、跨事件最终运输 |

## 角色范围边界

- `action_root`、`nested_only`、`standalone_root`、`unbound_definition` 是类型化的调用角色，
  不能由 runtime 读取 source trace、能力名称、子节点数量或文件路径推断。完整定义只有从真实
  生产者根节点可达时才进入正式执行目录。
- P9 角色阶段只要声明正式图权威，缺 entry 或 graph 必须 fail-closed，绝不回退旧任务树。
- 怪物、怪物召唤物、关卡和其他尚未建立完整控制流来源图的内容域保留为明确的
  `external_content_dependency`。它们可以暂时使用已有执行路径，但不得被计入 P9 角色闭合，
  也不得阻止角色域消灭第二套控制解释器。
- 全局删除 AbilityTaskIR 旧拓扑字段要等全部消费域都有同等来源权威；S8B6 只清除 P9 角色域
  的旧回退和双写依赖，并列出外部内容域剩余账本。

## 聚合通过条件

- B3A、B3B、B3C 均有已验收检查点。
- 角色动作入口不会把嵌套 phase 当作并列 root 重复执行。
- TriggerAbility 唯一关联 action 内嵌 phase 或 standalone graph，歧义时在 compiler blocked。
- 一个 RuleBook 只安装一个与其 Canonical IR 完整一致的 formal catalog；来源账本只合并一次。
- 角色普通动作与 queue standalone 都只消费 S8B2，共享失败原子性和 graph-qualified 投影。
- P9 角色域旧控制解释器回退为零；外部内容域保留项有类型化范围和后续 owner。
