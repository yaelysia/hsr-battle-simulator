# P9-S8B2 通用原子任务图执行器执行卡

## 执行配置

- 对应问题：P9-I08；原 P9-S8B 的执行语义权威部分。
- 硬前置：P9-S8B1 已验收并提交检查点。
- 推荐：5.6 Sol / `xhigh` / 普通聚焦。
- 本卡只建立领域中立执行器，不迁移动作、状态或事件系统。
- 开工只读：本卡、S8B1 公共模型和查询、`core/model.py`、`core/reducer.py`、
  `core/transition_outcome.py`。不得阅读 ability/status 的旧控制流实现作为复制模板。

## 闭合地图

| 项目 | 本卡权威 |
|---|---|
| 输入 | S8B1 已准入任务图、不可变入口上下文、领域 leaf hooks、精确 reducer |
| 输出 | 单一任务图执行结果：候选状态、mutation/event/RNG/settlement、节点投影、blocked 原因 |
| 原子边界 | 从 root 进入到选中路径完成；任一选中节点失败则回到入口状态并清空正式结果通道 |
| 控制权威 | 有序序列、确定性分支、固定/条件/目标迭代、template frame、子图调用和调用栈 |
| 领域边界 | hook 只求值或执行一个 leaf；不得选择 child、递归图或自行提交整段事务 |
| 后续调用者 | S8B3 ability/standalone 和 S8B4 status callback |

## 阶段目标

1. 新增单一通用执行器，消费 S8B1 IR，不读取 raw、S8A catalog 或领域旧 task 字段。
2. 执行器按图中稳定顺序处理：有序序列、条件成功/失败分支、固定次数循环、条件循环、有限目标
   迭代、template 参数 frame 和子图调用。projectile、random、parallel、barrier 只返回精确 S8C
   blocker。
3. condition/count/target/leaf/graph resolver 通过类型化 hook 提供。hook 返回结果，不能接收 child
   runner，也不能决定控制结构的后继节点。
4. 事务使用不可变候选状态向前计算；只有完整选中路径成功才发布结果。选中路径任一失败必须返回：
   - 原入口状态；
   - 零正式 mutation、event、RNG 和成功 settlement；
   - 一个结构化失败结果和已尝试路径诊断。
5. 未选择分支中的 blocked 节点不得预先阻断已选择且合法的分支；完整图结构非法则在执行前
   blocked，二者不能混淆。
6. 子图调用维护 graph-qualified active stack；重复进入任一 active graph 均阻断，不使用固定深度
   上限。嵌套节点投影必须带图身份，不能只用局部 task id 合并。
7. 循环只能使用 S8B1 已准入的有限次数、有限目标集合或可证明进展依据；缺依据、非整数、负数、
   空转无进展均在首次 leaf 前 blocked。

## 生产边界必须拒绝

- graph/root、上下文或 hook 类型错配。
- hook 返回未知字段、状态与 mutation 不一致、伪造 graph/node 身份或可变结果。
- child runner 被领域 hook 持有或调用。
- 选中路径失败后仍泄露 mutation、event、RNG、成功 settlement 或候选状态。
- 调用环、跨图节点投影冲突、重复执行身份和无进展循环。
- 把未选择分支的领域 blocker 当作整图结构 blocker。

## 本卡明确不做

- 不修改 `systems/ability.py`、`systems/status_callbacks.py`、`systems/status.py`、scheduler、
  event dispatcher、lowering 或 Canonical IR。
- 不建立第二套 condition、target、numeric、effect 或 RNG 解释器。
- 不证明任何真实角色动作已经 executable；本卡只证明共享执行协议。
- 不实现 S8C 的随机、命中、parallel 或 barrier 合并。

## 允许修改的生产范围

- 新增 `systems/task_graph.py`。
- 最小修改 `systems/__init__.py` 和共享结果类型所在文件；如需变更 reducer，只允许注入现有接口，
  不得改变 reducer 语义。

如需修改领域消费者或三个以上未列出的生产文件，立即返回 `plan_mismatch`。

## 验收谓词

```text
one_shared_executor_owns_control_flow=true
domain_hooks_cannot_execute_children=true
selected_path_failure_is_atomic=true
unselected_blocked_branch_does_not_preblock_selected_path=true
loop_termination_is_source_admitted=true
active_graph_cycle_fails_without_depth_cap=true
executed_projections_are_graph_qualified=true
s8c_control_kinds_remain_blocked=true
production_domain_consumers_changed=false
source_scan_count=0
```

## 验证与止损

- 一个主入口：`validate_p9_s8b2_atomic_executor_core.py`。
- 使用明确标注的最小 `validation_fixture` 图证明通用协议；不得据此宣称真实内容执行完成。
- 一个控制结构一个最小正例或反例，不复制领域战斗世界，不构建 Canonical IR/RuleBook。
- 预算：10 秒、256 MiB、192 KiB evidence、验证器目标不超过 250 非空行。
- 主入口只在 API 自审、失败原子性审查和调用边界审查后运行一次。
- 45 分钟内必须形成可编译执行器，并通过“单 leaf 成功”和“第二 leaf 失败后全回滚”两个最小探针；
  否则停止，不能靠扩大 fixture 或阅读领域实现继续拖延。

## 唯一执行清单

- [ ] 通用执行器和受限领域 hook 协议完成。
- [ ] 选中路径失败原子回滚及未选分支语义完成。
- [ ] 循环、template frame、子图调用栈和图限定投影完成。
- [ ] 领域系统未迁移，S8C 范围未提前实现。
- [ ] 唯一主验证和资源门通过，提交 `ready_for_review`。
