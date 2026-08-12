# P9-S8B4B 状态 Callback Runtime 迁移验收报告

状态：`accepted`

## 结论

角色正式状态 callback 已从旧递归解释路径迁移到 S8B2 共享任务图执行器。状态 callback 系统只保留
领域叶节点、条件、数值和目标适配；节点顺序、分支和目标作用域由共享执行器负责。外部装备、怪物和
全局状态 callback 仍走显式 legacy 路径，未知来源不会回退。随机目标、Remodifier 和嵌套能力分别
保持给 S8C、S10 和 S8B5，不在本阶段伪装成可执行。

## 五面审查

1. 来源范围：正式范围由 `mainline_avatar_ability` 与 S8B4A callback/entry/graph 目录共同确定，
   runtime 不按角色、文件、ID 或当前是否跑通选路。聚焦来源重建动态选到真实单叶、确定性 Retarget、
   RandomConfig 和 Remodifier 结构；当前审计事实为 76 条已物化确定性 Retarget、139 条随机
   Retarget deferred，不作为固定数量门。
2. 生产不变量：callback、status instance、entry、graph 和 formal task 身份在第一条 mutation 前
   核对；未准入任务在 hook 边界阻断。图失败返回入口 state，并清空 mutation、event、RNG 和成功
   settlement。可变 damage-window ledger 使用暂存副本，只有整个 callback 组成功后才提交。
3. 正式调用者：事件派发等普通入口均汇合到 `StatusCallbackSystem.execute`，属性区间 watcher 唯一
   使用 `execute_callback_id`；两者最终共享 `_execute_callback` admission。CodeGraph 未发现角色
   正式路径直接调用旧 child runner；旧 `_execute_task` 只服务显式外部 legacy 路径。
4. Gap 归属：随机选择与随机目标归 S8C，Remodifier 状态查询归 S10，TriggerAbility 与跨入口
   active context 归 S8B5，legacy 拓扑退役归 S8B6。合法空目标与目标解析失败保持不同结果，未产生
   混合“后续处理”桶。
5. 验证独立性：主验证从真实角色来源动态选择当前生产已准入的图，不手拼第二套拓扑。领域叶执行
   仅在运输探针中替换为无副作用适配，以证明共享图调度，不冒充真实角色完整执行；生产失败原子性、
   两个公开入口和外部 legacy admission 由独立最小反例覆盖。

## 验证结果

- 聚焦主入口最终业务结果：`ok=true`，11/11 谓词通过。
- 墙钟 12.50 秒，外层峰值 RSS 343,704 KiB；evidence 2,954 bytes。
- 完整 Canonical IR build 0 次；来源 snapshot、control catalog 和聚焦 materialization 各 1 次。
- 验证器最终 380 个非空行，达到目标并低于 430 行硬上限。
- `compileall`、`git diff --check` 通过；未运行历史阶段聚合或无调用链 direct。

首次主入口为 `ok=false`：正例选择了生产上已 blocked 的 `StackProperty`，且 Retarget 测试替身未接收
新增的关键字上下文。集中修正为“真实来源且生产已准入”的单叶选样，并让替身接受完整调用形状后，
同一业务入口通过。通过后仅抽取重复的图节点查询并收敛排版到 380 行；该等价验证代码整理只复跑
`compileall` 与 diff，没有为取得重复绿灯再次扫描来源。

## 流程反馈

结构存在不能作为可执行正例，验证选样必须先经过与正式 runtime 相同的 production admission；否则
验证器会把诚实 blocked 误报成实现失败。执行卡预检也必须把“节点物化状态”和“对应领域任务准入”
做交叉核对，不能只统计图节点。测试替身若位于领域适配边界，必须接收完整的生产调用形状，包括新增
的作用域关键字；更优先替换最窄的领域叶，不替换共享执行器或顶层 admission。

本验证器验收后冻结为 `historical_evidence`。后续只在 status callback 图消费契约本身变化时提取
最小 active direct，不把本阶段来源扫描加入常规回归。
