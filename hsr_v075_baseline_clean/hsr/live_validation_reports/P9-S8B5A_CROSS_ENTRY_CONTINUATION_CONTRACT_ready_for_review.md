# P9-S8B5A 跨入口 Continuation 契约验收报告

## 结论

P9-S8B5A 已通过验收。该结论只覆盖共享任务图执行器的 continuation 与 child projection 契约，
不表示状态 TriggerAbility 已进入正式目录，也不表示真实角色跨 ability/event/status 链已执行。

## 生产结果

- `TaskGraphHookRequest` 自身拒绝空栈、重复活动图及栈末端与当前图不一致。
- `TaskGraphContinuation` 只能从精确类型的 hook request 派生，保留父 invocation、graph、node、
  formal task、上下文和完整活动图栈；child context 不接受调用者改写活动栈。
- `TaskGraphLeafResult` 可携带递归不可变的成功 child projection；blocked leaf 不得携带该通道。
- child projection 在 mutation reducer 前完成身份冲突预检。相同身份和内容只保留一次；同身份不同
  内容使外层事务 blocked。失败不发布 child 成功 projection，既有外层 blocked projection 仅作诊断。

## 五面验收

| 审查面 | 结果 |
|---|---|
| 来源范围 | 本阶段无来源/lowering 责任，完整 Canonical IR 构建和来源扫描均为 0 |
| 生产不变量 | continuation 构造、栈闭合、blocked 泄漏和投影冲突均在共享生产边界拒绝 |
| 正式调用者 | `ability.py`、`event_dispatch.py`、`status_callbacks.py` 均未修改；消费迁移留给 S8B5C |
| gap 归属 | TriggerAbility 目录准入归 S8B5B，跨领域运输归 S8B5C，无未归属 gameplay gap |
| 验证独立性 | 冲突 execution ID 由独立稳定公式生成；人工 diff 范围审查未伪装成自动谓词 |

## 验证结果

- 最终主入口：6/6 谓词通过。
- 直接和间接活动图环均在首条 mutation 前 blocked。
- A -> B 成功链只产生两个唯一、图限定的 projection；重复 child projection 被确定性去重。
- 冲突负例中 state unchanged，mutation/event/RNG/settlement 均为空，只有外层 blocked 诊断。
- `compileall` 和 `git diff --check` 通过。
- 最终主入口墙钟约 0.27 秒，峰值 RSS 33,688 KiB，evidence 5,305 bytes。
- 验证器 225 个非空行，低于 230 硬上限；已冻结为 `historical_evidence`，后续不继续扩写。

首次主入口仅因验证器把内部 `FrozenJSONList` 误当成 Python `tuple` 而失败；生产隔离行为正确。
最终 oracle 改为修改原输入并按公开序列内容核对。该经验已写入通用验证流程。

## 后续边界

下一阶段只能执行 P9-S8B5B。S8B5 聚合项继续保持未完成，直至 S8B5B 和 S8B5C 分别验收。
