# P9-S8B5B 状态 TriggerAbility 目录准入验收报告

## 结论

P9-S8B5B 已通过验收。角色状态回调中的真实 `TriggerAbility` 目标定义现已进入正式 nested 目录，
但父状态链仍被既有事件、随机和状态生命周期缺口阻断；本阶段不宣称真实角色 gameplay 已执行。

## 完成结果

- invocation role 可达闭包新增角色状态调用边，同时继续复用动作与队列的同一闭包算法。
- 只接受 `mainline_avatar_ability` 回调指向同文件 `mainline_avatar` standalone graph；丢失、错归属、
  重复身份或 phase/graph 账本不一致均在目录物化前失败。
- blocked 父 callback/task 只贡献定义可达性，不改变自身 coverage、blocker 或 runtime admission。
- 未修改 materializer、RuleBook、ability、event、status 或其他 runtime 文件。

## 五面验收

| 审查面 | 结果 |
|---|---|
| 来源范围 | 完整控制节点目录独立得到 8 条状态 TriggerAbility，和 8 条类型化任务逐来源一致 |
| 生产不变量 | 回调归属、同文件目标、graph/phase 账本与重复身份均由 production helper fail-closed |
| 正式调用者 | 完整 lowering 调用点已传入 status callback/task；实际 ability catalog 物化 6 个 entry |
| gap 归属 | 8 个父项仍 blocked；事件/随机/生命周期分别保留给 S8C、S9、S10，runtime 运输归 S8B5C |
| 验证独立性 | 分母来自控制节点，不由已链接任务反向定义；人工 runtime diff 审查不进入自动总门 |

## 验证结果

- 8 条 raw 来源与 8 条类型化调用边一一对应。
- 8 条调用边归并为 6 个唯一 `nested_only` phase 和 6 个 materialized entry。
- blocked parent 数为 8，调用角色分配前后其 coverage 与 blocker 完全一致。
- 缺失目标负例在目录前失败；外部 callback 不能把角色 phase 认领为 nested root。
- 最终主入口 8/8，通过；完整 Canonical IR build 0 次，materialization prepare 1 次。
- 墙钟约 10.88 秒，峰值 RSS 368,240 KiB，evidence 11,013 bytes。
- 验证器 298 个非空行，低于 330 硬上限；达到软复核线后确认没有重复入口或重复业务矩阵，
  其主要体积用于单次完整来源分母和实际 materializer 纵切。验收后冻结为 `historical_evidence`。
- `compileall`、聚焦生产负例和 `git diff --check` 通过。

首次运行在来源扫描后发现最小 `CanonicalIR` fixture 漏传必填 `version`，未进入业务谓词；补齐公开
构造契约后唯一最终运行通过。流程已新增“重扫描前先做零来源构造与调用形状 smoke”规则。

## 后续边界

下一阶段只能执行 P9-S8B5C，消费已经验收的 continuation 和 nested catalog；不得在运输阶段重写
目录角色、任务图身份或事件/状态领域语义。S8B5 聚合项继续保持未完成。
