# P7-S10 行动条与控制回合语义待验收报告

状态：`ready_for_review=true`。本报告仅索引统一验收证据，不宣告阶段完成，不修改 P7 checklist。

## 本阶段结果

- `TimelineSystem` 以 remaining action value 为统一时间线事实。速度变化使用 `remaining_after = remaining_before * old_speed / new_speed`，同时提交 speed 与 action-value 两条带 before 的 Mutation，不重置已经走过的进度。
- advance、delay、immediate action、extra action 统一进入 `TimelineAdjustmentPlan/Result`。前三者产生同构 mutation/event/settlement；extra action 明确保持普通行动值不变，不制造无意义 Mutation；未知 operation blocked/no mutation。
- 同 action value 不再按 unit id 排序。若卡片没有唯一 `timeline_priority`，只读查询会返回一组带稳定 `timeline_tie_choice_id` 的外部选择；该选择必须经过 DecisionToken 原样提交。审计详情不参与选择身份或准入，缺失、过期或伪造 choice id 均结构化 blocked。
- `SetActionDelay` 状态回调已接入统一 `TimelineSystem.adjust_action_value(operation="set")`，不再直接写绝对行动值；其 mutation/event/settlement 与 advance、delay、immediate action 使用同一契约。
- timeline candidate 统一排除 defeated、removed、off-field、backline、action-disabled 及未准入 summon。
- scheduler 在 turn begin 与 pre-action 状态生命周期后检查控制门。仍受控则提交 `pre_action → turn_end` 的可信跳过 transition；下一内部 step 完成 TurnEnd 生命周期与行动值重置，DecisionSystem 继续推进，不会停在同一 actor 的 blocked 决策点。
- 已打开决策后若状态变化导致 actor 受控，submit 路径仍保持安全 blocked/state unchanged；自然时间线跳过与提交时并发安全门职责分离。

## 结构化验证证据

主验证：

```text
python3 -m simulator_v8_clean_core.tools.validate_p7_s10_timeline_control_semantics --output-dir /tmp/p7_direct_regressions/s10
```

结果：`ok=true`、`ready_for_review=true`、`rows=6`。

验证实际覆盖：

- 中途 100→200 加速与 200→50 减速后，remaining action value 分别为 60→30→120，完成进度始终为 0.4；两次 transition 的 replay、contract、source audit 均通过。
- 同值候选由唯一结构化优先级自动选择；优先级缺失/冲突时，DecisionSystem 查询给出 typed actor choices，并经 token/submit 完成 round trip；无效显式选择 blocked。
- advance 20、delay 30、immediate action 的 remaining value 分别为 40、90、0；extra action 保持 60 且 Mutation 为零；未知 operation 不产生 Mutation。
- defeated、removed、off-field、backline、action-disabled 五类更早候选均被跳过，唯一 admitted actor 被选择。
- 一回合结构化控制状态在 pre-action 后触发 `turn.control_skipped`；没有 `scheduler.action.before`；TurnEnd 生命周期真实移除状态；3 个连续 transition 均 successor eligible、replay/contract/source audit 通过，下一次 decision ready。
- 静态边界确认不存在 `(action_value, unit_id)` 二级排序，生产状态回调也不再调用旧绝对 setter。

输出：

- `/tmp/p7_direct_regressions/s10/validation_summary_p7_s10_timeline_control_semantics.json`
- `/tmp/p7_direct_regressions/s10/p7_s10_timeline_control_matrix.json`
- `/tmp/p7_direct_regressions/s10/p7_s10_timeline_control_evidence.json`

## 直接回归与资源情况

- P7-S8 decision loop：`ok=true`，6 rows。
- P7-S9 phase machine：`ok=true`，7 rows。
- P2-S6 status control gate：低优先级串行运行，`ok=true`。旧验证已补 S8 决策授权；仍验证 submit-time control gate blocked/state unchanged，没有降低断言。
- `compileall`：通过。
- `git diff --check`：通过。
- 未运行 P1-5 或其他无关重验证；所有输出位于 `/tmp`。

## 明确未做

- 未实现状态命中概率与效果抵抗；归 P7-S15。
- 未实现独立 RNG 身份；归 P7-S16。
- 未修改 invalid queue entry 的终态；归 P7-S11。
- 未按角色名、怪物 ID 或 unit ID 写时间线特判。
- 未修改 P7 checklist，未提交 Git 检查点。
