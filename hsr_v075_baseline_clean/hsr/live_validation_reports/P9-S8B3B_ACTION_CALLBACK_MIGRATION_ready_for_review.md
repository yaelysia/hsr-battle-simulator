# P9-S8B3B 普通角色动作任务图迁移验收报告

状态：`accepted`

## 结论

普通角色动作中的 `action_root` callback 已切换为 B3A 正式目录与 B2 原子任务图执行器。
`nested_only` 只能经类型化能力调用进入；缺图、错身份、选中未准入节点、领域 leaf 失败、递归
和跨根重复通道身份均 fail-closed，不回退旧树解释器。Queue standalone 与 status callback 未提前迁移。

## 五面审查

1. 来源范围：主验证从当前角色来源图动态选择一个真实 root -> nested action，不固定角色、动作或
   文件。当前样本为 `avatar_skill:131202`，正式图已命中；因验证状态没有该角色的动态参数来源，
   以 `dynamic_hash_unbound` 诚实阻断。该结果只证明真实来源分流与无回退，不宣称该角色已可战斗。
2. 生产不变量：正式入口只接受 `action_root/nested_only` 角色；入口、图、节点、任务和回调身份逐层
   闭合。任何失败返回原 `BattleState`，mutation/event/RNG/正式 settlement 均为空。
3. 正式调用者：`core/executor.py` 现有三个动作窗口调用继续消费同一
   `AbilityTaskExecutionResult`；没有新增验证专用 core API。Queue 仍走旧 standalone 路径，状态文件未改。
4. Gap 归属：queue standalone 留给 S8B3C，status callback 留给 S8B4，跨入口上下文留给 S8B5，
   旧父子拓扑和外部内容依赖留给 S8B6；命中/随机/parallel 等节点仍由 S8C 及后续领域阶段准入。
5. 验证独立性：真实来源探针与显式 validation fixture 分栏。Fixture 只证明通用执行链，不冒充真实
   角色；中途 mutation 后递归失败仍整体回滚，嵌套 leaf 恰好执行一次。验证器不导入历史验证 helper。

## 验证结果

- 唯一主入口：`ok=true`，9 项谓词符合预期。
- 墙钟：12.21 秒；峰值 RSS：417,092 KiB；evidence：789 bytes。
- 验证器：288 个非空行，低于修订后的 300 行目标和 360 行硬上限。
- 主入口后五面审查删除了一次多余 reducer 重放；只运行 fixture、原子回滚与 hook 权威最小反例，
  未重复扫描真实来源，均通过。
- `compileall`、CLI `--help`、`git diff --check` 通过。
- 完整 `TBGDLowering.build()`：0 次；未运行 B1/B2/B3A 或历史聚合验证。

## 流程反馈

本阶段主验证一次通过，首次五面审查只发现一类设计偏差：领域 hook 不应读取第二份候选状态。
已将“共享 API 按类型化调用角色分流”和“原子 hook 不做二次 reducer”写入项目流程规范。
验证预算在主入口前按 70% 门复核并修订，没有通过压行或增加并列入口规避预算。
