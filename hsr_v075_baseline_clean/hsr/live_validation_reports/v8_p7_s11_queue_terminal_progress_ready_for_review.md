# P7-S11 队列条目终态与前进保证待验收报告

状态：`ready_for_review=true`。本报告仅作为统一验收证据索引，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- 新增一等 `QueueEntryTerminalPlan/Result`。队列条目可进入 `completed`、`cancelled`、`blocked_removed`、`waiting_window`、`retargeted`；每个 plan 记录 before/after length、retained、原因、来源和 `monotonic_progress`。
- 无效头项不再永久留队：actor 缺失/死亡/离场、target 不可选、来源状态失活、窗口过期等进入 `cancelled`；执行图 blocked/diagnostic 进入 `blocked_removed`。
- wait/retarget 只有 cancel policy 明确 `*_policy_admitted=true` 且目标/窗口有效时才可保留；policy source 仅用于审计，不影响行为。缺 typed admission 的 retarget 不会换到首个存活目标，而是取消。
- `plan_next_drain` 先处理无效头项；处理后下一合法项可在下一 scheduler step 执行。waiting entry 在目标窗口到来前不反复写同一 Mutation，也不遮挡其他 admitted entry。
- 子 action 或独立 ability graph 不是 successor eligible 时，其 Mutation 均保持不发布；父层只提交队列条目的 `blocked_removed`，并把 child outcome 作为过程证据，不继承 child diagnostic 导致无限回滚重试。
- source audit 新增真实 `terminal_remove` 操作：仍要求 QueueIntent、QueuePriority、QueueWindow 可追溯，但不伪造成功 target/window plan；改为审核 terminal disposition、blocked reason 和单调前进。
- 每个 scheduler step 最多处理一个条目，`QUEUE_DRAIN_STEP_BUDGET=1`。正常完成和异常终态都在 coverage 中报告 before/after length。
- `resolve_queue_entry` 接入 S9 phase operation admission；idle、awaiting-decision、post-action、insert-window 可处理，action-execution 等非法阶段 blocked/state unchanged。
- 来源状态与过期策略只读取正式字段；`source_status_policy_source`、policy `source_trace` 等审计字段清空后，紧凑键与 queue drain 行为均保持相同。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s11_queue_terminal_progress --output-dir /tmp/p7_review_s11
```

结果：`ok=true`、`ready_for_review=true`、`rows=10`。

验证实际覆盖：

- 无效 actor 头项先取消，队列 2→1；后续合法 action 下一步执行，队列 1→0。两步均 committed、replay/contract/source audit 通过。
- 无效 target、来源状态不存在、event-index 窗口过期三类分别产生结构化 `cancelled`，队列清空且审计通过。
- typed-admitted wait policy 将条目标记 `waiting_window`，长度不变但等待窗口发生可证明变化；窗口到来后仍无效则取消。
- typed-admitted retarget policy 只改写明确目标，下一步完成；裁剪 policy source 后行为等价；缺 `retarget_policy_admitted` 时取消，不 fallback。
- `validation:partial` child 返回非可信 outcome、0 Mutation；父层只发布一条 queue remove Mutation，终态为 `blocked_removed`，无非队列 Mutation 泄漏。
- 独立 ability graph 的首节点先产生候选 HP Mutation、后续节点 blocked 时，selected graph 原子门拒绝整个子图；正式父 transition 不发布该 HP Mutation，只终态化队列条目。
- action-execution phase 中尝试 drain 得到 `operation_not_allowed_in_phase:resolve_queue_entry:action_execution`、0 Mutation、state unchanged。
- 静态边界确认有限单步预算、四类异常 disposition 和无 first-alive retarget fallback。
- 新增审计裁剪反例：完整与清空 queue policy 来源的两个状态 compact key 相同，两个 drain plan 均可执行且行为投影一致。

输出：

- `/tmp/p7_review_s11/validation_summary_p7_s11_queue_terminal_progress.json`
- `/tmp/p7_review_s11/p7_s11_queue_terminal_matrix.json`
- `/tmp/p7_review_s11/p7_s11_queue_terminal_evidence.json`

## 直接回归与资源情况

- v0_251 队列优先级纯函数：通过；follow-up/counter、ultimate/extra-turn family order 与稳定入队顺序均保持。
- P7-S3 atomic commit：`ok=true`，9 cases。
- P7-S8 decision loop：`ok=true`，6 rows。
- P7-S9 phase machine：`ok=true`，7 rows。
- P7-S10 timeline/control：`ok=true`，6 rows。
- `compileall`、`git diff --check`：通过。
- 未运行 P1-5：该脚本已知默认写约 1.6GB 临时结果，不是普通 S11 回归入口；S11 主矩阵已直接覆盖本次触达路径。

## 明确未做

- 未新增没有真实来源的 queue family。
- 未实现无来源的随机 retarget/retry。
- 未把所有 blocked 都统一换目标或无限重试。
- 未修改 P7 checklist，未提交 Git 检查点。
